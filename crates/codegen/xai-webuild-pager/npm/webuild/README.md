# WeBuild

Terminal AI coding agent (independent fork). Default model: **qwen3.7-max**.

**[Repository](https://github.com/AgenticEconomics/webuild)** · **[Releases](https://github.com/AgenticEconomics/webuild/releases)**

## Install

```bash
# Recommended: prebuilt binary (Linux / macOS Apple Silicon)
curl -fsSL https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh | bash
export PATH="$HOME/.webuild/bin:$PATH"
```

Or install with npm (when platform packages are published):

```bash
npm i -g @webuild/webuild
```

## Get Started

```bash
export DASHSCOPE_API_KEY="sk-..."   # or QWEN_API_KEY — default model qwen3.7-max
webuild                             # interactive TUI
webuild -p "Explain this codebase" --always-approve
```

Optional xAI models: `export XAI_API_KEY=...` then `webuild -m grok-build`.

## Update

Re-run the curl installer, or:

```bash
webuild update   # when configured for GitHub Releases / npm
# npm i -g @webuild/webuild@latest
```

## Supported Platforms (prebuilt)

| Platform | Architecture |
|---|---|
| macOS | Apple Silicon (arm64) |
| Linux | x86_64, arm64 |

macOS Intel: build from source. See the [repository README](https://github.com/AgenticEconomics/webuild#readme).

## Documentation

In the TUI: `/howto` or `/docs`. Online: [GitHub README](https://github.com/AgenticEconomics/webuild#readme).
