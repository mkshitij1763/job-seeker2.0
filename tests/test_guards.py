from jobseeker.outreach.drafter import DraftBundle
from jobseeker.outreach.guards import check_bundle, style_violations, ungrounded_numbers

FACTS = "cut errors by 67% across 480K+ tests; churn model 84% ROC-AUC on 30,000+ users"


def test_grounded_numbers_pass():
    assert ungrounded_numbers("I cut errors 67% over 480K+ tests and hit 84%.", FACTS) == []
    assert ungrounded_numbers("Modelled 30000+ users", FACTS) == []


def test_invented_number_flagged():
    assert ungrounded_numbers("I improved retention 40%", FACTS) == ["40%"]


def test_jd_numbers_allowed_as_source():
    assert ungrounded_numbers("Your 10M users", FACTS, "serving 10M users") == []


def test_style():
    assert style_violations("I hope this finds you well. I'm passionate.") == [
        "banned phrase: i hope this finds you well", "banned phrase: passionate"]
    assert style_violations("one — two — three") == ["more than one em-dash"]


def _bundle(**kw):
    base = dict(contact_role="Hiring PM", contact_reason="r", email_subject="s",
                email_body="Short email citing 67%.", li_note="note", li_dm="dm")
    base.update(kw)
    return DraftBundle(**base)


def test_check_bundle_limits():
    assert check_bundle(_bundle(), [FACTS]) == []
    probs = check_bundle(_bundle(email_body="word " * 151, li_note="x" * 301, li_dm="y" * 601), [FACTS])
    assert "email body is 151 words (max 150)" in probs
    assert "LinkedIn note is 301 characters (max 300)" in probs
    assert "LinkedIn DM is 601 characters (max 600)" in probs
