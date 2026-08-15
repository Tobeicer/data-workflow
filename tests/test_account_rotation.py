"""多账号轮换模块测试：日配额、冷却切换、跨天重置与状态持久化。"""

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared" / "src"))

from data_workflow_core.browser.accounts import (  # noqa: E402
    Account,
    AccountRotator,
    build_rotator,
)


def make_accounts() -> list[Account]:
    return [
        Account(alias="a", profile_dir="runtime/browser-profiles/1688-a", daily_quota=2),
        Account(alias="b", profile_dir="runtime/browser-profiles/1688-b", daily_quota=2),
    ]


def test_current_returns_first_available() -> None:
    rotator = AccountRotator(make_accounts(), now=lambda: 1000.0)
    assert rotator.current().alias == "a"


def test_mark_blocked_cools_and_switches() -> None:
    rotator = AccountRotator(
        make_accounts(), cooldown_seconds=1800.0, now=lambda: 1000.0
    )
    assert rotator.current().alias == "a"
    rotator.mark_blocked("a")
    assert rotator.current().alias == "b"
    # a 进入冷却，直到 2800 才可用
    assert rotator._states["a"].cooldown_until == 2800.0


def test_cooling_account_becomes_available_after_cooldown() -> None:
    clock = {"now": 1000.0}
    rotator = AccountRotator(
        make_accounts(), cooldown_seconds=1800.0, now=lambda: clock["now"]
    )
    rotator.mark_blocked("a")
    assert rotator.current().alias == "b"
    clock["now"] = 2900.0
    # b 仍然可用时，轮换器先给 b；但 a 已不再是冷却状态
    assert rotator.available_count() == 2


def test_daily_quota_exhausts_account() -> None:
    rotator = AccountRotator(make_accounts(), now=lambda: 1000.0)
    rotator.record_request("a")
    rotator.record_request("a")
    assert rotator.current().alias == "b"  # a 已达日额度 2


def test_all_exhausted_returns_none() -> None:
    rotator = AccountRotator(make_accounts(), now=lambda: 1000.0)
    for alias in ("a", "b"):
        rotator.record_request(alias)
        rotator.record_request(alias)
    assert rotator.current() is None
    assert not rotator.can_continue()


def test_state_roundtrip(tmp_path: Path) -> None:
    state = tmp_path / "accounts.json"
    rotator = AccountRotator(
        make_accounts(), state_path=state, now=lambda: 1000.0
    )
    rotator.record_request("a")
    rotator.mark_blocked("b")
    assert state.is_file()

    loaded = AccountRotator(make_accounts(), state_path=state, now=lambda: 1000.0)
    assert loaded._states["a"].used_today == 1
    assert loaded._states["b"].cooldown_until == 2800.0


def test_date_rollover_resets_counts(tmp_path: Path) -> None:
    state = tmp_path / "accounts.json"
    state.write_text(
        json.dumps(
            {
                "a": {
                    "date": "2000-01-01",
                    "used_today": 2,
                    "cooldown_until": 9999.0,
                    "last_blocked_at": 1000.0,
                }
            }
        ),
        encoding="utf-8",
    )
    rotator = AccountRotator(
        make_accounts(), state_path=state, now=lambda: 1000.0
    )
    assert rotator._states["a"].used_today == 0
    assert rotator._states["a"].cooldown_until is None


def test_build_rotator_from_config(tmp_path: Path) -> None:
    config = tmp_path / "accounts.json"
    config.write_text(
        json.dumps(
            {
                "cooldown_seconds": 1200,
                "accounts": [
                    {"alias": "a", "profile_dir": "p-a", "daily_quota": 5},
                    {"alias": "b", "profile_dir": "p-b", "daily_quota": 7},
                ],
            }
        ),
        encoding="utf-8",
    )
    rotator = build_rotator(config_path=config, now=lambda: 1000.0)
    assert rotator.cooldown_seconds == 1200
    assert rotator._accounts["a"].daily_quota == 5
    assert rotator._accounts["b"].daily_quota == 7
    assert rotator.current().alias == "a"


def test_build_rotator_defaults_to_single_account() -> None:
    rotator = build_rotator(
        default_profile_dir="runtime/browser-profiles/1688", now=lambda: 1000.0
    )
    assert rotator.current().alias == "default"
    assert rotator.current().profile_dir == "runtime/browser-profiles/1688"
