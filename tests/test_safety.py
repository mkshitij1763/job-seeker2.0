from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "jobseeker"


def test_no_send_calls_anywhere():
    code = "\n".join(p.read_text() for p in SRC.rglob("*.py"))
    assert "messages().send" not in code and "drafts().send" not in code
    assert "gmail.send" not in code and "mail.google.com/mail/feed" not in code


def test_server_binds_localhost_only():
    assert 'host="127.0.0.1"' in (SRC / "cli.py").read_text()
