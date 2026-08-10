"""自适应频控（浏览器执行层·执行节奏）。

目标：在反爬验证/批量采集中，把“固定延时”升级为“自适应节奏”：
- 成功 → 逐步回落（更快，但不下探到 min_delay 以下）；
- 失败 → 指数退避（最多到 max_delay）；
- 验证/风控拦截 → 直接跳到 blocked_delay 冷却；
- 每日请求上限 → 超出后停止，避免一次性触发大规模风控；
- 检查点（JSON）→ 跨批次保存节奏与计数，断点续跑不重来。

用法：

    pacer = AdaptivePacer(checkpoint=Path("runtime/state/1688/pacing.json"))
    pacer.wait_for_next()          # 采集前等待
    ... 采集请求 ...
    pacer.record_success()         # 或 record_failure(blocked=True)

配置 JSON（--pacing-config 传入）：
{
  "min_delay": 3.0,
  "max_delay": 90.0,
  "initial_delay": 5.0,
  "backoff_factor": 2.0,
  "recovery_factor": 0.5,
  "blocked_delay": 120.0,
  "daily_cap": 300
}
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional


@dataclass
class PacingState:
    """可持久化的频控状态。"""

    date: str
    delay: float
    requests: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    blocked: int = 0


class AdaptivePacer:
    """自适应频控器。纯 Python 实现，不依赖 playwright，便于单测。"""

    def __init__(
        self,
        *,
        min_delay: float = 3.0,
        max_delay: float = 90.0,
        initial_delay: float = 5.0,
        backoff_factor: float = 2.0,
        recovery_factor: float = 0.5,
        blocked_delay: float = 120.0,
        jitter_ratio: float = 0.3,
        daily_cap: Optional[int] = None,
        checkpoint: Optional[Path | str] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_delay <= 0:
            raise ValueError("min_delay must be positive")
        if max_delay < min_delay:
            raise ValueError("max_delay must be >= min_delay")
        if daily_cap is not None and daily_cap <= 0:
            raise ValueError("daily_cap must be positive when set")
        if not 0.0 <= jitter_ratio <= 1.0:
            raise ValueError("jitter_ratio must be in [0, 1]")
        self.min_delay = float(min_delay)
        self.max_delay = float(max_delay)
        self.backoff_factor = float(backoff_factor)
        self.recovery_factor = float(recovery_factor)
        self.blocked_delay = float(blocked_delay)
        self.jitter_ratio = float(jitter_ratio)
        self.daily_cap = daily_cap
        self.checkpoint = Path(checkpoint) if checkpoint else None
        self._sleep = sleep
        self._state = PacingState(
            date=date.today().isoformat(),
            delay=max(float(initial_delay), self.min_delay),
        )
        if self.checkpoint is not None:
            self.load()
        self._rollover_if_needed()

    # ---------- 状态 ----------

    @property
    def delay(self) -> float:
        return self._state.delay

    @property
    def requests_today(self) -> int:
        return self._state.requests

    @property
    def exceeded_daily_cap(self) -> bool:
        return self.daily_cap is not None and self._state.requests >= self.daily_cap

    def should_stop(self) -> bool:
        """达到每日上限时应停止采集。"""
        return self.exceeded_daily_cap

    def _rollover_if_needed(self) -> None:
        today = date.today().isoformat()
        if self._state.date == today:
            return
        self._state = PacingState(
            date=today,
            delay=self._state.delay,  # 节奏跨天保留
        )
        self._save()

    # ---------- 节奏 ----------

    def wait_for_next(self) -> float:
        """按当前节奏休眠，返回休眠秒数。"""
        self._rollover_if_needed()
        wait = self._state.delay * random.uniform(
            1.0 - self.jitter_ratio, 1.0 + self.jitter_ratio
        )
        self._sleep(wait)
        return wait

    def record_success(self) -> None:
        self._rollover_if_needed()
        self._state.requests += 1
        self._state.successes += 1
        self._state.consecutive_failures = 0
        self._state.delay = max(
            self.min_delay,
            self._state.delay * self.recovery_factor,
        )
        self._save()

    def record_failure(self, *, blocked: bool = False) -> None:
        self._rollover_if_needed()
        self._state.requests += 1
        self._state.failures += 1
        self._state.consecutive_failures += 1
        if blocked:
            self._state.blocked += 1
            self._state.delay = self.blocked_delay
        else:
            self._state.delay = min(
                self.max_delay,
                self._state.delay * self.backoff_factor,
            )
        self._save()

    # ---------- 检查点 ----------

    def _save(self) -> None:
        if self.checkpoint is None:
            return
        try:
            self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
            self.checkpoint.write_text(
                json.dumps(asdict(self._state), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass  # 检查点写入失败不阻断采集

    def load(self) -> None:
        if self.checkpoint is None or not self.checkpoint.is_file():
            return
        try:
            payload = json.loads(self.checkpoint.read_text(encoding="utf-8"))
            self._state = PacingState(
                date=str(payload.get("date", date.today().isoformat())),
                delay=float(payload.get("delay", self._state.delay)),
                requests=int(payload.get("requests", 0)),
                successes=int(payload.get("successes", 0)),
                failures=int(payload.get("failures", 0)),
                consecutive_failures=int(payload.get("consecutive_failures", 0)),
                blocked=int(payload.get("blocked", 0)),
            )
            self._state.delay = min(
                max(self._state.delay, self.min_delay), self.max_delay
            )
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            pass


def load_pacing_config(path: Path | str) -> dict:
    """读取频控配置 JSON（--pacing-config 使用）。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("pacing config must be a JSON object")
    allowed = {
        "min_delay",
        "max_delay",
        "initial_delay",
        "backoff_factor",
        "recovery_factor",
        "blocked_delay",
        "jitter_ratio",
        "daily_cap",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown pacing config keys: {sorted(unknown)}")
    return payload


def build_pacer(
    *,
    config_path: Optional[Path | str] = None,
    daily_cap: Optional[int] = None,
    checkpoint: Optional[Path | str] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> AdaptivePacer:
    """从配置 JSON 构造频控器；未提供配置时使用默认参数。"""
    kwargs: dict = {}
    if config_path:
        kwargs.update(load_pacing_config(config_path))
    if daily_cap is not None:
        kwargs["daily_cap"] = daily_cap
    return AdaptivePacer(checkpoint=checkpoint, sleep=sleep, **kwargs)
