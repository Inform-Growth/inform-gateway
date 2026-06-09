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
    git \
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

# Install uv (provides `uvx` — used to run the Google Workspace MCP server in
# an isolated env without polluting the gateway's Python deps).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Copy the rest of the application
COPY . .

# Ensure the vendor directory install also runs
RUN npm install --prefix remote-gateway/vendor attio-mcp@^1.6.1 @modelcontextprotocol/server-github

# Build the admin-ui (React + Vite) — Node 20 is already installed above.
COPY remote-gateway/admin-ui/package*.json /app/remote-gateway/admin-ui/
WORKDIR /app/remote-gateway/admin-ui
RUN npm install
COPY remote-gateway/admin-ui /app/remote-gateway/admin-ui
RUN npm run build
WORKDIR /app

# Start the gateway, mapping Railway's PORT to MCP_SERVER_PORT
# We use python3 for maximum compatibility in the slim image
CMD ["sh", "-c", "if [ -n \"$GOOGLE_SA_JSON\" ]; then printf '%s' \"$GOOGLE_SA_JSON\" > /tmp/google-sa.json && export GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-sa.json; fi && MCP_SERVER_PORT=${PORT:-8000} python3 remote-gateway/core/mcp_server.py"]
