from radar.score import score_job


def test_techpack_is_assigned_to_lane_owner(jobs, cfg, now):
    s = score_job(jobs["1003"], cfg, now)
    assert s.primary_lane == "techpack"
    assert s.assignee == "sam"


def test_identity_is_most_credible_for_lane(jobs, cfg, now):
    s = score_job(jobs["1001"], cfg, now)
    # motion_ui: agency 0.5 > freelancer 0.4
    assert s.identity == "studio_agency"
    assert [o.identity for o in s.identity_options][0] == "studio_agency"


def test_branding_goes_to_freelancer(cfg, now):
    from radar.models import Client, Job
    job = Job(id="b", title="Brand identity and logo for a boutique hotel",
              description="Complete brand identity, logo design and packaging.", job_type="fixed",
              budget_fixed=1500, client=Client(country="United States", payment_verified=True))
    s = score_job(job, cfg, now)
    assert s.identity == "alex_freelancer"


def test_ties_go_to_preferred_identity(jobs, cfg, now):
    cfg2 = cfg.model_copy(deep=True)
    for ident in cfg2.profiles.identities:
        ident.lane_strength = {k: 0.5 for k in ident.lane_strength}
        ident.default_strength = 0.5
    s = score_job(jobs["1001"], cfg2, now)
    assert s.identity == "alex_freelancer"   # preference 1


def test_analog_respects_identity(jobs, cfg, now):
    cfg2 = cfg.model_copy(deep=True)
    item = cfg2.portfolio.get("saas-launch-video")
    item.identities = ["alex_freelancer"]
    s = score_job(jobs["1001"], cfg2, now)
    assert s.identity == "studio_agency"
    assert s.analog_id != "saas-launch-video"
    assert any("no lo puede citar" in w for w in s.warnings)
