# Call Card — BEFORE Stage (prep-card assembly)

> Design from the cohelper + operator session, 2026-06-30. Sibling to DURING
> (`ti-rnlqo`) and AFTER (`call-card-after-stage.md`). Bead: `ti-ipx8v`.
> Status: Proposed. Sequence after DURING.

---

## 0. Why BEFORE exists

BEFORE attacks the **anticipatory-dread** phase of the three-phase cycle (dossier
§1): it turns a one-line intent ("calling BCBS about the denied claim") into a prep
card that **restores control and offloads cognition** before the call. It is also
the **read side of the compounding moat** — it consumes the AFTER writeback so that
*next call's prep is already filled in*. Dossier §8 names "Facts at your fingertips
(§2B) + the compounding prior-commitments loop" the recommended **first build**, and
§2B is BEFORE's flagship.

**Principle: prep is a non-blocking aid, scaled to stakes — never the new
procrastination ritual.** Heavy prep for a 5-minute admin call betrays the
friction-reducing promise (dossier §2 caveat). Default minimal; expand only on stakes.

Silent v1: BEFORE produces a card the operator reads; iris does not speak.

---

## 1. Scope

**v1-BEFORE:** §2B **Facts at your fingertips** pre-fill (from AFTER's contact memory
+ roster + notes); a minimal **FRAME** (objective + a drafted opening line + the ask);
**open-commitment surfacing** ("last call — Karen promised a refund by Jul 3.
Honored?"); **scale-to-stakes**; and the hand-off that pre-populates DURING.

**Deferred (BEFORE.2):** the full negotiation checklist (§2D BATNA / objection
table), delivery/state coaching (§2E tone, breathing), and live objection-surfacing
*during* the call.

---

## 2. The PrepCard — assembled, mostly *reads* existing stores

BEFORE introduces **no major new durable store.** It reads
`ContactMemoryStore` (AFTER), `RosterStore`, and `NotesStore`, infers the rest with
an LLM, and **writes the assembled prep into DURING's `CALL_CARD.context_notes`**
(the architect's model already reserves that field "pre-populated by BEFORE"). The
PrepCard is the dossier §2 schema, with `call_type` selecting which sections render:

| Section | Fields (v1) | Source |
|---|---|---|
| **A — FRAME** | `objective`, `call_type`, (`success_criteria` v2) | LLM-inferred from the intent |
| **B — FACTS** *(flagship)* | account/claim/member IDs, dates, amounts; **`prior_commitments`**; docs to open | `contact_fact` + open `commitment` (AFTER); `NotesStore` |
| **C — WHAT TO SAY** | **`opening_line`** (drafted), `agenda` (3–5 bullets), `the_ask` | LLM, grounded in B |
| **D — CONTINGENCIES** | objections, BATNA, escalation_path | *deferred (BEFORE.2; dispute calls)* |
| **E — DELIVERY** | tone, pacing, buy-time line | *deferred (BEFORE.2)* |
| **F — CAPTURE bridge** | the assembled prep → DURING | see §6 |

The PrepCard is assembled on demand (optionally cached for a pending call); it is not
a new system of record — the durable memory it draws on is AFTER's.

---

## 3. Assembly flow

```mermaid
flowchart TD
    A[one-line intent\n'calling BCBS re: denied claim'] --> B[resolve contact\nRosterStore by name/number]
    B --> C[query ContactMemoryStore\ncontact_fact + open commitments + call_log]
    B --> D[query NotesStore\nopen follow-ups]
    C --> E[LLM: infer FRAME + draft\nopening_line / agenda / the_ask\nGROUNDED in retrieved facts]
    D --> E
    E --> F[assemble PrepCard\nscaled to call_type]
    F --> G[write CALL_CARD.context_notes\n(DURING seam)]
```

The LLM runs **off the hot path** (pre-call, not real-time) — fine to use — and is
**grounded**: it drafts language from the *retrieved* facts; it does not invent
account or reference numbers (same posture as AFTER's enricher, §7-C there).

---

## 4. The compounding read (AFTER → BEFORE) — the payoff

| From AFTER's store | Becomes, in BEFORE |
|---|---|
| `contact_fact` | pre-filled §2B IDs/dates/amounts — *"Acme account #12345"* already on the card |
| `commitment WHERE status='open'` | surfaced item + a candidate **opening line**: *"On June 30 your rep Karen promised a refund by July 3 — it didn't arrive."* |
| `call_log` | history context — *"3rd call to BCBS; last outcome: …"* |

A **broken** open commitment is the strongest case: AFTER captured it, BEFORE hands
it back as the operator's pre-drafted, dated opening — the moat made concrete.

---

## 5. Scale to stakes

`call_type` (dispute/service · outbound-ask · negotiation · difficult-personal ·
interview · **admin/appointment**) drives which sections render:
- **routine** (admin/appointment): a 3-field card — `objective`, the key fact,
  `opening_line`. Nothing more.
- **dispute / negotiation**: add §2D contingencies (BEFORE.2).

Default to minimal; expand on stakes. The guard is explicit: do not let prep become
the ritual that delays the call.

---

## 6. Seams

1. **FROM AFTER (the read side of the moat):** reads `ContactMemoryStore`
   (`contact_fact` / `commitment` / `call_log`), keyed on the same
   `RosterStore.contacts.id`. This is why AFTER persists those tables.
2. **TO DURING:** writes the assembled prep into **`CALL_CARD.context_notes`** (field
   already reserved in the DURING model). v1 = the prep text + surfaced open
   commitments. *(v2: pass structured "expected facts" so DURING can flag when the rep
   states the reference number you came in with.)*
3. **LLM (intent → plan):** pre-call, grounded, operator's API key — same privacy
   posture as AFTER's post-call enricher.

---

## 7. Open decisions (operator — review later)

- **A — Intent→plan:** LLM (grounded), **no template** — consistent with AFTER-C.
- **B — Draft the opening line?** Yes — it's the highest-value §2C artifact for the
  call-averse (dossier), rendered as an **editable** suggestion, never locked.
- **C — Contact resolution:** match the intent's named org against `RosterStore`
  (fuzzy by display_name); on no match, create-on-the-fly or prompt. Needs a rule.
- **D — Stakes default:** default to the 3-field minimal card; expand only when
  `call_type` is dispute/negotiation.
- **E — Where it runs:** the daemon (pre-call) or the console front-end — not
  real-time-constrained either way.
