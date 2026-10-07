from __future__ import annotations

import secrets
import smtplib
import socket
import string
import time
from collections.abc import Callable


class PortBlocked(Exception):
    """Port 25 is unreachable from this network."""


class BudgetExceeded(Exception):
    """The daily SMTP check limit is reached."""


class SmtpVerifier:
    """Asks a mail server whether addresses exist with RCPT TO only. DATA is never sent, so no email goes out."""

    def __init__(self, mx_host: str, sender: str, helo: str, smtp_factory: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep, pause: float = 2.0,
                 allow: Callable[[], bool] = lambda: True, spend: Callable[[], None] = lambda: None):
        self.mx_host, self.sender, self.helo = mx_host, sender, helo
        self.factory = smtp_factory or (lambda host: smtplib.SMTP(host, 25, local_hostname=helo, timeout=15))
        self.sleep, self.pause, self.allow, self.spend = sleep, pause, allow, spend
        self.server = None

    def __enter__(self) -> SmtpVerifier:
        try:
            self.server = self.factory(self.mx_host)
            self.server.ehlo(self.helo)
            self.server.mail(self.sender)
        except (OSError, socket.timeout, smtplib.SMTPException) as e:
            raise PortBlocked(str(e)) from e
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.server.quit()
        except Exception:
            pass

    def _rcpt(self, address: str) -> int:
        if not self.allow():
            raise BudgetExceeded("SMTP daily limit reached")
        code, _ = self.server.rcpt(address)
        self.spend()
        self.sleep(self.pause)
        return code

    def is_catch_all(self, domain: str) -> bool:
        probe = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(12))
        return self._rcpt(f"{probe}@{domain}") in (250, 251)

    def check(self, candidates: list[str]) -> str | None:
        for address in candidates:
            if self._rcpt(address) in (250, 251):
                return address
        return None
