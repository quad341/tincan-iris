"""Tests for iris doctor's asset preflight (check_assets) + its doctor_main wiring.

check_assets() reuses the real STT/TTS providers' resolution + .available(), so
these mock the provider classes (not the filesystem) to drive each status. The
service layer is covered separately in test_doctor.py.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

from iris import doctor
from iris.doctor import AssetCheckResult, DoctorStatus


def _fake_stt(available, python="/p/.venv-whisper/bin/python",
              model="/m/models/whisper/small.en"):
    s = MagicMock()
    s.available.return_value = available
    s.python = python
    s.model = model
    return s


def _fake_tts(available, python="/p/.venv-kokoro/bin/python",
              model="/m/models/kokoro/kokoro-v1.0.onnx",
              voices="/m/models/kokoro/voices-v1.0.bin"):
    t = MagicMock()
    t.available.return_value = available
    t.python = python
    t.model = model
    t.voices = voices
    return t


# ---------------------------------------------------------------------------
# check_assets — per-asset status
# ---------------------------------------------------------------------------

def test_whisper_ok_when_available():
    with patch("iris.audio.stt.FasterWhisperSTT", return_value=_fake_stt(True)), \
         patch("iris.audio.tts.KokoroTTS", return_value=_fake_tts(True)), \
         patch("iris.doctor.shutil.which", return_value="/usr/bin/espeak-ng"):
        assets = doctor.check_assets()
    w = next(a for a in assets if a.name == "whisper-stt")
    assert w.status == DoctorStatus.OK
    assert w.required is True


def test_whisper_down_with_fix_hint_when_missing():
    with patch("iris.audio.stt.FasterWhisperSTT", return_value=_fake_stt(False)), \
         patch("iris.audio.tts.KokoroTTS", return_value=_fake_tts(True)), \
         patch("iris.doctor.shutil.which", return_value="/usr/bin/espeak-ng"):
        assets = doctor.check_assets()
    w = next(a for a in assets if a.name == "whisper-stt")
    assert w.status == DoctorStatus.DOWN
    assert "missing" in w.detail
    assert "setup_whisper.sh" in w.fix
    assert "IRIS_WHISPER_DIR" in w.fix


def test_kokoro_degraded_not_down_when_missing():
    # espeak-ng fallback exists, so a missing kokoro is DEGRADED (robotic), not DOWN
    with patch("iris.audio.stt.FasterWhisperSTT", return_value=_fake_stt(True)), \
         patch("iris.audio.tts.KokoroTTS", return_value=_fake_tts(False)), \
         patch("iris.doctor.shutil.which", return_value="/usr/bin/espeak-ng"):
        assets = doctor.check_assets()
    k = next(a for a in assets if a.name == "kokoro-tts")
    assert k.status == DoctorStatus.DEGRADED
    assert k.required is False


def test_espeak_absent_when_not_on_path():
    with patch("iris.audio.stt.FasterWhisperSTT", return_value=_fake_stt(True)), \
         patch("iris.audio.tts.KokoroTTS", return_value=_fake_tts(True)), \
         patch("iris.doctor.shutil.which", return_value=None):
        assets = doctor.check_assets()
    e = next(a for a in assets if a.name == "espeak-ng")
    assert e.status == DoctorStatus.ABSENT


def test_provider_failure_reported_unknown_not_raised():
    with patch("iris.audio.stt.FasterWhisperSTT", side_effect=RuntimeError("boom")), \
         patch("iris.audio.tts.KokoroTTS", return_value=_fake_tts(True)), \
         patch("iris.doctor.shutil.which", return_value="/usr/bin/espeak-ng"):
        assets = doctor.check_assets()  # must not raise
    w = next(a for a in assets if a.name == "whisper-stt")
    assert w.status == DoctorStatus.UNKNOWN


# ---------------------------------------------------------------------------
# doctor_main integration — exit codes, JSON, rendering, filtering, advisory
# ---------------------------------------------------------------------------

def test_missing_required_asset_drives_exit_2():
    down = [AssetCheckResult("whisper-stt", DoctorStatus.DOWN, True,
                             detail="missing: venv+model", fix="run setup")]
    with patch("iris.doctor.check_assets", return_value=down), \
         patch("iris.doctor.check_services", return_value=[]):
        code = doctor.doctor_main(args=[])
    assert code == 2


def test_degraded_optional_asset_does_not_fail_exit_0():
    # kokoro missing falls back to espeak (it's optional) — Iris still works, so
    # the doctor exits 0. Parallels _exit_code skipping non-required services.
    deg = [AssetCheckResult("kokoro-tts", DoctorStatus.DEGRADED, False,
                            detail="missing", fix="run setup")]
    with patch("iris.doctor.check_assets", return_value=deg), \
         patch("iris.doctor.check_services", return_value=[]):
        code = doctor.doctor_main(args=[])
    assert code == 0


def test_degraded_required_asset_drives_exit_1():
    deg = [AssetCheckResult("some-required", DoctorStatus.DEGRADED, True,
                            detail="degraded", fix="run setup")]
    with patch("iris.doctor.check_assets", return_value=deg), \
         patch("iris.doctor.check_services", return_value=[]):
        code = doctor.doctor_main(args=[])
    assert code == 1


def test_json_includes_assets(capsys):
    ok = [AssetCheckResult("whisper-stt", DoctorStatus.OK, True, detail="/m/whisper")]
    with patch("iris.doctor.check_assets", return_value=ok), \
         patch("iris.doctor.check_services", return_value=[]):
        doctor.doctor_main(args=["--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["assets"][0]["name"] == "whisper-stt"
    assert data["assets"][0]["status"] == "ok"
    assert data["assets"][0]["required"] is True


def test_setup_block_printed_for_non_ok_asset(capsys):
    down = [AssetCheckResult("whisper-stt", DoctorStatus.DOWN, True,
                             detail="missing: venv+model",
                             fix="scripts/setup_whisper.sh --shared")]
    with patch("iris.doctor.check_assets", return_value=down), \
         patch("iris.doctor.check_services", return_value=[]):
        doctor.doctor_main(args=[])
    out = capsys.readouterr().out
    assert "Setup" in out
    assert "setup_whisper.sh" in out


def test_setup_block_absent_when_all_ok(capsys):
    ok = [AssetCheckResult("whisper-stt", DoctorStatus.OK, True, detail="ok", fix="")]
    with patch("iris.doctor.check_assets", return_value=ok), \
         patch("iris.doctor.check_services", return_value=[]):
        doctor.doctor_main(args=[])
    assert "Setup" not in capsys.readouterr().out


def test_check_flag_filters_assets(capsys):
    assets = [
        AssetCheckResult("whisper-stt", DoctorStatus.OK, True, detail="x"),
        AssetCheckResult("kokoro-tts", DoctorStatus.OK, False, detail="y"),
    ]
    with patch("iris.doctor.check_assets", return_value=assets), \
         patch("iris.doctor.check_services", return_value=[]):
        doctor.doctor_main(args=["--check=whisper-stt"])
    out = capsys.readouterr().out
    assert "whisper-stt" in out
    assert "kokoro-tts" not in out


def test_sco_advisory_when_no_nodes(capsys, monkeypatch):
    monkeypatch.setenv("IRIS_AUDIO", "tincan-sco")
    with patch("iris.doctor.check_assets", return_value=[]), \
         patch("iris.doctor.check_services", return_value=[]), \
         patch("iris.audio.endpoint.discover_sco_nodes", return_value=(None, None)):
        doctor.doctor_main(args=[])
    assert "active call" in capsys.readouterr().out


def test_no_sco_advisory_when_not_sco_mode(capsys, monkeypatch):
    monkeypatch.delenv("IRIS_AUDIO", raising=False)
    with patch("iris.doctor.check_assets", return_value=[]), \
         patch("iris.doctor.check_services", return_value=[]):
        doctor.doctor_main(args=[])
    assert "active call" not in capsys.readouterr().out


def test_json_includes_config_block(capsys):
    with patch("iris.doctor.check_assets", return_value=[]), \
         patch("iris.doctor.check_services", return_value=[]):
        doctor.doctor_main(args=["--json"])
    cfg = json.loads(capsys.readouterr().out)["config"]
    assert "path" in cfg and "found" in cfg and "home" in cfg


def test_human_output_shows_config_line(capsys):
    with patch("iris.doctor.check_assets", return_value=[]), \
         patch("iris.doctor.check_services", return_value=[]):
        doctor.doctor_main(args=[])
    assert "config:" in capsys.readouterr().out



# ---------------------------------------------------------------------------
# call-card enrichment check (ti-0c90n) — probes the DAEMON's interpreter
# ---------------------------------------------------------------------------

def _enrichment_result(monkeypatch, probe_rc: int):
    from iris import doctor as doc
    monkeypatch.setattr(doc, "_daemon_python", lambda: "/usr/bin/python3.14")
    real_run = doc.subprocess.run

    def fake_run(cmd, **kw):
        if cmd[0] == "/usr/bin/python3.14":
            return subprocess.CompletedProcess(cmd, probe_rc, "", "boom" if probe_rc else "")
        return real_run(cmd, **kw)

    monkeypatch.setattr(doc.subprocess, "run", fake_run)
    results = doc.check_assets()
    return next(r for r in results if r.name == "call-card-enrichment")


def test_enrichment_ok_when_daemon_python_imports_deps(monkeypatch):
    from iris.doctor import DoctorStatus
    r = _enrichment_result(monkeypatch, probe_rc=0)
    assert r.status is DoctorStatus.OK


def test_enrichment_degraded_with_fix_when_deps_missing(monkeypatch):
    """The mom-call gap: enrichment silently skipped on every call because the
    daemon env lacked pydantic — the doctor must name it and give the fix."""
    from iris.doctor import DoctorStatus
    r = _enrichment_result(monkeypatch, probe_rc=1)
    assert r.status is DoctorStatus.DEGRADED
    assert "pip install" in (r.fix or "")


# ---------------------------------------------------------------------------
# check_call_card_enrichment timeout_s (ti-hxqpz item 10) — heartbeat calls
# this with timeout_s=3.0 instead of the CLI's own 20.0 default.
# ---------------------------------------------------------------------------


def test_enrichment_propagates_custom_timeout_to_subprocess_run(monkeypatch):
    monkeypatch.setattr(doctor, "_daemon_python", lambda: "/usr/bin/python3.14")
    captured = {}

    def fake_run(cmd, **kw):
        captured["timeout"] = kw.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    doctor.check_call_card_enrichment(timeout_s=3.0)

    assert captured["timeout"] == 3.0


def test_enrichment_default_timeout_is_20_when_called_without_override(monkeypatch):
    monkeypatch.setattr(doctor, "_daemon_python", lambda: "/usr/bin/python3.14")
    captured = {}

    def fake_run(cmd, **kw):
        captured["timeout"] = kw.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    doctor.check_call_card_enrichment()

    assert captured["timeout"] == 20.0
