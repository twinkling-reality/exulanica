# Build on Linux with a reviewed digest-pinned PyTorch CUDA devel image.
# For example resolve pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel to its real digest first.
ARG CUDA_BASE
FROM ${CUDA_BASE}
ARG CUDA_BASE
ARG CODE_REVISION
ARG TORCH_CUDA_ARCH_LIST="8.6;8.9;9.0+PTX"
ENV TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST} \
    TORCH_HOME=/opt/torch-cache \
    PYTHONDONTWRITEBYTECODE=1 \
    EXULANICA_BUILD_REVISION=${CODE_REVISION}
# Refuse mutable base references or an unbound Exulanica build.
RUN python -c 'import os,re; assert re.fullmatch("[0-9a-f]{40}", os.environ["EXULANICA_BUILD_REVISION"])'
RUN case "${CUDA_BASE}" in *@sha256:*) ;; *) exit 1 ;; esac
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/gsplat/requirements.txt /opt/gsplat-requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/gsplat-requirements.txt
RUN git clone --recursive https://github.com/nerfstudio-project/gsplat.git /opt/gsplat \
    && git -C /opt/gsplat checkout 937e29912570c372bed6747a5c9bf85fed877bae \
    && git -C /opt/gsplat submodule update --init --recursive \
    && python -m pip install --no-deps --no-build-isolation -e /opt/gsplat
# Populate LPIPS weights at build time. Scene execution has no network access.
RUN python -c 'from torchmetrics.image.lpip import LearnedPerceptualImagePatchSimilarity as L; L(net_type="alex", normalize=True)'
COPY exulanica /app/exulanica
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
ENV PYTHONPATH=/app
RUN python -m pip freeze > /opt/runtime-requirements.txt \
    && chmod -R a+rX /opt/torch-cache /opt/gsplat /app
WORKDIR /app
LABEL org.opencontainers.image.source="https://github.com/twinkling-reality/exulanica" \
      org.opencontainers.image.licenses="Apache-2.0"
ENTRYPOINT ["python", "-m", "exulanica.reconstruction.gsplat_runner"]
