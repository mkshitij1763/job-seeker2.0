"""Which job-site searches to run: the union of every user's roles × places, capped, fair, rotating."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from jobseeker.config import Preferences


@dataclass(frozen=True)
class PlanUser:
    user_id: int
    queries: list[str]
    locations: list[str]
    custom: str
    prefs_updated_at: str


@dataclass(frozen=True)
class Plan:
    linkedin: list[str]
    pairs: list[tuple[str, str]]
    planned: int
    trimmed: int

    def for_site(self, site: str) -> list[tuple[str, str]]:
        return [(q, "India") for q in self.linkedin] if site == "linkedin" else list(self.pairs)


def plan_users(rows: list[tuple[int, Preferences, str, str]]) -> list[PlanUser]:
    out = []
    for user_id, prefs, custom, updated_at in rows:
        locations = list(prefs.cities) + (["India"] if prefs.remote_india_ok else [])
        out.append(PlanUser(user_id, list(dict.fromkeys(prefs.search.queries)), locations, custom, updated_at))
    return out


def build_plan(users: list[PlanUser], sites: list[str], catalog: set[str], run_no: int, cap: int,
               max_custom: int) -> Plan:
    customs = [c for _, c in sorted({(u.prefs_updated_at, u.custom) for u in users if u.custom})]
    allowed = catalog | set(list(dict.fromkeys(customs))[:max_custom])
    wants = {u.user_id: [q for q in u.queries if q in allowed] for u in users}
    query_demand = Counter(q for qs in wants.values() for q in set(qs))

    def query_key(q: str):
        return (q not in catalog, -query_demand[q], q)

    linkedin: list[str] = []
    budget = cap
    if "linkedin" in sites:
        for q in sorted(query_demand, key=query_key):
            if budget < 1:
                break
            linkedin.append(q)
            budget -= 1

    pair_cost = sum(1 for s in sites if s != "linkedin")
    if pair_cost == 0 or not users:
        return Plan(linkedin, [], len(linkedin), 0)
    user_pairs = {u.user_id: [(q, loc) for q in wants[u.user_id] for loc in u.locations] for u in users}
    pair_demand = Counter(p for ps in user_pairs.values() for p in set(ps))
    for uid, ps in user_pairs.items():
        ps.sort(key=lambda p: (-pair_demand[p], p[0] not in catalog, p))

    order = sorted(user_pairs)
    shift = run_no % len(order)
    order = order[shift:] + order[:shift]
    fair: list[tuple[str, str]] = []  # round-robin over users, skipping pairs already taken
    taken: set = set()
    idx = dict.fromkeys(order, 0)
    while any(idx[u] < len(user_pairs[u]) for u in order):
        for u in order:
            ps = user_pairs[u]
            while idx[u] < len(ps) and ps[idx[u]] in taken:
                idx[u] += 1
            if idx[u] < len(ps):
                taken.add(ps[idx[u]])
                fair.append(ps[idx[u]])
                idx[u] += 1

    slots = budget // pair_cost
    first_round = [user_pairs[u][0] for u in order if user_pairs[u]]
    first_round = list(dict.fromkeys(first_round))[:slots]
    rest = [p for p in fair if p not in set(first_round)]
    left = slots - len(first_round)
    if len(rest) <= left:
        chosen, trimmed = rest, 0
    else:
        start = (run_no * left) % len(rest) if left else 0
        chosen = [rest[(start + i) % len(rest)] for i in range(left)]
        trimmed = len(rest) - left
    pairs = first_round + chosen
    return Plan(linkedin, pairs, len(linkedin) + pair_cost * len(pairs), trimmed)
