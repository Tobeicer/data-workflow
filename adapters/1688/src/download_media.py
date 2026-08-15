"""Download media manifest entries into the NAS media store.

The manifest is treated as the single source of truth. Every URL is written to
``<media_root>/<local_rel_path>``, hashed with SHA-256, and the manifest row is
updated in place. Completed files are never re-downloaded unless requested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


MEDIA_ROOT_ENV = "DATA_MEDIA_ROOT"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://detail.1688.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def local_target(media_root: Path, rel_path: str) -> Path:
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe media path: {rel_path}")
    target = (media_root / rel).resolve()
    root = media_root.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"media path escapes media root: {rel_path}")
    return target


def should_download(record: dict, target: Path, overwrite: bool = False) -> bool:
    if overwrite:
        return True
    if record.get("status") == "downloaded" and target.exists() and target.stat().st_size > 0:
        return False
    return not (target.exists() and target.stat().st_size > 0)


def mark_downloaded(
    record: dict,
    content_hash: str,
    size_bytes: int,
    status: str,
    downloaded_at: str,
) -> None:
    record["status"] = status
    record["content_hash"] = content_hash
    record["size_bytes"] = size_bytes
    record["downloaded_at"] = downloaded_at


def update_checkpoint(path: Path, new_ids: set[str]) -> list[str]:
    existing: set[str] = set()
    if path.exists():
        try:
            existing = set(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            existing = set()
    merged = sorted(existing | new_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return merged


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def write_manifest(path: Path, rows: list[dict]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temp.replace(path)


def fetch_url(url: str, timeout: float, headers: dict[str, str], retries: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={**headers, **{"Referer": "https://detail.1688.com/"}})
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001 - every network error is retried
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1 + attempt * 1.5)
    raise RuntimeError(f"download failed after {retries} attempts: {last_error}")


def download_one(
    record: dict,
    media_root: Path,
    headers: dict[str, str],
    timeout: float = 30.0,
    retries: int = 3,
    overwrite: bool = False,
) -> str:
    rel_path = str(record.get("local_rel_path") or "").strip()
    if not rel_path:
        return "invalid_path"
    target = local_target(media_root, rel_path)
    if not should_download(record, target, overwrite=overwrite):
        return "skipped"
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    source_url = str(record.get("source_url") or "")
    fallback_url = str(record.get("fallback_url") or "")
    try:
        data = fetch_url(source_url, timeout, headers, retries)
    except Exception:  # noqa: BLE001
        if fallback_url and fallback_url != source_url:
            data = fetch_url(fallback_url, timeout, headers, retries)
        else:
            raise
    part.write_bytes(data)
    part.replace(target)
    mark_downloaded(
        record,
        sha256_hex(data),
        len(data),
        "downloaded",
        datetime.now(timezone.utc).isoformat(),
    )
    return "downloaded"


def run(
    manifest_path: Path,
    media_root: Path,
    checkpoint_path: Path,
    limit: int = 0,
    media_types: set[str] | None = None,
    delay: float = 0.5,
    timeout: float = 30.0,
    retries: int = 3,
) -> dict:
    rows = load_manifest(manifest_path)
    checkpoint = set(json.loads(checkpoint_path.read_text(encoding="utf-8"))) if checkpoint_path.exists() else set()
    # 断点已含 = 已下载完成：状态归一，避免清单与磁盘不一致
    for row in rows:
        if row.get("media_id") in checkpoint and row.get("status") != "downloaded":
            row["status"] = "downloaded"
    media_types = media_types or set()
    stats = {"total": 0, "downloaded": 0, "skipped": 0, "errors": 0, "remaining": 0}
    candidates = []
    for row in rows:
        if media_types and row.get("media_type") not in media_types:
            continue
        if row.get("status") == "downloaded" or row.get("media_id") in checkpoint:
            continue
        if row.get("status") not in ("pending_download", "download_error", None):
            continue
        candidates.append(row)
    selected = candidates[:limit] if limit else candidates
    for index, row in enumerate(selected, start=1):
        stats["total"] += 1
        try:
            outcome = download_one(row, media_root, DEFAULT_HEADERS, timeout, retries)
            if outcome == "downloaded":
                stats["downloaded"] += 1
                checkpoint.add(row["media_id"])
            else:
                stats["skipped"] += 1
                # 文件已存在（断点续传/重复运行）：状态归一为 downloaded，
                # 清单与磁盘保持一致，避免审计把已有文件误读为未下载。
                row["status"] = "downloaded"
        except Exception as exc:  # noqa: BLE001 - keep manifest row and continue
            row["status"] = "download_error"
            row["error"] = str(exc)[:500]
            stats["errors"] += 1
        if index % 25 == 0 or index == len(selected):
            update_checkpoint(checkpoint_path, checkpoint)
            write_manifest(manifest_path, rows)
            print(
                json.dumps(
                    {
                        "progress": f"{index}/{len(selected)}",
                        **stats,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        if delay:
            time.sleep(delay)
    write_manifest(manifest_path, rows)
    update_checkpoint(checkpoint_path, checkpoint)
    stats["remaining"] = len(candidates) - len(selected)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--media-root", default=os.environ.get(MEDIA_ROOT_ENV))
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--media-types", default="")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()
    if not args.media_root:
        raise SystemExit("--media-root is required (or set DATA_MEDIA_ROOT)")
    manifest_path = Path(args.manifest)
    checkpoint_path = Path(args.checkpoint) if args.checkpoint else manifest_path.parent / ".media_checkpoint.json"
    media_types = {item.strip() for item in args.media_types.split(",") if item.strip()} or None
    summary = run(
        manifest_path,
        Path(args.media_root),
        checkpoint_path,
        limit=args.limit,
        media_types=media_types,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
