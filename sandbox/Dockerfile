FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV WEBUILD_SANDBOX_MODE=1
ENV WEBUILD_WORKSPACE=/workspace
ENV HOME=/home/ubuntu

# Use Aliyun mirrors for China
RUN sed -i 's|archive.ubuntu.com|mirrors.aliyun.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null; \
    sed -i 's|security.ubuntu.com|mirrors.aliyun.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null; true

# Install dev tools (full agent needs git/node/python/rg for tool execution)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget ca-certificates \
    build-essential gcc g++ make \
    python3 python3-pip python3-venv \
    nodejs npm \
    ripgrep fd-find \
    openssh-client \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Optional legacy Python agent (fallback environment)
COPY requirements.txt /opt/sandbox/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages \
    -r /opt/sandbox/requirements.txt \
    --index-url https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com

COPY agent/sandbox_agent.py /opt/sandbox/sandbox_agent.py
COPY scripts/sandbox-init.sh /opt/sandbox/sandbox-init.sh
RUN chmod +x /opt/sandbox/sandbox-init.sh

# Full WeBuild CLI binary (built by CI as webuild-linux-x86_64)
COPY webuild-linux-x86_64 /usr/local/bin/webuild
RUN chmod +x /usr/local/bin/webuild \
    && ln -sf /usr/local/bin/webuild /usr/local/bin/agent

# Phase VI: vendored AgenticEconomics/skills (WeBuild marketplace layout)
COPY agent-skills /opt/webuild/agent-skills
ENV WEBUILD_AGENT_SKILLS_ROOT=/opt/webuild/agent-skills

# Workspace directory (ubuntu user UID/GID 1000)
RUN mkdir -p /workspace /home/ubuntu/.webuild \
    && chown -R 1000:1000 /workspace /home/ubuntu /opt/webuild

WORKDIR /workspace

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD pgrep -f '[w]ebuild' > /dev/null || pgrep -f '[s]andbox_agent' > /dev/null || exit 1

USER ubuntu

# Init clones repo / writes config, then execs webuild headless (or legacy python)
ENTRYPOINT ["/opt/sandbox/sandbox-init.sh"]
