# WeBuild Phase II 开发总结报告

> **项目名称**: WeBuild Web IDE & Cloud Sandbox  
> **开发周期**: 2026-07-25 ~ 2026-07-27（3天集中开发+部署）  
> **开发负责人**: Jerry Zhang  
> **版本范围**: v0.4.2 → v0.4.3+ (18 commits)

---

## 一、项目概述

Phase II 将 WeBuild 从纯终端 CLI 工具扩展为**浏览器可用的 AI 编程平台**，实现了 Web IDE 前端、WebSocket 中继、工具路由代理、沙箱生命周期管理等核心云服务，并完成 ECS 部署上线。

## 二、架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| **核心服务部署** | 独立 ECS + Docker Compose | 与生产 ACK 集群物理隔离，零干扰 |
| **沙箱执行** | 阿里云 ACS Serverless (ECI) | 零节点运维，秒级弹性，按 Pod 计费 |
| **反向代理** | 复用 XinGu Caddy | 避免新增 Nginx，host-based 路由隔离 |
| **域名** | `webuild.agentics-economics.org` | 单域名 + 路径路由，无 CORS |
| **数据库** | PostgreSQL (Docker) | 初期够用，无需 RDS |
| **LLM Agent** | Python 轻量 Agent + DashScope | 快速验证，无需依赖 Rust CLI |

## 三、交付物清单

### 3.1 新建服务（7个）

| 服务 | 技术栈 | 端口 | 功能 |
|------|--------|------|------|
| **Auth Service** | FastAPI + JWT + bcrypt | 8001 | 登录、Token 签发/刷新、API Key CRUD、RBAC |
| **Relay Server** | FastAPI + WebSocket | 8002 | ACP 消息中继，浏览器↔Agent 双向桥接 |
| **Hub Broker** | FastAPI + WebSocket | 8003 | 工具路由代理 (hello/serve/session.bind/tool.call) |
| **Gateway** | FastAPI + K8s API | 8004 | 沙箱生命周期管理（Phase 4 启用） |
| **Web IDE** | Next.js 14 + TypeScript | 3000 | 浏览器前端，Grok Console 风格 UI |
| **Agent** | Python + websockets + DashScope | — | 轻量 LLM Agent，自动发现并加入会话 |
| **PostgreSQL** | PostgreSQL 16 Alpine | 5432 | 持久化存储 |

### 3.2 共享库

| 模块 | 文件数 | 功能 |
|------|--------|------|
| `services/shared/` | 7 | JWT 管理器、SQLAlchemy 模型（User/ApiKey/Session/Sandbox/AuditLog）、认证中间件、日志配置 |

### 3.3 Rust 客户端修改

| Crate | 修改内容 |
|-------|---------|
| `xai-webuild-env` | 新增 Staging 变体，Production + Staging 均指向 `webuild.agentics-economics.org` |

### 3.4 基础设施配置

| 组件 | 配置 |
|------|------|
| **Docker Compose** | `deploy/docker-compose.yml` + override（生产/开发双模式） |
| **Caddy** | host-based 路由：`webuild.agentics-economics.org` → WeBuild，其他 → XinGu |
| **ACS 集群** | namespace `webuild-sandbox`、ServiceAccount、RBAC、NetworkPolicy（14 个 K8s 资源） |
| **沙箱镜像** | `sandbox/Dockerfile`（Ubuntu 24.04 + webuild 二进制 + 非 root 用户） |
| **CI/CD** | `.gitlab-ci.yml` 扩展 `build-images` + `deploy-ecs` 阶段 |

## 四、代码统计

| 指标 | 数值 |
|------|------|
| **新增文件** | 116 个 |
| **Python 文件** | 48 个，6,455 行 |
| **TypeScript/JSX** | 14 个，1,567 行 |
| **Docker 镜像** | 7 个（auth 773MB, relay 769MB, hub 766MB, gateway 902MB, web-ide 233MB, agent 215MB） |
| **Git commits** | 18 个 |
| **设计文档** | 1,492 行 (`web-ide-cloud-sandbox-plan.md` v0.3.0) |

## 五、Git 提交历史

```
46f127e  Add Web IDE and cloud sandbox implementation plan
963c5fe  Design: revise to ECS + Docker Compose, isolate from prod ACK
64cba2c  Design: replace ACK node pools with ACS Serverless (ECI)
01bbc2a  Phase II: full implementation (84 files, 8101 insertions)
63033bb  Fix Dockerfiles for China mirrors and auth migration
7d8c826  Fix Web IDE TypeScript build errors
98af7bd  Enable Web IDE in docker-compose and fix Caddy routing
d4da63c  Fix auth route prefix and add Web IDE build artifacts
e9f2bcf  Fix Web IDE navigation: New Session and Settings buttons (v0.4.3)
96d88e3  Redesign Web IDE with Grok console-style UI
f62abd3  Fix crypto.randomUUID not available over HTTP
0e2e604  Copy pip.conf into each service directory
ec93d69  Fix relay WebSocket: create DB tables on startup
add5df9  Fix WebSocket connection: pass session_id and role to relay
b09b269  Fix WebSocket protocol: auto-detect ws/wss from page protocol
c8c7220  Fix WebSocket: connect directly to relay :8002 bypassing Caddy
aa23f75  Set no-cache for Web IDE HTML pages
a9edf1b  Fix reconnect loop: don't send ACP initialize to relay
```

## 六、部署架构

```
                          ┌────────────────────────────────────┐
                          │  ECS 8.136.127.63                  │
                          │                                    │
 浏览器 ──HTTP──→ :80     │  Caddy (host-based routing)        │
                          │  ├─ webuild.agentics-economics.org │
                          │  │  ├─ /api/auth/*  → :8001       │
                          │  │  ├─ /api/relay/* → :8002       │
                          │  │  ├─ /ws/hub      → :8003       │
                          │  │  └─ /*           → :3000       │
                          │  └─ * (其他)         → XinGu       │
                          │                                    │
 浏览器 ──WS───→ :8002    │  Relay Server (直连,绕过Caddy)     │
                          │                                    │
                          │  Auth Service  :8001               │
                          │  Hub Broker    :8003               │
                          │  Agent (自动)   内部               │
                          │  PostgreSQL    :5432               │
                          └────────────────────────────────────┘
                                            │ K8s API (Phase 4)
                                            ▼
                          ┌────────────────────────────────────┐
                          │  ACS Serverless (Phase 4 启用)      │
                          │  webuild-sandbox-aliyun_2608       │
                          └────────────────────────────────────┘
```

## 七、关键技术问题与解决

| # | 问题 | 根因 | 解决方案 |
|---|------|------|---------|
| 1 | Caddy WS 代理浏览器连接失败 | Caddy reverse_proxy 对浏览器 WS 升级处理异常 | 浏览器直连 Relay :8002 端口 |
| 2 | WebSocket 无限重连循环 | AcpClient 向 Relay 发送 `initialize`，Relay 不处理→30s 超时 | `onopen` 直接 resolve，不发 initialize |
| 3 | `crypto.randomUUID()` 报错 | 需要安全上下文 (HTTPS)，HTTP 下不可用 | `generateId()` 回退到 Math.random UUID v4 |
| 4 | Next.js 页面缓存旧 JS | Caddy 透传 `s-maxage=31536000` | Caddy `header_down` 覆写为 `no-cache` |
| 5 | Relay DB 表不存在 | lifespan 未调用 `create_all()` | 启动时 `Base.metadata.create_all()` |
| 6 | `session_id` 未传入 WS URL | AcpClient 只传 token，缺 session_id 和 role | URLSearchParams 构建完整查询参数 |
| 7 | Docker 构建慢（中国） | Docker Hub + PyPI + Debian 源均被墙 | 阿里云镜像 (apt + pip + Docker registry) |
| 8 | JWT Token 过期后连接失败 | 60 分钟有效期，过期后 Relay 认证失败 | 需重新登录获取新 Token（待实现自动刷新） |

## 八、当前运行状态

| 容器 | 状态 | 端口 |
|------|------|------|
| deploy-auth-service-1 | ✅ Running | :8001 |
| deploy-relay-server-1 | ✅ Running | :8002 |
| deploy-hub-broker-1 | ✅ Running | :8003 |
| deploy-agent-1 | ✅ Running | 内部 |
| deploy-web-ide-1 | ✅ Running | :3000 |
| deploy-postgres-1 | ✅ Healthy | :5432 |

## 九、待完成项（后续 Phase）

| 优先级 | 任务 | 说明 |
|--------|------|------|
| **P0** | JWT Token 自动刷新 | 前端 Token 过期后自动调用 refresh 接口 |
| **P0** | Agent 与 DashScope 端到端联调 | 验证浏览器→Relay→Agent→DashScope→回复的完整链路 |
| **P1** | HTTPS/TLS | Caddy 配置 Let's Encrypt 或阿里云 SLB SSL |
| **P1** | 持久化部署 | PostgreSQL 数据盘挂载、定期备份 |
| **P2** | Phase 4: Gateway + 沙箱 | ACS 集群 Pod 管理、沙箱创建/销毁、TTL 清理 |
| **P2** | 用户自注册 | 开放注册接口，自动创建 API Key |
| **P3** | 监控告警 | Prometheus + Grafana dashboard |
| **P3** | CI/CD 自动化 | Docker 镜像自动构建推送、ECS 自动部署 |
