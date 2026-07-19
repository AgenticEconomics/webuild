# WeBuild

Terminal-based AI coding agent — fork of [Grok Build](https://x.ai/cli), rebranded for independent development.

CLI name: `webuild` · config home: `~/.webuild` · env prefix: `WEBUILD_*`

**Default model:** `qwen3.7-max` (OpenAI-compatible chat completions via DashScope).
System catalog lives in
[`crates/codegen/xai-webuild-models/default_models.json`](crates/codegen/xai-webuild-models/default_models.json)
— default ID, built-in rows, per-model `base_url` / `api_backend` / `env_key`.

Switch models anytime (`/model`, `Ctrl+M`, `-m`, or `[models] default` /
`[model.*]` in `~/.webuild/config.toml`), including baked-in `grok-build` (xAI)
and any custom provider. Set `DASHSCOPE_API_KEY` or `QWEN_API_KEY` for the
default Qwen endpoint; use `webuild login` / `XAI_API_KEY` when on xAI models.

---

## Install (end users)

After a [GitHub Release](https://github.com/AgenticEconomics/webuild/releases) is published:

```sh
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh | bash

# Optional: pin a version
curl -fsSL https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh | bash -s -- v0.2.102

export PATH="$HOME/.webuild/bin:$PATH"
export DASHSCOPE_API_KEY="..."
webuild --version
webuild
```

Binary lands in `~/.webuild/bin/webuild`. See [Publishing](#publishing-curl--bash) below.

---

## Build from source

```sh
# Needs: Rust (rust-toolchain.toml), DotSlash or system protoc on PATH
cargo run -p xai-webuild-pager-bin              # build + launch the TUI
cargo build -p xai-webuild-pager-bin --release  # target/release/xai-webuild-pager
cargo check -p xai-webuild-pager-bin            # fast validation
```

---

## Repository layout

| Path | Role |
|------|------|
| `crates/codegen/` | Product crates: TUI, agent runtime, tools, config, workspace |
| `crates/common/` | Shared leaf libraries (tools protocol, compaction, tracing, …) |
| `crates/build/` | Build-time helpers (`xai-proto-build`) |
| `prod/mc/` | Shared types with chat-proxy / MC services |
| `third_party/` | Vendored Mermaid diagram stack |
| `bin/` | DotSlash-wrapped hermetic tools (e.g. `protoc`) |

---

## Crate responsibilities

### Entry & TUI

| Crate | Responsibility |
|-------|----------------|
| **xai-webuild-pager-bin** | Composition root; links pager + optional minimal UI; produces `xai-webuild-pager` binary |
| **xai-webuild-pager** | Full-screen TUI: scrollback, prompt, modals, slash commands, session UX |
| **xai-webuild-pager-minimal** | Alternate “minimal” screen mode |
| **xai-webuild-pager-render** | Themes, syntax highlighting, render primitives |
| **xai-webuild-pager-pty-harness** | PTY test harness for the pager |

### Agent runtime

| Crate | Responsibility |
|-------|----------------|
| **xai-webuild-shell** | Agent loop, leader/stdio/headless entry points, orchestration |
| **xai-webuild-shell-base** | Shell-facing primitives (home helpers, shared base types) |
| **xai-webuild-shell-session-support** | Session persistence / resume support |
| **xai-webuild-agent** | Agent lifecycle glue beyond the shell loop |
| **xai-webuild-subagent-resolution** | Sub-agent discovery and routing |
| **xai-webuild-sampler** / **sampling-types** | Model sampling, request/response streaming types |
| **xai-webuild-memory** | Long-term / session memory |
| **xai-webuild-compaction** (`crates/common`) | Context compaction (shared with chat hosts) |

### Tools & execution

| Crate | Responsibility |
|-------|----------------|
| **xai-webuild-tools** | Tool implementations (`webuild_build`, concise/hashline variants, MCP bridges, …) |
| **xai-webuild-tools-api** | Protobuf / gRPC surface for tools |
| **xai-tool-*** (`common`) | Tool types, protocol, runtime engine |
| **xai-webuild-sandbox** | Sandboxed command execution |
| **xai-webuild-workspace** | Host FS, VCS, checkpoints, permissions, worktrees |
| **xai-webuild-workspace-client** / **workspace-types** | Workspace IPC client + shared types |
| **xai-webuild-paths** | Path normalization helpers |

### Config, auth, env

| Crate | Responsibility |
|-------|----------------|
| **xai-webuild-config** / **config-types** | `~/.webuild` config load/merge, typed settings |
| **xai-webuild-env** | Deploy endpoints, environment resolution |
| **xai-webuild-auth** | Login / credentials |
| **xai-webuild-hooks** | Project & user hooks |
| **xai-webuild-plugin-marketplace** | Plugin discovery / install |
| **xai-webuild-secrets** | Secret storage |
| **xai-webuild-models** | Model catalog (`default_models.json`) |

### Platform services

| Crate | Responsibility |
|-------|----------------|
| **xai-webuild-http** | HTTP client, User-Agent, shared headers |
| **xai-webuild-mcp** | MCP server integration |
| **xai-webuild-telemetry** | Analytics / OTLP events |
| **xai-webuild-update** / **version** | Auto-update + version strings |
| **xai-webuild-voice** | Voice / STT |
| **xai-webuild-markdown** / **markdown-core** / **mermaid** | Markdown + diagram rendering |
| **xai-webuild-announcements** | In-product announcements |
| **xai-webuild-shared** / **test-support** | Cross-cutting helpers + test fixtures |

### Supporting codegen (unprefixed `xai-*`)

ACP editor protocol (`xai-acp-lib`), chat state, codebase graph, crash handler, fast worktrees, git status, hunk tracker, prompt queue, ratatui widgets, sqlite journal, token estimation, etc. — infrastructure used by the WeBuild closure but not product-branded.

### Common / prod / third_party

- **common**: circuit breaker, computer-hub SDK/adapters, interjection core, tracing
- **prod/mc/cli-chat-proxy-types**: shared wire types with the chat proxy
- **third_party**: Mermaid → SVG (`mermaid-to-svg`, `dagre_rust`, `graphlib_rust`, `ordered_hashmap`)

---

## Naming map (upstream → WeBuild)

| Surface | Upstream | WeBuild |
|---------|----------|---------|
| CLI | `grok` | `webuild` |
| Cargo packages | `xai-grok-*` | `xai-webuild-*` |
| Binary artifact | `xai-grok-pager` | `xai-webuild-pager` |
| Config dir | `~/.grok` | `~/.webuild` |
| Env vars | `GROK_*` | `WEBUILD_*` |
| Tool namespace | `grok_build` | `webuild_build` |
| npm | `@xai-official/grok` | `@webuild/webuild` |

**Default inference:** `qwen3.7-max` → DashScope OpenAI-compatible endpoint +
`chat_completions` protocol (see `default_models.json`).

**Still available for switching:** xAI slugs (`grok-build`, …), `*.grok.com` /
`api.x.ai` dual routing on those rows, custom `[model.*]` providers.

**Intentionally kept (compatibility):** `x-grok-*` / `x-webuild-*` request
headers, some `grok_code.*` telemetry names, Apache license / third-party notices.

---

## Development

Requirements: Rust (see `rust-toolchain.toml`), [DotSlash](https://dotslash-cli.com) on `PATH` for `bin/protoc`.

```sh
cargo check -p <crate>           # prefer per-crate; full workspace is heavy
cargo test -p xai-webuild-config
cargo clippy -p <crate>
cargo fmt --all
```

Upstream layout notes (pre-rename) are archived in [`WEBUILD_README.md`](WEBUILD_README.md).

---

## Publishing (`curl | bash`)

Goal: users run one curl and get a working `webuild` on Linux/macOS without compiling.

### How it works

```text
You (maintainer)                         Users
─────────────────                        ─────
1. tag vX.Y.Z                            curl install.sh | bash
2. GitHub Actions builds                 → GitHub API: latest release
   linux/mac binaries                    → download webuild-<os>-<arch>
3. Assets attached to Release            → install ~/.webuild/bin/webuild
4. install.sh on main branch             → print PATH + quick start
```

| Piece | Path |
|-------|------|
| Installer | [`scripts/install.sh`](scripts/install.sh) |
| CI release | [`.github/workflows/release.yml`](.github/workflows/release.yml) |
| Asset names | `webuild-linux-x86_64`, `webuild-linux-aarch64`, `webuild-macos-aarch64`, `webuild-macos-x86_64` (+ `.tar.gz`) |

### One-time setup

1. Repo **Settings → Actions → General**: allow workflows to create releases (default `GITHUB_TOKEN` contents:write is enough for public repos).
2. Ensure `main` contains `scripts/install.sh` (so the raw.githubusercontent.com URL works).
3. Optional: custom domain later  
   `curl -fsSL https://your.domain/install.sh | bash`  
   just host the same script + point `WEBUILD_REPO` or hardcode your fork.

### Cut a release

```sh
# From a clean, tested main:
git checkout main
git pull

# Tag must match workflow filter: v*
git tag v0.2.103
git push origin v0.2.103
```

Or **Actions → Release → Run workflow** and enter a tag.

Wait for the workflow to finish (first build can take 15–40+ minutes per platform). Confirm assets appear under:

https://github.com/AgenticEconomics/webuild/releases

### Verify as a user

```sh
curl -fsSL https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh | bash
export PATH="$HOME/.webuild/bin:$PATH"
webuild --version
```

### Local dry-run (no GitHub Release yet)

```sh
# Build one platform yourself
cargo build -p xai-webuild-pager-bin --release
cp target/release/xai-webuild-pager /tmp/webuild-linux-x86_64

# Manual install path users effectively get:
mkdir -p ~/.webuild/bin
cp /tmp/webuild-linux-x86_64 ~/.webuild/bin/webuild
chmod +x ~/.webuild/bin/webuild
export PATH="$HOME/.webuild/bin:$PATH"
```

### Notes

- **Windows**: this curl installer is Unix-only; ship a `.exe` asset + PowerShell later if needed (`install.ps1` still exists under pager scripts for the upstream layout).
- **Private repo**: users need `GITHUB_TOKEN=...` with `repo` scope when running install.sh.
- **Auto-update**: in-app `webuild update` still points at upstream x.ai channels until you rewire `xai-webuild-update` to GitHub Releases; until then tell users to re-run the curl installer.
- **CI time/cost**: four native runners; disable unused arches in the workflow matrix if you only need linux-x64 + macos-arm64.
