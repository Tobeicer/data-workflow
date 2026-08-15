"""厂家任务：逐 memberId 采集工厂档案/工商信息/公司档案/联系方式四页，
按 normalize_companies_raw 期望的 pages 结构写入 companies_raw.jsonl。

用法：
  python adapters/1688/tasks/company.py --members b2b-1,b2b-2
  python adapters/1688/tasks/company.py --members-file <products_raw.jsonl>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (_REPO_ROOT / "shared" / "src", _REPO_ROOT / "adapters" / "1688"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from data_workflow_core.engine import write_jsonl  # noqa: E402
from tasks.cli import add_common_args, run_task_cli  # noqa: E402
from tasks.context import RunCtx, guarded_goto, read_page_text  # noqa: E402
from tasks.quality import check_company_pages  # noqa: E402
from tasks.records import (  # noqa: E402
    business_info_url,
    factory_archive_url,
    now_iso,
)

SHOP_DOMAIN_JS = """
() => {
  const infra = new Set(['sale', 'detail', 'm', 'www', 'login', 'work', 'ju', 'r', 'qr', 'log', 'my', 'page', 's']);
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const m = (a.href || '').match(/https?:\\/\\/([a-z0-9\\-]+)\\.1688\\.com/i);
    if (!m) continue;
    const host = m[1].toLowerCase();
    if (infra.has(host)) continue;
    if (/^wp\\./.test(host)) continue;
    if (host.length < 4) continue;
    seen.add(host);
  }
  return [...seen].slice(0, 5);
}
"""

FACTORY_MEDIA_JS = """
() => {
  const pick = (url) => (url || '').startsWith('//') ? 'https:' + url : (url || '');
  // 全页分类：会员桶图片 = 工厂自传内容（照片/证书）；ibank = 商品图；tfs/tps = UI 图标
  const memberPhoto = (u) => /cbu01\\.alicdn\\.com\\/i[1-4]\\/\\d{10,}\\//.test(u) && !/cbucrm/.test(u);
  const certImage = (u) => /cbu01\\.alicdn\\.com\\/i[1-4]\\/\\d{10,}\\//.test(u) && /cbucrm/.test(u);
  const dedupe = (list) => {
    const seen = new Set();
    return list.filter(x => { if (seen.has(x.url)) return false; seen.add(x.url); return true; });
  };
  const images = dedupe([...document.querySelectorAll('img')]
    .map(img => ({url: pick(img.currentSrc || img.src), title: img.alt || img.title || ''}))
    .filter(x => x.url.startsWith('http') && (memberPhoto(x.url) || certImage(x.url))));
  const photos = images.filter(x => memberPhoto(x.url));
  const certs = images.filter(x => certImage(x.url));
  const videos = dedupe([...document.querySelectorAll('video')]
    .map(v => ({url: pick(v.currentSrc || v.src), poster: pick(v.poster), title: ''}))
    .filter(x => x.url.startsWith('http')));
  return {images: photos, certs, videos};
}
"""

# 1688 基础设施/内容分发域：不能当店铺域（Python 侧二次过滤，与 JS 白名单双保险）
INFRA_SHOP_DOMAINS = {
    "sale", "detail", "m", "www", "login", "work", "ju", "r", "qr", "log",
    "my", "page", "s", "show", "air", "h5api", "picman", "img", "gtc",
    "gcrm", "gw", "open", "wb", "cbuimg", "imgm", "rule", "policy", "terms",
    "help", "about", "service", "legal", "trust",
}


def pick_shop_domain(hosts: list[str]) -> str:
    for host in hosts or []:
        host = (host or "").strip().lower()
        if not host:
            continue
        if host in INFRA_SHOP_DOMAINS:
            continue
        if host.startswith(("wp.", "gd", "cbu", "img", "pic")) or len(host) < 4:
            continue
        return host
    return ""


def load_members(value: str | None, members_file: str | None) -> list[str]:
    if members_file:
        members: list[str] = []
        seen: set[str] = set()
        for line in Path(members_file).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            member = str(row.get("member_id") or "").strip()
            if member and member not in seen:
                seen.add(member)
                members.append(member)
        return members
    if value:
        return [m.strip() for m in value.split(",") if m.strip()]
    return []


def discover_shop_domain(ctx: RunCtx) -> str:
    hosts = ctx.page.evaluate(SHOP_DOMAIN_JS) or []
    return pick_shop_domain(hosts)


def wait_for_business_text(ctx: RunCtx, polls: int = 4, interval_ms: int = 4000) -> str:
    """工商页是 JS 渲染的重页面：等「公司名称+统一社会信用代码」出现，最长约 16 秒。

    渲染超时仍返回当前文本（可能只是部分渲染，标签解析仍可用），
    外层对空文本再做一次整页重试。
    """
    text = read_page_text(ctx)
    for _ in range(polls):
        if "公司名称" in text and "统一社会信用代码" in text:
            break
        ctx.page.wait_for_timeout(interval_ms)
        text = read_page_text(ctx)
    return text


def collect_business_page(ctx: RunCtx, member_id: str) -> dict[str, str]:
    business_url = business_info_url(member_id)
    guarded_goto(ctx, business_url)
    business_text = wait_for_business_text(ctx)
    if len(business_text.strip()) < 50:
        ctx.log(
            f"business_info thin ({len(business_text.strip())} chars), retrying once",
            flush=True,
        )
        ctx.pause("manufacturer_s")
        guarded_goto(ctx, business_url)
        business_text = wait_for_business_text(ctx)
    return {"page_type": "business_info", "url": business_url, "text": business_text}


def collect_member_pages(ctx: RunCtx, member_id: str) -> list[dict[str, str]]:
    """采集四页并返回 pages 结构化记录。"""
    pages: list[dict[str, str]] = []

    factory_url = factory_archive_url(member_id)
    guarded_goto(ctx, factory_url)
    factory_text = read_page_text(ctx)
    factory_media = ctx.page.evaluate(FACTORY_MEDIA_JS) or {}
    pages.append(
        {
            "page_type": "factory_archive",
            "url": factory_url,
            "text": factory_text,
            "media": factory_media,
        }
    )
    shop_domain = discover_shop_domain(ctx)
    ctx.pause("manufacturer_s")

    pages.append(collect_business_page(ctx, member_id))
    if not shop_domain:
        shop_domain = discover_shop_domain(ctx)
    ctx.pause("manufacturer_s")

    if shop_domain:
        credit_url = f"https://{shop_domain}.1688.com/page/creditdetail.html"
        guarded_goto(ctx, credit_url)
        pages.append({"page_type": "credit_detail", "url": credit_url, "text": read_page_text(ctx)})
        ctx.pause("manufacturer_s")

        contact_url = f"https://{shop_domain}.1688.com/page/contactinfo.html"
        guarded_goto(ctx, contact_url)
        pages.append({"page_type": "contact_info", "url": contact_url, "text": read_page_text(ctx)})
        ctx.pause("manufacturer_s")
    return pages


def collect_factory_media_page(ctx: RunCtx, member_id: str) -> dict[str, str]:
    """只访问工厂档案页，采集文本 + 工厂展厅 DOM 媒体（补媒体重试用）。"""
    factory_url = factory_archive_url(member_id)
    guarded_goto(ctx, factory_url)
    factory_text = read_page_text(ctx)
    factory_media = ctx.page.evaluate(FACTORY_MEDIA_JS) or {}
    return {
        "page_type": "factory_archive",
        "url": factory_url,
        "text": factory_text,
        "media": factory_media,
    }


def run_company(
    ctx: RunCtx, members: list[str], limit: int, pages_mode: str = "all"
) -> dict[str, Any]:
    records_path = ctx.run_dir / "l0" / "companies_raw.jsonl"
    count = 0
    total_issues = 0
    for member_id in members[:limit]:
        if pages_mode == "business_info":
            pages = [collect_business_page(ctx, member_id)]
            ctx.pause("manufacturer_s")
        elif pages_mode == "factory_media":
            pages = [collect_factory_media_page(ctx, member_id)]
            ctx.pause("manufacturer_s")
        else:
            pages = collect_member_pages(ctx, member_id)
        record = {
            "source_platform": "1688",
            "member_id": member_id,
            "shop_url": "",
            "collected_at": now_iso(),
            "pages": pages,
        }
        # 采集合规检查层：页面结构校验，问题附在记录上
        issues = check_company_pages(pages)
        record["quality_issues"] = issues
        total_issues += len(issues)
        write_jsonl(records_path, [record])
        count += 1
        if issues:
            ctx.log(f"quality_issues {member_id}: {issues}", flush=True)
        ctx.log(
            f"manufacturer_done {member_id} pages={[p['page_type'] for p in pages]}",
            flush=True,
        )
    return {
        "manufacturers": count,
        "quality_issues": total_issues,
        "artifacts": {"companies_raw": str(records_path)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="1688 厂家任务（四页采集）")
    add_common_args(parser)
    parser.add_argument("--members", default=None, help="逗号分隔 memberId 列表")
    parser.add_argument("--members-file", default=None, help="products_raw.jsonl 路径")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--pages",
        choices=["all", "business_info", "factory_media"],
        default="all",
        help="business_info/factory_media：只重采对应页面（补空文本/补媒体重试用）",
    )
    args = parser.parse_args(argv)
    members = load_members(args.members, args.members_file)
    if not members:
        parser.error("需要 --members 或 --members-file")
    return run_task_cli(
        args, "company", lambda ctx: run_company(ctx, members, args.limit, args.pages)
    )


if __name__ == "__main__":
    sys.exit(main())
