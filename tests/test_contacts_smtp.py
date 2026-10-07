import pytest

from jobseeker.contacts.smtp_verify import BudgetExceeded, PortBlocked, SmtpVerifier


class FakeSMTP:
    """Scripted mail server: replies maps address -> code (default 550). Records every command."""

    def __init__(self, replies=None, default=550):
        self.replies, self.default, self.log = replies or {}, default, []

    def ehlo(self, name=None):
        self.log.append(("ehlo", name))
        return 250, b"ok"

    def mail(self, sender):
        self.log.append(("mail", sender))
        return 250, b"ok"

    def rcpt(self, addr):
        self.log.append(("rcpt", addr))
        return self.replies.get(addr, self.default), b""

    def quit(self):
        self.log.append(("quit",))


def verifier(server, **kw):
    return SmtpVerifier("mx.zepto.com", "me@gmail.com", "mac.local", smtp_factory=lambda host: server,
                        sleep=lambda s: None, **kw)


def test_finds_first_accepted_candidate_and_never_sends_data():
    server = FakeSMTP({"asha@zepto.com": 250})
    with verifier(server) as v:
        assert v.is_catch_all("zepto.com") is False
        assert v.check(["asha.rao@zepto.com", "asha@zepto.com", "arao@zepto.com"]) == "asha@zepto.com"
    commands = [c[0] for c in server.log]
    assert commands[:2] == ["ehlo", "mail"] and commands[-1] == "quit"
    assert "data" not in commands and ("rcpt", "arao@zepto.com") not in server.log  # stops at first hit


def test_catch_all_detected():
    with verifier(FakeSMTP(default=250)) as v:
        assert v.is_catch_all("zepto.com") is True


def test_greylisting_returns_none():
    with verifier(FakeSMTP(default=451)) as v:
        assert v.check(["a@zepto.com"]) is None


def test_connection_refused_is_port_blocked():
    def refuse(host):
        raise OSError("timed out")
    with pytest.raises(PortBlocked):
        with SmtpVerifier("mx", "me@gmail.com", "h", smtp_factory=refuse, sleep=lambda s: None):
            pass


def test_budget_stops_checks():
    spent = []
    with verifier(FakeSMTP(), allow=lambda: len(spent) < 1, spend=lambda: spent.append(1)) as v:
        with pytest.raises(BudgetExceeded):
            v.check(["a@zepto.com", "b@zepto.com"])
    assert len(spent) == 1
