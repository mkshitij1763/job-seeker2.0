import httpx
import respx

from jobseeker.contacts.people import (
    Candidate, Picks, from_results, mentions_company, parse_result, rank, search_queries,
)
from jobseeker.contacts.tavily import TavilyClient
from tests.fakes import FakeLLM

R = [
    {"title": "Sana Mazumdar - Product @ Zepto | LinkedIn", "url": "https://in.linkedin.com/in/sana-mazumdar",
     "content": "Product at Zepto. Bengaluru."},
    {"title": "Arpit Banerjee - Product | Ads, E-commerce", "url": "https://in.linkedin.com/in/arpit-banerjee",
     "content": "Ex-Flipkart."},
    {"title": "Harsh M. – Senior Product Manager @Zepto", "url": "https://www.linkedin.com/in/harshmehta2468?x=1",
     "content": ""},
    {"title": "Zepto | LinkedIn", "url": "https://www.linkedin.com/company/zepto", "content": ""},
]


@respx.mock
def test_tavily_search_posts_query_with_bearer():
    route = respx.post("https://api.tavily.com/search").respond(json={"results": R})
    out = TavilyClient("k").search("q", include_domains=["linkedin.com"], max_results=10)
    assert out == R
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer k"
    assert b'"include_domains":["linkedin.com"]' in sent.content.replace(b" ", b"")


def test_parse_and_company_filter():
    c = parse_result(R[0])
    assert c == Candidate("Sana Mazumdar", "Product @ Zepto", "https://www.linkedin.com/in/sana-mazumdar",
                          "Product at Zepto. Bengaluru.")
    assert parse_result(R[2]).linkedin_url == "https://www.linkedin.com/in/harshmehta2468"
    assert parse_result(R[3]) is None
    assert mentions_company(c, "Zepto") and not mentions_company(parse_result(R[1]), "Zepto")


def test_from_results_filters_and_dedups():
    seen = {"https://www.linkedin.com/in/harshmehta2468"}
    out = from_results(R, "Zepto", seen)
    assert [c.name for c in out] == ["Sana Mazumdar"]
    assert from_results(R, "Zepto", seen) == []


def test_search_queries():
    team, recruiting = search_queries("Zepto", "Associate Product Manager", "apm", "bengaluru")
    assert team == 'site:linkedin.com/in "Zepto" product manager bengaluru'
    assert recruiting == 'site:linkedin.com/in "Zepto" (recruiter OR "talent acquisition")'


def _cands(n):
    return [Candidate(f"P{i}", f"Role {i} @ Zepto", f"https://www.linkedin.com/in/p{i}") for i in range(n)]


def test_rank_returns_ordered_picks():
    llm = FakeLLM([{"picks": [{"index": 2, "label": "hiring_manager", "reason": "Leads product"},
                              {"index": 0, "label": "recruiter", "reason": "Hires PMs"}]}])
    out = rank(llm, "m", "APM", "Zepto", "jd", _cands(3))
    assert [(c.name, label) for c, label, _ in out] == [("P2", "hiring_manager"), ("P0", "recruiter")]
    assert llm.calls[0]["schema"] is Picks and "untrusted" in llm.calls[0]["system"].lower()


def test_rank_ignores_invalid_and_duplicate_indices():
    llm = FakeLLM([{"picks": [{"index": 7, "label": "peer", "reason": "x"}, {"index": 1, "label": "peer", "reason": "y"},
                              {"index": 1, "label": "team_lead", "reason": "z"}, {"index": -1, "label": "peer", "reason": "w"}]}])
    out = rank(llm, "m", "APM", "Zepto", "jd", _cands(2))
    assert [(c.name, label) for c, label, _ in out] == [("P1", "peer")]


def test_rank_with_no_candidates_skips_llm():
    llm = FakeLLM([])
    assert rank(llm, "m", "APM", "Zepto", "jd", []) == [] and llm.calls == []
