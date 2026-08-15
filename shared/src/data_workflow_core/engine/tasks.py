"""任务描述 JSON → 受控执行。

任务描述是引擎唯一的"采集计划"输入：由平台 adapter 生成，引擎执行。
动作词表固定且平台无关：

- ``goto``         带滑块守卫的页面跳转
- ``evaluate``     执行页面 JS（内联表达式或 CommonJS 文件里的函数）
- ``write_jsonl``  把上下文中的行列表追加写入 run_dir 内 JSONL
- ``sleep``        固定延时
- ``loop``         对上下文列表逐项执行嵌套步骤
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .antibot import goto_guarded, restriction, should_stop_for_slider
from .config import DEFAULT_ANTIBOT, ENGINE_VERSION
from .result import write_jsonl

ACTIONS = {"goto", "evaluate", "write_jsonl", "sleep", "loop"}
_TOKEN = re.compile(r"\{(\w+)\}")


class TaskError(Exception):
    """任务描述不合法或执行语义错误。"""


class _StopRun(Exception):
    """受控停止：携带机器状态，不视为程序错误。"""

    def __init__(self, status: str, note: str = "") -> None:
        super().__init__(status)
        self.status = status
        self.note = note


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def render_template(template: str, params: dict[str, Any]) -> str:
    """渲染 ``{name}`` 占位符；缺失参数报 TaskError。"""
    missing = [m for m in _TOKEN.findall(template) if m not in params]
    if missing:
        raise TaskError(f"template missing params: {missing}")
    return _TOKEN.sub(lambda m: str(params[m.group(1)]), template)


def _is_safe_relative_path(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _step_errors(step: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    action = step.get("action")
    if action not in ACTIONS:
        errors.append(f"unknown action: {action!r}")
        return errors
    if action == "goto" and not isinstance(step.get("url"), str):
        errors.append("goto step requires string 'url'")
    if action == "evaluate" and not (
        isinstance(step.get("expr"), str)
        or (isinstance(step.get("js_file"), str) and isinstance(step.get("function"), str))
    ):
        errors.append("evaluate step requires 'expr' or 'js_file'+'function'")
    if action == "write_jsonl":
        if not isinstance(step.get("rows"), str) or not isinstance(step.get("path"), str):
            errors.append("write_jsonl step requires 'rows' and 'path'")
        elif not _is_safe_relative_path(step["path"]):
            errors.append("write_jsonl path must be relative and stay inside run_dir")
    if action == "sleep" and not isinstance(step.get("seconds"), (int, float)):
        errors.append("sleep step requires numeric 'seconds'")
    if action == "loop":
        if not isinstance(step.get("items"), str) or not isinstance(step.get("steps"), list):
            errors.append("loop step requires 'items' and nested 'steps'")
        else:
            for nested in step["steps"]:
                if isinstance(nested, dict):
                    errors.extend(_step_errors(nested))
    return errors


def validate_task(spec: dict[str, Any]) -> list[str]:
    """返回任务描述的全部错误；空列表表示合法。"""
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["task spec must be a JSON object"]
    if not isinstance(spec.get("task_id"), str) or not spec["task_id"].strip():
        errors.append("task spec requires non-empty string 'task_id'")
    if not isinstance(spec.get("steps"), list) or not spec["steps"]:
        errors.append("task spec requires non-empty list 'steps'")
    else:
        for index, step in enumerate(spec["steps"]):
            if not isinstance(step, dict):
                errors.append(f"steps[{index}] must be an object")
                continue
            for error in _step_errors(step):
                errors.append(f"steps[{index}]: {error}")
    if "params" in spec and not isinstance(spec["params"], dict):
        errors.append("'params' must be an object")
    return errors


def _module_eval_js(js: str, function: str) -> str:
    """把 CommonJS 风格 JS 文件包装为可调用表达式（单参数数组解构）。"""
    return (
        "(arg) => {"
        "const [js, fnName, params] = arg;"
        "const module = {exports: {}};"
        "(function (module, exports) {\n"
        + js
        + "\n})(module, module.exports);"
        "return module.exports[fnName](params);"
        "}"
    )


def evaluate_module(
    page: Any, js: str, function: str, params: dict[str, Any] | None = None
) -> Any:
    """执行 CommonJS 风格 JS 文件中导出的函数（平台提取器统一调用方式）。"""
    return page.evaluate(
        _module_eval_js(js, function), [js, function, params or {}]
    )


def page_text(page: Any, limit: int = 6000) -> str:
    return page.evaluate(
        f"() => document.body ? (document.body.innerText || '').slice(0, {int(limit)}) : ''"
    )


class TaskRunner:
    """在给定 page 上执行任务描述；受控停止写进 report.status。"""

    def __init__(
        self,
        spec: dict[str, Any],
        page: Any,
        *,
        task_dir: str | Path,
        run_dir: str | Path,
        log: Any = print,
    ) -> None:
        errors = validate_task(spec)
        if errors:
            raise TaskError("; ".join(errors))
        self.spec = spec
        self.page = page
        self.task_dir = Path(task_dir)
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log = log
        antibot = dict(DEFAULT_ANTIBOT)
        antibot.update(spec.get("antibot") or {})
        self.antibot = antibot
        self.slider_events = 0
        self.steps_done = 0
        self.artifacts: dict[str, str] = {}
        self.ctx: dict[str, Any] = {"params": dict(spec.get("params") or {})}
        self.status = "running"

    def run(self) -> dict[str, Any]:
        started = _now_iso()
        error: dict[str, Any] | None = None
        try:
            for step in self.spec["steps"]:
                self._run_step(step)
                self.steps_done += 1
            self.status = "completed"
        except _StopRun as stop:
            self.status = stop.status
            if stop.note:
                self.log(f"STOP {stop.status}: {stop.note}", flush=True)
        except TaskError as exc:
            self.status = "failed"
            error = {"type": "task_error", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            self.status = "failed"
            error = {"type": type(exc).__name__, "message": str(exc)}
        return {
            "engine_version": ENGINE_VERSION,
            "task_id": self.spec.get("task_id"),
            "source": self.spec.get("source", "unknown"),
            "mode": self.spec.get("mode", "collect"),
            "status": self.status,
            "slider_events": self.slider_events,
            "steps_done": self.steps_done,
            "artifacts": self.artifacts,
            "started_at": started,
            "finished_at": _now_iso(),
            "error": error,
        }

    # -- 步骤执行 ----------------------------------------------------------

    def _run_step(self, step: dict[str, Any]) -> None:
        action = step["action"]
        if action == "goto":
            self._goto(step)
        elif action == "evaluate":
            self._evaluate(step)
        elif action == "write_jsonl":
            self._write_jsonl(step)
        elif action == "sleep":
            time.sleep(float(step["seconds"]))
        elif action == "loop":
            self._loop(step)
        if action != "loop":
            self.log(f"step_done {action} {step.get('label', '')}".strip(), flush=True)

    def _goto(self, step: dict[str, Any]) -> None:
        params = dict(self.ctx["params"])
        params.update(step.get("params") or {})
        url = render_template(step["url"], params)
        result = goto_guarded(
            self.page,
            url,
            timeout_ms=int(self.antibot["page_timeout_ms"]),
            settle_ms=int(self.antibot["settle_ms"]),
            budget=float(self.antibot["slider_budget_s"]),
            cooldown=float(self.antibot["slider_cooldown_s"]),
            on_seen=lambda: self.log(
                "SLIDER: 请在打开的 Chrome 窗口手动完成验证，脚本会等待并继续", flush=True
            ),
        )
        if result["seen"]:
            self.slider_events += 1
        if not result["solved"]:
            raise _StopRun("stopped_slider", "验证未在预算时间内清除")
        status, note = restriction(page_url=self.page.url)
        for pattern in self.antibot.get("restriction_url_patterns") or []:
            if status == "" and re.search(pattern, self.page.url or ""):
                status = "human_verification_required"
                note = f"url matched: {pattern}"
        if status:
            raise _StopRun(status, note)
        if should_stop_for_slider(
            self.slider_events, int(self.antibot["max_slider_events"])
        ):
            raise _StopRun("stopped_slider", "验证事件达到上限")

    def _evaluate(self, step: dict[str, Any]) -> None:
        params = step.get("params") or {}
        if "expr" in step:
            value = self.page.evaluate(step["expr"])
        else:
            js_file = self.task_dir / step["js_file"]
            js = js_file.read_text(encoding="utf-8")
            value = evaluate_module(self.page, js, step["function"], params)
        self.ctx[step.get("store") or "_last"] = value

    def _write_jsonl(self, step: dict[str, Any]) -> None:
        rows = self.ctx.get(step["rows"])
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise TaskError(f"rows {step['rows']!r} is not a list in context")
        target = (self.run_dir / step["path"]).resolve()
        if self.run_dir.resolve() not in target.parents:
            raise TaskError("write_jsonl path escapes run_dir")
        write_jsonl(target, rows)
        label = step.get("label") or step["path"]
        self.artifacts[label] = str(target)

    def _loop(self, step: dict[str, Any]) -> None:
        items = self.ctx.get(step["items"])
        if items is None:
            raise TaskError(f"loop items {step['items']!r} not found in context")
        if not isinstance(items, list):
            raise TaskError(f"loop items {step['items']!r} is not a list")
        var = step["var"]
        for item in items[: int(step.get("max_items") or len(items))]:
            self.ctx[var] = item
            for nested in step["steps"]:
                self._run_step(nested)
