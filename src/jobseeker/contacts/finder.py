from __future__ import annotations

import socket
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from jobseeker.config import Preferences
from jobseeker.contacts import names
from jobseeker.contacts.domains import FREE_MAIL, domain_from_text, mx_host, pick_domain
from jobseeker.contacts.people import from_results, rank, role_words, search_queries
from jobseeker.contacts.smtp_verify import BudgetExceeded, PortBlocked, SmtpVerifier, VerifyUnavailable
from jobseeker.db.contacts_repo import (
    blocked_names, blocked_profile_urls, bounced_emails, emailed_count, get_domain, known_catch_all, link_contact,
    save_candidates, save_domain, set_find_status, upsert_contact,
)
from jobseeker.db.core import connect, iso
from jobseeker.db.jobs import get_job
from jobseeker.db.applications import get_application
from jobseeker.db.usage import Budget, contacts_limits
from jobseeker.llm import LLM
from jobseeker.pipeline.normalize import normalize_company


class FinderError(Exception):
    pass


@dataclass
class Deps:
    tavily: object | None
    llm: LLM
    apify: object | None = None
    hunter: object | None = None
    resolver: Callable[[str], str | None] = mx_host
    smtp_factory: Callable | None = None
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


def _search(deps: Deps, budget: Budget, notes: list[str], query: str, **kw) -> list[dict]:
    if not budget.can("tavily"):
        notes.append(f"Tavily budget used for {budget.month}")
        return []
    budget.spend("tavily")
    return deps.tavily.search(query, **kw)


def find_contacts(conn: sqlite3.Connection, app_id: int, prefs: Preferences, deps: Deps) -> dict:
    if deps.tavily is None:
        raise FinderError("Add TAVILY_API_KEY to .env to find contacts")
    if emailed_count(conn, app_id):
        raise FinderError("People were already emailed for this job; edit or remove them individually instead")
    app = get_application(conn, app_id)
    user_id = app["user_id"]
    job = get_job(conn, app["job_id"])
    company, norm = job["company"], normalize_company(job["company"])
    budget = Budget(conn, user_id, contacts_limits(prefs.contacts), deps.now())
    notes: list[str] = []
    family = (conn.execute("SELECT role_family FROM scores WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                           (job["id"],)).fetchone() or {"role_family": ""})["role_family"]

    # 1. people
    seen = set(blocked_profile_urls(conn, company))
    cands = []
    for q in search_queries(company, job["title"], family, job["location_city"]):
        cands += from_results(_search(deps, budget, notes, q, include_domains=["linkedin.com"], max_results=10),
                              company, seen)
    if len(cands) < 3 and deps.apify is not None:
        if budget.can("apify", deps.apify.SEARCH_PAGE_USD):
            budget.spend("apify", deps.apify.SEARCH_PAGE_USD)
            try:
                found_people = deps.apify.search_people(company, role_words(job["title"], family), job["location_city"])
            except Exception as e:  # a fallback failing must not lose the run
                notes.append(f"Apify people search failed ({type(e).__name__})")
                found_people = []
            for c in found_people:
                if c.linkedin_url not in seen:
                    seen.add(c.linkedin_url)
                    cands.append(c)
        else:
            notes.append(f"Apify budget used for {budget.month}")
    blocked = blocked_names(conn, company)
    if blocked:
        cands = [c for c in cands if (nm := names.clean_name(c.name)) is None or (nm.first, nm.last) not in blocked]
    if not cands:
        raise FinderError(" ".join(notes) or f"No people found at {company} for this role")
    ranked = rank(deps.llm, prefs.models.drafting, job["title"], company, job["jd_text"], cands)
    if not ranked:
        raise FinderError(f"No relevant people found at {company} for this role")
    save_candidates(conn, app_id, ranked)
    top = ranked[:3]
    person_names = [names.clean_name(c.name) for c, _, _ in top]

    # 2. domain and pattern hints
    dom = get_domain(conn, norm) or {}
    domain = dom.get("domain") or domain_from_text(job["jd_text"], company)
    if not domain:  # generic names ("slice") need context: city + India, then Groq picks this employer's site
        query = " ".join(f'"{company}" {job["location_city"] or ""} India official website'.split())
        domain = pick_domain(deps.llm, prefs.models.scoring, company, job["title"], job["location_city"],
                             job["jd_text"], _search(deps, budget, notes, query, max_results=8),
                             has_mail=lambda d: deps.resolver(d) is not None)
        if not domain:
            notes.append(f"Couldn't tell which website is {company}'s; set the email domain on the card")
    mx = deps.resolver(domain) if domain else None
    if domain and not mx:
        notes.append(f"{domain} has no mail server")
    hints = [dom["pattern"]] if dom.get("pattern") else []
    if domain and mx and not hints:
        text = " ".join(r.get("content", "") for r in _search(deps, budget, notes, f'"@{domain}"', max_results=10))
        inferred = names.infer_pattern(names.emails_in_text(text, domain))
        if inferred:
            hints.append(inferred)

    # 3. SMTP verification
    results: dict[int, tuple[str, str, str]] = {}
    taken = set(bounced_emails(conn, company))  # one address per person, never a bounced one
    catch_all = known_catch_all(dom, deps.now())
    learned_at = None  # set when this run asked the mail server
    if domain and mx:
        sender = prefs.contacts.sender_email or prefs.email
        try:
            with SmtpVerifier(mx, sender, socket.gethostname(), smtp_factory=deps.smtp_factory, sleep=deps.sleep,
                              pause=prefs.contacts.smtp_pause_seconds, allow=lambda: budget.can("smtp"),
                              spend=lambda: budget.spend("smtp")) as v:
                if catch_all is None:
                    catch_all = v.is_catch_all(domain)
                    learned_at = iso(deps.now())
                if not catch_all:
                    for i, nm in enumerate(person_names):
                        if not nm:
                            continue
                        email = v.check([e for e in names.candidates(nm, domain, hints) if e not in taken])
                        if email:
                            results[i] = (email, "verified", "smtp")
                            taken.add(email)
                            learned = names.pattern_of(email, nm)
                            if learned:
                                hints = [learned] + [h for h in hints if h != learned]
        except PortBlocked:
            notes.append("Couldn't verify on this network (port 25 blocked); try again from office Wi-Fi")
        except BudgetExceeded:
            notes.append("SMTP daily check limit reached")
        except VerifyUnavailable as e:
            notes.append(f"{domain}'s mail server refused verification; emails left as likely ({e})")
            if "refused" in str(e):
                catch_all = 2  # remembered: skip checks for this domain next time
                learned_at = iso(deps.now())
        save_domain(conn, norm, domain=domain, mx_host=mx, catch_all=catch_all,
                    pattern=hints[0] if hints else None, **({"catch_all_at": learned_at} if learned_at else {}))

    # 4. fallbacks
    for i, (c, _, _) in enumerate(top):
        if i in results or deps.apify is None:
            continue
        if not budget.can("apify", deps.apify.PROFILE_EMAIL_USD):
            notes.append(f"Apify budget used for {budget.month}")
            break
        budget.spend("apify", deps.apify.PROFILE_EMAIL_USD)
        try:
            email = (deps.apify.profile_email(c.linkedin_url) or "").lower()
        except Exception as e:  # keep what SMTP already verified
            notes.append(f"Apify email lookup failed ({type(e).__name__}); kept the other results")
            break
        if not email or email in taken or email.split("@", 1)[-1] in FREE_MAIL:
            continue  # personal addresses never become work emails
        if not domain or not mx or email.endswith("@" + domain):
            results[i] = (email, "verified", "apify")
            taken.add(email)
    if not (domain and mx):  # an Apify-verified address reveals the real email domain: remember it for free reuse
        found = next(((results[i][0], person_names[i]) for i in sorted(results)
                      if results[i][2] == "apify" and person_names[i]), None)
        if found and found[0].split("@", 1)[1] not in FREE_MAIL and deps.resolver(found[0].split("@", 1)[1]):
            domain = found[0].split("@", 1)[1]
            mx = deps.resolver(domain)
            learned = names.pattern_of(found[0], found[1])
            hints = ([learned] if learned else []) + [h for h in hints if h != learned]
            save_domain(conn, norm, domain=domain, mx_host=mx, pattern=learned)
    missing = [i for i in range(len(top)) if i not in results]
    if domain and mx and missing and deps.hunter is not None and not hints:
        if budget.can("hunter"):
            budget.spend("hunter")
            try:
                found = deps.hunter.domain_search(domain)
            except Exception as e:
                notes.append(f"Hunter lookup failed ({type(e).__name__})")
                found = {"pattern": None, "emails": []}
            if found["pattern"]:
                hints.insert(0, found["pattern"])
                save_domain(conn, norm, pattern=found["pattern"])
            listed = {(f.lower(), l.lower()): e for f, l, e in found["emails"]}
            for i in missing:
                nm = person_names[i]
                if nm and (nm.first, nm.last) in listed and listed[(nm.first, nm.last)].lower() not in taken:
                    results[i] = (listed[(nm.first, nm.last)].lower(), "verified", "hunter")
                    taken.add(results[i][0])
        else:
            notes.append(f"Hunter budget used for {budget.month}")

    # Verified addresses at this company beat any hint: guesses follow their pattern.
    for i in sorted(results):
        learned = person_names[i] and names.pattern_of(results[i][0], person_names[i])
        if learned and domain and results[i][0].endswith("@" + domain):
            hints = [learned] + [h for h in hints if h != learned]
            save_domain(conn, norm, pattern=learned)
            break

    # 5. best guesses, then save
    verified, linked = 0, set()
    for i, (c, label, reason) in enumerate(top):
        email, status, source = results.get(i, ("", "not_found", ""))
        if status == "not_found" and domain and mx and person_names[i]:
            guesses = [e for e in names.candidates(person_names[i], domain, hints) if e not in taken]
            if guesses:
                email, status, source = guesses[0], "likely", "pattern"
                taken.add(email)
        cid = upsert_contact(conn, company, c.name, c.headline, c.linkedin_url, email,
                             "verified" if status == "verified" else "unverified", domain=domain if mx else None)
        if cid is None:
            continue
        verified += status == "verified"
        link_contact(conn, app_id, i + 1, cid, label, reason, source)
        linked.add(i + 1)
    stale = [r for r in (1, 2, 3) if r not in linked]  # an earlier run's people this run didn't refill
    conn.executemany("DELETE FROM application_contacts WHERE application_id = ? AND rank = ?",
                     [(app_id, r) for r in stale])
    conn.commit()
    return {"people": len(top), "verified": verified, "notes": notes}


def run_find(db_path: Path | str, app_id: int, prefs: Preferences, deps_factory: Callable[[], Deps]) -> None:
    """Background entry point: own connection, status recorded for the page to poll."""
    conn = connect(db_path)
    try:
        summary = find_contacts(conn, app_id, prefs, deps_factory())
        note = f"Found {summary['people']} people, {summary['verified']} verified emails."
        set_find_status(conn, app_id, "done", " ".join([note, *summary["notes"]]))
    except Exception as e:  # the page must always leave the running state
        set_find_status(conn, app_id, "failed", f"{type(e).__name__}: {e}" if not isinstance(e, FinderError) else str(e))
    finally:
        conn.close()
