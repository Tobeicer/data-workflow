from __future__ import annotations

import sys
import types
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

try:
    import mitmproxy  # noqa: F401
except ModuleNotFoundError:
    mitmproxy = types.ModuleType("mitmproxy")
    mitmproxy.ctx = types.SimpleNamespace()
    mitmproxy.http = types.SimpleNamespace(HTTPFlow=object)
    sys.modules["mitmproxy"] = mitmproxy

import capture_manlifang_full as capture_module  # noqa: E402


def test_running_default_capture_directory_is_independent_of_cwd(
    monkeypatch,
    tmp_path: Path,
) -> None:
    expected = (
        Path(capture_module.__file__).resolve().parents[3]
        / "runtime"
        / "runs"
        / "manlifang"
        / "manual"
    )
    workdirs = (tmp_path / "repo", tmp_path / "repo" / "data-workflow")
    for workdir in workdirs:
        workdir.mkdir(parents=True, exist_ok=True)

    monkeypatch.delenv("MANLIFANG_CAPTURE_DIR", raising=False)
    monkeypatch.setattr(
        capture_module,
        "ctx",
        types.SimpleNamespace(
            options=types.SimpleNamespace(manlifang_capture_dir=""),
            log=types.SimpleNamespace(info=lambda _message: None),
        ),
    )
    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(Path, "exists", lambda _path: False)
    monkeypatch.setattr(Path, "write_text", lambda *_args, **_kwargs: 0)

    actual = []
    for workdir in workdirs:
        monkeypatch.chdir(workdir)
        capture = capture_module.ManlifangFullCapture()
        capture.running()
        actual.append(capture.output_dir)

    assert actual == [expected, expected]
