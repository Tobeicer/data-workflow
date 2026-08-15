"""1688 平台任务层：搜索/详情/厂家采集任务（引擎之上的平台逻辑）。

本包只被 1688 采集使用；依赖规则：只允许引用引擎公开接口
（``data_workflow_core.engine``），不反向依赖引擎内部实现。
"""

from .records import (
    business_info_url,
    factory_archive_url,
    normalize_manufacturer_record,
    normalize_product_record,
    search_url,
)

__all__ = [
    "business_info_url",
    "factory_archive_url",
    "normalize_manufacturer_record",
    "normalize_product_record",
    "search_url",
]
