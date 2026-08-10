from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlparse

from company_profile import parse_company_asset


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SRC_DIR = Path(__file__).resolve().parent
WORKFLOW_DIR = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE_DIR = WORKFLOW_DIR / "runtime" / "browser-profiles" / "1688"
DEFAULT_PACING_CHECKPOINT = WORKFLOW_DIR / "runtime" / "state" / "1688_pacing.json"
CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)

sys.path.insert(0, str(WORKFLOW_DIR / "shared" / "src"))

from data_workflow_core.adaptive_pacing import (  # noqa: E402
    AdaptivePacer,
    build_pacer,
)
from data_workflow_core.browser_stealth import (  # noqa: E402
    apply_stealth,
    stealth_launch_args,
)


@dataclass
class CapturedResponse:
    url: str
    status: int
    body: str


@dataclass
class CapturedPage:
    page_type: str
    requested_url: str
    final_url: str
    title: str
    html: str
    text: str
    responses: list[CapturedResponse] = field(default_factory=list)
    network_urls: list[str] = field(default_factory=list)
    structured_data: dict = field(default_factory=dict)


class BrowserSession(Protocol):
    def capture(self, page_type: str, url: str) -> CapturedPage: ...


def chrome_executable() -> str | None:
    return next((str(path) for path in CHROME_PATHS if path.exists()), None)


def product_url(offer_id: str) -> str:
    return f"https://detail.1688.com/offer/{offer_id}.html"


def business_info_url(member_id: str) -> str:
    return (
        "https://wp.m.1688.com/page/businessinfor.html"
        f"?memberId={quote(member_id, safe='-')}"
        "&bizCode=winport"
    )


def factory_archive_url(member_id: str) -> str:
    encoded_member_id = quote(member_id, safe="-")
    return (
        "https://sale.1688.com/factory/card.html"
        f"?memberId={encoded_member_id}"
        "&__recSource__=win_port"
        f"&facMemId={encoded_member_id}"
    )


def normalize_shop_base(value: str) -> str:
    text = value.strip()
    if text.startswith("//"):
        text = "https:" + text
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.netloc:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}"


def decode_json_string(value: str) -> str:
    try:
        return json.loads('"' + value + '"')
    except json.JSONDecodeError:
        return value.replace(r"\/", "/")


def first_json_string(html: str, key: str) -> str:
    pattern = rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"'
    match = re.search(pattern, html)
    return decode_json_string(match.group(1)) if match else ""


def json_object_after_key(html: str, key: str) -> dict:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{', html)
    if not match:
        return {}
    start = html.find("{", match.start())
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(html[start : index + 1])
                except json.JSONDecodeError:
                    return {}
                return value if isinstance(value, dict) else {}
    return {}


def extract_seller_identity(html: str) -> dict[str, str]:
    seller_model = json_object_after_key(html, "sellerModel")
    winport_map = seller_model.get("sellerWinportUrlMap") or {}
    if not isinstance(winport_map, dict):
        winport_map = {}
    member_id = str(seller_model.get("memberId") or "").strip()
    if not member_id:
        member_matches = re.findall(r'"memberId"\s*:\s*"(b2b-[^"]+)"', html)
        member_id = member_matches[-1] if member_matches else first_json_string(html, "memberId")
    shop_url = normalize_shop_base(
        str(seller_model.get("winportUrl") or winport_map.get("defaultUrl") or "")
    )
    if not shop_url:
        shop_match = re.search(r'https?:\\?/\\?/([a-zA-Z0-9-]+\.1688\.com)', html)
        if shop_match:
            shop_url = "https://" + shop_match.group(1)
    return {
        "company_name": str(seller_model.get("companyName") or "").strip()
        or first_json_string(html, "companyName"),
        "member_id": member_id,
        "login_id": str(seller_model.get("loginId") or "").strip()
        or first_json_string(html, "loginId"),
        "shop_url": shop_url,
    }


def restriction_status(page: CapturedPage) -> str:
    combined = f"{page.final_url}\n{page.title}\n{page.text}".lower()
    if any(marker in combined for marker in (
        "captcha",
        "滑块",
        "安全验证",
        "请完成验证",
        "访问验证",
        "验证中心",
        "向右滑动验证",
        "拖动下方滑块",
        "contactinfo_invalid",
    )):
        return "human_verification_required"
    if "login.1688.com" in combined or "login.taobao.com" in combined:
        return "login_required"
    if any(marker in combined for marker in ("请先登录", "立即登录后", "登录后查看")):
        return "login_required"
    for response in page.responses:
        response_text = f"{response.url}\n{response.body}".lower()
        if response.status in {403, 429}:
            return "rate_limited"
        if any(
            marker in response_text
            for marker in ("/punish", "captcha", "x5step", "contactinfo_invalid")
        ):
            return "human_verification_required"
    return ""


def retry_after_human_verification(
    browser: BrowserSession,
    page: CapturedPage,
    *,
    page_type: str,
    url: str,
    timeout_seconds: int,
) -> tuple[CapturedPage, str]:
    current = page
    blocked = restriction_status(current)
    waiter = getattr(browser, "wait_for_human_verification", None)
    for _ in range(3):
        if blocked != "human_verification_required" or timeout_seconds <= 0:
            break
        if not callable(waiter) or not waiter(timeout_seconds=timeout_seconds):
            break
        current = browser.capture(page_type, url)
        blocked = restriction_status(current)
    return current, blocked


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, value: object) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    write_text(path, content)


def sanitize_html_for_storage(html: str) -> str:
    sanitized = re.sub(
        r"<script\b[^>]*>.*?</script\s*>",
        "",
        str(html or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    sanitized = re.sub(
        r"<(?:input|textarea|select)\b[^>]*>.*?</(?:textarea|select)\s*>",
        "",
        sanitized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    sanitized = re.sub(
        r"<input\b[^>]*>",
        "",
        sanitized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return sanitized


def persist_page(
    page: CapturedPage,
    *,
    l0_dir: Path,
    page_manifest: list[dict],
    response_manifest: list[dict],
) -> None:
    html_path = l0_dir / f"{page.page_type}.html"
    text_path = l0_dir / f"{page.page_type}.txt"
    stored_html = sanitize_html_for_storage(page.html)
    write_text(html_path, stored_html)
    write_text(text_path, page.text)
    network_path = l0_dir / "network_urls" / f"{page.page_type}.json"
    write_json(network_path, page.network_urls)
    page_manifest.append(
        {
            "page_type": page.page_type,
            "requested_url": page.requested_url,
            "final_url": page.final_url,
            "title": page.title,
            "html_file": html_path.relative_to(l0_dir.parent).as_posix(),
            "text_file": text_path.relative_to(l0_dir.parent).as_posix(),
            "network_file": network_path.relative_to(l0_dir.parent).as_posix(),
            "html_sha256": sha256_text(stored_html),
            "html_bytes": len(stored_html.encode("utf-8")),
            "response_count": len(page.responses),
            "network_count": len(page.network_urls),
        }
    )
    response_dir = l0_dir / "api_responses"
    for response in page.responses:
        index = len(response_manifest) + 1
        response_path = response_dir / f"{index:03d}_{page.page_type}.txt"
        write_text(response_path, response.body)
        response_manifest.append(
            {
                "page_type": page.page_type,
                "url": response.url,
                "status": response.status,
                "file": response_path.relative_to(l0_dir.parent).as_posix(),
                "sha256": sha256_text(response.body),
                "bytes": len(response.body.encode("utf-8")),
            }
        )


def find_response(pages: list[CapturedPage], fragment: str) -> CapturedResponse | None:
    return next(
        (
            response
            for page in pages
            for response in page.responses
            if urlparse(response.url).netloc.lower() == "h5api.m.1688.com"
            and (
                fragment.lower() in response.url.lower()
                or fragment.lower() in response.body.lower()
            )
            and response.body
        ),
        None,
    )


def add_tpdocument_source_urls(
    source_urls: dict[str, str], tp_responses: dict[str, CapturedResponse | None]
) -> dict[str, str]:
    merged = dict(source_urls)
    for name, response in tp_responses.items():
        if response:
            merged[f"tpdocument_{name}"] = response.url
    return merged


def save_run_result(output_dir: Path, result: dict) -> dict:
    write_json(
        output_dir / "run_manifest.json",
        {
            "manifest_version": "1.0",
            "source_platform": result.get("source_platform", "1688"),
            "offer_id": result.get("offer_id", ""),
            "member_id": result.get("member_id", ""),
            "company_id": result.get("company_id", ""),
            "collected_at": result.get("collected_at", ""),
            "status": result.get("status", "error"),
            "completed_pages": result.get("completed_pages", []),
            "counts": result.get("counts", {}),
            "outputs": result.get("outputs", {}),
            "run_result": "run_result.json",
        },
    )
    write_json(output_dir / "run_result.json", result)
    return result


def run_company_pilot(
    *,
    offer_id: str,
    output_dir: Path,
    browser: BrowserSession,
    collected_at: str | None = None,
    verification_wait_seconds: int = 240,
) -> dict:
    offer_id = re.sub(r"\D", "", str(offer_id))
    if not offer_id:
        raise ValueError("offer_id 必须包含数字")
    output_dir = Path(output_dir)
    l0_dir = output_dir / "l0"
    l1_dir = output_dir / "l1"
    l2_dir = output_dir / "l2"
    collected_at = collected_at or datetime.now().astimezone().isoformat()
    page_manifest: list[dict] = []
    response_manifest: list[dict] = []
    pages: list[CapturedPage] = []

    product = browser.capture("product", product_url(offer_id))
    pages.append(product)
    persist_page(
        product,
        l0_dir=l0_dir,
        page_manifest=page_manifest,
        response_manifest=response_manifest,
    )
    product, blocked = retry_after_human_verification(
        browser,
        product,
        page_type="product",
        url=product_url(offer_id),
        timeout_seconds=verification_wait_seconds,
    )
    if product is not pages[-1]:
        pages[-1] = product
        persist_page(
            product,
            l0_dir=l0_dir,
            page_manifest=page_manifest,
            response_manifest=response_manifest,
        )
    if blocked:
        write_json(l0_dir / "page_manifest.json", page_manifest)
        write_json(l0_dir / "api_responses" / "manifest.json", response_manifest)
        return save_run_result(
            output_dir,
            {
                "source_platform": "1688",
                "offer_id": offer_id,
                "collected_at": collected_at,
                "status": blocked,
                "completed_pages": ["product"],
                "message": "页面要求人工处理，采集器已停止且未绕过验证。",
            },
        )

    identity = extract_seller_identity(product.html)
    member_id = identity["member_id"]
    shop_base = identity["shop_url"]
    if not member_id or not shop_base:
        write_json(l0_dir / "page_manifest.json", page_manifest)
        write_json(l0_dir / "api_responses" / "manifest.json", response_manifest)
        return save_run_result(
            output_dir,
            {
                "source_platform": "1688",
                "offer_id": offer_id,
                "collected_at": collected_at,
                "status": "company_entry_missing",
                "completed_pages": ["product"],
                "identity": identity,
                "message": "商品页未同时取得 memberId 和规范化店铺地址。",
            },
        )

    page_targets = (
        ("shop", f"{shop_base}/page/index.html"),
        ("credit_detail", f"{shop_base}/page/creditdetail.html"),
        ("factory_archive", factory_archive_url(member_id)),
        ("contact_info", f"{shop_base}/page/contactinfo.html"),
        ("business_info", business_info_url(member_id)),
    )
    for page_type, url in page_targets:
        captured = browser.capture(page_type, url)
        pages.append(captured)
        persist_page(
            captured,
            l0_dir=l0_dir,
            page_manifest=page_manifest,
            response_manifest=response_manifest,
        )
        refreshed, blocked = retry_after_human_verification(
            browser,
            captured,
            page_type=page_type,
            url=url,
            timeout_seconds=verification_wait_seconds,
        )
        if refreshed is not captured:
            pages[-1] = refreshed
            persist_page(
                refreshed,
                l0_dir=l0_dir,
                page_manifest=page_manifest,
                response_manifest=response_manifest,
            )
        if blocked:
            write_json(l0_dir / "page_manifest.json", page_manifest)
            write_json(l0_dir / "api_responses" / "manifest.json", response_manifest)
            return save_run_result(
                output_dir,
                {
                    "source_platform": "1688",
                    "offer_id": offer_id,
                    "member_id": member_id,
                    "collected_at": collected_at,
                    "status": blocked,
                    "completed_pages": [page.page_type for page in pages],
                    "message": "页面要求人工处理，采集器已停止且未绕过验证。",
                },
            )

    write_json(l0_dir / "page_manifest.json", page_manifest)
    write_json(l0_dir / "api_responses" / "manifest.json", response_manifest)

    header = find_response(pages, "wp_pc_common_header")
    business = find_response(pages, "wp_pc_shop_basic_info")
    factory_archive_response = find_response(pages, "factory.card.common")
    tp_names = ("certificate", "patent", "regchanges", "credit")
    tp_responses = {name: find_response(pages, f"tpdocument.{name}") for name in tp_names}
    by_type = {page.page_type: page for page in pages}
    source_urls = {
        "company_header": header.url if header else by_type["credit_detail"].final_url,
        "credit_detail": by_type["credit_detail"].final_url,
        "factory_archive": by_type["factory_archive"].final_url,
        "contact_info": by_type["contact_info"].final_url,
        "business_info": by_type["business_info"].final_url,
    }
    if factory_archive_response:
        source_urls["factory_archive_api"] = factory_archive_response.url
    source_urls = add_tpdocument_source_urls(source_urls, tp_responses)

    try:
        company_asset = parse_company_asset(
            header_body=header.body if header else "",
            credit_detail_text=by_type["credit_detail"].text,
            factory_archive_text=by_type["factory_archive"].text,
            factory_archive_body=(
                factory_archive_response.body if factory_archive_response else ""
            ),
            contact_text=by_type["contact_info"].text,
            tpdocument_bodies={
                name: response.body if response else ""
                for name, response in tp_responses.items()
            },
            source_urls=source_urls,
            collected_at=collected_at,
            member_id=member_id,
            business_info_body=business.body if business else "",
            business_info_text=by_type["business_info"].text,
        )
    except Exception as exc:
        return save_run_result(
            output_dir,
            {
                "source_platform": "1688",
                "offer_id": offer_id,
                "member_id": member_id,
                "collected_at": collected_at,
                "status": "parser_drift",
                "completed_pages": [page.page_type for page in pages],
                "error": f"{type(exc).__name__}: {exc}",
                "counts": {
                    "pages": len(pages),
                    "api_responses": len(response_manifest),
                },
                "outputs": {
                    "page_manifest": "l0/page_manifest.json",
                    "response_manifest": "l0/api_responses/manifest.json",
                },
            },
        )
    status = "success" if header and business else "partial_success"
    company_asset["capture_status"] = status
    write_json(l1_dir / "company_asset.json", company_asset)

    company = company_asset["company"]
    product_record = {
        "source_platform": "1688",
        "offer_id": offer_id,
        "product_url": product.final_url,
        "title": product.title,
        "supplier_company_candidate": identity["company_name"],
        "collected_at": collected_at,
    }
    shop_record = {
        "source_platform": "1688",
        "member_id": member_id,
        "login_id": identity["login_id"],
        "shop_url": shop_base,
        "shop_name": identity["company_name"],
        "collected_at": collected_at,
    }
    write_jsonl(l1_dir / "products.jsonl", [product_record])
    write_jsonl(l1_dir / "shops.jsonl", [shop_record])
    write_jsonl(l1_dir / "companies.jsonl", [company])
    write_jsonl(
        l1_dir / "subject_qualifications.jsonl",
        [{**company_asset["subject_qualification"], "member_id": member_id}],
    )
    write_jsonl(l1_dir / "factory_profiles.jsonl", company_asset["factory_snapshots"])
    write_jsonl(l1_dir / "certificates.jsonl", company_asset["certificate_details"]["items"])
    write_jsonl(l1_dir / "patents.jsonl", company_asset["patent_details"]["items"])
    write_jsonl(l1_dir / "contacts.jsonl", [company_asset["contacts"]])
    write_jsonl(l1_dir / "company_media.jsonl", company_asset["company_media"])

    relation_common = {
        "source_platform": "1688",
        "collected_at": collected_at,
        "match_method": "product_embedded_member_id_and_official_business_info",
        "confidence": 1.0,
    }
    write_jsonl(
        l2_dir / "product_shop_relations.jsonl",
        [
            {
                **relation_common,
                "offer_id": offer_id,
                "member_id": member_id,
                "relation_type": "published_by_shop",
                "source_url": product.final_url,
            }
        ],
    )
    write_jsonl(
        l2_dir / "product_company_relations.jsonl",
        [
            {
                **relation_common,
                "offer_id": offer_id,
                "company_id": company.get("company_id", ""),
                "unified_social_credit_code": company.get("unified_social_credit_code", ""),
                "relation_type": "supplier_candidate_confirmed_by_member_id",
                "source_url": by_type["business_info"].final_url,
            }
        ],
    )
    write_jsonl(
        l2_dir / "shop_company_relations.jsonl",
        [
            {
                **relation_common,
                "member_id": member_id,
                "company_id": company.get("company_id", ""),
                "unified_social_credit_code": company.get("unified_social_credit_code", ""),
                "relation_type": "official_1688_business_qualification",
                "source_url": by_type["business_info"].final_url,
            }
        ],
    )

    review_queue: list[dict] = []
    source_company_name = identity["company_name"]
    official_company_name = company.get("company_name", "")
    if source_company_name and official_company_name and source_company_name != official_company_name:
        review_queue.append(
            {
                "review_type": "identity_conflict",
                "offer_id": offer_id,
                "member_id": member_id,
                "source_company_name": source_company_name,
                "official_company_name": official_company_name,
                "source_url": by_type["business_info"].final_url,
                "collected_at": collected_at,
            }
        )
    write_jsonl(l2_dir / "review_queue.jsonl", review_queue)

    required_company_fields = (
        "company_name",
        "member_id",
        "unified_social_credit_code",
        "legal_representative",
        "registered_capital_text",
        "established_date",
        "registered_address",
        "business_scope",
    )
    missing_fields = [field for field in required_company_fields if not company.get(field)]
    quality_report = {
        "source_platform": "1688",
        "offer_id": offer_id,
        "member_id": member_id,
        "collected_at": collected_at,
        "status": status,
        "page_count": len(pages),
        "api_response_count": len(response_manifest),
        "field_evidence_count": len(company_asset["field_evidence"]),
        "company_media_count": len(company_asset["company_media"]),
        "factory_snapshot_count": len(company_asset["factory_snapshots"]),
        "missing_required_company_fields": missing_fields,
        "review_queue_count": len(review_queue),
    }
    write_json(l2_dir / "quality_report.json", quality_report)

    return save_run_result(
        output_dir,
        {
            "source_platform": "1688",
            "offer_id": offer_id,
            "member_id": member_id,
            "company_id": company.get("company_id", ""),
            "company_name": company.get("company_name", ""),
            "collected_at": collected_at,
            "status": status,
            "completed_pages": [page.page_type for page in pages],
            "counts": {
                "pages": len(pages),
                "api_responses": len(response_manifest),
                "field_evidence": len(company_asset["field_evidence"]),
                "company_media": len(company_asset["company_media"]),
                "review_queue": len(review_queue),
            },
            "outputs": {
                "company_asset": "l1/company_asset.json",
                "subject_qualifications": "l1/subject_qualifications.jsonl",
                "quality_report": "l2/quality_report.json",
                "page_manifest": "l0/page_manifest.json",
                "response_manifest": "l0/api_responses/manifest.json",
            },
        },
    )


class PlaywrightBrowserSession:
    def __init__(
        self,
        *,
        profile_dir: Path,
        screenshot_dir: Path,
        delay_seconds: float = 5.0,
        debug: bool = False,
        headless: bool = False,
        stealth: bool = True,
        pacing: AdaptivePacer | None = None,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.screenshot_dir = Path(screenshot_dir)
        self.delay_seconds = max(float(delay_seconds), 0.0)
        self.debug = debug
        self.headless = headless
        self.stealth = stealth
        self.pacing = pacing
        self._playwright = None
        self._context = None
        self._page = None

    def __enter__(self) -> "PlaywrightBrowserSession":
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        launch_kwargs: dict = {
            "headless": self.headless,
            "args": stealth_launch_args() if self.stealth
            else ["--disable-blink-features=AutomationControlled", "--lang=zh-CN"],
        }
        executable = chrome_executable()
        if executable:
            launch_kwargs["executable_path"] = executable
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            **launch_kwargs,
            locale="zh-CN",
            viewport={"width": 1365, "height": 900},
        )
        if self.stealth:
            apply_stealth(self._context)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()

    def wait_for_human_verification(self, *, timeout_seconds: int = 240) -> bool:
        if self._page is None or self.headless or timeout_seconds <= 0:
            return False
        page = self._page
        print(f"[1688] 当前页面需要人工验证，浏览器将保持打开 {timeout_seconds} 秒。")
        print("[1688] 请在浏览器中完成滑块；成功后当前页面会自动重新采集。")
        deadline = time.time() + timeout_seconds
        markers = (
            "captcha",
            "滑块",
            "安全验证",
            "请完成验证",
            "访问验证",
            "验证中心",
            "向右滑动验证",
            "拖动下方滑块",
        )
        clear_streak = 0
        while time.time() < deadline:
            try:
                body_text = page.locator("body").inner_text(timeout=1500)
            except Exception:
                body_text = ""
            try:
                verification_frame_count = page.locator(
                    'iframe[src*="punish"], iframe[src*="captcha"], '
                    'iframe[src*="_____tmd_____"]'
                ).count()
            except Exception:
                verification_frame_count = 0
            combined = f"{page.url}\n{page.title()}\n{body_text}".lower()
            normal_page = (
                len(body_text.strip()) >= 100
                and verification_frame_count == 0
                and not any(marker in combined for marker in markers)
                and "/punish" not in page.url.lower()
                and "login.1688.com" not in page.url.lower()
                and "login.taobao.com" not in page.url.lower()
            )
            clear_streak = clear_streak + 1 if normal_page else 0
            if clear_streak >= 2:
                print("[1688] 检测到人工验证已完成。")
                return True
            page.wait_for_timeout(2000)
        print("[1688] 人工验证等待超时，保留断点后退出。")
        return False

    @staticmethod
    def relevant_response(url: str) -> bool:
        lowered = url.lower()
        return any(
            marker in lowered
            for marker in (
                "wp_pc_common_header",
                "wp_pc_shop_basic_info",
                "wp_pc_certification",
                "getshopmarketinfo",
                "moduleasyncservice",
                "tpdocument.",
                "factory.card.common",
                "factory-card-common",
                "mtop.1688.mmga.offerdetail.service",
                "mtop.1688.moga.pc.shopcard",
            )
        )

    @staticmethod
    def extract_product_structure(page) -> dict:
        return page.evaluate(
            r"""() => {
                const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
                const pickText = (selectors) => {
                    for (const selector of selectors) {
                        const node = document.querySelector(selector);
                        const text = clean(node && (node.innerText || node.textContent));
                        if (text) return text;
                    }
                    return '';
                };
                const attrs = {};
                const rows = Array.from(document.querySelectorAll(
                    '[data-module="od_product_attributes"] tr, #productAttributes tr, .module-od-product-attributes tr'
                ));
                for (const row of rows) {
                    const cells = Array.from(row.querySelectorAll('th,td'));
                    for (let index = 0; index + 1 < cells.length; index += 2) {
                        const key = clean(cells[index].innerText || cells[index].textContent).replace(/[:：]$/, '');
                        const value = clean(cells[index + 1].innerText || cells[index + 1].textContent);
                        if (key && value && key.length <= 30) attrs[key] = value;
                    }
                }
                const skuRows = [];
                for (const node of Array.from(document.querySelectorAll('.expand-view-list .expand-view-item'))) {
                    const labelNode = node.querySelector('.item-label');
                    const label = clean(labelNode && (labelNode.innerText || labelNode.textContent));
                    const values = Array.from(node.querySelectorAll('.item-price-stock'))
                        .map((item) => clean(item.innerText || item.textContent)).filter(Boolean);
                    const image = node.querySelector('img');
                    if (label || values.length) {
                        skuRows.push({
                            label,
                            text: clean([label, ...values].join(' ')),
                            priceText: values[0] || '',
                            stockText: values[1] || '',
                            imageUrl: image ? (image.currentSrc || image.src || image.getAttribute('src') || '') : '',
                        });
                    }
                }
                const related = [];
                for (const anchor of Array.from(document.querySelectorAll(
                    'a[href*="/offer/"], a[href*="offerId="]'
                )).slice(0, 80)) {
                    const text = clean(anchor.innerText || anchor.textContent);
                    const href = anchor.href || anchor.getAttribute('href') || '';
                    if (href && text && text.length > 4) related.push({text, href});
                }
                // 包装信息表：表头含 长/体积/重量 的表格（规格 × 长宽高/体积/重量）
                const packRows = [];
                for (const table of Array.from(document.querySelectorAll('table'))) {
                    const head = (table.innerText || '').slice(0, 300);
                    if (head.includes('长') && head.includes('体积') && head.includes('重量')) {
                        for (const tr of Array.from(table.querySelectorAll('tr'))) {
                            const row = Array.from(tr.querySelectorAll('td, th')).map(
                                (cell) => clean(cell.innerText || cell.textContent)
                            );
                            if (row.length >= 2) packRows.push(row);
                        }
                        break;
                    }
                }
                return {
                    title: (document.title || '').replace(/ - 阿里巴巴$/, ''),
                    priceText: pickText([
                        '[data-module="od_consign"] .item-price',
                        '.module-od-consign .item-price',
                        '.price-text'
                    ]),
                    supplierName: pickText([
                        '[class*="company"] [class*="name"]',
                        '[class*="supplier"]',
                        '[class*="shop"] [class*="name"]'
                    ]),
                    moduleContext: (
                        window.context && window.context.result && window.context.result.data
                    ) || {},
                    attrs,
                    skuRows,
                    related,
                    packRows,
                };
            }"""
        )

    @staticmethod
    def extract_detail_images(page) -> list[str]:
        """点击「商品详情」tab 并滚动触发懒加载，收集详情区图片 URL。"""
        try:
            page.evaluate(
                """() => {
                    const nodes = Array.from(document.querySelectorAll('*'));
                    const tab = nodes.find(
                        (node) => node.innerText && node.innerText.trim() === '商品详情'
                            && node.children.length === 0
                    );
                    if (tab) tab.click();
                }"""
            )
            page.wait_for_timeout(2000)
            for _ in range(3):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(600)
        except Exception:
            return []
        return page.evaluate(
            """() => {
                const urls = [];
                document.querySelectorAll('img').forEach((img) => {
                    const src = img.currentSrc || img.src
                        || img.getAttribute('data-lazyload') || img.getAttribute('data-src') || '';
                    if (src && src.includes('alicdn') && !src.includes('tps-')
                        && !src.includes('_sum.') && src.length > 40) {
                        urls.push(src);
                    }
                });
                return Array.from(new Set(urls));
            }"""
        )

    def capture(self, page_type: str, url: str) -> CapturedPage:
        if self._page is None:
            raise RuntimeError("PlaywrightBrowserSession 尚未启动")
        page = self._page
        responses: list[CapturedResponse] = []
        network_urls: list[str] = []

        def on_response(response) -> None:
            network_urls.append(response.url)
            if not self.relevant_response(response.url):
                return
            try:
                responses.append(
                    CapturedResponse(
                        url=response.url,
                        status=response.status,
                        body=response.text(),
                    )
                )
            except Exception:
                return

        page.on("response", on_response)
        if self.pacing is not None:
            self.pacing.wait_for_next()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if self.pacing is None:
                page.wait_for_timeout(int(self.delay_seconds * 1000))
            else:
                # 节奏由 pacer 接管，页面稳定等待模拟阅读停顿（2-3.5s 随机）
                page.wait_for_timeout(
                    int((2000 + random.uniform(0, 1500)))
                )
            if page_type in {
                "product",
                "shop",
                "credit_detail",
                "factory_archive",
                "contact_info",
            }:
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(800)
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(800)
            html = page.content()
            try:
                text = page.locator("body").inner_text(timeout=5000)
            except Exception:
                text = ""
            if self.debug:
                self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(self.screenshot_dir / f"{page_type}.png"),
                    full_page=True,
                )
            structured_data = {}
            if page_type == "product":
                try:
                    structured_data = self.extract_product_structure(page)
                    structured_data["detailImages"] = self.extract_detail_images(page)
                except Exception:
                    structured_data = {}
            if self.pacing is not None:
                self.pacing.record_success()
            return CapturedPage(
                page_type=page_type,
                requested_url=url,
                final_url=page.url,
                title=page.title(),
                html=html,
                text=text,
                responses=responses,
                network_urls=network_urls,
                structured_data=structured_data,
            )
        except Exception:
            if self.pacing is not None:
                self.pacing.record_failure()
            raise
        finally:
            page.remove_listener("response", on_response)


def main() -> int:
    parser = argparse.ArgumentParser(description="1688 单商品公司全字段低频试采器")
    parser.add_argument("--offer-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--delay-seconds", type=float, default=8.0)
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--verification-wait-seconds", type=int, default=240)
    parser.add_argument("--no-stealth", action="store_true", help="不注入 stealth 指纹（默认注入）")
    parser.add_argument("--pacing-config", help="自适应频控配置 JSON，提供后启用自适应节奏")
    parser.add_argument("--pacing-checkpoint", default=str(DEFAULT_PACING_CHECKPOINT))
    parser.add_argument("--daily-cap", type=int, help="当日请求上限（配合 --pacing-config 使用）")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    pacing = (
        build_pacer(
            config_path=args.pacing_config,
            daily_cap=args.daily_cap,
            checkpoint=args.pacing_checkpoint,
        )
        if args.pacing_config
        else None
    )
    with PlaywrightBrowserSession(
        profile_dir=Path(args.profile_dir),
        screenshot_dir=output_dir / "l0" / "screenshots",
        delay_seconds=args.delay_seconds,
        debug=args.debug,
        headless=args.headless,
        stealth=not args.no_stealth,
        pacing=pacing,
    ) as browser:
        result = run_company_pilot(
            offer_id=args.offer_id,
            output_dir=output_dir,
            browser=browser,
            verification_wait_seconds=args.verification_wait_seconds,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] in {"success", "partial_success"}:
        return 0
    if result["status"] in {"login_required", "human_verification_required"}:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
