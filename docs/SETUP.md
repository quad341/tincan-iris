# Setting up & running Iris

Everything Iris needs lives under **one home** — `IRIS_HOME` (default
`~/.local/share/iris`). Set it once in your shell (or rely on the default):

```bash
export IRIS_HOME=~/.local/share/iris   # optional; this is the default
```

`IRIS_HOME` holds your `config.toml`, `secrets.toml`, the memory/notes/roster
DBs, and (optionally) the shared model assets. Check the whole setup any time
with:

```bash
python -m iris.doctor          # assets + services + config, one screen
```

---

## 1. The brain (local model)

Iris's reasoning runs on a local **OpenAI/llama.cpp-compatible server on
`http://127.0.0.1:8080`** (`qwen_base_url`). If you already run `llama.cpp`
there, **that's your brain** — nothing else to install. `iris doctor` detects it
by probing the port, whether or not it's a managed systemd unit:

```
iris-llama   ✓ ok   yes   running (no systemd unit)
```

(Optionally run it as a managed service with `iris-install-services`.)

## 2. Voice assets (STT + TTS)

Speech-to-text (faster-whisper) and text-to-speech (Kokoro) run in their own
3.12 venvs, shelled out network-isolated. Provision them once:

```bash
scripts/setup_whisper.sh            # into this repo
scripts/setup_kokoro.sh
# …or share across every clone (installs under $IRIS_HOME):
scripts/setup_whisper.sh --shared
scripts/setup_kokoro.sh --shared
```

Resolution is **env override → repo-local → shared `$IRIS_HOME` → repo
default**, so once you `--shared` install, *any* clone just works — no
per-clone setup, no env-pointing. `iris doctor` shows exactly what resolved.
(Kokoro is optional — espeak-ng is the automatic fallback.)

## 3. Run

```bash
python -m iris.doctor            # verify (exit 0 = nothing broken)
iris-home                        # out-of-call dashboard (chat to Iris)
python -m iris.console           # in-call console (needs an active call)
```

---

## Configuration — `config.toml`

All launch knobs live in `$IRIS_HOME/config.toml` (copy `config.toml.example`).
**Precedence: an `IRIS_*` env var > this file > built-in default** — so the file
sets your machine's defaults and an env var still overrides per-launch.

```toml
[audio]
mode = ""                       # "" local mic/speakers; "tincan-sco" rides a live call
[voice]
kokoro_voice = "af_heart"
[assets]
whisper_model_size = "small.en"
```

See `config.toml.example` for every section (audio, assets, voice, email,
screening, take-message, servers, storage).

## Secrets — `secrets.toml`

Credentials never go in `config.toml`. Put them in `$IRIS_HOME/secrets.toml`
(copy `secrets.toml.example`, `chmod 600` — it's gitignored). An `IRIS_*` env
var still overrides.

```toml
[email]
password = "your-gmail-app-password"   # -> IRIS_EMAIL_PASSWORD
```

---

## Connectors (what Iris can do, out of call)

Iris registers a skill **only when its dependency is present**, so qwen offers
exactly what works. Past setup, it's all natural language — just ask.

| Connector | Needs | Then ask… |
|---|---|---|
| **Notes** | nothing (local) | "take a note: …", "what are my notes?" |
| **Web search** | nothing | "search the web for …" |
| **Roster** (contacts) | nothing (local) | "add a contact …", "what's …'s number?" |
| **Email** | `[email]` config + app-password | "any important email?", "reply to … saying …" |
| **Calendar** | `iris-auth gcal` (Google OAuth) | "am I free at 3pm?", "add an event …" |
| **Messages** (SMS/MAP) | a running `tincand` *(pending)* | "read my texts", "text … …" |

### Email (Gmail) — one command

```bash
iris-auth gmail                 # or: iris-auth gmail you@gmail.com
```

It prompts for a Gmail **App Password** (input hidden), verifies the IMAP login,
writes the config + a `chmod 600` secret for you, and confirms. Create the App
Password first — **<https://myaccount.google.com/apppasswords>** (requires
2-Step Verification; this is *not* your normal password). Help article:
<https://support.google.com/mail/answer/185833>. After it succeeds the email
skills auto-register and qwen can read / triage / draft replies (bodies are
summarized **locally** — never sent to the cloud tier). Re-check any time with
`iris-email-check`.

### Calendar (Google) — one command

```bash
iris-auth gcal ~/Downloads/credentials.json     # or just: iris-auth gcal (paste id/secret)
```

First, a one-time Google setup: in **Google Cloud Console** create an OAuth
**"Desktop app"** client and **enable the Google Calendar API** — when enabling
it, **double-check the project selector (top bar) shows the same project your
OAuth client is in**. It can silently default to a different project, and then
calls fail `403 SERVICE_DISABLED`. Download the client's `credentials.json`.
Then `iris-auth gcal` opens your browser for consent, catches the loopback
redirect, saves a **refreshable** token (`chmod 600`), and runs a quick test
read — so a not-yet-enabled API is caught right there, with a project-pinned
link to fix it. If consent loops or fails, open the printed URL in a **private /
incognito window** — that forces a clean Google account picker. The calendar
skills (free/busy, create, move) then auto-register and qwen can field "am I
free at 3pm?" / "add an event …". Access tokens refresh automatically.

---

## Troubleshooting

- **`python -m iris.console` fails on startup** → run `python -m iris.doctor`;
  it shows which asset is missing and the exact fix command.
- **`IRIS_AUDIO=tincan-sco` can't find audio** → the SCO nodes only exist
  *during* a call; launch the console after the call connects (the doctor warns
  about this).
- **A skill you expected isn't available** → its dependency isn't configured;
  `iris doctor` and the table above show what each needs.
