# Phase VI — 导入 AgenticEconomics/skills，丰富 WeBuild Skill 能力

> **状态**: 已实现（vendor + ensure + sandbox COPY）  
> **目标**: 将 [AgenticEconomics/skills](https://github.com/AgenticEconomics/skills)（fork 自 anthropics/skills）中的 skills 导入 WeBuild，使本地 CLI 与 ACS 沙箱 Agent 均可发现并执行这些技能。  
> **前置**: Phase V 沙箱完整 Agent 已可用。

---

## 1. 背景

### 上游仓库

| 项 | 内容 |
|----|------|
| 来源 | https://github.com/AgenticEconomics/skills |
| 布局 | `skills/<name>/SKILL.md` + `.claude-plugin/marketplace.json` |
| 数量 | 17 个 skill |
| 分组 | `document-skills`（docx/pdf/pptx/xlsx）、`example-skills`（设计/MCP/测试等）、`claude-api` |

### WeBuild 现有机制（可复用）

| 机制 | 说明 |
|------|------|
| Agent Skills 格式 | 已支持 `SKILL.md` + YAML frontmatter |
| 内置 skill | `~/.webuild/skills/`（`help` / `create-skill` / `code-review` / `imagine` / `check-work`） |
| Plugin skill | `~/.webuild/plugins/`、marketplace 安装 |
| Marketplace 扫描 | 支持 `.webuild-plugin/marketplace.json` 与 `.claude-plugin/marketplace.json` |
| **`default-skills/` 自动安装** | 扫描到 marketplace 根下 `default-skills/` 时，会话启动会自动 install |

上游 Claude marketplace 使用 `"source": "./"` + `skills: [...]` 数组；**WeBuild 安装器按「插件目录」拷贝，不解析该 skills 数组**。因此不能直接 `marketplace add` 上游仓库 URL，必须先改成 WeBuild 兼容布局。

### 许可注意

| Skill | 许可 |
|-------|------|
| 多数 example / claude-api | Apache 2.0 |
| **docx / pdf / pptx / xlsx** | Anthropic 专有（source-available）；须保留 LICENSE.txt 并在 NOTICE 中声明 |

历史上 WeBuild 曾将 `docx`/`pptx`/`xlsx` 从 bundled 中移除（见 `LEGACY_BUNDLED_SKILL_NAMES`）。Phase VI **不以 bundled `include_str` 方式塞回二进制**，改为 **marketplace / plugin** 交付，避免与旧清理逻辑冲突，并保留完整资源文件（脚本、字体等）。

---

## 2. 目标

1. **全部 17 个 skill** 可在 WeBuild 中被发现（`/skills`、prompt skill list、slash 触发）。
2. **默认可用**：首次启动后无需用户手动 `plugin install`（通过 `default-skills` 自动安装）。
3. **沙箱可用**：ACS 镜像内预置同一套 marketplace，headless agent 启动即可用。
4. **可溯源**：记录上游 commit、NOTICE、更新方式。
5. **不破坏** 现有 5 个 bundled skill；`skill-creator` 与 `create-skill` 可并存。

### 非目标（本阶段不做）

- 重写 skill 正文为 xAI/DashScope 专用（保留上游内容；`claude-api` 仅在用户涉及 Claude/Anthropic 时触发）。
- 把大型资源（如 canvas 字体 ~5.5MB）编入 Rust 二进制。
- 为每个 skill 写独立 E2E（仅做发现/安装冒烟）。
- 自动安装上游 Python/Node 运行时依赖到所有环境（沙箱可补常用包；本地按需）。

---

## 3. 目标架构

```
third_party/agent-skills/                    ← 仓库内 vendored（WeBuild 布局）
  SOURCE.md / NOTICE.md / README.md
  .webuild-plugin/marketplace.json
  default-skills/
    algorithmic-art/SKILL.md + …
    brand-guidelines/…
    …（全部 17 个）

运行时：
  resolve root → /opt/webuild/agent-skills 或 third_party/… 或 WEBUILD_AGENT_SKILLS_ROOT
       ↓ sync（版本 marker）
  ~/.webuild/marketplaces/agent-skills/
       ↓ [[marketplace.sources]] path=…
       ↓ auto_install_defaults / 启动时 ensure install
  ~/.webuild/plugins/<repo_key>/   （plugin.json skills=./）
       ↓ plugin discovery
  Agent prompt + /skills UI
```

沙箱镜像额外：

```
Dockerfile COPY third_party/agent-skills → /opt/webuild/agent-skills
sandbox-init 可依赖 webuild 启动时的 ensure_*（无需重复逻辑）
```

---

## 4. 实施方案（分步）

### VI-1 编写本计划并冻结范围

- 导入全部 17 skill；布局改为 `default-skills/<name>/`。
- 交付载体：vendored marketplace + 启动同步/自动安装 + 沙箱 COPY。

### VI-2 Vendor 上游 skills

```bash
# 从固定 commit 拷贝到 third_party/agent-skills/default-skills/
# 保留各 skill 的 LICENSE.txt / 脚本 / 字体 / 参考文档
# 写入 SOURCE.md（URL + commit SHA + 日期）
# 写入 NOTICE.md（Apache + Anthropic proprietary 声明）
# 写入 .webuild-plugin/marketplace.json
```

`marketplace.json` 示例：

```json
{
  "name": "webuild-agent-skills",
  "owner": { "name": "WeBuild" },
  "metadata": {
    "description": "Agent skills imported from AgenticEconomics/skills (Anthropic examples)",
    "version": "1.0.0",
    "upstream": "https://github.com/AgenticEconomics/skills"
  },
  "plugins": []
}
```

（`default-skills/` 由 scanner 虚拟成插件，无需列入 `plugins`。）

### VI-3 运行时接入（CLI）

在 `xai-webuild-shell` 增加 `agent_skills`（或扩展 `builtin` / `extensions::marketplace`）：

1. **`resolve_agent_skills_root()`** 查找顺序：
   - `WEBUILD_AGENT_SKILLS_ROOT`
   - `/opt/webuild/agent-skills`（沙箱约定路径）
   - 编译期 `CARGO_MANIFEST_DIR`/仓库相对 `third_party/agent-skills`（本地开发）
   - `~/.webuild/marketplaces/agent-skills`（已同步过则复用）

2. **`ensure_agent_skills_marketplace(webuild_home)`**（`init_process` 调用，默认开启）：
   - 将 vendor 树同步到 `~/.webuild/marketplaces/agent-skills/`（用 `SOURCE.md` commit 或目录 mtime/version 文件做 marker，避免每次全量拷贝）
   - 向 `config.toml` 追加：

     ```toml
     [[marketplace.sources]]
     name = "WeBuild Agent Skills"
     path = "~/.webuild/marketplaces/agent-skills"
     ```

   - 幂等；用户删除该 source 后可用 sticky flag 避免反复注入（可选，与 official marketplace 类似）。

3. **确保插件已安装**：
   - 复用 `installer::install_from_marketplace(..., "default-skills", ...)`  
   - 或依赖现有会话路径 `auto_install_defaults`；**启动时主动 install 一次**更稳（headless 沙箱不一定走 marketplace UI 刷新）。

### VI-4 沙箱镜像

- `sandbox/Dockerfile`：构建上下文内 `COPY agent-skills /opt/webuild/agent-skills`（CI/`README` 先从 `third_party/agent-skills` 拷贝）
- 可选：在 `requirements.txt` / apt 中补充文档类常用依赖（`pypdf`、`openpyxl` 等），降低首次用 pdf/xlsx skill 时的摩擦
- `sandbox-init.sh`：无需改启动命令；依赖 agent init 的 ensure

### VI-5 文档与验证

- 用户指南短节：`docs` 或 pager user-guide 指向 Phase VI / third_party README
- 冒烟：
  1. `ensure_*` 后 `~/.webuild/marketplaces/agent-skills/default-skills/*/SKILL.md` 存在
  2. install registry 含 default-skills；plugin 下可见 17 个 skill
  3. 单元测试：resolve path + sync idempotent + marketplace scan 含 default-skills

### VI-6 更新策略

- `third_party/agent-skills/SOURCE.md` 记录 upstream SHA
- 升级：重新 rsync upstream `skills/*` → `default-skills/*`，更新 SHA，bump marketplace metadata.version，用户侧靠 marker 触发再同步

---

## 5. Skill 清单（导入）

| Skill | 分组 | 许可 | 备注 |
|-------|------|------|------|
| algorithmic-art | example | Apache-2.0 | p5.js |
| brand-guidelines | example | Apache-2.0 | |
| canvas-design | example | Apache-2.0 | 含字体资源 |
| claude-api | claude-api | Apache-2.0 | Claude/Anthropic 专用；保留 |
| doc-coauthoring | example | Apache-2.0 | |
| docx | document | Proprietary | |
| frontend-design | example | Apache-2.0 | |
| internal-comms | example | Apache-2.0 | |
| mcp-builder | example | Apache-2.0 | |
| pdf | document | Proprietary | |
| pptx | document | Proprietary | |
| skill-creator | example | Apache-2.0 | 与 bundled `create-skill` 并存 |
| slack-gif-creator | example | Apache-2.0 | |
| theme-factory | example | Apache-2.0 | |
| web-artifacts-builder | example | Apache-2.0 | |
| webapp-testing | example | Apache-2.0 | Playwright |
| xlsx | document | Proprietary | |

---

## 6. 验收标准

- [x] `third_party/agent-skills/default-skills/` 含 17 个带 `SKILL.md` 的目录  
- [x] NOTICE / SOURCE / marketplace.json 齐全  
- [x] 本地启动 webuild 后，plugin 安装目录或 skills 列表可见上述 skill（`ensure_agent_skills` + installer 修复）  
- [x] 沙箱镜像含 `/opt/webuild/agent-skills`（Dockerfile + CI 拷贝），headless 启动后同样可见  
- [x] 现有 bundled skill 行为不变；`docx` 等不以旧 bundled 路径复活（走 plugin）  
- [x] 相关单测通过（`agent_skills::*`、marketplace installer）  

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 专有文档 skill 许可 | NOTICE + 保留 LICENSE；不以「WeBuild 自有」名义宣称 |
| 仓库体积 +12MB（字体） | 可接受；若过大再拆 `canvas-fonts` 为可选 |
| 上游布局不兼容 | Vendor 时改为 `default-skills/` |
| 沙箱缺 Python 包 | 镜像补常用依赖；skill 内仍可提示 pip install |
| 与 `create-skill` 名称混淆 | 保留两者；描述不同 |

---

## 8. 实现顺序（执行清单）

1. 落盘本计划  
2. Vendor 17 skills + metadata  
3. 实现 `ensure_agent_skills_marketplace` + init 挂钩  
4. 更新 sandbox Dockerfile（+ 可选 deps）  
5. 测试与冒烟  
6. （用户要求时）commit / 重建沙箱镜像  

---

## 9. 参考

- 上游：https://github.com/AgenticEconomics/skills  
- Agent Skills 标准：https://agentskills.io  
- WeBuild：`crates/codegen/xai-webuild-plugin-marketplace`（scanner / installer）  
- WeBuild：`extensions/marketplace.rs::auto_install_defaults`  
- 用户指南：`crates/codegen/xai-webuild-pager/docs/user-guide/08-skills.md`、`09-plugins.md`
