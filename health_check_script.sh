#!/bin/bash
set -e

# Health check script for Audio Transcription Service
# Usage: ./scripts/health_check.sh [--detailed] [--host HOST] [--timeout SECONDS]

# Default values
HOST="http://localhost"
TIMEOUT=30
DETAILED=false
NAGIOS_MODE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --detailed)
            DETAILED=true
            shift
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        --nagios)
            NAGIOS_MODE=true
            DETAILED=false
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--detailed] [--host HOST] [--timeout SECONDS] [--nagios]"
            echo ""
            echo "Options:"
            echo "  --detailed    Show detailed health information"
            echo "  --host HOST   Base URL to check (default: http://localhost)"
            echo "  --timeout N   Request timeout in seconds (default: 30)"
            echo "  --nagios      Output in Nagios-compatible format"
            echo "  -h, --help    Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Health check results
HEALTH_STATUS="OK"
HEALTH_DETAILS=""
FAILED_CHECKS=0
TOTAL_CHECKS=0

# Helper functions
log_info() {
    if [ "$NAGIOS_MODE" = false ]; then
        echo -e "${BLUE}[INFO]${NC} $1"
    fi
}

log_success() {
    if [ "$NAGIOS_MODE" = false ]; then
        echo -e "${GREEN}[OK]${NC} $1"
    fi
}

log_warning() {
    if [ "$NAGIOS_MODE" = false ]; then
        echo -e "${YELLOW}[WARNING]${NC} $1"
    fi
}

log_error() {
    if [ "$NAGIOS_MODE" = false ]; then
        echo -e "${RED}[ERROR]${NC} $1"
    fi
}

# Health check functions
check_endpoint() {
    local endpoint="$1"
    local expected_status="$2"
    local description="$3"
    
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    
    if [ "$DETAILED" = true ]; then
        log_info "Checking $description..."
    fi
    
    local start_time=$(date +%s.%N)
    local status_code
    
    status_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$HOST$endpoint" 2>/dev/null)
    local curl_exit=$?
    
    local end_time=$(date +%s.%N)
    local duration=$(echo "$end_time - $start_time" | bc -l)
    
    if [ $curl_exit -ne 0 ]; then
        log_error "$description - Connection failed"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
        HEALTH_STATUS="CRITICAL"
        HEALTH_DETAILS="$HEALTH_DETAILS $description: CONNECTION_FAILED;"
        return 1
    fi
    
    if [ "$status_code" = "$expected_status" ]; then
        if [ "$DETAILED" = true ]; then
            log_success "$description (${status_code}, ${duration}s)"
        fi
        HEALTH_DETAILS="$HEALTH_DETAILS $description: OK(${duration}s);"
        return 0
    else
        log_error "$description - Expected $expected_status, got $status_code"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
        HEALTH_STATUS="CRITICAL"
        HEALTH_DETAILS="$HEALTH_DETAILS $description: HTTP_${status_code};"
        return 1
    fi
}

check_json_endpoint() {
    local endpoint="$1"
    local description="$2"
    local required_field="$3"
    
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    
    if [ "$DETAILED" = true ]; then
        log_info "Checking $description..."
    fi
    
    local start_time=$(date +%s.%N)
    local response
    
    response=$(curl -s --max-time "$TIMEOUT" "$HOST$endpoint" 2>/dev/null)
    local curl_exit=$?
    
    local end_time=$(date +%s.%N)
    local duration=$(echo "$end_time - $start_time" | bc -l)
    
    if [ $curl_exit -ne 0 ]; then
        log_error "$description - Connection failed"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
        HEALTH_STATUS="CRITICAL"
        HEALTH_DETAILS="$HEALTH_DETAILS $description: CONNECTION_FAILED;"
        return 1
    fi
    
    # Check if response is valid JSON
    if ! echo "$response" | python -m json.tool > /dev/null 2>&1; then
        log_error "$description - Invalid JSON response"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
        HEALTH_STATUS="CRITICAL"
        HEALTH_DETAILS="$HEALTH_DETAILS $description: INVALID_JSON;"
        return 1
    fi
    
    # Check for required field if specified
    if [ -n "$required_field" ]; then
        if ! echo "$response" | python -c "import sys, json; data=json.load(sys.stdin); sys.exit(0 if '$required_field' in data else 1)" 2>/dev/null; then
            log_error "$description - Missing required field: $required_field"
            FAILED_CHECKS=$((FAILED_CHECKS + 1))
            HEALTH_STATUS="WARNING"
            HEALTH_DETAILS="$HEALTH_DETAILS $description: MISSING_FIELD($required_field);"
            return 1
        fi
    fi
    
    if [ "$DETAILED" = true ]; then
        log_success "$description (${duration}s)"
    fi
    HEALTH_DETAILS="$HEALTH_DETAILS $description: OK(${duration}s);"
    return 0
}

check_docker_services() {
    if [ "$DETAILED" = true ]; then
        log_info "Checking Docker services..."
    fi
    
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    
    # Check if docker-compose is available
    if ! command -v docker-compose &> /dev/null; then
        if [ "$DETAILED" = true ]; then
            log_warning "docker-compose not available, skipping service check"
        fi
        return 0
    fi
    
    # Check if we're in the right directory
    if [ ! -f "docker-compose.yml" ]; then
        if [ "$DETAILED" = true ]; then
            log_warning "docker-compose.yml not found, skipping service check"
        fi
        return 0
    fi
    
    # Check service status
    local services=(api worker postgres redis traefik)
    local failed_services=()
    
    for service in "${services[@]}"; do
        if ! docker-compose ps "$service" | grep -q "Up"; then
            failed_services+=("$service")
        fi
    done
    
    if [ ${#failed_services[@]} -gt 0 ]; then
        log_error "Docker services not running: ${failed_services[*]}"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
        HEALTH_STATUS="CRITICAL"
        HEALTH_DETAILS="$HEALTH_DETAILS Docker: SERVICES_DOWN(${failed_services[*]});"
        return 1
    fi
    
    if [ "$DETAILED" = true ]; then
        log_success "All Docker services running"
    fi
    HEALTH_DETAILS="$HEALTH_DETAILS Docker: OK;"
    return 0
}

check_disk_space() {
    if [ "$DETAILED" = true ]; then
        log_info "Checking disk space..."
    fi
    
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    
    # Check available disk space (warn if < 1GB)
    local available_space
    available_space=$(df . | awk 'NR==2 {print $4}')
    local available_gb=$((available_space / 1024 / 1024))
    
    if [ "$available_gb" -lt 1 ]; then
        log_warning "Low disk space: ${available_gb}GB available"
        HEALTH_STATUS="WARNING"
        HEALTH_DETAILS="$HEALTH_DETAILS Disk: LOW_SPACE(${available_gb}GB);"
        return 1
    fi
    
    if [ "$DETAILED" = true ]; then
        log_success "Disk space OK (${available_gb}GB available)"
    fi
    HEALTH_DETAILS="$HEALTH_DETAILS Disk: OK(${available_gb}GB);"
    return 0
}

# Main health check execution
main() {
    if [ "$NAGIOS_MODE" = false ]; then
        echo "🏥 Audio Transcription Service Health Check"
        echo "==========================================="
        echo ""
    fi
    
    # Core API endpoints
    check_endpoint "/healthz" "200" "Health endpoint"
    check_endpoint "/metrics" "200" "Metrics endpoint"
    check_json_endpoint "/api/v1/usage" "Usage endpoint" "daily_limit_minutes"
    
    # Optional admin endpoint (may require auth)
    if curl -s --max-time 5 "$HOST/api/v1/admin/overview" | grep -q "total_jobs" 2>/dev/null; then
        check_json_endpoint "/api/v1/admin/overview" "Admin overview" "total_jobs"
    elif [ "$DETAILED" = true ]; then
        log_info "Admin endpoint requires authentication (skipping)"
    fi
    
    # Infrastructure checks
    if [ "$DETAILED" = true ]; then
        check_docker_services
        check_disk_space
    fi
    
    # Summary
    if [ "$NAGIOS_MODE" = true ]; then
        # Nagios-compatible output
        if [ "$HEALTH_STATUS" = "OK" ]; then
            echo "OK - All health checks passed ($TOTAL_CHECKS checks) | checks_passed=$((TOTAL_CHECKS - FAILED_CHECKS)); checks_failed=$FAILED_CHECKS; response_time=0.001"
            exit 0
        elif [ "$HEALTH_STATUS" = "WARNING" ]; then
            echo "WARNING - $FAILED_CHECKS/$TOTAL_CHECKS checks failed | checks_passed=$((TOTAL_CHECKS - FAILED_CHECKS)); checks_failed=$FAILED_CHECKS"
            exit 1
        else
            echo "CRITICAL - $FAILED_CHECKS/$TOTAL_CHECKS checks failed | checks_passed=$((TOTAL_CHECKS - FAILED_CHECKS)); checks_failed=$FAILED_CHECKS"
            exit 2
        fi
    else
        echo ""
        echo "=========================================="
        
        if [ "$HEALTH_STATUS" = "OK" ]; then
            log_success "Overall Status: HEALTHY"
            echo -e "${GREEN}✅ All $TOTAL_CHECKS health checks passed${NC}"
            exit 0
        elif [ "$HEALTH_STATUS" = "WARNING" ]; then
            log_warning "Overall Status: WARNING"
            echo -e "${YELLOW}⚠️  $FAILED_CHECKS/$TOTAL_CHECKS health checks failed${NC}"
            exit 1
        else
            log_error "Overall Status: UNHEALTHY"
            echo -e "${RED}❌ $FAILED_CHECKS/$TOTAL_CHECKS health checks failed${NC}"
            exit 2
        fi
    fi
}

# Check for required dependencies
if ! command -v curl &> /dev/null; then
    echo "Error: curl is required but not installed"
    exit 3
fi

if ! command -v bc &> /dev/null; then
    echo "Error: bc is required but not installed"
    exit 3
fi

# Run main function
main "$@"