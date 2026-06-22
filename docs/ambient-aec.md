# Always-on audio: ambient echo cancellation + iris ride-along

How the echo canceller and iris fit together, from a per-call tool today toward
an always-on assistant. Three layers, each independently useful and building on
the last.

## The canceller has two modes

`scripts/aec_audio.sh` loads WebRTC AEC3 (`webrtc-audio-processing` v2 — the same
canceller Chrome/Meet use) as `iris_aec_src` (the cleaned mic) and `iris_aec_sink`
(the reference, which also feeds your speakers).

- **Per-call** (`up` → `bridge` → `down`): wire one live call's far-party stream
  into the reference and the cleaned mic onto its uplink. Needed for native
  Bluetooth phone-call (SCO) nodes, which exist only while a call is connected.
  Validated live: 31.4 dB bench, 15.8 dB on a pure-tone SCO call (floor-limited),
  **34.4 dB on a real broadband voice call with the far party confirming zero echo.**
- **Ambient** (`up` → `default`): make `iris_aec_src` / `iris_aec_sink` the *system
  defaults*. Every app — Discord, Zoom, browser, games — then captures a clean mic
  and lands its output in the reference automatically, with no per-call setup. This
  is the cleaner architecture for ordinary app audio (one default sink → no
  competing-route bridging).

## Layer 1 — ambient AEC (the foundation)

Run the canceller at login and set it as the default. `scripts/iris-aec.service`
is a standalone systemd **user** unit that does `up` + `default` on start and
restores your previous defaults on stop:

```bash
cp scripts/iris-aec.service ~/.config/systemd/user/
# edit AEC_SCRIPT to the absolute path of scripts/aec_audio.sh, then:
systemctl --user daemon-reload
systemctl --user enable --now iris-aec
pactl get-default-source   # expect iris_aec_src
```

**Trade-off:** all audio (music, video too) routes through the canceller and picks
up a little latency. **Caveat (validate on a relogin):** WirePlumber owns
default-target routing and may re-assert its own choice when devices change. If the
AEC defaults don't stick, add a WirePlumber drop-in pinning
`default.configured.audio.source/sink` to the AEC nodes. Not yet validated across a
relogin.

## Layer 2 — always-on iris (your ambient assistant)

The whisper / kokoro / brain / llama services run persistently (the
`iris/services/*.service.tmpl` units — once the `-m` template bug is fixed, see
ti-t8dy: they invoke `python iris/_whisper_server.py` as a script, which shadows
the stdlib `calendar` and crash-loops; the fix is `-m iris._whisper_server`). With
the ambient mic as default, iris continuously hears you, wake-word gated — "hey
iris" works anywhere, no console to launch.

## Layer 3 — call-aware ride-along (the dream)

iris subscribes to call events and auto-attaches its far-ear + the AEC per call.
This is already the designed path: tincand emits `im.tincan.Calls`
CallConnected / CallEnded, and the SCO endpoint (`TincanSCOAudio`) carries a
built-in far-ear (the downlink). The `TincanSCOAudio` docstring describes the
future `TincanCallControl` that answers by policy, binds on CallConnected, and
drops on CallEnded. Discord / Zoom are the same pattern (event → attach far-ear),
each its own integration.

Launch today (manual): `IRIS_AUDIO=tincan-sco IRIS_AEC=1 iris console`, then press
`[l]` (hear you) and `[f]` (hear the far party). Open questions to validate first:
can one whisper server run both ears at once, and does the console need the
`iris-brain` service to actually respond?

## The privacy split (by design)

Always-on is fine for some of this and a deliberate choice for the rest:

- **Always-on, no asterisk:** ambient AEC (cancelling ≠ recording) + iris hearing
  *you* (your consent).
- **Deliberate, gated:** iris hearing *them* — the far party. Off by default
  (far-party transcription gate, ti-gbz4.2; trust boundaries, ADR-0002/0005). The
  intended opt-in is an **announcement first** — iris introduces itself to the far
  party before it listens (ti-rqhn) — so no one is silently AI-captured.
