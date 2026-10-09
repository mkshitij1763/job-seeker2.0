from datetime import UTC, datetime, timedelta

from jobseeker.contacts.smtp_probe import port25_open
from jobseeker.db.core import connect

T = datetime(2026, 10, 9, tzinfo=UTC)


def test_probe_result_is_remembered_for_24h(settings):
    conn, calls = connect(settings.db_path), []
    probe = lambda: calls.append(1) or False  # noqa: E731
    assert port25_open(conn, T, probe) is False
    assert port25_open(conn, T + timedelta(hours=23), probe) is False and calls == [1]
    assert port25_open(conn, T + timedelta(hours=25), lambda: True) is True


def _mode(prefs, mode):
    return prefs.model_copy(update={"contacts": prefs.contacts.model_copy(update={"smtp_verify": mode})})


def _no_smtp(host):
    raise AssertionError("SMTP must not be used when verification is off")


SERVER_NOTE = "Email checks aren't available on this server; emails are best guesses unless Apify or Hunter found them."


def test_off_never_builds_a_verifier(prefs):
    from jobseeker.contacts.finder import find_contacts
    from jobseeker.db.contacts_repo import people
    from tests.test_contacts_finder import deps, setup_app
    conn, app = setup_app()
    d, _ = deps(smtp_factory=_no_smtp)
    summary = find_contacts(conn, app, _mode(prefs, "off"), d)
    ps = people(conn, app)
    assert SERVER_NOTE in summary["notes"]
    assert ps[0]["email"] == "asha.rao@zeptonow.com" and {p["email_status"] for p in ps} == {"unverified"}


def test_auto_with_port_25_blocked_behaves_as_off(prefs):
    from jobseeker.contacts.finder import find_contacts
    from tests.test_contacts_finder import deps, setup_app
    conn, app = setup_app()
    d, _ = deps(smtp_factory=_no_smtp, port25=lambda c, n: False)
    assert SERVER_NOTE in find_contacts(conn, app, _mode(prefs, "auto"), d)["notes"]


def test_on_is_unchanged(prefs):
    from jobseeker.contacts.finder import find_contacts
    from tests.test_contacts_finder import FakeSMTP, deps, setup_app
    conn, app = setup_app()
    d, _ = deps(FakeSMTP({"asha.rao@zeptonow.com": 250, "vikram.singh@zeptonow.com": 250,
                          "rahul.sharma@zeptonow.com": 250, "priya.nair@zeptonow.com": 250}))
    assert find_contacts(conn, app, _mode(prefs, "on"), d)["verified"] == 3
