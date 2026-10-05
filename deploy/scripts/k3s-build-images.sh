#!/usr/bin/env bash
# Build platform images and import them into the local k3s containerd.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

pull_base() {
  local name="$1"
  if docker image inspect "$name" >/dev/null 2>&1; then
    echo "base image present: $name"
    return
  fi
  echo "pulling $name via mirror"
  docker pull "docker.m.daocloud.io/library/${name}"
  docker tag "docker.m.daocloud.io/library/${name}" "$name"
}

import_image() {
  local name="$1"
  echo "importing $name into k3s"
  docker save "$name" | as_root k3s ctr images import -
}

pull_base python:3.11-slim
pull_base node:20-alpine
pull_base nginx:alpine
pull_base postgres:16-alpine

docker build -t webuild-auth:local -f "$ROOT/services/auth/Dockerfile" "$ROOT/services"
docker build -t webuild-relay:local -f "$ROOT/services/relay/Dockerfile" "$ROOT/services"
docker build -t webuild-hub:local -f "$ROOT/services/hub/Dockerfile" "$ROOT/services"
docker build -t webuild-gateway:local -f "$ROOT/services/gateway/Dockerfile" "$ROOT/services"
docker build -t webuild-web-ide:local "$ROOT/services/web-ide"

import_image webuild-auth:local
import_image webuild-relay:local
import_image webuild-hub:local
import_image webuild-gateway:local
import_image webuild-web-ide:local
import_image nginx:alpine
import_image postgres:16-alpine

echo "images imported"
