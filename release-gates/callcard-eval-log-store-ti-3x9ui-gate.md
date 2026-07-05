# Release Gate: callcard-eval-log-store-ti-3x9ui

**Bead:** ti-3x9ui
**Source bead:** ti-qi76c (closed, spec) -> ti-pqs9k (review, PASS)
**Feature branch:** deploy/callcard-eval-log-store-ti-3x9ui
**Base:** origin/main @ b0b827b52281e5c5bde63224ae38a0fd2cd1a1f9
**Date:** 2026-07-05

---

## Branch construction note (read before the criteria table)

The reviewed commit is `60a92dd` on `feat/callcard-after-data-layer-ti-hb2dx`.
That branch is not a straight line to origin/main — `60a92dd`'s own parent
chain also carries two other, unrelated beads' commits that are not part of
this deploy:

- `76237d0` ("route Call Card L3 through warm ClaudeTuiSession", ti-pkt2r.1) —
  already gated and PR'd separately (see ti-uo3l7 / PR #166, currently OPEN,
  not yet merged).
- `e72052b` ("Call Card AFTER post-call recap generator", ti-6a1y3) — deferred
  in its own deploy queue (ti-zd5os, status `deferred`, not part of this
  deploy either).

A plain `git cherry-pick 60a92dd` onto `origin/main` conflicts in
`iris/config.py`, `iris/daemon/call_card_host.py`, and `pyproject.toml`
because those two sibling commits touch the same files and are absent from
main. Inspected each conflict directly (`git show 60a92dd -- <file>` against
origin/main's actual current content) and confirmed all three are "main is
missing an unrelated, not-yet-merged block" situations, not genuine content
disputes — `60a92dd`'s own contribution in each shared file anchors on code
that is identical on origin/main and on the sibling commits (the
`call_card_ended` broadcast call, the `call_card_disclosure_script` field,
`_load_call_card_config()`, the `call-card` extras list).

Reconstructed `60a92dd`'s isolated delta directly onto a fresh branch off
`origin/main`:

- Two new files (`iris/capture/eval_log_store.py`, `iris/eval_log_keygen.py`)
  written verbatim from `git show 60a92dd:<path>` — byte-identical, confirmed
  via diff against the commit's own blob.
- `iris/daemon/call_card_host.py`: added the eval-log imports and the
  self-contained eval-log block in `stop_session()`, anchored on the
  pre-existing `transcript_store` assignment and the `call_card_ended`
  broadcast. Diffed the inserted block against `60a92dd`'s own version
  (`diff <(sed -n '140,173p' ours) <(git show 60a92dd:... | sed -n '142,175p')`)
  — **empty diff, byte-identical**. The only difference from `60a92dd`'s full
  file is the *trailing* L3-enrichment section, which correctly remains in
  main's current (pre-76237d0) form since that rewrite hasn't merged.
- `iris/config.py`: added only the new `eval_log_public_key` field, in
  isolation from the unrelated (unmerged) recap/enrichment config block that
  sits next to it on the entangled branch.
- `iris/daemon/__main__.py`: added the single
  `eval_log_public_key=settings.get(...)` line to `_load_call_card_config()`.
- `pyproject.toml`: verified fresh against `origin/main`'s actual current
  content (not assumed from the entangled branch, which already has 76237d0's
  `pydantic>=2` swap applied locally) — origin/main's `call-card` extra is
  still `instructor[anthropic]>=1.0` as of this gate (PR #166 unmerged).
  Appended `PyNaCl>=1.5` to that list; core `dependencies` untouched.

Net effect: this branch ships exactly `60a92dd`'s reviewed contribution, with
zero content from either unmerged sibling commit.

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-pqs9k (reviewer) closed with explicit "No blocking findings. Please deploy per standard protocol." — AST-walked API surface, live SealedBox round-trip, independence-from-L3-gate proven live, ruff clean, full suite re-run |
| 2 | Acceptance criteria met | **PASS** | See AC table below — all 6 from ti-qi76c independently re-verified on this branch |
| 3 | Tests pass | **PASS** | `pytest tests/ -q`: 1751 passed, 3 xpassed, 1 failed (pre-existing/environmental, see below) |
| 4 | No open HIGH findings | **PASS** | ti-pqs9k: zero blocking findings. Only open follow-up is ti-x46ji (needs-tests, non-blocking test-hygiene, already filed) and ti-8wtzr (P3, pre-existing, unrelated) |
| 5 | Final branch is clean | **PASS** | `git status`/`git diff --stat` on this branch shows exactly the 6 intended files (2 new, 4 modified, 56 insertions/2 deletions) — no stray content from the many unrelated scratch directories present in this shared worktree |
| 6 | Branch diverges cleanly from main | **PASS** | Branch built directly off `origin/main` @ `b0b827b`; single clean commit on top, no merge conflicts possible |
| 7 | Single feature theme | **PASS** | Write-only encrypted eval-log store only — no content from either entangled sibling commit |

---

## Acceptance Criteria (ti-qi76c)

| AC | Description | Verdict |
|----|-------------|---------|
| AC1 | Every call with non-empty transcript + configured public key produces exactly one `eval_log_entries` row | ✅ Code identical to reviewer's live-tested version (13/13 checks incl. real `stop_session()` integration for both empty-key and configured-key paths) |
| AC2 | Sealed blob cannot be decrypted without the private key; no read/decrypt method anywhere in `EvalLogStore` | ✅ Independently re-verified this gate: fresh keypair, `append()` via the store, raw row read back, `SealedBox` decrypt with the private key recovers the exact original bytes; `hasattr` checks confirm no `get`/`read`/`decrypt` method exists |
| AC3 | No public key configured -> no row written, no exception, `stop_session()` completes normally | ✅ Explicit `if not public_key: _log.debug(...)` skip branch, byte-identical to reviewed commit |
| AC4 | Grep/review-level check confirms no read/select method on `EvalLogStore` | ✅ Full source read this gate — only `__init__` and `append` are defined |
| AC5 | `pyproject.toml` core `dependencies` unchanged; `PyNaCl` only under `call-card` | ✅ Diff confirms only the `call-card` list changed |
| AC6 | Existing test suite stays green | ✅ 1751 passed/3 xpassed; the 1 failure is pre-existing/environmental (see below), reproduces identically off an unmodified tree |

---

## Test Run

```
python3 -m py_compile <all touched/new .py files>   -> SYNTAX OK
ruff check iris/ tests/                             -> All checks passed!
python3 -m pytest tests/ -q                         -> 1751 passed, 3 xpassed, 1 failed in 99.83s
```

The 1 failure (`tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`)
is pre-existing and environment-specific: a real `iris.daemon` process (pid
689129) is running on this shared dev box and holds the daemon's exclusivity
flock, which this test's unmocked `main()` call trips over. Already filed as
`ti-8wtzr` (P3), confirmed there to reproduce identically against a
git-stashed unmodified tree — not a regression from this branch.

Additionally smoke-tested the new code directly (no committed tests exist
yet for this feature — tracked separately as `ti-x46ji`, non-blocking per
reviewer): `EvalLogStore.append()` end-to-end with a real generated keypair,
confirmed the stored `sealed_blob` round-trips through `nacl.public.SealedBox`
decryption to the exact original plaintext, and confirmed `iris.eval_log_keygen`
runs cleanly.

---

## Verdict: **PASS**
