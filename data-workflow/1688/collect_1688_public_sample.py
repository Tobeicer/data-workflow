from __future__ import annotations

import csv
import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, parse_qs

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
DEBUG_DIR = BASE_DIR / "_debug"
CHROME_PATHS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]

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


def chrome_executable() -> str | None:
    for path in CHROME_PATHS:
        if path.exists():
            return str(path)
    return None


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


def looks_blocked(page_text: str, page_url: str) -> tuple[bool, str]:
    text = page_text.lower()
    url = page_url.lower()
    markers = [
        ("login.1688.com", "页面跳转到登录"),
        ("登录", "页面要求登录"),
        ("signin", "页面要求登录"),
        ("验证码", "页面出现验证码"),
        ("captcha", "页面出现验证码"),
        ("滑块", "页面出现滑块验证"),
        ("访问受限", "页面访问受限"),
    ]
    for marker, note in markers:
        if marker.lower() in text or marker.lower() in url:
            return True, note
    return False, ""


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", action="append", help="只采集指定关键词，可重复传入")
    parser.add_argument("--prepare-login", action="store_true", help="打开 1688 登录页，等待人工登录并保存本地浏览器登录态")
    parser.add_argument("--login-wait-seconds", type=int, default=240, help="人工登录等待秒数")
    parser.add_argument("--limit-per-keyword", type=int, default=50, help="每个关键词最多保留的商品数")
    parser.add_argument("--delay-seconds", type=float, default=3.0, help="每个关键词之间的等待秒数")
    parser.add_argument("--scroll-count", type=int, default=2, help="每个搜索页向下滚动次数")
    parser.add_argument("--debug", action="store_true", help="保存搜索页 HTML 和截图调试文件")
    parser.add_argument("--output", help="输出 CSV 路径；默认按时间戳写入 1688 目录")
    parser.add_argument("--output-prefix", default="1688_product_sample", help="未指定 --output 时使用的输出文件名前缀")
    args = parser.parse_args()
    keywords = args.keyword or KEYWORDS

    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else BASE_DIR / f"{args.output_prefix}_{stamp}.csv"
    executable_path = chrome_executable()
    if args.debug:
        DEBUG_DIR.mkdir(exist_ok=True)

    all_rows: list[dict[str, str]] = []

    with sync_playwright() as p:
        launch_kwargs: dict = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--lang=zh-CN",
            ],
        }
        if executable_path:
            launch_kwargs["executable_path"] = executable_path

        user_data_dir = BASE_DIR / ".browser-profile"
        context = p.chromium.launch_persistent_context(
            str(user_data_dir),
            **launch_kwargs,
            locale="zh-CN",
            viewport={"width": 1365, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.pages[0] if context.pages else context.new_page()

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
            context.close()
            print("[1688] 登录准备步骤结束。本地登录态已保存在 data-workflow/1688/.browser-profile。")
            return

        for keyword in keywords:
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
                blocked, note = looks_blocked(text, page.url)
                if blocked:
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
                            "capture_status": "blocked",
                            "capture_note": note,
                        }
                    )
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

                time.sleep(args.delay_seconds)
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
                        "capture_status": "error",
                        "capture_note": f"{type(exc).__name__}: {exc}",
                    }
                )

        context.close()

    deduped: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for row in all_rows:
        key = row.get("offer_id") or row.get("product_url") or f"{row.get('keyword')}::{row.get('capture_status')}::{row.get('capture_note')}"
        if key in seen_keys and row.get("capture_status") == "success":
            continue
        seen_keys.add(key)
        deduped.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(deduped)

    success_count = sum(1 for row in deduped if row["capture_status"] == "success")
    print(f"[1688] 输出：{output_path}")
    print(f"[1688] 成功商品记录：{success_count}")
    print(f"[1688] 总记录：{len(deduped)}")


if __name__ == "__main__":
    main()
