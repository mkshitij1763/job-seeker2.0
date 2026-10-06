from jobseeker.config import load_companies
from jobseeker.sources.registry import build_sources


def test_build_sources(settings):
    sources = build_sources(load_companies(settings.companies_path))
    names = [s.name for s in sources]
    assert "lever:cred" in names and "ashby:sarvam" in names and "greenhouse:groww" in names
    assert len(names) == len(set(names)) == 13


def test_build_sources_with_discovered_and_search(settings):
    from jobseeker.config import Company, SearchConfig

    companies = load_companies(settings.companies_path)
    discovered = [("tracxn", Company(name="Tracxn", ats="lever", slug="tracxn")),
                  ("cred", Company(name="CRED", ats="lever", slug="cred")),
                  ("cred club", Company(name="Cred Club", ats="lever", slug="cred"))]
    sources = build_sources(companies, discovered, SearchConfig(sites=["naukri", "linkedin"]))
    names = [s.name for s in sources]
    assert names[-3:] == ["lever:tracxn", "naukri", "linkedin"]
    assert names.count("lever:cred") == 1
    assert sources[-3].discovered_as == "tracxn"
