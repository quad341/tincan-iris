"""Configuration — provider slots and endpoints.

NO secrets and NO PII live here. Real credentials (OAuth tokens for calendar /
email, etc.) load from the local environment or a gitignored secrets file at
runtime, used only by our own direct-API skill adapters — never committed, and
never handed to the cloud model (see ``docs/adr/0001``).
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Safety invariant — NOT a config key, never moved to Config.proactive_*:
# Iris must NOT speak while a call is in progress without an explicit
# operator approval gesture. Changing this to True would let Iris interrupt
# the far party unbidden, which is the most jarring failure mode in the
# co-pilot model. It must stay a hard-coded constant until that whole path
# (interrupt policy, approval gate, conflict resolution) is designed and shipped.
SPEAK_DURING_CALL: bool = False


@dataclass(frozen=True)
class Config:
    # --- Latency masking. Fire a filler at first_filler_s, repeat every
    # repeat_filler_s; if a lane runs past lane_deadline_s, abandon it and fall
    # back (the box is shared with the city, so the local model can stall).
    first_filler_s: float = 2.0
    repeat_filler_s: float = 6.0
    lane_deadline_s: float = 30.0
    lane_timeout_reply: str = (
        "Sorry — I'm running slow right now. Let me get back to you on that."
    )

    # --- Tier 1: local brain (warm). llama.cpp server, OpenAI/Anthropic-compatible.
    qwen_base_url: str = "http://127.0.0.1:8080"
    qwen_timeout_s: float = 30.0
    qwen_max_tokens: int = 96

    # --- Operator identity (used in disclosure script and ring announcements).
    operator_name: str = ""  # e.g. "Jim" — first name only; blank disables personalisation

    # --- Call Card disclosure (the consent-gate script shown/spoken before
    # capture starts; see iris/daemon/call_card_host.py). Empty string means
    # "use the built-in default script" (_DEFAULT_DISCLOSURE in
    # call_card_host.py) — distinct from the auto-answer TTS disclosure in
    # iris/disclosure.py, which is a separate flow.
    call_card_disclosure_script: str = ""

    # --- Screening (handling_rule='screen'). relay_timeout_secs: how long Iris
    # waits for the operator to decide before auto-pivoting to take_message.
    screening_relay_timeout_secs: float = 20.0

    # --- Tier 2: cloud raw-text tier. Driven ONLY through the vendor TUI
    # (Claude Code), lean + text-only, NEVER tools/MCP. See docs/adr/0001.
    haiku_enabled: bool = True
    haiku_model: str = "claude-haiku-4-5"
    haiku_tmux_session: str = "iris-haiku"
    haiku_ready_timeout_s: float = 40.0
    haiku_system_prompt: str = (
        "You are Iris, answering aloud on the user's behalf. Reply in ONE short, "
        "warm, spoken sentence (under ~30 words). No markdown, no lists, no preamble."
    )

    # --- Memory / embedding (ADR-0003). embedding_model is the GGUF model name for
    # the llama.cpp slot; embedding_dim must match its output dimension.
    # sqlite_vec_path="" means use the system default. db_path="" defaults to
    # ~/.local/share/iris/iris.db at runtime.
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768
    sqlite_vec_path: str = ""
    db_path: str = ""

    # --- Email lane. Disabled when email_imap_host == "" (default).
    # Credentials (IRIS_EMAIL_PASSWORD) load from the environment only — never
    # committed here. Recommended auth: Gmail App Password (Google Account →
    # Security → App passwords). See docs/adr/0001 (no-cloud-PII constraint).
    email_imap_host: str = ""        # e.g. "imap.gmail.com"; empty = disabled
    email_imap_port: int = 993       # SSL port (IMAP4_SSL)
    email_smtp_host: str = ""        # e.g. "smtp.gmail.com"
    email_smtp_port: int = 587       # STARTTLS port
    email_user: str = ""             # e.g. "user@gmail.com"
    email_archive_folder: str = "Archive"  # Gmail: "[Gmail]/All Mail"

    # --- [proactive] — v1 ships disabled; schema is here so operators can see what
    # will be available and enable it in a future release.
    #
    # proactive_enabled        — master gate; False in v1.
    # proactive_classes        — which notification classes to deliver (empty = all
    #                            are suppressed). E.g. ("lookup_done", "calendar").
    # proactive_min_priority   — only deliver notifications at or above this priority
    #                            (0 = critical … 4 = backlog; 2 = medium default).
    # proactive_cooldown_s     — global minimum gap between proactive utterances.
    # proactive_speak_during_listen — allow proactive speech while operator is silent
    #                            (True = safe; SPEAK_DURING_CALL stays False always).
    proactive_enabled: bool = False
    proactive_classes: tuple[str, ...] = field(default_factory=tuple)
    proactive_min_priority: int = 2
    proactive_cooldown_s: float = 60.0
    proactive_speak_during_listen: bool = True

    calendar_nudge_min: int = 30
    calendar_poll_interval_s: float = 300.0

    doctor_timeout_s: float = 2.0
    doctor_deep_timeout_s: float = 5.0

    # --- Multilingual presentation profiles (ti-6371 / ti-joq2).
    language_set: list[str] = field(default_factory=lambda: ["en"])  # ordered BCP-47 tags; Whisper detects top-to-bottom
    default_language: str = "en"
    cadence_default: float = 1.0
    cadence_slow: float = 0.7    # applied per-turn on re-ask trigger
    cadence_range: tuple[float, float] = (0.7, 1.4)
    language_detect_threshold: float = 0.80  # Whisper min confidence


DEFAULT = Config()

_PROACTIVE_STARTUP_NOTICE = (
    "[proactive] Proactive notifications are available but disabled in v1. "
    "To enable, set proactive_enabled=True in your config and choose classes. "
    "See docs/adr/ for design context."
)


def proactive_startup_notice(cfg: Config) -> str | None:
    """Return a one-time startup notice if [proactive] section is at defaults.

    Returns ``None`` when the operator has explicitly configured the section
    (i.e., ``proactive_enabled=True`` or ``proactive_classes`` is non-empty) —
    in that case they already know it exists.  Returns the notice string when
    the section is absent (all defaults), so new operators discover the feature.
    """
    if cfg.proactive_enabled or cfg.proactive_classes:
        return None
    return _PROACTIVE_STARTUP_NOTICE
