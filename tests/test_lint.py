import pytest

from radar.brief import EN_END, EN_START, ES_END, ES_START, render
from radar.lint import lint_text
from radar.score import score_job

GOOD_FAST = (
    "A launch video only works when the viewer understands the product in the first five seconds. "
    "For a logistics SaaS that means showing the real dashboard, not abstract shapes. "
    "We recently delivered a 60-second launch video for a project-management SaaS, with the real UI rebuilt "
    "and animated in code, so every screen matched the product exactly and could be re-rendered when the UI "
    "changed. For your video I would rebuild your dashboard from the Figma files, animate three features with "
    "cursor clicks and live data, and cut the three vertical versions from the same source so captions and "
    "brand colors stay consistent. Delivery is ten business days for the horizontal master and three more days "
    "for the vertical cuts, with two revision rounds. "
    "Which feature do your customers mention first when they explain why they switched to you?"
)


def doc(en, *, mode="fast", hook="B", analog="saas-launch-video", es="Borrador en español."):
    return (f"---\nmode: {mode}\nhook_type: {hook}\nanalog_id: {analog}\n---\n"
            f"{ES_START}\n{es}\n{ES_END}\n{EN_START}\n{en}\n{EN_END}\n")


def test_good_fast_proposal_passes(cfg):
    r = lint_text(doc(GOOD_FAST), cfg)
    assert r.ok, r.errors


@pytest.mark.parametrize("en, expected", [
    ("Hi there! " + GOOD_FAST, "R1"),
    ("My name is Alex and I make videos. " + GOOD_FAST, "R1"),
    (GOOD_FAST + " Can we talk tomorrow?", "R6"),
    (GOOD_FAST.replace("?", "."), "R6"),
    ("Short text. Which feature matters most?", "largo"),
    (GOOD_FAST.replace("We recently", "I am excited to apply. We recently"), "frase prohibida"),
    (GOOD_FAST.replace("Delivery", "[Delivery]"), "marcadores"),
])
def test_rule_violations(cfg, en, expected):
    r = lint_text(doc(en), cfg)
    assert any(expected in e for e in r.errors), r.errors


def test_unknown_analog_fails_r7(cfg):
    r = lint_text(doc(GOOD_FAST, analog="invented-client"), cfg)
    assert any("R7" in e for e in r.errors)


def test_bad_hook_type(cfg):
    assert any("hook_type" in e for e in lint_text(doc(GOOD_FAST, hook="Z"), cfg).errors)


def test_repeated_hook_is_a_warning(cfg):
    r = lint_text(doc(GOOD_FAST), cfg, hooks_used_today=["B"])
    assert r.ok and any("ya se usó" in w for w in r.warnings)


def test_full_mode_needs_phases(cfg):
    long = " ".join([GOOD_FAST.rsplit(" Which", 1)[0]] * 3) + " Which feature matters most?"
    r = lint_text(doc(long, mode="full"), cfg)
    assert any("R5" in e for e in r.errors)
    phased = long.replace(" Which feature", "\n\nPhase 1 Script and storyboard: 4 days, $600\n"
                                            "Phase 2 Animation and sound: 8 days, $1,500\n"
                                            "Phase 3 Vertical cuts: 3 days, $400\n\nWhich feature")
    assert not any("R5" in e for e in lint_text(doc(phased, mode="full"), cfg).errors)


def test_fresh_brief_fails_until_filled(jobs, cfg, now):
    md = render(score_job(jobs["1001"], cfg, now), cfg)
    r = lint_text(md, cfg)
    assert any("faltan bloques" in e for e in r.errors)
    assert "## 8. Preguntas de filtro del cliente" in md


SRC = ("I am developing a luxury American Mahjong tile collection inspired by Kerala, South India. "
       "I need a talented illustrator to manually recreate my renderings into hand-drawn artwork, "
       "then vectorize each tile for production with the manufacturer.")


def doc_src(en, title="Hand-Drawn Illustrator for Kerala Mahjong Tile Collection", budget=500):
    return (f"---\nmode: fast\nhook_type: C\nanalog_id: saas-launch-video\ntitle: {title}\nbudget: {budget}\n---\n"
            f"<!-- SRC:START -->\n{SRC}\n<!-- SRC:END -->\n"
            f"<!-- ES:START -->\nBorrador.\n<!-- ES:END -->\n<!-- EN:START -->\n{en}\n<!-- EN:END -->\n")


SPECIFIC = ("A Mahjong set lives or dies on consistency: every tile has to read as one family once it sits on the "
            "table. Kerala gives you a strong visual language, from temple architecture to backwater greens, and "
            "the risk with AI renderings is that each tile drifts in line weight and detail. I would redraw your "
            "renderings by hand at one fixed scale, then vectorize them so the manufacturer gets clean, "
            "production-ready files with matching stroke widths across the whole collection. We did the same for "
            "a launch video where every screen had to match. Delivery is ten business days for the first suit, with "
            "two revision rounds. Which suit should we draw first so you can judge the line quality?")


def test_specific_proposal_passes_template_checks(cfg):
    r = lint_text(doc_src(SPECIFIC), cfg)
    assert not [e for e in r.errors if "plantilla" in e or "genérica" in e], r.errors


def test_pasted_title_is_rejected(cfg):
    en = SPECIFIC.replace("A Mahjong set", "Hand-Drawn Illustrator for Kerala Mahjong Tile Collection: a set", 1)
    assert any("título" in e for e in lint_text(doc_src(en), cfg).errors)


def test_copied_client_sentence_is_rejected(cfg):
    en = SPECIFIC.replace("We did the same", "I need a talented illustrator to manually recreate my renderings into hand-drawn artwork. We did the same")
    assert any("copia frases" in e for e in lint_text(doc_src(en), cfg).errors)


def test_generic_proposal_is_rejected(cfg):
    assert any("genérica" in e for e in lint_text(doc_src(GOOD_FAST), cfg).errors)


def test_same_template_across_run_is_rejected(cfg, tmp_path):
    from radar.lint import lint_many
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(doc_src(SPECIFIC))
    b.write_text(doc_src(SPECIFIC.replace("Kerala", "Kerala, India,")))
    res = lint_many([a, b], cfg)
    assert all(any("igual a" in e for e in r.errors) for r in res.values())
