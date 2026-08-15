"""Read-only inspection utility for the platform PostgreSQL database.

数据侧只读查验工具（不写入任何数据）：

- 连接串只读 `REMOTE_DATABASE_URL`（.env.local，未跟踪），可用 `--url` 覆盖；
- 会话级强制只读（default_transaction_read_only=on），只执行 SELECT；
- 用于查验 staging_manufacturer 现状、平台导入结果与正式 ID 映射。

用途定位：查看通道，不是交付通道。交付仍走 `deliveries/` 文件包（总纲 §12.1）。

退出码：
  0  查询成功
  2  用法/参数错误
  3  连接配置或连接失败（前置检查失败）

用法：
  python tools/db_inspect.py tables                 # public 表清单 + 行数
  python tools/db_inspect.py staging                # staging_manufacturer 列 + 最近 5 行
  python tools/db_inspect.py mapping [--limit N]    # 正式 manufacturer.id 与 name/source_url 映射
  python tools/db_inspect.py products [--limit N]   # product 表最近行摘要
"""

import argparse
import sys
from pathlib import Path

import psycopg

STAGING_COLS = [
    "id", "name", "short_name", "region", "main_products", "website",
    "contact_name", "contact_phone", "wechat", "address", "description",
    "source_url", "status", "claim_status", "created_at", "updated_at",
]

WATCH_TABLES = [
    "staging_manufacturer", "manufacturer", "product", "accessory",
    "category", "document",
]


def load_env_url() -> str | None:
    env_file = Path(".env.local")
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("REMOTE_DATABASE_URL="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def connect(url: str):
    # 会话级只读，双保险：即使代码误写也会被数据库拒绝
    return psycopg.connect(url, connect_timeout=8,
                           options="-c default_transaction_read_only=on")


def cmd_tables(cur) -> None:
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name"
    )
    tables = [r[0] for r in cur.fetchall()]
    print(f"public schema tables: {len(tables)}")
    for t in tables:
        note = ""
        if t in WATCH_TABLES:
            try:
                cur.execute(f'SELECT COUNT(*) FROM public."{t}"')
                note = f" rows={cur.fetchone()[0]}"
            except Exception as exc:  # noqa: BLE001
                note = f" count_error={type(exc).__name__}"
        print(f"  {t}{note}")


def cmd_staging(cur) -> None:
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='staging_manufacturer'"
    )
    if not cur.fetchall():
        print("staging_manufacturer 不存在")
        return
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='staging_manufacturer' "
        "ORDER BY ordinal_position"
    )
    cols = [r[0] for r in cur.fetchall()]
    print(f"staging_manufacturer 列（{len(cols)}）: {cols}")
    missing = [c for c in STAGING_COLS if c not in cols]
    extra = [c for c in cols if c not in STAGING_COLS]
    if missing:
        print(f"  缺少预期列: {missing}")
    if extra:
        print(f"  多出列: {extra}")
    cur.execute("SELECT COUNT(*) FROM public.staging_manufacturer")
    print(f"行数: {cur.fetchone()[0]}")
    cur.execute(
        "SELECT id, name, region, status, claim_status, source_url, created_at "
        "FROM public.staging_manufacturer ORDER BY id DESC LIMIT 5"
    )
    rows = cur.fetchall()
    if rows:
        print("最近 5 行（联系方式列已省略）:")
        for r in rows:
            print("  ", [str(x)[:36] if x is not None else None for x in r])


def cmd_mapping(cur, limit: int) -> None:
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='manufacturer'"
    )
    if not cur.fetchall():
        print("manufacturer 正式表不存在（尚未晋级）")
        return
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='manufacturer' "
        "ORDER BY ordinal_position"
    )
    cols = [r[0] for r in cur.fetchall()]
    name_col = "name" if "name" in cols else cols[0]
    source_col = "source_url" if "source_url" in cols else None
    sel = "id, " + name_col
    if source_col:
        sel += ", " + source_col
    cur.execute(
        f"SELECT {sel} FROM public.manufacturer ORDER BY id DESC LIMIT %s",
        (limit,),
    )
    print(f"manufacturer 正式表列: {cols}")
    print(f"最近 {limit} 行（id ↔ {name_col}）:")
    for r in cur.fetchall():
        print("  ", [str(x)[:48] if x is not None else None for x in r])


def cmd_products(cur, limit: int) -> None:
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='product'"
    )
    if not cur.fetchall():
        print("product 正式表不存在")
        return
    cur.execute("SELECT COUNT(*) FROM public.product")
    print(f"product 行数: {cur.fetchone()[0]}")
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='product' "
        "ORDER BY ordinal_position"
    )
    cols = [r[0] for r in cur.fetchall()]
    print(f"product 列: {cols}")
    sel = "id, name, category, price_range" if {"name", "category", "price_range"} <= set(cols) else "*"
    cur.execute(f"SELECT {sel} FROM public.product ORDER BY id DESC LIMIT %s", (limit,))
    print(f"最近 {limit} 行:")
    for r in cur.fetchall():
        print("  ", [str(x)[:40] if x is not None else None for x in r])


def main() -> int:
    parser = argparse.ArgumentParser(description="只读查验平台数据库")
    parser.add_argument("command", choices=["tables", "staging", "mapping", "products"])
    parser.add_argument("--url", default=None, help="覆盖 REMOTE_DATABASE_URL")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    url = args.url or load_env_url()
    if not url:
        print("未配置 REMOTE_DATABASE_URL（.env.local），无法连接。", file=sys.stderr)
        print("拿到平台方只读账号后填入：postgresql://<user>:<password>@<主机>:5432/<库名>；"
              "主机以平台方 Navicat 连接 `youyiquan` 现场值为准（历史记录 192.168.1.98）",
              file=sys.stderr)
        return 3

    try:
        with connect(url) as con, con.cursor() as cur:
            if args.command == "tables":
                cmd_tables(cur)
            elif args.command == "staging":
                cmd_staging(cur)
            elif args.command == "mapping":
                cmd_mapping(cur, args.limit)
            elif args.command == "products":
                cmd_products(cur, args.limit)
    except psycopg.Error as exc:
        print(f"连接/查询失败: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
