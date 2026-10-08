from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from jobseeker.config import ContactsConfig


@dataclass(frozen=True)
class Limit:
    period: Literal["day", "month"]
    global_cap: float
    share_cap: float


def contacts_limits(cfg: ContactsConfig) -> dict[str, Limit]:
    """One user (the owner): their share is the whole free tier. Later sub-projects split shares."""
    return {"tavily": Limit("month", cfg.tavily_monthly_limit, cfg.tavily_monthly_limit),
            "apify": Limit("month", cfg.apify_monthly_usd_limit, cfg.apify_monthly_usd_limit),
            "hunter": Limit("month", cfg.hunter_monthly_limit, cfg.hunter_monthly_limit),
            "smtp": Limit("day", cfg.smtp_daily_limit, cfg.smtp_daily_limit)}


class Budget:
    """Free-tier guard: every outside call checks can() and records spend(). A user stops at their share and
    everyone stops at the global cap, so nothing is ever paid for."""

    def __init__(self, conn: sqlite3.Connection, user_id: int, limits: dict[str, Limit], now: datetime):
        self.conn, self.user_id, self.limits = conn, user_id, limits
        self.month, self.day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")

    def _period(self, service: str) -> str:
        return self.month if self.limits[service].period == "month" else self.day

    def used(self, service: str) -> float:
        row = self.conn.execute("SELECT amount FROM usage WHERE user_id = ? AND period = ? AND service = ?",
                                (self.user_id, self._period(service), service)).fetchone()
        return row["amount"] if row else 0.0

    def used_all(self, service: str) -> float:
        row = self.conn.execute("SELECT COALESCE(SUM(amount), 0) AS a FROM usage WHERE period = ? AND service = ?",
                                (self._period(service), service)).fetchone()
        return row["a"]

    def can(self, service: str, amount: float = 1) -> bool:
        lim = self.limits[service]
        return (self.used(service) + amount <= lim.share_cap + 1e-9
                and self.used_all(service) + amount <= lim.global_cap + 1e-9)

    def spend(self, service: str, amount: float = 1) -> None:
        self.conn.execute(
            """INSERT INTO usage (user_id, period, service, amount) VALUES (?, ?, ?, ?)
               ON CONFLICT (user_id, period, service) DO UPDATE SET amount = amount + excluded.amount""",
            (self.user_id, self._period(service), service, amount))
        self.conn.commit()

    def summary(self) -> str:
        lim = self.limits
        return (f"Tavily {self.used('tavily'):.0f}/{lim['tavily'].share_cap:.0f} · "
                f"Apify ${self.used('apify'):.2f}/${lim['apify'].share_cap:.2f} · "
                f"Hunter {self.used('hunter'):.0f}/{lim['hunter'].share_cap:.0f} · "
                f"SMTP today {self.used('smtp'):.0f}/{lim['smtp'].share_cap:.0f}")
