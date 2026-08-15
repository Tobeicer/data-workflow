# Project Context

- Project: 游艺圈
- Workspace: `C:\Users\Administrator\Desktop\data-workflow`
- Current scope: data asset workflow, not platform construction

## Directory Boundaries

- `docs/`: documentation index, sole active handbook, field specification, classification reference and protected historical requirements.
- Workspace root: source adapters, acquisition guides, scripts, raw assets, cleaned data and deliveries.
- `docs/requirements/游艺圈历史总体需求.md`: merged historical overall requirements (former `project-split/` + requirements framework); reference only, never treated as active scope.
- `docs/requirements/信息整理.md`: the only entry that receives new confirmed requirements.

## Authority And Reading Order

When documents conflict, use this order:

1. The user's latest explicit instruction.
2. `docs/README.md` when document location or maintenance ownership is needed.
3. `docs/游艺圈数据工作流总纲.md` (sole active handbook: boundaries, architecture, contracts, roadmap, status and next action).
4. The current source guide under `adapters/<source>/README.md` for source-specific behavior.
5. `docs/游艺圈游戏游艺设备完整分类清单.md` for taxonomy, platform mappings, keywords and scope rules.
6. `docs/数据字段规范.md` for the database field baseline (public schema table structures and the platform receiving tables) and the current L3 Excel adapter.
7. Protected historical references (`docs/requirements/游艺圈历史总体需求.md`), only when historical product context is explicitly needed.

New confirmed business requirements go to `docs/requirements/信息整理.md`.

## Markdown Context Hygiene

- Active documents contain current decisions, not rejected alternatives.
- Once a decision is confirmed, remove A/B/C comparisons and write the selected approach directly.
- Do not place command failures, retry history or conversational reasoning in formal documents.
- A fact should have one authoritative definition; other documents link to it instead of repeating it.
- New role, data-layer, database-boundary or integration decisions must update the active handbook first.
- Cross-source architecture, logical datasets, implementation tasks, progress and the next execution point belong only in `docs/游艺圈数据工作流总纲.md`; source commands and evidence belong only in the source adapter README.

## Current Data Role

Responsible for:

- source discovery and evaluation;
- data crawling (大平台爬虫、授权与业务来源), authorized API integration (店铺入驻), and file-based acquisition;
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

- Current Manlifang assets, counts, tracked code and commands are documented only in `adapters/manlifang/README.md`.
- The 1688 and Taobao executable guides are `adapters/1688/README.md` and `adapters/taobao/README.md`.
- The experimental WeChat source (Phase H, H1/H2/H3 done) is documented only in `adapters/wechat/README.md`; it does not participate in the seven commodity sources' G4 enablement.
- Source status and enabled state are defined only in `orchestration/n8n/configs/source_registry.json`.

Formal targets are `orchestration/n8n/`, `adapters/<source>/`, `shared/`, `contracts/`, `configs/`, `tests/`, `tools/`, `runtime/` and `deliveries/`. Roadmap tasks that have not started have no placeholder files; their contracts live in the handbook. The G1 `configs/`, the A2/A6 validators under `tools/`, and the B6 master/shared/source workflows under `orchestration/n8n/workflows/` are created when those tasks start. Current `tools/` contains only the keyword export tool and current `orchestration/n8n/workflows/` contains only the experimental WeChat workflow.

## Database Snapshot Reference

Live platform database (verified 2026-08-14):

- Working DB (current integration target): PostgreSQL `192.168.1.43:5432` (platform dev environment), Database `postgres`, Schema `public`, Navicat connection `youyiquan`
- Production DB (registered, do not touch yet): cloud server `47.119.113.170` via SSH (root); PostgreSQL listens only on its local `127.0.0.1:5432`; migrate after the working DB is validated
- Receiving tables: `industry_source_1688_product` (57 cols, unique key `(source_platform, product_id)`), `industry_source_1688_sku` (13 cols), `industry_source_1688_binding` (9 cols); manufacturers go to formal `manufacturer` (33 cols incl. `member_id`) with `import_batch` + `status='pending'`; manufacturer dedup: registry → `member_id` → `source_url` → same-name fallback
- Write account: platform owner decided to use the `postgres` superuser during development; a least-privilege account comes later if a dedicated DB operator is assigned
- `staging_manufacturer` (16 cols) exists but is unused by the platform (0 rows)
- `192.168.1.98:5432` is a deprecated old environment (July ingest trial) — do not use
- Field baseline: `docs/数据字段规范.md` (re-queried 2026-08-14)
- Expected historical dump path: `database/public.sql` (currently absent; create the folder when a snapshot arrives)

Do not store passwords in Markdown. Use an untracked `.env.local` file.

## Integration Rules

- Data side writes only these platform tables: `public.manufacturer` (with `import_batch`, `status='pending'`) and `public.industry_source_1688_product` / `industry_source_1688_sku`. Never write `public.product`, `public.accessory`, or business/order/transaction tables.
- Write account (platform owner's decision, 2026-08-14): use the `postgres` superuser during development; switch to a least-privilege account later if a dedicated DB operator is assigned.
- Integration mode (settled 2026-08-14): direct batch writes to the receiving tables above; file snapshots under `deliveries/` (local + NAS `data/deliveries/` mirror) are kept as audit fallback. A platform import API, if provided later, can replace the direct writes.
- NAS `\\tdd-nas\ai应用部\游艺圈\data\` holds only `media/` (images/videos) and `deliveries/` (snapshot mirror); L0-L2 assets live only in local `runtime/`; NAS never runs a database.
- The platform Git repository has not been received. When available, inspect it only to finalize the L3 adapter; never delete L0-L2 fields because the platform cannot currently consume them.
- Logical datasets and index suggestions in `docs/游艺圈数据工作流总纲.md` are recommendations for the contract/staging discussion, not authorization to create production tables or migrations.
- If `.codegraph/` exists and the task is about locating or understanding code, use CodeGraph before text search.
