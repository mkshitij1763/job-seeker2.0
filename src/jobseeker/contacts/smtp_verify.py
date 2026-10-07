from __future__ import annotations

import re
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


class VerifyUnavailable(Exception):
    """The server refuses address checks (policy) or dropped the connection; nothing more can be verified."""


# 5.1.x means "no such mailbox"; 5.4.x / 5.7.x (and these words) mean the server is refusing us, not the address.
_REFUSAL = re.compile(rb"\b5\.[47]\.\d+\b|access denied|blocked|spamhaus|policy|not permitted|relay", re.I)


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
        try:
            code, message = self.server.rcpt(address)
        except (smtplib.SMTPException, OSError) as e:
            raise VerifyUnavailable(f"mail server dropped the connection ({e})") from e
        self.spend()
        bad_mailbox = re.search(rb"\b5\.1\.\d+\b", message or b"")  # e.g. Postfix "User unknown in relay ..."
        if code >= 500 and not bad_mailbox and _REFUSAL.search(message or b""):
            raise VerifyUnavailable(f"mail server refused verification ({message[:80].decode(errors='replace')})")
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
