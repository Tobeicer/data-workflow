from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BASE_DIR / "collect_taobao_full_workflow.py"


class TaobaoFullWorkflowHelpersTest(unittest.TestCase):
    def load_module(self):
        if not SCRIPT_PATH.exists():
            self.fail("collect_taobao_full_workflow.py should exist")
        spec = importlib.util.spec_from_file_location("collect_taobao_full_workflow", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module

    def test_search_url_and_item_id_helpers(self):
        module = self.load_module()

        self.assertIn("%E6%8A%95%E5%B8%81%E5%99%A8", module.search_url("投币器"))
        self.assertEqual(module.item_id_from_url("https://item.taobao.com/item.htm?id=123456789"), "123456789")
        self.assertEqual(module.item_id_from_url("https://detail.tmall.com/item.htm?id=987654321"), "987654321")

    def test_parse_parameter_lines_handles_common_taobao_orders(self):
        module = self.load_module()
        text = """
        男女通用 适用性别
        通利 品牌
        8岁 适用年龄段
        型号 TW--131
        控制系统 游艺机
        颜色分类 银色投币器,黄色投币器
        """

        attrs = module.parse_parameter_lines(text)

        self.assertEqual(attrs["适用性别"], "男女通用")
        self.assertEqual(attrs["品牌"], "通利")
        self.assertEqual(attrs["适用年龄段"], "8岁")
        self.assertEqual(attrs["型号"], "TW--131")
        self.assertEqual(attrs["控制系统"], "游艺机")
        self.assertEqual(attrs["颜色分类"], "银色投币器,黄色投币器")

    def test_merge_rows_keeps_full_output_without_intermediate_files(self):
        module = self.load_module()
        search_rows = [
            {
                "keyword": "投币器",
                "product_title": "通利投币器",
                "product_url": "https://item.taobao.com/item.htm?id=123456789",
                "item_id": "123456789",
                "price_text": "¥ 32",
                "shop_name": "漫立方",
                "shop_url": "https://shop.example.com",
                "location": "广东广州",
                "sales_text": "已售100",
                "image_url": "https://img.example.com/a.jpg",
            },
            {
                "keyword": "娃娃机配件",
                "product_title": "通利投币器",
                "product_url": "https://item.taobao.com/item.htm?id=123456789",
                "item_id": "123456789",
                "price_text": "¥ 32",
                "shop_name": "漫立方",
                "shop_url": "https://shop.example.com",
                "location": "广东广州",
                "sales_text": "已售100",
                "image_url": "https://img.example.com/a.jpg",
            },
        ]
        detail_rows = [
            {
                "item_id": "123456789",
                "product_url": "https://item.taobao.com/item.htm?id=123456789",
                "title": "通利投币器详情",
                "price_text": "¥ 32.7",
                "model": "TW-131",
                "brand": "通利",
                "control_system": "游艺机",
                "payment_method": "投币",
                "theme_style": "动漫",
                "color_category": "银色,黄色",
                "origin_place": "广州番禺",
                "applicable_scene": "电玩城",
                "applicable_age": "6-80岁",
                "device_type": "娃娃机",
                "applicable_gender": "男女通用",
                "attributes_json": '{"型号":"TW-131"}',
                "collected_at": "2026-07-09 18:00:00",
                "capture_status": "success",
                "capture_note": "",
            }
        ]

        merged = module.merge_search_and_detail_rows(search_rows, detail_rows)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["keywords"], "娃娃机配件、投币器")
        self.assertEqual(merged[0]["model"], "TW-131")
        self.assertEqual(merged[0]["search_price_text"], "¥ 32")
        self.assertEqual(merged[0]["detail_price_text"], "¥ 32.7")

    def test_help_does_not_require_playwright_import(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("--prepare-login", result.stdout)


if __name__ == "__main__":
    unittest.main()
