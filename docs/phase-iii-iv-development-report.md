# WeBuild Phase III & IV 技术总结报告

> **项目名称**: WeBuild Web IDE & Cloud Sandbox  
> **开发周期**: 2026-07-27（1天集中开发+部署+调试）  
> **开发负责人**: Jerry Zhang  
> **版本范围**: Phase II (v0.4.3) → Phase III/IV 完成  
> **当前状态**: ✅ 全部功能上线运行

---

## 一、Phase III — Hub Broker 与工具路由

### 1.1 概述

Phase III 实现了 Hub Broker 工具路由服务，使云端沙箱 Agent 可以通过 Hub 远程调用本地 Workspace 的工具。Hub Broker 替代了上游 `computer-hub.grok.com` 的角色。

### 1.2 已完成组件

#### Hub Broker (`services/hub/`)

| 文件 | 功能 |
|------|------|
| `src/main.py` | FastAPI 应用，WebSocket 端点 `/ws`，健康检查 `/health`，连接统计 `/stats` |
| `src/broker.py` | 核心路由引擎：处理 hello 握手、serve 注册、session.bind 绑定、tool.call 转发 |
| `src/connection.py` | 连接管理：跟踪 connection_id、kind (ToolServer/ToolHarness)、server_id |
| `src/routing_table.py` | 路由表：正向索引 connection→tools，反向索引 (session_id, tool_id)→connection |
| `src/session.py` | 会话状态管理 |
| `src/wire/protocol.py` | JSON-RPC 2.0 协议常量、消息编解码 |
| `src/wire/handshake.py` | Hello 握手验证：protocolVersion、kind 提取 |

#### 协议兼容性

Hub Broker 与 Rust `xai-computer-hub-sdk` 的 JSON-RPC 2.0 协议完全兼容：

```
1. WebSocket 连接 + Bearer Token
2. hello 握手: { protocol_version, kind: "ToolServer"|"ToolHarness", server_id }
3. serve: 注册工具列表 → session.bind: 绑定会话
4. tool.call: Harness 调用 → Broker 路由 → ToolServer 执行 → 返回结果
```

### 1.3 部署状态

| 项目 | 值 |
|------|-----|
| **端口** | 8003 |
| **镜像** | `webuild-hub:local` (768MB) |
| **容器** | `deploy-hub-broker-1` — Running |
| **Caddy 路由** | `/ws/hub` → `deploy-hub-broker-1:8003` |

---

## 二、Phase IV — ACS 云端沙箱

### 2.1 概述

Phase IV 实现了阿里云 ACS Serverless 集群上的云端沙箱功能。用户可以一键创建隔离的云端执行环境，沙箱内运行 AI Agent，通过 DashScope API 调用大模型，并通过 Relay 与浏览器通信。

### 2.2 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│  浏览器 (Web IDE)                                               │
│  https://webuild.datoms.cn/sandboxes/[id]                       │
└────────────┬──────────────────────────────────────┬─────────────┘
             │ HTTPS                                │ WSS
             ▼                                      ▼
┌────────────────────────┐          ┌──────────────────────────────┐
│  Gateway (:8004)       │          │  Relay Server (:8002)        │
│  REST API: 沙箱 CRUD   │          │  WebSocket 桥接              │
│  K8s API: Pod 生命周期  │          │  browser ⟷ agent 配对       │
└────────────┬───────────┘          └──────────┬───────────────────┘
             │ K8s API (远程)                    │ WS (role=agent)
             ▼                                  │
┌─────────────────────────────────────────────┐ │
│  ACS Serverless 集群                         │ │
│  webuild-sandbox-aliyun_2608                │ │
│  c3f5b659659ed469d9517019a4bab4785          │ │
│                                             │ │
│  ┌───────────────────────────────────────┐  │ │
│  │  Sandbox Pod (ECI 弹性实例)            │  │ │
│  │  ├─ python:3.11-slim (基础镜像)       │──┘ │
│  │  ├─ ConfigMap 注入 sandbox_agent.py    │    │
│  │  ├─ pip install → httpx/websockets     │    │
│  │  └─ Sandbox Agent (:8080)              │    │
│  │     ├─ 出站连接 Relay (role=agent)     │    │
│  │     ├─ DashScope API (qwen-max)       │    │
│  │     └─ 流式响应 → Relay → 浏览器      │    │
│  └───────────────────────────────────────┘    │
│                                               │
│  NetworkPolicy:                               │
│  ├─ sandbox-deny-ingress (默认拒绝入站)       │
│  ├─ sandbox-allow-gateway-ingress (:8080)     │
│  └─ sandbox-egress-restrict (TCP/443 + DNS)   │
└─────────────────────────────────────────────────┘
```

### 2.3 核心组件

#### Gateway 服务 (`services/gateway/`)

| 文件 | 功能 |
|------|------|
| `src/main.py` | FastAPI 应用，REST 端点 + WebSocket 代理 `/ws/sandbox/{id}` |
| `src/k8s_client.py` | K8s API 封装：Pod/Service/ConfigMap CRUD，Agent 代码注入 |
| `src/sandbox_manager.py` | 沙箱生命周期管理：创建/终止/列表/TTL 清理，环境模板 |
| `src/acp_proxy.py` | WebSocket 双向代理：浏览器 ⟷ 沙箱 Pod |
| `src/models.py` | Pydantic 模型：SandboxStatus, SandboxEnvironment, CreateSandboxRequest |

**关键设计决策 — ConfigMap 注入 Agent 代码**：

由于 ACS 集群无法拉取自定义镜像（ACR 凭证过期），Gateway 使用标准 `python:3.11-slim` 镜像 + ConfigMap 注入方式：

1. Gateway 读取本地 `sandbox/agent/sandbox_agent.py` 源码
2. 创建 K8s ConfigMap 包含 Agent 代码
3. Pod 挂载 ConfigMap 到 `/opt/agent/`
4. Pod 启动命令：`pip install httpx websockets structlog && python3 /opt/agent/sandbox_agent.py`

#### Sandbox Agent (`sandbox/agent/sandbox_agent.py`)

轻量 Python WebSocket Agent，运行在每个沙箱 Pod 内：

- **出站连接模式**：Agent 启动后主动连接 Relay Server（`role=agent`），而非被动等待
- **ACP 协议处理**：支持 `initialize`、`session/new`、`session/prompt`、`session/cancel`
- **DashScope 流式调用**：通过 `httpx` 流式调用 DashScope API，逐 token 转发给 Relay
- **自动重连**：连接断开后 3 秒自动重连
- **优雅关闭**：捕获 SIGTERM/SIGINT 信号

#### Relay 增强 (`services/relay/`)

| 增强 | 说明 |
|------|------|
| `RELAY_INTERNAL_TOKEN` | 内部 Agent 认证令牌，沙箱 Agent 绕过 JWT 验证 |
| Agent 自动建 Session | Agent 先于 Browser 连接时自动创建 Session |
| `/discover` 端点 | 列出等待 Agent 的 Session（无认证） |
| DB 表自动创建 | lifespan 中 `Base.metadata.create_all()` |

### 2.4 ACS 集群配置

| 资源 | 值 |
|------|-----|
| **集群** | `webuild-sandbox-aliyun_2608` (ACS Serverless) |
| **Cluster ID** | `c3f5b659659ed469d9517019a4bab4785` |
| **Namespace** | `webuild-sandbox` |
| **ServiceAccount** | `gateway-sa` (最小权限 RBAC) |
| **Virtual Kubelet** | cn-hangzhou-b/j/k (3 AZ) |
| **NetworkPolicy** | 3 个策略：deny-ingress + allow-gateway + egress-restrict |

### 2.5 沙箱 API

```
GET    /api/gateway/environments     # 列出环境模板
POST   /api/gateway/sandboxes        # 创建沙箱 (→ K8s Pod)
GET    /api/gateway/sandboxes        # 列出用户沙箱
GET    /api/gateway/sandboxes/:id    # 沙箱详情 + Pod 状态
DELETE /api/gateway/sandboxes/:id    # 终止沙箱 (→ 删除 Pod)
GET    /api/gateway/sandboxes/:id/logs  # Pod 日志
```

### 2.6 Web IDE 沙箱管理 UI

| 页面 | 功能 |
|------|------|
| `/sandboxes` | 沙箱列表：状态徽章、创建时间、终止按钮、空状态引导 |
| `/sandboxes/[id]` | 沙箱详情：状态指示器、元信息栏、实时聊天、Agent 连接状态 |

---

## 三、基础设施增强

### 3.1 HTTPS/TLS (Let's Encrypt)

| 项目 | 值 |
|------|-----|
| **域名** | `webuild.datoms.cn` |
| **证书** | Let's Encrypt (自动签发 + 续期) |
| **颁发机构** | `acme-v02.api.letsencrypt.org` |
| **Caddy 端口** | 80 (HTTP) + 443 (HTTPS) + 443/udp (HTTP/3) |
| **HTTP→HTTPS** | 自动 301 重定向（排除 ACME challenge 路径） |

**ACME Challenge 踩坑记录**：

1. **TLS-ALPN-01 失败**：ECS 安全组未开放 443 端口 → 添加端口映射
2. **HTTP-01 首次失败**：Caddy 的 `redir` 指令将 `/.well-known/acme-challenge/*` 也重定向到 HTTPS → 添加 `not path` 排除条件
3. **Rate Limit**：5 次失败后触发 Let's Encrypt 1 小时限流 → 修复后等待限流解除
4. **域名切换**：`agentics-economics.org` DNS 未生效 → 改用 `webuild.datoms.cn` 成功

### 3.2 域名变更

`webuild.agentics-economics.org` → **`webuild.datoms.cn`**

全量替换涉及：Rust (xai-webuild-env)、Python (jwt.py)、Caddy、Nginx、文档

### 3.3 JWT 自动刷新

| 组件 | 功能 |
|------|------|
| `use-token-refresh.ts` | React Hook：解码 JWT exp，过期前 2 分钟自动调用 refresh |
| `token-refresh-provider.tsx` | Client Component 包装器，挂载到 Layout |
| Settings 登录表单 | 用户名/密码登录，自动存储 access_token + refresh_token |

### 3.4 WebSocket 连接修复

| 问题 | 根因 | 解决方案 |
|------|------|---------|
| Caddy WS 代理浏览器失败 | Caddy `reverse_proxy` WS 升级与浏览器不兼容 | 浏览器直连 Relay :8002 |
| AcpClient 无限重连 | `initialize` 发给 Relay → 30s 超时 → 断开重连 | `onopen` 直接 resolve，不发 initialize |
| Next.js 缓存旧 JS | `s-maxage=31536000` 透传 | Caddy `header_down` 覆写 `no-cache` |
| `crypto.randomUUID` 报错 | HTTP 下非安全上下文 | `generateId()` 回退 Math.random |
| WS 协议不匹配 | HTTPS 页面用 `ws://` 被混合内容阻止 | 自动检测 `wss://` / `ws://` |

---

## 四、代码统计

| 指标 | 数值 |
|------|------|
| **新增文件** | 124 个 |
| **Python 代码** | 6,765 行 |
| **TypeScript 代码** | 2,207 行 |
| **Docker 镜像** | 7 个（auth 773MB, relay 769MB, hub 768MB, gateway 903MB, web-ide 233MB, sandbox 1.03GB, agent 215MB） |
| **Git Commits** | 20 个 (Phase II-IV) |

### 服务清单

| 服务 | 技术栈 | 端口 | 容器状态 |
|------|--------|------|---------|
| Auth Service | FastAPI + JWT + bcrypt | 8001 | ✅ Running |
| Relay Server | FastAPI + WebSocket + SQLAlchemy | 8002 | ✅ Running |
| Hub Broker | FastAPI + WebSocket | 8003 | ✅ Running |
| Gateway | FastAPI + K8s API + WebSocket | 8004 | ✅ Running |
| Web IDE | Next.js 14 + TypeScript + Tailwind | 3000 | ✅ Running |
| Agent (本地) | Python + websockets | — | ✅ Running |
| PostgreSQL | 16-alpine | 5432 | ✅ Healthy |

---

## 五、端到端验证结果

### 5.1 完整链路

```
浏览器 → Caddy (HTTPS) → Web IDE (Next.js)
浏览器 → Relay :8002 (WS, role=browser)
ACS Pod Agent → Relay :8002 (WS, role=agent)
ACS Pod Agent → DashScope API (qwen-max, streaming)
```

### 5.2 验证清单

| 测试项 | 结果 |
|--------|------|
| HTTPS 访问 `https://webuild.datoms.cn` | ✅ Let's Encrypt 证书有效 |
| Auth 登录 `jerry/test123` | ✅ 返回 access_token + refresh_token |
| JWT 自动刷新 | ✅ 过期前 2 分钟自动 renew |
| 沙箱列表 `/sandboxes` | ✅ 显示历史沙箱 |
| 创建沙箱 | ✅ ACS Pod 启动，Agent 连接 Relay |
| E2E 对话 | ✅ 浏览器发消息 → Agent → DashScope → 流式回复 |
| 沙箱 TTL 自动清理 | ✅ 过期 Pod 自动终止 |

---

## 六、Git 提交历史

```
01bbc2a  Phase II: Web IDE + Cloud Sandbox — full implementation
63033bb  Fix Dockerfiles for China mirrors and auth migration
7d8c826  Fix Web IDE TypeScript build errors
98af7bd  Enable Web IDE in docker-compose and fix Caddy routing
d4da63c  Fix auth route prefix and add Web IDE build artifacts
e9f2bcf  Fix Web IDE navigation: New Session and Settings buttons
96d88e3  Redesign Web IDE with Grok console-style UI
f62abd3  Fix crypto.randomUUID not available over HTTP
0e2e604  Copy pip.conf into each service directory for Docker builds
ec93d69  Fix relay WebSocket: create DB tables on startup
add5df9  Fix WebSocket connection: pass session_id and role to relay
b09b269  Fix WebSocket protocol: auto-detect ws/wss from page protocol
c8c7220  Fix WebSocket: connect directly to relay :8002 bypassing Caddy
aa23f75  Set no-cache for Web IDE HTML pages
a9edf1b  Fix reconnect loop: don't send ACP initialize to relay
263864f  (v0.4.3) Docs: add Phase II development summary report
b290b42  Phase IV: ACS cloud sandbox — end-to-end verified
cf5daf0  Add sandbox management UI, login form, and JWT auto-refresh
ff30796  Rename domain to webuild.datoms.cn (Let's Encrypt TLS verified)
349ffe2  Fix sandboxes list: extract .sandboxes array from Gateway response
```

---

## 七、已知限制与后续优化

| 优先级 | 项目 | 说明 |
|--------|------|------|
| P1 | 自定义沙箱镜像 | ACR 凭证恢复后推送包含 dev tools 的完整镜像，替代 ConfigMap 注入 |
| P1 | 沙箱 Agent 工具执行 | 当前 Agent 仅做 LLM 对话，未集成 read_file/bash 等工具 |
| P2 | Hub 端到端集成 | 沙箱 Agent 作为 ToolHarness 通过 Hub 调用本地 Workspace 工具 |
| P2 | 多用户支持 | 用户注册、团队管理、API Key 自助管理 |
| P3 | 监控告警 | Prometheus + Grafana dashboard |
| P3 | 沙箱持久化 | PVC 挂载，沙箱休眠/恢复 |
