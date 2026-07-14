from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

from mitmproxy import ctx, http


KNOWN_ENDPOINTS = (
    "productcatalog/queryall",
    "productcatalog/sublevel",
    "mshopproduct/queryinfolist",
    "mshopproduct/queryproductspuinfooptimize",
)

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

SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "token",
    "access_token",
    "refresh_token",
    "session",
    "sessionid",
    "openid",
    "unionid",
    "phone",
    "mobile",
    "password",
    "address",
    "receiver",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
IMAGE_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+?(?:\.jpg|\.jpeg|\.png|\.webp|\.gif|\.bmp|\.avif)(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def safe_name(value: str, limit: int = 70) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (cleaned or "flow")[:limit]


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower().replace("-", "_") in SENSITIVE_KEYS:
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = scrub(item)
        return result
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def parse_json_text(text: str) -> Any | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def request_payload(flow: http.HTTPFlow) -> Any | None:
    text = flow.request.get_text(strict=False) or ""
    parsed = parse_json_text(text)
    if parsed is not None:
        return scrub(parsed)
    if not text or len(text) > 200_000:
        return None
    return text


def image_role(path: str) -> str:
    lowered = path.lower()
    if "sku" in lowered or "spec" in lowered:
        return "sku"
    if "detail" in lowered or "content" in lowered or "desc" in lowered:
        return "detail"
    if "param" in lowered or "attribute" in lowered:
        return "parameter"
    if "banner" in lowered or "carousel" in lowered or "gallery" in lowered or "album" in lowered:
        return "gallery"
    if "main" in lowered or "cover" in lowered or "thumb" in lowered or "logo" in lowered:
        return "main"
    return "unknown"


def normalized_image_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))


def find_image_urls(value: Any, path: str = "$") -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            found.extend(find_image_urls(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(find_image_urls(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        candidates = IMAGE_URL_RE.findall(value)
        if value.startswith(("http://", "https://")):
            parsed = urlparse(value)
            if Path(parsed.path).suffix.lower() in IMAGE_EXTENSIONS or any(
                hint in path.lower() for hint in ("img", "image", "pic", "photo", "cover")
            ):
                candidates.append(value)
        for url in candidates:
            found.append((url, path, image_role(path)))
    return found


class ManlifangFullCapture:
    def __init__(self) -> None:
        self.output_dir: Path | None = None
        self.response_dir: Path | None = None
        self.image_dir: Path | None = None
        self.learned_api_hosts: set[str] = set()
        self.discovered_image_urls: set[str] = set()

    def load(self, loader) -> None:
        loader.add_option(
            "manlifang_capture_dir",
            str,
            "",
            "Directory for the Manlifang capture batch",
        )

    def running(self) -> None:
        configured = ctx.options.manlifang_capture_dir or os.environ.get("MANLIFANG_CAPTURE_DIR", "")
        if not configured:
            configured = str(
                Path.cwd() / "data-workflow" / "runtime" / "runs" / "manlifang" / "manual"
            )
        self.output_dir = Path(configured).resolve()
        self.response_dir = self.output_dir / "raw" / "responses"
        self.image_dir = self.output_dir / "raw" / "images"
        self.response_dir.mkdir(parents=True, exist_ok=True)
        self.image_dir.mkdir(parents=True, exist_ok=True)
        discovered_path = self.output_dir / "discovered_image_urls.jsonl"
        if discovered_path.exists():
            for line in discovered_path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                url = str(record.get("url", ""))
                if url:
                    self.discovered_image_urls.add(normalized_image_url(url))
        started_path = self.output_dir / "capture_started_at.txt"
        if not started_path.exists():
            started_path.write_text(utc_now(), encoding="utf-8")
        ctx.log.info(f"Manlifang capture directory: {self.output_dir}")

    def is_sensitive(self, flow: http.HTTPFlow) -> bool:
        target = f"{flow.request.host}{flow.request.path}".lower()
        return any(hint in target for hint in SENSITIVE_HINTS)

    def is_known_product_api(self, flow: http.HTTPFlow) -> bool:
        target = f"{flow.request.host}{flow.request.path}".lower()
        return any(endpoint in target for endpoint in KNOWN_ENDPOINTS) or "mshopproduct" in target or "productcatalog" in target

    def should_capture_api(self, flow: http.HTTPFlow) -> bool:
        if self.is_sensitive(flow) or not flow.response:
            return False
        content_type = flow.response.headers.get("content-type", "").lower()
        target = f"{flow.request.host}{flow.request.path}".lower()
        if self.is_known_product_api(flow):
            return True
        if "json" in content_type and any(hint in target for hint in PRODUCT_HINTS):
            return True
        return False

    def should_capture_image(self, flow: http.HTTPFlow) -> bool:
        if self.is_sensitive(flow) or not flow.response:
            return False
        content_type = flow.response.headers.get("content-type", "").lower()
        if not content_type.startswith("image/"):
            return False
        url = normalized_image_url(flow.request.pretty_url)
        return url in self.discovered_image_urls

    def record_discovered_images(self, flow_id: str, response_json: Any) -> None:
        assert self.output_dir is not None
        for url, json_path, role in find_image_urls(response_json):
            normalized_url = normalized_image_url(url)
            if normalized_url in self.discovered_image_urls:
                continue
            self.discovered_image_urls.add(normalized_url)
            append_jsonl(
                self.output_dir / "discovered_image_urls.jsonl",
                {
                    "flow_id": flow_id,
                    "url": url,
                    "json_path": json_path,
                    "image_role": role,
                    "discovered_at": utc_now(),
                },
            )

    def capture_api(self, flow: http.HTTPFlow) -> None:
        assert self.output_dir is not None and self.response_dir is not None and flow.response is not None
        self.learned_api_hosts.add(flow.request.host)
        response_text = flow.response.get_text(strict=False) or ""
        parsed_response = parse_json_text(response_text)
        safe_response = scrub(parsed_response) if parsed_response is not None else response_text[:2_000_000]
        flow_id = flow.id
        endpoint = safe_name(flow.request.path.strip("/").replace("/", "_"))
        body_hash = hashlib.sha256(flow.response.raw_content or b"").hexdigest()[:12]
        response_file = self.response_dir / f"{utc_now().replace(':', '').replace('+', '_')}_{endpoint}_{body_hash}.json"
        response_file.write_text(json.dumps(safe_response, ensure_ascii=False, indent=2), encoding="utf-8")

        record = {
            "flow_id": flow_id,
            "captured_at": utc_now(),
            "method": flow.request.method,
            "host": flow.request.host,
            "path": flow.request.path,
            "url": flow.request.pretty_url,
            "request_headers": {
                key: flow.request.headers.get(key)
                for key in ("content-type", "accept", "user-agent", "referer")
                if flow.request.headers.get(key)
            },
            "request_body": request_payload(flow),
            "status_code": flow.response.status_code,
            "response_headers": {
                key: flow.response.headers.get(key)
                for key in ("content-type", "content-length", "etag", "last-modified")
                if flow.response.headers.get(key)
            },
            "response_bytes": len(flow.response.raw_content or b""),
            "response_sha256": hashlib.sha256(flow.response.raw_content or b"").hexdigest(),
            "response_file": str(response_file.relative_to(self.output_dir)),
        }
        append_jsonl(self.output_dir / "api_flows.jsonl", record)
        if parsed_response is not None:
            self.record_discovered_images(flow_id, parsed_response)

    def capture_image(self, flow: http.HTTPFlow) -> None:
        assert self.output_dir is not None and self.image_dir is not None and flow.response is not None
        content = flow.response.raw_content or b""
        if not content:
            return
        digest = hashlib.sha256(content).hexdigest()
        content_type = flow.response.headers.get("content-type", "").split(";", 1)[0].lower()
        suffix_by_type = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/bmp": ".bmp",
            "image/avif": ".avif",
        }
        suffix = suffix_by_type.get(content_type) or Path(urlparse(flow.request.pretty_url).path).suffix.lower() or ".bin"
        target = self.image_dir / f"{digest}{suffix}"
        if not target.exists():
            target.write_bytes(content)
        append_jsonl(
            self.output_dir / "captured_image_manifest.jsonl",
            {
                "flow_id": flow.id,
                "captured_at": utc_now(),
                "url": flow.request.pretty_url,
                "status_code": flow.response.status_code,
                "content_type": content_type,
                "bytes": len(content),
                "sha256": digest,
                "local_file": str(target.relative_to(self.output_dir)),
                "etag": flow.response.headers.get("etag", ""),
                "last_modified": flow.response.headers.get("last-modified", ""),
            },
        )

    def response(self, flow: http.HTTPFlow) -> None:
        if self.output_dir is None or flow.response is None:
            return
        try:
            if self.should_capture_api(flow):
                self.capture_api(flow)
            if self.should_capture_image(flow):
                self.capture_image(flow)
        except Exception as exc:
            append_jsonl(
                self.output_dir / "capture_errors.jsonl",
                {
                    "captured_at": utc_now(),
                    "flow_id": flow.id,
                    "url": flow.request.pretty_url,
                    "error": repr(exc),
                },
            )
            ctx.log.warn(f"Manlifang capture error: {exc!r}")


addons = [ManlifangFullCapture()]
