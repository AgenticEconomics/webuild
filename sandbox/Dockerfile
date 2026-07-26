FROM ubuntu:24.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget ca-certificates \
    build-essential gcc g++ make \
    python3 python3-pip python3-venv \
    nodejs npm \
    ripgrep fd-find \
    openssh-client \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for sandbox execution
RUN groupadd -g 1000 sandbox && \
    useradd -u 1000 -g sandbox -m -s /bin/bash sandbox

# Install webuild binary (from CI artifact or local build)
COPY webuild-linux-x86_64 /usr/local/bin/webuild
RUN chmod +x /usr/local/bin/webuild

# Copy init script
COPY scripts/sandbox-init.sh /opt/sandbox-init.sh
RUN chmod +x /opt/sandbox-init.sh

# Workspace directory
RUN mkdir -p /workspace && chown sandbox:sandbox /workspace

WORKDIR /workspace

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD pgrep -f "webuild" > /dev/null || exit 1

# Run as non-root
USER sandbox

# Entry: headless agent mode
ENTRYPOINT ["/opt/sandbox-init.sh"]
