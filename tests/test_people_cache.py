from datetime import timedelta

from jobseeker.db.contacts_repo import cached_search, store_search
from jobseeker.db.core import connect
from tests.test_contacts_finder import NOW  # the finder tests' fixed clock


def test_cache_hit_within_30_days_then_miss(settings):
    conn = connect(settings.db_path)
    store_search(conn, "Acme Pvt Ltd", "q", "tavily", [{"url": "u"}], NOW)
    assert cached_search(conn, "acme", "q", "tavily", NOW + timedelta(days=29)) == [{"url": "u"}]
    assert cached_search(conn, "acme", "q", "tavily", NOW + timedelta(days=31)) is None
    assert cached_search(conn, "acme", "other", "tavily", NOW) is None
