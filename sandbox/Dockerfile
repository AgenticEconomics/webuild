FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Use Aliyun mirrors for China
RUN sed -i 's|archive.ubuntu.com|mirrors.aliyun.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null; \
    sed -i 's|security.ubuntu.com|mirrors.aliyun.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null; true

# Install dev tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget ca-certificates \
    build-essential gcc g++ make \
    python3 python3-pip python3-venv \
    nodejs npm \
    ripgrep fd-find \
    openssh-client \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Use existing ubuntu user (UID 1000 in Ubuntu 24.04)
# No need to create — already exists with UID/GID 1000

# Install Python agent dependencies
COPY requirements.txt /opt/sandbox/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages \
    -r /opt/sandbox/requirements.txt \
    --index-url https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com

# Copy sandbox agent
COPY agent/sandbox_agent.py /opt/sandbox/sandbox_agent.py
COPY scripts/sandbox-init.sh /opt/sandbox/sandbox-init.sh
RUN chmod +x /opt/sandbox/sandbox-init.sh

# Workspace directory
RUN mkdir -p /workspace && chown 1000:1000 /workspace

WORKDIR /workspace

# Health check: verify agent is listening on 8080
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD pgrep -f sandbox_agent > /dev/null || exit 1

# Run as non-root (ubuntu user, UID 1000)
USER ubuntu

# Start the sandbox agent WebSocket server
CMD ["python3", "/opt/sandbox/sandbox_agent.py"]
