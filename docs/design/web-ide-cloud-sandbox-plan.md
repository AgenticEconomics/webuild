***************************************************************
**  使用的 Agent Session: 
**   qwen --resume 2a570304-6007-4b74-8c02-2c0d89424c20
***************************************************************

# WeBuild Web IDE & 云端沙箱 — 实施方案

> 版本: v0.1.0-draft · 日期: 2026-07-25 · 作者: Jerry Zhang
>
> 状态: **提案阶段** — 本文档为架构设计与实施规划，待评审后启动开发。

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

| 组件 | 说明 | 技术栈 | 初始资源 (req/lim) |
|------|------|--------|-------------------|
| **WeBuild Relay Server** | WebSocket 中继服务，替代 `code.grok.com` | Python (FastAPI) + WebSocket | 200m/1C · 256Mi/1Gi |
| **WeBuild Hub Broker** | 工具路由 Broker，替代 `computer-hub.grok.com` | Python (FastAPI) + WebSocket | 200m/1C · 256Mi/1Gi |
| **WeBuild Web IDE** | 浏览器前端，替代 `grok.com/code` | TypeScript (Next.js) | 200m/1C · 256Mi/1Gi |
| **WeBuild Cloud Sandbox** | 隔离的执行环境，替代 xAI 云端沙箱 | Docker + K8s (ACK 弹性节点池) | 1C/2C · 2Gi/4Gi per pod |
| **WeBuild Gateway** | 沙箱生命周期管理，替代 `grok.com/ws/gw/` | Python (FastAPI) + WebSocket | 100m/500m · 128Mi/512Mi |
| **WeBuild Auth Service** | 统一认证服务 | Python (FastAPI) + JWT/OIDC | 100m/500m · 128Mi/512Mi |
| **合计 (核心, 1 replica)** | | | **800m / 1Gi req** |

### 2.3 不需要的组件

| 上游组件 | 原因 |
|---------|------|
| `cli-chat-proxy.grok.com` | 上游 xAI 内部服务，WeBuild 使用 DashScope 直连模型 |
| `assets.grok.com` | 静态资源服务器，WeBuild 自行托管 |
| xAI OIDC 认证 | WeBuild 使用自建认证体系 |

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

Gateway 管理沙箱的完整生命周期，是 `grok.com/ws/gw/` 的替代实现：

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

本地 Leader 进程需要新增认证适配：

```rust
// 修改 xai-webuild-auth，增加 WeBuild Auth Service 适配
// 新增 xai-webuild-env 端点:

pub fn auth_service_url(&self) -> String {
    env_var("WEBUILD_AUTH_SERVICE_URL")
        .unwrap_or("https://auth.webuild.jarvikheart.cn".to_string())
}

pub fn relay_ws_url(&self) -> String {
    env_var("WEBUILD_RELAY_WS_URL")
        .unwrap_or("wss://relay.webuild.jarvikheart.cn/ws/agent".to_string())
}

pub fn hub_ws_url(&self) -> String {
    env_var("WEBUILD_HUB_WS_URL")
        .unwrap_or("wss://hub.webuild.jarvikheart.cn/ws/tools".to_string())
}

pub fn gateway_ws_url(&self) -> String {
    env_var("WEBUILD_GATEWAY_WS_URL")
        .unwrap_or("wss://gateway.webuild.jarvikheart.cn/ws/gateway".to_string())
}
```

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

### 8.1b 沙箱 Pod 资源配置（Phase 4）

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

### 8.4 CI/CD 流水线扩展现有 `.gitlab-ci.yml`

```yaml
# 在现有 build + publish 基础上新增:

stages:
  - build          # Rust 二进制 (已有)
  - build-images   # Docker 镜像构建 (新增)
  - publish        # GitLab Release (已有)
  - deploy         # K8s 部署 (新增)

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

### Phase 0: 基础设施准备 (2 周)

| 任务 | 产出 |
|------|------|
| **ACK 集群扩容: 新增 2 个节点** | 5 节点 / 20C / 80G，CPU requests 降至 ~61% |
| K8s 命名空间 + RBAC 配置 | `webuild-system`, `webuild-sandbox` namespace |
| PostgreSQL + Redis 部署 | **阿里云 RDS + 云 Redis**（集群外，不占 K8s 资源） |
| ACR 镜像仓库创建 | `registry.cn-hangzhou.aliyuncs.com/webuild/*` |
| 域名 + DNS + TLS | `*.webuild.jarvikheart.cn`，复用现有 NLB + cert-manager |
| Helm Chart 骨架 | `helm/webuild/` 目录结构 |

### Phase 1: Auth Service (2 周)

| 任务 | 产出 |
|------|------|
| JWT 签发/验证 | `/api/auth/login`, `/api/auth/token/refresh` |
| API Key 管理 | `/api/auth/api-keys` CRUD |
| RBAC 中间件 | FastAPI dependency injection |
| 数据库 migration | Alembic: users, api_keys, roles 表 |
| 单元测试 + 集成测试 | pytest 覆盖 |

### Phase 2: Relay Server + Web IDE MVP (4 周)

| 任务 | 产出 | 周 |
|------|------|----|
| Relay WebSocket 服务 | ACP 消息路由、会话管理 | 1-2 |
| 会话持久化 | JSONL → PostgreSQL 归档 | 2 |
| Web IDE 核心页面 | 会话列表 + 对话流 + 权限弹窗 | 2-3 |
| ACP Client SDK (TS) | WebSocket 封装 + 类型定义 | 1 |
| 终端面板 | xterm.js 集成 | 3 |
| 代码查看器 | Monaco Editor 集成 | 3-4 |
| 联调测试 | 本地 Leader → Relay → Web IDE 端到端 | 4 |

### Phase 3: Hub Broker (3 周)

| 任务 | 产出 | 周 |
|------|------|----|
| Broker 核心 | 路由表、连接管理、JSON-RPC 转发 | 1-2 |
| 协议兼容测试 | 与 Rust Hub SDK 的 hello/serve/call 互通 | 2 |
| 并发控制 + 限流 | per-session / per-connection 限流 | 2 |
| 健康检查 + 重连 | WebSocket keepalive、graceful shutdown | 3 |
| 本地 Leader 适配 | 修改 `xai-webuild-env` 端点配置 | 3 |

### Phase 4: Gateway + Cloud Sandbox (4 周)

| 任务 | 产出 | 周 |
|------|------|----|
| 沙箱容器镜像 | Dockerfile.sandbox + 基础工具 | 1 |
| Gateway 服务 | 沙箱 CRUD + K8s API 集成 | 1-2 |
| NetworkPolicy | 出站限制 (DashScope + Hub) | 2 |
| 沙箱 ACP 代理 | Gateway 代理 WebSocket → Pod | 2-3 |
| 生命周期管理 | TTL 自动清理、hibernate/restore | 3 |
| Web IDE 沙箱页面 | 创建/管理/连接沙箱 UI | 3-4 |
| 联调测试 | 完整流程: Web IDE → Gateway → Sandbox → Hub → 本地 | 4 |

### Phase 5: 生产化 (3 周)

| 任务 | 产出 | 周 |
|------|------|----|
| 监控 + 告警 | Prometheus metrics + Grafana dashboard | 1 |
| 审计日志 | 全链路操作审计 | 1 |
| 负载测试 | WebSocket 并发连接测试 | 2 |
| 安全审计 | 渗透测试 + 权限绕过检查 | 2 |
| 文档 | 部署文档 + 运维手册 + 用户指南 | 3 |
| CI/CD 完善 | 自动化部署流水线 | 3 |

### 里程碑总览

```
Week  1  2  3  4  5  6  7  8  9  10  11  12  13  14
      ├──────┤                                       Phase 0: 基础设施
            ├──────┤                                 Phase 1: Auth
                  ├──────────────┤                   Phase 2: Relay + Web IDE
                        ├──────────────┤             Phase 3: Hub Broker
                              ├──────────────┤       Phase 4: Gateway + Sandbox
                                          ├──────────────┤  Phase 5: 生产化
      ──────────────────────────────────────────────
      ▲          ▲                ▲              ▲
      M0         M1               M2             M3
   基础就绪    Web IDE 可用    端到端打通     生产发布
```

**总计: ~14 周**（约 3.5 个月），可交付最小可用版本。

---

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| **集群 CPU requests 不足，新 Pod 无法调度** | 🔴 高 | 高 | Phase 0 **必须先扩容 2 个节点**；沙箱使用独立节点池，与核心服务隔离 |
| 沙箱抢占式实例被回收，运行中任务中断 | 中 | 高 | 沙箱 Pod 设置 `terminationGracePeriodSeconds: 120`；Gateway 监听节点事件，自动迁移沙箱；关键任务禁用 Spot |
| WebSocket 长连接在高并发下不稳定 | 中 | 高 | 复用现有 Nginx Ingress (已验证)；sticky session by IP hash；连接超时 + 自动重连 |
| 沙箱 Pod 启动延迟影响用户体验 | 中 | 中 | 预热 Pod Pool（维护 N 个待命 Pod）；沙箱创建异步化，前端显示进度 |
| Hub Broker 成为单点瓶颈 | 低 | 高 | Phase 1 单实例 + sticky session；Phase 2 水平扩展或 Rust 重写 |
| Rust 客户端代码修改量大 | 中 | 中 | 仅修改 `xai-webuild-env` 端点配置 + `xai-webuild-auth` 认证适配，其余 SDK 代码不变 |
| DashScope API 不稳定 | 低 | 中 | 重试策略已有（sampler retry.rs 15 次退避）；可配置 fallback 模型 |
| K8s NetworkPolicy 配置错误导致沙箱无法访问模型 API | 中 | 中 | staging 环境充分测试；NetworkPolicy 模板化 + Git 版本控制 |
| 跨团队协调（运维 / 安全） | 中 | 低 | 提前沟通部署需求；Helm Chart 标准化减少运维负担 |

---

## 11. 附录

### A. 现有代码修改清单

| 文件/Crate | 修改内容 | 工作量 |
|-----------|---------|--------|
| `xai-webuild-env` | 替换所有 grok.com 端点为 `*.webuild.jarvikheart.cn` | 小 |
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
| 沙箱创建时间 (预热 Pod) | < 10 秒 | Pod Pool 待命 |
| Hub Broker 工具调用延迟 | < 50ms (附加延迟) | Broker 转发开销 |
| 并发 WebSocket 连接数 | ≥ 50 per instance | 初期 1 replica |
| 并发沙箱数 | **≥ 20**（初期）/ ≥ 70（满配） | 受沙箱节点池规模限制 |

#### 资源预算对照

| 部署阶段 | 节点数 | 核心服务 CPU Req | 核心服务 Mem Req | 最大并发沙箱 |
|----------|--------|-----------------|-----------------|-------------|
| Phase 1-3 (初始) | 5 (扩容后) | 800m | 1Gi | — (沙箱未上线) |
| Phase 4 (沙箱上线) | 5 + 沙箱池 | 800m | 1Gi | ~20 (3 个沙箱节点) |
| Phase 5 (满配) | 5 + 沙箱池 (扩) | 2000m (2+ replica) | 4Gi | ~70 (10 个沙箱节点) |

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
