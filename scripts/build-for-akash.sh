#!/usr/bin/env bash
set -euo pipefail

IMAGE_REF=${1:-ghcr.io/your-org/transcribe-akash:latest}
PUSH_IMAGE=${PUSH_IMAGE:-false}
OUTPUT_DIR=${OUTPUT_DIR:-akash}

log() {
  echo -e "[build] $1"
}

log "Building container image ${IMAGE_REF}"
docker build -t "${IMAGE_REF}" -f Dockerfile .

if [[ "${PUSH_IMAGE}" == "true" ]]; then
  log "Pushing ${IMAGE_REF} to registry"
  docker push "${IMAGE_REF}"
fi

mkdir -p "${OUTPUT_DIR}"
log "Rendering deployment manifest at ${OUTPUT_DIR}/deploy.yaml"
sed "s|ghcr.io/your-org/transcribe-akash:latest|${IMAGE_REF}|g" deploy.yaml > "${OUTPUT_DIR}/deploy.yaml"

log "Done. Upload ${OUTPUT_DIR}/deploy.yaml to the Akash provider."
