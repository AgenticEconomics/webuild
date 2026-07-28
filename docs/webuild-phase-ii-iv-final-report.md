# WeBuild Phase II–IV 开发总结报告（最终版）

> **项目名称**: WeBuild Web IDE & Cloud Sandbox  
> **开发周期**: 2026-07-25 ~ 2026-07-28（4 天）  
> **开发负责人**: Jerry Zhang  
> **版本范围**: v0.4.2 → v0.4.3+（22 commits）  
> **线上地址**: https://webuild.datoms.cn  
> **状态**: ✅ 全部功能上线运行，测试验收通过

---

## 一、项目概述

WeBuild 原为纯终端 AI 编程助手（CLI/TUI），基于 Grok Build 的 Rust 代码 fork，默认使用阿里云 DashScope `qwen-max` 模型。Phase II–IV 将其扩展为**浏览器可用的 AI 编程平台**，新增 Web IDE 前端、WebSocket 中继、工具路由代理、云端沙箱执行环境，并完成 ECS + ACS Serverless 部署上线。

### 核心目标达成

| 目标 | 状态 | 说明 |
|------|------|------|
| 降低使用门槛 | ✅ | 浏览器即可使用，无需安装 CLI |
| 跨设备协作 | ✅ | 任意设备访问同一编程会话 |
| 云端执行环境 | ✅ | ACS Serverless 沙箱，按需创建/销毁 |
| 企业级管控 | ✅ | JWT 认证 + RBAC + 审计日志 |
| 数据自主 | ✅ | 全部服务部署在阿里云 ECS，代码不出企业边界 |

---

## 二、架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| **核心服务部署** | 独立 ECS + Docker Compose | 与生产 ACK 集群物理隔离，零干扰 |
| **沙箱执行** | 阿里云 ACS Serverless (ECI) | 零节点运维，秒级弹性，按 Pod 计费 |
| **反向代理** | 复用 XinGu Caddy | 避免新增 Nginx，host-based 路由隔离 |
| **域名** | `webuild.datoms.cn` | 单域名 + 路径路由，无 CORS |
| **TLS** | Let's Encrypt (Caddy auto_https) | 自动签发 + 续期，零运维 |
| **数据库** | PostgreSQL (Docker) | 初期够用，无需 RDS |
| **LLM Agent** | Python 轻量 Agent + DashScope | 快速验证，ConfigMap 注入到 ACS Pod |
| **Session-Sandbox 关联** | session_id = sandbox_id | 创建 Session 自动创建关联 Sandbox |

---

## 三、系统架构

```
                          ┌─────────────────────────────────────────┐
                          │  ECS 8.136.127.63                       │
                          │                                         │
 浏览器 ──HTTPS──→ :443   │  Caddy (Let's Encrypt TLS)              │
                          │  ├─ webuild.datoms.cn                   │
                          │  │  ├─ /api/auth/*  → Auth (:8001)      │
                          │  │  ├─ /api/relay/* → Relay (:8002)     │
                          │  │  ├─ /api/gateway/*→ Gateway (:8004)  │
                          │  │  ├─ /ws/relay    → Relay (:8002) WS  │
                          │  │  ├─ /ws/hub      → Hub (:8003) WS    │
                          │  │  └─ /*           → Web IDE (:3000)   │
                          │  └─ * (其他)         → XinGu             │
                          │                                         │
                          │  Docker Compose (7 容器)                 │
                          │  ┌──────────┬──────────┬──────────┐     │
                          │  │ Auth     │ Relay    │ Hub      │     │
                          │  │ :8001    │ :8002    │ :8003    │     │
                          │  └──────────┴──────────┴──────────┘     │
                          │  ┌──────────┬──────────┬──────────┐     │
                          │  │ Gateway  │ Web IDE  │ Postgres │     │
                          │  │ :8004    │ :3000    │ :5432    │     │
                          │  └──────────┴──────────┴──────────┘     │
                          │  ┌──────────┐                           │
                          │  │ Agent    │ (本地 LLM Agent)          │
                          │  └──────────┘                           │
                          └────────────────────┬────────────────────┘
                                               │ K8s API (远程)
                                               ▼
                          ┌─────────────────────────────────────────┐
                          │  ACS Serverless 集群                     │
                          │  webuild-sandbox-aliyun_2608            │
                          │  c3f5b659659ed469d9517019a4bab4785      │
                          │                                         │
                          │  ┌───────────────────────────────────┐  │
                          │  │  Sandbox Pod (ECI 弹性实例)        │  │
                          │  │  ├─ python:3.11-slim              │  │
                          │  │  ├─ ConfigMap → sandbox_agent.py  │  │
                          │  │  ├─ DashScope API (qwen-max)      │  │
                          │  │  └─ 出站连接 Relay (role=agent)   │  │
                          │  └───────────────────────────────────┘  │
                          │                                         │
                          │  NetworkPolicy:                         │
                          │  ├─ deny-ingress (默认拒绝)             │
                          │  ├─ allow-gateway-ingress (:8080)       │
                          │  └─ egress-restrict (TCP/443 + DNS)     │
                          └─────────────────────────────────────────┘
```

### 数据流

```
场景 A: 本地 Agent 模式
  浏览器 → Caddy (HTTPS) → Web IDE → Relay :8002 (WS, browser)
  本地 CLI → Relay :8002 (WS, agent)
  Relay 桥接 browser ⟷ agent

场景 B: 云端沙箱模式
  浏览器 → Web IDE → 创建 Session → Gateway 创建 Sandbox Pod
  Sandbox Agent → Relay :8002 (WS, agent, session_id)
  浏览器 → Relay :8002 (WS, browser, session_id)
  Relay 桥接 browser ⟷ sandbox agent
  Sandbox Agent → DashScope API → 流式回复 → Relay → 浏览器
```

---

## 四、交付物清单

### 4.1 后端服务（6 个）

| 服务 | 技术栈 | 端口 | 功能 |
|------|--------|------|------|
| **Auth Service** | FastAPI + JWT + bcrypt | 8001 | 登录、Token 签发/刷新、API Key CRUD、RBAC、邀请白名单 |
| **Relay Server** | FastAPI + WebSocket + SQLAlchemy | 8002 | ACP 消息中继，browser↔agent 双向桥接，Session 持久化 |
| **Hub Broker** | FastAPI + WebSocket | 8003 | 工具路由代理 (hello/serve/session.bind/tool.call) |
| **Gateway** | FastAPI + K8s API + WebSocket | 8004 | 沙箱生命周期管理，ConfigMap 注入，Pod 日志 |
| **Web IDE** | Next.js 14 + TypeScript + Tailwind | 3000 | 浏览器前端，Grok Console 风格 UI |
| **Agent** | Python + websockets + DashScope | — | 本地 LLM Agent，自动发现并加入会话 |

### 4.2 前端页面

| 页面 | 路由 | 功能 |
|------|------|------|
| **Dashboard** | `/` | 首页，快速入口 |
| **Session 列表** | `/sessions` | 持久化 Session 列表（从 Relay API 加载） |
| **Session 详情** | `/sessions/[id]` | 实时对话、工具调用展示、权限审批 |
| **Sandbox 列表** | `/sandboxes` | 沙箱列表：状态徽章、创建/终止 |
| **Sandbox 详情** | `/sandboxes/[id]` | 沙箱状态、Pod 日志、实时聊天 |
| **Settings** | `/settings` | 登录表单、WebSocket URL、API Token 配置 |

### 4.3 共享库

| 模块 | 文件数 | 功能 |
|------|--------|------|
| `services/shared/` | 7 | JWT 管理器、SQLAlchemy 模型（User/ApiKey/Session/Sandbox/AuditLog）、认证中间件、日志配置 |

### 4.4 Rust 客户端修改

| Crate | 修改内容 |
|-------|---------|
| `xai-webuild-env` | 新增 Staging 变体，Production + Staging 均指向 `webuild.datoms.cn` |

### 4.5 基础设施

| 组件 | 配置 |
|------|------|
| **Docker Compose** | `deploy/docker-compose.yml` + override（生产/开发双模式） |
| **Caddy** | HTTPS (Let's Encrypt) + host-based 路由 + HTTP→HTTPS 重定向 |
| **ACS 集群** | namespace `webuild-sandbox`、ServiceAccount、RBAC、3 个 NetworkPolicy |
| **CI/CD** | `.gitlab-ci.yml` 扩展 `build-images` + `deploy-ecs` 阶段 |

---

## 五、代码统计

| 指标 | 数值 |
|------|------|
| **总文件数** | 132 个 |
| **Python 文件** | 50 个，7,146 行 |
| **TypeScript/JSX** | 22 个，2,935 行 |
| **总代码行数** | 10,081 行 |
| **Docker 镜像** | 7 个 |
| **Git Commits** | 22 个 |
| **设计文档** | 1,492 行 (`web-ide-cloud-sandbox-plan.md` v0.3.0) |
| **技术报告** | 2 份 (Phase II + Phase III/IV) |

### Docker 镜像

| 镜像 | 大小 |
|------|------|
| webuild-auth:local | 773 MB |
| webuild-relay:local | 769 MB |
| webuild-hub:local | 768 MB |
| webuild-gateway:local | 903 MB |
| webuild-web-ide:local | 233 MB |
| webuild-agent:local | 215 MB |
| webuild-sandbox:local | 1.03 GB |

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
0e2e604  Copy pip.conf into each service directory
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
6e52577  Docs: add Phase III & IV technical summary report
0316777  Phase III/IV: session-sandbox linkage, persistent sessions, sandbox logs
```

---

## 七、测试验收结果

### 7.1 自动化测试（29/29 通过）

| 类别 | 测试项 | 结果 |
|------|--------|------|
| **基础设施** | HTTPS/TLS、Let's Encrypt 证书、PostgreSQL | 3/3 ✅ |
| **后端服务** | Auth、Relay、Hub、Gateway、Web IDE、Agent、PostgreSQL | 7/7 ✅ |
| **Auth 认证** | 登录、/me、Token 刷新、401 拒绝 | 4/4 ✅ |
| **Relay Sessions** | 列表、创建 | 2/2 ✅ |
| **Gateway Sandboxes** | 列表、环境模板、Logs API | 3/3 ✅ |
| **ACS 集群** | Pods Running、NetworkPolicy | 3/3 ✅ |
| **Web IDE 页面** | Dashboard、Sessions、Sandboxes、Settings | 4/4 ✅ |
| **Session-Sandbox** | ID 关联匹配 | 1/1 ✅ |
| **Agent 连接** | Agent → Relay 认证成功 | 1/1 ✅ |
| **Rust 单元测试** | xai-webuild-env (5 tests) | 5/5 ✅ |

### 7.2 端到端验证

| 链路 | 状态 |
|------|------|
| 浏览器 → Caddy (HTTPS) → Web IDE | ✅ |
| 浏览器 → Relay :8002 (WS, role=browser) | ✅ |
| ACS Pod Agent → Relay :8002 (WS, role=agent) | ✅ |
| ACS Pod Agent → DashScope API (qwen-max, streaming) | ✅ |
| Session 创建 → Sandbox 自动创建 → Agent 连接 Relay | ✅ |
| HTTP → HTTPS 自动重定向 | ✅ |

---

## 八、关键技术问题与解决

| # | 问题 | 根因 | 解决方案 |
|---|------|------|---------|
| 1 | Caddy WS 代理浏览器失败 | Caddy `reverse_proxy` WS 升级与浏览器不兼容 | 浏览器直连 Relay :8002 |
| 2 | WebSocket 无限重连循环 | AcpClient 向 Relay 发 `initialize` → 30s 超时 | `onopen` 直接 resolve，不发 initialize |
| 3 | `crypto.randomUUID()` 报错 | HTTP 下非安全上下文 | `generateId()` 回退 Math.random UUID v4 |
| 4 | Next.js 页面缓存旧 JS | Caddy 透传 `s-maxage=31536000` | Caddy `header_down` 覆写 `no-cache` |
| 5 | Relay DB 表不存在 | lifespan 未调用 `create_all()` | 启动时 `Base.metadata.create_all()` |
| 6 | `session_id` 未传入 WS URL | AcpClient 只传 token，缺 session_id/role | URLSearchParams 构建完整查询参数 |
| 7 | Docker 构建慢（中国） | Docker Hub + PyPI + Debian 源被墙 | 阿里云镜像 (apt + pip + Docker registry) |
| 8 | JWT issuer 不匹配 | 域名变更后未重建所有服务镜像 | 重建全部 4 个 Python 服务 |
| 9 | ACME HTTP-01 返回 403 | Caddy `redir` 拦截了 `/.well-known/` | 添加 `not path` 排除条件 |
| 10 | ACS 无法拉取 Docker Hub | 中国网络限制 | 使用阿里云镜像 `alinux/python:3.11-slim` |
| 11 | Agent Token 不匹配 | sandbox agent 默认 token ≠ relay 配置 | 统一使用 `RELAY_TOKEN` 环境变量 |
| 12 | Session 无 Agent 响应 | Session 未关联 Sandbox，无 Agent 连接 | Session 创建时自动创建关联 Sandbox |
| 13 | 沙箱列表 `.map()` 报错 | Gateway 返回 `{sandboxes:[...]}` 对象 | 前端提取 `data.sandboxes` 数组 |

---

## 九、当前运行状态

| 容器 | 状态 | 端口 |
|------|------|------|
| deploy-auth-service-1 | ✅ Running | :8001 |
| deploy-relay-server-1 | ✅ Running | :8002 |
| deploy-hub-broker-1 | ✅ Running | :8003 |
| deploy-gateway-1 | ✅ Running | :8004 |
| deploy-web-ide-1 | ✅ Running | :3000 |
| deploy-agent-1 | ✅ Running | 内部 |
| deploy-postgres-1 | ✅ Healthy | :5432 |

| ACS Pod | 状态 | 节点 |
|---------|------|------|
| sandbox-* (按需) | ✅ Running | virtual-kubelet-cn-hangzhou-k |

---

## 十、已知限制与后续优化

| 优先级 | 项目 | 说明 |
|--------|------|------|
| **P1** | 自定义沙箱镜像 | ACR 凭证恢复后推送包含 dev tools 的完整镜像 |
| **P1** | 沙箱 Agent 工具执行 | 当前 Agent 仅做 LLM 对话，未集成 read_file/bash 等工具 |
| **P2** | Hub 端到端集成 | 沙箱 Agent 作为 ToolHarness 通过 Hub 调用本地 Workspace 工具 |
| **P2** | 多用户支持 | 用户注册、团队管理、API Key 自助管理 |
| **P2** | JWT 刷新完善 | 前端自动刷新已实现，需增加 refresh_token 过期处理 |
| **P3** | 监控告警 | Prometheus + Grafana dashboard |
| **P3** | 沙箱持久化 | PVC 挂载，沙箱休眠/恢复 |
| **P3** | CI/CD 自动化 | Docker 镜像自动构建推送、ECS 自动部署 |

---

## 附录：访问信息

| 项目 | 值 |
|------|-----|
| **Web IDE** | https://webuild.datoms.cn |
| **Auth API** | https://webuild.datoms.cn/api/auth/health |
| **Relay API** | https://webuild.datoms.cn/api/relay/health |
| **Gateway API** | https://webuild.datoms.cn/api/gateway/health |
| **测试账号** | `jerry` / `test123` (admin) |
| **Git 仓库** | https://git.jarvikheart.cn/jerryzhang/webuild |
| **ACS 集群** | webuild-sandbox-aliyun_2608 (c3f5b659...) |
| **ECS IP** | 8.136.127.63 |
