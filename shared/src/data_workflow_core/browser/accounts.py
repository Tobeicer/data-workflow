"""多账号轮换（浏览器执行层·账号切换）。

目标：把单账号日额度（约 300 请求）扩展为 N 账号 × 日额度，按账号轮换实现
持续采集，从而在触发滑块后自动切换下一账号，而不是人工冷却等待。

配置（accounts.json）：
{
  "cooldown_seconds": 1800,
  "accounts": [
    {"alias": "main", "profile_dir": "runtime/browser-profiles/1688", "daily_quota": 300},
    {"alias": "alt1", "profile_dir": "runtime/browser-profiles/1688-alt1", "daily_quota": 300}
  ]
}

状态（runtime/state/accounts.json，git 忽略）：
{
  "main": {"date": "2026-08-13", "used_today": 120, "cooldown_until": null, "last_blocked_at": null}
}
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional


@dataclass
class Account:
    alias: str
    profile_dir: str
    daily_quota: int


@dataclass
class AccountState:
    date: str
    used_today: int = 0
    cooldown_until: Optional[float] = None
    last_blocked_at: Optional[float] = None


def _now_ts() -> float:
    return datetime.now().timestamp()


class AccountRotator:
    """按日额度 + 冷却状态在多账号间轮换。纯 Python，便于单测。"""

    def __init__(
        self,
        accounts: list[Account],
        *,
        state_path: Optional[Path | str] = None,
        cooldown_seconds: float = 1800.0,
        now: Optional[float] = None,
    ) -> None:
        if not accounts:
            raise ValueError("at least one account is required")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
        self._accounts = {account.alias: account for account in accounts}
        self._order = [account.alias for account in accounts]
        self.state_path = Path(state_path) if state_path else None
        self.cooldown_seconds = float(cooldown_seconds)
        self._now = now if now is not None else _now_ts
        self._cursor = 0
        self._states = {
            alias: AccountState(date=date.today().isoformat())
            for alias in self._order
        }
        if self.state_path is not None:
            self._load()
        self._rollover()

    # ---------- 状态读写 ----------

    def _load(self) -> None:
        if self.state_path is None or not self.state_path.is_file():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            for alias, raw in payload.items():
                if alias not in self._accounts:
                    continue
                self._states[alias] = AccountState(
                    date=str(raw.get("date", date.today().isoformat())),
                    used_today=int(raw.get("used_today", 0)),
                    cooldown_until=(
                        float(raw["cooldown_until"])
                        if raw.get("cooldown_until") is not None
                        else None
                    ),
                    last_blocked_at=(
                        float(raw["last_blocked_at"])
                        if raw.get("last_blocked_at") is not None
                        else None
                    ),
                )
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            pass

    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(
                    {
                        alias: asdict(state)
                        for alias, state in self._states.items()
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass  # 状态写入失败不阻断采集

    def _rollover(self) -> None:
        today = date.today().isoformat()
        for alias, state in self._states.items():
            if state.date != today:
                state.date = today
                state.used_today = 0
                state.cooldown_until = None
        self._save()

    # ---------- 账号判定 ----------

    def _usable(self, alias: str) -> bool:
        account = self._accounts[alias]
        state = self._states[alias]
        now = self._now()
        if state.used_today >= account.daily_quota:
            return False
        if state.cooldown_until is not None and now < state.cooldown_until:
            return False
        return True

    # ---------- 对外接口 ----------

    def current(self) -> Optional[Account]:
        """返回当前可用账号；若全部不可用则返回 None。"""
        for _ in range(len(self._order)):
            alias = self._order[self._cursor]
            if self._usable(alias):
                return self._accounts[alias]
            self._cursor = (self._cursor + 1) % len(self._order)
        return None

    def record_request(self, alias: str, *, blocked: bool = False) -> None:
        """记录一次请求；blocked=True 时把该账号送入冷却并切下一个。"""
        state = self._states[alias]
        self._rollover()
        state.used_today += 1
        if blocked:
            state.cooldown_until = self._now() + self.cooldown_seconds
            state.last_blocked_at = self._now()
            self._cursor = (self._order.index(alias) + 1) % len(self._order)
        self._save()

    def mark_blocked(self, alias: str) -> None:
        self.record_request(alias, blocked=True)

    def available_count(self) -> int:
        return sum(1 for alias in self._order if self._usable(alias))

    def can_continue(self) -> bool:
        return self.available_count() > 0


def load_accounts_config(path: Path | str) -> dict:
    """读取 accounts.json，返回配置字典（含 accounts 列表）。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("accounts config must be a JSON object")
    return payload


def build_rotator(
    *,
    config_path: Optional[Path | str] = None,
    state_path: Optional[Path | str] = None,
    default_profile_dir: Optional[str] = None,
    now: Optional[Callable[[], float]] = None,
) -> AccountRotator:
    """从配置 JSON 构造轮换器；未提供配置时退化为单账号轮换器。"""
    if not config_path:
        accounts = [
            Account(
                alias="default",
                profile_dir=default_profile_dir or "runtime/browser-profiles/1688",
                daily_quota=300,
            )
        ]
        return AccountRotator(accounts, state_path=state_path, now=now)
    config = load_accounts_config(config_path)
    cooldown_seconds = float(config.get("cooldown_seconds", 1800))
    accounts = [
        Account(
            alias=str(item["alias"]),
            profile_dir=str(item["profile_dir"]),
            daily_quota=int(item.get("daily_quota", 300)),
        )
        for item in config.get("accounts", [])
        if item.get("alias") and item.get("profile_dir")
    ]
    if not accounts:
        raise ValueError("accounts config has no valid accounts")
    return AccountRotator(
        accounts,
        state_path=state_path,
        cooldown_seconds=cooldown_seconds,
        now=now,
    )
