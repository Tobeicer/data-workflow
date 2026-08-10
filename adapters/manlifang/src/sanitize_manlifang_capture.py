from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


PRODUCT_HINTS = (
    "product",
    "catalog",
    "category",
    "spu",
    "sku",
    "spec",
    "detail",
    "image",
    "picture",
    "attribute",
    "parameter",
)

SENSITIVE_HINTS = (
    "order",
    "cart",
    "member",
    "payment",
    "pay/",
    "address",
    "checkout",
    "invoice",
    "login",
    "auth",
    "coupon",
    "wallet",
    "userinfo",
    "/user/",
    "wxjsapi",
    "wechataudit",
    "encryption",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def normalized_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))


def product_flow(row: dict[str, Any]) -> bool:
    target = " ".join(
        str(row.get(key, ""))
        for key in ("host", "path", "endpoint", "response_file")
    ).lower()
    return not any(hint in target for hint in SENSITIVE_HINTS) and any(hint in target for hint in PRODUCT_HINTS)


def keep_discovered_image(row: dict[str, Any], kept_flow_ids: set[str]) -> bool:
    flow_id = str(row.get("flow_id", ""))
    if flow_id:
        return flow_id in kept_flow_ids
    return bool(
        row.get("product_id") not in (None, "")
        and row.get("url")
        and product_flow({"endpoint": row.get("source_endpoint", "")})
    )


def safe_unlink(batch_dir: Path, relative_path: str) -> bool:
    if not relative_path:
        return False
    target = (batch_dir / relative_path).resolve()
    if not target.is_relative_to(batch_dir.resolve()) or not target.is_file():
        return False
    target.unlink()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove non-product flows and images from a Manlifang capture batch")
    parser.add_argument("batch_dir", type=Path)
    args = parser.parse_args()
    batch_dir = args.batch_dir.resolve()

    flow_path = batch_dir / "api_flows.jsonl"
    flow_rows = read_jsonl(flow_path)
    kept_flows = [row for row in flow_rows if product_flow(row)]
    removed_flows = [row for row in flow_rows if not product_flow(row)]
    kept_flow_ids = {str(row.get("flow_id", "")) for row in kept_flows}
    removed_response_files = sum(
        1 for row in removed_flows if safe_unlink(batch_dir, str(row.get("response_file", "")))
    )
    write_jsonl(flow_path, kept_flows)

    discovered_path = batch_dir / "discovered_image_urls.jsonl"
    discovered_rows = read_jsonl(discovered_path)
    kept_discovered = [row for row in discovered_rows if keep_discovered_image(row, kept_flow_ids)]
    write_jsonl(discovered_path, kept_discovered)
    discovered_urls = {normalized_url(str(row.get("url", ""))) for row in kept_discovered if row.get("url")}

    captured_path = batch_dir / "captured_image_manifest.jsonl"
    captured_rows = read_jsonl(captured_path)
    kept_captured = [
        row for row in captured_rows if normalized_url(str(row.get("url", ""))) in discovered_urls
    ]
    write_jsonl(captured_path, kept_captured)
    kept_hashes = {str(row.get("sha256", "")) for row in kept_captured if row.get("sha256")}

    image_dir = batch_dir / "raw" / "images"
    removed_images = 0
    if image_dir.exists():
        for path in image_dir.iterdir():
            if path.is_file() and path.stem not in kept_hashes:
                path.unlink()
                removed_images += 1

    print(
        "sanitized",
        f"flows_kept={len(kept_flows)}",
        f"flows_removed={len(removed_flows)}",
        f"responses_removed={removed_response_files}",
        f"image_urls_kept={len(kept_discovered)}",
        f"captured_image_rows_kept={len(kept_captured)}",
        f"image_files_removed={removed_images}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
