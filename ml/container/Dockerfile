# The texture inverse trainer, behind its own container boundary.
#
# NOTHING IN THE REPOSITORY BUILDS OR RUNS THIS. Building it downloads a PyTorch image, and running
# it spends GPU time; both wait for an operator's yes. The base is pinned by digest and the build
# refuses a tag. The base image supplies torch and numpy, so nothing is resolved at build time.
#
#   docker build -f ml/container/Dockerfile \
#     --build-arg TORCH_BASE=pytorch/pytorch:<version>-cuda<version>-cudnn<version>-runtime@sha256:<digest> \
#     --build-arg CODE_REVISION=<40 hex> .
#
# Run it with ml/container/run.sh, which gives it no network, a read-only root, the export and the
# published maker objects read-only, and one writable directory for the weights and the receipt.
ARG TORCH_BASE
FROM ${TORCH_BASE}
ARG TORCH_BASE
ARG CODE_REVISION
ENV EXULANICA_BUILD_REVISION=${CODE_REVISION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN case "${TORCH_BASE}" in *@sha256:*) ;; *) exit 1 ;; esac
RUN python -c 'import os,re; assert re.fullmatch("[0-9a-f]{40}", os.environ["EXULANICA_BUILD_REVISION"])'
COPY ml/exulanica_training /opt/exulanica-training/exulanica_training
COPY LICENSE THIRD_PARTY_NOTICES.md /opt/exulanica-training/
ENV PYTHONPATH=/opt/exulanica-training
RUN python -c 'import torch, numpy; import exulanica_training.texture_inverse.train' \
 && useradd --system --uid 10001 --no-create-home trainer
WORKDIR /opt/exulanica-training
USER trainer
LABEL org.opencontainers.image.source="https://github.com/twinkling-reality/exulanica" \
      org.opencontainers.image.licenses="Apache-2.0"
ENTRYPOINT ["python", "-m", "exulanica_training.texture_inverse"]
