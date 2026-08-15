"""采集合规检查层：提取后的记录立即校验是否符合数据库字段要求。

铁律：有参数就取、没有就空值；但"取了"就必须合规——
- 价格原文只允许符号+数值，出现字母/中文/库存文本即标记 issue；
- 商品图片只允许真实商品图 URL，SVG、tps-、gg_dtc 图标、_sum 缩略图
  一律标记 issue（原图规则见字段规范 §4.6）；
- 必填身份字段（offer_id/title）缺失标记 issue。

L0 原始记录保留原样，issue 以附加字段 `quality_issues` 记录，
写库前由 db_delivery 校验门再次硬校验。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (_REPO_ROOT / "adapters" / "1688" / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from page_guards import looks_like_taobao_page  # noqa: E402

_PRICE_TAIL = re.compile(r"^[¥￥]?\s*\d+(?:\.\d+)?\s*$")
_PRICE_RANGE = re.compile(
    r"^[¥￥]?\s*\d+(?:\.\d+)?\s*[-~—]\s*[¥￥]?\s*\d+(?:\.\d+)?\s*$"
)
_BAD_IMAGE = re.compile(
    r"\.svg($|\?)|/tps-|gg_dtc|_sum\.(?:jpg|jpeg|png|webp)"
    r"|amos\.alicdn\.com|img\.taobao\.com|NewGualianyingxiao|online\.aw"
    r"|img\.alicdn\.com/L\d*?/",
    re.I,
)


def check_price_text(price_text: Any) -> bool:
    """SKU 价格原文应为"符号+单数值"；纯数值也接受，空值允许。"""
    text = str(price_text or "").strip()
    if not text:
        return True  # 空值允许（有就取、没有就空）
    return bool(_PRICE_TAIL.match(text))


def check_price_range_text(price_text: Any) -> bool:
    """商品级价格原文允许单数值或区间（¥34.8 / ¥34.8-120），空值允许。"""
    text = str(price_text or "").strip()
    if not text:
        return True
    return bool(_PRICE_TAIL.match(text) or _PRICE_RANGE.match(text))


def is_bad_image_url(url: Any) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    if not text.startswith(("http://", "https://")):
        return True
    return bool(_BAD_IMAGE.search(text))


def check_product_record(record: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    offer_id = str(record.get("offer_id") or "").strip()
    title = str(record.get("title") or "").strip()
    if not offer_id:
        issues.append("offer_id 缺失")
    if not title:
        issues.append("title 缺失")

    main_image = str(record.get("main_image_url") or "")
    if main_image and is_bad_image_url(main_image):
        issues.append(f"main_image 非真实商品图: {main_image[:80]}")
    for url in record.get("image_urls") or []:
        if is_bad_image_url(url):
            issues.append(f"轮播图混入非商品图: {str(url)[:80]}")
    for url in record.get("detail_images") or []:
        if is_bad_image_url(url):
            issues.append(f"详情图混入非商品图: {str(url)[:80]}")

    for index, sku in enumerate(record.get("sku_rows") or []):
        if not isinstance(sku, dict):
            continue
        if not check_price_text(sku.get("priceText")):
            issues.append(
                f"sku[{index}] 价格原文含杂质: {str(sku.get('priceText'))[:60]!r}"
            )
    if record.get("price_text") and not check_price_range_text(record.get("price_text")):
        issues.append(f"商品价格原文含杂质: {str(record.get('price_text'))[:60]!r}")
    return issues


def check_company_pages(pages: list[dict[str, Any]]) -> list[str]:
    """厂家四页结构检查：关键页文本非空、工商页含公司名标签。"""
    issues: list[str] = []
    by_type = {str(p.get("page_type")): p for p in pages if isinstance(p, dict)}
    business = by_type.get("business_info") or {}
    business_text = str(business.get("text") or "").strip()
    if not business_text:
        issues.append("business_info 文本为空（公司名/信用代码来源缺失）")
    elif "公司名称" not in business_text:
        issues.append("business_info 文本缺'公司名称'标签")
    factory = by_type.get("factory_archive") or {}
    if not str(factory.get("text") or "").strip():
        issues.append("factory_archive 文本为空")
    contact = by_type.get("contact_info") or {}
    if not str(contact.get("text") or "").strip():
        issues.append("contact_info 文本为空（联系方式来源缺失）")
    for page_type in ("credit_detail", "contact_info"):
        page = by_type.get(page_type) or {}
        text = str(page.get("text") or "")
        if looks_like_taobao_page(text):
            issues.append(
                f"{page_type} 被淘宝错误页/首页重定向污染（内容不可用，应丢弃该页文本）"
            )
    return issues
