from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_manifest(root: Path) -> dict:
    root = root.resolve(strict=True)
    files = []
    file_ids: set[tuple[int, int]] = set()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        stat = path.stat()
        file_id = (stat.st_dev, stat.st_ino)
        file_ids.add(file_id)
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "sha256": sha256_file(path),
                "device": stat.st_dev,
                "inode": stat.st_ino,
            }
        )
    return {
        "root": str(root),
        "summary": {
            "files": len(files),
            "bytes": sum(item["size"] for item in files),
            "unique_file_ids": len(file_ids),
        },
        "files": files,
    }


def content_signature(manifest: dict) -> Counter:
    return Counter((item["size"], item["sha256"]) for item in manifest["files"])


def hardlink_signature(manifest: dict) -> Counter:
    groups = Counter((item["device"], item["inode"], item["size"]) for item in manifest["files"])
    return Counter((size, links) for (_, _, size), links in groups.items())


def compare_manifests(before: dict, after: dict) -> list[str]:
    errors = []
    if before["summary"]["files"] != after["summary"]["files"]:
        errors.append("file count differs")
    if before["summary"]["bytes"] != after["summary"]["bytes"]:
        errors.append("byte count differs")
    if content_signature(before) != content_signature(after):
        errors.append("content multiset differs")
    if hardlink_signature(before) != hardlink_signature(after):
        errors.append("hardlink topology differs")
    return errors


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("root", type=Path)
    create_parser.add_argument("output", type=Path)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("before", type=Path)
    compare_parser.add_argument("after", type=Path)
    args = parser.parse_args()

    if args.command == "create":
        write_manifest(args.output, create_manifest(args.root))
        return 0

    errors = compare_manifests(read_manifest(args.before), read_manifest(args.after))
    if errors:
        for error in errors:
            print(error)
        return 1
    print("manifests match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
