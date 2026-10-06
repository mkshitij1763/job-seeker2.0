from jobseeker.models import Job


def make_job(**overrides) -> Job:
    data = dict(
        source="lever",
        source_job_id="abc-1",
        company="CRED",
        title="Senior Product Analyst",
        location="Bengaluru",
        remote=False,
        posted_at=None,
        salary_text=None,
        jd_text="We need a product analyst with SQL and A/B testing. 2-4 years of experience.",
        apply_url="https://jobs.lever.co/cred/abc-1",
        location_city="bengaluru",
        is_remote=False,
        fingerprint="fp-senior-pa-cred-blr",
    )
    data.update(overrides)
    return Job(**data)
