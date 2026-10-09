from jobseeker.db.core import connect

COPY = ["Your daily shortlist of product and analytics roles in India.",
        "Every morning it searches LinkedIn, Naukri, Indeed and company career pages for your roles and cities.",
        "Each job is scored against your resume, with the reasons, so you read 10 jobs, not 600.",
        "Built for your phone: add it to your Home Screen.",
        "Your resume and drafts are visible only to you. The admin (the person who invited you) can see your job preferences and application statuses. Download or delete your data any time in Settings.",
        "A personal project, not affiliated with LinkedIn, Naukri, Indeed or Google."]


def test_anonymous_root_is_landing_without_data(anon_client, seeded_two, settings):
    conn = connect(settings.db_path)
    conn.execute("UPDATE users SET name = 'Kshitij Meshram' WHERE id = 1")
    conn.commit()
    r = anon_client().get("/")
    assert r.status_code == 200
    for line in COPY:
        assert line in r.text
    assert 'href="/login"' in r.text and "Continue with Google" in r.text
    assert '<meta name="robots" content="noindex">' in r.text
    assert "Invite-only. If you haven't been invited, ask Kshitij." in r.text
    for row in conn.execute("SELECT title, company FROM jobs"):
        assert row["title"] not in r.text and row["company"] not in r.text


def test_owner_without_name_falls_back(anon_client, seeded_two, settings):
    conn = connect(settings.db_path)
    conn.execute("UPDATE users SET name = '' WHERE id = 1")
    conn.commit()
    assert "ask the person who shared this link." in anon_client().get("/").text


def test_signed_in_root_is_inbox(client_as, seeded_two):
    r = client_as(1).get("/")
    assert r.status_code == 200 and "Continue with Google" not in r.text
