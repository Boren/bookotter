# Multi-stage build for BookOtter

# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

# Enable corepack for pnpm
RUN corepack enable

# Copy package files
COPY frontend/package.json frontend/pnpm-lock.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy frontend source
COPY frontend/ ./

# Build for production
RUN pnpm build

# Stage 2: Python backend with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BOOKOTTER_DATA_DIR=/app/data

WORKDIR /app

# Install system dependencies (gcc needed for some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
# UID/GID 1000 is typical for the first user on Linux systems
RUN groupadd -g 1000 bookotter && \
    useradd -m -u 1000 -g bookotter bookotter

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies with uv (10-100x faster than pip)
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy backend source
COPY --chown=bookotter:bookotter backend/ ./backend/

# Copy built frontend from previous stage
COPY --chown=bookotter:bookotter --from=frontend-build /app/frontend/dist ./static/

# Create data directory with proper ownership
RUN mkdir -p /app/data && chown -R bookotter:bookotter /app/data

# Expose port
EXPOSE 6887

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:6887/api/health')" || exit 1

# Switch to non-root user
USER bookotter

# Run the application
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "6887"]
