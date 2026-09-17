#!/usr/bin/env bash
# What this lane needs of a rented host, and nothing else. Run over SSH before the first build.
#
#   scripts/host-check.sh
#
# It reports the host, the GPU, the driver, Docker and the disk, and installs the NVIDIA container
# toolkit only if Docker has no NVIDIA runtime. It deliberately does not do what
# deploy/gsplat/host-bootstrap.sh does for the trainer: no Node, no local registry, no data
# directory. Every minute on this machine is billed, and this lane needs none of those.
set -euo pipefail

echo "== host"
uname -srm
id -un
nproc
free -g | head -2
df -h / | tail -1

echo "== gpu"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv

echo "== docker"
docker --version
if ! docker info 2>/dev/null | grep -qi nvidia; then
  echo "the NVIDIA runtime is not registered with Docker; installing the container toolkit"
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
else
  echo "the NVIDIA runtime is registered"
fi

echo "== the gpu inside a container, which is what the runner needs"
docker run --rm --gpus all ubuntu:24.04 nvidia-smi -L

echo "== python on the host, for the weights fetcher (standard library only)"
python3 --version

echo "host check complete"
