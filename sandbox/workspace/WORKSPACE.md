# WeBuild Sandbox Workspace

This directory is the agent working tree for one cloud sandbox session.
Follow these conventions so tools, skills, memory, and downloads stay consistent.

## Layout

| Path | Purpose |
|------|---------|
| `inbox/` | **User uploads** (Gateway writes here). Prefer read-only; copy before editing. |
| `sources/` | Normalized working copies of inbox materials (rename, extract, convert). |
| `work/` | Intermediate drafts and scratch analysis — not final deliverables. |
| `context/` | Context packs: summaries, indexes, cited excerpts for this session. |
| `memory/` | Short notes that should persist across turns inside this sandbox. |
| `ground-truth/` | Verified facts, citations, and evidence that must not be casually rewritten. |
| `audits/` | Cross-document consistency checks and discrepancy logs. |
| `skills/` | Optional session-local `SKILL.md` packs (supplement global skills). |
| `outputs/` | **Final deliverables** for the user (reports, decks, tables, exports). |
| `.webuild/` | Optional project config — not exposed for download. |

## Rules for the agent

1. Treat `inbox/` as the source of truth for user-provided files. Copy into `sources/` before mutating.
2. Put anything the user should download under `outputs/` (readable names, UTF-8 when text).
3. Record lasting conclusions in `memory/`; put citations and checked claims in `ground-truth/`.
4. When comparing multiple documents, write an audit note under `audits/`.
5. Prefer existing WeBuild skills/tools for PDF, DOCX, PPTX, XLSX, Markdown, and code.
6. After finishing a report, tell the user the exact path under `/workspace/outputs/…`.

## Lifetime

Files live on ephemeral pod storage. When the sandbox TTL ends or the pod is terminated, this tree is deleted. Download outputs before the sandbox expires.
