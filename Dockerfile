# Use Python 3.11 slim as the base image
FROM python:3.11-slim

# Set environment variables
# MCP_TRANSPORT=sse is CRITICAL for Railway/Remote deployment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_MAJOR=20 \
    MCP_TRANSPORT=sse \
    MCP_SERVER_HOST=0.0.0.0 \
    PATH="/app/node_modules/.bin:/app/remote-gateway/vendor/node_modules/.bin:${PATH}"

# Set working directory
WORKDIR /app

# Install system dependencies, Node.js, and curl
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
RUN pip install --no-cache-dir -e . && \
    npm install

# Copy the rest of the application
COPY . .

# Ensure the vendor directory install also runs
RUN npm install --prefix remote-gateway/vendor attio-mcp @modelcontextprotocol/server-github

# Expose the gateway port (Railway provides this via PORT env var)
EXPOSE 8000

# Start the gateway, mapping Railway's PORT to MCP_SERVER_PORT
CMD ["sh", "-c", "MCP_SERVER_PORT=${PORT:-8000} python remote-gateway/core/mcp_server.py"]
