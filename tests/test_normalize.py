from jobseeker.models import RawJob
from jobseeker.pipeline.normalize import (
    canonical_city, fingerprint, html_to_text, normalize, normalize_company, normalize_title,
)


def test_html_to_text_double_escaped():
    s = "&lt;div&gt;&lt;strong&gt;About Groww:&lt;/strong&gt;&lt;/div&gt;&lt;p&gt;Fees &amp;amp; more&lt;/p&gt;"
    assert html_to_text(s) == "About Groww:\nFees & more"


def test_html_to_text_plain_passthrough():
    assert html_to_text("Just text") == "Just text"


def test_canonical_city_aliases_and_priority():
    assert canonical_city("Bengaluru-VTP, India") == "bengaluru"
    assert canonical_city("Bangalore") == "bengaluru"
    assert canonical_city("Gurugram, Haryana") == "gurgaon"
    assert canonical_city("Hyderabad, Pune") == "pune"
    assert canonical_city("hyderabad") == "hyderabad"
    assert canonical_city("Remote") is None


def test_title_and_company_normalisation():
    assert normalize_title("Sr. Product Analyst") == "senior product analyst"
    assert normalize_title("APM - Growth") == "associate product manager growth"
    assert normalize_company("Meesho Technologies Pvt. Ltd.") == "meesho"


def test_fingerprint_equal_across_spellings():
    a = fingerprint("CRED", "Sr. Product Analyst", canonical_city("Bangalore"))
    b = fingerprint("Cred", "Senior Product Analyst", canonical_city("Bengaluru, Karnataka"))
    assert a == b


def test_normalize_detects_remote():
    raw = RawJob(source="ashby", source_job_id="1", company="Sarvam AI", title="PM",
                 location="Remote - India", jd_text="x", apply_url="https://a/1")
    job = normalize(raw)
    assert job.is_remote is True and job.location_city is None
    assert job.fingerprint == fingerprint("Sarvam AI", "PM", None)
