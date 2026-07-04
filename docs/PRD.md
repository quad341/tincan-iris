# PRD: Call Card v1 — AFTER: post-call writeback + compounding loop (ti-tr1m5)

**Status:** Draft — routed to architecture + design
**Source bead:** ti-tr1m5
**Author:** planner
**Date:** 2026-07-04

## Problem statement

Today, everything Call Card captures during a call (facts, action items, the
transcript) is scoped to that single call's ephemeral record
(`iris/capture/store.py`: `call_cards` / `captured_facts` / `action_items`,
keyed by `session_id`) and never survives to the next call with the same
contact. The BEFORE stage (`ti-ipx8v`) has nothing durable to read, so it
can't pre-populate "facts at your fingertips," and a promise the other party
made ("we'll process the refund by Friday") is invisible by the time the
operator calls back.

This defeats Call Card's central thesis (the "compounding moat" —
memory `iris-callcard-plan`): iris should get more useful with every call to
the same person or organization, not reset to zero each time.

**Who:** the call-averse operator (north-star: `iris-target-user-call-averse`),
both right after a call ends (rumination-puncture) and on the *next* call to
the same contact (compounding recall).

**Impact:** without this, DURING's capture work (`ti-rnlqo`, shipped) is a
dead end — captured facts and commitments are thrown away at call end instead
of compounding. This is also the explicit prerequisite for `ti-ipx8v`
(BEFORE), which depends on this bead.

A detailed design already exists and was resolved with the operator on
2026-06-30: `docs/designs/call-card-after-stage.md`. All decisions in its §7
are marked resolved. This PRD translates that design into PM-formal scope,
requirements, and — critically — checks its assumptions against the code as
it stands today (several have drifted; see Technical constraints).

## Goals

- **G1:** Every call, ungated, produces a durable raw record (an encrypted
  STT eval log + a `call_log` row) — "record, then verify, lose nothing." A
  laptop-closed-mid-call or skipped-review call loses nothing.
- **G2:** Operator-confirmed facts and commitments compound into durable,
  contact-keyed memory (`contact_fact`, `commitment`) that BEFORE can read on
  the next call to the same contact.
- **G3:** Operator sees an objective post-call recap (rumination-puncture)
  and a "from this call…" delta view of exactly what got added to the
  contact's record.
- **G4 (measurable):** on the next call to a contact with an open
  commitment, the operator is shown that commitment (e.g. "last call Jun 30 —
  Karen promised a refund by Jul 3") without manually searching history.

## Non-goals

- Proactive due-date nudges, automatic commitment resolution, or
  affective-forecasting coaching — deferred to AFTER.2 (design doc §1).
- A new "remind the operator" mechanism for their own promises — v1 just
  records `i_promised` items into the existing NotesStore follow-up
  lifecycle; no new reminder infrastructure.
- Richer promotion heuristics beyond the fixed durable-identity `fact_type`
  list — v1 uses a fixed mapping, not a learned/configurable one.
- Any change to DURING's capture behavior itself (`ti-rnlqo` is closed and
  out of scope here) beyond the read-only seams it already exposes.

## User stories

1. As the operator, right after I hang up, I want an objective recap of what
   was said/agreed, so I stop replaying the call wondering if I messed up or
   misheard something.
2. As the operator, I want facts and promises I confirmed to be remembered
   against that contact, so next call iris already has the account number,
   the case ID, and what was promised.
3. As the operator, I want to see exactly what this call added to a
   contact's record, so I can trust — and correct — what iris is compounding.
4. As the operator, if I close the laptop mid-call or skip the post-call
   review entirely, I want the raw record (that the call happened, roughly
   what was said) to still exist — nothing should depend on me finishing a
   review step.
5. As the operator calling the same organization again, I want to be told
   "last time, X promised Y by Z — did that happen?" so I can hold them to
   it, and a broken promise should read back as leverage, not just history.

## Functional requirements

Priority: P0 is the core compounding loop end-to-end; P1 materially improves
it; P2 is polish deferred if needed.

**FR1 (P0) — Always-on raw record, ungated.**
- AC: every call produces a `call_log` row and an encrypted STT eval log
  entry, regardless of whether the operator ever opens the post-call review
  or the app crashes/closes mid-call.
- AC: the STT eval log is write-only from the live system's point of view —
  no in-app or normal-operation read path exists (design doc §2.1, §7-A).

**FR2 (P0) — Post-call recap (rumination-puncture).**
- AC: an `outcome_summary` is generated via an LLM pass and shown to the
  operator immediately after call end.
- AC: every value the recap surfaces traces back to a captured/confirmed
  fact or action item for that session — the model restates, it does not
  re-extract or invent (design doc §7-C).
- AC: this LLM call is gated by the same opt-in mechanism
  `iris/capture/enricher.py`'s `PostCallEnricher` already uses
  (`cfg.anthropic_api_key` / `cfg.call_card.anthropic_api_key` /
  `IRIS_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY`) — no new, separately-gated
  cloud-egress path.

**FR3 (P0) — Confirmed writeback ("Save to [Contact]").**
- AC: confirmed action items become `commitment` rows —
  `direction='they_promised'` when `ActionItem.owner=='far'`,
  `'i_promised'` when `owner=='operator'` (existing field, `iris/capture/schemas.py`).
- AC: confirmed durable-identity facts upsert into `contact_fact`, keyed by
  `(contact_id, fact_type, normalized_value)` — a repeat capture updates
  `last_confirmed_at` rather than duplicating.
- AC: every `i_promised` commitment also lands in the existing NotesStore
  follow-up lifecycle (`iris/notes.py`) — no new reminder mechanism.
- AC: the raw floor (FR1) is never gated by this step; only
  `commitment`/`contact_fact` promotion requires `confirmed=1`.

**FR4 (P0) — "From this call…" delta view.**
- AC: after confirmation, the operator sees a plain list of what this call
  added to the contact's record — new/updated `contact_fact`s, new
  `commitment`s (direction + due date), and the `call_log` entry — each
  tagged verified/unverified (design doc §3.1).

**FR5 (P0) — BEFORE-facing read surface.**
- AC: `contact_fact` (by `contact_id`) and `commitment WHERE status='open'`
  are queryable in a form `ti-ipx8v` can consume directly for "facts at your
  fingertips" and open-commitment surfacing.

**FR6 (P1) — Commitment resolution.**
- AC: operator can mark an open commitment `honored`/`broken`.
- AC: a `broken` commitment is available as the literal opening line for the
  next call to that contact (design doc §4).

## Non-functional requirements

- **NFR1 (privacy/security — highest stakes in this bead):** the STT eval
  log holds full call transcripts for lines that can be medical, financial,
  or legal — ARCHITECTURE.md's local-first/never-egress-without-opt-in
  principle applies at its strictest here. The write-only,
  asymmetric-encryption design (§2.1, §7-A: daemon can append, cannot read;
  private key lives offline) is not optional polish — it is the mechanism
  that makes this store safe to have at all. This is a **net-new crypto
  component**; the architect must specify the actual algorithm/library, key
  provisioning/rotation, and on-disk format rather than leaving "encrypt it"
  unresolved.
- **NFR2 (no cloud-egress regression):** the recap LLM pass must degrade
  gracefully (skip the recap, or an equivalent non-cloud fallback) when no
  Anthropic key is configured — never silently call out where
  `PostCallEnricher` would have skipped.
- **NFR3 (data integrity):** a wrong value that compounds (a mis-transcribed
  account number, say) poisons every future call's prep — the worst version
  of iris's core failure mode (design doc §6). Promotion to `contact_fact`/
  `commitment` must be gated strictly on `confirmed=1`; provenance
  (`transcript_turn_id`, `transcript_offset_s`) must survive end-to-end so a
  compounded value stays tap-to-replay-able a call later.
- **NFR4 (contact identity stability):** all writeback keys on
  `contacts.id` (integer roster identity) — never a phone string — matching
  the existing FK pattern (`contact_addresses.contact_id`, `iris/roster.py`).
- **NFR5 (zero added core deps):** any new dependency (e.g. a crypto
  library for the eval log) must go into the `call-card` optional extra,
  preserving the zero-core-deps guarantee established in PR #129
  (`IRIS_CALL_CARD=1`-gated lazy import).
- **NFR6 (performance):** writeback and the delta view must not add
  perceptible latency to the post-call flow — the recap/writeback happens
  once per call, off the live-call hot path (consistent with DURING's
  existing L1-on-device / L3-post-call split).

## Technical constraints

No `docs/PROJECT_MANIFEST.md` exists in this rig (same finding as the
ti-w3n09 PRD). The following is derived from `ARCHITECTURE.md` and direct,
just-verified inspection of `origin/main` (current tip `8cf8378` as of
2026-07-04) — several of the design doc's own assumptions (written
2026-06-30) have since drifted and are corrected below for the architect.

**Already in place (verified, matches the design doc's assumptions):**
- `contacts.id` integer PK exists and is already an FK target
  (`contact_addresses.contact_id`, `iris/roster.py`) — ready for AFTER's new
  tables to follow the same pattern.
- `captured_facts.confirmed` / `action_items.confirmed` (nullable tri-state)
  and full provenance (`transcript_turn_id`, `transcript_offset_s`) exist
  exactly as assumed (`iris/capture/schemas.py`, `iris/capture/store.py`).
- `call_cards.enrichment_done` (0=pending/skipped, 1=success, 2=failed)
  exists; `PostCallEnricher` (`iris/capture/enricher.py`) is fully built and
  already runs one LLM pass per call, gated on an API-key opt-in check.
- `ActionItem.owner` already takes `{operator, far}`-style values, driving
  `commitment.direction` per design doc §5.3.

**Drifted from the design doc's assumptions — flag to architect:**
- The design doc's §5.2 assumes `CALL_CARD.written_back` "exists (they do
  in the strawman)." **It does not** — `call_cards` currently has only
  `enrichment_done`, no `written_back` column. This needs to be added.
- The design doc's §5.4 assumes a `disclosed_at` field flows onto the card.
  What actually shipped (PR #141/#144, `ti-ir12t`) is
  `disclosure_ack` / `disclosure_ack_ts` / `disclosure_state` (tri-state:
  pending/disclosed/skipped) on `call_cards` — functionally the same
  information, different field names. The architect should map
  `disclosure_ack_ts` → `call_log.disclosed_at`, not invent a new field.
- The design doc's §2/§5.6 assumes `contact_fact.fact_type` values including
  `account_id | member_id | policy_id`. The current `FactType` enum
  (`iris/capture/schemas.py`) only has
  `PHONE, CASE_ID, AMOUNT, DATE, NAME, ADDRESS, EMAIL` — no
  `account_id`/`member_id`/`policy_id` members exist. The architect must
  decide: extend the enum, or map durable-identity promotion onto the
  existing types.
- The three new tables the design doc proposes (`call_log`, `commitment`,
  `contact_fact`) do not exist anywhere in the codebase yet — this is a
  clean-slate schema addition, proposed home is the roster DB (design doc
  §7-D) for real FKs to `contacts(id)`.
- The write-only, asymmetrically-encrypted STT eval log store (§2.1) does
  not exist yet — net-new component, see NFR1.

## Dependencies

- `ti-rnlqo` (DURING) — CLOSED/shipped (PR #129 and follow-ups). AFTER
  builds directly on its `call_cards`/`captured_facts`/`action_items`
  schema and the already-built `PostCallEnricher`.
- `iris/roster.py` (`contacts` table, integer PK) — existing, stable FK
  target for the new tables.
- `iris/notes.py` (NotesStore) — existing follow-up/todo lifecycle that
  `i_promised` commitments feed into (per design doc §3; the exact
  append API should be confirmed by the architect, not re-derived here).
- Existing Anthropic API integration (opt-in gated) for the recap LLM pass —
  no new external service.
- Downstream: `ti-ipx8v` (BEFORE v2) depends on this bead shipping before it
  can consume `contact_fact`/`commitment`.

## Open questions

1. **(architecture)** Exact encryption scheme for the write-only STT eval
   log — algorithm, key generation/storage/rotation, on-disk/compression
   format. Highest-risk net-new piece in this bead (NFR1).
2. **(architecture)** Extend `FactType` with durable-identity-specific
   members, or map onto existing ones? Affects both DURING's L1 extractors
   (which emit `fact_type`) and AFTER's promotion logic.
3. **(architecture)** Is the recap (`outcome_summary`) generated by
   extending `PostCallEnricher`'s existing L3 pass with a new output field,
   or a second, separate pass? Affects latency/cost and exactly where the
   opt-in gate check needs to live.
4. **(design)** Concrete interaction design for the post-call review: how
   does the operator edit/correct a captured value before confirming (which
   widget, which keybinding), and what does the "from this call…" delta view
   actually look like laid out in the Textual console? The design doc says
   "keep it simple" (§3.1) but doesn't specify layout or keybindings — this
   is real UI/UX work, not resolved by the existing design doc.
5. **(design)** How is a `broken` commitment surfaced as "the opening line"
   of the next call — literal pre-filled text the operator can read/say, a
   flagged list item, something else?
