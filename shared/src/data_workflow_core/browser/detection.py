"""统一反爬检测（验证/登录/限流页面识别）。

所有浏览器采集脚本共用同一份标记与状态映射，避免各 adapter 各自实现
导致检测口径不一致。状态值对齐现有流程：
- human_verification_required：滑块/验证码/安全验证
- login_required：登录失效
- rate_limited：访问受限/限流
- ""：正常
"""

from __future__ import annotations

from typing import Protocol


RESTRICTION_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("滑块", "human_verification_required", "页面出现滑块验证"),
    ("captcha", "human_verification_required", "页面出现验证码"),
    ("安全验证", "human_verification_required", "页面出现安全验证"),
    ("punish", "human_verification_required", "页面出现安全验证"),
    ("请完成验证", "human_verification_required", "页面要求完成验证"),
    ("访问验证", "human_verification_required", "页面要求访问验证"),
    ("验证中心", "human_verification_required", "页面要求验证"),
    ("向右滑动验证", "human_verification_required", "页面要求滑动验证"),
    ("拖动下方滑块", "human_verification_required", "页面要求滑动验证"),
    # 阿里系特化：联系信息校验失效跳转（本库当前服务域）
    ("contactinfo_invalid", "human_verification_required", "联系信息校验失效"),
    ("login.1688.com", "login_required", "页面跳转到登录"),
    ("login.taobao.com", "login_required", "页面跳转到登录"),
    ("signin", "login_required", "页面要求登录"),
    ("请先登录", "login_required", "页面要求登录"),
    ("立即登录", "login_required", "页面要求登录"),
    ("登录后查看", "login_required", "页面要求登录"),
    ("访问受限", "rate_limited", "页面访问受限"),
)


def classify_restriction(page_text: str, page_url: str = "") -> tuple[str, str]:
    """根据页面文本与 URL 判定受限状态，返回 (status, note)；正常返回 ("", "")。"""
    text = page_text.lower()
    url = page_url.lower()
    for marker, status, note in RESTRICTION_MARKERS:
        if marker.lower() in text or marker.lower() in url:
            return status, note
    return "", ""


def looks_blocked(page_text: str, page_url: str = "") -> tuple[bool, str]:
    status, note = classify_restriction(page_text, page_url)
    return bool(status), note


class PageLike(Protocol):
    text: str
    url: str
    final_url: str | None = None
    title: str | None = None
    responses: list | None = None


def restriction_from_page(
    page: PageLike,
    *,
    extra_response_markers: tuple[str, ...] = (),
) -> str:
    """从已捕获页面（文本/URL/网络响应）判定受限状态。

    - 文本/URL 命中 RESTRICTION_MARKERS → 对应状态
    - 网络响应 403/429 → rate_limited
    - 网络响应含 /punish、captcha、x5step 或 extra_response_markers → 验证
    """
    text = getattr(page, "text", "") or ""
    url = getattr(page, "final_url", None) or getattr(page, "url", "") or ""
    title = getattr(page, "title", "") or ""
    status, _ = classify_restriction(f"{url}\n{title}\n{text}", url)
    if status:
        return status
    responses = getattr(page, "responses", None) or []
    for response in responses:
        body = getattr(response, "body", "") or ""
        response_text = f"{getattr(response, 'url', '')}\n{body}".lower()
        if getattr(response, "status", 0) in {403, 429}:
            return "rate_limited"
        if any(
            marker in response_text
            for marker in ("/punish", "captcha", "x5step") + tuple(extra_response_markers)
        ):
            return "human_verification_required"
    return ""
