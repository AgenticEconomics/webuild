# Phase VII — Session 文件上传、Workspace 目录规范、Outputs 下载

> **状态**: 已实现（VII-0–VII-4）  
> **分支**: `main`（`release-0.6.6` 已冻结 Phase I–VI）  
> **前置**: Phase V 沙箱全量 Agent；Phase VI Skills；v0.6.7 用户会话隔离  
> **目标**: 用户可在 Session 中向对应 Sandbox 上传材料；Agent 在规范 Workspace 中用 tools/skills 处理；用户可下载 `outputs/` 交付物。

---

## 1. 背景与缺口

### 现状

```
Browser → Relay ↔ ACS Pod: webuild agent headless
                         └─ /workspace（扁平、无约定子目录）
```

| 能力 | 现状 | 目标 |
|------|------|------|
| 用户上传 | 无 | Session 上传 → `/workspace/inbox` |
| Agent 处理 | 仅对话中的文本/工具自建文件 | 读取 inbox，用 skills/tools 处理 PDF/MD 等 |
| Workspace 结构 | 仅 `/workspace` | 规范化子目录（见 §3） |
| 交付下载 | 无；文件随 Pod TTL 消失 | 浏览器下载 `/workspace/outputs/**` |

### 约束

- ACS NetworkPolicy：**Ingress deny-all** → 浏览器不能直连 Pod；必须经 **Gateway → K8s API exec/cp**。
- `session_id === sandbox_id`；Gateway 已有 JWT + `Sandbox.user_id` 归属校验与 `pods/exec` RBAC。
- 当前无 PVC：`/workspace` 为容器 ephemeral FS；TTL 到期文件消失（本阶段文档说明即可）。

---

## 2. 目标架构

```
Browser (Session 页)
  ├─ 上传按钮 → POST /api/gateway/sandboxes/{id}/files  (multipart → inbox/)
  ├─ Prompt（可附带「已上传文件列表」提示）→ Relay → Agent
  └─ Outputs 面板 → GET .../files?prefix=outputs
                   → GET .../files/content?path=outputs/...

Gateway
  ├─ 归属校验 (sandbox.user_id == JWT.sub)
  ├─ 路径白名单 + 防穿越
  └─ K8s exec/tar → Pod /workspace/{inbox|outputs|...}

ACS Pod /workspace
  ├─ inbox/     ← 用户上传
  ├─ outputs/   ← Agent 交付物（可下载）
  ├─ …（见 §3）
  └─ webuild agent：tools + skills 读写上述目录
```

### 成功标准

| # | 标准 |
|---|------|
| S1 | Sandbox Running 时可上传文件到 `inbox/`，列表可见 |
| S2 | Prompt 后 Agent 能 `read_file` / skills 处理上传的 PDF/MD 等，并在对话中反馈 |
| S3 | 启动时创建完整 Workspace 子目录 + `WORKSPACE.md` 约定 |
| S4 | 可列出并下载 `outputs/` 下文件；越权路径返回 400/403 |
| S5 | 非 owner 的 JWT 无法上传/下载他人 sandbox |

---

## 3. Workspace 目录规范（最佳实践）

在 `/workspace` 建立「摄入 → 处理 → 证据 → 交付」流水线，便于 Agent 管理文件、记忆、审计与跨文档一致性。

```text
/workspace/
  WORKSPACE.md          # 目录约定与 Agent 操作规范（只读导向）
  inbox/                # 用户上传（Gateway 写入；Agent 只读优先）
  sources/              # 从 inbox 规范化后的工作副本（Agent 可改名/拆分）
  work/                 # 中间草稿、临时分析、未定稿
  context/              # 会话上下文包：摘要、索引、引用片段
  memory/               # 本沙箱内跨轮次笔记（短记忆，非全局 ~/.webuild/memory）
  ground-truth/         # 已核实事实、引用出处、不可轻易改写的真值表
  audits/               # 跨文档一致性审计、差异与核对记录
  skills/               # 本会话/项目级 SKILL.md（可选，补充全局 skills）
  outputs/              # 最终交付物（报告、表格、幻灯片等）← 唯一默认可下载根
  .webuild/              # 可选项目配置（不对外暴露下载）
```

### 约定规则（写入 `WORKSPACE.md`）

1. **用户材料**一律先落 `inbox/`；处理前复制到 `sources/`，保留原始 inbox 不变。  
2. **最终给用户的文件**必须写到 `outputs/`（含子目录），文件名可读、无路径穿越。  
3. **可下载范围**：Gateway 默认仅允许 `outputs/`（可选只读回看 `inbox/`）。  
4. **记忆**：短结论写入 `memory/`；引用与证据写入 `ground-truth/`；审计写入 `audits/`。  
5. **Skills**：优先用镜像内置 skills；会话特供流程可放 `skills/<name>/SKILL.md`。

---

## 4. API 设计

基路径：`/api/gateway`（现有 Nginx 反代）。均需 `Authorization: Bearer <JWT>`。

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/sandboxes/{id}/files` | multipart 上传到 `inbox/`（`dest=inbox` 默认） |
| `GET` | `/sandboxes/{id}/files?prefix=outputs` | 列出相对路径、size、mtime |
| `GET` | `/sandboxes/{id}/files/content?path=outputs/foo.md` | 下载单文件流 |

### 限制

| 项 | 值 |
|----|-----|
| 单文件 | 32 MiB |
| 单次请求总大小 | 64 MiB |
| 单次文件数 | ≤ 20 |
| 上传目标 | `inbox`（本阶段） |
| 下载/列表根 | `outputs`（列表可 `prefix=outputs`；content path 必须在白名单下） |
| 文件名 | basename only；拒绝 `..`、`/`、NUL、空名 |

### 传输实现

`K8sClient`：

- `exec_in_pod(pod, argv, stdin=bytes|None) -> bytes`  
- `ensure_workspace_dirs(pod)` → `mkdir -p` 各子目录  
- `upload_to_pod(pod, dest_rel, filename, data)` → `tar -C /workspace/<dest> -xf -`  
- `list_dir(pod, rel_prefix)` → `find` + `stat`（JSON 行）  
- `download_from_pod(pod, rel_path)` → `tar -C /workspace -cf - <path>` 解出

异步包装：`asyncio.to_thread` 避免阻塞事件循环。

---

## 5. Web IDE

### Session 页 (`sessions/[id]/page.tsx`)

1. **上传**：输入框旁纸夹按钮；选文件后 `uploadSandboxFiles`；成功后在输入区上方显示已上传 chip；发送 prompt 时自动追加一段系统提示：

   ```text
   [Uploaded files in /workspace/inbox]
   - report.pdf
   - notes.md
   Please process these files using available tools/skills. Put final deliverables under /workspace/outputs/.
   ```

2. **Outputs 面板**：可折叠「Outputs」；轮询或手动刷新 `listSandboxFiles('outputs')`；每行提供 Download。

### 客户端 (`gateway-api.ts`)

`uploadSandboxFiles` / `listSandboxFiles` / `downloadSandboxFile`。

### i18n

中英：上传、Outputs、下载失败、沙箱未就绪等文案。

---

## 6. 分步实施清单

| 步骤 | 内容 | 产出 |
|------|------|------|
| **VII-0** | 本文档 | `docs/phase-vii-workspace-files-plan.md` | ✅ |
| **VII-1** | `sandbox-init.sh` 建目录 + `WORKSPACE.md` 模板 | 镜像/挂载脚本更新 | ✅ |
| **VII-2** | `k8s_client` exec/tar + `SandboxManager` 文件方法 + Gateway 路由 + models | 可 curl 的 API | ✅ |
| **VII-3** | Web IDE 上传 + Outputs 下载 + i18n | Session UX | ✅ |
| **VII-4** | Gateway 单测（路径穿越/归属）；本地 compose rebuild | 可验收 | ✅ |

### 非目标（本阶段不做）

- PVC 持久化 / 跨会话保留文件  
- Hub 远程本机 `put_files`  
- 任意路径下载全盘 `/workspace`  
- 沙箱镜像强制重建推送 ACR（本地 compose + 脚本变更；生产镜像另发）

---

## 7. 安全与运维

- 所有文件 API：JWT + ownership + sandbox `running`。  
- 路径：规范化后必须落在允许根下。  
- Exec：固定 argv，禁止把用户路径拼进 `bash -c`。  
- Nginx：`/api/gateway/` 提高 `client_max_body_size`（如 64m）。  
- TTL：UI 提示「沙箱到期后 outputs 不可恢复」。

---

## 8. 回滚

- L1：停用前端上传/Outputs 入口（feature flag 或回滚 web-ide 镜像）。  
- L2：Gateway 去掉 `/files` 路由，不影响 Session 聊天。  
- L3：旧沙箱无子目录时，`mkdir -p` 在首次 upload/list 时幂等创建。

---

## 9. 变更索引（计划）

```text
docs/phase-vii-workspace-files-plan.md
sandbox/scripts/sandbox-init.sh
sandbox/workspace/WORKSPACE.md          # 模板，init 时复制
services/gateway/src/k8s_client.py
services/gateway/src/sandbox_manager.py
services/gateway/src/main.py
services/gateway/src/models.py
services/gateway/src/pathutil.py        # 路径校验
services/gateway/tests/…
services/web-ide/src/lib/gateway-api.ts
services/web-ide/src/app/sessions/[id]/page.tsx
services/web-ide/src/lib/i18n.tsx
services/web-ide/src/components/…       # 可选：workspace-files 面板
deploy/nginx/conf.d/webuild.conf
```

---

*Phase VII — 以 Gateway 为唯一文件通道，Workspace 约定驱动 Agent 行为，Outputs 面向用户下载。*
