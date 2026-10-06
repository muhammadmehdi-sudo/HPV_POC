from pathlib import Path

import pytest

import brain

ROOT = Path(__file__).resolve().parent.parent
content = brain.Content(ROOT / "content" / "hpv_placeholder.yaml")

ANSWERS = [
    # English
    ("is hpv vaccine safe?", "hpv.safety"),
    ("What is HPV", "hpv.what_is"),
    ("can the hpv vaccine make my daughter infertile", "hpv.fertility_myth"),
    ("what age should girls get the vaccine", "hpv.eligibility_age"),
    ("side effects?", "hpv.side_effects"),
    ("where do i get the vaccine", "hpv.where_to_get"),
    # Urdu script
    ("کیا ایچ پی وی ویکسین محفوظ ہے؟", "hpv.safety"),
    ("ایچ پی وی کیا ہے", "hpv.what_is"),
    ("کیا ویکسین سے بانجھ پن ہو جاتا ہے؟", "hpv.fertility_myth"),
    ("ویکسین کس عمر میں لگوانی چاہیے", "hpv.eligibility_age"),
    ("ویکسین کے مضر اثرات", "hpv.side_effects"),
    ("ٹیکہ کہاں لگے گا", "hpv.where_to_get"),
    # Roman Urdu, incl. misspellings and code-switching
    ("kya hpv vaccine mehfooz hai", "hpv.safety"),
    ("hpv kya hota hai", "hpv.what_is"),
    ("kya vacsin se baanjh pan hota hai", "hpv.fertility_myth"),
    ("teeka kis umr mein lagta hai", "hpv.eligibility_age"),
    ("tike ke side effects kya hain", "hpv.side_effects"),
    ("vaccine kahan se milegi", "hpv.where_to_get"),
    ("HPV ka vaccine safe hai kya meri beti ke liye?", "hpv.safety"),
    ("plzzz batao hpv vaccine mehfooz hai?", "hpv.safety"),
    ("waxin se banjh pan", "hpv.fertility_myth"),
]


@pytest.mark.parametrize("query,unit_id", ANSWERS)
def test_answers(query, unit_id):
    action, unit, _ = content.decide(query)
    assert (action, unit["id"]) == ("answer", unit_id)


@pytest.mark.parametrize("query", ["hi", "Assalam o Alaikum", "السلام علیکم"])
def test_greeting(query):
    assert content.decide(query)[0] == "greeting"


@pytest.mark.parametrize("query", [
    "teeka lagne ke baad behosh ho gayi",  # would otherwise look like side effects
    "my daughter fainted after the shot",
    "ٹیکے کے بعد سانس لینے میں مشکل",
    "beti ko daura para",
    "vaccine ke baad tez bukhar hai",
])
def test_danger_escalates_before_retrieval(query):
    action, unit, _ = content.decide(query)
    assert (action, unit["id"]) == ("escalate", "sys.emergency")


@pytest.mark.parametrize("query", ["cricket score", "write a poem", "bitcoin price", "what is the capital of france"])
def test_out_of_scope_deflects(query):
    action, unit, _ = content.decide(query)
    assert (action, unit["id"]) == ("deflect", "sys.out_of_scope")


@pytest.mark.parametrize("query", ["hpv vaccine", "is hpv vaccine ok"])
def test_ambiguous_clarifies(query):
    assert content.decide(query)[0] == "clarify"


@pytest.mark.parametrize("text,lang", [
    ("Is the HPV vaccine safe?", "en"),
    ("کیا ایچ پی وی ویکسین محفوظ ہے؟", "ur"),
    ("کیا HPV vaccine safe ہے؟", "ur"),
    ("kya hpv vaccine mehfooz hai", "ur_roman"),
    ("HPV ka vaccine safe hai kya?", "ur_roman"),
    ("123 ???", None),
])
def test_detect_lang(text, lang):
    assert brain.detect_lang(text) == lang


def test_reviewed_content_swaps_in_without_marker():
    alt = brain.Content(ROOT / "tests" / "fixtures" / "alt_content.yaml")
    action, unit, _ = alt.decide("is the vaccine safe")
    assert (action, unit["id"]) == ("answer", "alt.safety")


def test_unreviewed_unit_without_marker_is_rejected(tmp_path):
    source = (ROOT / "content" / "hpv_placeholder.yaml").read_text(encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text(source.replace("[PLACEHOLDER – not medical advice] HPV (human", "HPV (human", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="placeholder marker"):
        brain.Content(bad)
