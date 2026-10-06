from jobseeker.config import load_companies
from jobseeker.sources.registry import build_sources


def test_build_sources(settings):
    sources = build_sources(load_companies(settings.companies_path))
    names = [s.name for s in sources]
    assert "lever:cred" in names and "ashby:sarvam" in names and "greenhouse:groww" in names
    assert len(names) == len(set(names)) == 13
