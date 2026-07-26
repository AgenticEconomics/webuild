# Phase II 执行 Backlog

> 版本: v1.0 · 日期: 2026-07-26 · 状态: **可执行**
>
> 对应方案: [`web-ide-cloud-sandbox-plan.md`](./web-ide-cloud-sandbox-plan.md) v0.2
>
> 前提: 产品 Phase I（CLI + GitHub Release）已完成。本 backlog 覆盖 **Web IDE + 云协同基础设施**。

---

## 0. 如何读这份 Backlog

| 符号 | 含义 |
|------|------|
| **Epic** | 可独立验收的大块交付 |
| **Story** | 可开发的用户故事 / 工程任务 |
| **Spike** | 有时限的技术验证，产出结论而非产品功能 |
| **P0 / P1 / P2** | 必须 / 应该 / 可以（首版可砍） |
| **依赖** | 必须先完成的 Story ID |

**交付原则（强制）**

1. **场景 A 优先**：浏览器 → Relay → 本地 Leader（不依赖 Hub / 沙箱）
2. **场景 B 分两步**：先「独立云沙箱（Git clone）」，再「Hub 回本地 FS」
3. **三个 Spike 未通过，不得进入对应 Epic 的全面开发**
4. 每个 Story 需有明确 **验收标准（AC）**；无 AC 不排期

**建议人力假设**：1 名全栈 / 后端主导 + 0.5 名前端（或同一人），ACK 运维可协作。

---

## 1. 里程碑总览

| 里程碑 | 目标 | 目标周次 | 验收一句话 |
|--------|------|----------|------------|
| **M0** | 基础设施就绪 | W1–W2 | 命名空间、RDS/Redis、域名 TLS、可部署空 Helm |
| **M1** | Auth + 鉴权适配 | W2–W4 | 用户登录拿 JWT；本地 Leader 可用 WeBuild token 连 Relay |
| **M2a** | Web IDE 场景 A | W4–W8 | 浏览器完成一轮对话 + 工具卡片 + 权限审批 |
| **M2b** | 独立云沙箱 | W8–W11 | Web 创建沙箱，沙箱内 Agent 可 Git clone 并对话 |
| **M2c** | Hub 回本地 | W11–W14 | 沙箱工具经 Hub 落到本地 Workspace |
| **M3** | 生产化 | W14–W16 | 监控/审计/文档/手动生产发布就绪 |

> 原方案 14 周「全量生产」调整为：**M2a ~8 周可对外试用**；完整场景 B + 生产化 **16 周**。

```
W1  W2  W3  W4  W5  W6  W7  W8  W9  W10 W11 W12 W13 W14 W15 W16
├────┤                                                          EPI-0  基础设施
   ├──────┤                                                     EPI-1  Auth
      ├───┤  SPIKE-1/2                                          鉴权+Relay 协议
         ├────────────────┤                                     EPI-2  Relay+WebIDE (A)
            ├────┤  SPIKE-3                                     Hub wire
                        ├──────────┤                            EPI-3  Gateway+沙箱独立
                              ├──────────┤                      EPI-4  Hub Broker
                                    ├──────────┤                EPI-5  生产化
▲        ▲                 ▲              ▲           ▲
M0       M1                M2a            M2b         M2c/M3
```

---

## 2. Epic 与 Story 明细

### EPI-0 · 基础设施准备（M0）· P0

| ID | 类型 | 优先级 | 标题 | 依赖 | 预估 |
|----|------|--------|------|------|------|
| E0-1 | Story | P0 | ACK 扩容 +2 节点（4C/16G） | — | 运维 2d |
| E0-2 | Story | P0 | 创建 ns `webuild-system` / `webuild-sandbox` + RBAC | E0-1 | 1d |
| E0-3 | Story | P0 | 阿里云 RDS PostgreSQL + 云 Redis 开通与网络打通 | — | 2d |
| E0-4 | Story | P0 | ACR 仓库 `webuild/*` + 拉取密钥 | — | 1d |
| E0-5 | Story | P0 | DNS `*.webuild.jarvikheart.cn` → 现有 NLB | — | 1d |
| E0-6 | Story | P0 | cert-manager Certificate 模板（auth/relay/hub/gateway/web） | E0-5 | 1d |
| E0-7 | Story | P0 | Helm Chart 骨架 `helm/webuild`（空 Deploy + Ingress） | E0-2 | 2d |
| E0-8 | Story | P1 | Staging values + 健康检查 Ingress 路径 | E0-7 | 1d |

**Epic AC**

- [ ] 5 节点 CPU request 水位 < 70%
- [ ] 从集群内可连 RDS / Redis
- [ ] `helm upgrade --install` 空 chart 成功
- [ ] 子域名 TLS 签发成功（至少一个服务验证）

---

### EPI-1 · Auth Service（M1）· P0

| ID | 类型 | 优先级 | 标题 | 依赖 | 预估 |
|----|------|--------|------|------|------|
| E1-1 | Story | P0 | Auth 服务脚手架（FastAPI + Docker + Alembic） | E0-3 | 2d |
| E1-2 | Story | P0 | 用户模型 + 注册/登录（首版可用 invite / 预置用户） | E1-1 | 2d |
| E1-3 | Story | P0 | JWT 签发 / 刷新（RS256，含 `sub`/`scopes`/`aud`） | E1-2 | 2d |
| E1-4 | Story | P0 | API Key CRUD（hash 存储、prefix 展示、scopes） | E1-3 | 2d |
| E1-5 | Story | P0 | RBAC 中间件（admin / developer / viewer） | E1-3 | 1d |
| E1-6 | Story | P0 | 服务间校验接口：`POST /api/auth/introspect` 或 JWKS | E1-3 | 1d |
| E1-7 | Story | P1 | 审计：login / key create / role change 写 `audit_logs` | E1-2 | 1d |
| E1-8 | Story | P0 | 单元 + 集成测试（pytest） | E1-3,E1-4 | 2d |
| E1-9 | Story | P0 | 部署到 staging（Helm） | E0-7,E1-8 | 1d |

**Epic AC**

- [ ] `login` → access + refresh token
- [ ] API Key 可创建并用于后续服务鉴权设计
- [ ] JWKS 或 introspect 可被其他服务验证
- [ ] Staging 健康检查通过

**API 最小集**

```
POST /api/auth/login
POST /api/auth/token/refresh
GET  /api/auth/me
POST /api/auth/api-keys
GET  /api/auth/api-keys
DELETE /api/auth/api-keys/:id
GET  /api/auth/.well-known/jwks.json   # 或 introspect
```

---

### SPIKE · 技术验证（阻塞后续 Epic）

| ID | 标题 | 时限 | 阻塞 | 产出 |
|----|------|------|------|------|
| **SPIKE-1** | **Relay 协议逆向** | 3–5d | EPI-2 | 握手/会话绑定/消息帧说明 + mock server 可被现有 Leader 连接 |
| **SPIKE-2** | **鉴权门禁改造** | 2–3d | EPI-2 | 非 `is_xai_auth` 路径可拿到 Relay 凭证并建连；设计文档 |
| **SPIKE-3** | **Hub wire 最小环** | 3–5d | EPI-4 | 最小 Broker：hello → serve → session.bind → tool.call 与 Rust SDK 互通 |

#### SPIKE-1 详细 AC

- [ ] 阅读并记录 `agent/relay.rs`、`relay/sync.rs` 的建连头、错误码、重连语义
- [ ] 本地 mock Relay（可用 Python 临时服务）使 `webuild agent headless --webuild-ws-url` 或 Leader relay 连上
- [ ] 至少转发一轮 ACP `session/prompt` 相关消息
- [ ] 输出：`docs/design/relay-protocol-notes.md`（可后补文件名）

#### SPIKE-2 详细 AC

- [ ] 明确：`RelayConfig::for_session` 如何支持 WeBuild JWT / 受控 API Key
- [ ] 明确：cloud 扩展 `require_xai_auth` 的替换策略
- [ ] PoC：改完后 API Key 用户可触发 relay 连接（哪怕连 mock）
- [ ] 列出正式 Story 的文件变更清单（更新方案附录 A）

#### SPIKE-3 详细 AC

- [ ] 最小 Broker（语言不限；推荐后续 Rust，spike 可用任一）
- [ ] 与 `xai-computer-hub-sdk` ToolServer 完成 hello_ack 协议版本协商
- [ ] 完成一次 `tool.call` → `tool_call_request` → result 往返
- [ ] 记录必须实现的 method 白名单 vs 可延后 method

---

### EPI-1.5 · Rust 客户端鉴权适配（M1）· P0

> 方案原稿低估；**与 Auth 并行，必须在 Relay 联调前完成。**

| ID | 类型 | 优先级 | 标题 | 依赖 | 预估 |
|----|------|--------|------|------|------|
| E15-1 | Story | P0 | `xai-webuild-env`：默认/文档化 WeBuild 端点 + 保留 env override | — | 1d |
| E15-2 | Story | P0 | 实现 SPIKE-2 结论：`RelayConfig` 支持 WeBuild token | SPIKE-2,E1-3 | 3d |
| E15-3 | Story | P0 | Auth 适配：Leader 可向 Auth 换 Relay/Hub 用 bearer | E1-6,E15-2 | 2d |
| E15-4 | Story | P1 | `x.ai/cloud/*` 门禁改为 WeBuild scopes（`sandbox.*`） | E15-2 | 2d |
| E15-5 | Story | P0 | 配置项：`relay_url` / `hub_url` / `gateway_url` / `auth_url` | E15-1 | 1d |
| E15-6 | Story | P0 | 回归：API Key 本地 TUI 不回退；单元测试覆盖新门禁 | E15-2 | 2d |

**Epic AC**

- [ ] `WEBUILD_PRODUCTION_WS_URL` 指向自建 Relay 时可建连（mock 或真服务）
- [ ] API Key 用户不再因 `is_xai_auth` 被静默关闭 Relay
- [ ] 现有本地 headless / TUI 主路径无回归

---

### EPI-2 · Relay Server + Web IDE MVP（场景 A / M2a）· P0

| ID | 类型 | 优先级 | 标题 | 依赖 | 预估 |
|----|------|--------|------|------|------|
| E2-1 | Story | P0 | Relay Server 脚手架（FastAPI/WS + Docker） | SPIKE-1,E0-7 | 2d |
| E2-2 | Story | P0 | Agent 侧 WS 接入 + 会话路由表 | E2-1,E15-2 | 3d |
| E2-3 | Story | P0 | Browser 侧 WS 接入 + JWT 鉴权 | E2-1,E1-3 | 2d |
| E2-4 | Story | P0 | ACP 消息双向转发（透传 + 关联 session） | E2-2,E2-3 | 3d |
| E2-5 | Story | P1 | 会话元数据落库（sessions 表）+ REST 列表 | E2-4,E0-3 | 2d |
| E2-6 | Story | P1 | 历史归档（可选 JSONL→PG，MVP 可先内存+磁盘） | E2-5 | 2d |
| E2-7 | Story | P0 | TS ACP Client SDK（connect/prompt/cancel/events） | SPIKE-1 | 3d |
| E2-8 | Story | P0 | Web IDE：登录页 + 会话列表 | E1-9,E2-7 | 2d |
| E2-9 | Story | P0 | Web IDE：会话页对话流（流式 Markdown） | E2-4,E2-7 | 4d |
| E2-10 | Story | P0 | 工具调用卡片（Started/Completed） | E2-9 | 2d |
| E2-11 | Story | P0 | 权限审批弹窗（RequestPermission） | E2-9 | 2d |
| E2-12 | Story | P1 | 终端面板 xterm.js | E2-9 | 2d |
| E2-13 | Story | P1 | Monaco 代码只读查看（从 tool 结果提取） | E2-10 | 2d |
| E2-14 | Story | P0 | 端到端联调：本地 Leader ↔ Relay ↔ Web IDE | E2-4,E2-11,E15-2 | 3d |
| E2-15 | Story | P0 | Staging 部署 Relay + Web IDE | E2-14 | 2d |

**Epic AC（M2a 出门标准）**

- [ ] 用户浏览器登录后新建会话
- [ ] 本地 Leader 在线时，Web 端 prompt 得到流式回复
- [ ] 危险工具触发权限弹窗，批准/拒绝生效
- [ ] 断线重连后会话不丢（至少 Agent 侧 cursor 语义与 SPIKE-1 一致）
- [ ] Staging 演示路径可跑通

**明确非目标（本 Epic）**

- 完整文件树写回、多用户 pair、分享链接、admin 后台
- 云沙箱、Hub

---

### EPI-3 · Gateway + 独立云沙箱（M2b）· P0

| ID | 类型 | 优先级 | 标题 | 依赖 | 预估 |
|----|------|--------|------|------|------|
| E3-1 | Story | P0 | 沙箱镜像 Dockerfile（webuild 二进制 + 基础工具） | Release 产物 | 2d |
| E3-2 | Story | P0 | Gateway 脚手架 + K8s client（创建/删 Pod） | E0-2,E1-3 | 3d |
| E3-3 | Story | P0 | **对齐 `SandboxClient` REST 形状**（或 adapter） | E3-2 | 3d |
| E3-4 | Story | P0 | 创建沙箱：clone repo 可选 + agent headless 启动 | E3-1,E3-2 | 3d |
| E3-5 | Story | P0 | NetworkPolicy：出站 DashScope + 必要服务 | E3-4 | 2d |
| E3-6 | Story | P0 | Gateway ACP/WS 代理 → Pod 内 agent | E3-4 | 3d |
| E3-7 | Story | P0 | TTL 自动清理 + 手动 terminate | E3-2 | 2d |
| E3-8 | Story | P1 | Web IDE 沙箱列表/创建/进入会话 | E3-6,E2-8 | 3d |
| E3-9 | Story | P0 | 联调：Web → Gateway → 沙箱 Agent → DashScope | E3-6,E3-8 | 2d |
| E3-10 | Story | P2 | Hibernate/restore | E3-7 | 后置 |
| E3-11 | Story | P1 | 沙箱专用节点池（Spot）+ nodeSelector | E0-1 | 2d |

**Epic AC（M2b）**

- [ ] 用户可创建沙箱并在 Web 对话
- [ ] 沙箱内工具操作沙箱 FS（不经 Hub）
- [ ] TTL / 手动删除回收 Pod
- [ ] 网络策略阻止非常规出站（至少 staging 验证）

**API 对齐原则**

优先兼容现有 client 路径（见 `remote/agent.rs`），避免双轨：

```
POST   /sandbox/sessions/start
DELETE /sandbox/sessions/{id}
GET    /sandbox/sessions/{id}/status
GET    /sandbox/sessions/{id}/logs
POST   /sandbox/sessions/{id}/hibernate   # P2
POST   /sandbox/sessions/{id}/restore     # P2
GET|POST /sandbox/environments
...
```

若必须使用 `/api/gateway/*` 前缀，提供 **兼容 adapter** 或同步改 `SandboxClient` base path（同一 Story 内完成）。

---

### EPI-4 · Hub Broker + 回本地（M2c）· P1（M2a/M2b 之后）

| ID | 类型 | 优先级 | 标题 | 依赖 | 预估 |
|----|------|--------|------|------|------|
| E4-0 | 决策 | P0 | Broker 实现语言：优先 **Rust**（复用 protocol）；否则 Python 子集 | SPIKE-3 | 0.5d |
| E4-1 | Story | P0 | Broker：hello / hello_ack / 连接管理 | SPIKE-3 | 3d |
| E4-2 | Story | P0 | `serve` + 路由表 + `session.bind/unbind` | E4-1 | 3d |
| E4-3 | Story | P0 | `tool.call` ↔ `tool_call_request` 转发 | E4-2 | 3d |
| E4-4 | Story | P1 | 并发限流 + keepalive + graceful shutdown | E4-3 | 2d |
| E4-5 | Story | P0 | 本地 Leader ToolServer 指向自建 Hub URL | E15-5,E4-3 | 1d |
| E4-6 | Story | P0 | 沙箱 Agent 作为 Harness 调用本地工具 | E4-5,E3-6 | 3d |
| E4-7 | Story | P0 | 权限/HITL：远程工具调用经本地 permission 路径 | E4-6 | 2d |
| E4-8 | Story | P1 | wire 兼容测试套件（SDK 集成测） | E4-3 | 2d |
| E4-9 | Story | P2 | donate（traces/logs/metrics）— 可 mock 忽略 | — | 后置 |

**Epic AC（M2c）**

- [ ] 沙箱会话中 `read_file` 可命中本地 Workspace（session 绑定正确）
- [ ] 跨 session 不可调用
- [ ] 本地拒绝权限时沙箱侧收到错误
- [ ] 本地断线后行为可预期（错误或重连，文档化）

**Method 白名单（MVP）**

必须：`hello`, `hello_ack`, `ping/pong`, `serve`, `session.bind`, `session.unbind`, `tool.call`, `tool_call_request`, `tool_call_progress`（若 SDK 依赖）, `tools_changed`（最小）

可延后：`tools.search`, donate 系列, `session_attach_server`, 复杂 hook 全链路

---

### EPI-5 · 生产化（M3）· P0（相对发布）

| ID | 类型 | 优先级 | 标题 | 依赖 | 预估 |
|----|------|--------|------|------|------|
| E5-1 | Story | P0 | Prometheus metrics（各服务基础 RED + WS 连接数） | M2a | 2d |
| E5-2 | Story | P0 | Grafana 看板（或 ARMS） | E5-1 | 1d |
| E5-3 | Story | P0 | 审计日志覆盖：会话/沙箱/权限变更 | E1-7,M2a | 2d |
| E5-4 | Story | P0 | WebSocket 并发与断线压测报告 | M2a | 2d |
| E5-5 | Story | P1 | 安全自检清单（权限绕过、跨 session、沙箱逃逸面） | M2b | 2d |
| E5-6 | Story | P0 | 部署/运维文档 + 用户指南（Web IDE 场景 A） | M2a | 2d |
| E5-7 | Story | P0 | CI：镜像 build + staging deploy（扩展现有 Release） | E0-4 | 3d |
| E5-8 | Story | P1 | 生产发布 runbook + 手动 Helm 生产 | E5-6,E5-7 | 1d |

**Epic AC**

- [ ] Staging 持续可演示
- [ ] 关键指标可观测
- [ ] 生产发布 checklist 可执行

---

## 3. 跨切面工作（不单独成 Epic，但需认领）

| ID | 标题 | 何时 | 说明 |
|----|------|------|------|
| X-1 | 统一错误码与日志字段（request_id / user_id / session_id） | EPI-1 起 | 全服务约定 |
| X-2 | Ingress WebSocket 超时 / sticky 配置 | EPI-2 部署前 | 复用 NLB |
| X-3 | 密钥与 Secret 管理（JWT 私钥、DB、Redis） | E0/E1 | 禁止进仓库 |
| X-4 | 功能开关：relay / hub / sandbox 可独立关 | EPI-2+ | 降低 blast radius |

---

## 4. 优先级裁剪清单（进度紧张时）

**可砍（不影响 M2a）**

- Monaco / xterm 精致 UI → 纯文本先上
- 会话历史 PG 归档 → 本地磁盘即可
- 分享链接、admin、team、billing
- Hibernate/restore
- Hub donate / 完整 tools.search
- 多 replica

**不可砍（M2a）**

- Auth JWT
- SPIKE-1/2 结论落地
- Relay 双向 ACP 转发
- 对话流 + 权限弹窗
- 端到端联调

---

## 5. 依赖关系图（关键路径）

```
E0-* 基础设施
  │
  ├─► E1-* Auth ──────────────────────────────┐
  │         │                                 │
  │         ▼                                 │
  │      SPIKE-2 ──► E15-* Rust 鉴权          │
  │         │                                 │
  │         ▼                                 │
  │      SPIKE-1 ──► E2-* Relay + Web IDE ────┼──► M2a
  │                                           │
  │         SPIKE-3                           │
  │            │                              │
  └─► E3-* Gateway + 独立沙箱 ──► M2b          │
               │                              │
               └─► E4-* Hub + 回本地 ──► M2c   │
                                              │
                         E5-* 生产化 ◄─────────┘
```

---

## 6. 验收与 Definition of Done

每个 Story 合并前：

1. AC 全部勾选或书面豁免
2. 有自动化测试 **或** 手测步骤写在 PR / 文档
3. Staging 可部署（涉及服务的 Story）
4. 不引入「仅 xAI OIDC 才能用」的新硬门禁
5. 密钥不进 git

每个里程碑：

| 里程碑 | Demo 剧本 |
|--------|-----------|
| M1 | 登录拿 token；本地配置后 Leader 日志出现 relay connecting |
| M2a | 浏览器提问 → 本地改文件工具卡片 → 权限批准 |
| M2b | 创建沙箱 → clone 公开/内网仓 → 沙箱内问答 |
| M2c | 沙箱读本地路径文件成功 |
| M3 | 压测数字 + 看板 + runbook 走查 |

---

## 7. 建议首个 Sprint（W1–W2）任务包

**目标：M0 + Auth 起步 + 三个 Spike 排期**

| 负责人角色 | 任务 |
|------------|------|
| 运维/后端 | E0-1, E0-2, E0-3, E0-5 |
| 后端 | E1-1, E1-2 启动；并行 SPIKE-1 |
| 后端/Rust | SPIKE-2 启动 |
| 全员 | 评审本 backlog + 方案 v0.2；确认 E4-0 语言倾向 |

**W2 结束检查点**

- [ ] 集群可调度 WeBuild 核心服务
- [ ] Auth 能 login（哪怕仅预置用户）
- [ ] SPIKE-1 或 SPIKE-2 至少一个有书面结论

---

## 8. 跟踪建议

- 用本文件 ID（`E2-9`）作为 issue / 提交前缀
- 周会只盯：**阻塞 Spike、M2a 关键路径、基础设施依赖**
- 方案文档变更时同步改本节里程碑周次

---

## 9. 文档索引

| 文档 | 用途 |
|------|------|
| [web-ide-cloud-sandbox-plan.md](./web-ide-cloud-sandbox-plan.md) | 架构与实施方案（v0.2） |
| 本文件 | 可执行 backlog |
| （SPIKE 产出）relay-protocol-notes 等 | 协议细节，开发时新增 |
