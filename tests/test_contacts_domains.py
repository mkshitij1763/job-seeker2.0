from jobseeker.contacts.domains import domain_from_text, official_domain


def test_domain_from_text_prefers_company_like_domain():
    jd = "Apply via jobs.lever.co. Questions: talent@zeptonow.com. Visit https://www.zeptonow.com/about"
    assert domain_from_text(jd, "Zepto") == "zeptonow.com"


def test_domain_from_text_ignores_job_boards_and_webmail():
    assert domain_from_text("mail me at x@gmail.com or see linkedin.com/company/x", "Acme") is None


def test_official_domain_from_search_results():
    results = [{"url": "https://www.linkedin.com/company/zepto"}, {"url": "https://www.crunchbase.com/org/zepto"},
               {"url": "https://www.zeptonow.com/"}, {"url": "https://blog.zeptonow.com/x"}]
    assert official_domain(results, "Zepto") == "zeptonow.com"


def test_official_domain_handles_co_in():
    assert official_domain([{"url": "https://careers.acme.co.in/jobs"}], "Acme") == "acme.co.in"
