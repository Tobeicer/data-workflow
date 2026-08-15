import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from run_1688_pipeline import run_pipeline  # noqa: E402


def test_run_pipeline_writes_ai_foundation_and_run_result(tmp_path):
    product_delivery = tmp_path / "product.json"
    manufacturer_delivery = tmp_path / "manufacturer.json"
    product_delivery.write_text(
        json.dumps(
            {
                "products": [
                    {
                        "source_platform": "1688",
                        "product_id": "1",
                        "product_url": "https://detail.1688.com/offer/1.html",
                        "title": "测试商品",
                        "main_image_url": "https://img.example.com/a.jpg",
                        "image_urls": [],
                        "detail_images_json": "[]",
                        "video_url": "",
                        "observed_at": "2026-08-13T10:00:00+08:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manufacturer_delivery.write_text(
        json.dumps({"manufacturers": []}),
        encoding="utf-8",
    )
    config = {
        "pipeline_version": "1.0.0",
        "source": "1688",
        "data_root": str(tmp_path / "data"),
        "media_root": str(tmp_path / "media"),
        "product_delivery": str(product_delivery),
        "manufacturer_delivery": str(manufacturer_delivery),
    }
    result = run_pipeline(config, media_limit=0)
    assert result["status"] == "success"
    assert result["stages"]["precheck"] == "success"
    assert result["stages"]["ai_foundation"] == "success"
    assert result["stages"]["media"] in ("success", "skipped")
    run_dir = Path(result["run_dir"])
    assert (run_dir / "run_result.json").exists()
    assert (tmp_path / "data" / "ai" / "1688" / "v1" / "products_kb.jsonl").exists()
