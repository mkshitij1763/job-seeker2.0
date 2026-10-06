from __future__ import annotations

import re

EMAIL_MAX_WORDS = 150
LI_NOTE_MAX_CHARS = 300
LI_DM_MAX_CHARS = 600

BANNED = [
    "i hope this finds you well", "i hope this email finds you", "passionate", "leverage", "synergy",
    "i am writing to express", "i'm writing to express", "delve", "thrilled", "excited to apply",
    "dynamic team", "fast-paced", "to whom it may concern", "game-changer", "cutting-edge",
]
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|[kKmM]\+?|\+|x\b)?")


def _core(token: str) -> str:
    return re.sub(r"[^\d.]", "", token).rstrip(".")


def _numbers(text: str) -> dict[str, str]:
    return {_core(m.group()): m.group().strip() for m in _NUM.finditer(text) if _core(m.group())}


def ungrounded_numbers(text: str, *sources: str) -> list[str]:
    allowed: set[str] = set()
    for s in sources:
        allowed |= set(_numbers(s))
    return sorted(raw for core, raw in _numbers(text).items() if core not in allowed)


def style_violations(text: str) -> list[str]:
    low = text.lower()
    problems = [f"banned phrase: {p}" for p in BANNED if p in low]
    if text.count("—") > 1:
        problems.append("more than one em-dash")
    return problems


def check_bundle(bundle, sources: list[str]) -> list[str]:
    problems: list[str] = []
    words = len(bundle.email_body.split())
    if words > EMAIL_MAX_WORDS:
        problems.append(f"email body is {words} words (max {EMAIL_MAX_WORDS})")
    if len(bundle.li_note) > LI_NOTE_MAX_CHARS:
        problems.append(f"LinkedIn note is {len(bundle.li_note)} characters (max {LI_NOTE_MAX_CHARS})")
    if len(bundle.li_dm) > LI_DM_MAX_CHARS:
        problems.append(f"LinkedIn DM is {len(bundle.li_dm)} characters (max {LI_DM_MAX_CHARS})")
    for field in ("email_subject", "email_body", "li_note", "li_dm"):
        text = getattr(bundle, field)
        for n in ungrounded_numbers(text, *sources):
            problems.append(f"{field}: number {n} is not in the resume facts or the job posting")
        problems += [f"{field}: {p}" for p in style_violations(text)]
    return problems
