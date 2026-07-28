# WeBuild Phase V 审计报告 — 沙箱完整 Agent + 全工具能力

> **审计日期**: 2026-07-28
> **审计范围**: Phase V 方案（`docs/phase-v-sandbox-full-agent-plan.md`）已完成项 V1.1–V2.2
> **审计方法**: 5 路并行代码审阅（沙箱镜像 / Gateway / Relay / Rust headless / CI+K8s）
> **审计结论**: 4 项已完成任务代码实现完整，核心路径贯通；1 项上线阻塞（镜像未推送），4 项 P1 需修复，5 项 P2 建议改进

---

## 一、审计概要

### 1.1 方案目标

在 ACS 沙箱 Pod 内运行完整 Rust `webuild` 二进制，具备与本地 CLI 同等的工具能力（bash / read_file / search_replace / list_dir 等），替代 Phase IV 的 Python 文本流式 agent。

### 1.2 方案 Checklist 完成状态

| 任务 | 状态 | 审计结论 |
|------|------|----------|
| **V1.1** 改 `sandbox/Dockerfile` + `sandbox-init.sh` | ✅ 已完成 | 代码正确 |
| **V1.2** 改 Gateway 模板 / k8s_client / compose RELAY_URL | ✅ 已完成 | 代码正确 |
| **V2.1** Relay 接受 Authorization Bearer | ✅ 已完成 | 代码正确 |
| **V2.2** Rust sandbox headless：URL 组装 + 绕过 OIDC + YOLO | ✅ 已完成 | 代码正确 |
| **V1.3** 构建推送 sandbox 镜像 + Gateway 指向 | ⬜ 未完成 | 上线阻塞项 |
| **V3** E2E 验证工具调用 | ⬜ 未完成 | — |
| **V4** Hub 远程工具 | ⬜ 未完成 | 后续阶段 |

---

## 二、逐项审计结果

### 2.1 V1.1 — 沙箱镜像与 Init 脚本

**审计文件**: `sandbox/Dockerfile`, `sandbox/scripts/sandbox-init.sh`, `sandbox/agent/sandbox_agent.py`, `.gitlab-ci.yml`

#### Dockerfile

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 基础镜像含开发工具链 | ✅ | `ubuntu:24.04` + git/node/python3/build-essential/ripgrep/fd-find 等 |
| COPY webuild 二进制 | ✅ | `COPY webuild-linux-x86_64 /usr/local/bin/webuild`，CI 预先拷贝到构建上下文 |
| ENTRYPOINT 直接执行 init | ✅ | `ENTRYPOINT ["/opt/sandbox/sandbox-init.sh"]`，init 脚本用 `exec` 替换进程 |
| HEALTHCHECK 检测 webuild 进程 | ✅ | `pgrep -f '[w]ebuild'`，fallback `pgrep -f '[s]andbox_agent'` |
| 非 root 运行 | ✅ | `USER ubuntu` (UID 1000)，`/workspace` 和 `~/.webuild` 属主正确 |
| 阿里云 apt 镜像 | ✅ | 配置 `mirrors.aliyun.com`，适配国内网络 |

#### Init 脚本 (`sandbox-init.sh`)

| 检查项 | 结果 | 说明 |
|--------|------|------|
| `set -euo pipefail` | ✅ | 严格错误处理 |
| Git clone + safe.directory | ✅ | `git config --global --add safe.directory /workspace` |
| API key 写入 | ✅ | `~/.webuild/api_key`，权限 600 |
| config.toml 写入 | ✅ | `[cli] auto_update = false` + `[sandbox] profile = "off"` + `auto_allow_bash = true` |
| config.toml 字段与 Rust 对齐 | ✅ | Rust 端 `SandboxSettingsConfig` 反序列化 `[sandbox]` table，字段名完全匹配 |
| Relay URL 组装 | ✅ | 正确处理 `?`/`&` 分隔符，拼接 `session_id`/`role`/`token`/`agent_kind`/`user_id` |
| Headless 启动命令 | ✅ | `exec webuild agent --yolo -m "$MODEL" headless --webuild-ws-url "$WS_URL"` |
| Python fallback | ✅ | `SANDBOX_AGENT=python` 时 exec Python agent；webuild 二进制缺失时也 fallback |

#### CI Pipeline

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 二进制缺失 fail | ✅ | `if [ ! -f dist/webuild-linux-x86_64 ]; then exit 1; fi` |
| Sandbox 镜像构建推送 | ✅ | 拷贝二进制到 `sandbox/`，build + push 到 ACR（`$CI_COMMIT_SHA` + `latest`） |
| 触发条件 | ✅ | tag push (`v*`) 或 manual web pipeline |

#### P2 建议

- CI `build-images` job 未声明 `needs: [build]`，依赖 stage 顺序隐式保证，建议显式声明
- Dockerfile 无 build-arg 版本标签，镜像内无法追溯二进制版本

---

### 2.2 V1.2 — Gateway 接线与 Docker Compose

**审计文件**: `services/gateway/src/sandbox_manager.py`, `services/gateway/src/k8s_client.py`, `deploy/docker-compose.yml`, `deploy/docker-compose.override.yml`

#### sandbox_manager.py — 环境模板与 Env 注入

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 默认模板使用 sandbox 镜像 | ✅ | `_DEFAULT_SANDBOX_IMAGE` 读 `SANDBOX_IMAGE` env，默认 ACR 地址 |
| Legacy Python 模板保留 | ✅ | `environment_id="legacy-python"` 独立模板 |
| Env 变量完整注入 | ✅ | SANDBOX_ID, SESSION_ID, WEBUILD_USER_ID, DASHSCOPE_API_KEY, MODEL, RELAY_URL, RELAY_TOKEN, WEBUILD_SANDBOX_MODE, WEBUILD_YOLO, WEBUILD_WORKSPACE, SANDBOX_REPO_URL, SANDBOX_REPO_BRANCH, HUB_WS_URL, RUST_LOG, WEBUILD_LOG |
| RELAY_URL 默认值 | ✅ | `wss://webuild.datoms.cn/ws/relay` |
| RELAY_TOKEN 来源 | ✅ | 读 `RELAY_INTERNAL_TOKEN` env |
| WEBUILD_SANDBOX_MODE | ✅ | 硬编码 `"1"` |
| WEBUILD_YOLO | ✅ | 读 env，默认 `"1"` |
| SANDBOX_AGENT feature flag | ✅ | `legacy-python` → `"python"`，default → `"webuild"` |

#### k8s_client.py — Pod 创建

| 检查项 | 结果 | 说明 |
|--------|------|------|
| webuild 模式无 ConfigMap | ✅ | `agent_mode="webuild"` 时不创建 ConfigMap、不挂载 volume、不覆盖 command |
| Python fallback 保留 | ✅ | `agent_mode="python"` 时走 ConfigMap + pip install 路径 |
| 资源限制 | ✅ | default: CPU 1/4, Memory 2Gi/8Gi, Ephemeral 20Gi — 与方案一致 |
| Capabilities drop ALL | ✅ | `V1Capabilities(drop=["ALL"])` |
| 非 root (webuild 模式) | ✅ | `run_as_user=1000` |
| 无 kubeconfig 注入 | ✅ | Pod spec 不挂载任何 kubeconfig |

#### Docker Compose

| 检查项 | 结果 | 说明 |
|--------|------|------|
| RELAY_URL 统一 | ✅ | 生产 + override 均默认 `wss://webuild.datoms.cn/ws/relay` |
| SANDBOX_IMAGE 注入 | ✅ | Gateway env 传递 |
| SANDBOX_AGENT 注入 | ✅ | Gateway env 传递 |
| RELAY_INTERNAL_TOKEN 注入 | ✅ | Gateway env 传递 |
| 端到端一致性 | ✅ | docker-compose → gateway env → sandbox_manager → k8s_client pod spec 全链路贯通 |

#### P1 问题

- `SANDBOX_AGENT` 默认值为 `"webuild"`，但镜像尚未推送（V1.3 未完成）。**在镜像就绪前，默认值应改回 `"python"`**，否则所有新 Session 会 `ImagePullBackOff`

#### P2 建议

- `RELAY_URL=wss://webuild.datoms.cn/ws/relay` 在本地开发环境不可达，建议增加 `.env` 覆盖机制

---

### 2.3 V2.1 — Relay 接受 Authorization Bearer

**审计文件**: `services/relay/src/relay.py`, `crates/codegen/xai-webuild-shell/src/agent/relay.rs`

| 检查项 | 结果 | 说明 |
|--------|------|------|
| Query param `token` 支持 | ✅ | FastAPI `Query(default="")` |
| `Authorization: Bearer` header 支持 | ✅ | 从 `ws.headers` 提取，case-insensitive |
| 优先级 | ✅ | `effective_token = token or header_token`，query 优先 |
| Internal token 路径 role-gated | ✅ | `RELAY_INTERNAL_TOKEN` 比对仅在 `role == "agent"` 时生效 |
| JWT 验证路径 | ✅ | 非 internal token 走 JWT 验证 |
| Rust 客户端发 Bearer header | ✅ | `req.headers_mut().insert("Authorization", "Bearer {key}")` |
| 双端一致性 | ✅ | Rust agent client 与 Python relay server 协议对齐 |

#### P1 问题

- Token 比对使用 `==` 字符串比较，存在**时序攻击风险**。应使用 `hmac.compare_digest`

#### P2 建议

- `ws.headers.get("authorization") or ws.headers.get("Authorization")` 中第二次调用是死代码（Starlette Headers case-insensitive）
- WebSocket `/ws` 端点的 Bearer header 认证路径缺少集成测试

---

### 2.4 V2.2 — Rust 沙箱 Headless 模式

**审计文件**: `crates/codegen/xai-webuild-shell/src/agent/relay.rs`, `crates/codegen/xai-webuild-shell/src/agent/app.rs`, `crates/codegen/xai-webuild-pager-bin/src/main.rs`, `crates/codegen/xai-webuild-pager/src/app/cli.rs`

#### 沙箱模式检测

| 检查项 | 结果 | 说明 |
|--------|------|------|
| `WEBUILD_SANDBOX_MODE` 检测 | ✅ | `is_cloud_sandbox_mode()` 匹配 `"1" / "true" / "yes"` |
| 三处设置源 | ✅ | Dockerfile `ENV`、sandbox-init.sh `export`、docker-compose env |
| 统一入口 | ✅ | `app.rs` `run_headless_inner()` 顶部调用并缓存 `sandbox_mode` |

#### Relay URL 与连接

| 检查项 | 结果 | 说明 |
|--------|------|------|
| URL 组装在 init 脚本 | ✅ | shell 层拼接 query params，Rust 端通过 `--webuild-ws-url` 接收 |
| `RelayConfig::for_sandbox()` | ✅ | 独立构造函数，接受任何非空 `auth.key`（不要求 OIDC） |
| `auth_manager: None` | ✅ | 无 proactive token refresh，沙箱不需要 |
| 单元测试 | ✅ | `for_sandbox()` 有测试：接受 ApiKey auth，拒绝空 key |

#### OIDC 绕过

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 跳过 `session.is_xai_auth()` 检查 | ✅ | `for_sandbox()` 不调用 `for_session()` 的 OIDC 门禁 |
| 直接构造 `WeBuildAuth` | ✅ | Token 从 `RELAY_TOKEN` / `RELAY_INTERNAL_TOKEN` env 取，`auth_mode: ApiKey` |
| 跳过浏览器流程 | ✅ | `no_browser` / `reauthenticate` / normal 分支全部跳过 |
| user_id 默认值 | ✅ | `WEBUILD_USER_ID` env，默认 `"sandbox-agent"` |

#### YOLO 模式

| 检查项 | 结果 | 说明 |
|--------|------|------|
| Rust 端强制启用 | ✅ | `sandbox_mode` 时 `agent_config.default_yolo_mode = true`（无条件） |
| CLI `--yolo` flag | ✅ | init 脚本传递 `--yolo` |
| 双重保障 | ✅ | 即使 CLI flag 丢失，Rust 内部仍强制 |

#### LLM 路径

| 检查项 | 结果 | 说明 |
|--------|------|------|
| DashScope API key | ✅ | init 脚本写入 `~/.webuild/api_key`，已有加载路径读取 |
| 模型选择 | ✅ | `-m "$MODEL"` flag，默认 `qwen-max` |

#### cwd

| 检查项 | 结果 | 说明 |
|--------|------|------|
| Dockerfile WORKDIR | ✅ | `WORKDIR /workspace` |
| init 脚本 cd | ✅ | `cd "$WORKSPACE"` 在 exec webuild 之前 |

#### P1 问题

- 沙箱 YOLO 强制启用**绕过 `yolo_disabled_by_policy()` 策略检查**。如果未来部署管理策略禁止 YOLO，沙箱仍会启用。建议文档化此设计决策

#### P2 建议

- `WEBUILD_YOLO` env var 被 init 脚本导出但 Rust 端从未读取——死配置。建议删除或让 Rust 端读取
- `RelayConfig::for_sandbox()` 不验证 URL 包含 `session_id`/`role=agent`/`token`，畸形 URL 产生不透明错误
- 401 恢复消息 "Run `webuild login`" 在沙箱中不可操作，应输出沙箱专用消息
- `xai-webuild-env` crate（方案中提及）不存在，env 处理在 shell/Dockerfile 中完成——实际可行但与方案描述不同

---

### 2.5 NetworkPolicy 与 Pod 安全

**审计文件**: `deploy/k8s/sandbox-namespace.yaml`

| 检查项 | 结果 | 说明 |
|--------|------|------|
| Egress: TCP/443 | ✅ | `sandbox-egress-restrict` 放行 `0.0.0.0/0:443` |
| Egress: DNS | ✅ | UDP+TCP/53 |
| Ingress: deny-all | ✅ | `sandbox-deny-ingress` with `ingress: []` |
| Capabilities drop ALL | ✅ | `V1Capabilities(drop=["ALL"])` |
| 非 root (webuild) | ✅ | `run_as_user=1000` |
| 非 root (legacy-python) | ⚠️ | `run_as_user=0`（root），因 pip install 需要——已知 trade-off |
| 无 kubeconfig 注入 | ✅ | Pod spec 不挂载 kubeconfig |

#### P1 建议

- 添加 `run_as_non_root: true` 到安全上下文，提供 admission controller 级强制保障

---

## 三、问题汇总

### P0 — 阻塞上线（1 项）

| # | 位置 | 问题 | 修复方案 |
|---|------|------|----------|
| P0-1 | ACR 镜像 | sandbox 镜像尚未构建推送到 ACR，创建 Session 会 `ImagePullBackOff` | 完成 V1.3：CI 构建推送或手动推送 |

### P1 — 需修复（4 项）

| # | 位置 | 问题 | 修复方案 |
|---|------|------|----------|
| P1-1 | `relay.py` | Token 比对使用 `==`，存在时序攻击风险 | 改用 `hmac.compare_digest` |
| P1-2 | `docker-compose.yml` | `SANDBOX_AGENT` 默认 `"webuild"` 但镜像未推送 | 镜像就绪前改回 `"python"` |
| P1-3 | `app.rs:462` | 沙箱 YOLO 绕过策略检查 `yolo_disabled_by_policy()` | 文档化设计决策或添加日志 |
| P1-4 | `k8s_client.py:177` | 缺少 `run_as_non_root: true` | 添加到 `V1SecurityContext` |

### P2 — 建议改进（5 项）

| # | 位置 | 问题 |
|---|------|------|
| P2-1 | `sandbox-init.sh:56` | `WEBUILD_YOLO` env var 是死配置，Rust 端未读取 |
| P2-2 | `relay.rs` `for_sandbox()` | 不验证 URL 含必要 query params |
| P2-3 | `relay.rs` `attempt_auth_recovery()` | 401 消息在沙箱中不可操作 |
| P2-4 | `docker-compose.yml` | 本地开发 RELAY_URL 不可达，缺 `.env` 覆盖 |
| P2-5 | `.gitlab-ci.yml` | `build-images` 缺 `needs: [build]` 显式依赖 |

---

## 四、上线行动清单

按优先级排序：

1. **P0-1**: 完成 V1.3 — 构建并推送 sandbox 镜像到 ACR
2. **P1-2**: 镜像推送前，将 `SANDBOX_AGENT` 默认值改回 `"python"`
3. **P1-1**: Relay token 比对改 `hmac.compare_digest`
4. **P1-4**: 添加 `run_as_non_root: true`
5. **P1-3**: 文档化沙箱 YOLO 绕过策略检查的设计决策
6. **V3**: 镜像就绪后执行 E2E 验证（创建 Session → prompt → 工具调用 → 文件读写）
7. **P2-1~5**: 后续迭代中逐步改进

---

## 五、审计结论

Phase V 已完成项（V1.1–V2.2）的**代码实现质量良好**，架构设计与方案一致：

- **沙箱镜像**：基于 Ubuntu 24.04 全工具链，init 脚本健壮（`set -euo pipefail` + `exec` 进程替换 + fallback 机制）
- **Gateway 接线**：15+ 环境变量完整注入，feature flag 端到端贯通，Python fallback 保留
- **Relay 认证**：Bearer header 与 query token 双路支持，Rust/Python 双端协议对齐
- **Rust headless**：沙箱模式检测、OIDC 绕过、YOLO 强制、Relay URL 接收均已实现，有单元测试覆盖
- **K8s 安全**：NetworkPolicy 精确匹配方案定义，capabilities drop ALL，非 root 运行

**唯一上线阻塞项**是 sandbox 镜像尚未推送到 ACR（V1.3），这是方案 checklist 中的显式待办项，不属于代码遗漏。

建议按上方行动清单顺序推进，预计 P0 + P1 修复后可进入 V3 E2E 验证阶段。
