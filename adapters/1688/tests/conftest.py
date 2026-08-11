"""测试隔离：注册表默认路径指向临时目录，避免污染真实采集状态。"""

import pytest


@pytest.fixture(autouse=True)
def isolate_collect_registry(tmp_path, monkeypatch):
    import collect_registry

    monkeypatch.setattr(
        collect_registry,
        "DEFAULT_REGISTRY_PATH",
        tmp_path / "registry.json",
    )
