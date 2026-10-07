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


class ScriptedSMTP(FakeSMTP):
    """Like FakeSMTP but replies carry server text, and can disconnect after N RCPTs."""

    def __init__(self, replies=None, default=(550, b"5.1.1 User unknown"), drop_after=None):
        super().__init__()
        self.replies, self.default, self.drop_after, self.count = replies or {}, default, drop_after, 0

    def rcpt(self, addr):
        import smtplib
        self.count += 1
        if self.drop_after is not None and self.count > self.drop_after:
            raise smtplib.SMTPServerDisconnected("Server not connected")
        self.log.append(("rcpt", addr))
        return self.replies.get(addr, self.default)


def test_policy_refusal_on_probe_means_unverifiable():
    from jobseeker.contacts.smtp_verify import VerifyUnavailable

    server = ScriptedSMTP(default=(550, b"5.4.1 Recipient address rejected: Access denied. AS(201806281)"))
    with pytest.raises(VerifyUnavailable):
        with verifier(server) as v:
            v.is_catch_all("sliceit.com")


def test_disconnect_mid_check_means_unverifiable():
    from jobseeker.contacts.smtp_verify import VerifyUnavailable

    with pytest.raises(VerifyUnavailable):
        with verifier(ScriptedSMTP(drop_after=2)) as v:
            v.is_catch_all("x.com")
            v.check(["a@x.com", "b@x.com", "c@x.com"])


def test_bad_mailbox_reply_is_just_not_found():
    server = ScriptedSMTP(replies={"asha@x.com": (250, b"2.1.5 OK")},
                          default=(550, b"5.1.1 The email account that you tried to reach does not exist"))
    with verifier(server) as v:
        assert v.is_catch_all("x.com") is False
        assert v.check(["asha.rao@x.com", "asha@x.com"]) == "asha@x.com"
