"""Deterministic, explainable suggestions. Ranking alone never approves a link."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import PurePosixPath


_EDITION_RULES = [
    (r"\bod\s*&\s*d\b|\boriginal dungeons (?:and|&) dragons\b", {"OD&D"}),
    (r"\bb\s*/\s*x\b|\b(?:becmi|basic d&d|d&d basic|basic)\b", {"Basic"}),
    (r"\b(?:1e|1st[ -]+ed(?:ition)?|first edition)\b", {"AD&D 1e"}),
    (r"\b(?:2e|2nd[ -]+ed(?:ition)?|second edition)\b", {"AD&D 2e"}),
    (r"\bv?3[._ ]5\b", {"3.5"}),
    (r"\bv?3[._ ]0\b", {"3.0"}),
    (r"\b(?:4e|4th[ -]+ed(?:ition)?|fourth edition)\b", {"4e"}),
    (r"\b(?:5e|5th[ -]+ed(?:ition)?|fifth edition)\b", {"5e (2014)", "5e (2024)"}),
]
_YEAR = re.compile(r"(?<!\w)(?:19[7-9]\d|20\d{2})(?!\w)")
_EXTRA = re.compile(r"\b(?:maps?|handouts?|errata|character sheets?|(?:part|disc) [0-9]+)\b")
_JUNK_META = re.compile(r"^(?:untitled|document\d*|scan(?:ner)?|adobe acrobat|microsoft (?:word|office))\b")
_NOISE = re.compile(r"\b(?:d and d|ad and d|dungeons and dragons|tsr|wotc|wizards of the coast|ocr|scanned|scan|pdf|retail|digital|drive thru rpg|drivethrurpg|dms guild)\b")
_MARKED_NUMBER = re.compile(r"(?<!\w)(?:(?:tsr|wotc|sku|code)[\s:#-]*|#\s*)\d+(?!\w)", re.I)


def normalize(text: str) -> str:
    text = re.sub(r"(?<=\w)_s(?=[_\W]|$)", "s", text, flags=re.I)
    text = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", text)
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", re.sub(r"['’]", "", text).replace("&", " and ")).split())


def _years(text: str) -> set[int]:
    text = _MARKED_NUMBER.sub(" ", text)
    return {int(year) for year in _YEAR.findall(text.replace("_", " "))}


def _editions(text: str, *, folder: bool = False) -> set[str]:
    text = text.casefold().replace("_", " ")
    found = set().union(*(editions for pattern, editions in _EDITION_RULES
                          if re.search(pattern, text) and (folder or text.strip() != "basic")))
    modern = {"5e (2014)", "5e (2024)"}
    years = _years(text)
    if found & modern or not found:
        if len(years & {2014, 2024}) == 1:
            found = (found - modern) | {f"5e ({next(iter(years & {2014, 2024}))})"}
    return found


def _isbn(text: str) -> str:
    value = re.sub(r"[\s-]", "", text).upper()
    if re.fullmatch(r"[0-9]{9}[0-9X]", value):
        return value if sum((10 - i) * (10 if c == "X" else int(c))
                            for i, c in enumerate(value)) % 11 == 0 else ""
    if re.fullmatch(r"97[89][0-9]{10}", value):
        return value if sum((1 if i % 2 == 0 else 3) * int(c)
                            for i, c in enumerate(value)) % 10 == 0 else ""
    return ""


def _isbn_pattern(value: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + r"[\s-]*".join(value) + r"(?!\w)", re.I)


def _code_pattern(code: str) -> re.Pattern[str]:
    # Allow TSR 9034, TSR9034, and GAZ-1 without accepting B2 inside B20.
    code = re.sub(r"[\W_]", "", code)
    parts = re.findall(r"[a-z]+|\d+", code, re.I)
    return re.compile(r"(?<!\w)(?:(tsr|wotc|sku|code|#)[\s:#-]*)?"
                      + r"[\s-]*".join(parts) + r"(?!\w)", re.I)


def _clean(text: str) -> str:
    text = re.sub(r"(?<=\w)_s(?=[_\W]|$)", "s", text, flags=re.I).replace("_", " ")
    for pattern, _ in _EDITION_RULES:
        if pattern != _EDITION_RULES[1][0]:
            text = re.sub(pattern, " ", text, flags=re.I)
    text = _YEAR.sub(" ", _MARKED_NUMBER.sub(" ", text))
    return " ".join(_NOISE.sub(" ", normalize(text)).split())


@dataclass(frozen=True)
class Release:
    id: str
    work_id: str
    title: str
    edition: str
    year: int | None
    label: str | None
    kind: str
    primary: bool
    linked: bool
    product_code: str | None = None
    isbn: str | None = None
    modules: tuple[str, ...] = ()


@dataclass
class Candidate:
    release: Release
    score: float
    reasons: list[str]
    strong: bool
    printing_evidence: int


@dataclass
class Match:
    tier: str
    candidates: list[Candidate]
    query: str
    note: str | None = None


class Matcher:
    def __init__(self, releases: list[Release]):
        self.releases = releases
        self.variants = Counter(r.work_id for r in releases)
        self.titles = {}
        self.codes = {}
        self.isbns = {}
        for r in releases:
            titles = {normalize(r.title), _clean(r.title)} - {""}
            self.codes[r.id] = [(code, _code_pattern(code)) for code in
                                filter(None, (r.product_code, *r.modules)) if re.search(r"[a-z0-9]", code, re.I)]
            for _, pattern in self.codes[r.id]:
                titles.add(_clean(pattern.sub(" ", r.title, count=1)))
            self.titles[r.id] = [(title, set(title.split())) for title in sorted(titles - {""})]
            value = _isbn(r.isbn or "")
            self.isbns[r.id] = _isbn_pattern(value) if value else None
        unique_titles = {normalize(r.title) for r in releases}
        counts = Counter(token for title in unique_titles for token in set(title.split()))
        self.weights = {word: 1 + math.log((len(unique_titles) + 1) / (count + 1))
                        for word, count in counts.items()}

    def _weight(self, words: set[str]) -> float:
        return sum(self.weights.get(word, 1) for word in sorted(words))

    def _similarity(self, forms: set[str], titles: list[tuple[str, set[str]]]) -> tuple[float, bool]:
        if not forms:
            return 0, False
        if any(title in forms for title, _ in titles):
            return 1, True
        best = 0.0
        for form in sorted(forms):
            words = set(form.split())
            for title, tokens in titles:
                common = words & tokens
                if common:
                    best = max(best, 2 * self._weight(common) / (self._weight(words) + self._weight(tokens)))
                if (common or (len(words) == len(tokens) == 1 and len(title) >= 5
                               and title[:1] == form[:1])) and min(len(form), len(title)) >= 5:
                    if best >= .45 or not common:
                        best = max(best, .92 * SequenceMatcher(None, form, title, autojunk=False).ratio())
        return best, False

    def match(self, relative: str, metadata_title: str | None = None) -> Match:
        path = PurePosixPath(relative)
        stem = path.stem
        filename = stem.replace("_", " ")
        normalized = normalize(stem)
        clean = _clean(stem)
        name_forms = {clean, normalized} - {""}
        all_edition_hints = [(segment, hints) for i, segment in enumerate((stem, *reversed(path.parts[:-1])))
                             if (hints := _editions(segment, folder=i > 0))]
        editions = set.intersection(*(hint for _, hint in all_edition_hints)) if all_edition_hints else set()
        contradictory_editions = bool(all_edition_hints) and not editions
        years = _years(filename)
        metadata = normalize(metadata_title or "")
        meta_forms = ({metadata, _clean(metadata_title or "")} - {""}
                      if metadata and metadata != normalized and not _JUNK_META.match(metadata) else set())
        if _EXTRA.fullmatch(normalized) and not meta_forms:
            return Match("none", [], clean)
        extra = bool(_EXTRA.search(normalized))
        ranked: list[Candidate] = []
        filename_exact_works, metadata_exact_works, identifier_works = set(), set(), set()

        for r in self.releases:
            forms = name_forms.copy()
            evidence, remainders = [], []
            isbn = self.isbns[r.id]
            isbn_hit = bool(isbn and isbn.search(filename))
            if isbn_hit and isbn is not None:
                remainders.append(isbn.sub(" ", filename))
            for code, pattern in self.codes[r.id]:
                hit = pattern.search(filename)
                if hit:
                    remainders += [pattern.sub(" ", filename), pattern.sub(" ", clean)]
                    marked = bool(hit[1])
                    weak = (code.isdigit() and (len(code) < 4 or int(code) in years)) or len(code) <= 2
                    if marked or not weak:
                        evidence.append(code)
            forms.update(form for rest in remainders if (form := _clean(rest)))
            filename_score, filename_exact = self._similarity(forms, self.titles[r.id])
            meta_score, meta_exact = self._similarity(meta_forms, self.titles[r.id])
            if filename_exact:
                filename_exact_works.add(r.work_id)
            if meta_exact:
                metadata_exact_works.add(r.work_id)
            if isbn_hit or evidence:
                identifier_works.add(r.work_id)
            title_score = max(filename_score, .94 * meta_score)
            if title_score < .63 and not (isbn_hit or evidence):
                continue
            reasons = []
            if filename_score >= .63:
                reasons.append("Exact filename title" if filename_exact else "Similar filename title")
            if meta_score >= .70:
                reasons.append("PDF metadata title")
            if isbn_hit:
                reasons.append(f"ISBN {r.isbn}")
            reasons.extend(f"Code {code}" for code in evidence)
            edition_match = r.edition in editions
            edition_conflict = bool(editions and not edition_match) or contradictory_editions
            if edition_match:
                reasons.append(f"Edition: {r.edition}")
            if edition_conflict:
                reasons.append("Conflicting edition clues")
            year_match = r.year in years
            if year_match:
                reasons.append(f"Year {r.year}")
            kind = normalize(r.kind)
            kind_match = kind != "original" and bool(re.search(rf"\b{re.escape(kind)}\b", normalized))
            if kind_match:
                reasons.append(r.kind)
            label = normalize(r.label or "")
            label_match = len(label) >= 5 and bool(re.search(rf"\b{re.escape(label)}\b", normalized))
            if label_match:
                reasons.append("Printing label")
            printing = 4 * isbn_hit + 2 * bool(r.product_code in evidence) + 2 * label_match + year_match + kind_match
            score = (title_score * 100 + 45 * isbn_hit + 22 * bool(evidence) + 17 * edition_match
                     - 24 * edition_conflict + 9 * year_match + 8 * kind_match + 8 * label_match)
            strong = not edition_conflict and (isbn_hit or filename_exact or bool(evidence and title_score >= .75))
            ranked.append(Candidate(r, score, reasons, strong, printing))

        ranked.sort(key=lambda c: (-c.score, -c.release.primary, c.release.year or 9999, c.release.id))
        if not ranked:
            return Match("none", [], clean)
        top = ranked[0]
        r = top.release
        runner_up = next((c for c in ranked if c.release.work_id != r.work_id), None)
        other_printing = next((c for c in ranked[1:] if c.release.work_id == r.work_id), None)
        ambiguous_printing = self.variants[r.work_id] > 1 and (
            not top.printing_evidence or (other_printing is not None
                                          and top.printing_evidence <= other_printing.printing_evidence))
        conflicting_titles = bool(
            (filename_exact_works and r.work_id not in filename_exact_works)
            or (metadata_exact_works and r.work_id not in metadata_exact_works)
            or (identifier_works and r.work_id not in identifier_works)
        )
        note = None
        if r.linked:
            note = "Best match already has a linked PDF."
        elif extra:
            note = "Filename may describe a supplement or part, not the whole book."
        elif conflicting_titles:
            note = "Title and identifier clues point to different books."
        elif ambiguous_printing:
            note = "Check which printing this PDF represents."
        confident = (top.strong and not note and (runner_up is None or top.score - runner_up.score >= 14))
        return Match("ready" if confident else "review", ranked[:8], clean, note)
