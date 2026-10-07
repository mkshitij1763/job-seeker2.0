from jobseeker.contacts.domains import domain_from_text, official_domain


def test_domain_from_text_prefers_company_like_domain():
    jd = "Apply via jobs.lever.co. Questions: talent@zeptonow.com. Visit https://www.zeptonow.com/about"
    assert domain_from_text(jd, "Zepto") == "zeptonow.com"


def test_domain_from_text_ignores_job_boards_and_webmail():
    assert domain_from_text("mail me at x@gmail.com or see linkedin.com/company/x", "Acme") is None


def test_domain_from_text_needs_the_full_company_name():
    jd = "We partner with Tata Steel (careers@tatasteel.com) and https://www.nslice.com"
    assert domain_from_text(jd, "Tata 1mg") is None  # "tata" alone matches a sister company
    assert domain_from_text(jd, "slice") is None  # a name inside another label isn't a match
    assert domain_from_text("Write to hr@tata1mg.com", "Tata 1mg") == "tata1mg.com"


def test_official_domain_from_search_results():
    results = [{"url": "https://www.linkedin.com/company/zepto"}, {"url": "https://www.crunchbase.com/org/zepto"},
               {"url": "https://www.zeptonow.com/"}, {"url": "https://blog.zeptonow.com/x"}]
    assert official_domain(results, "Zepto") == "zeptonow.com"


def test_official_domain_handles_co_in():
    assert official_domain([{"url": "https://careers.acme.co.in/jobs"}], "Acme") == "acme.co.in"


def test_domain_candidates_skip_job_sites_and_dedup():
    from jobseeker.contacts.domains import domain_candidates

    results = [{"url": "https://leadiq.com/c/slice/1", "title": "Slice | LeadIQ", "content": "x"},
               {"url": "https://slice.com", "title": "Slice — restaurants", "content": "US pizza"},
               {"url": "https://www.sliceit.com/about", "title": "slice - India", "content": "Bengaluru fintech"},
               {"url": "https://blog.sliceit.com/x", "title": "blog", "content": ""},
               {"url": "https://www.linkedin.com/company/slice", "title": "li", "content": ""}]
    assert [d for d, _ in domain_candidates(results)] == ["slice.com", "sliceit.com"]


def test_pick_domain_uses_llm_index_or_none():
    from jobseeker.contacts.domains import DomainPick, pick_domain
    from tests.fakes import FakeLLM

    results = [{"url": "https://slice.com", "title": "Slice — restaurants", "content": "US"},
               {"url": "https://www.sliceit.com", "title": "slice", "content": "Bengaluru fintech"}]
    llm = FakeLLM([{"index": 1}, {"index": -1}, {"index": 9}])
    args = (llm, "m", "slice", "Senior Product Analyst", "bengaluru", "UPI credit card fintech")
    assert pick_domain(*args, results) == "sliceit.com"
    assert pick_domain(*args, results) is None
    assert pick_domain(*args, results) is None
    assert llm.calls[0]["schema"] is DomainPick and "untrusted" in llm.calls[0]["system"].lower()
    assert pick_domain(FakeLLM([]), "m", "x", "t", None, "", []) is None


def test_pick_domain_only_offers_domains_that_receive_mail():
    from jobseeker.contacts.domains import pick_domain
    from tests.fakes import FakeLLM

    results = [{"url": "https://slice.careers", "title": "slice careers", "content": ""},
               {"url": "https://www.sliceit.com", "title": "slice", "content": "fintech"}]
    llm = FakeLLM([{"index": 0}])
    picked = pick_domain(llm, "m", "slice", "PA", "bengaluru", "", results,
                         has_mail=lambda d: d == "sliceit.com")
    assert picked == "sliceit.com" and "slice.careers" not in llm.calls[0]["prompt"]
