# Call Card (DURING, v1 silent) — Decisions + Fact Catalog

> Working doc from the cohelper + operator design session, 2026-06-30.
> Companion to the architect's `ti-rnlqo` strawman. Purpose of the catalog
> (operator's ask): enumerate the **facts iris catches during a live call**, so
> we know what to build and — explicitly — **what to test and how**.
>
> Grounding: dossier §2B / §3 / §F (`docs/research/call-aversion-dossier.md`),
> the `iris/console/ride_along.py` v0 detection prototypes, and the `ti-rnlqo`
> data model (`CapturedFact` / `ActionItem`).

---

## Part 1 — Decisions locked this session

These refine (and in two places overrule) the architect's strawman.

1. **Disclosure is always attempted, never gated, never acknowledged.**
   - iris **always** introduces itself / surfaces the disclosure at `call_connected`
     — every call, by default. Rationale (operator): if this is ever audited, the
     behavior we ship is the one we're most confident *had* to happen. Open source
     means anyone can change it; we ship the always-disclose default.
   - Disclosure is a **one-way notice**, modeled on "this call may be recorded for
     quality…" / a EULA: the notice must be *delivered*; the far party's choice to
     continue is implicit consent. We do **not** require far-party acknowledgement,
     and we do **not** require operator acknowledgement to begin capture. Capture is
     ungated (this matches the strawman's "reminder, not a gate").
   - We **do** record **`disclosed_at`** (timestamp the operator marked it said, or
     iris played `disclosure.wav`) — purely the operator's own audit trail, carried
     into the AFTER summary. (Reuse the strawman's `disclosure_ack` field, renamed.)
   - *(Not legal advice; Tim is trusted but not a lawyer. This is the operator's
     call and the "implied-consent-on-continue" standing is sound.)*

2. **Confidence is a coarse bucket + a "CHECK THIS" flag, not float precision.**
   - Surface `high / medium / low` (e.g. low on a bad connection is genuinely
     useful), **not** `0.25357`. For always-critical facts we may render **no**
     number at all — the "CHECK THIS" flag is the real signal.
   - The value is helping the human realize *"verify this one"* — confidence is UX,
     not telemetry.

3. **First build is a representative vertical slice, not a spike.**
   - It rides the **production** daemon / store / DaemonAPI / console — not a throwaway
     POC on different infra. (Confirmed: dual-channel speaker-tagged capture already
     exists — `StreamingTranscriber` tags `"far"` vs operator, `endpoint.far_source`
     is the SCO downlink, `ride_along.on_transcript(text, speaker)` already branches.
     So FR-01 is reuse, not new risk.)
   - **Slice 1:** on a real call, iris silently catches a **reference/case number**
     (cue-anchored), renders it as a real CriticalFactCard, operator confirms it —
     end to end. Thin cut across `ti-rnlqo.1` (store: CALL_CARD + CAPTURED_FACT only),
     `.2` (**only** the CueIdExtractor), `.3` (CaptureSession/Host on the real daemon),
     `.4` (`call_card_fact` event + `confirm_fact` cmd), `.6` (DisclosureCard +
     CriticalFactCard + confirm). **Deferred as additive follow-ons:** `.5` the whole
     post-call enricher; the other extractors; inline edit; tap-to-replay seek.

---

## Part 2 — Fact Catalog

**Legend**
- **Layer** — `L1` deterministic on-device hot path (≤50 ms, no LLM); `L3` post-call LLM enrichment; `L1→L3` seeded live, completed post-call.
- **Critical?** — flagged "CHECK THIS" for operator confirmation. A wrong value here
  reintroduces the dread iris exists to remove (dossier §3: *"a confidently wrong
  confirmation number is worse than no number"*).
- **STT-fragile?** — token class STT mangles (numbers / IDs / names / dates): 8–12%
  error on real audio, a transposed digit is unrecoverable → **read-back is mandatory
  regardless of how good the extractor is.**
- **Unit-testable?** — coverable with a deterministic **text** fixture (no audio, no
  LLM)? This is the column that tells us our automated-test surface vs. what needs an
  audio/LLM eval harness.

### Tier A — Hard data (L1 deterministic, high precision)

| Fact | Spoken example | Cue / method | Normalize to | Layer | Critical? | STT-fragile? | Unit-testable? |
|---|---|---|---|---|---|---|---|
| **reference/case/claim/ticket/order/policy/member/account ID** | "your reference number is R as in Romeo, 8-8-2-1-1" | **cue-word anchored** regex (`reference\|confirmation\|claim\|ticket\|case\|order\|policy\|member\|account` + num/#/code) on the same or prior turn | upper-case, strip filler | L1 | **Always** | **Yes** | **Yes** — the cue-anchoring logic is pure text |
| **amount / money** | "that'll be forty-seven fifty" / "a $47.50 charge" | regex `$\s*[\d,]+(\.\d{2})?` + `\d+ dollars?`; spoken-number → value | decimal + currency | L1 | **Always** | Yes | **Yes** (incl. word→number cases) |
| **date / time / deadline** | "we'll have it resolved by Friday" / "the 15th" | **`dateparser`** (relative expressions — beats regex *and* LLM on "by Friday") | ISO date, **vs a fixed reference `now`** | L1 | Yes if a deadline or >7 days out | Medium | **Yes** — pin a reference date so tests are deterministic |
| **phone** | "call me back at 415-555-1234" | **`phonenumbers`** (libphonenumber; returns offsets) | E.164 | L1 | Yes if not in roster | **Yes** | **Yes** |
| **email** | "send it to j dot smith at gmail dot com" | regex + spoken-form normalizer ("dot"/"at") | canonical address | L1 | No (but verify spelling) | **Yes** (spoken emails mangle) | **Yes** — note spoken-form parsing is its own case set |
| **postal address** | "ship to 123 Main Street" | street-suffix regex (`_ADDRESS_RE` prototype) | freeform string | L1 | No | Medium | **Yes** |

### Tier B — Commitments & next steps (L1 pattern → L3 completion)

| Fact | Spoken example | Cue / method | Captures | Layer | Critical? | Unit-testable? |
|---|---|---|---|---|---|---|
| **action item** | "I'll email you the form today" | `I'll/I will/Let me/We'll` + verb (`_ACTION_RE` prototype) | description, **owner = speaker channel**, due_date (via date extractor) | L1→L3 | No (confirm) | Pattern: **Yes**; owner/completeness: **L3 eval** |
| **commitment / promise made to you** | "we'll waive the fee this once" | commitment verbs; the §B `prior_commitments` moat ("rep X promised Y") | who promised, what, when | L1→L3 | Yes (it's what AFTER writes back) | Pattern: partial; semantic: **L3** |
| **scheduling / appointment** | "let's say Tuesday at 2" | weekday / "at noon\|N pm" / "the Nth" (`detect_commitment` prototype) | datetime | L1 | Yes | **Yes** |

### Tier C — Relational & semantic (L1 seed → L3 / NER)

| Fact | Spoken example | Cue / method | Layer | Critical? | Unit-testable? |
|---|---|---|---|---|---|
| **rep / agent name** | "my name is Karen, I'm in billing" | `my name is / this is / you're speaking with / I'm [X]`; NER post-call | L1→L3 | No (but key to the prior-commitment loop) | Pattern: **Yes**; NER + **non-Western-name attribution: explicit eval** (dossier §3 name-bias mandate) |
| **company / department / role** | "this is the claims department" | pattern + L3 | L1→L3 | No | Partial |
| **contradiction / discrepancy flag** | "wait — I thought you said it was already refunded" | `_FLAG_RE` prototype ("thought you said", "you told me earlier") | L1 | Surfaces a CHECK | **Yes** |
| **prior-commitment match** (cross-call) | (vs. stored "last rep promised a refund by the 1st") | match new turns against the notes store | L3 / logic | Yes | **Yes** with seeded-store fixtures |
| **escalation / "too angry to be effective" cue** | (sustained anger markers) | dossier §5 anger lever | L3 | — | **Deferred** — belongs to the anger/handoff phase, *not* v1 silent |

---

## Part 3 — What this means for testing (the operator's ask)

**Unit-testable today, no audio, no LLM** — every L1 extractor against **spoken-text
fixtures**. This is the bulk of our automated surface and the slice-1 acceptance set:

| # | Fixture utterance (speaker) | Expected fact |
|---|---|---|
| 1 | far: "your confirmation number is REF-88211" | `case_id = REF-88211`, critical |
| 2 | far: "reference number, that's R-as-in-Romeo 8 8 2 1 1" | `case_id = R88211` (cue-anchored across spelled digits) |
| 3 | far: "the total comes to forty-seven fifty" | `amount = 47.50` |
| 4 | far: "there's a $129.00 cancellation fee" | `amount = 129.00`, critical |
| 5 | op: "I'll call you back by Friday" | `action_item{owner=operator, due=<next Fri>}` |
| 6 | far: "we'll have a tech out next Tuesday at 2" | `appointment = <Tue> 14:00` |
| 7 | far: "you can reach me at 415-555-1234" | `phone = +14155551234` |
| 8 | far: "my name is Karen from billing" | `name = Karen`, `dept = billing` |
| 9 | op: "wait, I thought you said it was already refunded" | `flag = contradiction` |
| 10 | far: "send the form to help dot desk at acme dot com" | `email = helpdesk@acme.com` |

**Needs an audio / LLM eval harness (cannot be a pure unit test)** — and these are the
ones that actually decide product trust:
- **STT accuracy on the fragile tokens** (IDs/numbers/names/dates). Needs audio
  fixtures + a WER-on-critical-tokens check. Mitigations are mandatory, not optional:
  **read critical numbers back**, and **bias the STT with expected vocab** (operator
  name, the company being called, likely ID formats) — dossier §3 says biasing beats
  any post-hoc regex.
- **L3 ownership attribution + completeness** — transcript fixtures + an LLM judge;
  must include **non-Western names** explicitly.
- **The verification loop end to end** — capture → CriticalFactCard → `confirm_fact`
  → confirmed state — an integration test on the real daemon (this *is* slice 1).

**Cross-cutting:** every fact carries `transcript_turn_id` + `transcript_offset_s`
provenance from day one (tap-to-replay), and every item renders as an **editable**
suggestion. These aren't per-fact — they're invariants of the store + UI.
