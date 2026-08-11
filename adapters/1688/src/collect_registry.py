"""1688 已采商品注册表（跨批次全局查重）。

目的：避免不同批次（不同关键词/不同时间）重复采集同一商品。
批次内去重由 sample_selector/checkpoint 承担；注册表解决跨批次问题。

文件：runtime/state/1688_collected_offers.json（git 忽略）

结构：
{
  "version": 1,
  "updated_at": "2026-08-11T09:00:00+08:00",
  "offers": {
    "<offer_id>": {
      "collected_at": "...",
      "validation_category": "A01",
      "member_id": "...",
      "run_id": "..."
    }
  },
  "companies": {
    "<member_id>": {"collected_at": "...", "run_id": "..."}
  }
}
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "runtime" / "state" / "1688_collected_offers.json"
)


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> dict:
    path = Path(path)
    if not path.is_file():
        return {"version": 1, "updated_at": "", "offers": {}, "companies": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.setdefault("offers", {})
        payload.setdefault("companies", {})
        return payload
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "updated_at": "", "offers": {}, "companies": {}}


def save_registry(registry: dict, path: Path | str = DEFAULT_REGISTRY_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    registry["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_offer(
    registry: dict,
    *,
    offer_id: str,
    validation_category: str = "",
    member_id: str = "",
    run_id: str = "",
) -> bool:
    """登记一个已采商品；返回是否为新登记（True=此前未登记）。"""
    offer_id = str(offer_id or "").strip()
    if not offer_id:
        return False
    if offer_id in registry["offers"]:
        return False
    registry["offers"][offer_id] = {
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "validation_category": str(validation_category or ""),
        "member_id": str(member_id or ""),
        "run_id": str(run_id or ""),
    }
    return True


def register_company(registry: dict, *, member_id: str, run_id: str = "") -> bool:
    """登记一个已采厂家；返回是否为新登记。"""
    member_id = str(member_id or "").strip()
    if not member_id:
        return False
    if member_id in registry["companies"]:
        return False
    registry["companies"][member_id] = {
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": str(run_id or ""),
    }
    return True


def register_offers_bulk(
    registry: dict,
    items: Iterable[dict],
) -> int:
    """批量登记（items: offer_id/validation_category/member_id 字典）；返回新登记数。"""
    added = 0
    for item in items:
        if register_offer(
            registry,
            offer_id=str(item.get("offer_id") or ""),
            validation_category=str(item.get("validation_category") or ""),
            member_id=str(item.get("member_id") or ""),
            run_id=str(item.get("run_id") or ""),
        ):
            added += 1
    return added


def collected_offer_ids(registry: dict) -> set[str]:
    return set(registry.get("offers", {}))


def collected_member_ids(registry: dict) -> set[str]:
    return set(registry.get("companies", {}))
