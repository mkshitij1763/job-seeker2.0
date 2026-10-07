from __future__ import annotations

import sqlite3
from datetime import datetime

from jobseeker.config import ContactsConfig

MONTHLY = ("tavily", "apify", "hunter")


class Budget:
    """Free-tier guard: every outside call checks can() and records spend() so nothing is ever paid for."""

    def __init__(self, conn: sqlite3.Connection, cfg: ContactsConfig, now: datetime):
        self.conn, self.cfg = conn, cfg
        self.month, self.day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
        self.limits = {"tavily": cfg.tavily_monthly_limit, "apify": cfg.apify_monthly_usd_limit,
                       "hunter": cfg.hunter_monthly_limit, "smtp": cfg.smtp_daily_limit}

    def _period(self, service: str) -> str:
        return self.month if service in MONTHLY else self.day

    def used(self, service: str) -> float:
        row = self.conn.execute("SELECT amount FROM usage WHERE period = ? AND service = ?",
                                (self._period(service), service)).fetchone()
        return row["amount"] if row else 0.0

    def can(self, service: str, amount: float = 1) -> bool:
        return self.used(service) + amount <= self.limits[service] + 1e-9

    def spend(self, service: str, amount: float = 1) -> None:
        self.conn.execute(
            """INSERT INTO usage (period, service, amount) VALUES (?, ?, ?)
               ON CONFLICT (period, service) DO UPDATE SET amount = amount + excluded.amount""",
            (self._period(service), service, amount))
        self.conn.commit()

    def summary(self) -> str:
        return (f"Tavily {self.used('tavily'):.0f}/{self.limits['tavily']} · "
                f"Apify ${self.used('apify'):.2f}/${self.limits['apify']:.2f} · "
                f"Hunter {self.used('hunter'):.0f}/{self.limits['hunter']} · "
                f"SMTP today {self.used('smtp'):.0f}/{self.limits['smtp']}")
