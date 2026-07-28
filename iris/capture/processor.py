"""L1CaptureProcessor — deterministic hot-path fact extraction (ti-rnlqo.2.3)."""
from __future__ import annotations

import calendar
import re
from collections import deque
from datetime import date, datetime

import dateparser.search
import phonenumbers

from iris.capture.schemas import ActionItem, CapturedFact, ContactRoster, FactType

# ── CueId ─────────────────────────────────────────────────────────────────────

_CUE_WORD_RE = re.compile(
    r"\b(reference|confirmation|claim|ticket|case|order|policy|member|account)\b", re.IGNORECASE
)
_SECONDARY_CUE_TOKENS = frozenset({"number", "no", "code", "id", "identifier", "num"})
_CUE_ID_RE = re.compile(r"\b([A-Z0-9][A-Z0-9\-]{4,19})\b", re.IGNORECASE)

# Normalize spoken IDs: "R as in Romeo" → "R", "8 8 2 1 1" → "88211"
_NATO_RE = re.compile(r"\b(\w) as in \w+\b", re.IGNORECASE)
# Negative lookbehind for apostrophes prevents "that's R" from collapsing to "sR..."
_SPACED_SINGLE_RE = re.compile(r"(?<!['\w])([A-Z0-9])((?:\s+[A-Z0-9]){2,})(?!\w)", re.IGNORECASE)

# ── Phone ─────────────────────────────────────────────────────────────────────

_PHONE_SCAN_RE = re.compile(r"\d[\d\s\-\.]{6,14}\d")

# ── Amount ────────────────────────────────────────────────────────────────────

_AMOUNT_DIGIT_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d{1,2})?)"
    r"|([\d,]+(?:\.\d{1,2})?)\s+dollars?\b",
    re.IGNORECASE,
)

_NUM_WORD = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
    "forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million"
)
_SPOKEN_AMOUNT_RE = re.compile(
    rf"\b(?:a\s+)?(?:{_NUM_WORD})(?:[\s\-]+(?:{_NUM_WORD}))*(?:\s+dollars?)?\b",
    re.IGNORECASE,
)

_ONES: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "a": 1, "an": 1,
}
_MULTS: dict[str, int] = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_TENS = frozenset({"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"})

# ── Date ──────────────────────────────────────────────────────────────────────

_AT_TIME_RE = re.compile(r"(.+?)\s+at\s+(\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)\b", re.IGNORECASE)
_DOM_RE = re.compile(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.IGNORECASE)

# Dateparser is very aggressive — only keep results whose span contains a genuine
# date indicator (month name, weekday, relative word, or numeric date-like form).
_DATE_KEYWORD_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r"|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?"
    r"|sat(?:urday)?|sun(?:day)?"
    r"|today|tomorrow|yesterday|next|last|tonight|noon|midnight"
    r"|\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|\d{1,2}(?:st|nd|rd|th)"
    r"|\d{1,2}\s*(?:am|pm))\b",
    re.IGNORECASE,
)

# ── Action ────────────────────────────────────────────────────────────────────

_ACTION_RE = re.compile(
    r"\b(I(?:'ll| will)|Let\s+me|We(?:'ll| will))\b(.+?)(?=[.!?]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# ── Name ──────────────────────────────────────────────────────────────────────

_NAME_RE = re.compile(
    r"\b(?:my name is|I'm|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _normalize_spoken_id(text: str) -> str:
    text = _NATO_RE.sub(lambda m: m.group(1), text)
    text = _SPACED_SINGLE_RE.sub(lambda m: (m.group(1) + m.group(2)).replace(" ", ""), text)
    return text


def _words_to_number(words: list[str]) -> float | None:
    total = 0
    current = 0
    for word in words:
        w = word.lower()
        if w in _ONES:
            current += _ONES[w]
        elif w in _MULTS:
            if current == 0:
                current = 1
            current *= _MULTS[w]
            if _MULTS[w] >= 1000:
                total += current
                current = 0
        else:
            return None
    value = total + current
    return float(value) if value > 0 else None


def _spoken_to_amount(raw: str) -> float | None:
    """Convert a spoken dollar amount to float. 'forty-seven fifty' → 47.50."""
    text = re.sub(r"\bdollars?\b", "", raw, flags=re.IGNORECASE).strip()
    text = text.lower().replace("-", " ")
    words = [w for w in text.split() if w]
    if not words:
        return None
    # "forty seven fifty" → [forty, seven] whole dollars + [fifty] = $0.50 cents
    if len(words) >= 2 and words[-1] in _TENS:
        dollars = _words_to_number(words[:-1])
        if dollars is not None:
            return round(dollars + _ONES[words[-1]] / 100, 2)
    return _words_to_number(words)


def _roll_forward_dom(today: date, day: int) -> date | None:
    """Return the next date whose day-of-month is `day`, strictly after today."""
    year, month = today.year, today.month
    for _ in range(3):
        _, days_in_month = calendar.monthrange(year, month)
        if day <= days_in_month:
            candidate = date(year, month, day)
            if candidate > today:
                return candidate
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return None


def _mask_nondate_patterns(text: str) -> str:
    """Remove price and phone patterns that mislead dateparser."""
    text = re.sub(r"\$\s*[\d,]+(?:\.\d+)?", " ", text)
    text = re.sub(r"\d[\d\s\-\.]{6,14}\d", " ", text)
    return text


def _search_dates_with_fallback(
    text: str, settings: dict
) -> list[tuple[str, datetime]]:
    found = dateparser.search.search_dates(text, settings=settings) or []
    if found:
        return found
    # Fallback: split "next Tuesday at 2" → parse date part, inject time
    m = _AT_TIME_RE.search(text)
    if not m:
        return []
    date_text, time_str = m.group(1).strip(), m.group(2).strip()
    date_results = dateparser.search.search_dates(date_text, settings=settings) or []
    if not date_results:
        return []
    hour_m = re.match(r"^(\d{1,2})(?::(\d{2}))?(?:\s*([ap]m))?$", time_str, re.IGNORECASE)
    if not hour_m:
        return date_results
    hour = int(hour_m.group(1))
    minute = int(hour_m.group(2) or 0)
    period = (hour_m.group(3) or "").lower()
    if not period and 1 <= hour <= 7:
        hour += 12  # coerce bare 1–7 to PM (business hours)
    elif period == "pm" and hour != 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0
    return [
        (f"{s} at {time_str}", dt.replace(hour=hour % 24, minute=minute))
        for s, dt in date_results
    ]


# ── Processor ─────────────────────────────────────────────────────────────────

class L1CaptureProcessor:
    """Deterministic L1 extractor; no LLM, target ≤50 ms per turn."""

    def __init__(self, roster: ContactRoster | None = None, now: date | None = None) -> None:
        self.session_id: str = ""
        self._roster: ContactRoster = roster or frozenset()
        self._cue_ctx: deque[str] = deque(maxlen=2)
        self._now: date | None = now

    def process(
        self,
        text: str,
        speaker: str,
        turn_id: int,
        offset_s: float,
    ) -> list[CapturedFact | ActionItem]:
        try:
            dates = self._extract_dates(text, speaker, turn_id, offset_s)
            results: list[CapturedFact | ActionItem] = (
                self._extract_phones(text, speaker, turn_id, offset_s)
                + self._extract_cue_ids(text, speaker, turn_id, offset_s)
                + self._extract_amounts(text, speaker, turn_id, offset_s)
                + dates
                + self._extract_actions(text, speaker, turn_id, offset_s, dates)
                + self._extract_names(text, speaker, turn_id, offset_s)
            )
        except Exception:
            results = []
        self._cue_ctx.append(text)
        return results

    # ── private helpers ───────────────────────────────────────────────────────

    def _fact(
        self,
        fact_type: FactType,
        raw: str,
        value: str,
        speaker: str,
        turn_id: int,
        offset_s: float,
        confidence: float,
        critical: bool,
    ) -> CapturedFact:
        return CapturedFact(
            session_id=self.session_id,
            fact_type=fact_type,
            raw_text=raw,
            normalized_value=value,
            transcript_turn_id=turn_id,
            transcript_offset_s=offset_s,
            speaker=speaker,
            confidence=confidence,
            critical=critical,
        )

    def _extract_phones(
        self, text: str, speaker: str, turn_id: int, offset_s: float
    ) -> list[CapturedFact]:
        results = []
        for m in _PHONE_SCAN_RE.finditer(text):
            raw = m.group(0)
            stripped = re.sub(r"[\s\-\.]", "", raw)
            try:
                phone = phonenumbers.parse(stripped, "US")
                if phonenumbers.is_valid_number(phone):
                    e164 = phonenumbers.format_number(
                        phone, phonenumbers.PhoneNumberFormat.E164
                    )
                    results.append(self._fact(
                        FactType.PHONE, raw, e164, speaker, turn_id, offset_s,
                        confidence=0.9, critical=e164 not in self._roster,
                    ))
            except Exception:
                pass
        return results

    def _extract_cue_ids(
        self, text: str, speaker: str, turn_id: int, offset_s: float
    ) -> list[CapturedFact]:
        has_cue = bool(_CUE_WORD_RE.search(text)) or any(
            _CUE_WORD_RE.search(c) for c in self._cue_ctx
        )
        if not has_cue:
            return []
        normalized = _normalize_spoken_id(text).upper()
        seen: set[str] = set()
        results = []
        for m in _CUE_ID_RE.finditer(normalized):
            candidate = m.group(1)
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.lower() in _SECONDARY_CUE_TOKENS:
                continue
            if not re.search(r"\d", candidate):  # require ≥1 digit
                continue
            if re.fullmatch(r"[\d\-]+", candidate):  # skip pure-numeric
                continue
            results.append(self._fact(
                FactType.CASE_ID, candidate, candidate, speaker, turn_id, offset_s,
                confidence=0.95, critical=True,
            ))
        return results

    def _extract_amounts(
        self, text: str, speaker: str, turn_id: int, offset_s: float
    ) -> list[CapturedFact]:
        seen: set[str] = set()
        results = []

        for m in _AMOUNT_DIGIT_RE.finditer(text):
            raw = m.group(0).strip()
            value_str = (m.group(1) or m.group(2)).replace(",", "")
            try:
                value = float(value_str)
            except ValueError:
                continue
            normalized = f"${value:.2f}"
            if normalized in seen:
                continue
            seen.add(normalized)
            results.append(self._fact(
                FactType.AMOUNT, raw, normalized, speaker, turn_id, offset_s,
                confidence=0.9, critical=True,
            ))

        for m in _SPOKEN_AMOUNT_RE.finditer(text):
            raw = m.group(0).strip()
            # Require ≥2 number words, or explicit "dollars", to reduce noise
            num_words = re.split(r"[\s\-]+", re.sub(r"\bdollars?\b", "", raw, flags=re.IGNORECASE).strip())
            num_words = [w for w in num_words if w and w.lower() not in ("a", "an")]
            has_dollars = bool(re.search(r"\bdollars?\b", raw, re.IGNORECASE))
            if len(num_words) < 2 and not has_dollars:
                continue
            value = _spoken_to_amount(raw)
            if value is None or value <= 0:
                continue
            normalized = f"${value:.2f}"
            if normalized in seen:
                continue
            seen.add(normalized)
            results.append(self._fact(
                FactType.AMOUNT, raw, normalized, speaker, turn_id, offset_s,
                confidence=0.9, critical=True,
            ))

        return results

    def _extract_dates(
        self, text: str, speaker: str, turn_id: int, offset_s: float
    ) -> list[CapturedFact]:
        today = self._now or date.today()
        settings = {
            "RETURN_TIME_AS_PERIOD": True,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.combine(today, datetime.min.time()),
        }
        masked = _mask_nondate_patterns(text)
        found = _search_dates_with_fallback(masked, settings)
        seen: set[str] = set()
        results = []
        for span, dt in found:
            # Reject spans that don't contain a genuine date indicator word
            if not _DATE_KEYWORD_RE.search(span):
                continue
            parsed = dt.date() if hasattr(dt, "date") else dt
            if parsed == today:
                continue
            if parsed < today:
                dom_m = _DOM_RE.search(span)
                if dom_m:
                    rolled = _roll_forward_dom(today, int(dom_m.group(1)))
                    if rolled:
                        parsed = rolled
                    else:
                        continue
                else:
                    continue
            iso = parsed.strftime("%Y-%m-%d")
            if iso in seen:
                continue
            seen.add(iso)
            results.append(self._fact(
                FactType.DATE, span, iso, speaker, turn_id, offset_s,
                confidence=0.8, critical=(parsed - today).days > 7,
            ))
        return results

    def _extract_actions(
        self,
        text: str,
        speaker: str,
        turn_id: int,
        offset_s: float,
        date_facts: list[CapturedFact],
    ) -> list[ActionItem]:
        due = date_facts[0].normalized_value if date_facts else None
        results = []
        for m in _ACTION_RE.finditer(text):
            results.append(ActionItem(
                session_id=self.session_id,
                description=text,
                trigger=m.group(0).strip(),
                owner=speaker,
                transcript_turn_id=turn_id,
                transcript_offset_s=offset_s,
                speaker=speaker,
                confidence=0.85,
                due_date=due,
            ))
        return results

    def _extract_names(
        self, text: str, speaker: str, turn_id: int, offset_s: float
    ) -> list[CapturedFact]:
        if speaker != "far":
            return []
        results = []
        for m in _NAME_RE.finditer(text):
            results.append(self._fact(
                FactType.NAME, m.group(0), m.group(1).strip(), speaker, turn_id, offset_s,
                confidence=0.7, critical=False,
            ))
        return results
