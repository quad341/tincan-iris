# ADR-0005 — Trust, permission & assurance model: principals × assurance × capability grants, daemon-enforced

- **Status:** proposed (2026-06-19)
- **Related:** [ADR-0001](0001-no-mcp-direct-api-via-qwen.md) (no tools to models — invariant #1 here);
  [ADR-0002](0002-capability-gating-by-speaker-channel.md) (this ADR **extends and supersedes its coarse two-mode model**, and is the "later ADR" 0002 §Consequences anticipates);
  [ADR-0003](0003-memory-three-layer-architecture.md) (memory)
- **Authors:** operator (@quad341) + cohelper

## Context

ADR-0002 gave us the foundation and it still holds: **speaker identity is the
audio channel** (operator on the mic, far party on the SCO downlink), the
**operator is the trust anchor**, **demo-by-default** is telemarketer-safe, and
Iris **acts without disclosing**. But 0002 is deliberately *coarse* — a single
"full-mode" flag — and explicitly defers finer-grained sharing to a later ADR.

It also makes one claim that needs sharpening: 0002 calls the physical channel
**"spoof-proof."** That holds against a far party on the downlink, but **not
against the microphone+speaker loop** — an adversary who induces Iris to *speak*
a command that echoes back into the mic and is attributed to the operator. AEC
mitigates this; it cannot be the basis of *hard* security. So **assurance — how
confident we are that the speaker really is the operator — must become a
first-class, graded axis**, separate from authorization.

### Threat model (what this ADR defends against)

- **Mic-loop impersonation** of the operator (above).
- **A coaxed or prompt-injected local model.** Untrusted content (web results,
  email bodies, caller audio) flows through Qwen; assume it can be steered.
- **Far-party social engineering** ("Iris, text me his address").
- **Exfiltration** of the operator's private data outbound.

Crucial enabling fact from ADR-0001: **the models have no intrinsic tools** — no
filesystem, shell, or network of their own. A model's *entire* reach is (a)
*proposing* a skill and (b) *emitting text* that gets spoken. Everything below
builds on that.

## Decision

Three composable parts, one fixed enforcement architecture, six invariants.

### 1. Principals — *who is acting* (from the audio channel, per ADR-0002)

`operator` (mic) · `far-party` (downlink) · `demo` · `external-agent`
(informational only — e.g. the mayor reply channel; **never a command path**).
**Default-closed:** every new conversation/channel starts untrusted; trust only
ratchets *up* via an operator grant on the mic, never inherits.

### 2. Assurance — *how sure we are it's that principal* (the sudo↔security dial)

A graded ladder, because the question is really "how spoofable is this signal":

1. **Ambient** — channel only (mic = operator). Convenience tier; loop-spoofable;
   fine for low stakes.
2. **Corroborated** — channel **+** a soft factor (AEC reports clean → Iris's
   own output did *not* loop; recent known-good operator turn). Better, still audio.
3. **Out-of-band** — a **non-audio** confirm. On our hardware that is **the
   keyboard on Iris's own console** (tincan stays a dumb conduit and knows
   nothing of this). The only tier that survives the loop.

Each capability declares a **required assurance tier** (product-configurable).
Tier-3 ops are **keyboard-confirmed**; the strongest class is **keyboard-only**
(voice can never even initiate). **Invariant:** *no audio path, at any assurance
level, may grant trust or change a grant.* Consequence to accept: **hands-free ⇒
tier-1/2 only**; tier-3 needs the console.

### 3. Capabilities & grants — *what may be done* (fine-grained, per-principal)

Capabilities are **narrow verbs** (`read_availability`, `book_free_slot`,
`read_event_details`, `read_location`, `send_to_known`, `send_to_new`,
`place_call`, `delegate_to_mayor`, `change_grant`, …). Each carries
`(assurance tier, enforcement strength, default-stranger policy)`. **Per-contact
grant profiles** live in the roster ("mother → {availability, event_details,
location}"); the **stranger default is the operator's configurable privacy
policy** (e.g. `{availability, book_free_slot}`). Disclosure and far-party-action
collapse into one capability-grant model keyed on the principal. A starter table
is in the appendix; completing it is an open item.

### 4. Enforcement — *the daemon is the gate; the model only proposes*

> The model is **never** a trust boundary. The Iris daemon is.

Flow: **model proposes** `(skill, args)` → **daemon authorizes**
(`principal × assurance × grant`) → tier-3 ⇒ **keyboard confirm** → **execute** →
**disclosure-filter the result by audience** → TTS. The qwen lane should
*return a proposal*; the daemon *authorizes and executes*. (PR #71's
`operator_only` gate is a first concrete step but lives inside the lane; the
target is to pull the gate out onto the daemon spine.)

**Enforcement strength matches blast radius** — you do **not** hard-gate
everything:

- **Hard** — deterministic daemon refusal. High blast radius: `send_to_new`,
  `place_call`, mutate-state, `change_grant`. Airtight.
- **Soft** — guidance + offered-set scoping; best-effort, occasional leaks
  tolerable. Low blast radius: `web_search`, `time`, `take_note`.

Three layers exist, only the last is a boundary: **prompt guidance < offered-set
scoping < daemon hard-gate.** Keep the **hard set small** — only the verbs where
a leak actually hurts — so Iris stays un-annoying for the 95% low-stakes case.

### 5. Context lifecycle — *the daemon owns context; default-closed*

The model is a **stateless function**; the daemon **replays the full intended
context every turn** (llama.cpp `cache_prompt` is a *speed* optimization, safe by
construction — it can only skip recomputing tokens already in the prompt, never
*add* content). Context is **conversation-scoped** and **flushed to
empty-private on every boundary** (call start/end, audience or principal change);
on any uncertainty, **drop to least-privilege**. Optional KV-slot reset when
crossing *down* into an untrusted principal, for zero residue.

### 6. PII stays in skills, not the model — *sharpening "act without disclosing"*

ADR-0002 has Iris *reason over* private data and reveal a coarse result. We push
that boundary **down into the skill**: the **skill computes the answer over the
PII and hands the model only the sanitized result** — free/busy is computed by
the calendar skill; the model sees `"free"`, never the events. *The model gets
answers, not data*, so a coaxed model has nothing to divulge. The **irreducible
exceptions** — generative-over-private-content (summarize an email, draft a
reply) — are **contained**: local model only (never cloud), entitled principal
only, transient (one turn), flushed on boundary.

## The six invariants (the spec)

1. **No tools to any model** (local or cloud) — only action surface is skills. (ADR-0001)
2. **Skills are narrow** — no generic `run`/`read_file`/`eval`; blast radius = generality.
3. **The daemon hard-gates the dangerous verbs**; **trust/grant changes are keyboard-only.**
4. **PII lives in skills, not the model** (irreducible cases contained).
5. **Conversations are bounded, default-closed.**
6. **The daemon owns the context** (full replay; never depend on model/server-retained state).

The **trust-critical core is just three things — the gate, the boundary
detector, and "PII-stays-in-skills."** Audit and test *those* hard; the entire
soft surface (web search, phrasing, the model itself) can be buggy without a
breach. That is the small, *designed-in* trust boundary.

## Testing strategy — validate now vs. after the system exists

We deliberately separate guard-tests we can write **today** (locking the
invariants in before the gate is built, so the codebase can't drift away from
this design) from tests that need the new machinery.

**Testable NOW (cheap, prevents drift):**
- *Inv. 1 — no tools:* assert the completion calls to Qwen and the Claude TUI
  carry **no tool/function definitions**; the test fails the moment a tool
  surface is introduced.
- *Inv. 4 — PII-in-skills:* assert sanitizing skills never return raw PII
  (calendar free/busy returns no titles/attendees — **already covered** by the
  act-without-disclose tests; extend the pattern to email triage, etc.).
- *Inv. 6 — daemon owns context:* assert the qwen lane builds a full prompt each
  turn and does not depend on server-retained state; add an `iris doctor` check
  that the llama.cpp config isn't a stateful-session mode we lean on.
- *Inv. 2 — narrow skills:* a review checklist + a name lint (no
  `run`/`exec`/`read_file`/`eval` skill); enforced primarily at review.
- *Speaker-tag integrity (ADR-0002):* assert the `speaker` tag rides
  capture → addressing → brain and **cannot be set from the downlink**.

**Testable only AFTER the gate/principal/assurance system is implemented:**
- The daemon gate: `principal × assurance × grant` authorization, **one unit
  test per capability-table row.**
- Tier-3 keyboard-confirm, and **keyboard-only-trust** (assert *no* audio path
  reaches `change_grant`).
- **Boundary detection + flush:** the mom→stranger pressure-test as an
  integration test — verify the loads/flushes land where this ADR says.
- Disclosure filtering by audience; default-closed on uncertainty.
- Per-principal **qwen scoping** (constrained/empty private context for a far party).

**Approach:** write the NOW guard-tests immediately; build the gate; then add the
AFTER tests against the capability table as it's finalized.

## Consequences

- ➕ **Small, auditable trust core** — security concentrates in three components,
  not smeared across the system.
- ➕ **Telemarketer-safe by default** (inherited from ADR-0002), now with
  *graded* widening instead of one flag.
- ➕ **Injection/coaxing bounded to the soft set** — it can never reach a hard verb.
- ➕ **Designed-in, not bolted-on** — the invariants are guard-testable before the
  gate exists.
- ➖ **More plumbing** — assurance signals (AEC-clean, recency), a grant store,
  the daemon gate, the keyboard-confirm UX, per-principal qwen context scoping.
- ➖ **Hands-free can't do tier-3** — a deliberate security/UX trade.
- ➖ **The capability table is real config to maintain.**
- **Supersedes** ADR-0002's coarse single-flag full-mode; **keeps** its
  foundations (speaker=channel, operator-anchor, demo-default, push-in-not-out).

## Open questions

- The full capability × tier × strength × default-stranger table (appendix is a
  first cut).
- Boundary detection **within a continuous channel** (intra-call principal
  change) — rests on speaker attribution; default-closed is the backstop.
- Containment specifics for the irreducible summarize/draft PII cases.
- The exact `iris doctor` validation of the llama.cpp no-server-state assumption.
- Reconciling PR #71's inline `operator_only` gate onto the daemon spine.

## Appendix — starter capability table (illustrative, NOT final)

Assurance here is the confidence-it's-the-operator required for **operator**
invocation (the keyboard tiers defend against the mic-loop faking the operator);
far-party-granted actions are gated by the reliable channel attribution + the
grant. "Default: stranger" is the operator's *configurable* privacy policy
(values shown are the example operator's, not a mandate).

| Verb | Assurance (operator) | Strength | Default: stranger |
|---|---|---|---|
| `time` / `date` / `introduce` | ambient | soft | allow |
| `web_search` | ambient | soft | allow (best-effort; leak tolerable) |
| `take_note` / `list_notes` | ambient | soft | deny |
| `read_availability` (free/busy) | ambient | soft | allow |
| `book_free_slot` | corroborated | hard | allow |
| `read_event_details` (titles/attendees) | corroborated | hard | deny (grant per-contact) |
| `read_location` | corroborated | hard | deny (grant per-contact) |
| `send_to_known` (reply in existing thread) | corroborated | hard | deny |
| `send_to_new` (new recipient) | out-of-band | hard | deny |
| `place_call` (known contact) | corroborated | hard | deny |
| `place_call` (non-contact) | out-of-band | hard | deny |
| `delegate_to_mayor` | corroborated | hard | deny |
| `change_grant` / trust | **keyboard-only** | hard | deny (never voice) |
