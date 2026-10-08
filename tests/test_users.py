from datetime import UTC, datetime

import pytest

from jobseeker.db.applications import ensure_application
from jobseeker.db.core import connect
from jobseeker.db.jobs import upsert_job
from jobseeker.db.users import (
    OWNER_ID, LastAdmin, add_invite, ensure_owner, owner_first_name, resolve_sign_in, set_disabled, user_by_id,
)
from tests.factories import make_job

T = datetime(2026, 10, 8, tzinfo=UTC)


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


def _db(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    ensure_owner(conn, "owner@example.com")
    return conn


def test_owner_first_login_claims_sub_then_sub_wins(tmp_path):
    conn = _db(tmp_path)
    u = resolve_sign_in(conn, "g-1", "Owner@Example.com", "Kay Em", T)
    assert u.id == 1 and u.is_admin
    assert resolve_sign_in(conn, "g-1", "renamed@example.com", "Kay Em", T).id == 1


def test_uninvited_gets_none_and_no_row(tmp_path):
    conn = _db(tmp_path)
    assert resolve_sign_in(conn, "g-2", "stranger@example.com", "S", T) is None
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_invited_creates_user_and_accepts(tmp_path):
    conn = _db(tmp_path)
    add_invite(conn, "Roomie@Example.com", 1, T)
    u = resolve_sign_in(conn, "g-3", "roomie@example.com", "Roo Mie", T)
    assert u.id == 2 and not u.is_admin
    assert conn.execute("SELECT accepted_at FROM invites").fetchone()[0] is not None


def test_another_account_cannot_claim_owner_by_email_after_sub_is_set(tmp_path):
    conn = _db(tmp_path)
    resolve_sign_in(conn, "g-1", "owner@example.com", "Kay", T)
    assert resolve_sign_in(conn, "g-other", "owner@example.com", "X", T) is None


def test_disabled_is_refused_and_last_admin_kept(tmp_path):
    conn = _db(tmp_path)
    add_invite(conn, "r@example.com", 1, T)
    resolve_sign_in(conn, "g-3", "r@example.com", "R", T)
    set_disabled(conn, 2, True, T)
    assert resolve_sign_in(conn, "g-3", "r@example.com", "R", T) is None
    with pytest.raises(LastAdmin):
        set_disabled(conn, 1, True, T)


def test_owner_first_name_fallback(tmp_path):
    conn = _db(tmp_path)
    assert owner_first_name(conn) == "the person who shared this link"
    resolve_sign_in(conn, "g-1", "owner@example.com", "Kay Em", T)
    assert owner_first_name(conn) == "Kay"
    assert user_by_id(conn, 1).name == "Kay Em"
