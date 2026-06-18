# Release Gate: IrisMode, ScopeManifest, MessageStore SQLite, servers, services

**Bead:** ti-xz9c  
**Source bead (build+review):** ti-c55o  
**Branch:** feature/irismode-servers-services-ti-xz9c  
**Base commit (origin/main):** 0487065  
**Feature commit (cherry-picked):** 7e8edf5 (from reviewed commit 83fc6da / b578e83)  
**Date:** 2026-06-18

---

## Gate Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-c55o notes: "Reviewer Verdict: PASS" — first-pass (claude) reviewer. Second-pass (gemini) currently disabled per rig policy. |
| 2 | Acceptance criteria met | ✅ PASS | Reviewer verified all 5 sub-bead criteria (see detail below). |
| 3 | Tests pass | ✅ PASS | 633 passed, 3 skipped, 3 xpassed, 0 failed (7.36s). |
| 4 | No high-severity findings open | ✅ PASS | 7 INFO/LOW findings; 0 HIGH. None block deploy. |
| 5 | Final branch is clean | ✅ PASS | `git status`: clean working tree. Untracked items are `.gc/` and prior gate files — repo-controlled artifacts, not feature files. |
| 6 | Branch diverges cleanly from main | ✅ PASS | Single clean cherry-pick onto origin/main. No merge conflicts. |
| 7 | Single feature theme | ✅ PASS | IrisMode, ScopeManifest, MessageStore SQLite, persistent servers, and service templates form a tightly coupled ops-infrastructure layer. All 5 sub-beads address the same concern: operating iris as a persistent, mode-aware, install-able system service. |

**Overall: PASS**

---

## Acceptance Criteria Verification (per reviewer)

| Sub-bead | Feature | Verdict |
|----------|---------|---------|
| ti-qxel.1.1 | `_whisper_server.py` + `_kokoro_server.py` with `/health` + `/transcribe`/`/synth`; `test_http_servers.py` green | ✅ PASS |
| ti-qxel.3.1 | 4 systemd unit templates + `install.py` + `iris-install-services` entry point; `test_install_services.py` green | ✅ PASS |
| ti-6qsb.2.1 | `IrisMode` enum + `ModeManager` + `ScopeManifest` + `lanes.py _help`; `test_iris_mode.py` green | ✅ PASS |
| ti-6qsb.3.1 | `DesktopNotifySink` + `ProactiveDelivery` OUT_OF_CALL routing + P0 cooldown bypass; `test_desktop_notify_sink.py` + `test_proactive_delivery.py` green | ✅ PASS |
| ti-6qsb.4.1 | `MessageStore` SQLite with WAL + backward-compat `obj_cache`; `test_message_store_sqlite.py` green | ✅ PASS |

---

## Security Findings (INFO/LOW — non-blocking)

Per reviewer (ti-c55o notes):

1. `iris/_whisper_server.py:208` [INFO] — `os.environ.setdefault` at import time. Acceptable: standalone server process, prevents HuggingFace network access.
2. `iris/_whisper_server.py` + `_kokoro_server.py` [INFO] — No `Content-Length` ceiling on HTTP bodies. Acceptable: 127.0.0.1-only servers.
3. `iris/_kokoro_server.py:96`, `_whisper_server.py:273` [INFO] — Raw exception `str()` in 500 responses. Acceptable: localhost debugging aid.
4. `iris/message_store.py:468` [INFO] — `check_same_thread=False` without Python lock. Low risk: voice messages arrive serially in practice.
5. `iris/notify_sink.py:629` [PASS] — `subprocess.run` with list args + `--` separator. Command injection correctly prevented.
6. `iris/services/install.py:845` [INFO] — `CalledProcessError` stderr not logged; caller hints `journalctl`. Acceptable.
7. `iris/proactive_delivery.py:686-700` [LOW] — P0/P1 items silently discarded when `notify_sink=None` + `OUT_OF_CALL`. Not a crash risk; not a blocker.

---

## Test Run Detail

```
633 passed, 3 skipped, 3 xpassed, 2 warnings in 7.36s
```

Note: the reviewer ran 730 tests on a branch that also included the pending roster-multichannel-email work (ti-lqj4). The lower count here (633) reflects origin/main + this bead only — the email/roster test files are not part of this deploy. No regressions observed.

---

## Cherry-pick Note

The build commit `83fc6da` was authored on a branch that included unreleased email work. The reviewed cherry-pick (`b578e83`) included `iris-email-check` in `pyproject.toml` as an artifact of its branch context; `iris/email_check.py` is not part of this bead. That entry point was removed from the cherry-pick before gating. The resulting commit (`7e8edf5`) adds exactly: `iris-install-services`, `iris-whisper-server`, `iris-kokoro-server` to `pyproject.toml`, matching the intended scope of this bead.
