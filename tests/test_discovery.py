from datetime import UTC, datetime, timedelta

import httpx
import respx

from jobseeker.db.companies import get_company, record_company
from jobseeker.db.core import connect
from jobseeker.pipeline.discovery import candidate_slugs, discover, find_board

NOW = datetime(2026, 10, 7, tzinfo=UTC)
GH = "https://boards-api.greenhouse.io/v1/boards/{}/jobs"
LV = "https://api.lever.co/v0/postings/{}"
AB = "https://api.ashbyhq.com/posting-api/job-board/{}"
NO_SLEEP = dict(sleep=lambda s: None)


def test_candidate_slugs():
    assert candidate_slugs("Pocket FM") == ["pocketfm", "pocket-fm", "pocket"]
    assert candidate_slugs("Observe.AI") == ["observeai", "observe-ai", "observe"]
    assert candidate_slugs("Meesho Technologies Pvt Ltd") == ["meesho"]
    assert candidate_slugs("Pvt Ltd") == []


@respx.mock
def test_finds_lever_board_by_title():
    respx.get(LV.format("tracxn")).respond(json=[{"text": "Senior Associate Product Manager - Data Platform"}])
    respx.route().respond(404)
    hit = find_board(httpx.Client(), "Tracxn", {"tracxn senior associate product manager data platform"},
                     **NO_SLEEP)
    assert hit == ("lever", "tracxn")


@respx.mock
def test_finds_greenhouse_board_by_name_when_titles_differ():
    respx.get(GH.format("groww")).respond(json={"jobs": [{"title": "Data Engineer"}]})
    respx.get("https://boards-api.greenhouse.io/v1/boards/groww").respond(json={"name": "Groww"})
    respx.route().respond(404)
    assert find_board(httpx.Client(), "Groww", {"product analyst"}, **NO_SLEEP) == ("greenhouse", "groww")


@respx.mock
def test_rejects_board_with_unrelated_titles():
    respx.get(LV.format("zeta")).respond(json=[{"text": "Line Cook"}, {"text": "Barista"}])
    respx.route().respond(404)
    assert find_board(httpx.Client(), "Zeta", {"product manager ii"}, **NO_SLEEP) is None


@respx.mock
def test_ashby_board_found():
    respx.get(AB.format("sarvam")).respond(json={"jobs": [{"title": "AI Product Manager"}]})
    respx.route().respond(404)
    assert find_board(httpx.Client(), "Sarvam", {"ai product manager"}, **NO_SLEEP) == ("ashby", "sarvam")


@respx.mock
def test_discover_records_active_and_none_and_respects_skip_and_limit():
    respx.get(LV.format("tracxn")).respond(json=[{"text": "APM, Payments"}])
    respx.route().respond(404)
    conn = connect(":memory:")
    seen = {"tracxn": ("Tracxn", {"associate product manager payments"}), "acme": ("Acme", {"pm"}),
            "cred": ("CRED", {"pm"}), "later": ("Later", {"pm"})}
    found = discover(conn, httpx.Client(), seen, skip={"cred"}, now=NOW, limit=2, **NO_SLEEP)
    assert found == 1
    assert get_company(conn, "tracxn")["status"] == "active"
    assert get_company(conn, "acme")["status"] == "none"
    assert get_company(conn, "cred") is None and get_company(conn, "later") is None


@respx.mock
def test_timeout_is_not_recorded_as_none():
    respx.route().mock(side_effect=httpx.ConnectTimeout("slow"))
    conn = connect(":memory:")
    assert discover(conn, httpx.Client(), {"acme": ("Acme", {"pm"})}, set(), NOW, **NO_SLEEP) == 0
    assert get_company(conn, "acme") is None


@respx.mock
def test_recently_checked_company_is_not_probed_again():
    route = respx.route().respond(404)
    conn = connect(":memory:")
    record_company(conn, "acme", "Acme", "none", now=NOW - timedelta(days=5))
    discover(conn, httpx.Client(), {"acme": ("Acme", {"pm"})}, set(), NOW, **NO_SLEEP)
    assert route.call_count == 0


@respx.mock
def test_first_word_slug_needs_board_name():
    respx.get(GH.format("zeta")).respond(json={"jobs": [{"title": "Product Manager Payments"}]})
    respx.get("https://boards-api.greenhouse.io/v1/boards/zeta").respond(json={"name": "Zeta Global"})
    respx.route().respond(404)
    assert find_board(httpx.Client(), "Zeta Suite", {"product manager payments"}, **NO_SLEEP) is None


@respx.mock
def test_single_generic_title_match_is_not_enough():
    respx.get(LV.format("acme")).respond(json=[{"text": "Product Manager II"}, {"text": "Line Cook"}])
    respx.route().respond(404)
    assert find_board(httpx.Client(), "Acme", {"senior product manager ii"}, **NO_SLEEP) is None


@respx.mock
def test_two_generic_title_matches_are_enough():
    respx.get(LV.format("acme")).respond(json=[{"text": "Product Manager"}, {"text": "Product Analyst"}])
    respx.route().respond(404)
    assert find_board(httpx.Client(), "Acme", {"product manager", "senior product analyst"}, **NO_SLEEP) \
        == ("lever", "acme")
