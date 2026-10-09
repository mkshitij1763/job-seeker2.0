from jobseeker.pipeline.plan import Plan, PlanUser, build_plan

SITES = ["linkedin", "naukri", "indeed"]
CATALOG = {"Product Analyst", "Associate Product Manager", "Product Manager", "Founder's Office", "Growth Analyst",
           "Business Analyst", "Data Analyst"}
OWNER = PlanUser(1, ["Product Analyst", "Associate Product Manager", "Product Manager", "Founder's Office",
                     "Growth Analyst"], ["Bengaluru", "Gurgaon", "Noida", "Pune", "India"], "", "2026-10-01")


def test_owner_alone_is_todays_55_searches():
    plan = build_plan([OWNER], SITES, CATALOG, run_no=0, cap=60, max_custom=3)
    assert len(plan.linkedin) == 5 and len(plan.pairs) == 25
    assert plan.planned == plan.total == 55 and plan.trimmed == 0
    assert plan.for_site("linkedin") == [(q, "India") for q in plan.linkedin]
    assert plan.for_site("naukri") == plan.pairs


def test_union_dedups_and_round_one_serves_everyone():
    a = PlanUser(1, ["Product Analyst"], ["Bengaluru", "Pune"], "", "1")
    b = PlanUser(2, ["Data Analyst"], ["Mumbai"], "", "2")
    c = PlanUser(3, ["Product Analyst"], ["Bengaluru"], "", "3")
    plan = build_plan([a, b, c], SITES, CATALOG, run_no=0, cap=2 + 2 * 2, max_custom=3)  # 2 linkedin + 2 pairs
    assert sorted(plan.linkedin) == ["Data Analyst", "Product Analyst"]
    assert ("Product Analyst", "Bengaluru") in plan.pairs and ("Data Analyst", "Mumbai") in plan.pairs
    # every search wanted: 2 linkedin + 2 sites x 3 pairs; ("Product Analyst", "Pune") rotates in later
    assert plan.planned == 6 and plan.total == 8 and plan.trimmed == 2


def test_cap_never_exceeded_and_rotation_reaches_every_pair():
    users = [PlanUser(u, ["Product Analyst", "Data Analyst"], ["Bengaluru", "Pune", "Mumbai", "Hyderabad"], "", str(u))
             for u in (1, 2, 3)]
    seen: set = set()
    plans = [build_plan(users, SITES, CATALOG, run_no=n, cap=14, max_custom=3) for n in range(8)]
    for p in plans:
        assert len(p.linkedin) + 2 * len(p.pairs) <= 14
        seen |= set(p.pairs)
    assert seen == {(q, c) for q in ("Product Analyst", "Data Analyst") for c in ("Bengaluru", "Pune", "Mumbai", "Hyderabad")}


def test_custom_queries_capped_oldest_first():
    users = [PlanUser(u, [f"Custom {u}"], ["Pune"], f"Custom {u}", f"2026-10-0{u}") for u in (4, 1, 3, 2)]
    plan = build_plan(users, SITES, CATALOG, run_no=0, cap=100, max_custom=3)
    assert sorted(plan.linkedin) == ["Custom 1", "Custom 2", "Custom 3"]


def test_no_linkedin_site_and_empty_users():
    assert build_plan([], SITES, CATALOG, 0, 60, 3) == Plan([], [], 0, 0, 0)
    plan = build_plan([OWNER], ["naukri"], CATALOG, 0, 60, 3)
    assert plan.linkedin == [] and plan.planned == plan.total == 25 and plan.trimmed == 0


def test_trimmed_counts_linkedin_queries_cut_by_the_cap():
    a = PlanUser(1, ["Product Analyst", "Data Analyst"], ["Pune"], "", "1")
    plan = build_plan([a], SITES, CATALOG, run_no=0, cap=1, max_custom=3)
    assert len(plan.linkedin) == 1 and plan.pairs == []
    assert plan.planned == 1 and plan.total == 2 + 2 * 2 and plan.trimmed == 5
