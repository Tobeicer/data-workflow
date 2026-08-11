from __future__ import annotations

import csv
import argparse
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, parse_qs

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC_DIR = Path(__file__).resolve().parent
WORKFLOW_DIR = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(WORKFLOW_DIR / "shared" / "src"))
from data_workflow_core.browser import (  # noqa: E402
    PlaywrightBrowserSession,
    classify_restriction,
)

RUNS_DIR = WORKFLOW_DIR / "runtime" / "runs" / "1688"
PROFILE_DIR = WORKFLOW_DIR / "runtime" / "browser-profiles" / "1688"
DEBUG_DIR = WORKFLOW_DIR / "runtime" / "tmp" / "1688"

KEYWORDS = [
    "游戏机配件",
    "游艺机配件",
    "娃娃机配件",
    "投币器",
    "退币器",
    "出票器",
    "彩票机配件",
    "游戏机按钮",
    "游戏机摇杆",
    "游戏机主板",
    "游戏机电源",
    "游戏机锁具",
    "游戏机灯条",
]

FIELDNAMES = [
    "source_platform",
    "keyword",
    "product_title",
    "product_url",
    "offer_id",
    "price",
    "min_order_quantity",
    "sales_text",
    "shop_name",
    "shop_url",
    "location",
    "image_url",
    "collected_at",
    "capture_status",
    "capture_note",
]


def search_url(keyword: str) -> str:
    encoded = quote(keyword.encode("gbk"))
    return f"https://s.1688.com/selloffer/offer_search.htm?keywords={encoded}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/"):
        return urljoin("https://www.1688.com", value)
    return value


def offer_id_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    match = re.search(r"/offer/(\d+)\.html", parsed.path)
    if match:
        return match.group(1)
    qs = parse_qs(parsed.query)
    for key in ("offerId", "offer_id", "id"):
        if qs.get(key):
            return qs[key][0]
    match = re.search(r"(\d{8,})", url)
    return match.group(1) if match else ""


def offer_id_from_report(value: str | None) -> str:
    if not value:
        return ""
    for pattern in (r"object_id@(\d{8,})", r"offerIds=(\d{8,})", r"offerId=(\d{8,})"):
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return ""


def classify_search_restriction(page_text: str, page_url: str) -> tuple[str, str]:
    """兼容别名：统一检测在 data_workflow_core.browser.detection。"""
    return classify_restriction(page_text, page_url)


def looks_blocked(page_text: str, page_url: str) -> tuple[bool, str]:
    status, note = classify_restriction(page_text, page_url)
    return bool(status), note


def should_stop_discovery(status: str) -> bool:
    return status in {
        "login_required",
        "human_verification_required",
        "rate_limited",
        "network_error",
        "error",
    }


def classify_discovery_error(message: str) -> str:
    text = str(message or "").lower()
    if any(
        marker in text
        for marker in (
            "net::err_",
            "targetclosederror",
            "interrupted by another navigation",
            "browser has been closed",
            "context has been closed",
        )
    ):
        return "network_error"
    return "error"


def discovery_checkpoint_path(output_path: Path) -> Path:
    return output_path.with_suffix(".checkpoint.json")


def dedupe_discovery_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for row in rows:
        key = (
            row.get("offer_id")
            or row.get("product_url")
            or f"{row.get('keyword')}::{row.get('capture_status')}::{row.get('capture_note')}"
        )
        if key in seen_keys and row.get("capture_status") == "success":
            continue
        seen_keys.add(key)
        deduped.append(row)
    return deduped


def persist_discovery_state(
    output_path: Path,
    *,
    rows: list[dict[str, str]],
    requested_keywords: list[str],
    completed_keywords: list[str],
    status: str,
    current_keyword: str = "",
    message: str = "",
) -> None:
    deduped = dedupe_discovery_rows(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(deduped)

    checkpoint = {
        "status": status,
        "retryable": status in {
            "network_error",
            "timeout",
            "human_verification_required",
            "rate_limited",
            "login_required",
        },
        "requested_keywords": requested_keywords,
        "completed_keywords": completed_keywords,
        "current_keyword": current_keyword,
        "message": message,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output": str(output_path),
        "row_count": len(deduped),
        "success_count": sum(row.get("capture_status") == "success" for row in deduped),
    }
    discovery_checkpoint_path(output_path).write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_discovery_state(output_path: Path) -> tuple[list[dict[str, str]], set[str]]:
    rows: list[dict[str, str]] = []
    completed_keywords: set[str] = set()
    if output_path.exists():
        with output_path.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    checkpoint_path = discovery_checkpoint_path(output_path)
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        completed_keywords = set(checkpoint.get("completed_keywords") or [])
    elif rows:
        completed_keywords = {
            str(row.get("keyword") or "")
            for row in rows
            if row.get("capture_status") in {"success", "no_cards"}
            and str(row.get("keyword") or "")
        }
    return rows, completed_keywords


def extract_cards(page, keyword: str, collected_at: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    cards = page.locator(".search-offer-item")
    count = min(cards.count(), 80)
    seen: set[str] = set()

    for index in range(count):
        card = cards.nth(index)
        try:
            href = normalize_url(card.get_attribute("href"))
            if not href:
                continue
            offer_id = offer_id_from_url(href) or offer_id_from_report(card.get_attribute("data-aplus-report"))
            key = offer_id or href
            if key in seen:
                continue
            seen.add(key)

            handle = card.element_handle()
            if not handle:
                continue

            data = handle.evaluate(
                """el => {
                    const pickText = (selector) => {
                        const node = el.querySelector(selector);
                        return node ? (node.innerText || node.textContent || '').trim() : '';
                    };
                    const pickAttr = (selector, attr) => {
                        const node = el.querySelector(selector);
                        return node ? (node.getAttribute(attr) || '') : '';
                    };
                    return {
                        text: el.innerText || '',
                        title: pickText('.offer-title-row .title-text') || pickText('.offer-title-row'),
                        price: pickText('.offer-price-row .price-item') || pickText('.offer-price-row .col-desc'),
                        sales: pickText('.offer-price-row .col-desc_after'),
                        shopName: pickText('.offer-shop-row .col-left') || pickText('.offer-shop-row a'),
                        shopUrl: pickAttr('.offer-shop-row a', 'href'),
                        imageUrl: pickAttr('img.main-img', 'src') || pickAttr('img', 'src') || pickAttr('img', 'data-src'),
                    };
                }"""
            )

            title = clean_text(data.get("title") or "")
            if not title or len(title) < 2:
                continue

            card_text = clean_text(data.get("text") or "")
            price = ""
            price_text = clean_text(data.get("price") or "")
            price_text = re.sub(r"\s+", "", price_text).replace("¥", "").replace("￥", "")
            price_match = re.search(r"([0-9]+(?:\.[0-9]+)?)", price_text)
            if price_match:
                price = price_match.group(1)
            else:
                price_match = re.search(r"(?:¥|￥)\s*([0-9]+(?:\s*\.\s*[0-9]+)?)", card_text)
                if price_match:
                    price = re.sub(r"\s+", "", price_match.group(1))

            min_order_quantity = ""
            moq_match = re.search(r"([0-9]+)\s*(?:件|个|台|套|只|条|把|张)\s*起", card_text)
            if moq_match:
                min_order_quantity = moq_match.group(0)

            sales_text = ""
            sales_match = re.search(r"((?:成交|销量|已售|付款)[^ ]{0,16})", card_text)
            if sales_match:
                sales_text = sales_match.group(1)
            if not sales_text:
                sales_text = clean_text(data.get("sales") or "")

            rows.append(
                {
                    "source_platform": "1688",
                    "keyword": keyword,
                    "product_title": title,
                    "product_url": href,
                    "offer_id": offer_id,
                    "price": price,
                    "min_order_quantity": min_order_quantity,
                    "sales_text": sales_text,
                    "shop_name": clean_text(data.get("shopName") or ""),
                    "shop_url": normalize_url(data.get("shopUrl") or ""),
                    "location": "",
                    "image_url": normalize_url(data.get("imageUrl") or ""),
                    "collected_at": collected_at,
                    "capture_status": "success",
                    "capture_note": "",
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "source_platform": "1688",
                    "keyword": keyword,
                    "product_title": "",
                    "product_url": "",
                    "offer_id": "",
                    "price": "",
                    "min_order_quantity": "",
                    "sales_text": "",
                    "shop_name": "",
                    "shop_url": "",
                    "location": "",
                    "image_url": "",
                    "collected_at": collected_at,
                    "capture_status": "card_error",
                    "capture_note": f"{type(exc).__name__}: {exc}",
                }
            )

    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", action="append", help="只采集指定关键词，可重复传入")
    parser.add_argument("--prepare-login", action="store_true", help="打开 1688 登录页，等待人工登录并保存本地浏览器登录态")
    parser.add_argument("--login-wait-seconds", type=int, default=240, help="人工登录等待秒数")
    parser.add_argument("--prepare-verification", action="store_true", help="打开受限搜索页，等待人工完成验证")
    parser.add_argument("--verification-wait-seconds", type=int, default=240, help="人工验证等待秒数")
    parser.add_argument("--limit-per-keyword", type=int, default=50, help="每个关键词最多保留的商品数")
    parser.add_argument("--delay-seconds", type=float, default=5.0, help="每个关键词之间的等待秒数")
    parser.add_argument("--scroll-count", type=int, default=2, help="每个搜索页向下滚动次数")
    parser.add_argument("--profile-dir", default=str(PROFILE_DIR), help="browser profile dir for account isolation")
    parser.add_argument("--debug", action="store_true", help="保存搜索页 HTML 和截图调试文件")
    parser.add_argument("--output", help="输出 CSV 路径；默认按时间戳写入 1688 目录")
    parser.add_argument("--output-prefix", default="1688_product_sample", help="未指定 --output 时使用的输出文件名前缀")
    args = parser.parse_args()
    keywords = args.keyword or KEYWORDS

    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(args.output)
        if args.output
        else RUNS_DIR / f"1688_sample_{stamp}" / f"{args.output_prefix}_{stamp}.csv"
    )
    if args.debug:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_rows, completed_keywords = load_discovery_state(output_path)
    stop_status = ""
    stop_message = ""
    current_keyword = ""
    
    with PlaywrightBrowserSession(
        profile_dir=Path(args.profile_dir),
        screenshot_dir=DEBUG_DIR if args.debug else RUNS_DIR,
        delay_seconds=args.delay_seconds,
        debug=args.debug,
    ) as browser:
        page = browser.page

        if args.prepare_login:
            login_url = "https://login.1688.com/member/signin.htm"
            print(f"[1688] 已打开登录页：{login_url}")
            print("[1688] 请在弹出的 Chrome 窗口中手动登录 1688。")
            print(f"[1688] 登录完成后可等待脚本自动结束，最长等待 {args.login_wait_seconds} 秒。")
            page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
            deadline = time.time() + args.login_wait_seconds
            while time.time() < deadline:
                current_url = page.url
                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=1000)
                except Exception:
                    body_text = ""
                if "login.1688.com" not in current_url and "login.taobao.com" not in current_url:
                    print(f"[1688] 检测到已离开登录页：{current_url}")
                    break
                if "退出" in body_text or "我的阿里" in body_text:
                    print("[1688] 检测到可能已登录。")
                    break
                page.wait_for_timeout(3000)
            print(
                "[1688] 登录准备步骤结束。本地登录态已保存在 "
                "runtime/browser-profiles/1688/。"
            )
            return 0

        if args.prepare_verification:
            keyword = keywords[0]
            url = search_url(keyword)
            print(f"[1688] 已打开待验证搜索页：{keyword} -> {url}")
            print("[1688] 请在弹出的 Chrome 窗口中完成滑块或登录验证。")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except PlaywrightTimeoutError:
                pass
            deadline = time.time() + args.verification_wait_seconds
            verified = False
            while time.time() < deadline:
                try:
                    body_text = page.locator("body").inner_text(timeout=1500)
                    restriction, _ = classify_search_restriction(body_text, page.url)
                    offer_count = page.locator(
                        '.search-offer-item, a[href*="/offer/"]'
                    ).count()
                    if not restriction and offer_count > 0:
                        verified = True
                        print(f"[1688] 验证已通过，页面出现 {offer_count} 个商品节点。")
                        break
                except Exception:
                    pass
                page.wait_for_timeout(2000)
            if verified:
                print("[1688] 验证状态已保存，可使用 validate 从断点续跑。")
                return 0
            print("[1688] 等待超时，验证尚未通过。")
            return 2

        for keyword in keywords:
            if keyword in completed_keywords:
                print(f"[1688] 断点跳过已完成关键词：{keyword}")
                continue
            current_keyword = keyword
            all_rows = [
                row
                for row in all_rows
                if not (
                    row.get("keyword") == keyword
                    and row.get("capture_status") != "success"
                )
            ]
            url = search_url(keyword)
            print(f"[1688] 打开关键词：{keyword} -> {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)
                for _ in range(args.scroll_count):
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(1500)

                text = page.locator("body").inner_text(timeout=5000)
                if args.debug:
                    (DEBUG_DIR / f"{stamp}_{quote(keyword, safe='')}.html").write_text(page.content(), encoding="utf-8")
                    page.screenshot(path=str(DEBUG_DIR / f"{stamp}_{quote(keyword, safe='')}.png"), full_page=True)
                restriction, note = classify_search_restriction(text, page.url)
                if restriction:
                    print(f"[1688] 受限：{keyword} - {note}")
                    all_rows.append(
                        {
                            "source_platform": "1688",
                            "keyword": keyword,
                            "product_title": "",
                            "product_url": page.url,
                            "offer_id": "",
                            "price": "",
                            "min_order_quantity": "",
                            "sales_text": "",
                            "shop_name": "",
                            "shop_url": "",
                            "location": "",
                            "image_url": "",
                            "collected_at": collected_at,
                            "capture_status": restriction,
                            "capture_note": note,
                        }
                    )
                    if should_stop_discovery(restriction):
                        stop_status = restriction
                        stop_message = note
                        persist_discovery_state(
                            output_path,
                            rows=all_rows,
                            requested_keywords=keywords,
                            completed_keywords=[key for key in keywords if key in completed_keywords],
                            status=stop_status,
                            current_keyword=keyword,
                            message=stop_message,
                        )
                        break
                    continue

                rows = extract_cards(page, keyword, collected_at)
                print(f"[1688] 解析到 {len(rows)} 条候选")
                if rows:
                    all_rows.extend(rows[: args.limit_per_keyword])
                else:
                    all_rows.append(
                        {
                            "source_platform": "1688",
                            "keyword": keyword,
                            "product_title": "",
                            "product_url": page.url,
                            "offer_id": "",
                            "price": "",
                            "min_order_quantity": "",
                            "sales_text": "",
                            "shop_name": "",
                            "shop_url": "",
                            "location": "",
                            "image_url": "",
                            "collected_at": collected_at,
                            "capture_status": "no_cards",
                            "capture_note": "页面未解析到公开商品卡片",
                        }
                    )

                completed_keywords.add(keyword)
                persist_discovery_state(
                    output_path,
                    rows=all_rows,
                    requested_keywords=keywords,
                    completed_keywords=[key for key in keywords if key in completed_keywords],
                    status="running",
                    current_keyword=keyword,
                )
                time.sleep(args.delay_seconds * random.uniform(0.9, 1.6))
            except PlaywrightTimeoutError as exc:
                print(f"[1688] 超时：{keyword}")
                all_rows.append(
                    {
                        "source_platform": "1688",
                        "keyword": keyword,
                        "product_title": "",
                        "product_url": url,
                        "offer_id": "",
                        "price": "",
                        "min_order_quantity": "",
                        "sales_text": "",
                        "shop_name": "",
                        "shop_url": "",
                        "location": "",
                        "image_url": "",
                        "collected_at": collected_at,
                        "capture_status": "timeout",
                        "capture_note": str(exc),
                    }
                )
                stop_status = "timeout"
                stop_message = str(exc)
                persist_discovery_state(
                    output_path,
                    rows=all_rows,
                    requested_keywords=keywords,
                    completed_keywords=[key for key in keywords if key in completed_keywords],
                    status=stop_status,
                    current_keyword=keyword,
                    message=stop_message,
                )
                break
            except Exception as exc:
                print(f"[1688] 失败：{keyword} - {type(exc).__name__}: {exc}")
                all_rows.append(
                    {
                        "source_platform": "1688",
                        "keyword": keyword,
                        "product_title": "",
                        "product_url": url,
                        "offer_id": "",
                        "price": "",
                        "min_order_quantity": "",
                        "sales_text": "",
                        "shop_name": "",
                        "shop_url": "",
                        "location": "",
                        "image_url": "",
                        "collected_at": collected_at,
                        "capture_status": classify_discovery_error(str(exc)),
                        "capture_note": f"{type(exc).__name__}: {exc}",
                    }
                )
                stop_status = classify_discovery_error(str(exc))
                stop_message = f"{type(exc).__name__}: {exc}"
                persist_discovery_state(
                    output_path,
                    rows=all_rows,
                    requested_keywords=keywords,
                    completed_keywords=[key for key in keywords if key in completed_keywords],
                    status=stop_status,
                    current_keyword=keyword,
                    message=stop_message,
                )
                break


    deduped = dedupe_discovery_rows(all_rows)
    final_status = stop_status or "completed"
    persist_discovery_state(
        output_path,
        rows=deduped,
        requested_keywords=keywords,
        completed_keywords=[key for key in keywords if key in completed_keywords],
        status=final_status,
        current_keyword=current_keyword,
        message=stop_message,
    )

    success_count = sum(1 for row in deduped if row["capture_status"] == "success")
    print(f"[1688] 输出：{output_path}")
    print(f"[1688] 成功商品记录：{success_count}")
    print(f"[1688] 总记录：{len(deduped)}")
    if final_status in {"human_verification_required", "login_required", "rate_limited"}:
        return 2
    if final_status in {"network_error", "timeout", "error"}:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
