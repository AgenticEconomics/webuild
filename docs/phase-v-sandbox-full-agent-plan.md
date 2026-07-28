# Phase V — 沙箱完整 WeBuild Agent + 全工具能力

> **状态**: 实施方案（2026-07-28）  
> **目标**: ACS 沙箱内运行完整 Rust `webuild` Agent，具备与本地 CLI 同等的工具能力；可选通过 Hub 访问用户本机 Workspace。  
> **前置**: Phase II–IV 已上线（Web IDE / Relay / Gateway / 轻量 Python sandbox agent）

---

## 1. 背景与缺口

### 现状

```
Browser (Web IDE)
  → Relay :8002 (role=browser)
  ↔ ACS Pod (role=agent)
       sandbox_agent.py → 仅 DashScope 文本流式回复（无工具）
```

| 层 | 现状 | 目标 |
|----|------|------|
| 进程 | ConfigMap 注入 Python `sandbox_agent.py` | 镜像内 `webuild agent headless` |
| 镜像 | `alinux/python:3.11-slim` | 自定义 `webuild/sandbox`（含二进制 + 开发工具链） |
| 工具 | 无 | 沙箱本地 FS/Shell 全工具；可选 Hub 远程本机 |
| Relay 鉴权 | query `token` + `RELAY_INTERNAL_TOKEN` | Rust 支持同协议；并兼容 `Authorization` |
| 权限 | N/A | YOLO / auto-approve（无人值守） |

设计文档 Phase 4 已写明目标形态；当前 Python 仅为过渡。Phase 报告 **P1/P2** 即本阶段范围。

### 根因（不能“直接换二进制”）

1. **Relay 协议差异**: WeBuild Relay 要求 `?session_id=&role=agent&token=`；Rust headless 当前只发 Bearer JWT，且 `RelayConfig::for_session` 拒绝 BYOK/API Key。
2. **镜像路径未启用**: `sandbox/Dockerfile` 已有开发工具，但 Gateway 仍用 slim Python + ConfigMap；CI 虽拷贝 `webuild-linux-x86_64`，Dockerfile 未 COPY。
3. **NetworkPolicy**: 仅放行 TCP/443 + DNS；`ws://IP:8002` 在策略生效时会失败，必须走 `wss://webuild.datoms.cn/ws/relay`。
4. **权限/无人值守**: 完整 Agent 默认会 `request_permission`；沙箱需 YOLO。

---

## 2. 目标架构

```
Browser (Web IDE)
  → wss://webuild.datoms.cn/ws/relay (role=browser, JWT)
  ↔ ACS Pod: webuild agent headless
       ├─ 本地工具: bash / read_file / search_replace / list_dir / …（/workspace）
       ├─ LLM: DashScope (DASHSCOPE_API_KEY, MODEL)
       └─ (Phase V-B) Hub ToolHarness → 本地 Leader ToolServer
```

**推荐方案 A（本方案采用）**: Pod 内跑完整 `webuild` 二进制。  
备选 B（Python 自建工具）/ C（双进程门面）不采用——与 CLI 长期分叉、维护成本高。

### 成功标准

| # | 标准 |
|---|------|
| S1 | 新建 Session → ACS Pod Running → Web IDE 可见 agent 已配对 |
| S2 | Prompt 后出现 **tool_call** 卡片（非仅文本） |
| S3 | 工具在 `/workspace` 读写/执行成功 |
| S4 | 危险操作可 YOLO 自动通过；或经 Web IDE 审批（可配置） |
| S5 | （V-B）Hub 可路由到本机 Workspace 工具 |
| S6 | Python ConfigMap 路径降级为 fallback / 可关闭 |

### 已知修复（2026-07-28）

Web IDE 原先只发 `session/prompt`（Python 轻量 agent 可接受），完整 Rust agent 要求先 `initialize` + `session/new`（`_meta.sessionId` = Relay UUID）。已在 Web IDE 中：等 `agent_connected` → ACP handshake → 再允许 prompt。

---

## 3. 分阶段实施

### V0 — 方案与基线锁定（本文档）

- [x] 选定方案 A；明确协议/鉴权/镜像/网络依赖
- [ ] 验收清单与回滚策略（见 §6）

### V1 — 沙箱镜像与 Gateway 接线（本机工具前提）

**产出**: 可推送的 `webuild-sandbox` 镜像；Gateway 默认用该镜像启动 webuild。

| 任务 | 文件 |
|------|------|
| Dockerfile COPY 二进制；ENTRYPOINT 走 init → webuild | `sandbox/Dockerfile` |
| init 脚本改为 headless + Relay URL；写 config / API key | `sandbox/scripts/sandbox-init.sh` |
| 模板镜像改为 ACR/本地 sandbox 镜像；注入完整 env | `services/gateway/src/sandbox_manager.py` |
| 有 webuild 时不再 ConfigMap 注入 Python；保留 fallback | `services/gateway/src/k8s_client.py` |
| RELAY_URL 统一 `wss://webuild.datoms.cn/ws/relay` | `deploy/docker-compose*.yml`、Gateway env |
| CI：二进制缺失则 fail；推送 sandbox 镜像 | `.gitlab-ci.yml` |
| 健康检查改为 webuild 进程 | Dockerfile HEALTHCHECK |

**Pod 环境变量约定**:

```text
SANDBOX_ID / SESSION_ID     # 与 Web Session 同 id
WEBUILD_USER_ID
DASHSCOPE_API_KEY
MODEL                       # 默认 qwen-max
RELAY_URL                   # wss://webuild.datoms.cn/ws/relay
RELAY_TOKEN                 # RELAY_INTERNAL_TOKEN
WEBUILD_SANDBOX_MODE=1      # 启用沙箱 headless 鉴权路径
WEBUILD_YOLO=1              # 无人值守自动批准工具
WEBUILD_WORKSPACE=/workspace
SANDBOX_REPO_URL / BRANCH   # 可选 clone
HUB_WS_URL                  # V-B 再用
```

### V2 — Rust：沙箱 Headless 接入 WeBuild Relay（硬门槛）

**产出**: `webuild` 可用 API Key + internal token 加入指定 session，并跑完整工具循环。

| 任务 | 说明 |
|------|------|
| 沙箱模式检测 | `WEBUILD_SANDBOX_MODE=1` 或专用子命令/flag |
| Relay URL 组装 | `{RELAY_URL}?session_id={id}&role=agent&token={RELAY_TOKEN}&user_id=…` |
| 绕过 OIDC 门禁 | `RelayConfig` / `run_headless` 在沙箱模式下允许 BYOK + internal token |
| LLM | 继续走已有 DashScope / API Key 路径 |
| YOLO | `default_yolo_mode=true`（env / config） |
| cwd | `/workspace` |
| Relay 侧 | 接受 `Authorization: Bearer`（与 query `token` 等价），方便后续统一 |

主要改动 crate：`xai-webuild-shell`（`relay.rs`, `app.rs`）、`xai-webuild-pager-bin`、可选 `xai-webuild-env`。

### V3 — 沙箱本地工具打磨

- init：git clone、`safe.directory`、`~/.webuild`
- 资源规格：提高默认 memory（建议 request 2Gi / limit 8Gi）
- 去掉或保留 Python agent 为 `environment_id=legacy-python`
- Web IDE：确认 tool_call / permission UI 在沙箱会话可用
- E2E：创建 → prompt “在 /workspace 写 hello.txt” → 文件存在

### V4 — Hub 远程工具（原 P2）

- 本地 Leader 以 ToolServer 注册 Hub（`wss://webuild.datoms.cn/ws/hub`）
- 沙箱 Agent 以 ToolHarness 按 session 绑定
- Hub 增加 JWT / internal token
- NetworkPolicy 确认 443 可达 Hub
- 危险远程工具优先走 Web IDE HITL

### V5 — 硬化与收尾

- 监控：Pod 失败原因、冷启动时长、工具错误率
- PVC / 休眠（原 P3，可另立项）
- 删除 ConfigMap Python 注入默认路径
- 更新 Phase II–IV 报告与用户文档

---

## 4. 协议与鉴权细节

### 4.1 WeBuild Relay（已部署）

Agent 连接：

```text
GET /ws?session_id=<id>&role=agent&token=<RELAY_INTERNAL_TOKEN>&user_id=<optional>
```

或（V2 增强）Header：`Authorization: Bearer <token>` + 同上 query（session_id/role）。

### 4.2 Rust 现状 vs 改造

| 项 | 现状 | 改造 |
|----|------|------|
| URL | `wss://…/ws/relay` 无 query | 追加 session_id/role/token |
| Auth | 仅 OIDC `is_xai_auth()` | 沙箱模式：internal token 或 Gateway 签发的短时 JWT |
| LLM | API Key 可用，但 headless 拒 BYOK 上 relay | 沙箱模式：API Key + relay 并存 |

**优选路径**: internal token（与现 Python 一致，改动面小）。  
**备选**: Gateway 创建沙箱时签发短时 JWT（更贴近生产，但要打通 Auth→Gateway）。

### 4.3 权限

- 默认 `WEBUILD_YOLO=1`：沙箱内工具自动批准
- 配置关闭 YOLO 时：`session/request_permission` → Web IDE（已有 UI）

---

## 5. 网络与安全

```yaml
# sandbox-namespace NetworkPolicy（保持 443 + DNS）
Egress:
  - TCP/443 → DashScope, webuild.datoms.cn (Relay/Hub/Auth)
  - UDP/TCP 53 → DNS
Ingress: deny-all（Agent 只出站）
```

- 禁止向沙箱注入宿主机 kubeconfig
- `RELAY_TOKEN` / API Key 仅经 Pod env；不写进镜像层
- Capabilities drop ALL；尽量非 root（若 pip 已不需要 root）

---

## 6. 回滚

| 级别 | 动作 |
|------|------|
| L1 | Gateway 模板切回 `environment_id=legacy-python` 或镜像 tag 回滚 |
| L2 | `k8s_client` feature flag `SANDBOX_AGENT=python\|webuild` |
| L3 | 关闭 ACS 创建，Web IDE 仅用 ECS 轻量 agent discover |

---

## 7. 工作量粗估

| 阶段 | 估计 |
|------|------|
| V1 镜像 + Gateway | 1–2 天 |
| V2 Rust Relay 沙箱模式 | 2–4 天（含联调） |
| V3 打磨 + E2E | 1–2 天 |
| V4 Hub | 1–2 周 |
| V5 硬化 | 持续 |

---

## 8. 实施顺序（开发 checklist）

1. [x] **V1.1** 改 `sandbox/Dockerfile` + `sandbox-init.sh`
2. [x] **V1.2** 改 Gateway 模板 / k8s_client / compose RELAY_URL
3. [x] **V2.1** Relay 接受 Authorization Bearer
4. [x] **V2.2** Rust sandbox headless：URL 组装 + 绕过 OIDC + YOLO
5. [ ] **V1.3** 本地/CI 构建 sandbox 镜像并让 Gateway 指向它（需 ACR 推送 + 重编含沙箱模式的 webuild）
6. [ ] **V3** E2E 验证工具调用
7. [ ] **V4** Hub（可并行设计，串行联调）

---

## 9. 非目标（本 Phase 不做）

- 沙箱内 TUI 交互
- 多环境模板市场（仅增强 `default`，可选保留 `legacy-python`）
- PVC 持久化 / 休眠唤醒（P3）
- Windows / macOS 沙箱镜像
