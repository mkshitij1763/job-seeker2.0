from jobseeker.db.applications import ensure_application
from jobseeker.db.core import connect
from jobseeker.db.jobs import upsert_job
from jobseeker.db.users import OWNER_ID, ensure_owner
from tests.factories import make_job


def test_ensure_owner_sets_email_once(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    ensure_owner(conn, "Owner@Example.com")
    assert conn.execute("SELECT email FROM users WHERE id = 1").fetchone()[0] == "owner@example.com"
    conn.execute("UPDATE users SET google_sub = 'g1' WHERE id = 1")
    ensure_owner(conn, "other@example.com")  # an owner who has signed in keeps their identity
    assert conn.execute("SELECT email FROM users WHERE id = 1").fetchone()[0] == "owner@example.com"


def test_same_job_two_users_two_applications(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    job_id, _ = upsert_job(conn, make_job())
    a = ensure_application(conn, OWNER_ID, job_id)
    b = ensure_application(conn, 2, job_id)
    assert a != b
    assert ensure_application(conn, 2, job_id) == b
