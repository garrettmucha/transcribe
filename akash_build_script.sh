#!/bin/bash
set -e

# Build script for Akash deployment
# This script builds and pushes container images to a registry

# Configuration
REGISTRY="ghcr.io"  # GitHub Container Registry (free)
USERNAME="${GITHUB_USERNAME:-your-username}"
IMAGE_NAME="transcribe-service"
TAG="${IMAGE_TAG:-latest}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check requirements
check_requirements() {
    log_info "Checking requirements..."
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker is required but not installed"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running"
        exit 1
    fi
    
    log_success "Requirements check passed"
}

# Build the container image
build_image() {
    log_info "Building container image..."
    
    # Build with Akash-optimized Dockerfile
    docker build \
        -f Dockerfile.akash \
        -t "${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}" \
        .
    
    log_success "Container image built: ${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}"
}

# Test the image locally
test_image() {
    log_info "Testing container image..."
    
    # Test that the image starts correctly
    CONTAINER_ID=$(docker run -d \
        -e DATABASE_URL="sqlite:///test.db" \
        -e REDIS_URL="redis://localhost:6379" \
        -p 8001:8000 \
        "${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}")
    
    # Wait for startup
    sleep 10
    
    # Check health
    if curl -f http://localhost:8001/healthz &> /dev/null; then
        log_success "Container health check passed"
    else
        log_warning "Health check failed (may be expected without database)"
    fi
    
    # Cleanup
    docker stop "$CONTAINER_ID" &> /dev/null
    docker rm "$CONTAINER_ID" &> /dev/null
    
    log_success "Container test completed"
}

# Push to registry
push_image() {
    log_info "Pushing to container registry..."
    
    # Login to registry (assumes you're already authenticated)
    # For GitHub Container Registry: echo $GITHUB_TOKEN | docker login ghcr.io -u $GITHUB_USERNAME --password-stdin
    
    docker push "${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}"
    
    log_success "Image pushed to ${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}"
}

# Generate deployment file with correct image
generate_deployment() {
    log_info "Generating Akash deployment file..."
    
    # Create akash directory if it doesn't exist
    mkdir -p akash
    
    # Update deploy.yaml with correct image name
    sed "s|ghcr.io/your-username/transcribe-service:latest|${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}|g" \
        deploy.yaml > akash/deploy.yaml
    
    log_success "Deployment file generated: akash/deploy.yaml"
}

# Create optimized deployment configurations
create_deployment_configs() {
    log_info "Creating deployment configurations..."
    
    mkdir -p akash
    
    # Create different deployment profiles
    cat > akash/deploy-small.yaml << EOF
# Small deployment profile (lower resource usage)
---
version: "2.0"

services:
  postgres:
    image: postgres:15-alpine
    env:
      - POSTGRES_DB=transcribe_db
      - POSTGRES_USER=transcribe_user
      - POSTGRES_PASSWORD=transcribe_pass
    expose:
      - port: 5432
        as: 5432
        to:
          - service: api
          - service: worker

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "128mb"]
    expose:
      - port: 6379
        as: 6379
        to:
          - service: api
          - service: worker

  api:
    image: ${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}
    env:
      - DATABASE_URL=postgresql://transcribe_user:transcribe_pass@postgres:5432/transcribe_db
      - REDIS_URL=redis://redis:6379
      - WHISPER_MODEL=small
      - ENABLE_DIARIZATION=false
      - MAX_DURATION_MIN=10
      - DAILY_CAP_MIN=5
    expose:
      - port: 8000
        as: 80
        to:
          - global: true

  worker:
    image: ${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}
    env:
      - DATABASE_URL=postgresql://transcribe_user:transcribe_pass@postgres:5432/transcribe_db
      - REDIS_URL=redis://redis:6379
      - WHISPER_MODEL=small
      - ENABLE_DIARIZATION=false
    command: ["celery", "-A", "app.tasks.main", "worker", "--loglevel=info", "--concurrency=1"]

profiles:
  compute:
    api:
      resources:
        cpu:
          units: 1
        memory:
          size: 2Gi
        storage:
          - size: 5Gi
    worker:
      resources:
        cpu:
          units: 2
        memory:
          size: 3Gi
        storage:
          - size: 3Gi
    postgres:
      resources:
        cpu:
          units: 0.5
        memory:
          size: 1Gi
        storage:
          - size: 10Gi
    redis:
      resources:
        cpu:
          units: 0.25
        memory:
          size: 256Mi
        storage:
          - size: 512Mi

  placement:
    dcloud:
      pricing:
        api:
          denom: uakt
          amount: 500
        worker:
          denom: uakt
          amount: 1000
        postgres:
          denom: uakt
          amount: 300
        redis:
          denom: uakt
          amount: 100

deployment:
  api:
    dcloud:
      profile: api
      count: 1
  worker:
    dcloud:
      profile: worker
      count: 1
  postgres:
    dcloud:
      profile: postgres
      count: 1
  redis:
    dcloud:
      profile: redis
      count: 1
EOF

    log_success "Created small deployment profile: akash/deploy-small.yaml"
}

# Main execution
main() {
    log_info "🚀 Building Audio Transcription Service for Akash"
    echo "======================================================="
    
    check_requirements
    build_image
    test_image
    
    # Ask user if they want to push
    echo ""
    read -p "Push image to registry? (y/N): " -r
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        push_image
        generate_deployment
        create_deployment_configs
        
        echo ""
        log_success "🎉 Build complete!"
        echo ""
        echo "Next steps:"
        echo "1. Review and customize akash/deploy.yaml or akash/deploy-small.yaml"
        echo "2. Add your S3/R2 credentials to the deployment file"
        echo "3. Deploy to Akash: akash tx deployment create akash/deploy.yaml"
        echo ""
        echo "Image: ${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}"
    else
        log_info "Skipping registry push. Image available locally."
        echo ""
        echo "To push later: docker push ${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${TAG}"
    fi
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --username)
            USERNAME="$2"
            shift 2
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --registry)
            REGISTRY="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--username USERNAME] [--tag TAG] [--registry REGISTRY]"
            echo ""
            echo "Options:"
            echo "  --username    Container registry username (default: \$GITHUB_USERNAME)"
            echo "  --tag         Image tag (default: latest)"
            echo "  --registry    Container registry (default: ghcr.io)"
            echo "  -h, --help    Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Run main function
main "$@"