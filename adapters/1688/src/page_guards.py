"""页面文本哨兵：识别被淘宝错误页/首页重定向污染的采集文本。

1688 某些基础设施域名（rule 等）上的无效路径会被阿里统一体系
重定向到淘宝侧错误页/首页；这类页面文本绝不能当作公司/联系方式证据。
"""

from __future__ import annotations

TAOBAO_PAGE_MARKERS = (
    "淘宝网首页",
    "已买到的宝贝",
    "我的淘宝",
    "千牛卖家中心",
    "tobeicer",
    "error.taobao.com",
)


def looks_like_taobao_page(text: str) -> bool:
    if not text:
        return False
    return any(marker in text for marker in TAOBAO_PAGE_MARKERS)
