from jobseeker.outreach.drafter import DraftBundle, draft_outreach, greeting, linkedin_search_url, signature
from tests.factories import make_job
from tests.fakes import FakeLLM

GOOD = dict(contact_role="Product Analytics Lead", contact_reason="Owns the analyst hire",
            email_subject="Product analyst who cut errors 67%",
            email_body="Hi, your role mentions experimentation. At Inito I cut errors by 67% across 480K+ tests. Open to a 15-minute call?",
            li_note="Hi! I'm a product analyst at Inito (67% fewer test errors via A/B tests). Would love to connect.",
            li_dm="Thanks for connecting. I applied for the Senior PA role and would value 15 minutes.")


def test_first_draft_accepted(prefs, facts):
    llm = FakeLLM([GOOD])
    r = draft_outreach(llm, make_job(jd_text="15-minute chats welcome"), facts, prefs, "openai/gpt-oss-120b")
    assert r.warnings == [] and r.bundle == DraftBundle(**GOOD)
    assert r.linkedin_search_url == "https://www.linkedin.com/search/results/people/?keywords=CRED+Product+Analytics+Lead"
    assert llm.calls[0]["model"] == "openai/gpt-oss-120b" and llm.calls[0]["effort"] == "medium"


def test_regenerates_with_feedback_then_accepts(prefs, facts):
    bad = {**GOOD, "email_body": "I'm passionate and improved retention 40%."}
    llm = FakeLLM([bad, GOOD])
    r = draft_outreach(llm, make_job(jd_text="15-minute chats welcome"), facts, prefs, "m")
    assert r.warnings == []
    assert "40%" in llm.calls[1]["prompt"] and "passionate" in llm.calls[1]["prompt"]


def test_gives_up_with_warnings(prefs, facts):
    bad = {**GOOD, "email_body": "Improved retention 40%."}
    llm = FakeLLM([bad, bad, bad])
    r = draft_outreach(llm, make_job(), facts, prefs, "m", max_retries=2)
    assert len(llm.calls) == 3 and any("40%" in w for w in r.warnings)


def test_signature_and_search_url(prefs):
    assert signature(prefs).endswith("https://www.linkedin.com/in/asha-owner/")
    assert "keywords=Groww+Founder%27s+Office" in linkedin_search_url("Groww", "Founder's Office")


def test_greeting_uses_first_name():
    assert greeting("Asha Rao", "Body") == "Hi Asha,\n\nBody"
    assert greeting("", "Body") == "Hi,\n\nBody"


def test_greeting_skipped_when_body_already_greets():
    assert greeting("Asha", "Hello Asha, quick note") == "Hello Asha, quick note"
    assert greeting("Asha", "  hi there") == "  hi there"
