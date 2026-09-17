"""Build reviewed material packs: small GLB containers holding one material's textures.

A pack's glTF material names its colour image as ``baseColorTexture`` so every engine decodes it
as sRGB; normal and opacity images stay linear. The catalog, not the pack, states which texture
plays which role at runtime.
"""

import io
import json
from pathlib import Path

from PIL import Image, ImageChops

if __package__:
    from .glb import BinaryBuilder, write_glb
else:
    from glb import BinaryBuilder, write_glb

MHMAT_KEYS = {
    "diffuseTexture": "diffuse",
    "normalmapTexture": "normal",
    "aomapTexture": "occlusion",
    "transparent": "transparent",
    "backfaceCull": "backfaceCull",
}


def read_mhmat(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        if key in MHMAT_KEYS:
            values[MHMAT_KEYS[key]] = value.strip()
    return values


def repair(image, repairs):
    """Replace reviewed rectangles with fabric copied from a declared offset, feathered."""
    if not repairs:
        return image
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    source = rgba.copy()
    src = source.load()
    for item in repairs:
        x0, y0, x1, y1 = item["rect"]
        dx, dy = item["from"]
        feather = 12
        for y in range(y0, y1):
            for x in range(x0, x1):
                edge = min(x - x0, y - y0, x1 - 1 - x, y1 - 1 - y)
                weight = min(1.0, edge / feather)
                a = src[x, y]
                b = src[x + dx, y + dy]
                pixels[x, y] = tuple(round(a[c] * (1 - weight) + b[c] * weight) for c in range(4))
    return rgba if image.mode == "RGBA" else rgba.convert(image.mode)


def bake_occlusion(colour, occlusion):
    """Multiply the authored ambient occlusion into the colour, so no extra texture ships."""
    shade = occlusion.convert("L").resize(colour.size, Image.Resampling.BILINEAR).convert("RGB")
    out = ImageChops.multiply(colour.convert("RGB"), shade)
    if colour.mode == "RGBA":
        out.putalpha(colour.getchannel("A"))
    return out


def normalise_hair(colour):
    """A light neutral strand texture for multiplicative tinting, keeping relative contrast."""
    rgba = colour.convert("RGBA")
    luminance = rgba.convert("L")
    alpha = rgba.getchannel("A")
    values = [v for v, a in zip(luminance.getdata(), alpha.getdata(), strict=True) if a > 128]
    mean = sum(values) / len(values) if values else 128
    scale = 205 / max(mean, 1)
    lifted = luminance.point(lambda v: min(255, round(v * scale)))
    return Image.merge("RGB", [lifted, lifted, lifted])


def encode(image, fmt, quality=86):
    buffer = io.BytesIO()
    if fmt == "jpeg":
        image.convert("RGB").save(buffer, "JPEG", quality=quality, optimize=True, progressive=False)
        return buffer.getvalue(), "image/jpeg"
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue(), "image/png"


def average_colour(image, mask=None):
    rgb = image.convert("RGB").resize((256, 256), Image.Resampling.BOX)
    if mask is None:
        mask = Image.new("L", rgb.size, 255)
    mask = mask.resize(rgb.size, Image.Resampling.BOX)
    total = [0, 0, 0]
    weight = 0
    for pixel, m in zip(rgb.getdata(), mask.getdata(), strict=True):
        if m > 128:
            for c in range(3):
                total[c] += pixel[c]
            weight += 1
    if not weight:
        return "#808080"
    return "#" + "".join(f"{round(t / weight):02x}" for t in total)


def pack_glb(name, images, material):
    """images: list of (bytes, mime); material: glTF material dict referencing texture 0."""
    buffer = BinaryBuilder()
    doc = {
        "asset": {"version": "2.0", "generator": "exulanica material pack/1"},
        "images": [],
        "textures": [],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
        "materials": [dict(material, name=name)],
        "bufferViews": buffer.views,
        "buffers": [],
    }
    for index, (payload, mime) in enumerate(images):
        view = buffer.add(payload)
        doc["images"].append({"bufferView": view, "mimeType": mime, "name": f"{name}-{index}"})
        doc["textures"].append({"sampler": 0, "source": index})
    data = bytes(buffer.data)
    doc["buffers"] = [{"byteLength": len(data) + (-len(data) % 4)}]
    return write_glb(doc, data)


def build_pack(name, kind, mhmat, settings, repairs=None, image_path=None, return_image=False):
    """Return (glb bytes, description) for one material, plus the processed colour image.

    ``image_path`` overrides the mhmat's diffuse texture (eye colour variants).
    """
    folder = Path(mhmat).parent
    info = read_mhmat(mhmat)
    colour_path = Path(image_path) if image_path else folder / info["diffuse"]
    colour = Image.open(colour_path)
    colour.load()
    colour = repair(colour, repairs)
    if settings.get("bakeOcclusion") and "occlusion" in info:
        colour = bake_occlusion(colour, Image.open(folder / info["occlusion"]))
    roles = {"baseColor": 0}
    images = []
    size = settings["size"]
    alpha_mode = settings.get("alphaMode", "OPAQUE")
    tint = settings.get("tint")
    average = average_colour(colour, colour.getchannel("A") if colour.mode == "RGBA" and alpha_mode != "OPAQUE" else None)
    if kind == "hair":
        base = normalise_hair(colour).resize((size, size), Image.Resampling.LANCZOS)
        images.append(encode(base, settings["format"], settings.get("quality", 86)))
        alpha = colour.convert("RGBA").getchannel("A").resize(
            (settings["alphaSize"], settings["alphaSize"]), Image.Resampling.LANCZOS
        )
        images.append(encode(alpha, "png"))
        roles["opacity"] = 1
    else:
        resized = colour.resize((size, size), Image.Resampling.LANCZOS)
        if alpha_mode == "OPAQUE":
            resized = resized.convert("RGB")
            images.append(encode(resized, settings["format"], settings.get("quality", 86)))
        else:
            images.append(encode(resized.convert("RGBA"), "png"))
        if "normalSize" in settings and "normal" in info:
            normal = Image.open(folder / info["normal"]).convert("RGB")
            normal = normal.resize((settings["normalSize"], settings["normalSize"]), Image.Resampling.LANCZOS)
            images.append(encode(normal, "jpeg", 92))
            roles["normal"] = len(images) - 1
    material = {
        "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0},
            "metallicFactor": 0,
            "roughnessFactor": settings.get("roughness", 700) / 1000,
        },
        "alphaMode": "OPAQUE" if kind == "hair" else alpha_mode,
    }
    if "normal" in roles:
        material["normalTexture"] = {"index": roles["normal"]}
    if alpha_mode == "MASK" and kind != "hair":
        material["alphaCutoff"] = settings.get("alphaCutoff", 500) / 1000
    if settings.get("doubleSided"):
        material["doubleSided"] = True
    description = {
        "kind": kind,
        "roles": roles,
        "alphaMode": alpha_mode,
        "alphaCutoffMilli": settings.get("alphaCutoff", 500) if alpha_mode == "MASK" else None,
        "doubleSided": bool(settings.get("doubleSided")),
        "roughnessMilli": settings.get("roughness", 700),
        "tint": tint,
        "averageColour": average,
        "source": {"mhmat": mhmat_relative(mhmat), "image": mhmat_relative(colour_path)},
    }
    data = pack_glb(name, images, material)
    if return_image:
        processed = normalise_hair(colour) if kind == "hair" else colour
        return data, description, processed
    return data, description


def mhmat_relative(path):
    parts = Path(path).parts
    for anchor in ("clothes", "hair", "skins", "eyes", "eyebrows", "eyelashes"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor) :])
    return Path(path).name


if __name__ == "__main__":
    import sys

    args = json.loads(sys.argv[1])
    data, info = build_pack(**args)
    Path(args["name"] + ".glb").write_bytes(data)
    print(json.dumps(info))
