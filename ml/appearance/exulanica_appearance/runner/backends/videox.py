"""VideoX-Fun control pipelines for Qwen-Image-2512 and Z-Image, with seamless tiling. GPU only.

Imported only inside the GPU container, after every weights file has been verified. VideoX-Fun is
the reference implementation the Fun union controls' own cards point to; it is installed at a pinned
commit (``container/Dockerfile``). Its package imports every model it supports at import time, and
one of those imports, ``func_timeout`` (LGPL-3.0), serves only its dataset loaders, which nothing here
calls; a module standing in for it is registered before the import, so the LGPL package is never
installed.

Tiling, without forking VideoX-Fun (see ``runner.tiling``):

- the transformer's ``forward`` is wrapped on the instance: before each step the latent grid and the
  control latents are rolled by the schedule's offset, and the prediction is rolled back;
- the VAE's ``encode`` is wrapped so the control picture is wrap-padded before encoding and the
  latents cropped after;
- the pipeline is asked for latents, and they are decoded here, wrap-padded and cropped.

Everything loads onto the one GPU at bf16 with no offload: Qwen-Image-2512 is about 58 GB with its
text encoder, well inside 96 GB.
"""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
import types
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from exulanica_appearance.runner.tiling import shift_for_step

__all__ = ["VIDEOX_FUN_ROOT", "QwenImageFunControl", "ZImageFunControl"]

VIDEOX_FUN_ROOT: Final = Path("/opt/videox-fun")
LATENT_PX: Final = 8
PATCH: Final = 2

#: From VideoX-Fun's config/qwenimage/qwenimage_control.yaml at the pinned commit.
QWEN_CONTROL_KWARGS: Final = {"control_layers": [0, 12, 24, 36, 48], "control_in_dim": 132}
#: From VideoX-Fun's config/z_image/z_image_control_2.1.yaml at the pinned commit.
ZIMAGE_CONTROL_KWARGS: Final = {
    "control_layers_places": [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28],
    "control_refiner_layers_places": [0, 1],
    "add_control_noise_refiner": True,
    "add_control_noise_refiner_correctly": True,
    "control_in_dim": 33,
}


def _import_videox() -> None:
    if "func_timeout" not in sys.modules:
        stand_in = types.ModuleType("func_timeout")

        class FunctionTimedOut(Exception):
            pass

        def func_timeout(*_: Any, **__: Any) -> Any:
            raise RuntimeError(
                "func_timeout is not installed; VideoX-Fun's dataset loaders are not used here"
            )

        stand_in.FunctionTimedOut = FunctionTimedOut  # type: ignore[attr-defined]
        stand_in.func_timeout = func_timeout  # type: ignore[attr-defined]
        sys.modules["func_timeout"] = stand_in
    if str(VIDEOX_FUN_ROOT) not in sys.path:
        sys.path.insert(0, str(VIDEOX_FUN_ROOT))


def _runtime(extra: Mapping[str, str]) -> dict[str, Any]:
    import torch

    driver = (
        subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()[0]
    )
    libraries = [
        {"name": name, "version": importlib.metadata.version(name)}
        for name in (
            "accelerate",
            "diffusers",
            "numpy",
            "pillow",
            "safetensors",
            "torch",
            "transformers",
        )
    ]
    libraries += [{"name": name, "version": version} for name, version in extra.items()]
    return {
        "cuda": str(torch.version.cuda),
        "driver": driver,
        "hardware": f"{torch.cuda.get_device_name(0)}, {torch.cuda.get_device_properties(0).total_memory} bytes",
        "libraries": sorted(libraries, key=lambda item: item["name"]),
    }


def _circular_pad(tensor: Any, margin: int) -> Any:
    """Wrap-pad the last two axes of a tensor by ``margin``."""
    import torch

    if margin == 0:
        return tensor
    tensor = torch.cat([tensor[..., -margin:, :], tensor, tensor[..., :margin, :]], dim=-2)
    return torch.cat([tensor[..., :, -margin:], tensor, tensor[..., :, :margin]], dim=-1)


def _crop(tensor: Any, margin: int) -> Any:
    return tensor[..., margin:-margin, margin:-margin] if margin else tensor


class _CroppedDistribution:
    def __init__(self, distribution: Any, margin: int) -> None:
        self.distribution = distribution
        self.margin = margin

    def mode(self) -> Any:
        return _crop(self.distribution.mode(), self.margin)

    def sample(self, generator: Any = None) -> Any:
        return _crop(self.distribution.sample(generator), self.margin)


def _wrap_encode(vae: Any, margin_px: int) -> None:
    original = vae.encode

    def encode(x: Any, *args: Any, **kwargs: Any) -> Any:
        output = original(_circular_pad(x, margin_px), *args, **kwargs)
        return (_CroppedDistribution(output[0], margin_px // LATENT_PX),)

    vae.encode = encode


def _to_rgb8(image: Any) -> NDArray[np.uint8]:
    import torch

    pixels = ((image.float().clamp(-1, 1) + 1) * 127.5).round().to(torch.uint8)
    return pixels[0].permute(1, 2, 0).cpu().numpy()


def _control_tensor(conditioning: NDArray[np.uint8]) -> Any:
    import torch

    return (
        torch.from_numpy(np.ascontiguousarray(conditioning)).permute(2, 0, 1).unsqueeze(0).float()
        / 255
    )


class _Base:
    name = "videox"

    def __init__(self, candidate: Mapping[str, Any], directories: Mapping[str, Path]) -> None:
        import torch

        _import_videox()
        self.candidate = candidate
        self.device = torch.device("cuda")
        self.dtype = torch.bfloat16
        self.base = directories["base"]
        self.control = directories["control"]
        self.videox_commit = (VIDEOX_FUN_ROOT / "COMMIT").read_text(encoding="ascii").strip()
        self.step = 0
        self.seed = 0
        self.rows = 0
        self.columns = 0

    def runtime(self) -> dict[str, Any]:
        return _runtime({"videox-fun": self.videox_commit})

    def _shift(self) -> tuple[int, int]:
        shift = shift_for_step(self.seed, self.step, self.rows, self.columns)
        self.step += 1
        return shift


class QwenImageFunControl(_Base):
    name = "videox-qwenimage-fun-control"
    CONTROL_FILE: Final = "Qwen-Image-2512-Fun-Controlnet-Union-2602.safetensors"

    def __init__(self, candidate: Mapping[str, Any], directories: Mapping[str, Path]) -> None:
        super().__init__(candidate, directories)
        from diffusers import FlowMatchEulerDiscreteScheduler
        from safetensors.torch import load_file
        from videox_fun.models import (
            AutoencoderKLQwenImage,
            Qwen2_5_VLForConditionalGeneration,
            Qwen2Tokenizer,
            QwenImageControlTransformer2DModel,
        )
        from videox_fun.pipeline import QwenImageControlPipeline

        base = str(self.base)
        transformer = QwenImageControlTransformer2DModel.from_pretrained(
            base,
            subfolder="transformer",
            low_cpu_mem_usage=True,
            torch_dtype=self.dtype,
            transformer_additional_kwargs=dict(QWEN_CONTROL_KWARGS),
        ).to(self.dtype)
        missing, unexpected = transformer.load_state_dict(
            load_file(str(self.control / self.CONTROL_FILE)), strict=False
        )
        if unexpected:
            raise RuntimeError(
                f"the control weights hold {len(unexpected)} keys the control transformer has no place for"
            )
        self.missing_control_keys = len(missing)
        self.vae = AutoencoderKLQwenImage.from_pretrained(base, subfolder="vae").to(self.dtype)
        self.pipeline = QwenImageControlPipeline(
            vae=self.vae,
            tokenizer=Qwen2Tokenizer.from_pretrained(base, subfolder="tokenizer"),
            text_encoder=Qwen2_5_VLForConditionalGeneration.from_pretrained(
                base, subfolder="text_encoder", dtype=self.dtype
            ),
            transformer=transformer,
            scheduler=FlowMatchEulerDiscreteScheduler.from_pretrained(base, subfolder="scheduler"),
        ).to(self.device)
        self._wrap_transformer(transformer)

    def _wrap_transformer(self, transformer: Any) -> None:
        import torch

        original = transformer.forward

        def forward(*args: Any, **kwargs: Any) -> Any:
            dy, dx = self._shift()
            batch = kwargs["hidden_states"].shape[0]

            def roll(tokens: Any, sign: int) -> Any:
                grid = tokens.reshape(batch, self.rows, self.columns, tokens.shape[-1])
                return torch.roll(grid, shifts=(sign * dy, sign * dx), dims=(1, 2)).reshape(
                    tokens.shape
                )

            kwargs["hidden_states"] = roll(kwargs["hidden_states"], 1)
            kwargs["control_context"] = roll(kwargs["control_context"], 1)
            output = original(*args, **kwargs)
            prediction = output[0] if isinstance(output, tuple) else output.sample
            return (roll(prediction, -1),)

        transformer.forward = forward

    def generate(
        self, *, prompt: str, conditioning: NDArray[np.uint8], seed: int, sampler: Mapping[str, Any]
    ) -> NDArray[np.uint8]:
        import torch

        width, height, margin = sampler["width"], sampler["height"], sampler["wrap_margin_px"]
        self.seed, self.step = seed, 0
        self.rows, self.columns = height // (LATENT_PX * PATCH), width // (LATENT_PX * PATCH)
        if not getattr(self.vae, "_exulanica_wrapped", False):
            _wrap_encode(self.vae, margin)
            self.vae._exulanica_wrapped = True
        generator = torch.Generator(device=self.device).manual_seed(seed)
        with torch.no_grad():
            packed = self.pipeline(
                prompt,
                negative_prompt=sampler["negative_prompt"],
                height=height,
                width=width,
                generator=generator,
                true_cfg_scale=sampler["guidance_milli"] / 1000,
                num_inference_steps=sampler["steps"],
                image=None,
                mask_image=None,
                control_image=_control_tensor(conditioning),
                control_context_scale=sampler["control_context_scale_milli"] / 1000,
                output_type="latent",
            ).images
            if self.step != sampler["steps"]:
                raise RuntimeError(
                    f"the transformer ran {self.step} times for {sampler['steps']} steps; the roll schedule did not hold"
                )
            tokens = self.rows * self.columns
            latents = self.pipeline._unpack_latents(
                packed[:, :tokens], height, width, self.pipeline.vae_scale_factor, num_frame=1
            )
            latents = latents[:, :, :1].to(self.vae.dtype)
            config = self.vae.config
            mean = (
                torch.tensor(config.latents_mean)
                .view(1, config.z_dim, 1, 1, 1)
                .to(latents.device, latents.dtype)
            )
            std = (
                torch.tensor(config.latents_std)
                .view(1, config.z_dim, 1, 1, 1)
                .to(latents.device, latents.dtype)
            )
            latents = latents * std + mean
            decoded = self.vae.decode(
                _circular_pad(latents, margin // LATENT_PX), return_dict=False
            )[0]
            image = _crop(decoded[:, :, 0], margin)
        return _to_rgb8(image)


class ZImageFunControl(_Base):
    name = "videox-zimage-fun-control"
    CONTROL_FILE: Final = "Z-Image-Fun-Controlnet-Union-2.1.safetensors"

    def __init__(self, candidate: Mapping[str, Any], directories: Mapping[str, Path]) -> None:
        super().__init__(candidate, directories)
        from diffusers import FlowMatchEulerDiscreteScheduler
        from safetensors.torch import load_file
        from transformers import AutoTokenizer, Qwen3ForCausalLM
        from videox_fun.models import AutoencoderKL, ZImageControlTransformer2DModel
        from videox_fun.pipeline import ZImageControlPipeline

        base = str(self.base)
        transformer = ZImageControlTransformer2DModel.from_pretrained(
            base,
            subfolder="transformer",
            low_cpu_mem_usage=True,
            torch_dtype=self.dtype,
            transformer_additional_kwargs=dict(ZIMAGE_CONTROL_KWARGS),
        ).to(self.dtype)
        missing, unexpected = transformer.load_state_dict(
            load_file(str(self.control / self.CONTROL_FILE)), strict=False
        )
        if unexpected:
            raise RuntimeError(
                f"the control weights hold {len(unexpected)} keys the control transformer has no place for"
            )
        self.missing_control_keys = len(missing)
        self.vae = AutoencoderKL.from_pretrained(base, subfolder="vae").to(self.dtype)
        self.pipeline = ZImageControlPipeline(
            vae=self.vae,
            tokenizer=AutoTokenizer.from_pretrained(base, subfolder="tokenizer"),
            text_encoder=Qwen3ForCausalLM.from_pretrained(
                base, subfolder="text_encoder", dtype=self.dtype, low_cpu_mem_usage=True
            ),
            transformer=transformer,
            scheduler=FlowMatchEulerDiscreteScheduler.from_pretrained(base, subfolder="scheduler"),
        ).to(self.device)
        self._wrap_transformer(transformer)

    def _wrap_transformer(self, transformer: Any) -> None:
        import torch

        original = transformer.forward

        def forward(latents: Any, *args: Any, **kwargs: Any) -> Any:
            dy, dx = self._shift()
            shift = (dy * PATCH, dx * PATCH)
            rolled = [torch.roll(item, shifts=shift, dims=(-2, -1)) for item in latents]
            kwargs["control_context"] = torch.roll(
                kwargs["control_context"], shifts=shift, dims=(-2, -1)
            )
            output = original(rolled, *args, **kwargs)
            predictions = [
                torch.roll(item, shifts=(-shift[0], -shift[1]), dims=(-2, -1)) for item in output[0]
            ]
            return (predictions, *output[1:])

        transformer.forward = forward

    def generate(
        self, *, prompt: str, conditioning: NDArray[np.uint8], seed: int, sampler: Mapping[str, Any]
    ) -> NDArray[np.uint8]:
        import torch

        width, height, margin = sampler["width"], sampler["height"], sampler["wrap_margin_px"]
        self.seed, self.step = seed, 0
        self.rows, self.columns = height // (LATENT_PX * PATCH), width // (LATENT_PX * PATCH)
        if not getattr(self.vae, "_exulanica_wrapped", False):
            _wrap_encode(self.vae, margin)
            self.vae._exulanica_wrapped = True
        generator = torch.Generator(device=self.device).manual_seed(seed)
        with torch.no_grad():
            latents = self.pipeline(
                prompt=prompt,
                negative_prompt=sampler["negative_prompt"],
                height=height,
                width=width,
                generator=generator,
                guidance_scale=sampler["guidance_milli"] / 1000,
                image=None,
                mask_image=None,
                control_image=_control_tensor(conditioning),
                num_inference_steps=sampler["steps"],
                control_context_scale=sampler["control_context_scale_milli"] / 1000,
                output_type="latent",
            ).images
            if self.step != sampler["steps"]:
                raise RuntimeError(
                    f"the transformer ran {self.step} times for {sampler['steps']} steps; the roll schedule did not hold"
                )
            latents = (
                latents.to(self.vae.dtype) / self.vae.config.scaling_factor
                + self.vae.config.shift_factor
            )
            decoded = self.vae.decode(
                _circular_pad(latents, margin // LATENT_PX), return_dict=False
            )[0]
            image = _crop(decoded, margin)
        return _to_rgb8(image)
