# APEX-OS Multi-Stage Dockerfile
# Builds all three systems: ApexAMM (Python), Apex_ULL (Rust/C++), DCC (Python/Node.js)

# ============================================================================
# Stage 1: Base — shared dependencies
# ============================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ============================================================================
# Stage 2: Python builder — ApexAMM + DCC Python deps
# ============================================================================
FROM base AS python-builder

COPY pyproject.toml README.md ./
COPY apexmm/ ./apexmm/ 2>/dev/null || true
COPY dcc/ ./dcc/ 2>/dev/null || true

RUN pip install --upgrade pip setuptools wheel && \
    pip install -e ".[apexmm,ull,dcc]" 2>/dev/null || \
    pip install numpy scipy pandas "psycopg[binary,pool]>=3.2,<4" \
        opentelemetry-api opentelemetry-sdk

# ============================================================================
# Stage 3: Node.js builder — DCC data-center-commander
# ============================================================================
FROM node:20-slim AS node-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
COPY data-center-commander/ ./data-center-commander/ 2>/dev/null || true

RUN npm install --workspaces --if-present 2>/dev/null || npm install

# ============================================================================
# Stage 4: Rust builder — Apex_ULL
# ============================================================================
FROM rust:1.75-slim AS rust-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY Apex_ULL/ ./Apex_ULL/ 2>/dev/null || true

RUN if [ -f Apex_ULL/Cargo.toml ]; then \
        cd Apex_ULL && cargo build --release; \
    else \
        echo "No Apex_ULL Cargo.toml found, skipping Rust build"; \
    fi

# ============================================================================
# Stage 5: Final — production image
# ============================================================================
FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    APEX_OS_ENV=production \
    APEX_OS_LOG_LEVEL=info

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r apex && useradd -r -g apex -d /app -s /sbin/nologin apex

WORKDIR /app

# Copy Python packages from builder
COPY --from=python-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-builder /usr/local/bin /usr/local/bin

# Copy Node.js application
COPY --from=node-builder /app/data-center-commander ./data-center-commander
COPY --from=node-builder /app/node_modules ./node_modules

# Copy Rust binaries
COPY --from=rust-builder /app/Apex_ULL/target/release/ ./Apex_ULL/bin/ 2>/dev/null || true

# Copy application code
COPY pyproject.toml README.md ./
COPY apexmm/ ./apexmm/ 2>/dev/null || true
COPY dcc/ ./dcc/ 2>/dev/null || true
COPY Apex_ULL/ ./Apex_ULL/ 2>/dev/null || true
COPY docs/ ./docs/
COPY compliance/ ./compliance/
COPY patents/ ./patents/

# Copy entrypoint script
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Create necessary directories
RUN mkdir -p /app/logs /app/data /app/tmp && \
    chown -R apex:apex /app

USER apex

EXPOSE 8000 8080 9090

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["all"]
