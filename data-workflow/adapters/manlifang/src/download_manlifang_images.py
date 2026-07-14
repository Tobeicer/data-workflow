from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def suffix_for(url: str, content_type: str) -> str:
    known = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/avif": ".avif",
    }
    mime = content_type.split(";", 1)[0].lower()
    if mime in known:
        return known[mime]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix:
        return suffix[:10]
    return mimetypes.guess_extension(mime) or ".bin"


def download(url: str, timeout: float, retries: int) -> tuple[bytes, str, int]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                content = response.read()
                return content, response.headers.get_content_type(), int(response.status)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.0 + attempt)
    raise RuntimeError(str(last_error) if last_error else "download failed")


def download_images(
    batch_dir: Path,
    *,
    delay: float,
    timeout: float,
    retries: int,
    workers: int,
    download_fn=download,
) -> dict[str, int]:
    batch_dir = batch_dir.resolve()
    discovered_path = batch_dir / "discovered_image_urls.jsonl"
    captured_path = batch_dir / "captured_image_manifest.jsonl"
    output_manifest = batch_dir / "downloaded_image_manifest.jsonl"
    image_dir = batch_dir / "raw" / "images_downloaded"
    image_dir.mkdir(parents=True, exist_ok=True)

    captured_urls = {str(row.get("url", "")) for row in iter_jsonl(captured_path) or [] if row.get("url")}
    completed_urls = {str(row.get("url", "")) for row in iter_jsonl(output_manifest) or [] if row.get("status") == "downloaded"}
    discovered_rows = list(iter_jsonl(discovered_path) or [])
    unique_rows: dict[str, dict[str, Any]] = {}
    for row in discovered_rows:
        url = str(row.get("url", "")).strip()
        if url and url.startswith(("http://", "https://")):
            unique_rows.setdefault(url, row)

    pending = [url for url in unique_rows if url not in captured_urls and url not in completed_urls]
    print(f"discovered={len(unique_rows)} captured_through_proxy={len(captured_urls)} pending={len(pending)}")

    def fetch(url: str) -> dict[str, Any]:
        started = time.time()
        base_record = {
            "url": url,
            "image_role": unique_rows[url].get("image_role", "unknown"),
            "json_path": unique_rows[url].get("json_path", ""),
        }
        try:
            content, content_type, status_code = download_fn(url, timeout, retries)
            if not content_type.startswith("image/"):
                raise RuntimeError(f"unexpected content type: {content_type}")
            digest = hashlib.sha256(content).hexdigest()
            return {
                **base_record,
                "status": "downloaded",
                "status_code": status_code,
                "content_type": content_type,
                "bytes": len(content),
                "sha256": digest,
                "local_file": str((image_dir / f"{digest}{suffix_for(url, content_type)}").relative_to(batch_dir)),
                "elapsed_seconds": round(time.time() - started, 3),
                "_content": content,
            }
        except Exception as exc:
            return {
                **base_record,
                "status": "failed",
                "error": repr(exc),
                "elapsed_seconds": round(time.time() - started, 3),
            }
        finally:
            time.sleep(max(delay, 0.0))

    downloaded_count = 0
    failed_count = 0
    worker_count = max(int(workers), 1)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(fetch, url): url for url in pending}
        for index, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            content = record.pop("_content", None)
            if record.get("status") == "downloaded" and content is not None:
                target = batch_dir / str(record["local_file"])
                if not target.exists():
                    target.write_bytes(content)
                downloaded_count += 1
                print(f"[{index}/{len(pending)}] downloaded {record.get('bytes', 0)} bytes {record['url']}")
            else:
                failed_count += 1
                print(f"[{index}/{len(pending)}] failed {record['url']}: {record.get('error', '')}")
            append_jsonl(output_manifest, record)

    return {
        "discovered": len(unique_rows),
        "pending": len(pending),
        "downloaded": downloaded_count,
        "failed": failed_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download all discovered public Manlifang product images")
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    stats = download_images(
        args.batch_dir,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        workers=args.workers,
    )
    print("download_summary", " ".join(f"{key}={value}" for key, value in stats.items()))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
