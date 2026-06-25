# Design: On-the-fly Presentation Profiles (mp6v.1 §5)

**Bead:** ti-6371  
**Designer:** tincan-iris/designer  
**Date:** 2026-06-25  
**Wireframes:** `iris-profiles-ux.excalidraw` / `iris-profiles-ux.png`

---

## Scope

Presentation profiles are **cosmetic-only** settings that change how iris speaks
to a caller — language, TTS voice selection, cadence (playback speed).  They
have zero effect on trust grants, permission gates, or handling rules.  Those
remain exclusively in the Brain / ADR-0005 trust model.

This design covers the **automated (screen / take-message) path** only.
Ride-along / golden-path calls are out of scope for v1.

---

## Resolution Chain

Priority order (highest first).  First hit wins; the profile is then locked for
the remainder of the call.

| Step | Source | Condition |
|------|--------|-----------|
| ① | Override key | Runtime key injected by operator tooling (e.g. A/B test fixture) |
| ② | Contact annotation | `PreferencesStore.get(contact_id, "lang")` matches a loaded language |
| ③ | Whisper detector | Single-utterance detection on utt-1; confidence ≥ threshold; lang in loaded set |
| ④ | Default | `Config.default_language` (operator config) |

**Lock semantics:**  
Profile is frozen at the end of utterance-1 processing.  No mid-call language
swap.  Cadence slow-mode (0.7×) is an exception: it applies per-turn when a
re-ask trigger fires, but does not change the locked language.

**ADR-0005 invariant:**  
Caller-ID spoofing may win a mismatched accent (chain step ②), but it can never
win additional permissions.  The trust gate stays in Brain.

---

## Five Wireframe Screens

### Screen 1 — Operator Config (`settings > voice profiles`)

Operator configures the language set and cadence defaults before calls arrive.

**Language set panel**
- Ordered checklist of available languages (2–5).  
- Order determines Whisper detection priority (step ③ evaluates top-to-bottom
  until one clears threshold).  
- Drag-to-reorder (or keyboard: focus + Space + arrow keys — see A11y below).  
- First checked language is the default fallback (chain step ④).

**Cadence panel**
- Default: 1.0×.  Range: 0.7× – 1.4×.  
- Slider; screen-reader announces value on change.  
- Callout note: re-ask trigger drops to 0.7× for that turn regardless.

**Save button** — persists to `Config`; takes effect on next incoming call (no
mid-call hot-reload in v1).

### Screen 2 — Automated Call: Detection In Progress

Shown on operator console while utterance-1 is being analysed.

- Caller utterance displayed verbatim.
- Detection panel shows Whisper confidence bars (color + bar width + % text — not
  color alone; WCAG 1.4.1).
- Resolution chain shows steps ①② as "none", step ③ as "running…" (spinner
  icon + text), step ④ as "en (fallback)".
- Status bar: amber "[WAIT] Detecting…  [voice]".

### Screen 3 — Profile Applied and Locked

Immediately after detection resolves.

- Caller utterance shown; iris reply shown with typing cursor (streamed).  
- Resolution chain: ① ② struck through in dim colour; ③ highlighted green with
  "✓ es (94%) ← ACTIVE" text on coloured background row.  
- Active profile block:  
  - Language: Spanish (es)  
  - TTS voice: es-MX-DaliaNeural  
  - Cadence: 1.0× (default)  
  - Source: detector · 🔒 LOCKED  
- Note: "No mid-call swap — profile stable for call duration."  
- Status bar: blue "[SPEAKING] [voice] · Español · 🔒"

### Screen 4 — Contact Annotation (`contacts > [name] > Preferences`)

Operator adds per-contact presentation preferences.

- Contact header: name, phone, handling rule, trust tier (read-only — trust is
  not set here).  
- Language dropdown (constrained to operator-loaded set).  
- Cadence dropdown (Slow 0.7× / Normal 1.0× / Fast 1.4×).  
- Save / Clear buttons.  
- Warning callout: "Cosmetic only — trust grants stay in ADR-0005."  
- Effect note: "Next call from this number → skips detector, applies saved
  settings (chain step ②)."

### Screen 5 — Resolution Chain Flowchart

Reference diagram for builders and PM review.

```
📞 Call starts
      │
      ▼
 ①  Override key? ──YES──▶ Apply + 🔒 LOCK
      │ NO
      ▼
 ②  Contact annotation? ──YES──▶ Apply + 🔒 LOCK
      │ NO
      ▼
 ③  Whisper detect ≥ threshold? ──HIT──▶ Apply + 🔒 LOCK
      │ MISS
      ▼
 ④  Default (operator config) ──────────▶ Apply + 🔒 LOCK
```

All four paths converge into `🔒 PROFILE LOCKED` (stable for call duration,
cosmetic only, trust gate unaffected).

Footnotes on diagram:
- ADR-0005 invariant: caller-ID spoofing wins the wrong accent, never
  permissions.
- Detector runs in Pipecat `ParallelPipeline` — concurrent with transcription,
  zero added latency.
- Re-ask trigger → slow mode (0.7×) for that turn only; language lock unchanged.

---

## A11y Audit — WCAG 2.1 AA

| Criterion | Element | Status | Notes |
|-----------|---------|--------|-------|
| 1.1.1 Non-text content | Confidence bars, status icons | PASS | Alt text / aria-label on each bar; status icons have adjacent text labels |
| 1.3.1 Info & relationships | Resolution chain list | PASS | Ordered `<ol>` with `<li>` items; active item has `aria-current="true"` |
| 1.3.3 Sensory characteristics | All callouts | PASS | Warnings use icon + text + border colour (not colour alone) |
| 1.4.1 Use of colour | Confidence bars, status bar | PASS | Bar width + % text + colour; status bar icon + text + colour |
| 1.4.3 Contrast (AA) | Catppuccin Mocha dark palette | PASS | Background #1e1e2e / text #cdd6f4: ratio ≈ 12:1.  Accent #89b4fa on dark: ≈ 5.5:1 |
| 1.4.11 Non-text contrast | Slider thumb, button borders | PASS | Slider thumb ≥ 3:1; button borders ≥ 3:1 against adjacent BG |
| 2.1.1 Keyboard | Drag-to-reorder language list | PASS | Focus + Space to grab, arrow keys to move, Space/Enter to drop; Esc to cancel |
| 2.1.1 Keyboard | All dropdowns and buttons | PASS | Standard `<select>` and `<button>` elements |
| 2.4.3 Focus order | Settings screen | PASS | Tab order: Language set → Cadence slider → Save |
| 2.4.6 Headings & labels | All panels | PASS | Panel titles as `<h2>`, field labels as `<label for=>` |
| 3.3.2 Labels or instructions | Cadence slider | PASS | "Re-ask trigger → drops to 0.7× for that turn" displayed below slider |
| 4.1.2 Name, role, value | Active profile LOCK badge | PASS | `aria-label="Profile locked for this call"` on lock icon |

**Builder note on LOCK badge:** render as `<span aria-label="Profile locked for this call" role="img">🔒</span>` alongside visible text "LOCKED" — the emoji alone fails 1.1.1.

---

## Builder Guidance

### New file: `iris/voice/profile_resolver.py`

```python
@dataclass
class PresentationProfile:
    language: str          # BCP-47 tag, e.g. "es"
    tts_voice: str         # Azure/edge-tts voice name
    cadence: float = 1.0   # 0.7 – 1.4; default 1.0
    source: str = "default"  # override|annotation|detector|default

class ProfileResolver:
    """Resolves presentation profile for a call, then locks it."""

    def resolve(
        self,
        contact_id: int,
        override_key: str | None,
        utterance_1_audio: bytes,
        config: Config,
        prefs: PreferencesStore,
    ) -> PresentationProfile:
        # ① Override key
        # ② Contact annotation  (prefs.get(contact_id, "lang"))
        # ③ Whisper single-utterance detection
        # ④ Default from config
        ...
```

### `iris/config.py` additions

```python
@dataclass(frozen=True)
class Config:
    ...
    language_set: list[str] = field(default_factory=lambda: ["en"])
    default_language: str = "en"
    cadence_default: float = 1.0
    cadence_slow: float = 0.7      # applied on re-ask trigger
    cadence_range: tuple[float, float] = (0.7, 1.4)
    language_detect_threshold: float = 0.80  # Whisper min confidence
```

### `iris/prefs.py` — existing, no changes required

`PreferencesStore.get(context, "lang")` and `.get(context, "cadence")` already
support the annotation keys needed for chain step ②.

### Pipecat integration

Detection (step ③) runs inside a `ParallelPipeline` alongside the first-utterance
transcription — zero added wall-clock latency before iris replies.  The resolver
is called synchronously after both streams complete (detection result + transcript
available together).

---

## Open Questions for PM

1. **Threshold tuning** — what Whisper confidence floor should ship as the default
   (`language_detect_threshold`)?  0.80 is the design default; operator may
   want to configure.

2. **Unknown-caller cadence annotation** — should `SENTINEL_CONTACT_ID = 0` support
   a cadence annotation for "all unknown callers"?  Not in scope for v1 per
   current design.

3. **Voice catalogue** — where does `tts_voice` mapping (language tag → Azure voice
   name) live?  Config file, DB table, or hardcoded lookup table?

4. **Re-ask trigger definition** — what exact Brain signal fires the per-turn
   cadence drop?  (Assumed: `intent.re_ask == True` from Tier-1 skill output.)
