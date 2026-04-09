# Use Python 3.11 slim as the base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_MAJOR=20 \
    PATH="/app/node_modules/.bin:/app/remote-gateway/vendor/node_modules/.bin:${PATH}"

# Set working directory
WORKDIR /app

# Install system dependencies and Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    build-essential \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy configuration files first for better caching
COPY pyproject.toml package.json ./

# Install Python and Node.js dependencies
# Note: package.json install will put tools in /app/node_modules/.bin
RUN pip install --no-cache-dir -e . && \
    npm install

# Copy the rest of the application
COPY . .

# Ensure the vendor directory install also runs if needed (redundant but safe based on your previous config)
RUN npm install --prefix remote-gateway/vendor attio-mcp @modelcontextprotocol/server-github

# Expose the gateway port
EXPOSE 8000

# Set health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Start the gateway
CMD ["python", "remote-gateway/core/mcp_server.py"]
