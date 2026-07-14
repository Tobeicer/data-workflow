from __future__ import annotations

import builtins
import contextlib
import importlib.util
import io
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "src" / "run_source.py"
SRC_DIR = SCRIPT_PATH.parent
WORKFLOW_DIR = SCRIPT_PATH.parents[3]
PROFILE_DIR = WORKFLOW_DIR / "runtime" / "browser-profiles" / "taobao"
DEBUG_DIR = WORKFLOW_DIR / "runtime" / "tmp" / "taobao"
RUNS_DIR = WORKFLOW_DIR / "runtime" / "runs" / "taobao"


def snapshot_path(path: Path) -> tuple[object, ...]:
    if not path.exists():
        return ("missing",)
    entries = [path, *sorted(path.rglob("*"), key=lambda item: item.as_posix())]
    return tuple(
        (
            item.relative_to(path).as_posix() if item != path else ".",
            item.is_dir(),
            item.stat().st_size,
            item.stat().st_mtime_ns,
        )
        for item in entries
    )


class TaobaoFullWorkflowHelpersTest(unittest.TestCase):
    def load_module(self):
        if not SCRIPT_PATH.exists():
            self.fail("formal Taobao run_source.py should exist")
        spec = importlib.util.spec_from_file_location("taobao_run_source", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module

    def run_main(self, module, cwd: Path, *args: str) -> str:
        previous_cwd = Path.cwd()
        output = io.StringIO()
        try:
            os.chdir(cwd)
            with mock.patch.object(sys, "argv", [str(SCRIPT_PATH), *args]):
                with contextlib.redirect_stdout(output):
                    module.main()
        finally:
            os.chdir(previous_cwd)
        return output.getvalue()

    def test_migrated_module_resolves_runtime_paths_from_file(self):
        module = self.load_module()

        self.assertEqual(module.SRC_DIR, SRC_DIR)
        self.assertEqual(module.WORKFLOW_DIR, WORKFLOW_DIR)
        self.assertEqual(module.PROFILE_DIR, PROFILE_DIR)
        self.assertEqual(module.DEBUG_DIR, DEBUG_DIR)
        self.assertEqual(module.RUNS_DIR, RUNS_DIR)

    def test_default_output_path_uses_timestamped_l1_runtime_batch(self):
        module = self.load_module()

        self.assertEqual(
            module.default_output_path("20260714_120000"),
            RUNS_DIR
            / "taobao_20260714_120000"
            / "l1"
            / "taobao_product_full_20260714_120000.csv",
        )

    def test_dry_run_is_offline_cwd_independent_and_asset_side_effect_free(self):
        guarded_paths = (RUNS_DIR, PROFILE_DIR, DEBUG_DIR)
        before = {path: snapshot_path(path) for path in guarded_paths}
        playwright_modules_before = {
            name
            for name in sys.modules
            if name == "playwright" or name.startswith("playwright.")
        }

        def reject_process(*_args, **_kwargs):
            raise AssertionError("dry-run attempted to start a subprocess")

        def reject_network(*_args, **_kwargs):
            raise AssertionError("dry-run attempted to use the network")

        real_import = builtins.__import__

        def reject_playwright_import(
            name, globals=None, locals=None, fromlist=(), level=0
        ):
            if name == "playwright" or name.startswith("playwright."):
                raise AssertionError("dry-run attempted to import Playwright")
            return real_import(name, globals, locals, fromlist, level)

        with contextlib.ExitStack() as stack:
            for attribute in ("run", "Popen", "call", "check_call", "check_output"):
                stack.enter_context(mock.patch.object(subprocess, attribute, reject_process))
            for attribute in ("socket", "create_connection", "getaddrinfo"):
                stack.enter_context(mock.patch.object(socket, attribute, reject_network))
            stack.enter_context(
                mock.patch.object(builtins, "__import__", reject_playwright_import)
            )

            module = self.load_module()
            with (
                tempfile.TemporaryDirectory() as first_cwd,
                tempfile.TemporaryDirectory() as second_cwd,
            ):
                first = self.run_main(module, Path(first_cwd), "--dry-run")
                second = self.run_main(module, Path(second_cwd), "--dry-run")
                self.assertEqual(list(Path(first_cwd).iterdir()), [])
                self.assertEqual(list(Path(second_cwd).iterdir()), [])

        self.assertEqual(first, second)
        self.assertIn(f"profile: {PROFILE_DIR}", first)
        self.assertIn(f"debug: {DEBUG_DIR}", first)
        self.assertIn(
            f"output: {RUNS_DIR / 'taobao_<timestamp>' / 'l1' / 'taobao_product_full_<timestamp>.csv'}",
            first,
        )
        self.assertIn(
            "plan: public search -> detail enrichment -> in-memory merge -> L1 CSV",
            first,
        )
        self.assertEqual({path: snapshot_path(path) for path in guarded_paths}, before)
        self.assertEqual(
            {
                name
                for name in sys.modules
                if name == "playwright" or name.startswith("playwright.")
            },
            playwright_modules_before,
        )

    def test_dry_run_resolves_explicit_relative_output_from_user_cwd(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as cwd:
            cwd_path = Path(cwd)
            output = self.run_main(
                module, cwd_path, "--dry-run", "--output", "planned.csv"
            )

            self.assertIn(f"output: {(cwd_path / 'planned.csv').resolve()}", output)
            self.assertFalse((cwd_path / "planned.csv").exists())

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
        self.assertIn("--dry-run", result.stdout)


if __name__ == "__main__":
    unittest.main()
