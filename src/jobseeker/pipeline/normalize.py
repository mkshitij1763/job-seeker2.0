import re

_COMPANY_STOP = {"pvt", "private", "ltd", "limited", "inc", "llp", "technologies", "technology", "india", "labs"}


def normalize_company(name: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return " ".join(t for t in tokens if t not in _COMPANY_STOP)
