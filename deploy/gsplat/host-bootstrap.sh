#!/usr/bin/env bash
# Prepare an authorized CUDA host for the Exulanica scene worker. Idempotent; run over SSH as the
# operator user. Verified 2026-09-05 on Ubuntu 22.04 with Docker 29 and an NVIDIA L40S.
set -euo pipefail
echo "== host"; uname -a; id; nproc; free -g | head -2; df -h / | tail -1
echo "== gpu"; nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
echo "== docker"; docker --version
if ! docker info 2>/dev/null | grep -qi nvidia; then
  echo "NVIDIA runtime is not registered with Docker; installing the container toolkit"
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
fi
echo "== gpu inside docker"; docker run --rm --gpus device=0 ubuntu:24.04 nvidia-smi -L
# Node runs the locked splat-transform compressor; the official tarball needs no root.
NODE_VERSION="${NODE_VERSION:-v22.12.0}"
if [ ! -x "$HOME/node/bin/node" ]; then
  curl -fsSL "https://nodejs.org/dist/$NODE_VERSION/node-$NODE_VERSION-linux-x64.tar.xz" -o /tmp/node.tar.xz
  mkdir -p "$HOME/node" && tar -xJf /tmp/node.tar.xz -C "$HOME/node" --strip-components=1
fi
export PATH="$HOME/node/bin:$PATH"; echo "== node $(node --version) npm $(npm --version)"
# A local registry gives every image a real immutable manifest digest without an external account.
docker ps --format '{{.Names}}' | grep -q '^registry$' \
  || docker run -d --restart always -p 127.0.0.1:5000:5000 --name registry registry:2 >/dev/null
echo "== registry $(docker ps --format '{{.Names}} {{.Status}}' | grep registry)"
mkdir -p "${EXULANICA_DATA_DIR:-$HOME/exulanica-data}/blobs"
echo "bootstrap complete"
