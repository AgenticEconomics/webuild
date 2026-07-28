# WeBuild Cloud Sandbox Image (Phase V + VI)

Custom ACS image: full `webuild` CLI + toolchain + Phase VI agent skills.
Replaces the Phase II–IV ConfigMap-injected Python chat agent for
`environment_id=default`.

## Build (local)

```bash
# Use a release/CI linux amd64 binary
cp ~/.webuild/bin/webuild sandbox/webuild-linux-x86_64
# or: cp dist/webuild-linux-x86_64 sandbox/

# Phase VI skills marketplace (WeBuild layout)
rm -rf sandbox/agent-skills
cp -a third_party/agent-skills sandbox/agent-skills

docker build -t webuild-sandbox:local sandbox/
```

## Runtime

`sandbox-init.sh` (ENTRYPOINT):

1. Optional git clone into `/workspace`
2. Write `DASHSCOPE_API_KEY` / YOLO config
3. `webuild agent --yolo -m $MODEL --webuild-ws-url 'wss://…/ws/relay?session_id=…&role=agent&token=…' headless`

On agent init, WeBuild syncs `/opt/webuild/agent-skills` into
`~/.webuild/marketplaces/agent-skills` and auto-installs `default-skills`
(17 skills from AgenticEconomics/skills). See
`docs/phase-vi-skills-import-plan.md`.

Env: see `docs/phase-v-sandbox-full-agent-plan.md` §V1.

Fallback: `SANDBOX_AGENT=python` runs legacy `sandbox_agent.py`.
