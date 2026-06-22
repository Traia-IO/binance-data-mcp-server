# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN chmod +x /usr/local/bin/uv

# Create non-root user
RUN useradd -m -u 1000 appuser

# Create app directory and set ownership
RUN mkdir -p /app && chown -R appuser:appuser /app

# Set working directory
WORKDIR /app

# Switch to non-root user
USER appuser

# Copy project files
COPY --chown=appuser:appuser . .

# Optional local package override for IATP source builds.
RUN if [ -d .docker-iatp/IATP ]; then \
        cp -r .docker-iatp/IATP /tmp/IATP && \
        echo "Using local IATP package (local development mode)"; \
    else \
        echo "Using published IATP package (remote deployment mode)"; \
    fi

# Install Python dependencies
RUN uv venv .venv && \
    uv pip install -r pyproject.toml

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1
ENV UV_SYSTEM_PYTHON=1
ENV STAGE=MAINNET
ENV LOG_LEVEL=INFO

# Health check - uses dedicated health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Expose port (uses PORT environment variable with default)
EXPOSE ${PORT:-8080}

# Run the application
CMD ["uv", "run", "python", "server.py"]