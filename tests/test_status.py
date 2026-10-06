from jobseeker.status import allowed_next, can_transition


def test_happy_path():
    path = ["new", "shortlisted", "drafted", "approved", "sent", "replied", "interview", "offer"]
    for cur, new in zip(path, path[1:]):
        assert can_transition(cur, new), (cur, new)


def test_side_exits_only_from_active():
    assert can_transition("drafted", "skipped")
    assert can_transition("sent", "not_interested")
    assert not can_transition("offer", "skipped")
    assert not can_transition("rejected", "snoozed")


def test_disallowed():
    assert not can_transition("new", "sent")
    assert not can_transition("approved", "interview")


def test_allowed_next_excludes_snoozed():
    assert "snoozed" not in allowed_next("drafted")
    assert "approved" in allowed_next("drafted")
