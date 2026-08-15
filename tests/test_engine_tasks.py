"""引擎任务描述校验与执行测试（FakePage，离线）。"""

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared" / "src"))

from data_workflow_core.engine.tasks import (  # noqa: E402
    TaskError,
    TaskRunner,
    render_template,
    validate_task,
)


class FakePage:
    """最小 page 替身：可模拟滑块出现与 URL 受限。"""

    def __init__(self, *, slider_active: bool = False) -> None:
        self.slider_active = slider_active
        self.url = "https://detail.1688.com/offer/1.html"
        self.goto_calls: list[str] = []
        self.wait_ms: list[int] = []

    def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        self.goto_calls.append(url)
        self.url = url

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_ms.append(ms)

    def evaluate(self, expr: str, arg: Any = None) -> Any:
        if "querySelectorAll" in expr:
            return {"active": self.slider_active, "selectors": [], "textHint": False}
        return None


class DataPage(FakePage):
    """按调用顺序吐数据的 page：先列表，后单条记录。"""

    def __init__(self, first: Any, then: Any) -> None:
        super().__init__()
        self.first = first
        self.then = then
        self.used_first = False

    def evaluate(self, expr: str, arg: Any = None) -> Any:
        if "querySelectorAll" in expr:
            return {"active": False, "selectors": [], "textHint": False}
        if not self.used_first:
            self.used_first = True
            return self.first
        return self.then


class RedirectPage(FakePage):
    """goto 后页面被重定向到登录页。"""

    def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        self.goto_calls.append(url)
        self.url = "https://login.1688.com/member/signin.htm"


def make_spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "task_id": "t1",
        "source": "1688",
        "mode": "collect",
        "steps": [{"action": "sleep", "seconds": 0}],
    }
    spec.update(overrides)
    return spec


# -- 校验 -----------------------------------------------------------------


def test_validate_accepts_minimal_spec() -> None:
    assert validate_task(make_spec()) == []


def test_validate_rejects_missing_task_id() -> None:
    errors = validate_task({"steps": [{"action": "sleep", "seconds": 0}]})
    assert any("task_id" in e for e in errors)


def test_validate_rejects_unknown_action() -> None:
    errors = validate_task(make_spec(steps=[{"action": "click", "xpath": "//a"}]))
    assert any("unknown action" in e for e in errors)


def test_validate_rejects_goto_without_url() -> None:
    errors = validate_task(make_spec(steps=[{"action": "goto"}]))
    assert any("requires string 'url'" in e for e in errors)


def test_validate_rejects_unsafe_jsonl_path() -> None:
    for path in ("../escape.jsonl", r"C:\\tmp\\abs.jsonl"):
        spec = make_spec(
            steps=[{"action": "write_jsonl", "rows": "r", "path": path}]
        )
        errors = validate_task(spec)
        assert any("relative" in e for e in errors)


def test_validate_rejects_loop_without_items() -> None:
    spec = make_spec(steps=[{"action": "loop", "steps": []}])
    assert any("requires 'items'" in e for e in validate_task(spec))


def test_render_template_missing_param_raises() -> None:
    with pytest.raises(TaskError):
        render_template("https://x.com?kw={keyword}", {})


def test_render_template_ok() -> None:
    assert (
        render_template("https://x.com?kw={keyword}", {"keyword": "娃娃机"})
        == "https://x.com?kw=娃娃机"
    )


# -- 执行 -----------------------------------------------------------------


def test_run_completes_with_write_jsonl(tmp_path: Path) -> None:
    spec = make_spec(
        steps=[
            {
                "action": "evaluate",
                "expr": "() => [{a: 1}, {a: 2}]",
                "store": "rows",
            },
            {
                "action": "write_jsonl",
                "rows": "rows",
                "path": "l0/rows.jsonl",
                "label": "rows",
            },
        ]
    )
    runner = TaskRunner(
        spec,
        DataPage([{"a": 1}, {"a": 2}], None),
        task_dir=tmp_path,
        run_dir=tmp_path / "run",
    )
    report = runner.run()
    assert report["status"] == "completed"
    lines = (tmp_path / "run" / "l0" / "rows.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "rows" in report["artifacts"]


def test_goto_slider_unresolved_stops_with_iron_rule(tmp_path: Path) -> None:
    spec = make_spec(
        antibot={"slider_budget_s": 0.05, "settle_ms": 0},
        steps=[{"action": "goto", "url": "https://s.1688.com/x", "label": "search"}],
    )
    runner = TaskRunner(
        spec,
        FakePage(slider_active=True),
        task_dir=tmp_path,
        run_dir=tmp_path / "run",
    )
    report = runner.run()
    assert report["status"] == "stopped_slider"
    assert report["slider_events"] == 1


def test_goto_login_redirect_stops_login_required(tmp_path: Path) -> None:
    spec = make_spec(
        antibot={"slider_budget_s": 0.05, "settle_ms": 0},
        steps=[{"action": "goto", "url": "https://detail.1688.com/offer/1.html"}],
    )
    runner = TaskRunner(spec, RedirectPage(), task_dir=tmp_path, run_dir=tmp_path / "run")
    report = runner.run()
    assert report["status"] == "login_required"


def test_loop_writes_each_item(tmp_path: Path) -> None:
    spec = make_spec(
        steps=[
            {
                "action": "loop",
                "items": "items",
                "var": "item",
                "steps": [
                    {
                        "action": "write_jsonl",
                        "rows": "item",
                        "path": "l0/out.jsonl",
                    },
                ],
            },
        ]
    )
    runner = TaskRunner(
        spec,
        DataPage(None, None),
        task_dir=tmp_path,
        run_dir=tmp_path / "run",
    )
    runner.ctx["items"] = [{"id": 1}, {"id": 2}, {"id": 3}]
    report = runner.run()
    assert report["status"] == "completed"
    lines = (tmp_path / "run" / "l0" / "out.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_write_jsonl_accepts_single_object(tmp_path: Path) -> None:
    spec = make_spec(
        steps=[
            {
                "action": "write_jsonl",
                "rows": "row",
                "path": "l0/one.jsonl",
            },
        ]
    )
    runner = TaskRunner(spec, FakePage(), task_dir=tmp_path, run_dir=tmp_path / "run")
    runner.ctx["row"] = {"only": 1}
    report = runner.run()
    assert report["status"] == "completed"
    lines = (tmp_path / "run" / "l0" / "one.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
