# Call Card — AFTER Stage (post-call writeback + compounding loop)

> Design from the cohelper + operator session, 2026-06-30. Sibling to the DURING
> strawman (`ti-rnlqo`) and BEFORE (`ti-ipx8v`). Bead: `ti-tr1m5`.
> Status: Proposed — decisions in §7 are open for the operator.

---

## 0. Why AFTER exists (two distinct jobs)

The dossier gives AFTER two evidence-backed jobs, and they have *different* risk
profiles — keep them separate:

1. **The post-call record (rumination-puncture).** Low-stakes, always produced.
   A concise objective recap that punctures the post-event "did I mess up / what
   did they even say" loop (dossier §1, §8#3) — the feature most rivals miss.
2. **The compounding writeback (the moat).** High-stakes, **confirmation-gated.**
   Persist the *verified* facts + commitments to durable, contact-keyed memory so
   **next call's BEFORE pre-populates from them** (dossier §2B `prior_commitments`,
   §F, §8 — "next call's prep gets better because iris remembers what the last rep
   promised"). This is the defensible edge.

**Load-bearing principle: only confirmed facts compound.** DURING captures
liberally and ungated; AFTER writes back only operator-verified items. A
confidently-wrong reference number that *compounds into next call's prep* is the
worst-case version of iris's core failure — so the verification gate is the wall
between capture and the moat.

---

## 1. Scope

**v1-AFTER:** the post-call record; the durable `call_log` + `commitment` +
`contact_fact` writeback (confirmed-only); and the BEFORE-facing query that
surfaces open commitments on the next call. The core compounding loop, end to end.

**Deferred (AFTER.2):** proactive due-date nudges ("Acme refund was due today —
did it land?"); automatic commitment resolution; affective-forecasting coaching
("how did that go vs. how you feared?"); richer promotion heuristics.

---

## 2. Data model — a new contact-keyed store

`NotesStore` is freeform JSON (capture→list→done, no contact key, no due/status) —
unfit for structured commitments. `RosterStore` owns contact identity
(`contacts.id`, SQLite). **AFTER introduces three structured tables keyed to
`contacts.id`** (proposal: in the roster DB so the FK to `contacts(id)` is real;
see §7-D).

```
call_log            -- the dated "who I spoke to and when" record (CFPB §2B)
  id PK
  contact_id        FK -> contacts(id)
  session_id        -- the DURING CallCard session (provenance back-link)
  started_at, ended_at
  agent_name        -- the rep (from a captured `name` fact)
  disclosed_at      -- carried from CALL_CARD (our audit-trail decision)
  outcome_summary   -- the rumination-puncture recap text
  objective         -- nullable; from BEFORE if present

commitment          -- THE MOAT
  id PK
  contact_id        FK -> contacts(id)
  call_log_id       FK
  direction         -- 'they_promised' | 'i_promised'
  description
  amount            -- nullable (links a $ fact)
  due_date          -- nullable ISO
  status            -- 'open' | 'honored' | 'broken' | 'cancelled'
  source_turn_id, source_offset_s   -- provenance survives into next call (tap-to-replay)
  captured_at, resolved_at

contact_fact        -- durable identity facts that pre-populate next call's §B
  id PK
  contact_id        FK -> contacts(id)
  fact_type         -- account_id | member_id | policy_id | address | email | ...
  normalized_value
  label             -- nullable ("Acme account #")
  first_seen_session, last_confirmed_at
```

Per-call, transient facts (this call's hold time, a one-off case number that isn't
an identity) stay in the DURING `CALL_CARD` and do **not** get promoted.

---

## 3. Writeback flow

```mermaid
flowchart TD
    A[call_ended] --> B[DURING PostCallEnricher L3 completes\nenrichment_done=1 — card finalized]
    B --> C[AFTER: generate outcome_summary\nfrom CONFIRMED + high-conf facts]
    C --> D[Show post-call record to operator\n(rumination-puncture; always)]
    D --> E[Operator confirms / edits criticals\n(verification gate — consumed, not designed here)]
    E --> F{Finalize\n'Save to [Contact]'}
    F --> G[write call_log row  (always — the dated record)]
    F --> H[write commitment rows\nfrom CONFIRMED action items/promises]
    F --> I[upsert contact_fact\nfor CONFIRMED durable identity facts]
    F --> J[i_promised items -> NotesStore\n(reuse existing follow-up lifecycle)]
    G --> K[set CALL_CARD.written_back=1]
    H --> K
    I --> K
```

- **`call_log` is always written** (the dated record is low-stakes and useful even
  if nothing else is confirmed). **`commitment` / `contact_fact` are confirm-gated.**
- **Mapping:** `ACTION_ITEM.owner == 'far'` → `commitment(they_promised)`;
  `owner == 'operator'` → `commitment(i_promised)` **and** a NotesStore follow-up
  (so the operator's own to-dos land in the existing capture→list→done lifecycle).
- The L3 enricher already runs an LLM pass — reuse it to emit `outcome_summary`,
  **strictly grounded in the captured facts** (no new entities; the recap restates,
  it doesn't re-extract). See §7-C for the template-vs-LLM call.

---

## 4. The compounding loop (AFTER → BEFORE)

Next call to the same `contact_id`, BEFORE (`ti-ipx8v`) queries this store:

| Source | Becomes, in BEFORE |
|---|---|
| `contact_fact` | pre-filled §B "Facts at your fingertips" (account #, member ID, prior IDs) |
| `commitment WHERE status='open'` | **open items** surfaced as agenda / opening line: *"Last call Jun 30 — Karen promised a refund by Jul 3. Honored?"* |
| `call_log` | history context (*"3rd call to Acme; last outcome: …"*) |

Operator resolves an open commitment → `honored` / `broken`. A **broken** commitment
is dispute leverage *and* the literal opening line of the next call (*"On June 30,
your rep Karen promised X by July 3 and it didn't happen"*) — the compounding moat
made concrete.

---

## 5. Seams DURING must honor — lock these NOW (the actionable output)

DURING is being built right now; these are the contracts it must leave clean so
AFTER drops in without rework:

1. **`CALL_CARD.contact_id` = `RosterStore.contacts.id`** (the integer identity) —
   *not* a phone string. AFTER keys every writeback on it.
2. **`CAPTURED_FACT.confirmed` + `CALL_CARD.written_back`** flags exist (they do in
   the strawman). AFTER reads `confirmed=1 AND written_back=0`.
3. **`ACTION_ITEM.owner ∈ {operator, far}`** — drives `commitment.direction`.
4. **`disclosed_at`** on the card flows into `call_log`.
5. **Provenance (`transcript_turn_id`, `transcript_offset_s`)** flows into
   `commitment.source_*` so a compounded commitment is still tap-to-replay-able a
   call later.
6. **A way to tell durable-identity facts from transient ones** — so AFTER knows
   what to promote to `contact_fact`. Either a fact_type subset rule
   (`account_id|member_id|policy_id|address|email` are durable) or a `durable` flag.
   *This is the one seam not yet in the DURING model — worth adding now.*

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Garbage compounds (STT-mangled value written back, poisons next prep) | confirm-gate the writeback; only `confirmed=1` items promote; provenance kept for re-check |
| Duplicate facts across calls (same account # captured every call) | `contact_fact` upsert by (contact_id, fact_type, normalized_value); update `last_confirmed_at`, don't duplicate |
| Contact identity drift (same human, new number) | key on `contacts.id`, not phone; rely on RosterStore's identity resolution |
| Commitment never resolved (open forever) | v1: surfaced every next call until resolved; AFTER.2 adds due-date nudge |
| Operator skips the post-call review (nothing confirmed → nothing compounds) | `call_log` still written (the record survives); criticals just stay unconfirmed and re-surface |

---

## 7. Open decisions (operator)

- **A — Writeback gating.** Proposed: `call_log` always written; `commitment` /
  `contact_fact` written on explicit one-tap **"Save to [Contact]"** after review.
  Alt: auto-save all confirmed items after a grace period (less friction, less control).
- **B — `i_promised` items.** Proposed: write a `commitment(i_promised)` **and** a
  NotesStore follow-up (operator's to-do). Alt: commitment only (don't touch Notes).
- **C — Summary generation.** Proposed: reuse the L3 enricher's LLM, strictly
  grounded (restate, don't re-extract). Alt: deterministic template (fully private,
  no extra LLM call) for v1.
- **D — Store home.** Proposed: new tables in the **roster DB** (real FK to
  `contacts(id)`). Alt: a separate `contact_memory.db` (cleaner separation, no
  cross-DB FK).
- **E — v1 boundary.** Proposed v1 = record + writeback + BEFORE-surfacing; defer
  nudges/auto-resolution to AFTER.2. Confirm that's the right cut.
