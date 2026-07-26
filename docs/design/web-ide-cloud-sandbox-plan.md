***************************************************************
**  使用的 Agent Session: 
**   qwen --resume 2a570304-6007-4b74-8c02-2c0d89424c20
***************************************************************

# WeBuild Web IDE & 云端沙箱 — 实施方案

> 版本: v0.3.0-draft · 日期: 2026-07-26 · 作者: Jerry Zhang
>
> 状态: **评审修订** — v0.1 评审后调整：基础设施从生产 ACK 集群迁移至独立 ECS + Docker Compose，沙箱使用阿里云 ACS Serverless (ECI)。

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

**复用价值**: 替换 WebSocket 端点即可将本地 Agent 接入自建 Web 前端。

#### Computer Hub SDK（`xai-computer-hub-*`）

- 完整的工具路由网格：ToolServer（Provider）/ ToolHarness（Consumer）/ Hub（Broker）
- JSON-RPC 2.0 over WebSocket，hello 握手、session.bind、tool_call_request
- 连接池、自动重连、并发限流（per-session / per-connection / global）
- MCP Adapter：将 MCP Server 工具桥接到 Hub
- Local-shadows-remote 解析策略

**复用价值**: Hub Broker 是唯一需要新建的服务端组件，SDK 侧（ToolServer / ToolHarness）已在 Rust 中实现。

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

| 组件 | 说明 | 技术栈 | 部署位置 |
|------|------|--------|---------|
| **WeBuild Relay Server** | WebSocket 中继服务，替代 `code.grok.com` | Python (FastAPI) + WebSocket | ECS (Docker Compose) |
| **WeBuild Hub Broker** | 工具路由 Broker，替代 `computer-hub.grok.com` | Python (FastAPI) + WebSocket | ECS (Docker Compose) |
| **WeBuild Web IDE** | 浏览器前端，替代 `grok.com/code` | TypeScript (Next.js) | ECS (Docker Compose) |
| **WeBuild Gateway** | 沙箱生命周期管理，替代 `grok.com/ws/gw/` | Python (FastAPI) + WebSocket | ECS (Docker Compose) |
| **WeBuild Auth Service** | 统一认证服务 | Python (FastAPI) + JWT/OIDC | ECS (Docker Compose) |
| **WeBuild Cloud Sandbox** | 隔离的执行环境，替代 xAI 云端沙箱 | Docker + ACS Serverless (ECI) | 阿里云 ACS 集群 (Phase 4) |
| **Nginx 反向代理** | 单域名路径路由 + TLS 终结 | Nginx + Let's Encrypt | ECS (Docker Compose) |
| **PostgreSQL** | 用户、会话、审计数据存储 | PostgreSQL (Docker 容器) | ECS (Docker Compose) |

### 2.3 不需要的组件

| 上游组件 | 原因 |
|---------|------|
| `cli-chat-proxy.grok.com` | 上游 xAI 内部服务，WeBuild 使用 DashScope 直连模型 |
| `assets.grok.com` | 静态资源服务器，WeBuild 自行托管 |
| xAI OIDC 认证 | WeBuild 使用自建认证体系 |

---

## 3. 目标架构

### 3.1 总体架构

> **基础设施策略**: 核心服务部署在**独立 ECS 实例**上（Docker Compose 编排），与生产 ACK 集群物理隔离，避免干扰线上业务。沙箱执行环境在 Phase 4 使用**阿里云 ACS Serverless 集群** (ECI 弹性实例)，与核心服务通过 K8s API 远程通信。

```
                     ┌──────────────────────────────────────────────────────┐
                     │  独立 ECS 实例 (ecs.c7.xlarge / 4C8G)                │
                     │  webuild.agentics-economics.org                              │
                     │                                                      │
┌──────────┐         │  ┌────────────────────────────────────────────┐     │
│          │ HTTPS   │  │  Nginx (反向代理 + TLS)                     │     │
│  浏览器   │────────→│  │  /            → Web IDE (:3000)            │     │
│          │←────────│  │  /api/auth/*  → Auth Service (:8001)       │     │
└──────────┘         │  │  /api/gateway/*→ Gateway (:8004)           │     │
                     │  │  /ws/relay    → Relay Server (:8002) [WS]  │     │
┌──────────┐  WSS    │  │  /ws/hub      → Hub Broker (:8003) [WS]    │     │
│  本地    │────────→│  └────────────────────────────────────────────┘     │
│  webuild │←────────│                                                      │
│  TUI/CLI │         │  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ │
└──────────┘         │  │ Auth Service│ │Relay Server  │ │ Hub Broker   │ │
     │               │  │ :8001       │ │:8002         │ │ :8003        │ │
     │ ACP           │  └─────────────┘ └──────────────┘ └──────────────┘ │
     ▼               │  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ │
┌──────────────┐     │  │ Gateway     │ │ Web IDE      │ │ PostgreSQL   │ │
│ MvpAgent     │     │  │ :8004       │ │ :3000        │ │ :5432        │ │
│ (Leader 进程) │     │  └──────┬──────┘ └──────────────┘ └──────────────┘ │
│ ├─ Session   │ WSS │         │                                            │
│ │  Actor     │─────│─────────│──── 连接沙箱 ──────────────┐              │
│ ├─ Sampler   │     │         │                            │              │
│ └─ ToolBridge│     │  Docker Compose 统一编排              │              │
└──────────────┘     └─────────────────────────────────────│──────────────┘
                                                           │ K8s API (远程)
                                                           ▼
                     ┌──────────────────────────────────────────────────────┐
                     │  阿里云 ACS Serverless (沙箱专用, Phase 4)            │
                     │  Cluster: webuild-sandbox-aliyun_2608                │
                     │  c3f5b659659ed469d9517019a4bab4785                   │
                     │                                                      │
                     │  ┌────────────────────────────────────────────────┐  │
                     │  │  Sandbox Pod 1 (ECI 弹性实例)                   │  │
                     │  │  ├─ webuild agent (headless)                   │  │
                     │  │  ├─ 隔离文件系统 (/workspace)                   │  │
                     │  │  └─ 资源限制 (1C/2Gi req, 2C/4Gi lim)          │  │
                     │  └────────────────────────────────────────────────┘  │
                     │  ┌────────────────────────────────────────────────┐  │
                     │  │  Sandbox Pod N  ... (按需创建/销毁, 秒级弹性)   │  │
                     │  └────────────────────────────────────────────────┘  │
                     │                                                      │
                     │  NetworkPolicy: 仅允许出站 DashScope + Hub Broker    │
                     │  Virtual Kubelet: cn-hangzhou-b/j/k (3 AZ)          │
                     │  无固定节点, 零运维, 按 Pod 资源用量计费              │
                     └──────────────────────────────────────────────────────┘
```

### 3.2 数据流概览

#### 场景 A：Web IDE 驱动本地 Agent

> 所有中间件（Relay Server、Auth Service）运行在 ECS 实例上，通过 Nginx 反向代理暴露。

```
浏览器 (Web IDE)
  │ HTTPS/WSS → Nginx (ECS)
  │ ACP over WebSocket
  ▼
Relay Server (ECS, Docker Compose)
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

#### 场景 B：云端沙箱 Agent (Phase 4)

> Gateway 运行在 ECS 上，通过 K8s API 远程管理 ACS Serverless 集群中的沙箱 Pod。

```
浏览器 (Web IDE)
  │ HTTPS/WSS → Nginx (ECS)
  │ ACP over WebSocket
  ▼
Gateway (ECS, Docker Compose)
  │ ACP over WebSocket (代理到沙箱 Pod)
  │ K8s API → ACS Serverless 集群
  ▼
沙箱 Pod 内的 webuild agent (headless)  ← 运行在 ACS (ECI 弹性实例)
  │
  ├─ 需要操作本地代码？
  │    │ JSON-RPC over WebSocket
  │    ▼
  │  Hub Broker (ECS, Docker Compose)
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

> **部署隔离**: 沙箱 Pod 运行在**阿里云 ACS Serverless 集群**中，每个 Pod 是独立的 ECI (Elastic Container Instance)，与生产 ACK 集群和核心服务 ECS 完全隔离。Gateway（ECS 上）通过 K8s API 远程管理沙箱集群。

每个沙箱是一个 Kubernetes Pod (ECI 弹性实例)，内含：

```
┌─────────────────────────────────────────────────┐
│  Sandbox Pod (ACS Serverless / ECI)              │
│                                                 │
│  ┌─────────────────────────────────────────────┐ │
│  │  webuild agent (headless mode)              │ │
│  │  - ACP over WebSocket (入口)                 │ │
│  │  - 模型调用 → DashScope                     │ │
│  │  - 工具执行 → 沙箱本地 FS / Hub             │ │
│  └──────────────┬──────────────────────────────┘ │
│                 │                                │
│  ┌──────────────▼──────────────────────────────┐ │
│  │  沙箱工具层                                  │ │
│  │  - read_file / search_replace               │ │
│  │  - run_terminal_cmd (沙箱内执行)             │ │
│  │  - grep / list_dir                          │ │
│  │  - MCP tools (如果配置)                      │ │
│  └──────────────┬──────────────────────────────┘ │
│                 │                                │
│  ┌──────────────▼──────────────────────────────┐ │
│  │  隔离文件系统 (emptyDir / PVC)               │ │
│  │  /workspace/  ← 用户代码                    │ │
│  │  /tmp/        ← 临时文件                    │ │
│  └─────────────────────────────────────────────┘ │
│                                                 │
│  资源限制:                                       │
│  - CPU: 1 core (request) / 2 (limit)            │
│  - Memory: 2Gi (request) / 4Gi (limit)          │
│  - Ephemeral Storage: 10Gi                      │
│  - Network: 仅允许出站到 DashScope + Hub Broker  │
│  - 调度: Virtual Kubelet (ECI, 3 AZ)            │
│  - TTL: 最长 4 小时                             │
└─────────────────────────────────────────────────┘
```

### 5.2 沙箱生命周期

```
用户点击"创建沙箱"
  │
  ▼
POST /api/gateway/sandboxes
  │ Gateway (ECS) 通过远程 K8s API 操作 ACS Serverless 集群:
  │ → K8s API 创建 Pod + Service + NetworkPolicy (ACS 集群)
  │ → 等待 Pod Ready
  │ → webuild agent 启动 (headless)
  │
  ▼ 返回 { sandboxId, wsUrl, status }
  │
  ▼
Web IDE → Nginx (ECS) → Gateway (ECS) → 代理 WebSocket 到沙箱 Pod
  │ 正常使用 Agent（对话 + 工具调用）
  │
  ▼ 沙箱内 Agent 需要操作本地代码？
  │ → 通过 Hub Broker (ECS) 路由到本地 Leader
  │
  ▼ 用户关闭 / TTL 到期 / 手动终止
  │
  ▼
DELETE /api/gateway/sandboxes/:id
  │ Gateway drain Agent sessions
  │ → 远程 K8s API 删除 Pod (ACS Serverless 集群)
  │ → 清理 NetworkPolicy + Service
  │
  ▼ 可选: 导出 workspace 内容 (git diff / tar)
```

### 5.3 Gateway 服务设计

Gateway 运行在 ECS 上，通过远程 K8s API 管理 ACS Serverless 集群中的沙箱 Pod (ECI 弹性实例)。它是 `grok.com/ws/gw/` 的替代实现：

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

```
# 环境管理
GET    /api/gateway/environments              # 列出环境模板
POST   /api/gateway/environments              # 创建环境模板
PUT    /api/gateway/environments/:id          # 更新环境模板
DELETE /api/gateway/environments/:id          # 删除环境模板

# 沙箱管理
POST   /api/gateway/sandboxes                 # 创建沙箱
GET    /api/gateway/sandboxes                 # 列出沙箱
GET    /api/gateway/sandboxes/:id             # 获取沙箱详情
DELETE /api/gateway/sandboxes/:id             # 终止沙箱
POST   /api/gateway/sandboxes/:id/hibernate   # 暂停沙箱
POST   /api/gateway/sandboxes/:id/restore     # 恢复沙箱

# 沙箱日志
GET    /api/gateway/sandboxes/:id/logs        # 获取 Agent 日志
GET    /api/gateway/sandboxes/:id/status      # 获取运行状态
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

沙箱需要访问用户代码，有三种模式：

| 模式 | 机制 | 适用场景 |
|------|------|---------|
| **Git Clone** | 创建沙箱时 clone 仓库到 `/workspace` | 独立项目、不需要回写本地 |
| **Hub 代理** | 沙箱 Agent 通过 Hub 路由文件操作到本地 Leader | 需要操作本地代码库 |
| **文件上传** | Web IDE 上传文件到沙箱 (`workspace.put_files`) | 临时文件、补丁 |

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

#### 实现策略

**Phase 1**: Python (FastAPI) 单进程实现，满足初始需求。

**Phase 2**: 如果性能成为瓶颈，考虑：
- 用 Rust 重写（复用 `xai-computer-hub-core` 的 trait 定义）
- 或水平扩展（多 Broker 实例 + sticky session by `session_id`）

---

## 6. 认证与权限体系

### 6.1 认证方案

```
┌──────────────────────────────────────────────────────┐
│  WeBuild Auth Service                                │
│                                                      │
│  认证方式:                                            │
│  ├─ API Key (个人使用)                                │
│  │   └─ DASHSCOPE_API_KEY / WEBUILD_API_KEY          │
│  ├─ JWT Token (Web IDE / 服务间通信)                   │
│  │   └─ Auth Service 签发，RS256                      │
│  └─ OIDC (企业 SSO, 未来扩展)                         │
│      └─ 对接公司 SSO (LDAP/AD)                        │
│                                                      │
│  Token 结构:                                         │
│  {                                                   │
│    "sub": "user_id",                                 │
│    "iss": "webuild.agentics-economics.org",                  │
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

本地 Leader 进程需要新增认证适配：

```rust
// 修改 xai-webuild-auth，增加 WeBuild Auth Service 适配
// 新增 xai-webuild-env 端点 (单域名 + 路径路由):

pub fn auth_service_url(&self) -> String {
    env_var("WEBUILD_AUTH_SERVICE_URL")
        .unwrap_or("https://webuild.agentics-economics.org/api/auth".to_string())
}

pub fn relay_ws_url(&self) -> String {
    env_var("WEBUILD_RELAY_WS_URL")
        .unwrap_or("wss://webuild.agentics-economics.org/ws/relay".to_string())
}

pub fn hub_ws_url(&self) -> String {
    env_var("WEBUILD_HUB_WS_URL")
        .unwrap_or("wss://webuild.agentics-economics.org/ws/hub".to_string())
}

pub fn gateway_ws_url(&self) -> String {
    env_var("WEBUILD_GATEWAY_WS_URL")
        .unwrap_or("wss://webuild.agentics-economics.org/ws/gateway".to_string())
}
```

---

## 7. 安全模型

### 7.1 纵深防御

```
┌─ 第 1 层: 网络 ──────────────────────────────────────────────┐
│  - 所有外部通信强制 WSS/HTTPS (Nginx TLS 终结)               │
│  - ECS 安全组: 仅开放 80/443 端口                             │
│  - 核心服务仅监听 127.0.0.1 (Docker 内部网络)                 │
│  - 沙箱 ACS 集群: K8s NetworkPolicy 限制出站                  │
├─ 第 2 层: 认证 ──────────────────────────────────────────────┤
│  - JWT Token + API Key 双因子                                 │
│  - Token 短有效期 (1h)，Refresh Token 轮换                     │
│  - Docker 服务间: 内部网络 + 共享 JWT secret                  │
├─ 第 3 层: 授权 ──────────────────────────────────────────────┤
│  - RBAC: 角色决定可执行的 API 操作                             │
│  - Session 隔离: 用户只能访问自己的会话                         │
│  - Hub 路由: (session_id, tool_id) 绑定，跨 session 不可调用   │
├─ 第 4 层: 沙箱隔离 ──────────────────────────────────────────┤
│  - ACS Serverless: 独立集群 + ECI 实例级隔离                   │
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

### 7.2 沙箱安全策略 (ACS Serverless / ECI)

```yaml
# K8s SecurityContext for sandbox pods (ACS Serverless, ECI 弹性实例)
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  readOnlyRootFilesystem: false    # Agent 需要写文件
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]

# NetworkPolicy: 仅允许必要的出站 (在 ACS 集群中应用)
egress:
  - to:
      # DashScope API
      - ipBlock: { cidr: <dashscope-ip-range> }
    ports:
      - { protocol: TCP, port: 443 }
  - to:
      # Hub Broker (ECS 实例, 通过公网/内网 IP)
      - ipBlock: { cidr: <ecs-internal-ip>/32 }
    ports:
      - { protocol: TCP, port: 443 }
  - to:
      # DNS 解析
      - namespaceSelector: {}
    ports:
      - { protocol: UDP, port: 53 }
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

### 8.0 基础设施策略

> **核心原则**: WeBuild 核心服务与生产 ACK 集群**物理隔离**，避免干扰线上业务。

| 环境 | 部署方式 | 理由 |
|------|---------|------|
| **核心服务** (Auth/Relay/Hub/Gateway/Web IDE/DB) | 独立 ECS + Docker Compose | 5 个容器 + DB，K8s 过度工程；与生产集群零干扰 |
| **沙箱执行** (Phase 4) | 阿里云 ACS Serverless (ECI) | Pod 级 ECI 隔离、NetworkPolicy、秒级弹性、零运维 |
| **生产 ACK 集群** | **不触碰** | 承载 jarvildatavault、xingu 等核心业务，CPU requests 已 89% |

### 8.1 核心服务 — ECS + Docker Compose

#### ECS 实例规格

| 配置项 | 选择 | 月成本估算 |
|--------|------|-----------|
| 实例规格 | ecs.c7.xlarge (4 vCPU / 8 GiB) | ~¥300-500 |
| 系统盘 | ESSD 40GB | 含在实例价内 |
| 数据盘 | ESSD 50GB (挂载 /data，存放 PostgreSQL 数据) | ~¥25/月 |
| 带宽 | 按流量计 (峰值 10Mbps) | ~¥50-100/月 |
| **合计** | | **~¥400-600/月** |

#### Docker Compose 编排

```yaml
# docker-compose.yml (部署在 ECS 实例上)

version: "3.9"

services:
  # ── 反向代理 + TLS ──
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./certbot/conf:/etc/letsencrypt:ro
      - ./certbot/www:/var/www/certbot:ro
    depends_on:
      - auth-service
      - relay-server
      - hub-broker
      - gateway
      - web-ide
    restart: unless-stopped

  # ── Auth Service — JWT 签发/验证, API Key 管理 ──
  auth-service:
    image: registry.cn-hangzhou.aliyuncs.com/webuild/auth-service:latest
    environment:
      - DATABASE_URL=postgresql://webuild:${DB_PASSWORD}@postgres:5432/webuild
      - JWT_SECRET=${JWT_SECRET}
    expose:
      - "8001"
    depends_on:
      - postgres
    restart: unless-stopped

  # ── Relay Server — WebSocket ACP 中继 ──
  relay-server:
    image: registry.cn-hangzhou.aliyuncs.com/webuild/relay-server:latest
    environment:
      - AUTH_SERVICE_URL=http://auth-service:8001
      - DATABASE_URL=postgresql://webuild:${DB_PASSWORD}@postgres:5432/webuild
    expose:
      - "8002"
    depends_on:
      - auth-service
      - postgres
    restart: unless-stopped

  # ── Hub Broker — 工具路由 ──
  hub-broker:
    image: registry.cn-hangzhou.aliyuncs.com/webuild/hub-broker:latest
    environment:
      - AUTH_SERVICE_URL=http://auth-service:8001
    expose:
      - "8003"
    depends_on:
      - auth-service
    restart: unless-stopped

  # ── Gateway — 沙箱生命周期管理 (Phase 4) ──
  gateway:
    image: registry.cn-hangzhou.aliyuncs.com/webuild/gateway:latest
    environment:
      - AUTH_SERVICE_URL=http://auth-service:8001
      - DATABASE_URL=postgresql://webuild:${DB_PASSWORD}@postgres:5432/webuild
      - KUBECONFIG=/run/secrets/sandbox-kubeconfig    # ACS Serverless 集群凭证
      - SANDBOX_CLUSTER_API=${SANDBOX_CLUSTER_API}
    expose:
      - "8004"
    secrets:
      - sandbox-kubeconfig
    depends_on:
      - auth-service
      - postgres
    restart: unless-stopped
    profiles: ["sandbox"]                             # Phase 4 才启用

  # ── Web IDE — Next.js 前端 ──
  web-ide:
    image: registry.cn-hangzhou.aliyuncs.com/webuild/web-ide:latest
    environment:
      - NEXT_PUBLIC_API_BASE_URL=https://webuild.agentics-economics.org
    expose:
      - "3000"
    restart: unless-stopped

  # ── PostgreSQL — 持久化存储 ──
  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=webuild
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=webuild
    volumes:
      - pgdata:/var/lib/postgresql/data
    expose:
      - "5432"
    restart: unless-stopped

  # ── TLS 证书自动续签 ──
  certbot:
    image: certbot/certbot
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"

volumes:
  pgdata:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /data/postgres

secrets:
  sandbox-kubeconfig:
    file: ./secrets/sandbox-kubeconfig.yaml           # Phase 4: ACS Serverless 集群凭证
```

#### Nginx 反向代理配置

```nginx
# nginx/conf.d/webuild.conf

upstream auth_service  { server auth-service:8001; }
upstream relay_server  { server relay-server:8002; }
upstream hub_broker    { server hub-broker:8003; }
upstream gateway       { server gateway:8004; }
upstream web_ide       { server web-ide:3000; }

server {
    listen 443 ssl http2;
    server_name webuild.agentics-economics.org;

    ssl_certificate     /etc/letsencrypt/live/webuild.agentics-economics.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/webuild.agentics-economics.org/privkey.pem;

    # Web IDE (Next.js)
    location / {
        proxy_pass http://web_ide;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Auth Service REST API
    location /api/auth/ {
        proxy_pass http://auth_service/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Relay Server REST API
    location /api/relay/ {
        proxy_pass http://relay_server/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Gateway REST API
    location /api/gateway/ {
        proxy_pass http://gateway/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Relay Server WebSocket
    location /ws/relay {
        proxy_pass http://relay_server;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;     # WebSocket 长连接 24h
        proxy_send_timeout 86400s;
    }

    # Hub Broker WebSocket
    location /ws/hub {
        proxy_pass http://hub_broker;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # Gateway WebSocket (沙箱代理)
    location /ws/gateway {
        proxy_pass http://gateway;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name webuild.agentics-economics.org;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}
```

### 8.1b 沙箱 — 阿里云 ACS Serverless (Phase 4)

> 沙箱集群已创建: **webuild-sandbox-aliyun_2608** (ACS Serverless)。核心服务（ECS 上的 Gateway）通过 K8s API 远程管理。无需节点池，Pod 按需调度为 ECI 弹性实例。

```yaml
# 沙箱 ACS Serverless 集群 (已创建)
cluster:
  name: webuild-sandbox-aliyun_2608
  cluster_id: c3f5b659659ed469d9517019a4bab4785
  type: ACS Serverless (ManagedKubernetes, profile: Acs)
  spec: ack.pro.small
  region: cn-hangzhou
  version: "1.36.1-aliyun.1"
  vpc: vpc-bp1qtsayedt7wp5vy8v9p (172.16.0.0/12)
  api_server_public: https://120.55.190.66:6443
  api_server_private: https://172.23.56.86:6443
  nat_gateway: ngw-bp1us9y0enfouxc4basda (SNAT 已启用)
  deletion_protection: true

# Virtual Kubelet 可用区 (Serverless Pod 调度)
virtual_kubelet:
  - cn-hangzhou-b
  - cn-hangzhou-j
  - cn-hangzhou-k

# 沙箱 Pod 资源配置 (每个 Pod = 独立 ECI 实例)
sandbox-pod:
  resources:
    requests: { cpu: "1", memory: "2Gi" }
    limits:   { cpu: "2", memory: "4Gi" }
    ephemeral-storage: "10Gi"
  ttl: 4h
  namespace: webuild-sandbox

# ACS Serverless 优势 (相比传统 ACK + 节点池):
#   - 零节点运维: 无需管理节点池、Cluster Autoscaler
#   - 秒级弹性: Pod 直接调度为 ECI，无需等待节点就绪
#   - 实例级隔离: 每个 Pod 运行在独立 ECI 沙箱中
#   - 零闲置成本: 无沙箱时零费用 (无节点开销)
#   - 多 AZ 高可用: 自动跨 3 个可用区调度
#
# 计费模式:
#   - 按 Pod 实际资源用量 (vCPU·秒 + 内存·秒) 计费
#   - 估算: 1C/2Gi Pod 约 ¥0.12/小时 (按量)
#   - 20 并发沙箱 × 4h/天 × 30 天 ≈ ¥288/月
#   - 70 并发沙箱 (满配) ≈ ¥1008/月
```

### 8.2 基础设施依赖

| 组件 | 选择 | 用途 | 部署位置 |
|------|------|------|---------|
| **数据库** | PostgreSQL 16 (Docker 容器) | 用户、会话元数据、审计日志 | ECS 实例内 (数据盘 /data) |
| **TLS** | Let's Encrypt + certbot | 自动证书管理 | ECS 实例内 (Docker 容器) |
| **容器镜像** | 阿里云 ACR | 服务镜像 + 沙箱镜像 | 已有 ACR 实例 |
| **域名** | `webuild.agentics-economics.org` | 单域名 + 路径路由 | DNS A 记录指向 ECS |
| **日志** | 阿里云 SLS (可选) | 集中日志 | 集群外 |

> **初期不引入的组件** (延后到用户量增长时):
> - Redis — JWT 黑名单和限流用内存 LRU 代替，Phase 5 按需引入
> - 阿里云 OSS — 会话历史先存 PostgreSQL JSONB，Phase 4+ 按需引入
> - 阿里云 RDS — 初期 Docker PostgreSQL 足够，用户量增长后迁移
> - Grafana — Phase 5 接入 Prometheus + Grafana

### 8.3 域名规划

> **单域名策略**: 所有服务通过一个域名暴露，Nginx 按路径分发。前端只连一个域名，消除 CORS 问题，简化证书管理。

```
webuild.agentics-economics.org
├── /                       → Web IDE (Next.js, :3000)
├── /api/auth/*             → Auth Service (:8001)
├── /api/gateway/*          → Gateway (:8004)
├── /api/relay/*            → Relay Server REST (:8002)
├── /ws/relay               → Relay Server WebSocket (:8002)
├── /ws/hub                 → Hub Broker WebSocket (:8003)
└── /ws/gateway             → Gateway WebSocket 代理 (:8004)
```

DNS 配置:
```
webuild.agentics-economics.org    A    <ECS 公网 IP>
```

### 8.4 CI/CD 流水线扩展现有 `.gitlab-ci.yml`

```yaml
# 在现有 build + publish 基础上新增:

stages:
  - build          # Rust 二进制 (已有)
  - build-images   # Docker 镜像构建 (新增)
  - publish        # GitLab Release (已有)
  - deploy         # ECS 部署 (新增)

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

deploy-ecs:
  stage: deploy
  environment: production
  when: manual      # 手动触发部署
  script:
    # SSH 到 ECS 实例，拉取新镜像并重启
    - ssh -o StrictHostKeyChecking=no $ECS_USER@$ECS_IP "
        cd /opt/webuild &&
        docker compose pull &&
        docker compose up -d --remove-orphans &&
        docker image prune -f
      "
  only:
    - main
```

### 8.5 迁移路径（未来扩展）

当用户量增长到需要 K8s 编排时，核心服务可平滑迁移：

1. 新建 ACK/ACS 集群（或复用沙箱 ACS 集群添加核心服务 namespace）
2. 将 `docker-compose.yml` 转换为 Helm Chart（服务定义不变，只换编排层）
3. Nginx 配置转换为 K8s Ingress
4. PostgreSQL 迁移到阿里云 RDS
5. **服务代码零改动**，只换部署方式

---

## 9. 实施路线

### Phase 0: 基础设施准备 (1.5 周)

| 任务 | 产出 |
|------|------|
| **购买 ECS 实例** (ecs.c7.xlarge 4C8G) | 独立实例，与生产 ACK 集群物理隔离 |
| ECS 环境搭建 | Docker + Docker Compose + Nginx |
| 数据盘挂载 | `/data` (ESSD 50GB) 用于 PostgreSQL 数据持久化 |
| ACR 镜像仓库创建 | `registry.cn-hangzhou.aliyuncs.com/webuild/*` |
| 域名 + DNS | `webuild.agentics-economics.org` A 记录指向 ECS 公网 IP |
| TLS 证书 | Let's Encrypt + certbot 自动续签 |
| `docker-compose.yml` + Nginx 配置 | 项目仓库 `deploy/` 目录 |

### Phase 1: Auth Service + `xai-webuild-env` 多环境改造 (2.5 周)

| 任务 | 产出 |
|------|------|
| JWT 签发/验证 | `/api/auth/login`, `/api/auth/token/refresh` |
| API Key 管理 | `/api/auth/api-keys` CRUD |
| RBAC 中间件 | FastAPI dependency injection |
| 数据库 migration | Alembic: users, api_keys, roles 表 |
| **`xai-webuild-env` 多环境改造** | 恢复 Staging 变体，支持 `WEBUILD_*` 环境变量覆盖 |
| 单元测试 + 集成测试 | pytest 覆盖 |
| **ECS 部署验证** | Auth Service 上线 ECS，域名可达 |

### Phase 2: Relay Server + Web IDE MVP (5 周)

| 任务 | 产出 | 周 |
|------|------|----|
| **协议逆向 Spike** | 从 `relay.rs` 提取 WebSocket 握手协议 spec | 0.5 |
| Relay WebSocket 服务 | ACP 消息路由、会话管理 | 1-2 |
| 会话持久化 | JSONL → PostgreSQL 归档 | 2 |
| Web IDE 核心页面 | 会话列表 + 对话流 + 权限弹窗 | 2-3 |
| ACP Client SDK (TS) | WebSocket 封装 + 类型定义 | 1 |
| 终端面板 | xterm.js 集成 | 3-4 |
| 代码查看器 | Monaco Editor 集成 | 4 |
| 联调测试 | 本地 Leader → Relay → Web IDE 端到端 | 5 |

### Phase 3: Hub Broker (3.5 周)

| 任务 | 产出 | 周 |
|------|------|----|
| **协议兼容 Spike** | 最小 Python Broker 与 Rust ToolServer 握手验证 | 0.5 |
| Broker 核心 | 路由表、连接管理、JSON-RPC 转发 | 1-2 |
| 协议兼容测试 | 与 Rust Hub SDK 的 hello/serve/call 完整互通 | 2 |
| 并发控制 + 限流 | per-session / per-connection 限流 | 2-3 |
| 健康检查 + 重连 | WebSocket keepalive、graceful shutdown | 3 |
| 本地 Leader 适配 | 修改 `xai-webuild-env` 端点 + `xai-webuild-auth` 适配 | 3-3.5 |

### Phase 4: Gateway + Cloud Sandbox (4 周)

| 任务 | 产出 | 周 |
|------|------|----|
| **配置 ACS Serverless 集群** | 创建 namespace + RBAC + NetworkPolicy (集群已创建) | 0.5 |
| 沙箱容器镜像 | Dockerfile.sandbox + 基础工具 | 1 |
| Gateway 服务 | 沙箱 CRUD + 远程 K8s API 集成 | 1-2 |
| NetworkPolicy | 出站限制 (DashScope + ECS Hub Broker) | 2 |
| 沙箱 ACP 代理 | Gateway 代理 WebSocket → Pod | 2-3 |
| 生命周期管理 | TTL 自动清理 | 3 |
| Web IDE 沙箱页面 | 创建/管理/连接沙箱 UI | 3-4 |
| 联调测试 | 完整流程: Web IDE → Gateway → Sandbox → Hub → 本地 | 4 |

### Phase 5: 生产化 (3 周)

| 任务 | 产出 | 周 |
|------|------|----|
| 监控 + 告警 | Docker metrics + Prometheus + Grafana | 1 |
| 审计日志 | 全链路操作审计 | 1 |
| 负载测试 | WebSocket 并发连接测试 | 2 |
| 安全审计 | 渗透测试 + 权限绕过检查 | 2 |
| 文档 | 部署文档 + 运维手册 + 用户指南 | 3 |
| CI/CD 完善 | 自动化部署流水线 (SSH → docker compose) | 3 |

### 里程碑总览

```
Week  1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16
      ├───┤                                                         Phase 0: ECS 基础设施
          ├─────┤                                                   Phase 1: Auth + env 改造
                ├─────────────┤                                     Phase 2: Relay + Web IDE
                      ├──────────┤                                  Phase 3: Hub Broker
                            ├─────────────┤                         Phase 4: Gateway + Sandbox
                                          ├──────────┤              Phase 5: 生产化
      ──────────────────────────────────────────────────────────
      ▲       ▲              ▲                    ▲
      M0      M1             M2                   M3
   基础就绪  Web IDE 可用  端到端打通          生产发布
```

**总计: ~16 周**（约 4 个月），可交付最小可用版本。

---

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| **Relay 握手协议逆向不准确** | 🟡 中 | 高 | Phase 2 前置 0.5 周 Spike，从 `relay.rs` 提取完整协议 spec；写 Python mock 验证 Rust 客户端连通性 |
| **Hub Broker Python↔Rust JSON-RPC 不兼容** | 🟡 中 | 高 | Phase 3 前置 3 天 Spike，最小 Broker 与 Rust ToolServer 握手验证 |
| **`xai-webuild-env` 多环境改造引入回归** | 🟡 中 | 中 | Phase 1 专门处理，增加环境变量覆盖的单元测试；Production 变体行为不变 |
| ACS ECI 实例启动延迟或配额不足 | 低 | 中 | ACS 跨 3 AZ 调度提高可用率；提前申请 ECI 配额提升；Gateway 异步创建 + 前端显示进度 |
| ECS 单实例故障，全部服务不可用 | 低 | 高 | ECS 自动快照 + 数据盘定期备份；`docker compose` 的 `restart: unless-stopped` 自愈；未来可迁移到 ACK |
| WebSocket 长连接在高并发下不稳定 | 中 | 高 | Nginx 已验证 WebSocket 代理能力；`proxy_read_timeout 86400s`；客户端自动重连 |
| 沙箱 Pod 启动延迟影响用户体验 | 中 | 中 | 预热 Pod Pool（维护 N 个待命 Pod）；沙箱创建异步化，前端显示进度 |
| Hub Broker 成为单点瓶颈 | 低 | 高 | 初期单实例够用；未来水平扩展或 Rust 重写 |
| Rust 客户端代码修改量大 | 低 | 中 | 仅修改 `xai-webuild-env` 端点 + `xai-webuild-auth` 适配，其余 SDK 不变 |
| DashScope API 不稳定 | 低 | 中 | 重试策略已有（sampler retry.rs 15 次退避）；可配置 fallback 模型 |
| K8s NetworkPolicy 配置错误导致沙箱无法访问模型 API | 中 | 中 | Phase 4 在 ACS 集群充分测试；NetworkPolicy 模板化 + Git 版本控制 |
| PostgreSQL 容器数据丢失 | 低 | 高 | 数据盘 `/data` 独立于系统盘；定期 `pg_dump` 备份到 OSS；系统盘快照 |

---

## 11. 附录

### A. 现有代码修改清单

| 文件/Crate | 修改内容 | 工作量 |
|-----------|---------|--------|
| `xai-webuild-env` | 恢复 Staging 变体，端点改为 `webuild.agentics-economics.org` 路径路由，支持 `WEBUILD_*` 环境变量覆盖 | 中 |
| `xai-webuild-auth` | 新增 WeBuild Auth Service 适配器（JWT 验证） | 中 |
| `xai-webuild-shell/src/agent/relay.rs` | 适配自建 Relay Server 的握手协议 | 小 |
| `xai-webuild-shell/src/agent/app.rs` | 更新 relay 启动条件（移除 xAI auth 限制） | 小 |
| `xai-webuild-workspace/src/hub.rs` | 适配自建 Hub Broker URL | 小 |
| `xai-webuild-config` | 新增 `relay_url`, `hub_url`, `gateway_url` 配置项 | 小 |
| `xai-webuild-models` | `default_models.json` 确认 DashScope 模型配置正确 | 小 |
| `xai-webuild-pager` | 可选: TUI 中显示 Web IDE 分享链接 | 小 |

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
│   ├── hub/                         # Hub Broker
│   │   ├── Dockerfile
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── broker.py           # 工具路由核心
│   │   │   ├── connection.py       # 连接管理
│   │   │   ├── routing_table.py    # 路由表
│   │   │   ├── session.py          # 会话绑定
│   │   │   └── wire/
│   │   │       ├── protocol.py     # JSON-RPC 2.0
│   │   │       └── handshake.py    # Hello 握手
│   │   └── tests/
│   ├── gateway/                     # Gateway
│   │   ├── Dockerfile
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── sandbox_manager.py  # 沙箱生命周期
│   │   │   ├── k8s_client.py       # 远程 K8s API 封装
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
├── deploy/                          # ECS 部署配置 (新增)
│   ├── docker-compose.yml           # 核心服务编排
│   ├── docker-compose.override.yml  # 本地开发覆盖
│   ├── .env.example                 # 环境变量模板
│   ├── nginx/
│   │   ├── nginx.conf               # Nginx 主配置
│   │   └── conf.d/
│   │       └── webuild.conf         # 站点配置 (路径路由 + WebSocket)
│   └── secrets/                     # 敏感文件 (git-ignored)
│       └── sandbox-kubeconfig.yaml  # Phase 4: ACS Serverless 集群凭证
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
| 沙箱创建时间 (预热 Pod) | < 10 秒 | Pod Pool 待命 |
| Hub Broker 工具调用延迟 | < 50ms (附加延迟) | Broker 转发开销 |
| 并发 WebSocket 连接数 | ≥ 50 per instance | 初期 1 replica |
| 并发沙箱数 | **≥ 20**（初期）/ ≥ 70（满配） | 受 ECI 配额限制 (可申请提升) |

#### 资源预算对照

| 部署阶段 | 核心服务部署 | 核心服务月成本 | 沙箱集群 | 最大并发沙箱 |
|----------|-------------|---------------|---------|-------------|
| Phase 0-3 (初始) | ECS (4C8G) Docker Compose | ~¥400-600 | — | — (沙箱未上线) |
| Phase 4 (沙箱上线) | ECS (4C8G) Docker Compose | ~¥400-600 | ACS Serverless (ECI 按量) | ~20 (≈¥288/月) |
| Phase 5 (满配) | ECS (升配 8C16G) 或迁移 ACK | ~¥800-1200 | ACS Serverless (ECI 按量) | ~70 (≈¥1008/月) |

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
| **ECS** | 阿里云弹性计算服务 (Elastic Compute Service)，本方案用于部署核心服务 |
| **ACK** | 阿里云容器服务 Kubernetes 版，本方案中生产集群不触碰 |
| **ACS** | 阿里云容器计算服务 (Container Service)，Serverless K8s，本方案中沙箱使用 ACS 集群 |
| **ECI** | 弹性容器实例 (Elastic Container Instance)，ACS Serverless 的底层运行单元 |
| **Docker Compose** | 容器编排工具，本方案用于 ECS 上的核心服务部署 |
