from radar.lanes import classify, flags, has
from radar.models import Job


def lanes_of(job, cfg):
    return [h.lane for h in classify(job, cfg.lanes)]


def test_term_matching_is_whole_word_and_plural_tolerant():
    assert has("ui animation", "we want UI-animations for our app")
    assert has("tech pack", "two Tech Packs needed")
    assert not has("cap", "screen capture tool")


def test_saas_video_is_motion_first(jobs, cfg):
    assert lanes_of(jobs["1001"], cfg)[0] == "motion_ui"


def test_hoodie_is_techpack(jobs, cfg):
    assert lanes_of(jobs["1003"], cfg)[0] == "techpack"


def test_painting_estimator_is_not_painting(jobs, cfg):
    assert "painting" not in lanes_of(jobs["1004"], cfg)


def test_website_video_is_not_web(cfg):
    job = Job(id="x", title="Website Video for Business Broker Homepage Video, 60 to 75 Seconds",
              description="Homepage video with captions, b-roll and a vertical cut.", skills=["Explainer Video"])
    assert "web" not in lanes_of(job, cfg)


def test_flags(cfg):
    job = Job(id="x", title="Hand-painted memorial portrait", description="watercolor, luxury frame")
    assert flags(job, cfg.lanes) == ["H1", "H2", "H5"]
