# WeBuild 本地部署实战指南：多沙箱协同完成复杂长程任务

> 作者：VitaCardia Group（本地 k3s 部署用户）
> 日期：2026-10-14
> 适用范围：WeBuild v0.2.102，本地 k3s + containerd 部署

---

## 一、WeBuild 能做什么

WeBuild 是一个 AI Agent 沙箱平台。每个沙箱是一个隔离的 Linux 容器，内置一个 AI Agent（当前模型 qwen3.7-max），拥有完整工具链：

| 能力 | 工具 | 说明 |
|------|------|------|
| 网络搜索 | `web_search` | 实时检索互联网信息，交叉验证事实 |
| 终端命令 | `run_terminal_command` | 在沙箱内执行任意 shell 命令 |
| 文件读写 | `write` / `read_file` / `search_replace` | 生成 HTML 报告并迭代修改 |
| 任务管理 | `todo_write` | Agent 自组织任务计划 |
| 子代理 | `spawn_subagent` | 并行处理子任务（注意重复调用风险） |

**核心优势**：Agent 不是简单的对话式 AI——它是一个有手有脚的自主执行者，能搜索、编程、写文件、运行命令，完成需要数十步工具调用的复杂任务。

---

## 二、多沙箱协同架构

单个沙箱可以完成独立任务（如一次性报告生成）。但对于需要**质量保障**的生产级任务，单沙箱有致命缺陷：Agent 审核自己的作品时，会带着写作时的偏见和记忆，无法发现自身错误。

### 2.1 Writer + Reviewer 双沙箱模式

这是我们经过大量实践验证的最佳架构：

```
          ┌──────────────────────────────────┐
          │      Coordinator（本地 Node.js）  │
          │   管理生命周期、传递数据、解析结论  │
          └──────┬───────────────┬───────────┘
                 │               │
    ┌────────────▼─────┐  ┌─────▼─────────────┐
    │   Writer 沙箱     │  │  Reviewer 沙箱     │
    │  持久，跨轮次     │  │  每轮新建，零上下文 │
    │                   │  │                    │
    │  搜索→写→改→输出  │  │  阅读→验证→打分    │
    └───────────────────┘  └────────────────────┘
```

**三个角色分工**：

| 角色 | 载体 | 职责 | 上下文 |
|------|------|------|--------|
| Coordinator | 本地 Node.js | 编排循环、传递草稿、解析审核结论 | 全局状态 |
| Writer | 沙箱 A（持久） | 搜索数据、撰写 HTML、按反馈修改 | 跨轮次累积 |
| Reviewer | 沙箱 B/C/D…（每轮新建） | 独立审计、web_search 核实、评分 | **零上下文** |

### 2.2 为什么 Reviewer 必须每轮新建

这是整个架构中最关键的设计决策。Reviewer 沙箱**每轮创建全新实例**，确保：

1. **独立性**：不知道 Writer 写了什么、搜了什么、做了哪些取舍
2. **零偏见**：不会"因为看到 Writer 做了大量搜索就倾向给高分"
3. **严格验证**：必须用自己的 `web_search` 重新核实每一个事实声明
4. **防共谋**：Writer 和 Reviewer 之间没有共享状态，只有 Coordinator 中转

### 2.3 循环流程

```
R1: Writer 写初稿 → Coordinator 下载 → Reviewer 审核 → 不通过（72分）
     ↓ 反馈：3 个 Critical + 5 个需修改项
R2: Writer 只改失败项 → Coordinator 下载 → 新 Reviewer 审核 → 通过（85分）✅
     ↓
输出终稿 + 清理审核痕迹 + 分发
```

**退出条件**（满足任一即停）：
- 审核通过（≥80 分且零 Critical）→ 输出终稿
- 轮次用完（默认 3 轮）→ 输出当前最佳版本，标记 `-unverified`

---

## 三、提示词工程：如何与 Agent 高效协作

### 3.1 提示词结构设计

一个生产级提示词包含以下结构：

```markdown
# 任务标题与元数据

## 0. 循环规则
（最多 N 轮，通过/不通过的处理方式）

## 1. 研究对象与元数据
（目标公司/主题、时间窗口、重点地区等）

## 2. 写作者要回答的问题
### 必须覆盖的分析维度
### 种子线索
（给 Writer 的检索起点）

## 3. 草稿要求
（HTML 格式、CSS 风格、字数范围、引用规范）

<!-- WRITER_PROMPT_END -->
<!-- REVIEWER_PROMPT_START -->

## 4. 独立审核
### 强制数据抽样验证协议
### 评分标准
### 通过/不通过判定
```

### 3.2 Writer 提示词的关键技巧

1. **给种子线索**：提供具体搜索词（如"瑛泰医疗 2025年度业绩公告 港交所"），比泛泛要求"搜索相关信息"效果好 10 倍
2. **指定数据密集度**：明确要求"每个分析维度至少 3 个具体数据点"，否则 Writer 倾向于写空洞概述
3. **禁止编造**：明确写"禁止编造交易金额、融资数据、估值"，Agent 会严格遵守
4. **指定 HTML 风格**：内联 CSS，不依赖外部字体，确保报告可直接打开
5. **控制字数**：6000–10000 字中文是最佳区间；太短不够深入，太长 Agent 会丢上下文

### 3.3 Reviewer 提示词的关键技巧

1. **强制抽样验证**：要求"从草稿中抽取至少 8 条具体交易事件，逐条用 web_search 核实"
2. **Critical 失败列表**：明确列出"任何一项 = 直接不通过"的错误类型
3. **分数上限约束**：如"如果数据抽样有未通过项，引用与 HTML 项不得超过 14/20"——防止格式完美但事实错误
4. **输出格式固定**：要求"轮次；数据抽样验证日志；总分；通过/不通过；Critical 列表；应修改项"——方便 Coordinator 解析

---

## 四、实战运行经验

### 4.1 性能数据（VitaCardia 实测）

| 指标 | Writer（R1 初稿） | Reviewer（单轮） | 总耗时（首轮通过） |
|------|-------------------|------------------|-------------------|
| 工具调用数 | 30–50 次 | 20–30 次 | 50–80 次 |
| web_search 次数 | 15–20 次 | 15–25 次 | 30–45 次 |
| 耗时 | 10–15 分钟 | 10–15 分钟 | 25–35 分钟 |
| Token 消耗 | ~200K–500K | ~150K–300K | ~350K–800K |

**首轮通过率**：我们的 12 赛道 FTM 报告批量生成中，11/12 首轮通过（92%），平均 86 分。

### 4.2 沙箱生命周期管理

- **硬过期**：每个沙箱有 1 小时硬过期（`expires_at = created_at + 1h`），超时必须重建
- **Pod 失败**：健康沙箱不会提前终止；提前死亡一定是 Pod 故障（通常是 ImagePullBackOff）
- **就绪检查三层**：DB `status=running` → K8s `pod_phase=Running` → Agent 启动（~15s）——**必须全部满足**
- **WebSocket 断开**：沙箱终止时 WS 静默关闭（code 1006/1011），必须监听 `close`/`error` 事件

### 4.3 常见问题与解决方案

| 问题 | 现象 | 解决方案 |
|------|------|----------|
| DashScope 401 | `invalid_api_key` | 检查 API Key 与 Base URL 是否匹配（Token Plan key 只能用于 Token Plan 端点） |
| WebSocket 1008 | `Policy Violation` | `RELAY_INTERNAL_TOKEN` 不一致，重启所有 Pod |
| Writer 重复循环 | DashScope 报 `Repetitive tool calls` | 避免 `spawn_subagent` + 重复轮询，改用单沙箱模式 |
| 审核 429 | `insufficient_quota` | DashScope 日配额耗尽，等次日重置（每天重置，非每月） |
| 草稿下载失败 | `Sandbox is not running` | 沙箱已终止，文件不可恢复，必须重新生成 |
| Reviewer 反馈 `[object Object]` | Writer 无法理解修改指令 | Coordinator 需 JSON 序列化 Reviewer 结构化反馈 |

### 4.4 批量生成策略

**推荐节奏**：每天最多 2–3 份完整报告生成（避免 DashScope 日配额耗尽）。

**串行 vs 并行**：
- **串行**（推荐）：逐个生成，前一个完成/失败再启动下一个。稳定，易排查。
- **并行**：多个 Writer 同时跑，速度快但 token 消耗峰值高，容易触发 429。

**批量脚本模式**：
```javascript
// 遍历配置 → 逐个 execSync 调用生成脚本 → 汇总结果
for (const sector of sectors) {
  execSync(`node generate-report.mjs ${sector.id} --rounds 3`, { timeout: 900000 })
}
```

---

## 五、本地 k3s 部署运维要点

### 5.1 架构组件

```
Nginx (443)
  ├─ Auth Service (:8001)    — JWT 登录
  ├─ Relay Server (:8002)    — WS 桥接（browser ↔ agent）
  ├─ Gateway (:8004)         — K8s Pod 生命周期管理
  ├─ Hub Broker (:8003)      — 工具路由
  └─ Web-IDE                 — 浏览器开发环境
```

### 5.2 Secret 管理

所有凭据存储在 k3s Secret `webuild-env`（vitacardia namespace）中：

| Key | 用途 |
|-----|------|
| `JWT_SECRET` | JWT 签名密钥（auth + gateway 必须一致） |
| `DASHSCOPE_API_KEY` | 模型 API 密钥（注入到 sandbox pod） |
| `DASHSCOPE_BASE_URL` | 模型 API 端点（Token Plan 需对应端点） |
| `DB_PASSWORD` | PostgreSQL 密码 |
| `RELAY_INTERNAL_TOKEN` | relay ↔ agent 认证令牌 |

**⚠️ 修改 secret 后必须**：
1. `rollout restart` 所有依赖的 deployment（gateway、auth、relay、hub、nginx、web-ide）
2. 如果修改了 `DB_PASSWORD`，还需在 PostgreSQL 中执行 `ALTER USER webuild PASSWORD '<new>'`
3. 如果修改了 `DASHSCOPE_BASE_URL`，需重编译 sandbox agent 的 Rust binary（base_url 是编译时嵌入）

### 5.3 镜像管理

k3s 使用 **containerd**（非 Docker）。本地构建的镜像必须手动同步：

```bash
docker build -t webuild-sandbox:local .
docker save webuild-sandbox:local | k3s ctr images import -
```

否则 Pod 会 `ImagePullBackOff`（尝试从 docker.io 拉取，DaoCloud 镜像返回 403）。

---

## 六、总结：最大化 WeBuild 价值的核心原则

### 原则一：让 AI 做 AI 擅长的事

WeBuild Agent 擅长**信息密集型任务**：大量搜索、交叉验证、综合撰写、迭代修改。不适合需要确定性逻辑的任务（如数学计算、代码编译）。

### 原则二：分治优于全能

与其让一个 Agent 写+审，不如拆成 Writer（写）+ Reviewer（审）。**Reviewer 的零上下文设计是质量保障的基石**——这模拟了人类审稿中"独立审稿人"的角色。

### 原则三：提示词是产品

好的提示词 = 好的产品规格。它定义了输入（种子线索）、过程（分析维度）、输出（HTML 格式）和质量标准（评分体系）。投入时间打磨提示词的 ROI 远高于调参。

### 原则四：可观测性

每轮记录：工具调用数、搜索次数、耗时、token 消耗、审核分数。这些数据帮助优化提示词、判断模型能力边界、规划配额使用。

### 原则五：基础设施即产品

WeBuild 的本地部署不是"装好就不管"——它是需要持续运维的基础设施。Secret 轮换、镜像更新、Pod 健康检查、API 配额监控都是日常运维的一部分。建立 AgentPost 通信渠道（与 WeBuild agent 互发邮件）是高效的问题报告和修复流程。

---

## 附录 A：VitaCardia 报告生成体系总览

| 系统 | 生成器 | 提示词 | 输出 | 数量 |
|------|--------|--------|------|------|
| 赛道深度研究 | `generate-report.mjs` | `report-prompts.json` | `public/reports/` | 12 赛道 |
| 公司追踪仪表盘 | `generate-company.mjs` | `company-prompts.json` | `public/company/` | 22 公司 |
| 专题深度研究 | `generate-topic.mjs` | `prompts/topics/*.md` | `public/topics/` | 按需 |
| 人物追踪 | `generate-person.mjs` | `prompts/following-the-people/*.md` | `public/following-the-people/` | 按需 |
| 资本流向分析 | `generate-money.mjs` | `prompts/following-the-money/*.md` | `public/following-the-money/` | 12 赛道 + 公司级 |
| Watchlist 雷达 | `watchlist/*/run-radar.mjs` | `watchlist/*/radar-prompt.txt` | `watchlist/*/output/` | 2 公司 |

**全部使用 Writer + Reviewer 多沙箱架构**，除 Watchlist 雷达（单沙箱，无审核）。

## 附录 B：审核评分体系

| 维度 | 权重 | 说明 |
|------|------|------|
| 事实与数据准确性 | 40 分 | 交易金额、公司名、时间、数据是否正确 |
| 分析完整度 | 20–25 分 | 是否覆盖所有要求的分析维度 |
| 证据与来源 | 20 分 | 是否标注数据来源、交叉验证 |
| HTML 与引用 | 15–20 分 | 格式规范、引用一文献一编号 |

**通过线：80 分 + 零 Critical 失败**
