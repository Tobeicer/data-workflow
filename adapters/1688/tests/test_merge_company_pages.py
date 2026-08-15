import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
ADAPTER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(ADAPTER_DIR))

from merge_company_pages import load_records, merge_records  # noqa: E402


def record(member: str, pages: list[dict]) -> dict:
    return {
        "source_platform": "1688",
        "member_id": member,
        "shop_url": "",
        "collected_at": "2026-08-14T10:00:00+08:00",
        "pages": pages,
    }


def test_override_replaces_empty_business_page(tmp_path: Path) -> None:
    base = {
        "b2b-1": record(
            "b2b-1",
            [
                {"page_type": "factory_archive", "url": "https://sale.1688.com/f", "text": "工厂档案"},
                {"page_type": "business_info", "url": "https://wp.m.1688.com/b", "text": ""},
                {"page_type": "credit_detail", "url": "https://s1.1688.com/c", "text": "公司名 某厂"},
            ],
        )
    }
    override = {
        "b2b-1": record(
            "b2b-1",
            [
                {
                    "page_type": "business_info",
                    "url": "https://wp.m.1688.com/b",
                    "text": "公司名称\n某厂\n统一社会信用代码\n9144XXX",
                }
            ],
        )
    }
    merged = merge_records(base, override)
    pages = {p["page_type"]: p for p in merged["b2b-1"]["pages"]}

    assert "统一社会信用代码" in pages["business_info"]["text"]
    assert pages["factory_archive"]["text"] == "工厂档案"
    assert pages["credit_detail"]["text"] == "公司名 某厂"
    assert len(merged["b2b-1"]["pages"]) == 3


def test_override_keeps_old_page_when_rerun_still_empty(tmp_path: Path) -> None:
    base = {
        "b2b-2": record(
            "b2b-2", [{"page_type": "business_info", "url": "https://wp.m.1688.com/b", "text": ""}]
        )
    }
    override = {
        "b2b-2": record(
            "b2b-2", [{"page_type": "business_info", "url": "https://wp.m.1688.com/b", "text": ""}]
        )
    }
    merged = merge_records(base, override)
    pages = merged["b2b-2"]["pages"]

    assert len(pages) == 1
    assert pages[0]["text"] == ""


def test_override_appends_new_member(tmp_path: Path) -> None:
    base = {"b2b-1": record("b2b-1", [{"page_type": "business_info", "text": "x"}])}
    override = {"b2b-9": record("b2b-9", [{"page_type": "business_info", "text": "y"}])}
    merged = merge_records(base, override)

    assert set(merged) == {"b2b-1", "b2b-9"}


def test_load_records_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "raw.jsonl"
    path.write_text(
        json.dumps(record("b2b-1", [{"page_type": "business_info", "text": "a"}]))
        + "\n"
        + json.dumps(record("b2b-2", [{"page_type": "business_info", "text": "b"}]))
        + "\n",
        encoding="utf-8",
    )
    loaded = load_records(path)

    assert set(loaded) == {"b2b-1", "b2b-2"}
