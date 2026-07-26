# GitLab Runner & CI/CD Setup

## Runner Provisioning

1. Install gitlab-runner:
   ```bash
   curl -L https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh | sudo bash
   sudo apt install gitlab-runner
   ```

2. Replace `REPLACE_WITH_RUNNER_TOKEN` in `config.toml` with the runner registration token
   (GitLab → Admin → CI/CD → Runners → Register → token)

3. Deploy config and start service:
   ```bash
   sudo ./setup.sh
   ```

### Host Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Rust (rustup) | pinned in `rust-toolchain.toml` | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| protoc | >= 3.15 | `apt install protobuf-compiler` |
| ripgrep | any | `apt install ripgrep` |

Grant the `gitlab-runner` user access to the Rust toolchain:
```bash
chmod o+rx /root
chmod -R o+rX /root/.cargo /root/.rustup
```

### Runner Tags

| Tag | Platform |
|-----|----------|
| `linux` | Linux x86_64 / aarch64 |
| `macos` | macOS Apple Silicon |
| `docker` | Docker executor |

## CI/CD Variables

Configure in **GitLab → Settings → CI/CD → Variables**:

| Key | Value | Masked | Protected | Description |
|-----|-------|--------|-----------|-------------|
| `GITLAB_RELEASE_TOKEN` | PAT with `api` scope | ✅ | ❌ | Used by the publish job to upload release assets and create GitLab Releases. Generate at User Settings → Access Tokens with `api` scope. |

### Pipeline Variables (in `.gitlab-ci.yml`)

These are defined in the pipeline config, not in GitLab UI:

| Key | Value | Description |
|-----|-------|-------------|
| `CARGO_TERM_COLOR` | `always` | Colored cargo output |
| `RUST_BACKTRACE` | `1` | Full backtraces on panic |
| `GITLAB_HOST` | `https://git.jarvikheart.cn` | GitLab instance URL |
| `RUSTUP_DIST_SERVER` | `https://rsproxy.cn` | Rust toolchain mirror (China) |
| `RUSTUP_UPDATE_ROOT` | `https://rsproxy.cn/rustup` | Rustup mirror (China) |

### Runner Environment Variables (in `config.toml`)

Passed to every CI job via the runner:

| Key | Value | Description |
|-----|-------|-------------|
| `RUSTUP_DIST_SERVER` | `https://rsproxy.cn` | Rust mirror for toolchain downloads |
| `RUSTUP_UPDATE_ROOT` | `https://rsproxy.cn/rustup` | Rustup mirror |
| `RUSTUP_HOME` | `/root/.rustup` | Toolchain storage location |
| `CARGO_HOME` | `/root/.cargo` | Cargo registry and binaries |
| `PATH` | `/root/.cargo/bin:...` | Ensure cargo/rustc are on PATH |

## Release Flow

```
git tag v0.4.2 && git push origin v0.4.2
        │
        ▼
  ┌──────────┐    ~22min    ┌───────────┐    ~3min
  │  build   │─────────────▶│  publish   │
  │  (cargo) │  artifacts   │ (release)  │
  └──────────┘   .tar.gz    └───────────┘
```

1. **build** — `cargo build --release`, produces `dist/webuild-*.tar.gz`
2. **publish** — uploads tar.gz via `/uploads` API, creates GitLab Release with asset links

Trigger: tag matching `v*`, manual web run, or scheduled pipeline.
