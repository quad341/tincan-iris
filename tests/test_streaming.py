"""Tests for StreamingTranscriber. Subprocess is not spawned — command building
and the JSON read-loop are exercised directly, so these run anywhere."""
from __future__ import annotations

from iris.audio.streaming import StreamingTranscriber


def test_recorder_cmd_default_and_named_source():
    st = StreamingTranscriber(lambda t: None)
    cmd = st._recorder_cmd()
    assert cmd[:2] == ["parecord", "--raw"]
    assert not any(a.startswith("--device=") for a in cmd)
    st2 = StreamingTranscriber(lambda t: None, source="far_end")
    assert "--device=far_end" in st2._recorder_cmd()


def test_worker_cmd_isolated_with_paths():
    st = StreamingTranscriber(lambda t: None, python="/x/py", model="/x/m")
    cmd = st._worker_cmd()
    assert cmd[:3] == ["unshare", "-rn", "/x/py"]
    assert "/x/m" in cmd and "--min-silence-ms" in cmd


def test_worker_cmd_without_isolation():
    st = StreamingTranscriber(lambda t: None, python="/x/py", model="/x/m", isolate=False)
    assert st._worker_cmd()[0] == "/x/py"


class _FakeProc:
    def __init__(self, lines):
        self.stdout = iter(lines)

    def poll(self):
        return None


def test_read_loop_dispatches_text_and_sets_ready():
    got: list = []
    st = StreamingTranscriber(got.append)
    st._worker = _FakeProc([
        b'{"ready": true}\n',
        b'{"text": "hello there"}\n',
        b'not json\n',
        b'{"text": "how are you"}\n',
    ])
    st._read_loop()
    assert got == ["hello there", "how are you"]
    assert st._ready.is_set()
