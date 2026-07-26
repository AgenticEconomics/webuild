***************************************************************
**  使用的 Agent Session:
**   qwen --resume 2a570304-6007-4b74-8c02-2c0d89424c20
***************************************************************

# WeBuild Web IDE & 云端沙箱 — 实施方案

> 版本: **v0.2.0** · 日期: 2026-07-26 · 作者: Jerry Zhang
>
> 状态: **已评审修订** — 纳入可行性评估结论；可执行 backlog 见
> [`phase-ii-backlog.md`](./phase-ii-backlog.md)。
>
> 变更摘要 (v0.1 → v0.2):
> - 明确 **场景 A（Web→Relay→本地 Agent）优先**，场景 B 分「独立沙箱」与「Hub 回本地」两步
> - 纠正鉴权工作量：WeBuild 为 API-key-first，Relay/Cloud 现有 `is_xai_auth` 门禁必须改造
> - Hub Broker 改为 **协议子集 MVP**，实现语言 **优先 Rust**；Python 全量兼容降级为备选
> - Gateway REST **对齐现有 `SandboxClient`**，避免双轨 API
> - 时间线由「14 周全量生产」调整为 **~8 周 M2a 试用 / ~16 周场景 B+生产**
> - 强制三个技术 Spike 通过后再全面开发对应 Epic

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [现状分析](#2-现状分析)
3. [目标架构](#3-目标架构)
4. [Web IDE 方案](#4-web-ide-方案)
5. [云端沙箱方案](#5-云端沙箱方案)
6. [认证与权限体系](#6-认证与权限体系)
7. [安全模型](#7-安全模型)
8. [部署架构](#8-部署架构)
9. [实施路线](#9-实施路线)
10. [风险与缓解](#10-风险与缓解)
11. [附录](#11-附录)
12. [可行性结论与交付策略](#12-可行性结论与交付策略)

---

## 1. 背景与动机

### 1.1 现状

WeBuild 当前是一个**纯终端 AI 编程助手**（CLI/TUI），基于 Grok Build 的 Rust 代码 fork，默认使用阿里云 DashScope `qwen3.7-max` 模型。用户必须在本地安装二进制、配置 API Key，通过终端交互。

上游 Grok Build 设计了两个云-端协同基础设施：

| 功能 | 上游实现 | WeBuild 现状 |
|------|---------|-------------|
| **Relay** | WebSocket 桥接本地 Agent ↔ grok.com Web 前端 | 代码保留，无对应 Web 前端，实际不启用 |
| **Computer Hub** | 工具路由网格，云端沙箱通过 Hub 操控本地文件系统 | 代码保留，无对应云服务，实际不启用 |

### 1.2 为什么需要自建

1. **降低使用门槛** — 终端操作对非技术用户不友好，Web IDE 可在浏览器中使用，无需安装
2. **跨设备协作** — 团队成员可在任意设备访问同一编程会话，支持 pair programming
3. **云端执行环境** — 本地机器资源有限，云端沙箱提供隔离的、可扩展的计算环境
4. **企业级管控** — 需要统一的认证、审计、用量统计和权限控制
5. **数据自主** — 代码不出企业边界，所有服务部署在阿里云或公司内网

### 1.3 非目标

- 不构建完整的在线 IDE（如 VS Code for the Web）—— 聚焦 AI 编程助手场景
- 不替代本地 TUI —— Web IDE 和 TUI 并存，同一 Agent 可同时服务两种客户端
- 不构建通用云平台 —— 沙箱仅服务于 WeBuild Agent 的工具调用

### 1.4 产品阶段与本文档范围

| 阶段 | 内容 | 状态 |
|------|------|------|
| **产品 Phase I** | CLI/TUI、DashScope 默认模型、API-key-first、GitHub Release | **已完成**（v0.4.x） |
| **产品 Phase II** | Web IDE、自建 Relay/Auth、云端沙箱、Hub（本文档） | **进行中 / 规划已修订** |

执行级任务拆解、Story ID、验收标准见 **[`phase-ii-backlog.md`](./phase-ii-backlog.md)**。架构细节以本文为准；排期与砍 scope 以 backlog 为准。

---

## 2. 现状分析

### 2.1 可复用的代码资产

WeBuild 继承的 Grok Build 代码中包含成熟的云-端协同架构，以下组件可直接复用或改造：

#### ACP 协议层（`xai-acp-lib`）

完整的双向 JSON-RPC 协议定义，Agent 与 Client 之间的所有通信都通过 ACP：

```
Agent ← Client: Initialize, Authenticate, NewSession, LoadSession, Prompt, Cancel, ...
Agent → Client: SessionNotification (session/update), RequestPermission, TerminalCreate/Output, ...
```

**复用价值**: Web IDE 前端只需实现 ACP Client 侧协议，即可与现有 Agent 完全兼容。

#### Relay 机制（`xai-webuild-shell/src/relay/`）

- WebSocket 双向桥接，传输标准 ACP 消息
- RelaySync 层：磁盘游标断点续传、事件缓冲（256 条）、`initialize` 握手
- 已有重连、auth recovery、keepalive 机制

**复用价值**: Agent **客户端**已完整；服务端需自建。**不是**「只改 URL」——见 §6.3 鉴权门禁与 §12 Spike 要求。

#### Computer Hub SDK（`xai-computer-hub-*`）

- 完整的工具路由网格：ToolServer（Provider）/ ToolHarness（Consumer）/ Hub（Broker）
- JSON-RPC 2.0 over WebSocket，hello 握手、session.bind、tool_call_request
- 连接池、自动重连、并发限流（per-session / per-connection / global）
- MCP Adapter：将 MCP Server 工具桥接到 Hub
- Local-shadows-remote 解析策略

**复用价值**: SDK 侧（ToolServer / ToolHarness）已在 Rust 中实现；Broker 需新建。
**注意**: 线协议含 30+ method（`serve` / `session.bind` / hooks / donate 等），SDK connection/server/harness 合计约万行级语义。MVP 只实现 **method 白名单子集**，禁止假设「薄转发 3 周即可全兼容」。

#### 工具系统（`xai-webuild-tools`）

35+ 内建工具，覆盖文件操作、终端执行、搜索、任务管理、MCP 桥接等。

**复用价值**: 云端沙箱中的 Agent 可直接使用全部工具，无需重新实现。

#### Workspace 集成（`xai-webuild-workspace/src/hub.rs`）

Workspace 以 ToolServer 身份注册到 Hub，暴露全部工具给远程调用方。包含：
- Session 路由的 tool handler
- 权限检查（HITL permission_request hook）
- 状态发布（tool_server.status）
- Workspace RPC（git_status, fs_*, put_files, get_files 等）

**复用价值**: 云端沙箱可直接作为 ToolHarness 消费本地 Workspace 暴露的工具。

### 2.2 需要新建的组件

| 组件 | 说明 | 技术栈 | 初始资源 (req/lim) | 交付批次 |
|------|------|--------|-------------------|----------|
| **WeBuild Auth Service** | 统一认证 | Python (FastAPI) + JWT | 100m/500m · 128Mi/512Mi | M1 |
| **WeBuild Relay Server** | WebSocket ACP 中继，替代 `code.grok.com` | Python (FastAPI) + WebSocket | 200m/1C · 256Mi/1Gi | M2a |
| **WeBuild Web IDE** | 浏览器前端 | TypeScript (Next.js) | 200m/1C · 256Mi/1Gi | M2a |
| **WeBuild Gateway** | 沙箱生命周期，优先兼容 `SandboxClient` REST | Python (FastAPI) + WS | 100m/500m · 128Mi/512Mi | M2b |
| **WeBuild Cloud Sandbox** | K8s Pod 隔离执行环境 | Docker + ACK 弹性节点池 | 1C/2C · 2Gi/4Gi per pod | M2b |
| **WeBuild Hub Broker** | 工具路由，替代 `computer-hub.grok.com` | **优先 Rust**（复用 `xai-tool-protocol`）；备选 Python 子集 | 200m/1C · 256Mi/1Gi | M2c |
| **合计 (核心, 1 replica, 不含沙箱 Pod)** | | | **800m / 1Gi req** | |

### 2.3 不需要的组件

| 上游组件 | 原因 |
|---------|------|
| `cli-chat-proxy.grok.com` | 上游 xAI 内部服务，WeBuild 使用 DashScope 直连模型（沙箱 REST 形状可复用，服务不复用） |
| `assets.grok.com` | 静态资源服务器，WeBuild 自行托管 |
| xAI OIDC 认证作为唯一登录 | WeBuild 使用 API Key + 自建 JWT；企业 OIDC 为后续扩展 |

### 2.4 现状中的阻塞点（v0.2 增补）

| 阻塞 | 代码位置 | 影响 |
|------|----------|------|
| Relay 仅允许 `is_xai_auth()` | `agent/relay.rs` → `RelayConfig::for_session` | API Key 用户**不会**启动 Relay |
| Cloud 扩展要求 xAI auth | `mvp_agent` 中 `x.ai/cloud/*` + `require_xai_auth` | 企业 JWT/API Key 无法用云沙箱 API |
| Hub 默认 URL 写死上游 | `leader/server.rs` → `PROD_COMPUTER_HUB_URL` | 需配置/默认改为自建 |
| 无 Relay/Hub **服务端**实现 | 仅有 client SDK | 必须新建并做协议兼容测试 |
| Gateway 客户端期望 cli-chat-proxy 路径 | `remote/agent.rs` → `SandboxClient` | 新 Gateway 应对齐或提供 adapter |

---

## 3. 目标架构

### 3.1 总体架构

```
                            ┌─────────────────────────────────────┐
                            │        阿里云 ACK (Kubernetes)        │
                            │                                     │
┌──────────┐    HTTPS/WSS   │  ┌───────────────────────────────┐  │
│          │ ──────────────→│  │  WeBuild Web IDE (Next.js)    │  │
│  浏览器   │                │  │  - 会话管理 UI                 │  │
│          │←──────────────│  │  - 代码查看/编辑                 │  │
└──────────┘    ACP/WS      │  │  - 终端输出展示                 │  │
                            │  │  - 权限审批交互                 │  │
┌──────────┐    HTTPS       │  └───────────┬───────────────────┘  │
│          │ ──────────────→│              │ ACP over WebSocket   │
│  本地    │                │  ┌───────────▼───────────────────┐  │
│  webuild │←───── WSS ────│  │  WeBuild Relay Server          │  │
│  TUI     │                │  │  (FastAPI + WebSocket)         │  │
│  CLI     │                │  │  - ACP 消息路由                 │  │
└──────────┘                │  │  - 会话同步/持久化              │  │
     │                      │  │  - 认证代理                    │  │
     │ ACP (Unix Socket)    │  └───────────┬───────────────────┘  │
     ▼                      │              │                       │
┌──────────────┐            │  ┌───────────▼───────────────────┐  │
│ MvpAgent     │            │  │  WeBuild Hub Broker             │  │
│ (Leader 进程) │            │  │  (FastAPI + WebSocket)         │  │
│ ├─ Session   │── WSS ────│  │  │  - 工具路由 (session,tool)    │  │
│ │  Actor     │            │  │  - 连接管理                     │  │
│ ├─ Sampler   │            │  │  - 并发控制                     │  │
│ └─ ToolBridge│            │  └───────────┬───────────────────┘  │
└──────────────┘            │              │                       │
                            │  ┌───────────▼───────────────────┐  │
                            │  │  WeBuild Gateway               │  │
                            │  │  (FastAPI + WebSocket)         │  │
                            │  │  - 沙箱生命周期管理              │  │
                            │  │  - ACP 代理                    │  │
                            │  └───────────┬───────────────────┘  │
                            │              │                       │
                            │  ┌───────────▼───────────────────┐  │
                            │  │  Cloud Sandbox Pods            │  │
                            │  │  (Docker in K8s)               │  │
                            │  │  - webuild agent (headless)    │  │
                            │  │  - 隔离文件系统                  │  │
                            │  │  - 资源限制                     │  │
                            │  └────────────────────────────────┘  │
                            │                                     │
                            │  ┌────────────────────────────────┐  │
                            │  │  WeBuild Auth Service           │  │
                            │  │  (FastAPI)                      │  │
                            │  │  - JWT 签发/验证                │  │
                            │  │  - API Key 管理                 │  │
                            │  │  - RBAC                        │  │
                            │  └────────────────────────────────┘  │
                            └─────────────────────────────────────┘
```

### 3.2 数据流概览

#### 场景 A：Web IDE 驱动本地 Agent

```
浏览器 (Web IDE)
  │ ACP over WebSocket
  ▼
Relay Server
  │ ACP over WebSocket
  ▼
本地 Leader 进程 (MvpAgent)
  │ 内部 ACP (Unix Socket)
  ▼
SessionActor → Sampler → Qwen3.7-max (DashScope)
                    │
                    ▼ 模型返回 tool_call
              ToolBridge → WorkspaceOps → 本地文件系统/终端
```

#### 场景 B：云端沙箱 Agent

```
浏览器 (Web IDE)
  │ ACP over WebSocket
  ▼
Gateway
  │ ACP over WebSocket
  ▼
沙箱 Pod 内的 webuild agent (headless)
  │
  ├─ 需要操作本地代码？
  │    │ JSON-RPC over WebSocket
  │    ▼
  │  Hub Broker
  │    │ JSON-RPC over WebSocket
  │    ▼
  │  本地 Leader (ToolServer 身份)
  │    → WorkspaceOps → 本地文件系统/终端
  │
  └─ 在沙箱内执行？
       → 沙箱内 ToolBridge → 沙箱文件系统/终端
```

---

## 4. Web IDE 方案

### 4.1 技术选型

| 层 | 选择 | 理由 |
|---|------|------|
| 框架 | Next.js 14 (App Router) | 团队已有经验，SSR 首屏快，路由灵活 |
| UI | Tailwind CSS + shadcn/ui | 快速构建，组件质量高 |
| 状态 | Zustand | 轻量，适合 WebSocket 驱动的状态 |
| 编辑器 | Monaco Editor (只读查看 + 轻量编辑) | 不追求完整 IDE，够用即可 |
| 终端 | xterm.js | 展示 Agent 的终端输出 |
| WebSocket | 原生 WebSocket + reconnecting-websocket | ACP 消息传输 |
| Markdown | react-markdown + remark-gfm | 渲染 Agent 的 Markdown 回复 |

### 4.2 页面结构

```
/                           # 首页/仪表盘
├── /sessions               # 会话列表
│   └── /sessions/[id]      # 会话详情（核心页面）
│       ├── 对话流（SessionNotification 渲染）
│       ├── 代码查看面板（Monaco）
│       ├── 终端输出（xterm.js）
│       └── 权限审批弹窗
├── /sandboxes              # 沙箱管理
│   ├── /sandboxes/new      # 创建沙箱
│   └── /sandboxes/[id]     # 沙箱详情 + 会话
├── /settings               # 设置
│   ├── /settings/models    # 模型配置
│   ├── /settings/api-keys  # API Key 管理
│   └── /settings/team      # 团队成员管理
└── /admin                  # 管理后台
    ├── /admin/users        # 用户管理
    ├── /admin/usage        # 用量统计
    └── /admin/audit        # 审计日志
```

### 4.3 核心交互流程

#### 4.3.1 会话创建

```
用户点击"新建会话"
  │
  ▼
POST /api/relay/sessions
  │ 返回 { sessionId, wsUrl }
  │
  ▼
WebSocket 连接 wsUrl
  │
  ▼ 发送 ACP Initialize
  ▼ 发送 ACP session/new
  │ 返回 { sessionId, model, capabilities }
  │
  ▼
进入会话页面，等待 session/update 通知
```

#### 4.3.2 对话交互

```
用户在输入框输入 prompt
  │
  ▼
WebSocket 发送 ACP session/prompt
  │
  ▼ 接收 stream: session/update (UserMessageChunk)     → 回显用户消息
  ▼ 接收 stream: session/update (AssistantMessageChunk) → 流式渲染模型回复
  ▼ 接收 stream: session/update (ToolCallStarted)       → 显示工具调用卡片
  ▼ 接收 stream: session/update (ToolCallCompleted)     → 显示工具结果
  ▼ 接收 stream: session/update (TurnCompleted)         → 标记 turn 结束
  │
  ▼ 如果收到 RequestPermission
  │  → 弹出权限审批弹窗
  │  → 用户批准/拒绝
  │  → WebSocket 回复 permission response
  │
  ▼ 循环，直到 TurnCompleted
```

#### 4.3.3 关键 UI 组件

| 组件 | 数据源 (ACP) | 渲染方式 |
|------|-------------|---------|
| **消息气泡** | `SessionUpdate::UserMessageChunk` / `AssistantMessageChunk` | Markdown 渲染 + 代码高亮 |
| **工具调用卡片** | `ToolCallStarted` / `ToolCallCompleted` | 折叠面板：工具名 + 参数 + 结果 |
| **终端面板** | `TerminalCreate` / `TerminalOutput` | xterm.js 实时渲染 |
| **代码查看器** | 从 `ToolCallCompleted` 的 read_file 结果提取 | Monaco Editor |
| **权限弹窗** | `RequestPermission` | 模态框：命令预览 + 批准/拒绝 |
| **文件树** | `list_dir` 工具结果 | 树形组件 |
| **Todo 面板** | `todo_write` 工具结果 | 任务列表（checkbox） |
| **状态栏** | `TurnCompleted` meta (tokens, model) | 底部状态栏 |

### 4.4 ACP Client SDK (TypeScript)

需要实现一个轻量的 TypeScript ACP Client SDK，封装 WebSocket 通信：

```typescript
// packages/webuild-acp-client/src/index.ts

interface AcpClient {
  // 连接管理
  connect(wsUrl: string, token: string): Promise<InitializeResponse>;
  disconnect(): void;
  onDisconnect(handler: (reason: DisconnectReason) => void): void;

  // 会话管理
  newSession(opts: NewSessionRequest): Promise<NewSessionResponse>;
  loadSession(sessionId: string): Promise<LoadSessionResponse>;
  closeSession(sessionId: string): Promise<void>;
  listSessions(): Promise<SessionInfo[]>;

  // 对话
  prompt(sessionId: string, content: PromptContent): Promise<PromptResponse>;
  cancel(sessionId: string): void;

  // 事件订阅
  onSessionUpdate(handler: (update: SessionUpdate) => void): void;
  onPermissionRequest(handler: (req: PermissionRequest) => Promise<PermissionResponse>): void;
  onTerminalOutput(handler: (output: TerminalOutput) => void): void;

  // 配置
  setModel(sessionId: string, model: string): Promise<void>;
  setAutoMode(sessionId: string, mode: AutoMode): Promise<void>;
}
```

### 4.5 Relay Server API 扩展

在 Relay Server 中需要提供 Web IDE 所需的 REST API：

```
POST   /api/relay/sessions              # 创建会话（代理 ACP session/new）
GET    /api/relay/sessions              # 列出会话
GET    /api/relay/sessions/:id          # 获取会话详情
DELETE /api/relay/sessions/:id          # 关闭会话

GET    /api/relay/sessions/:id/history  # 获取历史消息（从持久化存储读取）
POST   /api/relay/sessions/:id/share    # 生成分享链接

GET    /api/models                      # 获取可用模型列表
POST   /api/models/switch               # 切换模型

GET    /api/usage                       # 用量统计
GET    /api/health                      # 健康检查
```

---

## 5. 云端沙箱方案

### 5.1 沙箱架构

每个沙箱是一个 Kubernetes Pod，内含：

```
┌─────────────────────────────────────────┐
│  Sandbox Pod (K8s)                       │
│                                         │
│  ┌─────────────────────────────────────┐ │
│  │  webuild agent (headless mode)      │ │
│  │  - ACP over WebSocket (入口)         │ │
│  │  - 模型调用 → DashScope             │ │
│  │  - 工具执行 → 沙箱本地 FS / Hub     │ │
│  └──────────────┬──────────────────────┘ │
│                 │                        │
│  ┌──────────────▼──────────────────────┐ │
│  │  沙箱工具层                          │ │
│  │  - read_file / search_replace       │ │
│  │  - run_terminal_cmd (沙箱内执行)     │ │
│  │  - grep / list_dir                  │ │
│  │  - MCP tools (如果配置)              │ │
│  └──────────────┬──────────────────────┘ │
│                 │                        │
│  ┌──────────────▼──────────────────────┐ │
│  │  隔离文件系统 (emptyDir / PVC)       │ │
│  │  /workspace/  ← 用户代码            │ │
│  │  /tmp/        ← 临时文件            │ │
│  └─────────────────────────────────────┘ │
│                                         │
│  资源限制:                               │
│  - CPU: 1 core (request) / 2 (limit)    │
│  - Memory: 2Gi (request) / 4Gi (limit)  │
│  - Ephemeral Storage: 10Gi              │
│  - Network: 仅允许出站到 DashScope      │
│  - 调度: 沙箱专用节点池 (Spot Instance)  │
│  - TTL: 最长 4 小时                     │
└─────────────────────────────────────────┘
```

### 5.2 沙箱生命周期

```
用户点击"创建沙箱"
  │
  ▼
POST /api/gateway/sandboxes
  │ Gateway 生成沙箱配置
  │ → K8s API 创建 Pod + Service + NetworkPolicy
  │ → 等待 Pod Ready
  │ → webuild agent 启动 (headless)
  │
  ▼ 返回 { sandboxId, wsUrl, status }
  │
  ▼
Web IDE 连接 wsUrl (ACP over WebSocket)
  │ 正常使用 Agent（对话 + 工具调用）
  │
  ▼ 沙箱内 Agent 需要操作本地代码？
  │ → 通过 Hub Broker 路由到本地 Leader
  │
  ▼ 用户关闭 / TTL 到期 / 手动终止
  │
  ▼
DELETE /api/gateway/sandboxes/:id
  │ Gateway drain Agent sessions
  │ → K8s API 删除 Pod
  │ → 清理 NetworkPolicy + Service
  │
  ▼ 可选: 导出 workspace 内容 (git diff / tar)
```

### 5.3 Gateway 服务设计

Gateway 管理沙箱的完整生命周期，替代上游 `grok.com/ws/gw/` **与** cli-chat-proxy 的 sandbox REST。

**API 对齐原则（v0.2）**：仓库内已有 `SandboxClient`（`remote/agent.rs`）与完整请求/响应类型。
新建 Gateway 时 **优先兼容下列路径**（可通过统一 base URL 指向自建 Gateway），避免 Web 与 TUI 双轨：

```
POST   /sandbox/sessions/start
DELETE /sandbox/sessions/{id}
GET    /sandbox/sessions/{id}/status
GET    /sandbox/sessions/{id}/logs
POST   /sandbox/sessions/{id}/hibernate    # P2 / 后置
POST   /sandbox/sessions/{id}/restore      # P2 / 后置
GET    /sandbox/environments
POST   /sandbox/environments
...
```

若对外网关需要 `/api/gateway/*` 前缀，必须在同一迭代提供 **兼容 adapter** 或同步修改 `SandboxClient`。

Gateway 管理沙箱的完整生命周期：

```python
# 核心数据模型

class SandboxEnvironment(BaseModel):
    """沙箱环境模板"""
    id: str
    name: str
    description: str
    container_image: str          # e.g. "registry.cn-hangzhou.aliyuncs.com/webuild/sandbox:latest"
    setup_script: str | None      # Pod 启动后执行的初始化脚本
    repository: str | None        # Git 仓库 URL（自动 clone）
    default_branch: str           # 默认分支
    resource_profile: str         # "small" | "medium" | "large"
    max_ttl_seconds: int          # 最大存活时间
    network_policy: str           # "restricted" | "open"

class SandboxSession(BaseModel):
    """沙箱实例"""
    id: str
    environment_id: str
    user_id: str
    status: SandboxStatus         # creating | running | hibernating | terminated
    pod_name: str
    ws_url: str
    created_at: datetime
    expires_at: datetime
    last_activity_at: datetime

class SandboxStatus(str, Enum):
    CREATING = "creating"
    RUNNING = "running"
    HIBERNATING = "hibernating"     # 暂停但未销毁
    TERMINATED = "terminated"
```

#### Gateway REST API

**推荐（与 `SandboxClient` 对齐）**：

```
# 环境模板
GET    /sandbox/environments
POST   /sandbox/environments
GET    /sandbox/environments/{id}
PUT    /sandbox/environments/{id}
DELETE /sandbox/environments/{id}

# 会话 / 沙箱实例
POST   /sandbox/sessions/start
DELETE /sandbox/sessions/{id}
GET    /sandbox/sessions/{id}/status
GET    /sandbox/sessions/{id}/logs
POST   /sandbox/sessions/{id}/hibernate   # 后置
POST   /sandbox/sessions/{id}/restore     # 后置
POST   /sandbox/sessions/fork             # 后置

# 健康检查
GET    /health
```

**可选别名**（BFF / 文档友好，非 TUI 必需）：

```
POST   /api/gateway/sandboxes          → 内部映射 start
DELETE /api/gateway/sandboxes/:id      → terminate
GET    /api/gateway/sandboxes/:id/*    → status/logs
```

### 5.4 沙箱容器镜像

```dockerfile
# Dockerfile.sandbox
FROM ubuntu:24.04

# 基础工具
RUN apt-get update && apt-get install -y \
    git curl wget build-essential \
    python3 python3-pip \
    nodejs npm \
    ripgrep fd-find \
    && rm -rf /var/lib/apt/lists/*

# 安装 webuild
COPY webuild-linux-x86_64 /usr/local/bin/webuild
RUN chmod +x /usr/local/bin/webuild

# 沙箱初始化脚本
COPY scripts/sandbox-init.sh /opt/sandbox-init.sh

# 工作目录
WORKDIR /workspace

# 入口: headless agent
ENTRYPOINT ["webuild", "agent", "stdio", "--headless"]
```

### 5.5 代码同步策略

沙箱需要访问用户代码，有三种模式。**实施顺序强制为 1 → 3 → 2**（Hub 最后）：

| 顺序 | 模式 | 机制 | 适用场景 | 里程碑 |
|------|------|------|---------|--------|
| 1 | **Git Clone** | 创建沙箱时 clone 到 `/workspace` | 独立项目、不需要回写本地 | M2b |
| 2 | **文件上传** | Web IDE 上传 (`workspace.put_files`) | 临时文件、补丁 | M2b/P1 |
| 3 | **Hub 代理** | 沙箱经 Hub 路由到本地 Leader | 操作开发者本机工作区 | M2c |

### 5.6 Hub Broker 设计

Hub Broker 是 `computer-hub.grok.com` 的替代实现。由于 Hub SDK（ToolServer / ToolHarness）已在 Rust 中完整实现，**Broker 是唯一需要新建的服务端组件**。

#### 核心职责

```
ToolServer (本地 Leader)  ──register──→  Hub Broker  ←──call──  ToolHarness (沙箱 Agent)
                                          │
                                     路由决策:
                                     (session_id, tool_id)
                                     → 找到对应 ConnectionId
                                     → 转发 tool_call_request
                                     → 返回 tool_call_result
```

#### 路由表数据结构

```python
class RoutingTable:
    """工具路由表"""

    # 正向索引: connection_id → {tool_id → ToolRegistration}
    connections: dict[str, ConnectionRecord]

    # 反向索引: (session_id, tool_id) → connection_id
    session_bindings: dict[tuple[str, str], str]

    # 连接元数据: connection_id → {user_id, server_id, kind}
    connection_meta: dict[str, ConnectionMeta]
```

#### Broker WebSocket 协议

Broker 复用现有 Hub SDK 的 JSON-RPC 2.0 协议，无需修改客户端代码：

```
1. WebSocket 连接 + Bearer Token
2. Hello 握手: { protocol_version, kind: "ToolServer"|"Harness", server_id }
3. ToolServer: serve { session_id, tools: [...] }  → 注册工具
4. ToolServer: session.bind { session_id }          → 绑定会话
5. Harness:    tool.call { session_id, tool_id, arguments, tool_call_id }
6. Broker 路由到对应 ToolServer 的 connection
7. ToolServer 返回 tool_call_result
8. Broker 转发给 Harness
```

#### 实现策略（v0.2 修订）

**MVP（M2c）**：只实现 method **白名单子集**（见 backlog EPI-4）：

- 必须：`hello` / `hello_ack` / `ping`/`pong` / `serve` / `session.bind` / `session.unbind` / `tool.call` / `tool_call_request`（及 SDK 依赖的 progress/changed 最小集）
- 延后：`tools.search`、donate 全系列、`session_attach_server`、完整 hook 矩阵

**实现语言**：

| 选项 | 建议 | 理由 |
|------|------|------|
| **Rust Broker（推荐）** | 默认 | 与 `xai-tool-protocol` / SDK 同构，降低 wire 漂移 |
| Python 子集 | 备选 | 仅当团队人力强约束且 SPIKE-3 证明子集足够 |

**扩展**：性能瓶颈时水平扩展（sticky by `session_id`），而非先上「全协议 Python」。

**强制门禁**：SPIKE-3（hello→serve→bind→tool.call 与 Rust SDK 互通）通过前，不启动 Broker 全面开发。

---

## 6. 认证与权限体系

### 6.1 认证方案

WeBuild 产品默认是 **API-key-first**（DashScope / `WEBUILD_API_KEY`），**不是** xAI OIDC。
云服务认证必须覆盖这一事实，禁止继续假设「只有 grok.com 登录用户才需要 Relay」。

```
┌──────────────────────────────────────────────────────┐
│  WeBuild Auth Service                                │
│                                                      │
│  认证方式:                                            │
│  ├─ API Key (CLI/TUI 主路径)                          │
│  │   └─ DASHSCOPE_API_KEY / WEBUILD_API_KEY          │
│  │   └─ 可向 Auth 换取短时 Relay/Hub JWT（推荐）       │
│  ├─ JWT Token (Web IDE / 服务间 / Relay 建连)          │
│  │   └─ Auth Service 签发，RS256                      │
│  └─ OIDC (企业 SSO, 未来扩展)                         │
│      └─ 对接公司 SSO (LDAP/AD)                        │
│                                                      │
│  Token 结构:                                         │
│  {                                                   │
│    "sub": "user_id",                                 │
│    "iss": "auth.webuild.jarvikheart.cn",             │
│    "aud": ["webuild-relay", "webuild-hub", ...],     │
│    "scopes": ["agent.use", "sandbox.create", ...],   │
│    "exp": 1234567890                                 │
│  }                                                   │
└──────────────────────────────────────────────────────┘
```

### 6.2 权限模型 (RBAC)

```python
class Role(str, Enum):
    ADMIN = "admin"           # 全部权限
    DEVELOPER = "developer"   # 使用 Agent + 创建沙箱
    VIEWER = "viewer"         # 只读查看会话

class Permission(str, Enum):
    # Agent 操作
    AGENT_USE = "agent.use"
    AGENT_MANAGE_SESSIONS = "agent.manage_sessions"

    # 沙箱操作
    SANDBOX_CREATE = "sandbox.create"
    SANDBOX_MANAGE = "sandbox.manage"

    # 管理操作
    ADMIN_USERS = "admin.users"
    ADMIN_AUDIT = "admin.audit"
    ADMIN_BILLING = "admin.billing"

    # 工具权限
    TOOL_BASH = "tool.bash"          # 是否允许执行 shell 命令
    TOOL_FILE_WRITE = "tool.file_write"
    TOOL_NETWORK = "tool.network"    # 是否允许网络访问
```

### 6.3 与现有 Leader 的集成

本地 Leader / Agent 需要 **端点配置 + 鉴权门禁改造**（工作量中等，不可省略）。

#### 6.3.1 端点（小）

`xai-webuild-env` 已支持 `WEBUILD_PRODUCTION_*` 覆盖。将默认生产端点改为自建域名，并文档化：

```text
WEBUILD_PRODUCTION_WS_URL           # Relay（注意：后缀为 _WS_URL）
WEBUILD_PRODUCTION_GATEWAY_WS_URL
WEBUILD_AUTH_SERVICE_URL            # 新增
# Hub：Leader 侧现有 hub_url / 默认 computer-hub.grok.com，改为可配置默认
```

建议默认：

| 用途 | URL |
|------|-----|
| Auth | `https://auth.webuild.jarvikheart.cn` |
| Relay | `wss://relay.webuild.jarvikheart.cn/ws/agent`（以 SPIKE-1 路径为准） |
| Hub | `wss://hub.webuild.jarvikheart.cn/v1/tools` |
| Gateway | `wss://gateway.webuild.jarvikheart.cn/ws/gw/` 或 REST base |

#### 6.3.2 鉴权门禁（中，阻塞 M2a）

必须修改的行为：

| 现状 | 目标 |
|------|------|
| `RelayConfig::for_session` 要求 `is_xai_auth()` | 接受 WeBuild JWT，或「API Key → Auth 换 ticket」后的 bearer |
| `x.ai/cloud/*` 使用 `require_xai_auth` | 改为 scopes：`sandbox.create` / `sandbox.manage` 等 |
| Hub `AuthProvider` 绑 OIDC 假设 | 支持 WeBuild JWT / 服务账号 token |

**推荐集成路径**：

```
CLI API Key ──► Auth Service (exchange) ──► short-lived JWT
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
                 Relay WS                  Hub WS                   Gateway REST
```

Web IDE 用户则直接 login 拿 JWT，无需 exchange。

详细任务见 backlog **EPI-1.5** 与 **SPIKE-2**。

---

## 7. 安全模型

### 7.1 纵深防御

```
┌─ 第 1 层: 网络 ──────────────────────────────────────────────┐
│  - 所有外部通信强制 WSS/HTTPS                                 │
│  - K8s NetworkPolicy: 沙箱仅可出站 DashScope + Hub Broker     │
│  - 内网服务间 mTLS (可选)                                     │
├─ 第 2 层: 认证 ──────────────────────────────────────────────┤
│  - JWT Token + API Key 双因子                                 │
│  - Token 短有效期 (1h)，Refresh Token 轮换                     │
│  - 服务间通信: Service Account Token                          │
├─ 第 3 层: 授权 ──────────────────────────────────────────────┤
│  - RBAC: 角色决定可执行的 API 操作                             │
│  - Session 隔离: 用户只能访问自己的会话                         │
│  - Hub 路由: (session_id, tool_id) 绑定，跨 session 不可调用   │
├─ 第 4 层: 沙箱隔离 ──────────────────────────────────────────┤
│  - K8s Pod 隔离: 独立 namespace, 独立 ServiceAccount          │
│  - 资源限制: CPU/Memory/Storage/Network                       │
│  - 文件系统: emptyDir (非持久化) 或 PVC (可选持久化)           │
│  - 进程隔离: 沙箱内 Agent 无法访问宿主机                       │
├─ 第 5 层: 工具权限 ──────────────────────────────────────────┤
│  - PermissionHandle: YOLO / Auto / Interactive 模式           │
│  - HITL (Human-in-the-loop): 危险操作需要 Web IDE 弹窗确认    │
│  - Local-shadows-remote: 本地工具永远优先于远程                │
│  - Gitignore 强制执行                                         │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 沙箱安全策略

```yaml
# K8s SecurityContext for sandbox pods
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  readOnlyRootFilesystem: false    # Agent 需要写文件
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]

# NetworkPolicy: 仅允许必要的出站
egress:
  - to:
      # DashScope API
      - ipBlock: { cidr: <dashscope-ip-range> }
    ports:
      - { protocol: TCP, port: 443 }
  - to:
      # Hub Broker (集群内)
      - namespaceSelector:
          matchLabels: { name: webuild }
        podSelector:
          matchLabels: { app: hub-broker }
    ports:
      - { protocol: TCP, port: 443 }
```

### 7.3 审计日志

所有关键操作记录审计日志：

```json
{
  "timestamp": "2026-07-25T10:30:00Z",
  "user_id": "jerry.zhang",
  "action": "sandbox.create",
  "resource": "sandbox/sbx_abc123",
  "details": {
    "environment_id": "env_default",
    "container_image": "registry.cn-hangzhou.aliyuncs.com/webuild/sandbox:v1.0"
  },
  "source_ip": "10.0.1.5",
  "result": "success"
}
```

审计范围:
- 会话创建/删除/分享
- 沙箱创建/终止/休眠/恢复
- 权限变更
- 模型切换
- 工具调用（仅记录工具名和参数摘要，不记录完整内容）

---

## 8. 部署架构

### 8.0 当前集群资源评估（2026-07-25 实测）

> 集群: ACK v1.36.1-aliyun.1 · 杭州可用区 · 3 节点

#### 节点规格与当前占用

| 节点 | 规格 | CPU Allocatable | CPU Requested | 内存 Allocatable | 内存 Requested |
|------|------|-----------------|---------------|------------------|----------------|
| 10.87.37.37 | 4C/16G | 3920m | 3815m (97%) 🔴 | 14.3Gi | 5.0Gi (34%) |
| 10.94.219.179 | 4C/16G | 3920m | 3445m (87%) 🟡 | 14.3Gi | 4.0Gi (28%) |
| 10.94.219.249 | 4C/16G | 3920m | 3225m (82%) 🟡 | 14.3Gi | 4.5Gi (31%) |
| **合计** | **12C/48G** | **11760m** | **10485m (89%)** | **42.9Gi** | **13.5Gi (31%)** |

- **CPU requests 偏高**（89%），仅剩 ~1.3 cores 可分配
- **CPU 实际使用极低**（~450m / 3.8%），大量 request 是保守声明
- **内存充裕**（31%），剩余 ~29Gi
- 已有负载: `jarvildatavault` (2.8C/4.2Gi), `arms-prom` (1.3C/1.5Gi), `xingu` (1.6C/1.3Gi), `kube-system` (3.5C/3.5Gi) 等

#### 已有基础设施（可直接复用）

| 组件 | 状态 | 备注 |
|------|------|------|
| Nginx Ingress Controller | ✅ | 2 replicas，通过阿里云 NLB 暴露 |
| cert-manager | ✅ | 可为新域名签发 TLS 证书 |
| metrics-server | ✅ | HPA 可用 |
| ARMS Prometheus | ✅ | 集群监控已接入 |
| StorageClass | ✅ | alicloud-disk-essd / ssd / efficiency |
| NLB | ✅ | `nlb-ojay7qm1jdz4g4fuzb.cn-hangzhou.nlb.aliyuncsslb.com` |

#### 扩容计划

| 阶段 | 操作 | 新增资源 | 理由 |
|------|------|---------|------|
| **Phase 0** | 新增 **2 个节点**（4C/16G） | +8C / +32G | WeBuild 核心服务初始部署 |
| **Phase 4** | 新增**沙箱专用节点池**（按需扩缩） | 按沙箱数量弹性 | 沙箱 Pod 资源隔离，使用抢占式实例降本 |
| 备选 | 现有节点升配到 8C/32G | 每节点翻倍 | 如果 4C/16G 碎片化严重 |

**Phase 0 扩容后资源预估**（5 节点, 20C/80G）:

| 类别 | CPU Requests | 内存 Requests |
|------|-------------|---------------|
| 现有负载 | 10.5 cores | 13.5Gi |
| WeBuild 核心服务 | ~1.5 cores | ~3.5Gi |
| **合计** | **~12 cores / 19.6 allocatable (61%)** | **~17Gi / 71.5Gi (24%)** |
| **剩余** | **~7.6 cores** | **~54.5Gi** |

### 8.1 Kubernetes 部署

```yaml
# 命名空间规划
namespaces:
  webuild-system:     # Auth Service, Relay, Hub Broker, Gateway, Web IDE
  webuild-sandbox:    # 用户沙箱 Pod (动态创建/销毁)
  # webuild-monitoring 不需要 — 复用现有 arms-prom namespace

# ── 核心服务部署 ──
# 初始阶段（Phase 1-3）使用 1 replica，用户量增长后再扩到 2+
# WebSocket 服务 (relay/hub) 扩 replica 时需配合 NLB sticky session

deployments:

  # Auth Service — JWT 签发/验证, API Key 管理
  auth-service:
    replicas: 1          # 初期 1，Phase 5 扩到 2
    image: registry.cn-hangzhou.aliyuncs.com/webuild/auth-service
    resources:
      requests: { cpu: "100m", memory: "128Mi" }
      limits:   { cpu: "500m", memory: "512Mi" }

  # Relay Server — WebSocket ACP 中继
  relay-server:
    replicas: 1          # WebSocket 长连接，初期 1 够用
    image: registry.cn-hangzhou.aliyuncs.com/webuild/relay-server
    resources:
      requests: { cpu: "200m", memory: "256Mi" }
      limits:   { cpu: "1",    memory: "1Gi" }

  # Hub Broker — 工具路由
  hub-broker:
    replicas: 1          # Phase 4 上线，初期 1
    image: registry.cn-hangzhou.aliyuncs.com/webuild/hub-broker
    resources:
      requests: { cpu: "200m", memory: "256Mi" }
      limits:   { cpu: "1",    memory: "1Gi" }

  # Gateway — 沙箱生命周期管理
  gateway:
    replicas: 1          # Phase 4 上线，初期 1
    image: registry.cn-hangzhou.aliyuncs.com/webuild/gateway
    resources:
      requests: { cpu: "100m", memory: "128Mi" }
      limits:   { cpu: "500m", memory: "512Mi" }

  # Web IDE — Next.js 前端
  web-ide:
    replicas: 1          # 初期 1，Phase 5 扩到 2-3
    image: registry.cn-hangzhou.aliyuncs.com/webuild/web-ide
    resources:
      requests: { cpu: "200m", memory: "256Mi" }
      limits:   { cpu: "1",    memory: "1Gi" }

# ── 核心服务资源合计（1 replica 初始配置）──
# CPU requests:    800m
# Memory requests: 1024Mi (~1Gi)
# CPU limits:      3500m
# Memory limits:   3584Mi (~3.5Gi)
```

### 8.1b 沙箱 Pod 资源配置（M2b / Phase 3）

```yaml
# 沙箱 Pod — 按需创建，运行在 webuild-sandbox namespace
# 使用独立节点池，不占用核心服务的节点资源

sandbox-pod:
  resources:
    requests: { cpu: "1",    memory: "2Gi" }       # 降低 request 提高调度成功率
    limits:   { cpu: "2",    memory: "4Gi" }
    ephemeral-storage: "10Gi"                        # 从 20Gi 降到 10Gi
  ttl: 4h                                            # 最长存活 4 小时
  nodeSelector:
    webuild-role: sandbox                            # 调度到沙箱专用节点池
  tolerations:
    - key: "sandbox"
      operator: "Exists"
      effect: "NoSchedule"

# 沙箱节点池配置（阿里云 ACK 弹性节点池）:
#   - 实例规格: ecs.c7.xlarge (4C/8G) 或 ecs.c7.2xlarge (8C/16G)
#   - 付费方式: 抢占式实例 (Spot Instance)，成本约为按量的 1/5
#   - 最小节点数: 0（无沙箱时缩到 0）
#   - 最大节点数: 10
#   - 弹性策略: Cluster Autoscaler
#
# 容量估算 (以 8C/16G 节点为例):
#   - 每节点可调度: ~7 个沙箱 (受 2Gi request 限制)
#   - 10 节点 = 70 并发沙箱
#   - 月成本估算: 10 × ecs.c7.2xlarge 抢占式 ≈ ¥1500-2500/月
```

### 8.2 基础设施依赖

| 组件 | 选择 | 用途 | 部署位置 |
|------|------|------|---------|
| **数据库** | PostgreSQL (阿里云 RDS) | 用户、会话元数据、审计日志 | **集群外** — 不占用 K8s 资源 |
| **缓存** | Redis (阿里云 Redis) | JWT 黑名单、会话状态缓存、限流 | **集群外** — 不占用 K8s 资源 |
| **对象存储** | 阿里云 OSS | 会话历史归档、文件上传 | **集群外** |
| **容器镜像** | 阿里云 ACR | webuild 二进制 + 沙箱镜像 | 已有 ACR 实例 |
| **负载均衡** | 阿里云 NLB (已有) | WebSocket sticky session (IP hash) | 复用 `nlb-ojay7qm1jdz4g4fuzb` |
| **域名** | `*.webuild.jarvikheart.cn` | 服务子域名 | DNS 指向现有 NLB |
| **TLS** | cert-manager (**已安装**) | 自动证书管理 | 复用 `cert-manager` namespace |
| **监控** | ARMS Prometheus (**已安装**) | 指标采集 + 告警 | 复用 `arms-prom` namespace |
| **日志** | 阿里云 SLS | 集中日志 | 集群外 |

### 8.3 域名规划

```
webuild.jarvikheart.cn              → Web IDE (Next.js)
api.webuild.jarvikheart.cn          → REST API 聚合入口
auth.webuild.jarvikheart.cn         → Auth Service
relay.webuild.jarvikheart.cn        → Relay Server (WebSocket)
hub.webuild.jarvikheart.cn          → Hub Broker (WebSocket)
gateway.webuild.jarvikheart.cn      → Gateway (WebSocket + REST)
grafana.webuild.jarvikheart.cn      → 监控面板
```

### 8.4 CI/CD 流水线（扩展现有 GitHub Release）

```yaml
# 在现有 GitHub Release 工作流基础上扩展（见 .github/workflows/release.yml）:
# 服务镜像可另建 workflow 或同 workflow 增 job

stages:
  - build          # Rust CLI 二进制 (已有 Release)
  - build-images   # 服务 + 沙箱 Docker 镜像 (新增)
  - publish        # GitHub Release (已有)
  - deploy         # K8s 部署 (新增，staging 自动 / 生产手动)

build-images:
  stage: build-images
  script:
    - docker build -t $ACR_REGISTRY/webuild/relay-server:$CI_COMMIT_SHA services/relay/
    - docker build -t $ACR_REGISTRY/webuild/hub-broker:$CI_COMMIT_SHA services/hub/
    - docker build -t $ACR_REGISTRY/webuild/gateway:$CI_COMMIT_SHA services/gateway/
    - docker build -t $ACR_REGISTRY/webuild/web-ide:$CI_COMMIT_SHA services/web-ide/
    - docker build -t $ACR_REGISTRY/webuild/auth-service:$CI_COMMIT_SHA services/auth/
    - docker build -t $ACR_REGISTRY/webuild/sandbox:$CI_COMMIT_SHA sandbox/
    - docker push $ACR_REGISTRY/webuild/*:$CI_COMMIT_SHA

deploy-staging:
  stage: deploy
  environment: staging
  script:
    - helm upgrade --install webuild ./helm/webuild
      --namespace webuild-system
      --set global.imageTag=$CI_COMMIT_SHA
      --values helm/webuild/values-staging.yaml

deploy-production:
  stage: deploy
  environment: production
  when: manual      # 手动触发生产部署
  script:
    - helm upgrade --install webuild ./helm/webuild
      --namespace webuild-system
      --set global.imageTag=$CI_COMMIT_SHA
      --values helm/webuild/values-production.yaml
```

---

## 9. 实施路线

> 执行粒度（Story / AC / 依赖）以 [`phase-ii-backlog.md`](./phase-ii-backlog.md) 为准。
> 本节描述 **阶段目标与强制顺序**。

### 9.0 交付策略（强制）

1. **场景 A 优先**：浏览器 → Relay → 本地 Leader（不依赖 Hub / 沙箱）→ **M2a**
2. **场景 B-1**：独立云沙箱（Git clone，工具只打沙箱 FS）→ **M2b**
3. **场景 B-2**：Hub 将沙箱工具路由回本地 Workspace → **M2c**
4. **三个 Spike 未通过，不得进入对应 Epic 全面开发**
   - SPIKE-1 Relay 协议逆向
   - SPIKE-2 鉴权门禁改造 PoC
   - SPIKE-3 Hub wire 最小环

### 9.1 方案阶段 ↔ Backlog Epic

| 方案阶段 | 周次 | Backlog | 产出 |
|----------|------|---------|------|
| **Phase 0** 基础设施 | W1–W2 | EPI-0 | 扩容、ns、RDS/Redis、ACR、DNS/TLS、Helm 骨架 |
| **Phase 1** Auth + Rust 鉴权 | W2–W4 | EPI-1, EPI-1.5, SPIKE-1/2 | JWT/API Key；Leader 可持 WeBuild token 连 Relay |
| **Phase 2** Relay + Web IDE | W4–W8 | EPI-2 | **M2a**：场景 A 端到端可演示 |
| **Phase 3** Gateway + 独立沙箱 | W8–W11 | EPI-3 | **M2b**：沙箱内 Agent + Git clone（**无 Hub**） |
| **Phase 4** Hub Broker 子集 | W11–W14 | EPI-4, SPIKE-3 | **M2c**：沙箱 → Hub → 本地工具 |
| **Phase 5** 生产化 | W14–W16 | EPI-5 | 监控、审计、压测、文档、CI/CD、发布 runbook |

### 9.2 Phase 0: 基础设施准备 (2 周)

| 任务 | 产出 |
|------|------|
| **ACK 集群扩容: 新增 2 个节点** | 5 节点 / 20C / 80G，CPU requests 降至 ~61% |
| K8s 命名空间 + RBAC | `webuild-system`, `webuild-sandbox` |
| PostgreSQL + Redis | **阿里云 RDS + 云 Redis**（集群外） |
| ACR | `registry.cn-hangzhou.aliyuncs.com/webuild/*` |
| 域名 + DNS + TLS | `*.webuild.jarvikheart.cn`，复用 NLB + cert-manager |
| Helm Chart 骨架 | `helm/webuild/` |

### 9.3 Phase 1: Auth + 客户端鉴权 (约 3 周，含 Spike)

| 任务 | 产出 |
|------|------|
| Auth Service | login / refresh / api-keys / JWKS 或 introspect / RBAC |
| SPIKE-1 / SPIKE-2 | Relay 协议说明 + 鉴权 PoC |
| Rust 适配 (EPI-1.5) | 放开 `is_xai_auth` 门禁；token exchange；端点默认值 |
| 回归 | API Key 本地 TUI/headless 不回退 |

### 9.4 Phase 2: Relay + Web IDE MVP — 场景 A (约 4 周)

| 任务 | 产出 | 优先级 |
|------|------|--------|
| Relay WS 服务 | Agent/Browser 接入、ACP 双向转发 | P0 |
| TS ACP Client | connect / prompt / cancel / events | P0 |
| Web 会话页 | 对话流 + 工具卡片 + **权限弹窗** | P0 |
| 终端 / Monaco | xterm、只读代码查看 | P1 |
| 会话持久化 | 元数据落库；历史归档可简化 | P1 |
| 联调 | 本地 Leader ↔ Relay ↔ Web IDE | P0 |

**M2a 出门标准**：浏览器登录 → prompt → 流式回复 → 权限批准生效 → staging 可演示。

### 9.5 Phase 3: Gateway + 独立云沙箱 — 场景 B-1 (约 3 周)

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 沙箱镜像 | webuild 二进制 + 基础工具 | P0 |
| Gateway + K8s | 创建/删除 Pod，**REST 对齐 SandboxClient** | P0 |
| ACP 代理 | Web → Pod 内 headless agent | P0 |
| Git clone / TTL / NetworkPolicy | 独立沙箱闭环 | P0 |
| Web 沙箱页 | 创建/列表/进入会话 | P0 |
| Hibernate/restore | 快照恢复 | P2 后置 |
| Hub 联调 | **本阶段不做** | — |

### 9.6 Phase 4: Hub Broker — 场景 B-2 (约 3 周)

| 任务 | 产出 | 优先级 |
|------|------|--------|
| SPIKE-3 | wire 最小环证明 | P0 门禁 |
| Broker 子集 | hello/serve/bind/tool.call | P0 |
| Leader ToolServer 指自建 Hub | 配置 + 验证 | P0 |
| 沙箱 Harness → 本地工具 | session 绑定与权限 | P0 |
| 全量 protocol / donate | — | P2 后置 |

### 9.7 Phase 5: 生产化 (约 2–3 周)

| 任务 | 产出 |
|------|------|
| Metrics + 看板 | RED、WS 连接数、沙箱数 |
| 审计 | 会话/沙箱/权限 |
| 压测与安全自检 | 报告 + 清单 |
| 文档 + CI 镜像部署 | runbook；staging 自动 / 生产手动 |

### 9.8 里程碑总览

```
Week  1  2  3  4  5  6  7  8  9  10 11 12 13 14 15 16
      ├────┤                                                    Phase 0  基础设施
         ├──────┤                                               Phase 1  Auth+鉴权
            ├── SPIKE-1/2
               ├────────────────┤                               Phase 2  Relay+WebIDE (A)
                              ├──────────┤                      Phase 3  独立沙箱 (B-1)
                                    ├ SPIKE-3
                                    ├──────────┤                Phase 4  Hub (B-2)
                                          ├──────────┤          Phase 5  生产化
      ────────────────────────────────────────────────
      ▲        ▲                 ▲          ▲        ▲
      M0       M1                M2a        M2b      M2c/M3
   基础就绪  可连 Relay        Web 可用   独立沙箱   Hub+生产
```

| 里程碑 | 目标周次 | 验收一句话 |
|--------|----------|------------|
| **M0** | W2 | 可调度、可解析域名、Helm 空站可装 |
| **M1** | W4 | JWT 可用；Leader 可用 WeBuild token 连 Relay（mock 或真） |
| **M2a** | W8 | **场景 A 对外试用** |
| **M2b** | W11 | 独立云沙箱可对话 |
| **M2c** | W14 | 沙箱经 Hub 操作本地 FS |
| **M3** | W16 | 生产发布就绪 |

**时间线结论**：

- **~8 周**：最小有价值交付（M2a Web IDE + 本地 Agent）
- **~16 周**：场景 B 完整路径 + 生产化
- 原 v0.1「14 周全量生产」在单小队下 **偏紧**，已拆分里程碑

### 9.9 MVP 明确砍掉 / 后置

| 项 | 处理 |
|----|------|
| 完整 admin / team / billing UI | 后置 |
| 会话分享链接 | 后置 |
| 沙箱 hibernate/restore | P2 |
| Hub donate / 全 method | P2 |
| WebSocket 多 replica | 初期单副本 |
| Monaco 可写完整 IDE | 只读 + 工具写文件 |

---

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| **鉴权门禁导致 API Key 用户无法用 Relay/云能力** | 🔴 高 | 高 | **SPIKE-2 + EPI-1.5 置于 M2a 关键路径**；禁止合并「仅 xAI OIDC」新门禁 |
| **Hub 协议完整度被低估 / Python 全量兼容失败** | 🔴 高 | 高 | MVP 白名单；**优先 Rust Broker**；SPIKE-3 门禁 |
| **Relay 服务端无规范，逆向成本高** | 高 | 高 | SPIKE-1 时限 3–5d；先 mock 再产品化 |
| **Gateway 与 SandboxClient 双轨 API** | 中 | 中 | REST 对齐现有 client；或同迭代改 client |
| **集群 CPU requests 不足** | 高 | 高 | Phase 0 **必须先扩容**；沙箱独立节点池 |
| 14–16 周范围膨胀拖垮 M2a | 高 | 高 | 场景 A 优先；§9.9 砍 scope 清单 |
| 沙箱 Spot 回收中断任务 | 中 | 高 | grace period；关键任务非 Spot；后置自动迁移 |
| WebSocket 高并发不稳 | 中 | 高 | 单副本 + sticky；客户端重连（已有） |
| 沙箱冷启动慢 | 中 | 中 | 异步创建 UI；镜像预拉；可选预热池（后置） |
| Hub 成单点 | 低 | 高 | 初期单实例；再水平扩展 |
| DashScope 不稳 | 低 | 中 | 现有 retry；可配置 fallback |
| NetworkPolicy 误配 | 中 | 中 | staging 模板化 + 版本控制 |
| 跨团队运维协调 | 中 | 中 | Helm 标准化；提前锁定扩容窗口 |

---

## 11. 附录

### A. 现有代码修改清单（v0.2 重估）

| 文件/Crate | 修改内容 | 工作量 |
|-----------|---------|--------|
| `xai-webuild-env` | 默认端点改为自建；文档化 `WEBUILD_PRODUCTION_*` | 小 |
| `xai-webuild-shell/src/agent/relay.rs` | **`RelayConfig::for_session` 门禁**；握手若有差异则适配 | **中** |
| `xai-webuild-shell/src/agent/app.rs` / leader | relay 启动条件、headless demand 与 WeBuild auth 一致 | **中** |
| `xai-webuild-shell/src/auth/*` | API Key → JWT exchange；AuthManager 与 Relay token | **中–大** |
| `xai-webuild-shell` cloud 扩展 | `require_xai_auth` → scopes；SandboxClient base URL | **中** |
| `xai-webuild-shell/src/leader/server.rs` | `PROD_COMPUTER_HUB_URL` 可配置/改默认 | 小 |
| `xai-webuild-workspace` hub 接入 | 自建 Hub URL + 新 auth provider | 小–中 |
| `xai-webuild-config` | `relay_url` / `hub_url` / `gateway_url` / `auth_url` | 小 |
| `xai-webuild-models` | DashScope 默认确认 | 小 |
| `xai-webuild-pager` | 可选：展示 Web 会话链接 | 小（后置） |

> v0.1 将鉴权一律标「小」不准确。端点替换小；**门禁与 token 路径是 M2a 关键路径。**

### B. 新建服务代码结构

```
webuild/
├── crates/                          # Rust 代码 (已有)
├── services/                        # Python/TS 服务 (新增)
│   ├── auth/                        # Auth Service
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── models.py           # SQLAlchemy models
│   │   │   ├── routes/
│   │   │   │   ├── auth.py
│   │   │   │   ├── users.py
│   │   │   │   └── api_keys.py
│   │   │   ├── middleware/
│   │   │   │   └── rbac.py
│   │   │   └── utils/
│   │   │       └── jwt.py
│   │   └── tests/
│   ├── relay/                       # Relay Server
│   │   ├── Dockerfile
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── relay.py            # WebSocket relay 核心
│   │   │   ├── session_manager.py  # 会话生命周期
│   │   │   ├── persistence.py      # 会话持久化
│   │   │   └── acp/
│   │   │       ├── protocol.py     # ACP 消息类型
│   │   │       └── router.py       # 消息路由
│   │   └── tests/
│   ├── hub/                         # Hub Broker（推荐 Rust 独立 crate 或 services/hub-rs）
│   │   ├── Dockerfile
│   │   ├── Cargo.toml               # 优先：复用 xai-tool-protocol
│   │   ├── src/
│   │   │   ├── main.rs
│   │   │   ├── broker.rs            # 路由表 + 转发
│   │   │   ├── connection.rs
│   │   │   └── session.rs
│   │   └── tests/                   # 与 SDK 的 wire 互通测试
│   │   # 备选：Python 子集实现（仅 SPIKE-3 证明可行时）
│   ├── gateway/                     # Gateway
│   │   ├── Dockerfile
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── sandbox_manager.py  # 沙箱生命周期
│   │   │   ├── k8s_client.py       # K8s API 封装
│   │   │   ├── acp_proxy.py        # ACP 代理
│   │   │   └── models.py
│   │   └── tests/
│   └── web-ide/                     # Web IDE (Next.js)
│       ├── Dockerfile
│       ├── package.json
│       ├── next.config.js
│       ├── src/
│       │   ├── app/                 # App Router 页面
│       │   ├── components/          # React 组件
│       │   ├── lib/
│       │   │   ├── acp-client.ts    # ACP Client SDK
│       │   │   ├── auth.ts
│       │   │   └── websocket.ts
│       │   └── stores/              # Zustand stores
│       └── public/
├── sandbox/                         # 沙箱容器 (新增)
│   ├── Dockerfile
│   └── scripts/
│       └── sandbox-init.sh
├── helm/                            # Helm Charts (新增)
│   └── webuild/
│       ├── Chart.yaml
│       ├── values.yaml
│       ├── values-staging.yaml
│       ├── values-production.yaml
│       └── templates/
└── docs/
    └── design/
        └── web-ide-cloud-sandbox-plan.md  # 本文档
```

### C. 数据库 Schema (核心表)

```sql
-- 用户
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username    VARCHAR(64) UNIQUE NOT NULL,
    email       VARCHAR(256) UNIQUE NOT NULL,
    role        VARCHAR(32) NOT NULL DEFAULT 'developer',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- API Keys
CREATE TABLE api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    key_hash    VARCHAR(64) NOT NULL,    -- bcrypt/sha256 hash
    key_prefix  VARCHAR(8) NOT NULL,     -- 前缀用于显示 "sk-xxxx..."
    name        VARCHAR(128),
    scopes      JSONB NOT NULL DEFAULT '[]',
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 会话元数据
CREATE TABLE sessions (
    id          VARCHAR(64) PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id),
    title       VARCHAR(256),
    model       VARCHAR(64),
    status      VARCHAR(32) NOT NULL DEFAULT 'active',  -- active, archived, deleted
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 沙箱
CREATE TABLE sandboxes (
    id              VARCHAR(64) PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id),
    environment_id  VARCHAR(64),
    status          VARCHAR(32) NOT NULL DEFAULT 'creating',
    pod_name        VARCHAR(128),
    namespace       VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ,
    terminated_at   TIMESTAMPTZ
);

-- 审计日志
CREATE TABLE audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id     UUID,
    action      VARCHAR(64) NOT NULL,
    resource    VARCHAR(256),
    details     JSONB,
    source_ip   INET,
    result      VARCHAR(32) NOT NULL   -- success, failure, denied
);

-- 索引
CREATE INDEX idx_sessions_user ON sessions(user_id, status);
CREATE INDEX idx_sandboxes_user ON sandboxes(user_id, status);
CREATE INDEX idx_audit_user ON audit_logs(user_id, timestamp);
CREATE INDEX idx_audit_action ON audit_logs(action, timestamp);
```

### D. 性能指标目标

| 指标 | 目标值 | 备注 |
|------|--------|------|
| Web IDE 首屏加载 | < 2 秒 | Next.js SSR |
| WebSocket 连接建立 | < 500ms | 含 TLS 握手 |
| ACP 消息端到端延迟 | < 100ms (同区域) | Relay → Leader → 回 |
| 沙箱创建时间 (Pod Ready) | < 45 秒 | 含镜像拉取（首次更慢） |
| 沙箱创建时间 (预热 Pod) | < 10 秒 | Pod Pool 待命（后置） |
| Hub Broker 工具调用延迟 | < 50ms (附加延迟) | Broker 转发开销 |
| 并发 WebSocket 连接数 | ≥ 50 per instance | 初期 1 replica |
| 并发沙箱数 | **≥ 20**（初期）/ ≥ 70（满配） | 受沙箱节点池规模限制 |

#### 资源预算对照

| 部署阶段 | 节点数 | 核心服务 CPU Req | 核心服务 Mem Req | 最大并发沙箱 |
|----------|--------|-----------------|-----------------|-------------|
| M1–M2a (Auth+Relay+Web) | 5 (扩容后) | ~500m | ~640Mi | — |
| M2b (独立沙箱上线) | 5 + 沙箱池 | ~600m | ~768Mi | ~20 (3 个沙箱节点) |
| M2c–M3 (Hub + 生产) | 5 + 沙箱池 | ~800m–2C | 1–4Gi | ~20–70 |

### E. 术语表

| 术语 | 含义 |
|------|------|
| **ACP** | Agent Client Protocol — Agent 与 Client 之间的 JSON-RPC 通信协议 |
| **Leader** | 本地运行的 webuild 后台守护进程 |
| **Relay** | WebSocket 中继，桥接 Web 前端与本地 Leader |
| **Hub** | 工具路由 Broker，连接 ToolServer 和 ToolHarness |
| **ToolServer** | Hub 的工具提供方（本地 Leader 注册工具） |
| **ToolHarness** | Hub 的工具消费方（沙箱 Agent 调用工具） |
| **Gateway** | 沙箱生命周期管理服务 |
| **HITL** | Human-in-the-loop — 需要人工确认的操作 |
| **Session Binding** | 将工具绑定到特定会话的路由规则 |
| **场景 A** | Web IDE → Relay → 本地 Leader（无沙箱/Hub） |
| **场景 B-1** | 独立云沙箱（Git clone，工具仅沙箱内） |
| **场景 B-2** | 沙箱经 Hub 操作本地 Workspace |
| **M2a / M2b / M2c** | Phase II 里程碑：Web 试用 / 独立沙箱 / Hub 回本地 |

---

## 12. 可行性结论与交付策略

> 评估日期: 2026-07-26 · 对照仓库 v0.4.x 与本文 v0.1 草案。

### 12.1 结论摘要

| 维度 | 评级 |
|------|------|
| 战略方向（复用 ACP/Relay/Hub/headless） | 正确 |
| **场景 A**（Web → Relay → 本地） | ⭐⭐⭐⭐☆ 高可行 |
| **场景 B-1**（独立沙箱） | ⭐⭐⭐⭐☆ 高可行（在 Gateway 对齐 client 后） |
| **场景 B-2**（Hub 回本地） | ⭐⭐⭐☆☆ 中等可行（协议子集 + 优先 Rust） |
| 原 14 周「全量含生产」一次做完 | ⭐⭐☆☆☆ 不推荐 |

### 12.2 最大机会与最大阻塞

**机会**：不必重写 Agent/工具系统；Release 二进制可直接进沙箱镜像；协议与 SDK 资产齐全。

**阻塞**：

1. 鉴权与 API-key-first 产品现实冲突  
2. Relay 仅有 client、无 server 规范  
3. Hub 线协议远厚于「薄 Broker」叙事  

### 12.3 推荐推进顺序

```
基础设施 → Auth → [SPIKE-1,2] → Rust 鉴权 → Relay+WebIDE(M2a)
                                              ↓
                                    Gateway+独立沙箱(M2b)
                                              ↓
                                    [SPIKE-3] → Hub 子集(M2c) → 生产化(M3)
```

### 12.4 相关文档

| 文档 | 说明 |
|------|------|
| [`phase-ii-backlog.md`](./phase-ii-backlog.md) | Epic/Story/Spike、AC、依赖、首 Sprint |
| 本文 v0.2 | 架构、安全、部署、修订后路线图 |
