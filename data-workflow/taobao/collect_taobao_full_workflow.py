from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlparse


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = BASE_DIR / ".browser-profile"
DEBUG_DIR = BASE_DIR / "_debug"

CHROME_PATHS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]

KEYWORDS = [
    "娃娃机配件",
    "投币器",
    "出票器",
    "彩票机配件",
    "游戏机按钮",
    "游戏机摇杆",
    "游戏机主板",
    "游戏机电源",
    "游戏机灯条",
    "游戏机信号线",
    "游戏机喇叭",
    "游戏机功放",
    "游戏机门锁",
    "游戏机脚轮",
    "游戏机微动开关",
    "游戏机插座",
    "游戏机排插",
    "游戏机电源线",
    "游戏机马达",
    "游戏机计数器",
    "篮球机配件",
    "曲棍球机配件",
    "游戏机枪配件",
    "空压机游戏机配件",
    "游戏机螺丝",
    "游戏机扎带",
    "游戏机塑胶件",
    "游戏机五金件",
    "游戏机工具",
    "马戏团游戏机配件",
    "控台配件",
]

PARAMETER_KEYS = [
    "适用性别",
    "产地",
    "品牌",
    "适用场景",
    "适用年龄段",
    "设备种类",
    "型号",
    "控制系统",
    "支付方式",
    "主题风格",
    "颜色分类",
    "材质",
    "功能",
    "规格",
    "适用人群",
]

FIELDNAMES = [
    "source_platform",
    "item_id",
    "keywords",
    "product_url",
    "product_title",
    "detail_title",
    "search_price_text",
    "detail_price_text",
    "shop_name",
    "shop_url",
    "location",
    "sales_text",
    "image_url",
    "model",
    "brand",
    "control_system",
    "payment_method",
    "theme_style",
    "color_category",
    "origin_place",
    "applicable_scene",
    "applicable_age",
    "device_type",
    "applicable_gender",
    "attributes_json",
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
    return "https://s.taobao.com/search?q=" + quote(keyword)


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
        return urljoin("https://www.taobao.com", value)
    return value


def item_id_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(normalize_url(url))
    qs = parse_qs(parsed.query)
    for key in ("id", "item_id", "itemId"):
        if qs.get(key):
            return qs[key][0]
    match = re.search(r"(?:id|itemId)[=/](\d{6,})", url)
    if match:
        return match.group(1)
    match = re.search(r"(\d{8,})", url)
    return match.group(1) if match else ""


def looks_blocked(page_text: str, page_url: str) -> tuple[bool, str]:
    text = page_text.lower()
    url = page_url.lower()
    markers = [
        ("login.taobao.com", "页面跳转到登录"),
        ("login.tmall.com", "页面跳转到登录"),
        ("登录", "页面要求登录"),
        ("验证码", "页面出现验证码"),
        ("captcha", "页面出现验证码"),
        ("滑块", "页面出现滑块验证"),
        ("安全验证", "页面出现安全验证"),
        ("访问受限", "页面访问受限"),
        ("verify", "页面出现验证"),
    ]
    for marker, note in markers:
        if marker.lower() in text or marker.lower() in url:
            return True, note
    return False, ""


def add_attr(attrs: dict[str, str], key: str | None, value: str | None) -> None:
    key = clean_text((key or "").rstrip(":："))
    value = clean_text(value)
    if key in PARAMETER_KEYS and value and value != key and key not in attrs:
        attrs[key] = value


def parse_parameter_lines(text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    lines = [clean_text(line) for line in re.split(r"[\r\n]+", text or "") if clean_text(line)]
    consumed_value_indexes: set[int] = set()

    for index, line in enumerate(lines):
        for key in PARAMETER_KEYS:
            if line == key:
                previous_line = lines[index - 1] if index > 0 else ""
                next_line = lines[index + 1] if index + 1 < len(lines) else ""
                if previous_line and previous_line not in PARAMETER_KEYS and index - 1 not in consumed_value_indexes:
                    add_attr(attrs, key, previous_line)
                    consumed_value_indexes.add(index - 1)
                elif next_line and next_line not in PARAMETER_KEYS:
                    add_attr(attrs, key, next_line)
                    consumed_value_indexes.add(index + 1)
            elif line.startswith(key):
                add_attr(attrs, key, line.removeprefix(key))
            elif line.endswith(key):
                add_attr(attrs, key, line[: -len(key)])

    cleaned = clean_text(text)
    if not cleaned:
        return attrs
    for index, key in enumerate(PARAMETER_KEYS):
        if key in attrs:
            continue
        next_keys = [re.escape(k) for k in PARAMETER_KEYS if k != key]
        next_pattern = "|".join(next_keys)
        pattern = rf"{re.escape(key)}\s+(.+?)(?=\s+(?:{next_pattern})\s+|$)"
        match = re.search(pattern, cleaned)
        if match:
            add_attr(attrs, key, match.group(1))
        elif index + 1 < len(PARAMETER_KEYS):
            continue
    return attrs


def pick_attr(attributes: dict[str, str], *names: str) -> str:
    for name in names:
        if attributes.get(name):
            return attributes[name]
    return ""


def normalize_attrs(raw_attrs: dict | None) -> dict[str, str]:
    attrs: dict[str, str] = {}
    if not isinstance(raw_attrs, dict):
        return attrs
    for key, value in raw_attrs.items():
        add_attr(attrs, str(key), str(value))
    return attrs


def human_pause(min_seconds: float, max_seconds: float) -> None:
    time.sleep(random.uniform(min_seconds, max(min_seconds, max_seconds)))


def browse_like_user(page, scroll_count: int, min_delay: float, max_delay: float) -> None:
    page.wait_for_timeout(int(random.uniform(min_delay, max_delay) * 1000))
    try:
        page.mouse.move(random.randint(180, 900), random.randint(160, 680), steps=random.randint(8, 18))
    except Exception:
        pass
    for _ in range(scroll_count):
        page.mouse.wheel(0, random.randint(650, 1100))
        page.wait_for_timeout(int(random.uniform(min_delay, max_delay) * 1000))


def extract_search_cards(page, keyword: str, collected_at: str, limit: int) -> list[dict[str, str]]:
    data = page.evaluate(
        """(limit) => {
            const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const normalizeUrl = (url) => {
                if (!url) return '';
                if (url.startsWith('//')) return 'https:' + url;
                if (url.startsWith('/')) return 'https://www.taobao.com' + url;
                return url;
            };
            const anchors = Array.from(document.querySelectorAll('a[href*="item.htm"], a[href*="detail.tmall.com"], a[href*="item.taobao.com"]'));
            const rows = [];
            const seen = new Set();
            for (const anchor of anchors) {
                const href = normalizeUrl(anchor.href || anchor.getAttribute('href') || '');
                if (!href || seen.has(href)) continue;
                const card = anchor.closest('[class*="item"], [class*="Card"], [class*="card"], li, div') || anchor.parentElement;
                const text = clean(card ? (card.innerText || card.textContent) : (anchor.innerText || anchor.textContent));
                const title = clean(anchor.innerText || anchor.textContent || text.split('￥')[0] || '');
                if (!title || title.length < 2) continue;
                const img = (card && card.querySelector('img')) || anchor.querySelector('img');
                const imageUrl = img ? normalizeUrl(img.currentSrc || img.src || img.getAttribute('src') || img.getAttribute('data-src') || '') : '';
                const shopAnchor = card ? Array.from(card.querySelectorAll('a')).find(a => clean(a.innerText || a.textContent).length > 1 && !String(a.href || '').includes('item.htm')) : null;
                rows.push({
                    href,
                    title,
                    text,
                    imageUrl,
                    shopName: shopAnchor ? clean(shopAnchor.innerText || shopAnchor.textContent) : '',
                    shopUrl: shopAnchor ? normalizeUrl(shopAnchor.href || shopAnchor.getAttribute('href') || '') : '',
                });
                seen.add(href);
                if (rows.length >= limit) break;
            }
            return rows;
        }""",
        limit,
    )

    rows: list[dict[str, str]] = []
    for item in data or []:
        text = clean_text(item.get("text") or "")
        title = clean_text(item.get("title") or "")
        title = re.split(r"\s*[¥￥]\s*", title, maxsplit=1)[0].strip()
        price_match = re.search(r"(?:¥|￥)\s*([0-9]+(?:\.[0-9]+)?)", text)
        sales_match = re.search(r"((?:已售|付款|销量|成交|评价)[^ ]{0,16})", text)
        location_match = re.search(
            r"(广东|浙江|江苏|山东|福建|河北|河南|湖南|湖北|四川|上海|北京|天津|重庆|广西|安徽|江西|辽宁|吉林|黑龙江|陕西|山西|云南|贵州|海南|新疆|内蒙古|宁夏|甘肃|青海|西藏)[^ ]{0,8}",
            text,
        )
        product_url = normalize_url(item.get("href") or "")
        rows.append(
            {
                "source_platform": "taobao",
                "keyword": keyword,
                "product_title": title,
                "product_url": product_url,
                "item_id": item_id_from_url(product_url),
                "price_text": price_match.group(0) if price_match else "",
                "shop_name": clean_text(item.get("shopName") or ""),
                "shop_url": normalize_url(item.get("shopUrl") or ""),
                "location": location_match.group(0) if location_match else "",
                "sales_text": sales_match.group(1) if sales_match else "",
                "image_url": normalize_url(item.get("imageUrl") or ""),
                "collected_at": collected_at,
                "capture_status": "success",
                "capture_note": "",
            }
        )
    return rows


def extract_detail(page, item_id: str, collected_at: str) -> dict[str, str]:
    data = page.evaluate(
        """() => {
            const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const attrs = {};
            const addAttr = (key, value) => {
                key = clean(key).replace(/[：:]+$/, '');
                value = clean(value);
                if (key && value && key !== value) attrs[key] = value;
            };
            const pickNodeText = (node) => clean(node?.getAttribute('title') || node?.innerText || node?.textContent || '');
            const bodyText = clean(document.body ? (document.body.innerText || document.body.textContent) : '');
            const title = clean(document.querySelector('h1')?.innerText || document.title || '');
            const priceNode = document.querySelector('[class*="price"], [class*="Price"]');
            const priceText = clean(priceNode ? (priceNode.innerText || priceNode.textContent) : '');
            const paramsRoot = document.querySelector('[class*="paramsInfoArea"]');
            if (paramsRoot) {
                Array.from(paramsRoot.querySelectorAll('[class^="emphasisParamsInfoItem--"], [class*=" emphasisParamsInfoItem--"]')).forEach((item) => {
                    const valueNode = item.querySelector('[class*="emphasisParamsInfoItemTitle"]');
                    const keyNode = item.querySelector('[class*="emphasisParamsInfoItemSubTitle"]');
                    addAttr(pickNodeText(keyNode), pickNodeText(valueNode));
                });
                Array.from(paramsRoot.querySelectorAll('[class^="generalParamsInfoItem--"], [class*=" generalParamsInfoItem--"]')).forEach((item) => {
                    const keyNode = item.querySelector('[class*="generalParamsInfoItemTitle"]');
                    const valueNode = item.querySelector('[class*="generalParamsInfoItemSubTitle"]');
                    addAttr(pickNodeText(keyNode), pickNodeText(valueNode));
                });
            }
            const collectBaseProps = (node, seen = new Set()) => {
                if (!node || typeof node !== 'object' || seen.has(node)) return;
                seen.add(node);
                if (node.type === 'BASE_PROPS' && Array.isArray(node.items)) {
                    node.items.forEach((item) => {
                        const text = Array.isArray(item.text) ? item.text.join(',') : item.text;
                        addAttr(item.title, text || item.value);
                    });
                }
                const children = Array.isArray(node) ? node : Object.values(node);
                children.forEach((child) => collectBaseProps(child, seen));
            };
            try {
                collectBaseProps(window.__ICE_APP_CONTEXT__);
            } catch (error) {}
            const parameterHead = Array.from(document.querySelectorAll('*')).find((node) => clean(node.innerText || node.textContent) === '参数信息');
            let parameterText = paramsRoot ? clean(paramsRoot.innerText || paramsRoot.textContent) : '';
            if (parameterHead) {
                let parent = parameterHead.parentElement;
                for (let depth = 0; depth < 6 && parent; depth++, parent = parent.parentElement) {
                    const text = clean(parent.innerText || parent.textContent);
                    if (text.includes('参数信息') && text.length > 20) {
                        parameterText = text.replace(/^参数信息\\s*/, '');
                        break;
                    }
                }
            }
            if (!parameterText) {
                const labels = ['控制系统', '支付方式', '型号', '设备种类', '颜色分类'];
                const found = labels.filter((label) => bodyText.includes(label));
                if (found.length) parameterText = bodyText;
            }
            return { title, priceText, parameterText, bodyText, attributes: attrs };
        }"""
    )
    parameter_text = clean_text(data.get("parameterText") or "")
    attrs = parse_parameter_lines(parameter_text)
    attrs.update(normalize_attrs(data.get("attributes")))
    title = clean_text(data.get("title") or "").replace("-淘宝网", "").replace("-天猫Tmall.com", "")
    price_text = clean_text(data.get("priceText") or "")

    return {
        "source_platform": "taobao",
        "item_id": item_id,
        "product_url": page.url,
        "title": title,
        "price_text": price_text,
        "model": pick_attr(attrs, "型号", "规格"),
        "control_system": pick_attr(attrs, "控制系统"),
        "payment_method": pick_attr(attrs, "支付方式"),
        "theme_style": pick_attr(attrs, "主题风格"),
        "color_category": pick_attr(attrs, "颜色分类"),
        "brand": pick_attr(attrs, "品牌"),
        "origin_place": pick_attr(attrs, "产地"),
        "applicable_scene": pick_attr(attrs, "适用场景"),
        "applicable_age": pick_attr(attrs, "适用年龄段"),
        "device_type": pick_attr(attrs, "设备种类"),
        "applicable_gender": pick_attr(attrs, "适用性别"),
        "attributes_json": json.dumps(attrs, ensure_ascii=False),
        "collected_at": collected_at,
        "capture_status": "success",
        "capture_note": "",
    }


def empty_detail(item_id: str, url: str, collected_at: str, status: str, note: str) -> dict[str, str]:
    return {
        "source_platform": "taobao",
        "item_id": item_id,
        "product_url": url,
        "title": "",
        "price_text": "",
        "model": "",
        "control_system": "",
        "payment_method": "",
        "theme_style": "",
        "color_category": "",
        "brand": "",
        "origin_place": "",
        "applicable_scene": "",
        "applicable_age": "",
        "device_type": "",
        "applicable_gender": "",
        "attributes_json": "{}",
        "collected_at": collected_at,
        "capture_status": status,
        "capture_note": note,
    }


def build_detail_targets(search_rows: list[dict[str, str]], max_details: int = 0) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in search_rows:
        item_id = row.get("item_id") or item_id_from_url(row.get("product_url", ""))
        product_url = normalize_url(row.get("product_url", ""))
        if not item_id or not product_url or item_id in seen:
            continue
        seen.add(item_id)
        targets.append({"item_id": item_id, "product_url": product_url})
        if max_details and len(targets) >= max_details:
            break
    return targets


def merge_search_and_detail_rows(search_rows: list[dict[str, str]], detail_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    search_by_item: dict[str, list[dict[str, str]]] = {}
    for row in search_rows:
        item_id = row.get("item_id") or item_id_from_url(row.get("product_url", ""))
        if not item_id:
            continue
        search_by_item.setdefault(item_id, []).append(row)

    detail_by_item = {row.get("item_id", ""): row for row in detail_rows if row.get("item_id")}
    item_ids = list(dict.fromkeys([*(search_by_item.keys()), *(detail_by_item.keys())]))
    merged: list[dict[str, str]] = []

    for item_id in item_ids:
        search_group = search_by_item.get(item_id, [])
        search = search_group[0] if search_group else {}
        detail = detail_by_item.get(item_id, {})
        keywords = "、".join(sorted({row.get("keyword", "") for row in search_group if row.get("keyword")}))
        status = detail.get("capture_status") or search.get("capture_status") or ""
        note = detail.get("capture_note") or search.get("capture_note") or ""
        merged.append(
            {
                "source_platform": "taobao",
                "item_id": item_id,
                "keywords": keywords,
                "product_url": detail.get("product_url") or search.get("product_url", ""),
                "product_title": search.get("product_title") or detail.get("title", ""),
                "detail_title": detail.get("title", ""),
                "search_price_text": search.get("price_text", ""),
                "detail_price_text": detail.get("price_text", ""),
                "shop_name": search.get("shop_name", ""),
                "shop_url": search.get("shop_url", ""),
                "location": search.get("location", ""),
                "sales_text": search.get("sales_text", ""),
                "image_url": search.get("image_url", ""),
                "model": detail.get("model", ""),
                "brand": detail.get("brand", ""),
                "control_system": detail.get("control_system", ""),
                "payment_method": detail.get("payment_method", ""),
                "theme_style": detail.get("theme_style", ""),
                "color_category": detail.get("color_category", ""),
                "origin_place": detail.get("origin_place", ""),
                "applicable_scene": detail.get("applicable_scene", ""),
                "applicable_age": detail.get("applicable_age", ""),
                "device_type": detail.get("device_type", ""),
                "applicable_gender": detail.get("applicable_gender", ""),
                "attributes_json": detail.get("attributes_json", "{}"),
                "collected_at": detail.get("collected_at") or search.get("collected_at", ""),
                "capture_status": status,
                "capture_note": note,
            }
        )
    return merged


def load_keywords(path: str | None, cli_keywords: list[str] | None) -> list[str]:
    if cli_keywords:
        return cli_keywords
    if path:
        values = [
            clean_text(line)
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if clean_text(line) and not clean_text(line).startswith("#")
        ]
        if values:
            return values
    return KEYWORDS


def write_full_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="淘宝公开商品搜索、详情参数和完整版 CSV 采集")
    parser.add_argument("--keyword", action="append", help="只采集指定关键词，可重复传入")
    parser.add_argument("--keyword-file", help="从 UTF-8 文本文件读取关键词，每行一个")
    parser.add_argument("--prepare-login", action="store_true", help="打开淘宝登录页，等待人工登录并保存本地浏览器登录态")
    parser.add_argument("--login-wait-seconds", type=int, default=240)
    parser.add_argument("--limit-per-keyword", type=int, default=2)
    parser.add_argument("--max-details", type=int, default=0, help="详情页最大补采数量；0 表示全部搜索结果")
    parser.add_argument("--skip-details", action="store_true", help="只采搜索结果，不打开详情页")
    parser.add_argument("--scroll-count", type=int, default=1)
    parser.add_argument("--delay-min", type=float, default=1.8)
    parser.add_argument("--delay-max", type=float, default=4.0)
    parser.add_argument("--debug", action="store_true", help="保存页面 HTML 和截图用于调试")
    parser.add_argument("--output", help="完整版 CSV 输出路径")
    args = parser.parse_args()

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    keywords = load_keywords(args.keyword_file, args.keyword)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_path = Path(args.output) if args.output else BASE_DIR / f"taobao_product_full_{stamp}.csv"
    if args.debug:
        DEBUG_DIR.mkdir(exist_ok=True)

    search_rows: list[dict[str, str]] = []
    detail_rows: list[dict[str, str]] = []
    executable_path = chrome_executable()

    with sync_playwright() as p:
        launch_kwargs: dict = {
            "headless": False,
            "args": ["--lang=zh-CN"],
        }
        if executable_path:
            launch_kwargs["executable_path"] = executable_path

        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
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
            login_url = "https://login.taobao.com/member/login.jhtml"
            print(f"[taobao] 已打开登录页：{login_url}")
            print("[taobao] 请在弹出的 Chrome 窗口中手动登录淘宝。")
            page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
            deadline = time.time() + args.login_wait_seconds
            while time.time() < deadline:
                current_url = page.url
                if "login.taobao.com" not in current_url and "login.tmall.com" not in current_url:
                    print(f"[taobao] 检测到已离开登录页：{current_url}")
                    break
                page.wait_for_timeout(3000)
            context.close()
            print("[taobao] 登录准备步骤结束。本地登录态已保存在 data-workflow/taobao/.browser-profile。")
            return

        for keyword in keywords:
            url = search_url(keyword)
            print(f"[taobao] 搜索：{keyword} -> {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                browse_like_user(page, args.scroll_count, args.delay_min, args.delay_max)
                body_text = page.locator("body").inner_text(timeout=5000)
                if args.debug:
                    safe_keyword = quote(keyword, safe="")
                    (DEBUG_DIR / f"{stamp}_search_{safe_keyword}.html").write_text(page.content(), encoding="utf-8")
                    page.screenshot(path=str(DEBUG_DIR / f"{stamp}_search_{safe_keyword}.png"), full_page=True)

                blocked, note = looks_blocked(body_text, page.url)
                if blocked:
                    print(f"[taobao] 受限：{keyword} - {note}")
                    search_rows.append(
                        {
                            "source_platform": "taobao",
                            "keyword": keyword,
                            "product_title": "",
                            "product_url": page.url,
                            "item_id": "",
                            "price_text": "",
                            "shop_name": "",
                            "shop_url": "",
                            "location": "",
                            "sales_text": "",
                            "image_url": "",
                            "collected_at": collected_at,
                            "capture_status": "blocked",
                            "capture_note": note,
                        }
                    )
                    continue

                keyword_rows = extract_search_cards(page, keyword, collected_at, args.limit_per_keyword)
                print(f"[taobao] 搜索解析到 {len(keyword_rows)} 条候选")
                search_rows.extend(keyword_rows)
                if not keyword_rows:
                    search_rows.append(
                        {
                            "source_platform": "taobao",
                            "keyword": keyword,
                            "product_title": "",
                            "product_url": page.url,
                            "item_id": "",
                            "price_text": "",
                            "shop_name": "",
                            "shop_url": "",
                            "location": "",
                            "sales_text": "",
                            "image_url": "",
                            "collected_at": collected_at,
                            "capture_status": "no_cards",
                            "capture_note": "页面未解析到公开商品卡片",
                        }
                    )
                human_pause(args.delay_min, args.delay_max)
            except PlaywrightTimeoutError as exc:
                print(f"[taobao] 搜索超时：{keyword}")
                search_rows.append(
                    {
                        "source_platform": "taobao",
                        "keyword": keyword,
                        "product_title": "",
                        "product_url": url,
                        "item_id": "",
                        "price_text": "",
                        "shop_name": "",
                        "shop_url": "",
                        "location": "",
                        "sales_text": "",
                        "image_url": "",
                        "collected_at": collected_at,
                        "capture_status": "timeout",
                        "capture_note": str(exc),
                    }
                )

        targets = [] if args.skip_details else build_detail_targets(search_rows, args.max_details)
        print(f"[taobao] 待补采详情：{len(targets)}")
        for target in targets:
            item_id = target["item_id"]
            url = target["product_url"]
            print(f"[taobao] 详情：{item_id} -> {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                browse_like_user(page, 1, args.delay_min, args.delay_max)
                body_text = page.locator("body").inner_text(timeout=5000)
                blocked, note = looks_blocked(body_text, page.url)
                if blocked:
                    print(f"[taobao] 详情受限：{item_id} - {note}")
                    detail_rows.append(empty_detail(item_id, page.url, collected_at, "blocked", note))
                    continue
                if args.debug:
                    page.screenshot(path=str(DEBUG_DIR / f"{stamp}_detail_{item_id}.png"), full_page=True)
                    (DEBUG_DIR / f"{stamp}_detail_{item_id}.html").write_text(page.content(), encoding="utf-8")
                detail = extract_detail(page, item_id, collected_at)
                attr_count = len(json.loads(detail["attributes_json"] or "{}"))
                detail_rows.append(detail)
                print(f"[taobao] 详情成功：{item_id} attrs={attr_count}")
                human_pause(args.delay_min, args.delay_max)
            except PlaywrightTimeoutError as exc:
                detail_rows.append(empty_detail(item_id, url, collected_at, "timeout", str(exc)))
            except Exception as exc:
                detail_rows.append(empty_detail(item_id, url, collected_at, "error", f"{type(exc).__name__}: {exc}"))

        context.close()

    full_rows = merge_search_and_detail_rows(search_rows, detail_rows)
    write_full_csv(full_rows, output_path)
    success_count = sum(1 for row in full_rows if row["capture_status"] == "success")
    print(f"[taobao] 输出完整版：{output_path}")
    print(f"[taobao] 搜索记录：{len(search_rows)}")
    print(f"[taobao] 详情记录：{len(detail_rows)}")
    print(f"[taobao] 完整版记录：{len(full_rows)}")
    print(f"[taobao] 成功记录：{success_count}")


if __name__ == "__main__":
    main()
