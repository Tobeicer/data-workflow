# Project Context

- Project: 游艺圈
- Workspace: `E:\Desktop_zm\data-workflow`
- Current scope: data asset workflow, not platform construction
- Product boundary: an information supply platform for amusement-facility products and manufacturers, not a marketplace

## Directory Boundaries

- `docs/`: execution baseline, architecture, governance and indexes.
- `data-workflow/`: current source directories, acquisition guides, scripts, runtime assets and deliveries.
- `docs/project-split/` and `docs/requirements/`: protected historical references; never modify them or let them override current decisions.

## Authority And Reading Order

When documents conflict, use this order:

1. The user's latest explicit instruction.
2. `docs/数据工作流与游艺圈系统对接执行基线.md`.
3. The current source guide under the existing `data-workflow/<source>/` directory.
4. `docs/游艺圈数据资产生产工作流总体执行方案.md` or `data-workflow/数据获取执行指南.md` only when the task needs architecture or general workflow context.
5. `游艺圈数据导入字段规范_v2.md` for the current L3 Excel adapter only.
6. Protected historical references, only when historical product context is explicitly needed.

For ordinary source work, read only `README.md`, the execution baseline and the relevant source guide. Do not load every planning or research document by default.

## Markdown Context Hygiene

- Active documents contain current decisions and current execution instructions, not rejected alternatives.
- Once a decision is confirmed, remove A/B/C comparisons and write the selected approach directly.
- Do not place command failures, retry history or conversational reasoning in formal documents.
- Historical batch results should be a short dated summary, not a chronological diary.
- A fact should have one authoritative definition; other documents link to it instead of repeating it.
- `task_plan.md`, `findings.md` and `progress.md` keep only current work, valid findings and recent verification evidence.
- New role, data-layer, database-boundary or integration decisions must update the execution baseline first.

## Current Ownership

### Data Owner

- discover, register, grade and evaluate compliant public or authorized sources;
- maintain the Manlifang, 1688, Taobao, JD, Pinduoduo, Douyin and Xianyu adapters;
- retain source fields as completely as possible and maintain traceable L0-L2 assets;
- generate replaceable, contract-based L3 deliveries;
- maintain n8n orchestration, retries, state, quality gates and update detection;
- prioritize stable acquisition workflows; classification, field rendering and formal database models are not the current implementation focus.

### Platform Owner

- maintain the formal database structure, migrations, indexes and permissions;
- maintain platform applications and field consumption or rendering;
- maintain import APIs, receiving validation and error receipts;
- own review, promotion to formal records, publishing and rollback.

### Joint Decisions

- confirm the L3 contract, source legality and authorization boundaries;
- confirm quality thresholds, exception handling and change compatibility;
- keep formal business-table writes on the platform side.

## Data Layers And Execution Boundary

- L0: immutable raw source assets and evidence.
- L1: normalized source assets with complete source fields.
- L2: relationships, snapshots, quality, changes and review queues.
- L3: replaceable platform-consumption deliveries generated from the current contract.

n8n is the control plane for triggers, orchestration, retries, state, human gates and alerts. Python/Node scripts are the execution plane for acquisition, cleaning, images, comparison, AI batches, quality checks and delivery generation.

## Current Executable Paths

- Manlifang source guide: `data-workflow/manlifang/漫立方抓包流程.md`
- 1688 source guide: `data-workflow/1688/1688_公开商品采集流程.md`
- Taobao source guide: `data-workflow/taobao/淘宝公开商品采集验证.md`

Use the commands documented in these existing guides until the corresponding adapter migration is complete.

## Approved Migration Target Paths

These paths are the approved formal contract. Task 3-6 must create or migrate them before they become executable entrypoints:

- n8n control plane: `data-workflow/orchestration/n8n/`
- source adapters: `data-workflow/adapters/<source>/`
- L0-L2 runtime assets: `data-workflow/runtime/`
- L3 deliveries: `data-workflow/deliveries/`
- historical archive: `legacy-workflow/`

## Current Manlifang Assets

- Batch: `data-workflow/manlifang/captures/manlifang_full_20260710_110814/`
- Raw XLSX: `data-workflow/manlifang/captures/manlifang_full_20260710_110814/漫立方_原始全量商品数据_manlifang_full_20260710_110814.xlsx`
- Cleaned XLSX: `data-workflow/manlifang/captures/manlifang_full_20260710_110814/cleaned/漫立方_新全量清洗主数据_20260712.xlsx`
- Delivery: `data-workflow/manlifang/漫立方_全量数据/`
- Handoff XLSX: `data-workflow/manlifang/漫立方_全量数据/漫立方_全量数据.xlsx`
- Source guide: `data-workflow/manlifang/漫立方抓包流程.md`

The final batch contains 3128 unique public products and 5528 normalized images. Later processing must use the fresh structured JSONL, raw responses and hash-named originals as source assets.

## Database Snapshot Reference

Historical/current-environment reference only. These details are not part of the Data Owner's current directory responsibility.

- PostgreSQL: `192.168.1.98:5432`
- Database: `postgres`
- Schema: `public`
- Navicat connection name: `youyiquan`
- Dump: `database/public.sql`

Observed formal tables include `manufacturer`, `product`, `accessory`, `category`, `document`, `file_resource`, `staging_manufacturer` and supporting user/audit/settings tables. Earlier Manlifang work also observed `ingest.*` and `asset.*` receiving tables.

Use them only to verify the historical/current environment and integration contract; they must not be used as a basis for direct writes to formal business tables.

Do not store passwords in Markdown. Use an untracked `.env.local` file.

## Integration Rules

- Do not write to `public.product`, `public.accessory`, `public.manufacturer` or other formal business tables without explicit scope expansion and an approved platform contract.
- Preferred integration order: internal import API, agreed permission-isolated `ingest/staging`, then L3 file import.
- The platform Git repository has not been received. When available, inspect it only to finalize the L3 adapter; never delete L0-L2 fields because the platform cannot currently consume them.
- If `.codegraph/` exists and the task is about locating or understanding code, use CodeGraph before text search.
