from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


MANLIFANG_DIR = Path(__file__).resolve().parents[1]
if str(MANLIFANG_DIR) not in sys.path:
    sys.path.insert(0, str(MANLIFANG_DIR))

from collect_manlifang_full_via_mitmweb import (  # noqa: E402
    BatchStore,
    CollectionError,
    ManlifangCollector,
    MitmwebClient,
    ReplayResult,
    build_sublevel_path,
    extract_image_references,
    extract_product_records,
    flatten_category_tree,
    required_templates_for_run,
    select_template_flows,
)


class FakeReplayClient:
    def __init__(self, responses: dict[tuple[str, str], object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, object, object]] = []

    def replay(
        self,
        endpoint: str,
        *,
        request_key: str,
        request_payload: object = None,
        request_path: str | None = None,
    ) -> ReplayResult:
        self.calls.append((endpoint, request_key, request_payload, request_path))
        payload = self.responses[(endpoint, request_key)]
        return ReplayResult(
            endpoint=endpoint,
            flow_id=f"flow-{endpoint}-{request_key}",
            status_code=200,
            request_path=request_path or "",
            response_payload=payload,
        )


class FlakyReplayClient:
    def __init__(self) -> None:
        self.calls = 0

    def replay(self, endpoint: str, **kwargs: object) -> ReplayResult:
        self.calls += 1
        if self.calls == 1:
            raise CollectionError("transient replay timeout")
        return ReplayResult(
            endpoint=endpoint,
            flow_id="recovered-flow",
            status_code=200,
            request_path="",
            response_payload={"productId": 9001, "availQty": 8},
        )


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = "",
        payload: object = None,
        content: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = {"content-type": "application/json"}

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeCookies:
    def get(self, name: str) -> str | None:
        return "xsrf-token" if name == "_xsrf" else None


class FakeUpdatesSocket:
    def __init__(self) -> None:
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        return None

    def recv(self) -> str:
        return json.dumps(
            {
                "resource": "flows",
                "cmd": "update",
                "data": {
                    "id": "duplicate-static",
                    "response": {"status_code": 200, "timestamp_end": 20.0},
                },
            }
        )

    def close(self) -> None:
        self.closed = True


class FakeMitmSession:
    def __init__(self) -> None:
        self.cookies = FakeCookies()
        self.calls: list[tuple[str, str, object]] = []
        self.flow_reads = 0
        self.replayed = False
        self.template_flow = {
            "id": "template-static",
            "request": {
                "method": "POST",
                "path": "/mshop/MshopProduct/queryMshopProductDetailStaticArchives?time=1",
            },
            "response": {"status_code": 200, "timestamp_end": 10.0},
        }
        self.duplicate_old = {
            "id": "duplicate-static",
            "request": dict(self.template_flow["request"]),
            "response": {"status_code": 200, "timestamp_end": 10.0},
        }

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("GET", url, None))
        if url.endswith("/flows/duplicate-static/response/content.data"):
            return FakeResponse(content=b'{"productId":9001,"name":"detail"}')
        if url.endswith("/flows"):
            self.flow_reads += 1
            if self.flow_reads == 1:
                flows = [self.template_flow]
            elif not self.replayed:
                flows = [self.template_flow, self.duplicate_old]
            else:
                fresh = {
                    **self.duplicate_old,
                    "response": {"status_code": 200, "timestamp_end": 20.0},
                }
                flows = [self.template_flow, fresh]
            return FakeResponse(payload=flows)
        return FakeResponse(text="mitmweb")

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("POST", url, kwargs.get("json")))
        if url.endswith("/duplicate"):
            return FakeResponse(text="duplicate-static")
        if url.endswith("/replay"):
            self.replayed = True
        return FakeResponse()

    def put(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("PUT", url, kwargs.get("json")))
        return FakeResponse()

    def delete(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("DELETE", url, None))
        return FakeResponse()


def test_select_template_flows_prefers_stable_browser_flow_over_temporary_replay() -> None:
    flows = [
        {
            "id": "old-static",
            "request": {"path": "/mshop/MshopProduct/queryMshopProductDetailStaticArchives"},
            "response": {"status_code": 200, "timestamp_end": 10.0},
        },
        {
            "id": "failed-static",
            "request": {"path": "/mshop/MshopProduct/queryMshopProductDetailStaticArchives"},
            "response": {"status_code": 701, "timestamp_end": 30.0},
        },
        {
            "id": "new-static",
            "modified": True,
            "is_replay": "request",
            "request": {"path": "/mshop/MshopProduct/queryMshopProductDetailStaticArchives"},
            "response": {"status_code": 200, "timestamp_end": 20.0},
        },
        {
            "id": "query-all",
            "request": {"path": "/product/ProductCatalog/queryAll"},
            "response": {"status_code": 200, "timestamp_end": 15.0},
        },
    ]

    templates = select_template_flows(flows)

    assert templates["query_all"] == "query-all"
    assert templates["static_detail"] == "old-static"


def test_required_templates_for_run_uses_completed_structured_snapshot(tmp_path: Path) -> None:
    structured = tmp_path / "structured"
    structured.mkdir()
    (structured / "categories.jsonl").write_text('{"product_catalog_id":1}\n', encoding="utf-8")
    (structured / "products.jsonl").write_text('{"product_id":9001}\n', encoding="utf-8")

    required = required_templates_for_run(tmp_path, phase="all", skip_spu=False)

    assert required == {"static_detail", "dynamic_detail", "spu_info"}


def test_required_templates_for_run_needs_discovery_templates_for_empty_batch(tmp_path: Path) -> None:
    required = required_templates_for_run(tmp_path, phase="all", skip_spu=False)

    assert required == {
        "query_all",
        "sub_level",
        "query_info_list",
        "static_detail",
        "dynamic_detail",
        "spu_info",
    }


def test_mitmweb_client_replays_updated_body_waits_for_fresh_response_and_deletes_flow() -> None:
    session = FakeMitmSession()
    client = MitmwebClient(
        "http://127.0.0.1:8081",
        session=session,
        updates_socket_factory=lambda *args, **kwargs: FakeUpdatesSocket(),
        poll_interval=0,
        replay_timeout=2,
        delay=0,
        sleep=lambda _: None,
    )

    result = client.replay(
        "static_detail",
        request_key="9001",
        request_payload={"productId": 9001},
    )

    assert result.status_code == 200
    assert result.response_payload == {"productId": 9001, "name": "detail"}
    put_call = next(call for call in session.calls if call[0] == "PUT")
    assert put_call[2] == {"request": {"content": '{"productId":9001}'}}
    assert any(call[0] == "POST" and call[1].endswith("/replay") for call in session.calls)
    assert any(call[0] == "DELETE" and call[1].endswith("/duplicate-static") for call in session.calls)
    assert session.flow_reads == 1


def test_collector_retries_a_transient_replay_failure_and_marks_success(tmp_path: Path) -> None:
    client = FlakyReplayClient()
    collector = ManlifangCollector(
        client=client,
        store=BatchStore(tmp_path),
        page_size=20,
        max_retries=2,
        retry_delay=0,
        sleep=lambda _: None,
    )

    payload = collector.request(
        "dynamic_detail",
        "9001",
        request_payload={"productId": 9001},
    )

    assert payload == {"productId": 9001, "availQty": 8}
    assert client.calls == 2
    assert collector.store.is_completed("dynamic_detail", "9001")


def test_build_sublevel_path_replaces_catalog_id_and_preserves_query() -> None:
    template = "/cc/shop/product/ProductCatalog/subLevel/111?time=123&user_req_id=abc"

    assert build_sublevel_path(template, 987654321) == (
        "/cc/shop/product/ProductCatalog/subLevel/987654321?time=123&user_req_id=abc"
    )


def test_flatten_category_tree_preserves_hierarchy_and_leaf_state() -> None:
    tree = [
        {
            "productCatalogId": 1,
            "name": "按钮类目",
            "treePath": "按钮类目^",
            "isLeafNode": False,
            "subCatalog": [
                {
                    "productCatalogId": 2,
                    "name": "小圆按钮",
                    "treePath": "按钮类目^小圆按钮^",
                    "isLeafNode": True,
                    "subCatalog": [],
                }
            ],
        }
    ]

    rows = flatten_category_tree(tree)

    assert [row["product_catalog_id"] for row in rows] == [1, 2]
    assert rows[0]["parent_catalog_id"] == ""
    assert rows[0]["depth"] == 0
    assert rows[1]["parent_catalog_id"] == 1
    assert rows[1]["depth"] == 1
    assert rows[1]["is_leaf_node"] is True


def test_extract_product_records_uses_nested_product_id_and_category_membership() -> None:
    response = {
        "data": [
            {
                "id": 7001,
                "vRetailPrice": 12.5,
                "productId": {
                    "id": 9001,
                    "code": "B10001",
                    "name": "测试按钮",
                    "primaryImageList": ["https://img.example.com/main.jpg"],
                },
            }
        ],
        "count": 1,
        "idList": [9001],
    }
    category = {
        "product_catalog_id": 123,
        "tree_path": "按钮类目^小圆按钮^",
        "name": "小圆按钮",
    }

    rows = extract_product_records(response, category, first_result=0)

    assert len(rows) == 1
    assert rows[0]["product_id"] == 9001
    assert rows[0]["listing_id"] == 7001
    assert rows[0]["product_code"] == "B10001"
    assert rows[0]["source_catalog_id"] == 123
    assert rows[0]["source_tree_path"] == "按钮类目^小圆按钮^"
    assert rows[0]["page_first_result"] == 0
    assert rows[0]["raw_product"]["name"] == "测试按钮"


def test_extract_product_records_rejects_rows_without_a_product_id() -> None:
    response = {"data": [{"id": 7001, "productId": {"name": "缺少 ID"}}]}
    category = {"product_catalog_id": 123, "tree_path": "测试^", "name": "测试"}

    assert extract_product_records(response, category, first_result=0) == []


def test_extract_image_references_finds_lists_html_and_canonical_original_urls() -> None:
    payload = {
        "productId": 9001,
        "primaryImageList": ["https://img.example.com/main.jpg?x-oss-process=resize,w_300"],
        "detailImageList": ["https://img.example.com/detail-1.png"],
        "displayDescription": '<p><img src="https://img.example.com/content.webp?width=640"></p>',
    }

    rows = extract_image_references(payload, source_endpoint="static_detail", product_id=9001)
    by_canonical = {row["canonical_url"]: row for row in rows}

    assert set(by_canonical) == {
        "https://img.example.com/main.jpg",
        "https://img.example.com/detail-1.png",
        "https://img.example.com/content.webp",
    }
    assert by_canonical["https://img.example.com/main.jpg"]["image_role"] == "main"
    assert by_canonical["https://img.example.com/detail-1.png"]["image_role"] == "detail"
    assert by_canonical["https://img.example.com/content.webp"]["image_role"] == "description"
    assert by_canonical["https://img.example.com/main.jpg"]["original_url"].endswith("resize,w_300")


def test_batch_store_saves_raw_json_and_resumes_completed_keys(tmp_path: Path) -> None:
    store = BatchStore(tmp_path)

    relative = store.save_response(
        endpoint="query_info_list",
        request_key="catalog-123-page-0",
        request_payload={"firstResult": 0, "maxResult": 20},
        response_payload={"data": [], "count": 0},
        status_code=200,
        replay_flow_id="temporary-flow",
    )
    store.mark_completed("query_info_list", "catalog-123-page-0")

    saved = json.loads((tmp_path / relative).read_text(encoding="utf-8"))
    resumed = BatchStore(tmp_path)

    assert saved == {"data": [], "count": 0}
    assert resumed.is_completed("query_info_list", "catalog-123-page-0")
    lines = (tmp_path / "api_flows.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "temporary-flow" in lines[0]


@pytest.mark.parametrize("status", [701, 403, 429, 500])
def test_batch_store_does_not_mark_failed_requests_completed(tmp_path: Path, status: int) -> None:
    store = BatchStore(tmp_path)
    store.save_response(
        endpoint="static_detail",
        request_key="9001",
        request_payload={"productId": 9001},
        response_payload={"error": "blocked"},
        status_code=status,
        replay_flow_id="temporary-flow",
    )

    assert not store.is_completed("static_detail", "9001")


def test_collect_categories_recursively_fetches_incomplete_non_leaf_nodes(tmp_path: Path) -> None:
    client = FakeReplayClient(
        {
            (
                "query_all",
                "root",
            ): [
                {
                    "productCatalogId": 1,
                    "name": "根类目",
                    "treePath": "根类目^",
                    "isLeafNode": False,
                    "subCatalog": [],
                }
            ],
            (
                "sub_level",
                "1",
            ): [
                {
                    "productCatalogId": 2,
                    "name": "叶子 A",
                    "treePath": "根类目^叶子 A^",
                    "isLeafNode": True,
                    "subCatalog": [],
                },
                {
                    "productCatalogId": 3,
                    "name": "中间类目",
                    "treePath": "根类目^中间类目^",
                    "isLeafNode": False,
                    "subCatalog": [],
                },
            ],
            (
                "sub_level",
                "3",
            ): [
                {
                    "productCatalogId": 4,
                    "name": "叶子 B",
                    "treePath": "根类目^中间类目^叶子 B^",
                    "isLeafNode": True,
                    "subCatalog": [],
                }
            ],
        }
    )
    collector = ManlifangCollector(client=client, store=BatchStore(tmp_path), page_size=2)

    categories = collector.collect_categories()

    assert [row["product_catalog_id"] for row in categories] == [1, 2, 3, 4]
    assert categories[3]["parent_catalog_id"] == 3
    assert categories[3]["depth"] == 2
    assert [(call[0], call[1]) for call in client.calls] == [
        ("query_all", "root"),
        ("sub_level", "1"),
        ("sub_level", "3"),
    ]
    assert (tmp_path / "structured" / "categories.jsonl").exists()


def test_collect_product_lists_paginates_and_deduplicates_products(tmp_path: Path) -> None:
    page_0 = {
        "data": [
            {"id": 71, "productId": {"id": 901, "code": "A", "name": "商品 A"}},
            {"id": 72, "productId": {"id": 902, "code": "B", "name": "商品 B"}},
        ],
        "count": 3,
    }
    page_2 = {
        "data": [{"id": 73, "productId": {"id": 903, "code": "C", "name": "商品 C"}}],
        "count": 3,
    }
    duplicate_page = {
        "data": [{"id": 74, "productId": {"id": 901, "code": "A", "name": "商品 A"}}],
        "count": 1,
    }
    client = FakeReplayClient(
        {
            ("query_info_list", "10_0"): page_0,
            ("query_info_list", "10_2"): page_2,
            ("query_info_list", "20_0"): duplicate_page,
        }
    )
    categories = [
        {
            "product_catalog_id": 10,
            "name": "叶子 A",
            "tree_path": "根^叶子 A^",
            "is_leaf_node": True,
        },
        {
            "product_catalog_id": 20,
            "name": "叶子 B",
            "tree_path": "根^叶子 B^",
            "is_leaf_node": True,
        },
    ]
    collector = ManlifangCollector(client=client, store=BatchStore(tmp_path), page_size=2)

    products, links, listings = collector.collect_product_lists(categories)

    assert [row["product_id"] for row in products] == [901, 902, 903]
    assert len(links) == 4
    assert len(listings) == 4
    product_a = next(row for row in products if row["product_id"] == 901)
    assert product_a["source_catalog_ids"] == [10, 20]
    assert [(call[0], call[1]) for call in client.calls] == [
        ("query_info_list", "10_0"),
        ("query_info_list", "10_2"),
        ("query_info_list", "20_0"),
    ]
    assert (tmp_path / "structured" / "products.jsonl").exists()
    assert (tmp_path / "structured" / "product_category_links.jsonl").exists()


def test_collect_details_keeps_static_dynamic_spu_and_all_image_sources(tmp_path: Path) -> None:
    products = [
        {
            "product_id": 901,
            "product_code": "A",
            "product_name": "商品 A",
            "raw_product": {
                "id": 901,
                "salesUomId": {"id": 501},
                "primaryImageList": ["https://img.example.com/list-a.jpg?resize=200"],
            },
            "raw_listing": {},
        },
        {
            "product_id": 902,
            "product_code": "B",
            "product_name": "商品 B",
            "raw_product": {"id": 902, "baseUomId": {"id": 502}},
            "raw_listing": {},
        },
    ]
    client = FakeReplayClient(
        {
            (
                "static_detail",
                "901",
            ): {
                "productId": 901,
                "primaryImageList": ["https://img.example.com/a-main.jpg"],
                "primaryImageVoList": [
                    {"url": "https://img.example.com/a-main.jpg"},
                    {"url": "https://img.example.com/a-alt.jpg"},
                ],
                "displayDescription": '<img src="https://img.example.com/a-description.webp">',
            },
            ("dynamic_detail", "901"): {"productId": 901, "price": 10, "availQty": 5},
            ("static_detail", "902"): {"productId": 902, "primaryImageList": []},
            ("dynamic_detail", "902"): {"productId": 902, "price": 20, "availQty": 8},
            (
                "spu_info",
                "0_901_902",
            ): {
                "datas": [
                    {"productId": 901, "uomId": 501, "fields": []},
                    {"productId": 902, "uomId": 502, "fields": []},
                ]
            },
        }
    )
    collector = ManlifangCollector(
        client=client,
        client_factory=lambda: client,
        store=BatchStore(tmp_path),
        page_size=20,
    )

    static_rows, dynamic_rows, spu_rows, images = collector.collect_details(
        products,
        include_spu=True,
        spu_batch_size=20,
        detail_workers=2,
    )

    assert [row["productId"] for row in static_rows] == [901, 902]
    assert [row["productId"] for row in dynamic_rows] == [901, 902]
    assert [row["productId"] for row in spu_rows] == [901, 902]
    assert {row["canonical_url"] for row in images if row["product_id"] == 901} == {
        "https://img.example.com/list-a.jpg",
        "https://img.example.com/a-main.jpg",
        "https://img.example.com/a-alt.jpg",
        "https://img.example.com/a-description.webp",
    }
    spu_call = next(call for call in client.calls if call[0] == "spu_info")
    assert spu_call[2]["products"] == [
        {"productId": 901, "uomId": 501},
        {"productId": 902, "uomId": 502},
    ]
    assert (tmp_path / "structured" / "static_details.jsonl").exists()
    assert (tmp_path / "structured" / "dynamic_details.jsonl").exists()
    assert (tmp_path / "structured" / "spu_details.jsonl").exists()
    assert (tmp_path / "discovered_image_urls.jsonl").exists()
