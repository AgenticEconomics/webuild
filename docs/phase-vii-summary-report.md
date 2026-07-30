# WeBuild Phase VII 阶段性开发总结报告

> **阶段**: Phase VII — Session 文件上传、Workspace 目录规范、Outputs 下载  
> **日期**: 2026-07-30  
> **状态**: **VII-0–VII-4 已交付**；Sandbox 镜像已推 ACR，Gateway 已 pin `v0.7.0`  
> **主提交**: `e8efba9`（功能）；`eac3061`（部署 tag pin）  
> **版本标签**: `v0.7.0`  
> **前置**: Phase V 全量 Agent；Phase VI Skills；v0.6.7 用户会话隔离  
> **相关文档**: [`phase-vii-workspace-files-plan.md`](./phase-vii-workspace-files-plan.md)

---

## 1. 阶段目标与结论

### 1.1 目标

打通「用户材料 → 沙箱 Agent 处理 → 交付物回传」闭环：

1. 在 Session 中向对应 ACS Sandbox 的 `/workspace/inbox` 上传文件；  
2. 在 Pod 内建立规范化 Workspace 子目录，约束 Agent 的摄入 / 处理 / 证据 / 交付路径；  
3. 用户可从浏览器列出并下载 `/workspace/outputs/**` 最终交付物。

约束不变：ACS NetworkPolicy Ingress deny-all，浏览器不能直连 Pod；文件通道必须经 **Gateway → K8s API exec/tar**。

### 1.2 结论（一句话）

**已达成**：Gateway 文件 API + 规范 Workspace + Session 上传/Outputs 面板上线；生产镜像与 compose 默认 tag 对齐 `v0.7.0`。  
**本阶段不做**：PVC 持久化、任意路径下载全盘、Hub 本机 `put_files`。

| 成功标准 | 结果 |
|----------|------|
| S1 Running 时可上传到 `inbox/`，列表可见 | ✅ API + UI |
| S2 Prompt 后 Agent 可用 tools/skills 处理上传文件 | ✅ 上传后自动注入 inbox 提示；依赖 Phase V/VI 能力 |
| S3 启动创建完整子目录 + `WORKSPACE.md` | ✅ `sandbox-init.sh` + 镜像内模板 |
| S4 可列出/下载 `outputs/`；越权路径 400 | ✅ pathutil 白名单 + 单测 |
| S5 非 owner JWT 无法读写他人 sandbox | ✅ 复用既有 ownership 校验 |

---

## 2. 架构变化

```
Before (Phase V/VI)
  Browser → Relay ↔ ACS Pod: webuild agent headless
                         └─ /workspace（扁平，无约定；无上传/下载通道）

After (Phase VII)
  Browser (Session)
    ├─ 上传 → POST /api/gateway/sandboxes/{id}/files  → inbox/
    ├─ Prompt（可附带已上传文件提示）→ Relay → Agent
    └─ Outputs 面板 → GET …/files?prefix=outputs
                     → GET …/files/content?path=outputs/…

  Gateway
    ├─ JWT + sandbox.user_id 归属
    ├─ pathutil 路径白名单 / 防穿越
    └─ K8s exec + tar → Pod /workspace/{inbox|outputs|…}

  ACS Pod /workspace
    ├─ inbox / sources / work / context / memory
    ├─ ground-truth / audits / skills / outputs / .webuild
    ├─ WORKSPACE.md（约定与 Agent 规则）
    └─ webuild agent：tools + skills 读写上述目录
```

**关键设计决策**：不以浏览器直连或 NodePort 暴露文件服务，而是把 Gateway 作为唯一文件通道，与现有沙箱安全模型一致。

---

## 3. 交付清单

### 3.1 按实施步骤

| 步骤 | 内容 | 状态 |
|------|------|------|
| **VII-0** | 计划文档 `docs/phase-vii-workspace-files-plan.md` | ✅ |
| **VII-1** | `sandbox-init.sh` 建目录 + `WORKSPACE.md` 模板进镜像 | ✅ |
| **VII-2** | `pathutil` + `k8s_client` exec/tar + `SandboxManager` + Gateway 路由 | ✅ |
| **VII-3** | Web IDE 纸夹上传 + Outputs 面板 + i18n | ✅ |
| **VII-4** | `test_pathutil`；compose rebuild；ACR 推送；tag pin | ✅ |

### 3.2 模块明细

| 模块 | 变更要点 |
|------|----------|
| **Sandbox 镜像** | 复制 `WORKSPACE.md` 到 `/opt/sandbox/`；init 时 `mkdir -p` 九个子目录并拷贝模板；clone 仓库时忽略布局目录，避免误判「已有项目」 |
| **Gateway `pathutil`** | 上传仅 `inbox`；列表/下载根为 `outputs`（及只读回看 `inbox`）；basename 净化、拒绝 `..` / NUL / 穿越 |
| **Gateway `k8s_client`** | `exec_in_pod`、`ensure_workspace_layout`、`upload_file_to_pod`（tar stdin）、`list_files_in_pod`（find）、`download_file_from_pod`（tar 抽出） |
| **Gateway `sandbox_manager`** | 限额：单文件 32 MiB、单次总 64 MiB、≤20 文件；`asyncio.to_thread` 包装同步 K8s 调用 |
| **Gateway API** | `POST/GET /sandboxes/{id}/files`、`GET …/files/content`；要求 sandbox `running` + owner |
| **Web IDE** | Session 纸夹上传、已上传 chip、prompt 追加 inbox 提示；`WorkspaceOutputsPanel` 列表/刷新/下载 |
| **Nginx** | `/api/gateway/` `client_max_body_size 64m` |
| **Deploy** | 默认 `SANDBOX_IMAGE=…/sandbox:v0.7.0`（`.env` / `.env.example` / compose） |

### 3.3 Workspace 目录规范（产品约定）

| 路径 | 用途 |
|------|------|
| `inbox/` | 用户上传（Gateway 写入；Agent 宜只读，处理前复制到 sources） |
| `sources/` | 规范化工作副本 |
| `work/` | 中间草稿 |
| `context/` | 会话上下文包 |
| `memory/` | 本沙箱短记忆 |
| `ground-truth/` | 已核实事实与引用 |
| `audits/` | 跨文档一致性审计 |
| `skills/` | 会话级 SKILL.md（可选） |
| `outputs/` | **最终交付物**（默认可下载根） |
| `.webuild/` | 项目配置（不对外暴露下载） |

规则写入 Pod 内 `WORKSPACE.md`，引导 Agent 把交付物落到 `outputs/`，并提示 ephemeral TTL。

### 3.4 API 一览

基路径：`/api/gateway`（经 Nginx）。均需 `Authorization: Bearer <JWT>`。

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/sandboxes/{id}/files` | multipart → `inbox/`（`dest=inbox`） |
| `GET` | `/sandboxes/{id}/files?prefix=outputs` | 列表 path / size / mtime |
| `GET` | `/sandboxes/{id}/files/content?path=outputs/…` | 单文件下载流 |

---

## 4. 安全设计

| 层 | 措施 |
|----|------|
| 身份 | JWT Bearer |
| 归属 | `sandbox.user_id == JWT.sub`（与 v0.6.7 会话隔离一致） |
| 状态 | 仅 `running` 沙箱允许文件操作 |
| 路径 | 规范化后必须落在允许根；禁止穿越与任意 `/workspace` 全盘下载 |
| Exec | 固定 argv + tar/find；避免用户路径拼进 `bash -c` |
| 体量 | 单文件 / 总大小 / 文件数硬限制；Nginx 64 m 与之对齐 |
| 生命周期 | 无 PVC；TTL 到期文件不可恢复；UI/文档提示先下载 |

单测覆盖：`services/gateway/tests/test_pathutil.py`（basename、上传 dest、列表 prefix、下载路径穿越）。

---

## 5. 发布与镜像核查（2026-07-30）

### 5.1 Git

| 项 | 值 |
|----|-----|
| 功能提交 | `e8efba9` — Phase VII: sandbox file upload, workspace layout, and outputs download |
| 部署提交 | `eac3061` — chore(deploy): pin sandbox image default tag to v0.7.0 |
| Tag | `v0.7.0`（已推 `origin`） |
| 分支 | `main`（`release-0.6.6` 冻结 Phase I–VI） |

变更规模（功能提交）：**16 files，+1106 / −35**。

### 5.2 ACR Sandbox 镜像

```text
Registry: xingu-aliyun-acr-registry.cn-hangzhou.cr.aliyuncs.com/webuild/sandbox
Tags:     v0.7.0, e8efba9, phase-vii, latest
Digest:   sha256:ff18f03a74032579e5265486f202a8f20d58166aa3ae89a44718b8b7ae57e680
```

镜像内核查：

| 检查项 | 结果 |
|--------|------|
| `/opt/sandbox/WORKSPACE.md` | ✅ |
| `/opt/sandbox/sandbox-init.sh` 含 inbox/outputs 等 mkdir | ✅ |
| ENTRYPOINT | `/opt/sandbox/sandbox-init.sh` |

### 5.3 运行时 Gateway

| 检查项 | 结果 |
|--------|------|
| `SANDBOX_IMAGE` | `…/webuild/sandbox:v0.7.0`（曾误残留 `:latest`，已 force-recreate 纠正） |
| Health | `GET :8004/health` → `{"status":"ok","service":"gateway"}` |
| OpenAPI | `/sandboxes/{sandbox_id}/files`、`…/files/content` 已注册 |

**运维注意**：已存在的 ACS Pod 不会自动换镜像；需**新建 Session/Sandbox** 才会拉 `v0.7.0`。若出现 `ImagePullBackOff`，继续用既有 ACR pull secret 刷新 cron。

---

## 6. Web IDE 用户体验

1. **上传**：Session 输入区旁纸夹；选文件后调用 `uploadSandboxFiles`；成功显示 chip。  
2. **Prompt 增强**：若有本轮上传，自动追加：

   ```text
   [Uploaded files in /workspace/inbox — please process with tools/skills;
    put final deliverables under /workspace/outputs/.]
   - <filename>…
   ```

3. **Outputs 面板**：可折叠列表；手动刷新；行内 Download；依赖沙箱 Running。  
4. **i18n**：中英上传 / Outputs / 失败与未就绪文案。

---

## 7. 验收与已知边界

### 7.1 已验证

- 路径安全单测通过  
- Gateway 健康与文件路由注册  
- ACR `v0.7.0` 内容与 digest 可拉取  
- Compose / `.env` 默认 tag 与运行时 `printenv SANDBOX_IMAGE` 一致  

### 7.2 边界与非目标（明确不做）

| 项 | 说明 |
|----|------|
| 无 PVC | 文件随 Pod TTL 消失，不可跨会话保留 |
| 下载范围 | 默认 `outputs/`（及 `inbox` 回看）；不可下 `memory/`、`work/` 等 |
| Hub put_files | 未做；本机 Leader 文件通道属后续阶段 |
| 全路径任意下载 | 明确拒绝，降低逃逸与泄密面 |

### 7.3 端到端业务路径（建议回归）

1. 白名单用户登录 → 新建 Session（起 ACS Running）  
2. 上传 PDF/MD → chip 可见  
3. Prompt「处理 inbox 并输出报告」→ Agent 工具读写 → 落盘 `outputs/`  
4. Outputs 面板刷新并下载  
5. 用另一账号 JWT 访问同一 sandbox_id → 应 403  

---

## 8. 回滚

| 级别 | 动作 |
|------|------|
| L1 | 回滚 web-ide：隐藏上传/Outputs（或回滚前端镜像） |
| L2 | Gateway 去掉 `/files` 路由；Session 聊天不受影响 |
| L3 | `SANDBOX_IMAGE` 回退旧 tag/digest；旧 Pod 无子目录时，首次 upload/list 仍可幂等 `mkdir -p` |

---

## 9. 下一阶段建议（优先级）

1. **E2E 自动化**：上传 → Agent 处理 → outputs 下载的 CI/冒烟（含 ownership 负例）  
2. **PVC 或对象存储**：可选持久化 outputs，解决 TTL 后不可恢复  
3. **Session 生命周期**：删 Session 联动 terminate sandbox；UI 明确剩余 TTL  
4. **更大文件**：分片上传或预签名对象存储，突破单请求 64 MiB  
5. **Agent 侧强化**：skills 默认把交付路径写到 `outputs/`，并在结束语中回传确切路径  
6. **监控**：文件 API 延迟/失败率、exec 超时、单沙箱磁盘占用  

---

## 10. 变更索引

```text
docs/phase-vii-workspace-files-plan.md
docs/phase-vii-summary-report.md          # 本报告
sandbox/Dockerfile
sandbox/scripts/sandbox-init.sh
sandbox/workspace/WORKSPACE.md
services/gateway/src/pathutil.py
services/gateway/src/k8s_client.py
services/gateway/src/sandbox_manager.py
services/gateway/src/main.py
services/gateway/src/models.py
services/gateway/tests/test_pathutil.py
services/web-ide/src/lib/gateway-api.ts
services/web-ide/src/app/sessions/[id]/page.tsx
services/web-ide/src/components/workspace-outputs-panel.tsx
services/web-ide/src/lib/i18n.tsx
deploy/nginx/conf.d/webuild.conf
deploy/docker-compose.yml
deploy/docker-compose.override.yml
deploy/.env.example
```

---

## 11. 总结

Phase VII 补齐了云沙箱场景下「材料进、结果出」的产品缺口：在 Ingress 全拒的 ACS 模型下，以 Gateway 为唯一安全文件通道；以 `WORKSPACE.md` 约定驱动 Agent 行为；以 `outputs/` 面向用户交付。版本 **`v0.7.0`** 已落盘、推送 ACR，并完成 Gateway 运行时 tag 对齐。后续重点是持久化策略、E2E 自动化与 Session/Sandbox 生命周期联动，而非再改文件通道的基本形态。

---

*报告生成于 Phase VII 功能合入、`v0.7.0` 镜像推送，以及 Gateway `SANDBOX_IMAGE` 纠正为 `:v0.7.0` 核查之后。*
