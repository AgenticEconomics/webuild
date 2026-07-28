# WeBuild Phase V 阶段性开发总结报告

> **阶段**: Phase V — 沙箱完整 WeBuild Agent + 全工具能力  
> **日期**: 2026-07-28  
> **状态**: **V1–V3 已交付并 E2E 验证通过**；V4（Hub 远程本机工具）未开始  
> **主提交**: `01fad79`（`main` / `origin/main`）  
> **相关文档**: [`phase-v-sandbox-full-agent-plan.md`](./phase-v-sandbox-full-agent-plan.md)、[`phase-v-audit-report.md`](./phase-v-audit-report.md)

---

## 1. 阶段目标与结论

### 1.1 目标

将 ACS 沙箱从「Python 仅聊天」升级为 **完整 Rust `webuild agent headless`**，在 `/workspace` 上具备与本地 CLI 同等的工具能力（读写文件、终端、搜索等），并通过 Web IDE + Relay 端到端可用。

### 1.2 结论（一句话）

**已达成**：新建 Session → ACS 起全量 Agent → ACP 握手 → 工具调用 → `/workspace` 落盘成功。  
**未达成**：沙箱经 Hub 调用本机 Workspace 工具（Phase V-B / V4）。

| 成功标准 | 结果 |
|----------|------|
| S1 Session 配对 ACS Agent | ✅ |
| S2 Prompt 出现 tool_call | ✅ |
| S3 `/workspace` 读写成功 | ✅ 已核实 `hello.txt` |
| S4 YOLO 无人值守 | ✅（默认开启 + Web IDE 自动批准兜底） |
| S5 Hub → 本机工具 | ❌ 未做 |
| S6 Python 降级为 fallback | ✅ `legacy-python` / `SANDBOX_AGENT=python` |

---

## 2. 架构变化

```
Before (Phase IV)
  Browser → Relay ← ACS Pod: sandbox_agent.py（无工具）

After (Phase V)
  Browser → Relay ← ACS Pod: webuild agent headless
                     ├─ 本地工具 ×25（/workspace）
                     ├─ DashScope LLM
                     └─ YOLO 自动批准
```

轻量 ECS `deploy-agent`（discover）已停用默认路径；`prefer_sandbox` 会话等待 ACS，避免聊天-only Agent 抢座。

---

## 3. 交付清单

### 3.1 已完成（V1–V3 + 联调修复）

| 模块 | 内容 |
|------|------|
| **镜像** | `sandbox/Dockerfile` 打包 `webuild`；`sandbox-init.sh` 写 config/API Key、拼 Relay URL、YOLO headless |
| **Gateway** | 默认 `SANDBOX_IMAGE` 全量镜像；资源 1C2G / 限 4C8G；TTL 1h；可重建 terminated sandbox |
| **Relay** | Bearer / query token；`prefer_sandbox`；`agent_kind=sandbox` 可置换轻量 agent |
| **Rust** | `WEBUILD_SANDBOX_MODE`、`RelayConfig::for_sandbox`、headless + internal token + YOLO |
| **Web IDE** | 等 `agent_connected` → `initialize` + `session/new`；关闭客户端 FS 能力；权限自动批准；Markdown 渲染 |
| **运维** | `deploy/scripts/refresh-acr-pull-secret.sh` + cron（ACR 临时 token ~1h） |

### 3.2 联调中发现并修复的关键问题

| 问题 | 现象 | 修复 |
|------|------|------|
| clap 参数顺序 | `--webuild-ws-url` 写在 `headless` 前 → query 丢失 | URL 必须跟在 `headless` 后 |
| 缺 ACP handshake | `session/prompt` 立刻 `unknown session id` | Web IDE 先 initialize + session/new |
| 声明了浏览器 FS | 卡在 `fs/read_text_file` | `readTextFile/writeTextFile=false` |
| ACR 临时凭据过期 | `ImagePullBackOff` / 401 | 刷新 secret + 45min cron |
| 轻量 agent 抢座 | 无工具的文本回复 | 停 discover agent + prefer_sandbox |
| Markdown 裸文本 | 表格显示为 `\|` | `react-markdown` + GFM |

### 3.3 未完成（下阶段）

- **V4 / V-B**：沙箱 ToolHarness → Hub → 本机 Leader ToolServer  
- Session 重连完整 `session/load`（刷新后 LLM context 可能不完整）  
- 删除 Session 时联动 terminate ACS（现需 Sandboxes 页手动停或等 TTL）  
- idle 回收、监控大盘、镜像内版本标签 build-arg

---

## 4. ACR 镜像版本核查（2026-07-28）

### 4.1 Gateway 实际使用

```text
SANDBOX_IMAGE=xingu-aliyun-acr-registry.cn-hangzhou.cr.aliyuncs.com/webuild/sandbox:latest
```

### 4.2 核查结果

| Tag | Digest (image id) | webuild 二进制 | `sandbox-init.sh` 中 headless 顺序 | 结论 |
|-----|-------------------|----------------|-------------------------------------|------|
| **`latest`** | `sha256:a59334c5…` | `0.2.102 (82160c6)` sha=`27b7a71b…` | ✅ `headless --webuild-ws-url …` | **正确（生产）** |
| **`phase-v`（核查前）** | `sha256:59ff8dc8…` | 同二进制 sha | ❌ `--webuild-ws-url … headless` | **错误（旧 init）** |
| **`phase-v`（已纠正）** | `sha256:a59334c5…`（与 latest 相同） | 同上 | ✅ 与 latest 一致 | **已删除旧 tag 后重推** |
| **`01fad79`** | `sha256:a59334c5…` | 同上 | ✅ | **追溯 tag，与 latest 一致** |

说明：

1. 二进制 content hash 相同（`27b7a71b…`）；核查前 `phase-v` 与 `latest` 的差异主要在 **init 脚本参数顺序**（决定 Relay query 是否完整）。  
2. ACR 默认禁止覆盖 tag，已通过 `cr DeleteRepoTag` 删除旧 `phase-v` 后再推送对齐。  
3. 其它仓库路径上的历史镜像（如 `webuild-sandbox:phase-v`、公共仓 `registry.cn-hangzhou…`）可能仍指向旧层；**以企业版 ACR `…/webuild/sandbox:{latest,phase-v,01fad79}` 为准**。  
4. Gateway `SANDBOX_IMAGE` 指向 `:latest`，与当前正确镜像一致。

### 4.3 建议运维约定

- ACS / Gateway **只拉** `…/webuild/sandbox:latest`（或固定 digest）  
- 发版时同步：`latest` + `phase-v` + `<git-short-sha>`  
- 保持 ACR pull secret cron（临时 `cr_temp_user`）

---

## 5. 运行与计费要点

- **TTL**：创建后 **1 小时** Gateway 自动删 Pod → 停 ECI 计费  
- **关浏览器 / 删 Session**：默认 **不停** ACS（删 Session 不联动 terminate）  
- **ACS 集群**：无 Pod 时集群仍在（Virtual Kubelet）；沙箱费用已停，集群本身可保留以便下次创建  

---

## 6. 验收证据（节选）

1. Session `0bb73d9c-…`：Agent 回复「文件已创建完成」；Pod 内  
   `cat /workspace/hello.txt` → `hello webuild`  
2. 工具列表（沙箱注册约 25 个）：`write` / `read_file` / `run_terminal_command` / `web_search` / …  
3. `web_search` 等工具在对话中出现 tool_call；Markdown 渲染已上线  

---

## 7. 回滚

| 级别 | 动作 |
|------|------|
| L1 | Gateway `SANDBOX_IMAGE` 回滚旧 digest / tag |
| L2 | `environment_id=legacy-python` 或 `SANDBOX_AGENT=python` |
| L3 | 停 ACS 创建，仅用 ECS 轻量 agent（不推荐） |

---

## 8. 下一阶段建议（优先级）

1. **V4**：Hub 远程本机工具（产品差异化）  
2. Web IDE：重连走 `session/load`；删 Session 联动 terminate sandbox  
3. 镜像：Dockerfile `ARG GIT_SHA` 写入 `/etc/webuild-release`  
4. 监控：冷启动耗时、ImagePullBackOff、工具失败率  

---

## 9. 变更索引（主要路径）

```text
sandbox/Dockerfile
sandbox/scripts/sandbox-init.sh
services/gateway/src/sandbox_manager.py
services/gateway/src/k8s_client.py
services/relay/src/{main,relay,session_manager}.py
crates/codegen/xai-webuild-shell/src/agent/{relay,app}.rs
services/web-ide/src/lib/acp-client.ts
services/web-ide/src/stores/session-store.ts
services/web-ide/src/components/message-content.tsx
deploy/scripts/refresh-acr-pull-secret.sh
deploy/docker-compose*.yml / deploy/.env
```

---

*报告生成于 Phase V E2E 通过且 ACR `latest`/`phase-v` 对齐核查之后。*
