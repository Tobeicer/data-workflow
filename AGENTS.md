# Project Context

- Project: 游艺圈
- Workspace: `E:\Desktop_zm\data-workflow`
- Current scope: data asset workflow, not platform construction

## Directory Boundaries

- `docs/`: execution baseline, unified technical design, classification reference and historical requirements.
- `data-workflow/`: source adapters, acquisition guides, scripts, raw assets, cleaned data and deliveries.
- `database/`: database snapshots and SQL dumps (reference only).
- `docs/project-split/`: protected original requirements; never modify.
- `docs/requirements/`: protected historical references; only `信息整理.md` receives new confirmed requirements.

## Authority And Reading Order

When documents conflict, use this order:

1. The user's latest explicit instruction.
2. `docs/数据工作流与游艺圈系统对接执行基线.md` (sole execution baseline).
3. `docs/数据工作流总体技术设计.md` for cross-source architecture, logical datasets and integration contracts.
4. The current source guide under `data-workflow/adapters/<source>/README.md` for source-specific behavior.
5. `docs/游艺圈游戏游艺设备完整分类清单.md` for taxonomy, platform mappings, keywords and scope rules.
6. `游艺圈数据导入字段规范_v2.md` for the current L3 Excel adapter only.
7. Protected historical references (`docs/project-split/`, `docs/requirements/`), only when historical product context is explicitly needed.

New confirmed business requirements go to `docs/requirements/信息整理.md`.

## Markdown Context Hygiene

- Active documents contain current decisions, not rejected alternatives.
- Once a decision is confirmed, remove A/B/C comparisons and write the selected approach directly.
- Do not place command failures, retry history or conversational reasoning in formal documents.
- A fact should have one authoritative definition; other documents link to it instead of repeating it.
- New role, data-layer, database-boundary or integration decisions must update the execution baseline first.
- Cross-source implementation details belong in `docs/数据工作流总体技术设计.md`; source commands and evidence belong only in the source adapter README.

## Current Data Role

Responsible for:

- source discovery and evaluation;
- public data crawling (大平台爬虫), authorized API integration (店铺入驻), and file-based acquisition;
- cleaning, deduplication, classification and AI-assisted analysis;
- update checks, change detection, quality gates and review queues;
- traceable L0-L2 assets and contract-based L3 deliveries.

Not responsible for:

- mini program, APP, Web admin, payment, order or transaction features;
- formal database schema, migrations or production business-table writes;
- platform review, promotion to formal records or publishing.

## Data Layers And Execution Boundary

- L0: immutable raw source assets and evidence.
- L1: normalized source assets with complete source fields.
- L2: relationships, snapshots, quality, changes and review queues.
- L3: replaceable platform-consumption deliveries generated from the current contract.

n8n is the control plane for triggers, orchestration, retries, state, human gates and alerts. Python/Node scripts are the execution plane for acquisition, cleaning, images, comparison, AI batches, quality checks and delivery generation.

Shared control-plane behavior does not imply shared collectors. Every platform owns an independent adapter and source workflow; shop, company and manufacturer roles remain distinct, and sparse source fields are represented by typed observations plus missing reasons.

## Current Source References

- `data-workflow/manlifang/漫立方抓包流程.md` is retained only as a compatibility entry.
- Current Manlifang assets, counts, tracked code and commands are documented only in `data-workflow/adapters/manlifang/README.md`.
- The 1688 and Taobao executable guides are `data-workflow/adapters/1688/README.md` and `data-workflow/adapters/taobao/README.md`.
- Source status and enabled state are defined only in `data-workflow/orchestration/n8n/configs/source_registry.json`.

Formal targets are `data-workflow/orchestration/n8n/`, `data-workflow/adapters/<source>/`, `data-workflow/runtime/`, `data-workflow/deliveries/` and root `legacy-workflow/`.

## Database Snapshot Reference

Historical/current-environment reference only:

- PostgreSQL: `192.168.1.98:5432`
- Database: `postgres`
- Schema: `public`
- Navicat connection name: `youyiquan`
- Expected historical dump path: `database/public.sql` (currently absent from this workspace)

Do not store passwords in Markdown. Use an untracked `.env.local` file.

## Integration Rules

- Do not write to `public.product`, `public.accessory`, `public.manufacturer` or other formal business tables without explicit scope expansion and an approved platform contract.
- Preferred integration order: internal import API, agreed permission-isolated `ingest/staging`, then L3 file import.
- The platform Git repository has not been received. When available, inspect it only to finalize the L3 adapter; never delete L0-L2 fields because the platform cannot currently consume them.
- Logical datasets and index suggestions in `docs/数据工作流总体技术设计.md` are recommendations for the contract/staging discussion, not authorization to create production tables or migrations.
- If `.codegraph/` exists and the task is about locating or understanding code, use CodeGraph before text search.
