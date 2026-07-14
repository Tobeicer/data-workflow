from __future__ import annotations

import json
import sys
from pathlib import Path


MANLIFANG_DIR = Path(__file__).resolve().parents[1]
if str(MANLIFANG_DIR) not in sys.path:
    sys.path.insert(0, str(MANLIFANG_DIR))

from download_manlifang_images import download_images  # noqa: E402


def test_download_images_uses_workers_and_writes_hash_manifest(tmp_path: Path) -> None:
    rows = [
        {"url": "https://img.example.com/a.jpg", "image_role": "main", "json_path": "$.a"},
        {"url": "https://img.example.com/b.jpg", "image_role": "detail", "json_path": "$.b"},
        {"url": "https://img.example.com/c.jpg", "image_role": "main", "json_path": "$.c"},
    ]
    (tmp_path / "discovered_image_urls.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    def fake_download(url: str, timeout: float, retries: int) -> tuple[bytes, str, int]:
        return url.encode("utf-8"), "image/jpeg", 200

    stats = download_images(
        tmp_path,
        delay=0,
        timeout=1,
        retries=0,
        workers=2,
        download_fn=fake_download,
    )

    manifest = [
        json.loads(line)
        for line in (tmp_path / "downloaded_image_manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    files = list((tmp_path / "raw" / "images_downloaded").glob("*.jpg"))
    assert stats == {"discovered": 3, "pending": 3, "downloaded": 3, "failed": 0}
    assert len(manifest) == 3
    assert len(files) == 3
    assert all(row["status"] == "downloaded" for row in manifest)
    assert all(len(row["sha256"]) == 64 for row in manifest)
