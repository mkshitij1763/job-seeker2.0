from datetime import timedelta

from jobseeker.config import Company

from jobseeker.db.core import connect
from tests.test_run import NOW, StaticSource, handler, raw
from tests.fakes import FakeLLM


class Board(StaticSource):  # an ATS board: has .company, like GreenhouseSource
    def __init__(self, name, **kw):
        super().__init__(name, **kw)
        self.company, self.calls = Company(name=name, ats="lever", slug=name), 0

    def fetch(self, client):
        self.calls += 1
        return super().fetch(client)


def test_fetch_now_skips_boards_fetched_ok_in_the_last_12h(prefs, rubric, facts):
    conn = connect(":memory:")
    ok, broken, site = Board("lever:cred", jobs=[raw()]), Board("lever:gone", error=RuntimeError("x")), StaticSource("naukri")
    llm = FakeLLM(handler=handler)

    def run(trigger, hours):
        from jobseeker.db.users import user_by_id
        from jobseeker.pipeline.run import run_all
        from tests.test_run_all import _cfg
        r = run_all(conn, users=[user_by_id(conn, 1)], trigger=trigger, fetch=True, plan_cap=60, client=None, llm=llm,
                cfg=_cfg(prefs), rubric=rubric, now=NOW + timedelta(hours=hours), describe=lambda s, i: "",
                sources_factory=lambda *a, **k: [ok, broken, site], context=lambda c, uid: (prefs, facts),
                notify=lambda *a: None)
        assert r.aborted is None, r.aborted
    run("fetch_now", 0)
    run("fetch_now", 1)                                # within 12h: the good board is skipped, the failed one retried
    assert (ok.calls, broken.calls) == (1, 2)
    run("schedule", 2)                                 # the scheduled run still sweeps every board
    assert (ok.calls, broken.calls) == (2, 3)
    run("fetch_now", 13)                               # 11h after the schedule's fetch: still fresh
    assert ok.calls == 2
    run("fetch_now", 14.5)                             # 12.5h after it: fetched again
    assert ok.calls == 3
