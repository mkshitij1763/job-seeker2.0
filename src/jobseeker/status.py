STATUSES = (
    "new", "shortlisted", "drafted", "approved", "sent", "replied", "interview",
    "offer", "rejected", "skipped", "snoozed", "applied_via_portal", "not_interested",
)
ACTIVE = {"new", "shortlisted", "drafted", "approved", "sent", "replied", "interview"}
SIDE_EXITS = {"skipped", "snoozed", "applied_via_portal", "not_interested"}
ALLOWED: dict[str, set[str]] = {
    "new": {"shortlisted", "drafted"},
    "shortlisted": {"drafted"},
    "drafted": {"approved"},
    "approved": {"sent", "drafted"},
    "sent": {"replied", "interview", "rejected"},
    "replied": {"interview", "rejected"},
    "interview": {"offer", "rejected"},
    "applied_via_portal": {"replied", "interview", "rejected"},
}


class InvalidTransition(ValueError):
    pass


def can_transition(cur: str, new: str) -> bool:
    if new in SIDE_EXITS and cur in ACTIVE:
        return True
    return new in ALLOWED.get(cur, set())


def allowed_next(cur: str) -> list[str]:
    return [s for s in STATUSES if s != "snoozed" and can_transition(cur, s)]
