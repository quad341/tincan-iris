"""Preferences store — per-contact tone and register, persisted as JSON.

Preferences are keyed by *context* (a contact ID, phone number, or any opaque
string the caller associates with the current call). Within each context, prefs
are flat ``key: value`` strings — e.g. ``tone = "warm and casual"``.

Example:
    store.set("contact:mom", "tone", "warm and casual")
    store.set("contact:mom", "formality", "informal")
    store.get("contact:mom", "tone")  # "warm and casual"
    store.hint("contact:mom")          # "tone: warm and casual; formality: informal"

The hint format is what ``Brain`` injects into Tier1's system prompt so the
local model naturally adopts the right register without extra scaffolding.
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = Path.home() / ".local" / "share" / "iris" / "prefs.json"


class PreferencesStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self, data: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def set(self, context: str, key: str, value: str) -> None:
        data = self._load()
        data.setdefault(context, {})[key] = value
        self._save(data)

    def get(self, context: str, key: str, default: str = "") -> str:
        return self._load().get(context, {}).get(key, default)

    def get_all(self, context: str) -> dict[str, str]:
        return dict(self._load().get(context, {}))

    def delete(self, context: str, key: str) -> bool:
        data = self._load()
        ctx = data.get(context, {})
        if key not in ctx:
            return False
        del ctx[key]
        if not ctx:
            del data[context]
        else:
            data[context] = ctx
        self._save(data)
        return True

    def hint(self, context: str) -> str:
        """One-liner injected into the Tier1 system prompt to set register/tone.

        Returns empty string if no prefs are set for this context.
        """
        prefs = self.get_all(context)
        if not prefs:
            return ""
        return "; ".join(f"{k}: {v}" for k, v in prefs.items())

    def contexts(self) -> list[str]:
        return list(self._load())
