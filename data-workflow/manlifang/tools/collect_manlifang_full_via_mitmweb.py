from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlsplit, urlunsplit

import requests


TEMPLATE_PATHS = {
    "query_all": "ProductCatalog/queryAll",
    "sub_level": "ProductCatalog/subLevel/",
    "query_info_list": "MshopProduct/queryInfoList",
    "spu_info": "MshopProduct/queryProductSpuInfoOptimize",
    "static_detail": "MshopProduct/queryMshopProductDetailStaticArchives",
    "dynamic_detail": "MshopProduct/queryMshopProductDetailDynamicArchives",
    "products_by_catalog": "MshopProduct/queryProductByCatalogId",
}

SPU_FIELDS = [
    "NAME",
    "PRICE",
    "MEMBER_PRICE",
    "IMAGE",
    "PRODUCT_BARCODE",
    "RETAIL_PRICE",
    "MONTH_SALE_AMOUNT",
    "CODE",
    "AVAIL_QTY",
    "SPEC",
    "SPEC_NAME",
    "SPEC_AVAIL_QTY",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
IMAGE_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+?(?:\.jpg|\.jpeg|\.png|\.webp|\.gif|\.bmp|\.avif)(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)


def local_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def safe_name(value: str, limit: int = 100) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return (cleaned or "item")[:limit]


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def select_template_flows(flows: Iterable[dict[str, Any]]) -> dict[str, str]:
    selected: dict[str, tuple[int, float, str]] = {}
    for flow in flows:
        request = flow.get("request") or {}
        response = flow.get("response") or {}
        if response.get("status_code") != 200:
            continue
        path = str(request.get("path", ""))
        timestamp = float(response.get("timestamp_end") or 0.0)
        stable = int(not flow.get("is_replay") and not flow.get("modified"))
        for endpoint, needle in TEMPLATE_PATHS.items():
            if needle not in path:
                continue
            current = selected.get(endpoint)
            candidate = (stable, timestamp, str(flow.get("id", "")))
            if current is None or candidate[:2] >= current[:2]:
                selected[endpoint] = candidate
    return {endpoint: flow_id for endpoint, (_, _, flow_id) in selected.items() if flow_id}


def required_templates_for_run(batch_dir: Path, *, phase: str, skip_spu: bool) -> set[str]:
    structured = batch_dir / "structured"
    has_snapshot = all(
        path.exists() and path.stat().st_size > 0
        for path in (structured / "categories.jsonl", structured / "products.jsonl")
    )
    required: set[str] = set()
    if not has_snapshot:
        required.update({"query_all", "sub_level", "query_info_list"})
    if phase in {"details", "all"}:
        required.update({"static_detail", "dynamic_detail"})
        if not skip_spu:
            required.add("spu_info")
    return required


def build_sublevel_path(template_path: str, catalog_id: int | str) -> str:
    prefix, marker, suffix = template_path.partition("ProductCatalog/subLevel/")
    if not marker:
        raise ValueError(f"not a subLevel path: {template_path}")
    query = ""
    if "?" in suffix:
        _, query = suffix.split("?", 1)
    result = f"{prefix}{marker}{catalog_id}"
    return f"{result}?{query}" if query else result


def flatten_category_tree(
    nodes: Iterable[dict[str, Any]],
    parent_catalog_id: int | str | None = None,
    depth: int = 0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        catalog_id = node.get("productCatalogId")
        if catalog_id in (None, ""):
            continue
        row = {
            "product_catalog_id": catalog_id,
            "parent_catalog_id": parent_catalog_id if parent_catalog_id not in (None, "") else "",
            "name": node.get("name", ""),
            "tree_path": node.get("treePath", ""),
            "is_leaf_node": bool(node.get("isLeafNode")),
            "is_hidden": bool(node.get("isHidden")),
            "sequence_num": node.get("sequenceNum", ""),
            "product_catalog_type_id": node.get("productCatalogTypeId", ""),
            "image_url": node.get("url", ""),
            "depth": depth,
            "raw_category": node,
        }
        rows.append(row)
        children = node.get("subCatalog") or []
        if isinstance(children, list) and children:
            rows.extend(flatten_category_tree(children, catalog_id, depth + 1))
    return rows


def extract_product_records(
    response: dict[str, Any],
    category: dict[str, Any],
    first_result: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for listing in response.get("data") or []:
        if not isinstance(listing, dict):
            continue
        product = listing.get("productId") or {}
        if not isinstance(product, dict):
            continue
        product_id = product.get("id")
        if product_id in (None, ""):
            continue
        rows.append(
            {
                "product_id": product_id,
                "listing_id": listing.get("id", ""),
                "product_code": product.get("code", ""),
                "product_name": product.get("name", ""),
                "source_catalog_id": category.get("product_catalog_id", ""),
                "source_catalog_name": category.get("name", ""),
                "source_tree_path": category.get("tree_path", ""),
                "page_first_result": first_result,
                "page_count": response.get("count", ""),
                "raw_listing": listing,
                "raw_product": product,
            }
        )
    return rows


def canonical_image_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))


def image_role(json_path: str) -> str:
    lowered = json_path.lower()
    if any(hint in lowered for hint in ("description", "displaydescription", "content", "html")):
        return "description"
    if any(hint in lowered for hint in ("sku", "spec")):
        return "sku"
    if any(hint in lowered for hint in ("detail", "album", "gallery", "carousel")):
        return "detail"
    if any(hint in lowered for hint in ("primary", "main", "cover", "thumb", "image")):
        return "main"
    return "unknown"


def walk_strings(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk_strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def extract_image_references(
    payload: Any,
    source_endpoint: str,
    product_id: int | str | None = None,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for json_path, text in walk_strings(payload):
        candidates = list(IMAGE_URL_RE.findall(text))
        if text.startswith(("http://", "https://")):
            suffix = Path(urlsplit(text).path).suffix.lower()
            if suffix in IMAGE_EXTENSIONS or any(
                hint in json_path.lower() for hint in ("image", "img", "pic", "photo", "cover")
            ):
                candidates.append(text)
        for original_url in candidates:
            original_url = original_url.rstrip(")]},;\"")
            canonical_url = canonical_image_url(original_url)
            if not canonical_url:
                continue
            rows.setdefault(
                canonical_url,
                {
                    "product_id": product_id if product_id not in (None, "") else "",
                    "source_endpoint": source_endpoint,
                    "json_path": json_path,
                    "image_role": image_role(json_path),
                    "original_url": original_url,
                    "canonical_url": canonical_url,
                },
            )
    return list(rows.values())


def nested_id(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("id")
    return value


def product_uom_id(product: dict[str, Any], static_detail: dict[str, Any] | None = None) -> Any:
    raw_product = product.get("raw_product") or {}
    raw_listing = product.get("raw_listing") or {}
    candidates = [
        raw_product.get("salesUomId"),
        raw_product.get("retailSalesUomId"),
        raw_product.get("baseUomId"),
        raw_listing.get("mshopCommonSalesUomId"),
    ]
    if static_detail:
        candidates.extend(
            [
                static_detail.get("defaultUomId"),
                static_detail.get("mshopCommonSalesUomId"),
                static_detail.get("retailSalesUomId"),
                static_detail.get("baseUomId"),
            ]
        )
    for candidate in candidates:
        value = nested_id(candidate)
        if value not in (None, ""):
            return value
    return ""


class BatchStore:
    def __init__(self, batch_dir: Path) -> None:
        self.batch_dir = batch_dir.resolve()
        self.response_dir = self.batch_dir / "raw" / "responses"
        self.checkpoint_path = self.batch_dir / "checkpoint.json"
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.response_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._checkpoint = self._load_checkpoint()

    def response_path(self, endpoint: str, request_key: str) -> Path:
        digest = hashlib.sha256(str(request_key).encode("utf-8")).hexdigest()[:12]
        return self.response_dir / safe_name(endpoint) / f"{safe_name(request_key)}_{digest}.json"

    def _load_checkpoint(self) -> dict[str, Any]:
        if not self.checkpoint_path.exists():
            return {"completed": {}, "updated_at": local_now()}
        try:
            value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"completed": {}, "updated_at": local_now()}
        return value if isinstance(value, dict) else {"completed": {}, "updated_at": local_now()}

    def is_completed(self, endpoint: str, request_key: str) -> bool:
        with self._lock:
            completed = self._checkpoint.get("completed") or {}
            return str(request_key) in set(completed.get(endpoint) or [])

    def mark_completed(self, endpoint: str, request_key: str) -> None:
        with self._lock:
            completed = self._checkpoint.setdefault("completed", {})
            keys = completed.setdefault(endpoint, [])
            key = str(request_key)
            if key not in keys:
                keys.append(key)
            self._checkpoint["updated_at"] = local_now()
            write_json_atomic(self.checkpoint_path, self._checkpoint)

    def load_response(self, endpoint: str, request_key: str) -> Any:
        with self._lock:
            path = self.response_path(endpoint, request_key)
            return json.loads(path.read_text(encoding="utf-8"))

    def append_record(self, relative_path: str, record: dict[str, Any]) -> None:
        with self._lock:
            append_jsonl(self.batch_dir / relative_path, record)

    def save_response(
        self,
        *,
        endpoint: str,
        request_key: str,
        request_payload: Any,
        response_payload: Any,
        status_code: int,
        replay_flow_id: str,
    ) -> str:
        with self._lock:
            target = self.response_path(endpoint, request_key)
            write_json_atomic(target, response_payload)
            relative = str(target.relative_to(self.batch_dir))
            raw_bytes = json.dumps(response_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            append_jsonl(
                self.batch_dir / "api_flows.jsonl",
                {
                    "flow_id": replay_flow_id,
                    "captured_at": local_now(),
                    "endpoint": endpoint,
                    "request_key": str(request_key),
                    "request_body": request_payload,
                    "status_code": status_code,
                    "response_bytes": len(raw_bytes),
                    "response_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "response_file": relative,
                },
            )
            return relative


@dataclass(frozen=True)
class ReplayResult:
    endpoint: str
    flow_id: str
    status_code: int
    request_path: str
    response_payload: Any


class CollectionError(RuntimeError):
    pass


class MitmwebClient:
    def __init__(
        self,
        base_url: str,
        *,
        session: Any | None = None,
        request_timeout: float = 20.0,
        replay_timeout: float = 45.0,
        poll_interval: float = 0.25,
        delay: float = 0.8,
        sleep: Any = time.sleep,
        updates_socket_factory: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.request_timeout = request_timeout
        self.replay_timeout = replay_timeout
        self.poll_interval = max(poll_interval, 0.0)
        self.delay = max(delay, 0.0)
        self.sleep = sleep
        self.updates_socket_factory = updates_socket_factory or self._default_updates_socket_factory
        self.template_ids: dict[str, str] = {}
        self.template_flows: dict[str, dict[str, Any]] = {}
        self._xsrf_headers: dict[str, str] = {}
        self._connected = False
        self._updates_socket: Any = None

    @staticmethod
    def _default_updates_socket_factory(url: str, *, timeout: float, origin: str) -> Any:
        try:
            import websocket
        except ImportError:
            return None
        return websocket.create_connection(url, timeout=timeout, origin=origin)

    def _ensure_updates_socket(self) -> Any:
        if self._updates_socket is not None:
            return self._updates_socket
        parsed = urlsplit(self.base_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = urlunsplit((ws_scheme, parsed.netloc, "/updates", "", ""))
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        try:
            self._updates_socket = self.updates_socket_factory(
                ws_url,
                timeout=self.replay_timeout,
                origin=origin,
            )
        except Exception:
            self._updates_socket = None
        return self._updates_socket

    def connect(self) -> None:
        if self._connected:
            self._ensure_updates_socket()
            return
        response = self.session.get(f"{self.base_url}/", timeout=self.request_timeout)
        response.raise_for_status()
        token = (
            self.session.cookies.get("_xsrf")
            or self.session.cookies.get("XSRF-TOKEN")
            or self.session.cookies.get("xsrf")
        )
        self._xsrf_headers = {"X-XSRFToken": token} if token else {}
        self._connected = True
        self._ensure_updates_socket()

    def list_flows(self) -> list[dict[str, Any]]:
        response = self.session.get(f"{self.base_url}/flows", timeout=self.request_timeout)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, list):
            raise CollectionError("mitmweb /flows did not return a list")
        return value

    def refresh_templates(self) -> dict[str, str]:
        self.connect()
        flows = self.list_flows()
        self.template_ids = select_template_flows(flows)
        by_id = {str(flow.get("id", "")): flow for flow in flows}
        self.template_flows = {
            endpoint: by_id[flow_id]
            for endpoint, flow_id in self.template_ids.items()
            if flow_id in by_id
        }
        return dict(self.template_ids)

    def _write_headers(self) -> dict[str, str]:
        if not self._xsrf_headers:
            self.connect()
        return self._xsrf_headers

    def _find_flow(self, flow_id: str) -> dict[str, Any] | None:
        return next((flow for flow in self.list_flows() if str(flow.get("id", "")) == flow_id), None)

    def _wait_for_flow_update(self, flow_id: str, old_timestamp: Any) -> dict[str, Any] | None:
        updates = self._ensure_updates_socket()
        if updates is None:
            return None
        deadline = time.monotonic() + self.replay_timeout
        try:
            updates.settimeout(self.replay_timeout)
            while time.monotonic() < deadline:
                message = updates.recv()
                if isinstance(message, bytes):
                    message = message.decode("utf-8", errors="replace")
                event = json.loads(message)
                if event.get("resource") != "flows" or event.get("cmd") not in {"add", "update"}:
                    continue
                data = event.get("data") or {}
                if str(data.get("id", "")) != flow_id:
                    continue
                response = data.get("response") or {}
                timestamp = response.get("timestamp_end")
                if timestamp not in (None, old_timestamp):
                    return data
        except Exception:
            try:
                updates.close()
            except Exception:
                pass
            self._updates_socket = None
        return None

    def replay(
        self,
        endpoint: str,
        *,
        request_key: str,
        request_payload: Any = None,
        request_path: str | None = None,
    ) -> ReplayResult:
        if endpoint not in self.template_ids:
            self.refresh_templates()
        template_id = self.template_ids.get(endpoint)
        template_flow = self.template_flows.get(endpoint)
        if not template_id or not template_flow:
            raise CollectionError(f"missing successful mitmweb template for {endpoint}")

        new_flow_id = ""
        response_payload: Any = None
        status_code = 0
        effective_path = str((template_flow.get("request") or {}).get("path", ""))
        try:
            self._ensure_updates_socket()
            duplicate = self.session.post(
                f"{self.base_url}/flows/{template_id}/duplicate",
                headers=self._write_headers(),
                timeout=self.request_timeout,
            )
            duplicate.raise_for_status()
            new_flow_id = duplicate.text.strip().strip('"')
            if not new_flow_id:
                raise CollectionError(f"mitmweb duplicate returned no flow id for {endpoint}")

            old_timestamp = (template_flow.get("response") or {}).get("timestamp_end")

            template_request = template_flow.get("request") or {}
            method = str(template_request.get("method", "GET")).upper()
            request_update: dict[str, Any] = {}
            if request_path:
                effective_path = request_path
                request_update["path"] = request_path
            elif endpoint == "sub_level" and isinstance(request_payload, dict):
                catalog_id = request_payload.get("catalogId")
                if catalog_id not in (None, ""):
                    effective_path = build_sublevel_path(effective_path, catalog_id)
                    request_update["path"] = effective_path
            if method != "GET" and request_payload is not None:
                request_update["content"] = json.dumps(
                    request_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            if request_update:
                updated = self.session.put(
                    f"{self.base_url}/flows/{new_flow_id}",
                    headers=self._write_headers(),
                    json={"request": request_update},
                    timeout=self.request_timeout,
                )
                updated.raise_for_status()

            replayed = self.session.post(
                f"{self.base_url}/flows/{new_flow_id}/replay",
                headers=self._write_headers(),
                timeout=self.request_timeout,
            )
            replayed.raise_for_status()

            deadline = time.monotonic() + self.replay_timeout
            fresh_flow = self._wait_for_flow_update(new_flow_id, old_timestamp)
            if fresh_flow is None:
                if self.poll_interval:
                    self.sleep(self.poll_interval)
                while time.monotonic() < deadline:
                    candidate = self._find_flow(new_flow_id)
                    response = (candidate or {}).get("response") or {}
                    timestamp = response.get("timestamp_end")
                    if timestamp not in (None, old_timestamp):
                        fresh_flow = candidate
                        break
                    self.sleep(self.poll_interval)
            if fresh_flow is None:
                raise CollectionError(f"replay timed out for {endpoint} {request_key}")

            status_code = int((fresh_flow.get("response") or {}).get("status_code") or 0)
            raw = self.session.get(
                f"{self.base_url}/flows/{new_flow_id}/response/content.data",
                timeout=self.request_timeout,
            )
            raw.raise_for_status()
            try:
                response_payload = json.loads(raw.content.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                raise CollectionError(f"non-JSON response for {endpoint} {request_key}: {exc}") from exc
            return ReplayResult(
                endpoint=endpoint,
                flow_id=new_flow_id,
                status_code=status_code,
                request_path=effective_path,
                response_payload=response_payload,
            )
        finally:
            if new_flow_id:
                try:
                    self.session.delete(
                        f"{self.base_url}/flows/{new_flow_id}",
                        headers=self._write_headers(),
                        timeout=self.request_timeout,
                    )
                finally:
                    if self.delay:
                        self.sleep(self.delay)


class ManlifangCollector:
    def __init__(
        self,
        *,
        client: Any,
        client_factory: Any = None,
        store: BatchStore,
        page_size: int = 20,
        progress: Any = None,
        max_retries: int = 2,
        retry_delay: float = 2.0,
        sleep: Any = time.sleep,
    ) -> None:
        self.client = client
        self.client_factory = client_factory
        self.store = store
        self.page_size = max(int(page_size), 1)
        self.progress = progress
        self.max_retries = max(int(max_retries), 0)
        self.retry_delay = max(float(retry_delay), 0.0)
        self.sleep = sleep
        self.structured_dir = self.store.batch_dir / "structured"
        self.structured_dir.mkdir(parents=True, exist_ok=True)

    def request(
        self,
        endpoint: str,
        request_key: str,
        request_payload: Any = None,
        request_path: str | None = None,
        client: Any = None,
    ) -> Any:
        if self.store.is_completed(endpoint, request_key):
            payload = self.store.load_response(endpoint, request_key)
            if self.progress:
                self.progress(endpoint, request_key, 200, True)
            return payload
        for attempt in range(self.max_retries + 1):
            try:
                active_client = client or self.client
                result = active_client.replay(
                    endpoint,
                    request_key=request_key,
                    request_payload=request_payload,
                    request_path=request_path,
                )
            except Exception as exc:
                if attempt >= self.max_retries:
                    raise
                self.store.append_record(
                    "request_retries.jsonl",
                    {
                        "recorded_at": local_now(),
                        "endpoint": endpoint,
                        "request_key": str(request_key),
                        "attempt": attempt + 1,
                        "reason": repr(exc),
                    },
                )
                self.sleep(self.retry_delay * (attempt + 1))
                continue

            self.store.save_response(
                endpoint=endpoint,
                request_key=request_key,
                request_payload=request_payload,
                response_payload=result.response_payload,
                status_code=result.status_code,
                replay_flow_id=result.flow_id,
            )
            if result.status_code == 200:
                self.store.mark_completed(endpoint, request_key)
                if self.progress:
                    self.progress(endpoint, request_key, result.status_code, False)
                return result.response_payload

            error = CollectionError(f"{endpoint} {request_key} returned HTTP {result.status_code}")
            if result.status_code in {701, 403, 429} or not 500 <= result.status_code <= 599:
                raise error
            if attempt >= self.max_retries:
                raise error
            self.store.append_record(
                "request_retries.jsonl",
                {
                    "recorded_at": local_now(),
                    "endpoint": endpoint,
                    "request_key": str(request_key),
                    "attempt": attempt + 1,
                    "reason": f"HTTP {result.status_code}",
                },
            )
            self.sleep(self.retry_delay * (attempt + 1))
        raise CollectionError(f"unreachable retry state for {endpoint} {request_key}")

    def collect_categories(self) -> list[dict[str, Any]]:
        root_payload = self.request("query_all", "root")
        if not isinstance(root_payload, list):
            raise CollectionError("queryAll did not return a category list")

        category_by_id: dict[str, dict[str, Any]] = {}
        ordered_ids: list[str] = []

        def merge(rows: Iterable[dict[str, Any]]) -> None:
            for row in rows:
                key = str(row["product_catalog_id"])
                existing = category_by_id.get(key)
                if existing is None:
                    category_by_id[key] = row
                    ordered_ids.append(key)
                else:
                    for field, value in row.items():
                        if existing.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
                            existing[field] = value

        merge(flatten_category_tree(root_payload))
        pending = [key for key in ordered_ids if not category_by_id[key]["is_leaf_node"]]
        processed: set[str] = set()

        while pending:
            catalog_key = pending.pop(0)
            if catalog_key in processed:
                continue
            processed.add(catalog_key)
            parent = category_by_id[catalog_key]
            child_payload = self.request(
                "sub_level",
                catalog_key,
                request_payload={"catalogId": parent["product_catalog_id"]},
            )
            if not isinstance(child_payload, list):
                raise CollectionError(f"subLevel {catalog_key} did not return a category list")
            child_rows = flatten_category_tree(
                child_payload,
                parent_catalog_id=parent["product_catalog_id"],
                depth=int(parent["depth"]) + 1,
            )
            merge(child_rows)
            for child in child_rows:
                child_key = str(child["product_catalog_id"])
                if not child["is_leaf_node"] and child_key not in processed and child_key not in pending:
                    pending.append(child_key)

        rows = [category_by_id[key] for key in ordered_ids]
        write_jsonl_atomic(self.structured_dir / "categories.jsonl", rows)
        return rows

    def collect_product_lists(
        self,
        categories: Iterable[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        product_by_id: dict[str, dict[str, Any]] = {}
        ordered_product_ids: list[str] = []
        links: list[dict[str, Any]] = []
        seen_links: set[tuple[str, str]] = set()
        listings: list[dict[str, Any]] = []

        for category in categories:
            if not category.get("is_leaf_node"):
                continue
            catalog_id = category.get("product_catalog_id")
            first_result = 0
            while True:
                request_key = f"{catalog_id}_{first_result}"
                request_payload = {
                    "qryCriteriaKey": "PRODUCT_MSHOP_CATALOG",
                    "qryCriteriaValue": category.get("tree_path", ""),
                    "firstResult": first_result,
                    "maxResult": self.page_size,
                    "qrySortList": [],
                }
                response = self.request("query_info_list", request_key, request_payload=request_payload)
                if not isinstance(response, dict):
                    raise CollectionError(f"queryInfoList {request_key} did not return an object")
                page_rows = extract_product_records(response, category, first_result)
                listings.extend(page_rows)

                for listing in page_rows:
                    product_key = str(listing["product_id"])
                    catalog_key = str(catalog_id)
                    product = product_by_id.get(product_key)
                    if product is None:
                        raw_product = listing["raw_product"]
                        product = {
                            "product_id": listing["product_id"],
                            "product_code": listing["product_code"],
                            "product_name": listing["product_name"],
                            "is_multi_spec_enabled": bool(raw_product.get("isMultiSpecEnabled")),
                            "source_catalog_ids": [],
                            "source_tree_paths": [],
                            "raw_product": raw_product,
                            "raw_listing": listing["raw_listing"],
                        }
                        product_by_id[product_key] = product
                        ordered_product_ids.append(product_key)
                    if catalog_id not in product["source_catalog_ids"]:
                        product["source_catalog_ids"].append(catalog_id)
                    tree_path = category.get("tree_path", "")
                    if tree_path not in product["source_tree_paths"]:
                        product["source_tree_paths"].append(tree_path)

                    link_key = (product_key, catalog_key)
                    if link_key not in seen_links:
                        seen_links.add(link_key)
                        links.append(
                            {
                                "product_id": listing["product_id"],
                                "product_catalog_id": catalog_id,
                                "catalog_name": category.get("name", ""),
                                "tree_path": tree_path,
                            }
                        )

                data = response.get("data") or []
                count = int(response.get("count") or 0)
                received = len(data) if isinstance(data, list) else 0
                first_result += self.page_size
                if received < self.page_size or (count and first_result >= count):
                    break

        products = [product_by_id[key] for key in ordered_product_ids]
        write_jsonl_atomic(self.structured_dir / "products.jsonl", products)
        write_jsonl_atomic(self.structured_dir / "product_category_links.jsonl", links)
        write_jsonl_atomic(self.structured_dir / "listing_records.jsonl", listings)
        return products, links, listings

    def collect_details(
        self,
        products: Iterable[dict[str, Any]],
        *,
        include_spu: bool = True,
        spu_batch_size: int = 20,
        detail_workers: int = 1,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        product_rows = list(products)
        static_rows: list[dict[str, Any]] = []
        dynamic_rows: list[dict[str, Any]] = []
        static_by_id: dict[str, dict[str, Any]] = {}
        image_rows: dict[tuple[str, str], dict[str, Any]] = {}

        def merge_images(payload: Any, endpoint: str, product_id: Any) -> None:
            for row in extract_image_references(payload, endpoint, product_id):
                row["url"] = row["canonical_url"]
                key = (str(product_id), row["canonical_url"])
                current = image_rows.get(key)
                if current is None:
                    image_rows[key] = row
                    continue
                sources = set(str(current.get("source_endpoint", "")).split("|"))
                sources.add(endpoint)
                current["source_endpoint"] = "|".join(sorted(source for source in sources if source))

        worker_count = max(int(detail_workers), 1)
        thread_local = threading.local()

        def detail_client() -> Any:
            if worker_count == 1:
                return self.client
            if self.client_factory is None:
                raise CollectionError("detail_workers > 1 requires client_factory")
            if not hasattr(thread_local, "client"):
                thread_local.client = self.client_factory()
            return thread_local.client

        def fetch_product_details(product: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            product_id = product.get("product_id")
            if product_id in (None, ""):
                return product, {}, {}
            key = str(product_id)
            static_payload = self.request(
                "static_detail",
                key,
                request_payload={"productId": product_id},
                client=detail_client(),
            )
            if not isinstance(static_payload, dict):
                raise CollectionError(f"static detail {product_id} did not return an object")
            dynamic_payload = self.request(
                "dynamic_detail",
                key,
                request_payload={"productId": product_id},
                client=detail_client(),
            )
            if not isinstance(dynamic_payload, dict):
                raise CollectionError(f"dynamic detail {product_id} did not return an object")
            return product, static_payload, dynamic_payload

        if worker_count == 1:
            detail_results = [fetch_product_details(product) for product in product_rows]
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                detail_results = list(executor.map(fetch_product_details, product_rows))

        for product, static_payload, dynamic_payload in detail_results:
            product_id = product.get("product_id")
            if product_id in (None, ""):
                continue
            key = str(product_id)
            merge_images(product.get("raw_product") or {}, "query_info_list", product_id)
            merge_images(product.get("raw_listing") or {}, "query_info_list", product_id)
            static_rows.append(static_payload)
            static_by_id[key] = static_payload
            merge_images(static_payload, "static_detail", product_id)
            dynamic_rows.append(dynamic_payload)
            merge_images(dynamic_payload, "dynamic_detail", product_id)

        spu_rows: list[dict[str, Any]] = []
        if include_spu:
            batch_size = max(int(spu_batch_size), 1)
            for batch_index, start in enumerate(range(0, len(product_rows), batch_size)):
                batch = product_rows[start : start + batch_size]
                request_products = []
                product_ids = []
                for product in batch:
                    product_id = product.get("product_id")
                    if product_id in (None, ""):
                        continue
                    uom_id = product_uom_id(product, static_by_id.get(str(product_id)))
                    if uom_id in (None, ""):
                        self.store.append_record(
                            "collector_errors.jsonl",
                            {
                                "recorded_at": local_now(),
                                "endpoint": "spu_info",
                                "product_id": product_id,
                                "error": "missing_uom_id",
                            },
                        )
                        continue
                    product_ids.append(str(product_id))
                    request_products.append({"productId": product_id, "uomId": uom_id})
                if not request_products:
                    continue
                request_key = f"{batch_index}_{'_'.join(product_ids)}"
                request_payload = {
                    "fields": SPU_FIELDS,
                    "products": request_products,
                    "storeId": "",
                }
                response = self.request("spu_info", request_key, request_payload=request_payload)
                if not isinstance(response, dict):
                    raise CollectionError(f"SPU batch {request_key} did not return an object")
                datas = response.get("datas") or []
                if not isinstance(datas, list):
                    raise CollectionError(f"SPU batch {request_key} returned invalid datas")
                for row in datas:
                    if isinstance(row, dict):
                        spu_rows.append(row)
                        merge_images(row, "spu_info", row.get("productId", ""))

        images = sorted(
            image_rows.values(),
            key=lambda row: (str(row.get("product_id", "")), str(row.get("canonical_url", ""))),
        )
        write_jsonl_atomic(self.structured_dir / "static_details.jsonl", static_rows)
        write_jsonl_atomic(self.structured_dir / "dynamic_details.jsonl", dynamic_rows)
        write_jsonl_atomic(self.structured_dir / "spu_details.jsonl", spu_rows)
        write_jsonl_atomic(self.store.batch_dir / "discovered_image_urls.jsonl", images)
        return static_rows, dynamic_rows, spu_rows, images


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Collect all public Manlifang product data through mitmweb replay")
    parser.add_argument("--batch-dir", type=Path)
    parser.add_argument("--mitmweb-url", default="http://127.0.0.1:8081")
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--spu-batch-size", type=int, default=20)
    parser.add_argument("--detail-workers", type=int, default=1)
    parser.add_argument("--replay-timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--phase", choices=("categories", "products", "details", "all"), default="all")
    parser.add_argument("--skip-spu", action="store_true")
    parser.add_argument("--limit-products", type=int, default=0)
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    manlifang_dir = script_dir.parent
    if args.batch_dir:
        batch_dir = args.batch_dir.resolve()
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = manlifang_dir / "captures" / f"manlifang_full_{stamp}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    store = BatchStore(batch_dir)

    state_path = batch_dir / "collector_state.json"
    started_path = batch_dir / "capture_started_at.txt"
    if not started_path.exists():
        started_path.write_text(local_now(), encoding="utf-8")
    metadata = {
        "batch_id": batch_dir.name,
        "batch_dir": str(batch_dir),
        "source": "Manlifang anonymous public H5 API via local mitmweb replay",
        "collection_mode": "fresh_live_category_tree",
        "uses_legacy_3128_csv_as_input": False,
        "mitmweb_url": args.mitmweb_url,
        "page_size": args.page_size,
        "spu_batch_size": args.spu_batch_size,
        "detail_workers": args.detail_workers,
        "delay_seconds": args.delay,
        "created_at": local_now(),
    }
    write_json_atomic(batch_dir / "batch_metadata.json", metadata)

    request_counter = 0
    progress_lock = threading.Lock()

    def progress(endpoint: str, request_key: str, status_code: int, cached: bool) -> None:
        nonlocal request_counter
        with progress_lock:
            request_counter += 1
            source = "cached" if cached else "live"
            print(f"[{request_counter}] {source} {endpoint} {request_key} HTTP {status_code}", flush=True)
            write_json_atomic(
                state_path,
                {
                    "status": "running",
                    "last_endpoint": endpoint,
                    "last_request_key": request_key,
                    "last_status_code": status_code,
                    "last_was_cached": cached,
                    "requests_seen_this_run": request_counter,
                    "updated_at": local_now(),
                },
            )

    client = MitmwebClient(
        args.mitmweb_url,
        delay=args.delay,
        replay_timeout=args.replay_timeout,
    )

    def client_factory() -> MitmwebClient:
        return MitmwebClient(
            args.mitmweb_url,
            delay=args.delay,
            replay_timeout=args.replay_timeout,
        )

    collector = ManlifangCollector(
        client=client,
        client_factory=client_factory,
        store=store,
        page_size=args.page_size,
        progress=progress,
        max_retries=args.retries,
        retry_delay=args.retry_delay,
    )

    try:
        templates = client.refresh_templates()
        required = required_templates_for_run(batch_dir, phase=args.phase, skip_spu=args.skip_spu)
        missing = sorted(required - set(templates))
        if missing:
            raise CollectionError(f"missing mitmweb templates: {', '.join(missing)}")
        template_inventory = []
        for endpoint, flow_id in sorted(templates.items()):
            flow = client.template_flows.get(endpoint) or {}
            request = flow.get("request") or {}
            response = flow.get("response") or {}
            template_inventory.append(
                {
                    "endpoint": endpoint,
                    "flow_id": flow_id,
                    "method": request.get("method", ""),
                    "path": request.get("path", ""),
                    "status_code": response.get("status_code", ""),
                    "response_timestamp_end": response.get("timestamp_end", ""),
                }
            )
        write_json_atomic(batch_dir / "template_inventory.json", template_inventory)

        categories_path = collector.structured_dir / "categories.jsonl"
        if args.phase in {"categories", "products", "details", "all"}:
            categories = collector.collect_categories()
        else:
            categories = read_jsonl(categories_path)
        print(
            f"categories={len(categories)} leaves={sum(bool(row.get('is_leaf_node')) for row in categories)}",
            flush=True,
        )

        if args.phase == "categories":
            products: list[dict[str, Any]] = []
        else:
            products, links, listings = collector.collect_product_lists(categories)
            print(f"products={len(products)} links={len(links)} listings={len(listings)}", flush=True)

        if args.phase in {"details", "all"}:
            detail_products = products[: args.limit_products] if args.limit_products > 0 else products
            static_rows, dynamic_rows, spu_rows, images = collector.collect_details(
                detail_products,
                include_spu=not args.skip_spu,
                spu_batch_size=args.spu_batch_size,
                detail_workers=args.detail_workers,
            )
            print(
                f"static={len(static_rows)} dynamic={len(dynamic_rows)} spu={len(spu_rows)} images={len(images)}",
                flush=True,
            )

        completed_at = local_now()
        (batch_dir / "capture_completed_at.txt").write_text(completed_at, encoding="utf-8")
        write_json_atomic(
            state_path,
            {
                "status": "completed",
                "requests_seen_this_run": request_counter,
                "completed_at": completed_at,
            },
        )
        print(f"COLLECTION_COMPLETED batch_dir={batch_dir}", flush=True)
        return 0
    except KeyboardInterrupt:
        write_json_atomic(state_path, {"status": "interrupted", "updated_at": local_now()})
        print(f"COLLECTION_INTERRUPTED batch_dir={batch_dir}", file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        append_jsonl(
            batch_dir / "collector_errors.jsonl",
            {"recorded_at": local_now(), "error": repr(exc)},
        )
        write_json_atomic(
            state_path,
            {"status": "failed", "error": repr(exc), "updated_at": local_now()},
        )
        print(f"COLLECTION_FAILED batch_dir={batch_dir} error={exc!r}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
