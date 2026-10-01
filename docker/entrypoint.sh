#!/usr/bin/env bash
# APEX-OS Container Entrypoint
# Handles service initialization, health checks, and graceful shutdown

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================
readonly LOG_LEVEL="${APEX_OS_LOG_LEVEL:-info}"
readonly SERVICE="${1:-all}"
readonly SHUTDOWN_TIMEOUT=30
readonly HEALTH_CHECK_INTERVAL=5
readonly HEALTH_CHECK_RETRIES=12

# ============================================================================
# Logging
# ============================================================================
log() {
    local level="$1"
    shift
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [${level}] $*" >&2
}

info() { log "INFO" "$@"; }
warn() { log "WARN" "$@"; }
error() { log "ERROR" "$@"; }
debug() { [[ "${LOG_LEVEL}" == "debug" ]] && log "DEBUG" "$@"; }

# ============================================================================
# Signal Handling — Graceful Shutdown
# ============================================================================
SHUTDOWN_REQUESTED=0

shutdown_handler() {
    local signal="$1"
    warn "Received ${signal}, initiating graceful shutdown..."
    SHUTDOWN_REQUESTED=1

    # Stop all background processes
    if [[ -n "${CHILD_PIDS:-}" ]]; then
        for pid in ${CHILD_PIDS}; do
            if kill -0 "${pid}" 2>/dev/null; then
                info "Stopping process ${pid}..."
                kill -TERM "${pid}" 2>/dev/null || true
            fi
        done

        # Wait for processes to terminate
        local count=0
        while [[ ${count} -lt ${SHUTDOWN_TIMEOUT} ]]; do
            local all_dead=1
            for pid in ${CHILD_PIDS}; do
                if kill -0 "${pid}" 2>/dev/null; then
                    all_dead=0
                    break
                fi
            done
            [[ ${all_dead} -eq 1 ]] && break
            sleep 1
            ((count++))
        done

        # Force kill if still running
        for pid in ${CHILD_PIDS}; do
            if kill -0 "${pid}" 2>/dev/null; then
                warn "Force killing process ${pid}..."
                kill -KILL "${pid}" 2>/dev/null || true
            fi
        done
    fi

    info "Shutdown complete"
    exit 0
}

trap 'shutdown_handler SIGTERM' SIGTERM
trap 'shutdown_handler SIGINT' SIGINT
trap 'shutdown_handler SIGHUP' SIGHUP

# ============================================================================
# Health Check
# ============================================================================
health_check() {
    local service="$1"
    local port="$2"
    local endpoint="${3:-/health}"
    local url="http://localhost:${port}${endpoint}"

    debug "Health check: ${url}"

    if curl -sf -o /dev/null --max-time 5 "${url}" 2>/dev/null; then
        return 0
    fi
    return 1
}

wait_for_healthy() {
    local service="$1"
    local port="$2"
    local endpoint="${3:-/health}"
    local max_retries="${4:-${HEALTH_CHECK_RETRIES}}"

    info "Waiting for ${service} to become healthy..."
    local i
    for i in $(seq 1 ${max_retries}); do
        if [[ ${SHUTDOWN_REQUESTED} -eq 1 ]]; then
            warn "Shutdown requested while waiting for ${service}"
            return 1
        fi

        if health_check "${service}" "${port}" "${endpoint}"; then
            info "${service} is healthy"
            return 0
        fi

        debug "Health check ${i}/${max_retries} failed for ${service}, retrying in ${HEALTH_CHECK_INTERVAL}s..."
        sleep "${HEALTH_CHECK_INTERVAL}"
    done

    error "${service} failed to become healthy after ${max_retries} attempts"
    return 1
}

# ============================================================================
# Dependency Checks
# ============================================================================
check_dependencies() {
    info "Checking dependencies..."

    # Check PostgreSQL
    if [[ -n "${DATABASE_URL:-}" ]]; then
        local pg_host
        pg_host=$(echo "${DATABASE_URL}" | sed -n 's/.*@\([^:]*\).*/\1/p')
        local pg_port
        pg_port=$(echo "${DATABASE_URL}" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
        pg_port="${pg_port:-5432}"

        info "Waiting for PostgreSQL at ${pg_host}:${pg_port}..."
        local i
        for i in $(seq 1 30); do
            if nc -z "${pg_host}" "${pg_port}" 2>/dev/null; then
                info "PostgreSQL is available"
                break
            fi
            if [[ ${i} -eq 30 ]]; then
                error "PostgreSQL not available after 30 attempts"
                return 1
            fi
            sleep 2
        done
    fi

    # Check Redis
    if [[ -n "${REDIS_URL:-}" ]]; then
        local redis_host
        redis_host=$(echo "${REDIS_URL}" | sed -n 's|redis://\([^:]*\).*|\1|p')
        local redis_port
        redis_port=$(echo "${REDIS_URL}" | sed -n 's|redis://[^:]*:\([0-9]*\).*|\1|p')
        redis_port="${redis_port:-6379}"

        info "Waiting for Redis at ${redis_host}:${redis_port}..."
        local i
        for i in $(seq 1 30); do
            if nc -z "${redis_host}" "${redis_port}" 2>/dev/null; then
                info "Redis is available"
                break
            fi
            if [[ ${i} -eq 30 ]]; then
                error "Redis not available after 30 attempts"
                return 1
            fi
            sleep 2
        done
    fi

    return 0
}

# ============================================================================
# Service Starters
# ============================================================================
start_apexmm() {
    info "Starting ApexAMM (Predictive Market Making)..."

    # Initialize ApexAMM
    python3 -c "
import sys
sys.path.insert(0, '/app')
try:
    from apexmm import initialize
    initialize()
except ImportError:
    print('ApexAMM module not found, skipping initialization')
except Exception as e:
    print(f'ApexAMM initialization warning: {e}')
" 2>/dev/null || warn "ApexAMM initialization skipped"

    # Start ApexAMM server
    exec python3 -m apexmm.server \
        --host 0.0.0.0 \
        --port 8000 \
        --log-level "${LOG_LEVEL}"
}

start_apexull() {
    info "Starting Apex_ULL (Ultra-Low Latency Infrastructure)..."

    # Check for Rust binaries
    if [[ -x /app/Apex_ULL/bin/apexull ]]; then
        exec /app/Apex_ULL/bin/apexull \
            --mode "${APEX_ULL_FEED_HANDLER_MODE:-simulation}" \
            --metrics-port 9090
    else
        # Fallback to Python simulation
        warn "Apex_ULL binary not found, using Python fallback"
        exec python3 -m apexull.server \
            --host 0.0.0.0 \
            --port 8080 \
            --log-level "${LOG_LEVEL}"
    fi
}

start_dcc() {
    info "Starting DCC (Data Center Commander)..."

    # Run database migrations
    if [[ -f /app/dcc/migrations/run.py ]]; then
        info "Running DCC database migrations..."
        python3 /app/dcc/migrations/run.py 2>/dev/null || warn "DCC migrations skipped"
    fi

    # Start DCC API server
    exec python3 -m dcc.server \
        --host 0.0.0.0 \
        --port 8000 \
        --log-level "${LOG_LEVEL}"
}

start_all() {
    info "Starting all APEX-OS services..."

    check_dependencies || exit 1

    # Start services in background
    CHILD_PIDS=""

    start_apexmm &
    CHILD_PIDS="${CHILD_PIDS} $!"

    start_apexull &
    CHILD_PIDS="${CHILD_PIDS} $!"

    start_dcc &
    CHILD_PIDS="${CHILD_PIDS} $!"

    # Wait for all services
    local exit_code=0
    for pid in ${CHILD_PIDS}; do
        if ! wait "${pid}"; then
            error "Process ${pid} exited with error"
            exit_code=1
        fi
    done

    return ${exit_code}
}

# ============================================================================
# Main
# ============================================================================
main() {
    info "APEX-OS Container Starting"
    info "Service: ${SERVICE}"
    info "Log Level: ${LOG_LEVEL}"
    info "Python Path: ${PYTHONPATH:-not set}"

    case "${SERVICE}" in
        apexmm)
            check_dependencies || exit 1
            start_apexmm
            ;;
        apexull)
            start_apexull
            ;;
        dcc)
            check_dependencies || exit 1
            start_dcc
            ;;
        all)
            start_all
            ;;
        health)
            # Health check mode — used by Docker HEALTHCHECK
            local healthy=0
            health_check "ApexAMM" 8000 || healthy=1
            health_check "Apex_ULL" 8080 || healthy=1
            health_check "DCC" 8001 || healthy=1
            exit ${healthy}
            ;;
        *)
            error "Unknown service: ${SERVICE}"
            echo "Usage: $0 {apexmm|apexull|dcc|all|health}"
            exit 1
            ;;
    esac
}

main "$@"
