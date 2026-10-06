"""Retrieval-only core: content loading, normalization, language ID, danger check, matching."""
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

import yaml

LANGS = ("en", "ur", "ur_roman")
PLACEHOLDER_MARKERS = ("[PLACEHOLDER", "[عارضی متن")
REQUIRED_UNITS = ("sys.greeting", "sys.emergency", "sys.out_of_scope")
MAX_TITLE, MAX_TEXT, MAX_RELATED = 20, 1024, 3  # WhatsApp button title, interactive body, buttons
ANSWER_THRESHOLD, CLARIFY_THRESHOLD = 0.50, 0.30
ANSWER_MARGIN = 0.10  # top must beat runner-up by this much, else clarify

# Arabic yeh/kaf -> Urdu forms; zero-width joiners dropped so "بے\u200cہوش" == "بےہوش".
CHAR_MAP = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": None, "\u200d": None})
DIACRITICS = re.compile(r"[\u064b-\u065f\u0670]")
REPEATS = re.compile(r"(.)\1{2,}")
PUNCT = re.compile(r"[^\w\s]")
ROMAN_URDU_MARKERS = {
    "hai", "hain", "kya", "kia", "mein", "nahi", "nahin", "ke", "ki", "ka", "ko", "se", "aur",
    "hota", "hoti", "hote", "alaikum", "kaise", "kahan", "kab", "kyun", "mujhe", "meri", "mera", "beti", "liye",
}


def clean(text):
    text = unicodedata.normalize("NFKC", text).lower().translate(CHAR_MAP)
    text = REPEATS.sub(r"\1", DIACRITICS.sub("", text))
    return " ".join(PUNCT.sub(" ", text).split())


def detect_lang(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    if any("\u0600" <= c <= "\u06ff" for c in letters):  # code-switched "\u06a9\u06cc\u0627 HPV vaccine safe \u06c1\u06d2\u061f" reads Urdu
        return "ur"
    return "ur_roman" if set(clean(text).split()) & ROMAN_URDU_MARKERS else "en"


def trigrams(normalized):
    grams = set()
    for word in normalized.split():
        padded = f" {word} "
        grams.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return grams


class Content:
    def __init__(self, path):
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.messages = data["messages"]
        self.units = {u["id"]: u for u in data["units"]}
        self._validate()

        self.token_map, self.phrases = {}, []
        for concept, variants in data["lexicon"].items():
            for variant in map(clean, variants):
                if " " in variant:
                    self.phrases.append((variant, concept))
                else:
                    self.token_map[variant] = concept
        self.phrases.sort(key=lambda p: -len(p[0]))
        self.stopwords = {clean(w) for w in data["stopwords"]}

        self.danger_phrases = [self.normalize(p) for p in data["danger_phrases"]]
        if not all(self.danger_phrases):
            raise ValueError("a danger phrase normalizes to nothing (all stopwords?)")
        self.index = [
            (unit, trigrams(self.normalize(v["text"])))
            for unit in self.units.values()
            for v in unit["question_variants"]
        ]
        # Trigrams shared by most variants ("hpv", "vaccine") carry little signal; unseen ones the most.
        doc_freq = Counter(g for _, grams in self.index for g in grams)
        self.max_weight = math.log(1 + len(self.index))
        self.weights = {g: math.log(1 + len(self.index) / df) for g, df in doc_freq.items()}
        self.topics = [u for u in self.units.values() if not u["id"].startswith("sys.")][:10]

    def _validate(self):
        for required in REQUIRED_UNITS:
            if required not in self.units:
                raise ValueError(f"missing required unit {required}")
        for uid, unit in self.units.items():
            for lang in LANGS:
                title, text = unit["title"].get(lang), unit["text"].get(lang)
                if not title or not text:
                    raise ValueError(f"{uid}: missing title/text for {lang}")
                if len(title) > MAX_TITLE or len(text) > MAX_TEXT:
                    raise ValueError(f"{uid}: {lang} title > {MAX_TITLE} or text > {MAX_TEXT} chars")
                if unit["review"]["reviewer_id"] is None and not text.startswith(PLACEHOLDER_MARKERS):
                    raise ValueError(f"{uid}: unreviewed unit lacks placeholder marker ({lang})")
            related = unit["related_units"]
            if len(related) > MAX_RELATED or any(r not in self.units for r in related):
                raise ValueError(f"{uid}: related_units must be <= {MAX_RELATED} existing ids")

    def normalize(self, text):
        padded = f" {clean(text)} "
        for phrase, concept in self.phrases:
            padded = padded.replace(f" {phrase} ", f" {concept} ")
        tokens = (self.token_map.get(t, t) for t in padded.split())
        return " ".join(t for t in tokens if t not in self.stopwords)

    def retrieve(self, text):
        """[(unit, score)] best first; score = best IDF-weighted char-trigram Dice over the unit's variants."""
        query = trigrams(self.normalize(text))

        def mass(grams):
            return sum(self.weights.get(g, self.max_weight) for g in grams)

        best = {}
        for unit, grams in self.index:
            score = 2 * mass(query & grams) / (mass(query) + mass(grams)) if query and grams else 0.0
            if score > best.get(unit["id"], (None, -1))[1]:
                best[unit["id"]] = (unit, score)
        return sorted(best.values(), key=lambda pair: -pair[1])

    def decide(self, text):
        """(action, unit_to_send or None, ranked). action: escalate|answer|greeting|clarify|deflect."""
        query = f" {self.normalize(text)} "
        if any(f" {phrase} " in query for phrase in self.danger_phrases):
            return "escalate", self.units["sys.emergency"], []
        ranked = self.retrieve(text)
        top_unit, top_score = ranked[0] if ranked else (None, 0.0)
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        if top_score >= ANSWER_THRESHOLD and top_score - runner_up >= ANSWER_MARGIN:
            return ("greeting" if top_unit["id"] == "sys.greeting" else "answer"), top_unit, ranked
        if top_score >= CLARIFY_THRESHOLD:
            return "clarify", None, ranked
        return "deflect", self.units["sys.out_of_scope"], ranked
