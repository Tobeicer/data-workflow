"""adaptive_pacing 模块测试：节奏演化、日限额与检查点持久化。"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "shared" / "src"))

from data_workflow_core.browser.pacing import (  # noqa: E402
    AdaptivePacer,
    build_pacer,
    load_pacing_config,
)


def make_pacer(**kwargs) -> tuple[AdaptivePacer, list[float]]:
    sleeps: list[float] = []
    kwargs.setdefault("sleep", sleeps.append)
    return AdaptivePacer(**kwargs), sleeps


def test_success_reduces_delay_toward_min() -> None:
    pacer, _ = make_pacer(min_delay=2.0, max_delay=60.0, initial_delay=8.0)
    pacer.record_success()
    assert pacer.delay == 4.0
    pacer.record_success()
    assert pacer.delay == 2.0
    pacer.record_success()
    assert pacer.delay == 2.0  # 不再下探


def test_failure_backs_off_and_clamps() -> None:
    pacer, _ = make_pacer(min_delay=2.0, max_delay=60.0, initial_delay=8.0)
    pacer.record_failure()
    assert pacer.delay == 16.0
    pacer.record_failure()
    assert pacer.delay == 32.0
    pacer.record_failure()
    assert pacer.delay == 60.0  # 封顶
    pacer.record_failure()
    assert pacer.delay == 60.0


def test_blocked_jumps_to_cooldown() -> None:
    pacer, _ = make_pacer(
        min_delay=2.0, max_delay=60.0, initial_delay=8.0, blocked_delay=120.0
    )
    pacer.record_failure(blocked=True)
    assert pacer.delay == 120.0
    assert pacer._state.blocked == 1
    assert pacer._state.consecutive_failures == 1


def test_success_resets_consecutive_failures() -> None:
    pacer, _ = make_pacer()
    pacer.record_failure()
    pacer.record_failure()
    assert pacer._state.consecutive_failures == 2
    pacer.record_success()
    assert pacer._state.consecutive_failures == 0


def test_wait_for_next_sleeps_current_delay() -> None:
    pacer, sleeps = make_pacer(initial_delay=5.0, jitter_ratio=0.0)
    waited = pacer.wait_for_next()
    assert waited == 5.0
    assert sleeps == [5.0]


def test_wait_for_next_applies_human_like_jitter() -> None:
    pacer, sleeps = make_pacer(initial_delay=10.0, jitter_ratio=0.3)
    waits = [pacer.wait_for_next() for _ in range(50)]
    assert all(7.0 <= w <= 13.0 for w in waits)  # 10 * (1 ± 0.3)
    assert len(set(waits)) > 1  # 存在随机波动
    assert len(sleeps) == 50


def test_jitter_ratio_validated() -> None:
    try:
        AdaptivePacer(jitter_ratio=1.5)
        raise AssertionError("should raise")
    except ValueError:
        pass


def test_daily_cap_stops() -> None:
    pacer, _ = make_pacer(daily_cap=3)
    assert not pacer.should_stop()
    pacer.record_success()
    pacer.record_success()
    pacer.record_success()
    assert pacer.exceeded_daily_cap
    assert pacer.should_stop()
    assert pacer.requests_today == 3


def test_initial_delay_clamped_to_min() -> None:
    pacer, _ = make_pacer(min_delay=5.0, max_delay=30.0, initial_delay=1.0)
    assert pacer.delay == 5.0


def test_invalid_params_rejected() -> None:
    try:
        AdaptivePacer(min_delay=0)
        raise AssertionError("should raise")
    except ValueError:
        pass
    try:
        AdaptivePacer(min_delay=10.0, max_delay=5.0)
        raise AssertionError("should raise")
    except ValueError:
        pass


def test_checkpoint_roundtrip(tmp_path: Path) -> None:
    checkpoint = tmp_path / "pacing.json"
    pacer, _ = make_pacer(
        min_delay=2.0, max_delay=90.0, initial_delay=5.0, checkpoint=checkpoint
    )
    pacer.record_failure()
    pacer.record_success()
    assert checkpoint.is_file()

    loaded, _ = make_pacer(
        min_delay=2.0, max_delay=90.0, initial_delay=5.0, checkpoint=checkpoint
    )
    assert loaded.delay == pacer.delay
    assert loaded.requests_today == 2
    assert loaded._state.successes == 1
    assert loaded._state.failures == 1


def test_checkpoint_date_rollover_resets_counts_keeps_delay(tmp_path: Path) -> None:
    checkpoint = tmp_path / "pacing.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    checkpoint.write_text(
        json.dumps(
            {
                "date": yesterday,
                "delay": 45.0,
                "requests": 300,
                "successes": 280,
                "failures": 20,
                "consecutive_failures": 3,
                "blocked": 2,
            }
        ),
        encoding="utf-8",
    )
    pacer, _ = make_pacer(min_delay=2.0, max_delay=90.0, checkpoint=checkpoint)
    assert pacer.requests_today == 0
    assert pacer._state.successes == 0
    assert pacer.delay == 45.0  # 节奏跨天保留


def test_load_pacing_config_and_build(tmp_path: Path) -> None:
    config = tmp_path / "pacing.json"
    config.write_text(
        json.dumps(
            {
                "min_delay": 4.0,
                "max_delay": 80.0,
                "initial_delay": 6.0,
                "backoff_factor": 1.5,
                "recovery_factor": 0.8,
                "blocked_delay": 100.0,
                "daily_cap": 120,
            }
        ),
        encoding="utf-8",
    )
    pacer = build_pacer(config_path=config, sleep=lambda s: None)
    assert pacer.min_delay == 4.0
    assert pacer.max_delay == 80.0
    assert pacer.delay == 6.0
    assert pacer.daily_cap == 120


def test_load_pacing_config_unknown_key_rejected(tmp_path: Path) -> None:
    config = tmp_path / "bad.json"
    config.write_text(json.dumps({"mystery": 1}), encoding="utf-8")
    try:
        load_pacing_config(config)
        raise AssertionError("should raise")
    except ValueError:
        pass
