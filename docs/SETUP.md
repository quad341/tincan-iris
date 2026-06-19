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
| **Calendar** | a Google OAuth token *(setup pending)* | "am I free at 3pm?", "add an event …" |
| **Messages** (SMS/MAP) | a running `tincand` *(pending)* | "read my texts", "text … …" |

### Email (Gmail example)

1. `config.toml` `[email]`: `imap_host = "imap.gmail.com"`, `smtp_host = "smtp.gmail.com"`, `user = "you@gmail.com"`.
2. Create a Gmail **App Password** (Google Account → Security → 2-Step
   Verification → App passwords) and put it in `secrets.toml` `[email] password`.
3. Verify: `iris-email-check`. The email skills then auto-register and qwen can
   read / triage / draft replies (bodies are summarized **locally** — never sent
   to the cloud tier).

### Calendar (status)

The calendar skills (free/busy, create, move) are built and wired — they
register the moment a Google OAuth token exists. The `iris auth gcal` flow that
mints that token needs a Google Cloud **OAuth client** (yours) and an
interactive browser consent, so it's a guided one-time step (see the open
calendar issue).

---

## Troubleshooting

- **`python -m iris.console` fails on startup** → run `python -m iris.doctor`;
  it shows which asset is missing and the exact fix command.
- **`IRIS_AUDIO=tincan-sco` can't find audio** → the SCO nodes only exist
  *during* a call; launch the console after the call connects (the doctor warns
  about this).
- **A skill you expected isn't available** → its dependency isn't configured;
  `iris doctor` and the table above show what each needs.
