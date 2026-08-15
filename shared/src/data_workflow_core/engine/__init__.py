"""反风控爬虫引擎：独立、解耦、可移植的浏览器采集执行层。

引擎职责（平台无关）：

- 真实 Chrome + CDP 持久化会话（登录态复用）；
- 滑块/验证码检测、人工接管等待、触发即停铁律；
- 统一受限状态识别（复用 ``data_workflow_core.browser.detection``）；
- 任务描述 JSON → 受控执行 → 机器可读 run result；
- 统一 CLI：``run`` / ``selfcheck`` / ``login``（供 n8n 或人工调用）。

平台逻辑（搜索词、选择器、字段映射）不属于引擎，由各 adapter 的任务文件承载。
"""

from .cdp import CdpSession
from .antibot import (
    SLIDER_SELECTORS,
    SLIDER_TEXT,
    goto_guarded,
    restriction,
    should_stop_for_slider,
    slider_probe_js,
    slider_snapshot,
    wait_slider_clear,
)
from .config import (
    DEFAULT_ANTIBOT,
    ENGINE_VERSION,
    load_engine_config,
    resolve_path,
)
from .result import make_run_id, resolve_run_dir, write_jsonl, write_run_result
from .tasks import TaskError, TaskRunner, evaluate_module, page_text, validate_task

__all__ = [
    "CdpSession",
    "DEFAULT_ANTIBOT",
    "ENGINE_VERSION",
    "SLIDER_SELECTORS",
    "SLIDER_TEXT",
    "TaskError",
    "TaskRunner",
    "evaluate_module",
    "goto_guarded",
    "load_engine_config",
    "make_run_id",
    "page_text",
    "resolve_path",
    "resolve_run_dir",
    "restriction",
    "should_stop_for_slider",
    "slider_probe_js",
    "slider_snapshot",
    "validate_task",
    "wait_slider_clear",
    "write_jsonl",
    "write_run_result",
]
