# AGENTS.md

Working in this repo? Use the `Makefile` — it's the canonical entry point
for every dev/ops command. Run `make help` for the full, current list.

## Dev loop

| Target | What it does |
|---|---|
| `make install` | `pip install -e '.[console,call-card]' pytest ruff` |
| `make lint` | `ruff check .` |
| `make test` | `pytest -q` |
| `make verify` | `lint` then `test`, same order as CI — run this before opening a PR |

`make verify` mirrors `.github/workflows/ci.yml` exactly (see the Makefile's
header comment). A green `make verify` locally means CI will be green too.

## Running the stack

| Target | What it does |
|---|---|
| `make up` (alias `make run`) | Bring up whisper/kokoro, check llama + tincand, launch the console |
| `make console` | Launch the operator console (Textual TUI) directly |
| `make doctor` | Health-check assets + services, one screen |
| `make tincan-status` | Deep tincand check (D-Bus/SELinux/BT adapter) |
| `make services` | Install/refresh the systemd user services |

## The daemon (headless call handling)

| Target | What it does |
|---|---|
| `make daemon` | Start the iris daemon in the background (safe to re-run) |
| `make daemon-callcard` | Start the daemon with Call Card capture forced on |
| `make daemon-status` | Show whether the daemon is running |
| `make daemon-stop` | Stop the daemon |
| `make callcard` | Stub — Call Card standalone view isn't wired up yet (ti-913rw) |

## Audio servers

| Target | What it does |
|---|---|
| `make whisper` (alias `make stt`) | Run the whisper STT server |
| `make kokoro` (alias `make tts`) | Run the kokoro TTS server |

## Guardrails

- No target starts/stops/restarts `tincand.service` directly — lifecycle
  stays brokered through `iris up` / `iris doctor`, exactly as today.
  `make tincan-status` is read-only.
- Single CLI actions that take arguments (`iris auth gcal`, `iris dnd on`,
  `iris chat`, `iris listen`, `iris speak`, `iris email-check`) are run
  directly via `iris <cmd>` — there's no Makefile passthrough for them.
- `.github/workflows/ci.yml` and the `install`/`lint`/`test`/`verify`
  targets above must stay in lockstep — edit one, edit both.
