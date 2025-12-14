# ETF MCP Server - Docker Deployment
# Version: 1.1.0 - Force rebuild to ensure tushare is installed
# Use an official Python runtime as the base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy dependency file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -c "import tushare; print(f'Tushare {tushare.__version__} installed successfully')"

# Copy the rest of the application code
COPY . .

# Give execute permission to start script
RUN chmod +x start.sh

# Expose the port (Smithery uses 8081)
EXPOSE 8081

# Health check (uses PORT environment variable, defaults to 8081)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8081}/health || exit 1

# Command to run the server using start script
CMD ["./start.sh"]
