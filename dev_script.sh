#!/bin/bash
set -e

# Development helper script for the Audio Transcription Service
# Usage: ./scripts/dev.sh [command]

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
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

# Check if docker-compose is available
check_docker() {
    if ! command -v docker-compose &> /dev/null; then
        log_error "docker-compose is not installed or not in PATH"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        log_error "Docker is not running"
        exit 1
    fi
}

# Setup environment
setup() {
    log_info "Setting up development environment..."
    
    cd "$PROJECT_DIR"
    
    # Copy .env file if it doesn't exist
    if [ ! -f ".env" ]; then
        log_info "Creating .env file from template..."
        cp .env.example .env
        log_warning "Please edit .env file with your configuration"
    else
        log_info ".env file already exists"
    fi
    
    # Create necessary directories
    mkdir -p tmp/transcribe/storage
    mkdir -p tmp/transcribe/temp
    
    log_success "Development environment setup complete"
}

# Start all services
start() {
    log_info "Starting all services..."
    cd "$PROJECT_DIR"
    
    check_docker
    docker-compose up -d
    
    log_info "Waiting for services to start..."
    sleep 10
    
    # Check health
    if curl -s http://localhost/healthz > /dev/null; then
        log_success "Services started successfully!"
        log_info "API: http://localhost"
        log_info "Metrics: http://localhost/metrics"
        log_info "Traefik Dashboard: http://localhost:8080"
    else
        log_error "Services failed to start properly"
        logs
        exit 1
    fi
}

# Stop all services
stop() {
    log_info "Stopping all services..."
    cd "$PROJECT_DIR"
    
    check_docker
    docker-compose down
    
    log_success "Services stopped"
}

# Restart services
restart() {
    log_info "Restarting services..."
    stop
    start
}

# View logs
logs() {
    cd "$PROJECT_DIR"
    check_docker
    
    if [ -n "$1" ]; then
        log_info "Showing logs for service: $1"
        docker-compose logs -f "$1"
    else
        log_info "Showing logs for all services"
        docker-compose logs -f
    fi
}

# Run tests
test() {
    log_info "Running tests..."
    cd "$PROJECT_DIR"
    
    check_docker
    
    # Ensure test dependencies are available
    docker-compose exec api pytest tests/ -v --cov=app --cov-report=term-missing
    
    log_success "Tests completed"
}

# Run linting and formatting
lint() {
    log_info "Running code quality checks..."
    cd "$PROJECT_DIR"
    
    check_docker
    
    # Format code
    log_info "Formatting code with black..."
    docker-compose exec api black app/ tests/
    
    # Lint code
    log_info "Linting code with ruff..."
    docker-compose exec api ruff app/ tests/
    
    # Type checking
    log_info "Type checking with mypy..."
    docker-compose exec api mypy app/
    
    log_success "Code quality checks completed"
}

# Database operations
db() {
    cd "$PROJECT_DIR"
    check_docker
    
    case "$1" in
        "migrate")
            log_info "Running database migrations..."
            docker-compose exec api alembic upgrade head
            log_success "Migrations completed"
            ;;
        "reset")
            log_warning "This will delete all data! Are you sure? (y/N)"
            read -r response
            if [[ "$response" =~ ^[Yy]$ ]]; then
                log_info "Resetting database..."
                docker-compose down -v
                docker-compose up -d postgres redis
                sleep 5
                docker-compose exec api alembic upgrade head
                log_success "Database reset completed"
            else
                log_info "Database reset cancelled"
            fi
            ;;
        "connect")
            log_info "Connecting to database..."
            docker-compose exec postgres psql -U transcribe_user -d transcribe_db
            ;;
        "backup")
            backup_file="backup_$(date +%Y%m%d_%H%M%S).sql"
            log_info "Creating database backup: $backup_file"
            docker-compose exec postgres pg_dump -U transcribe_user transcribe_db > "$backup_file"
            log_success "Database backup created: $backup_file"
            ;;
        *)
            log_error "Unknown database command: $1"
            echo "Available commands: migrate, reset, connect, backup"
            exit 1
            ;;
    esac
}

# Load testing
load_test() {
    log_info "Running load test..."
    cd "$PROJECT_DIR"
    
    # Check if locust is installed
    if ! command -v locust &> /dev/null; then
        log_error "Locust is not installed. Install with: pip install locust"
        exit 1
    fi
    
    # Start load test
    if [ -n "$1" ]; then
        scenario="$1"
    else
        scenario="normal"
    fi
    
    case "$scenario" in
        "normal")
            locust -f tests/load_test.py --host=http://localhost --users=10 --spawn-rate=2 --run-time=5m --headless
            ;;
        "peak")
            locust -f tests/load_test.py --host=http://localhost --users=50 --spawn-rate=5 --run-time=10m --headless
            ;;
        "stress")
            locust -f tests/load_test.py --host=http://localhost --users=100 --spawn-rate=10 --run-time=15m --headless
            ;;
        "interactive")
            log_info "Starting interactive load test. Open http://localhost:8089 in your browser."
            locust -f tests/load_test.py --host=http://localhost
            ;;
        *)
            log_error "Unknown load test scenario: $scenario"
            echo "Available scenarios: normal, peak, stress, interactive"
            exit 1
            ;;
    esac
}

# Clean up development environment
clean() {
    log_info "Cleaning up development environment..."
    cd "$PROJECT_DIR"
    
    check_docker
    
    # Stop and remove containers, networks, images, and volumes
    docker-compose down -v --rmi all --remove-orphans
    
    # Remove temporary files
    rm -rf tmp/
    
    # Clean up Python cache
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    
    log_success "Development environment cleaned"
}

# Show status of services
status() {
    log_info "Checking service status..."
    cd "$PROJECT_DIR"
    
    check_docker
    
    # Show container status
    docker-compose ps
    
    echo ""
    
    # Check health endpoints
    log_info "Health checks:"
    
    if curl -s http://localhost/healthz > /dev/null; then
        log_success "API: healthy"
    else
        log_error "API: unhealthy"
    fi
    
    if curl -s http://localhost/metrics > /dev/null; then
        log_success "Metrics: accessible"
    else
        log_error "Metrics: inaccessible"
    fi
}

# Show help
help() {
    echo "Audio Transcription Service - Development Helper"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  setup      Setup development environment"
    echo "  start      Start all services"
    echo "  stop       Stop all services"
    echo "  restart    Restart all services"
    echo "  logs       View logs (optionally for specific service)"
    echo "  test       Run tests"
    echo "  lint       Run code quality checks"
    echo "  db         Database operations (migrate|reset|connect|backup)"
    echo "  load-test  Run load tests (normal|peak|stress|interactive)"
    echo "  status     Show service status"
    echo "  clean      Clean up development environment"
    echo "  help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 setup"
    echo "  $0 start"
    echo "  $0 logs api"
    echo "  $0 db migrate"
    echo "  $0 load-test interactive"
}

# Main command dispatcher
case "${1:-help}" in
    "setup")
        setup
        ;;
    "start")
        start
        ;;
    "stop")
        stop
        ;;
    "restart")
        restart
        ;;
    "logs")
        logs "$2"
        ;;
    "test")
        test
        ;;
    "lint")
        lint
        ;;
    "db")
        db "$2"
        ;;
    "load-test")
        load_test "$2"
        ;;
    "status")
        status
        ;;
    "clean")
        clean
        ;;
    "help")
        help
        ;;
    *)
        log_error "Unknown command: $1"
        help
        exit 1
        ;;
esac