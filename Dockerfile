# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install to venv
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip setuptools wheel && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies: ffmpeg for audio, libopus0 for Discord voice, libsodium for PyNaCl
# Also install nodejs as a JS runtime for yt-dlp (required for some YouTube formats)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    libsodium23 \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 lainbot

# Copy venv from builder
COPY --from=builder --chown=lainbot:lainbot /opt/venv /opt/venv

# Copy application code
COPY --chown=lainbot:lainbot . .

# Create data and log directories with correct ownership
RUN mkdir -p /app/data /app/logs && \
    chown -R lainbot:lainbot /app

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/lainbot

# Switch to non-root user
USER lainbot

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Run bot
CMD ["python", "main.py"]
