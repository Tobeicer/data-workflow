import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from download_media import (  # noqa: E402
    local_target,
    mark_downloaded,
    should_download,
    update_checkpoint,
)


def make_record(status="pending_download"):
    return {
        "media_id": "1688:media:abc",
        "local_rel_path": "1688/products/1/main_image/a.jpg",
        "status": status,
        "content_hash": None,
        "size_bytes": None,
        "downloaded_at": None,
    }


def test_local_target_resolves_under_media_root(tmp_path):
    target = local_target(tmp_path, "1688/products/1/main_image/a.jpg")
    assert target == tmp_path / "1688/products/1/main_image/a.jpg"
    assert str(target).startswith(str(tmp_path))


def test_local_target_rejects_path_escape(tmp_path):
    try:
        local_target(tmp_path, "../outside.jpg")
    except ValueError:
        return
    raise AssertionError("expected path escape to raise ValueError")


def test_should_download_pending_when_file_missing(tmp_path):
    record = make_record("pending_download")
    assert should_download(record, tmp_path / "missing.jpg") is True


def test_should_download_skip_completed_when_file_exists(tmp_path):
    record = make_record("downloaded")
    target = tmp_path / "a.jpg"
    target.write_bytes(b"x")
    assert should_download(record, target) is False


def test_mark_downloaded_sets_hash_size_and_status():
    record = make_record()
    mark_downloaded(record, "sha256:abc", 123, "downloaded", "2026-08-13T00:00:00+00:00")
    assert record["status"] == "downloaded"
    assert record["content_hash"] == "sha256:abc"
    assert record["size_bytes"] == 123
    assert record["downloaded_at"] == "2026-08-13T00:00:00+00:00"


def test_update_checkpoint_keeps_known_media_ids(tmp_path):
    path = tmp_path / ".media_checkpoint.json"
    update_checkpoint(path, {"a", "b"})
    update_checkpoint(path, {"b", "c"})
    assert json.loads(path.read_text(encoding="utf-8")) == ["a", "b", "c"]
