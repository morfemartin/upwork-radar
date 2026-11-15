import pytest

from radar.score import score_all, score_job, sigmoid


@pytest.fixture
def scored(jobs, cfg, now):
    return {s.job.id: s for s in score_all(list(jobs.values()), cfg, now)}


def test_best_job_passes_and_is_first(jobs, cfg, now):
    ranked = score_all(list(jobs.values()), cfg, now)
    assert ranked[0].job.id == "1001"
    assert ranked[0].passes


def test_only_good_jobs_pass(scored):
    assert {i for i, s in scored.items() if s.passes} == {"1001"}


@pytest.mark.parametrize("job_id, reason", [
    ("1004", "no es trabajo creativo"),
    ("1005", "no es trabajo creativo"),
    ("1006", "país descartado"),
    ("1007", "skill que no tenemos"),
    ("1008", "propuestas y el encaje"),
    ("1009", "ya contrató"),
])
def test_knockouts(scored, job_id, reason):
    assert any(reason in k for k in scored[job_id].knockouts), scored[job_id].knockouts


def test_deferred_start_and_crowding_hurt(scored):
    assert scored["1002"].score < scored["1001"].score - 20


def test_factors_are_bounded(scored):
    for s in scored.values():
        assert 0 <= s.score <= 100
        assert 0 < s.probability < 1
        for f in s.factors:
            assert 0 <= f.value <= 1, (s.job.id, f)


def test_probability_is_monotonic_in_score(cfg):
    w = cfg.weights
    assert sigmoid(w.bias + w.slope * 0.8) > sigmoid(w.bias + w.slope * 0.5)


def test_expected_value(scored):
    s = scored["1001"]
    assert s.expected_pay == 2500
    assert s.expected_value == pytest.approx(s.probability * 2500 - 18 * 0.15, abs=0.01)


def test_unverified_payment_is_a_knockout(jobs, cfg, now):
    job = jobs["1001"].model_copy(deep=True)
    job.client.payment_verified = False
    assert "pago no verificado" in score_job(job, cfg, now).knockouts


def test_old_jobs_are_knocked_out(jobs, cfg, now):
    from datetime import timedelta
    assert any("publicado hace" in k for k in score_job(jobs["1001"], cfg, now + timedelta(days=4)).knockouts)


def test_mode(scored):
    assert scored["1001"].mode == "full"     # launch + several deliverables
