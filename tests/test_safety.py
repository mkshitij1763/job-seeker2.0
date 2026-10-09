from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "jobseeker"


def test_no_send_calls_anywhere():
    code = "\n".join(p.read_text() for p in SRC.rglob("*.py"))
    assert "messages().send" not in code and "drafts().send" not in code
    assert "gmail.send" not in code and "mail.google.com/mail/feed" not in code


def test_server_binds_localhost_only():
    assert 'host="127.0.0.1"' in (SRC / "cli.py").read_text()


def test_no_runtime_reads_of_profile_files():
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "jobseeker"
    offenders = [str(p) for p in src.rglob("*.py") if p.name != "importer.py"
                 for line in p.read_text().splitlines()
                 if any(s in line for s in ('"preferences.yaml"', '"facts.json"', "profile_dir /", "app.state.prefs"))]
    assert offenders == []
