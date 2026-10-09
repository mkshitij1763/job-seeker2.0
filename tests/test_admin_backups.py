from jobseeker.db.core import connect


def test_admin_shows_last_seven_backups(client_as, settings):
    conn = connect(settings.db_path)
    for d in range(1, 10):
        conn.execute("INSERT INTO backups (day, local_path, size_bytes, uploaded_at, upload_error, created_at) "
                     "VALUES (?, '/x', 10485760, ?, ?, 'now')",
                     (f"2026-10-0{d}" if d < 10 else "2026-10-10", None if d == 9 else "now",
                      "Upload of daily/x failed: HTTP 500" if d == 9 else None))
    conn.commit()
    html = client_as(1).get("/admin").text
    assert "Backups" in html and html.count('class="backup-row"') == 7
    assert "2026-10-09" in html and "Upload of daily/x failed: HTTP 500" in html and "2026-10-02" not in html
    assert "10.0 MB" in html and "Uploaded" in html


def test_delete_removes_push_subscriptions(client_as, settings, seeded_two):
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at) "
                 "VALUES (2, 'https://p/r', 'k', 'a', 'now'), (1, 'https://p/o', 'k', 'a', 'now')")
    conn.commit()
    c = client_as(2)
    c.post("/settings/delete", data={"email": "roomie@example.com"})
    rows = connect(settings.db_path).execute("SELECT user_id FROM push_subscriptions").fetchall()
    assert [r[0] for r in rows] == [1]


def test_export_has_no_push_endpoint(client_as, settings):
    import io
    import zipfile

    conn = connect(settings.db_path)
    conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at) "
                 "VALUES (1, 'https://p/secret-endpoint', 'k', 'a', 'now')")
    conn.commit()
    z = zipfile.ZipFile(io.BytesIO(client_as(1).get("/settings/export").content))
    assert all(b"secret-endpoint" not in z.read(n) for n in z.namelist())
