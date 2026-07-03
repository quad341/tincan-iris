"""NFR-03: the base iris daemon must import without the `call-card` optional extra.

The Call Card DURING feature pulls in ``phonenumbers`` + ``dateparser`` via
``iris.capture.processor``. Those imports must stay deferred behind
``IRIS_CALL_CARD=1`` (a lazy import inside ``main()``), so a user who installs
only the base package — no ``[call-card]`` extra — can still run
``python -m iris.daemon``.

Runs in a subprocess so the blocked-import state is fully isolated from the rest
of the suite (the real suite installs the extra and needs it).
"""
from __future__ import annotations

import subprocess
import sys
import textwrap


def test_base_daemon_imports_without_call_card_deps() -> None:
    code = textwrap.dedent(
        """
        import sys

        # Simulate the `call-card` extra being absent: a None entry makes any
        # `import phonenumbers` / `import dateparser` raise ImportError.
        sys.modules["phonenumbers"] = None
        sys.modules["dateparser"] = None
        sys.modules["dateparser.search"] = None

        # The base daemon module must import cleanly with those libs unavailable.
        import iris.daemon.__main__ as daemon_main
        assert hasattr(daemon_main, "main"), "daemon entrypoint missing"

        # Guard against a false positive: the extractor module *must* fail to
        # import under the same block, proving the deps are genuinely absent.
        try:
            import iris.capture.processor  # noqa: F401
        except ImportError:
            pass
        else:
            raise SystemExit("iris.capture.processor imported despite blocked deps")

        print("NFR03_OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "NFR03_OK" in result.stdout
