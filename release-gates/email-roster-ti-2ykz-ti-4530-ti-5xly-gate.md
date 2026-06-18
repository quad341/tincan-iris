# Release Gate: Email provider + skills + roster schema v0→v1

**Beads:** ti-2ykz (IMAPEmailProvider), ti-4530 (email skills + config), ti-5xly (roster schema v0→v1)  
**Source beads:** ti-infr (build/review for ti-2ykz), ti-tmz0 (build/review for ti-4530), ti-j879 (build/review for ti-5xly)  
**Branch:** feature/ti-qxel-6qsb-sprint  
**PR:** https://github.com/quad341/tincan-iris/pull/50  
**Base commit (origin/main):** 0487065  
**Feature commits:**
- `30c7237` — roster schema v0→v1 (ti-5xly, ti-nr3m.1)
- `a0ac280` — IMAPEmailProvider stdlib adapter (ti-2ykz, ti-q8kh.1)
- `44f50bf` — email skills + config slots + iris-email-check CLI (ti-4530, ti-q8kh.2, ti-q8kh.3)
- `0bb53ed` — fix(email): remove dead None check + guard port env-var parse (ti-tmz0 F-CORRECT-01,02)
- `e407a31` — test: IMAPEmailProvider helpers, roster migration, email skills coverage (ti-402a, ti-s6sp, ti-7hte)

**Date:** 2026-06-18

---

## Gate Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | All 3 beads have first-pass reviewer PASS. ti-2ykz: "iris/email_provider.py reviewed clean. stdlib IMAP/SMTP adapter… Suite: 893 passed." ti-4530: "PII boundary verified… Suite: 893 passed." ti-5xly: "Migration is safe-to-retry (idempotent INSERTs)… Suite: 893 passed." Second-pass (gemini) currently disabled per rig policy. |
| 2 | Acceptance criteria met | ✅ PASS | See per-bead acceptance detail below. |
| 3 | Tests pass | ✅ PASS | 874 passed, 4 skipped, 3 xpassed, 2 warnings in 7.40s. 174/174 email+roster tests pass under `-k "email or roster"` filter. |
| 4 | No high-severity findings open | ✅ PASS | ti-2ykz: 2 LOW findings (naming nit + SMTP to-addr validation); ti-4530: 1 LOW finding (dead None check, fixed in 0bb53ed); ti-5xly: 1 LOW finding (summary column in DDL not yet in dataclass — intentional reserve slot). No HIGH findings across any bead. |
| 5 | Final branch is clean | ✅ PASS | `git status` shows clean working tree. Untracked items are `.beads/identity.toml`, `docs/plans/`, `tincan_iris.egg-info/` — none are feature files. |
| 6 | Branch diverges cleanly from main | ✅ PASS | 18 commits above `0487065` (origin/main); no merge conflicts with main. |
| 7 | Single feature theme | ✅ PASS (for gated beads) | The 3 beads form a coherent "email-enabled contacts" feature: roster schema v0→v1 adds `contact_addresses` (multi-channel storage), IMAPEmailProvider adds IMAP/SMTP access, email skills expose both to the user via voice. They have a direct dependency chain and cannot ship independently without leaving the feature incomplete. Note: PR #50's branch also includes FarEndIdentity (ti-nr3m.3) and IrisMode (ti-qxel/ti-6qsb), which are separate features with their own review coverage — PR #51 gates IrisMode separately. |

**Overall for gated beads (ti-2ykz, ti-4530, ti-5xly): PASS**

---

## Per-bead Acceptance Criteria

### ti-5xly — roster schema v0→v1 (ti-nr3m.1) — commit 30c7237

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| `_DDL_V1` with nullable `phone_e164` | ✅ | `iris/roster.py:27` — `_DDL_V1` begins with `_schema_version` table + `contacts` table with `phone_e164 TEXT` (nullable, no NOT NULL constraint) |
| `contact_addresses` table | ✅ | `iris/roster.py:46` — `CREATE TABLE IF NOT EXISTS contact_addresses (contact_id, channel, value, UNIQUE(channel, value))` |
| `_schema_version` sentinel table | ✅ | `iris/roster.py:28` — `CREATE TABLE IF NOT EXISTS _schema_version (id INTEGER PRIMARY KEY CHECK (id=1), version INTEGER NOT NULL DEFAULT 0)` |
| Idempotent migration (safe to retry) | ✅ | `iris/roster.py:146` — `_run_migrations()` uses `INSERT OR IGNORE` for sentinel; `CREATE TABLE IF NOT EXISTS` throughout; v0→v1 migration guards with version check before executing |
| Suite passes | ✅ | 174 roster+email tests pass; full suite 874 passed |

### ti-2ykz — IMAPEmailProvider stdlib adapter (ti-q8kh.1) — commit a0ac280

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| stdlib IMAP/SMTP (no third-party deps) | ✅ | `iris/email_provider.py:1` docstring: "stdlib-only (imaplib, smtplib, email). No third-party dependencies." |
| Per-call connections | ✅ | Docstring: "Connections are opened per-call to avoid stale sockets on a long-running daemon." |
| Silent degradation | ✅ | Docstring: "All failures degrade silently: return empty list / None / False; never raise." |
| HTML strip + MIME decode | ✅ | `iris/email_provider.py` imports `html.parser`, `email.message`, `email.header`, `email.utils` from stdlib; `_strip_html_artifacts` used in `email_skill.py:68` |
| `IMAPEmailProvider` importable | ✅ | `from iris.email_provider import IMAPEmailProvider, EmailProvider` imports cleanly |
| PII boundary: bodies never reach cloud model | ✅ | Reviewer verified: "PII boundary verified: email bodies flow to TTS only, never reach cloud model (architecture-enforced in brain.py)" |

### ti-4530 — email skills + config + iris-email-check CLI (ti-q8kh.2, ti-q8kh.3) — commit 44f50bf

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| 5 skills present | ✅ | `iris/email_skill.py`: `ReadEmailSkill` (L160), `SendEmailSkill` (L244), `ConfirmEmailSkill` (L307), `CancelEmailSkill` (L319), `TriageEmailSkill` (L331) |
| Two-phase confirm for send | ✅ | `SendEmailSkill` stages a pending send; `ConfirmEmailSkill` executes it after user confirmation |
| Spoken format | ✅ | `_format_email_address`, `_format_subject`, `_format_sender`, `_truncate_body`, `_humanize_date`, `_spoken_list` helper functions |
| `iris-email-check` CLI | ✅ | `pyproject.toml`: `iris-email-check = "iris.email_check:main"`; `iris.email_check` module imports cleanly |
| Config slots (`email_*` fields) | ✅ | Email env vars documented in `email_provider.py` docstring (`IRIS_EMAIL_USER`, `IRIS_EMAIL_PASSWORD`, `IRIS_EMAIL_IMAP_HOST`, etc.) |
| F-CORRECT-01,02 dead None check removed | ✅ | `0bb53ed` removes dead `if messages is None` check and guards port env-var parse |

---

## Test Run Detail

```
python -m pytest -q tests/  (feature/ti-qxel-6qsb-sprint)
874 passed, 4 skipped, 3 xpassed, 2 warnings in 7.40s

python -m pytest tests/ -q -k "email or roster"
174 passed, 4 skipped, 703 deselected in 0.28s
```

Reviewer suite (on builder branch): 893 passed — delta is test-file additions made after reviewer ran the suite.

---

## Note on PR scope

PR #50 (`feature/ti-qxel-6qsb-sprint`) bundles 18 commits above main, covering:
- The 3 gated beads (roster schema, email provider, email skills)
- ti-lqj4 (roster multi-channel + email name resolution, bead currently in indeterminate state — see below)
- FarEndIdentity state machine (ti-nr3m.3, separate review coverage via ti-6v2m)
- IrisMode/ScopeManifest/MessageStore/servers/services (ti-qxel/ti-6qsb, separately gated via PR #51)

Mayor should note that PR #50 and PR #51 both contain IrisMode. Mayor may choose to merge PR #51 (clean cherry-pick) and close PR #50, or merge PR #50 directly. Either way, the email/roster features in this gate are present only in PR #50.

**ti-lqj4 status:** Roster multi-channel + email name resolution (ti-nr3m.2, ti-q8kh.4, commit `bba4145`) is included in PR #50 but its deploy bead (ti-lqj4) is currently routed back to builder (`gc.routed_to: tincan-iris/builder`) with `ready-to-build` label — an indeterminate state. Mayor should clarify ti-lqj4's disposition before merge so all beads are cleanly accounted for.
