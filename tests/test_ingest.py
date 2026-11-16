from radar.ingest import _budget, clean, money


def test_untrusted_tags_are_stripped(jobs):
    assert "untrusted" not in jobs["1001"].description
    assert jobs["1001"].description.startswith("We are a B2B SaaS")


def test_budget_parsing():
    assert _budget("2500.00", "fixed") == (2500.0, None, None)
    assert _budget("20.00–50.00/hr", "hourly") == (None, 20.0, 50.0)
    assert _budget("15-30/hr", "hourly") == (None, 15.0, 30.0)
    assert _budget(None, "fixed") == (None, None, None)


def test_money_and_clean():
    assert money("$38,200.00") == 38200.0
    assert money(None) is None
    assert clean("<untrusted_participant_content>\nhi\n</untrusted_participant_content>") == "hi"


def test_get_is_merged(jobs):
    j = jobs["1001"]
    assert j.has_details
    assert j.client.hire_rate == 72
    assert j.client.hires == 16
    assert j.client.country == "United States"
    assert j.connects_cost == 18
    assert j.screening_questions == ["Share 2 SaaS product videos you have made."]


def test_search_only_jobs_have_no_details(jobs):
    assert not jobs["1002"].has_details
    assert jobs["1002"].client.payment_verified is True
    assert jobs["1003"].client.payment_verified is None


def test_url_tracking_params_removed(jobs):
    assert jobs["1001"].url == "https://www.upwork.com/jobs/~021001"


def test_failed_files_are_reported(tmp_path):
    import json
    from radar.ingest import failed_files, ingest_dir
    (tmp_path / "a.json").write_text(json.dumps({"status": "error", "error_code": "SENSITIVE_RATE_LIMIT_EXCEEDED",
                                                 "retry_after_seconds": 5}))
    (tmp_path / "b.json").write_text(json.dumps({"status": "ok", "jobs": []}))
    assert failed_files(tmp_path) == [("a.json", "SENSITIVE_RATE_LIMIT_EXCEEDED", 5)]
    assert ingest_dir(tmp_path) == []
