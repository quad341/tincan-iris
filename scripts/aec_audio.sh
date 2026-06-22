#!/usr/bin/env bash
# Acoustic Echo Cancellation for headphone-free HFP/SCO phone calls — true
# speakerphone mode (ti-gbz4 / ti-gbz4.3).
#
# THE ECHO LOOP THIS KILLS — the far party hearing their OWN voice come back:
#
#   far party ──SCO downlink (bluez_input)──┐
#                                           ▼
#   Iris TTS ─────────────────────────► iris_aec_sink ──► your speakers
#                                           │  (everything you hear = the AEC reference)
#   your mic ──► [WebRTC AEC3: subtract reference] ──► iris_aec_src ──┬─► SCO uplink (bluez_output) ─► far party
#                                                                     └─► Iris push-to-talk (cleaned)
#
# TWO invariants — break either and the far party still hears echo:
#
#   1. The REFERENCE must contain the FAR PARTY. Everything you hear — the
#      far-party downlink AND Iris's voice — is routed through iris_aec_sink, so
#      it is all in the AEC reference and all gets subtracted from your mic.
#      (The previous version referenced only Iris's TTS monitor; the far party's
#      downlink reached the speakers by a separate route and was never in the
#      reference, so the canceller structurally could not remove it. That was the
#      root-cause bug behind "the far end says I sound echo-y".)
#
#   2. The CLEAN mic must be what the FAR PARTY hears. iris_aec_src (the
#      echo-cancelled, AGC-normalised, denoised mic) is linked directly onto the
#      SCO uplink, replacing the raw mic. (Previously iris_aec_src was a side
#      branch only Iris's push-to-talk consumed; the far party still received the
#      raw, echo-laden physical mic over HFP.)
#
# LIBRARY: PipeWire loads WebRTC AEC3 (webrtc-audio-processing v2) via
# aec_method=webrtc — the same canceller Chrome/Meet use. It is already the best
# software AEC available on Linux; there is no better library to swap to. The
# wins here are the routing invariants above plus the aec_args tuning below.
#
# Wired mic + wired speakers (the operator's setup) share the host audio clock,
# so there is no Bluetooth clock-drift in the echo loop — AEC3 converges cleanly.
# The SCO link's own clock lives only at the downlink-in / uplink-out boundary,
# outside the mic<->speaker echo path.
#
# ── Usage ────────────────────────────────────────────────────────────────────
#   scripts/aec_audio.sh up        # load the AEC module (before the call; inert until bridged)
#   # ... place / answer the HFP call so the SCO nodes exist ...
#   scripts/aec_audio.sh bridge    # wire the live SCO downlink/uplink into the AEC
#   scripts/aec_audio.sh status    # inspect the live graph (use this to verify/debug)
#   scripts/aec_audio.sh unbridge  # drop the SCO links (e.g. between calls)
#   scripts/aec_audio.sh down      # unbridge + unload, restore
#
# Launch Iris on the call with:
#   IRIS_AUDIO=tincan-sco IRIS_AEC=1 python -m iris.console
#
# ── Tuning (env overrides) ───────────────────────────────────────────────────
#   IRIS_AEC_MIC   capture device   (default: current default source at `up` time)
#   IRIS_AEC_SPK   playback device  (default: current default sink   at `up` time)
#   IRIS_AEC_ARGS  WebRTC AEC3 args (default below). To A/B AGC off (often a
#                  cleaner canceller at the cost of mic auto-leveling):
#                    IRIS_AEC_ARGS='webrtc.gain_control=0 webrtc.noise_suppression=1 webrtc.high_pass_filter=1'
#
# NOTE: the SCO `bridge`/`unbridge`/`status` paths use pw-link because the bluez
# SCO nodes are native PipeWire nodes invisible to PulseAudio (pactl/paplay).
# They exist only while a call is connected and embed the device MAC, so they are
# discovered fresh each call and never persisted.
set -euo pipefail

STATE="${XDG_RUNTIME_DIR:-/tmp}/iris_aec.module"     # holds: <module_id> <mic> <spk>
DEFAULTS="${XDG_RUNTIME_DIR:-/tmp}/iris_aec.defaults" # saved pre-AEC default source/sink
AEC_SRC="iris_aec_src"
AEC_SINK="iris_aec_sink"

# Default WebRTC AEC3 tuning. AGC + NS + high-pass on (preserves the prior
# "no manual mic boost" behaviour); extended_filter helps a longer echo tail.
DEFAULT_AEC_ARGS='webrtc.gain_control=1 webrtc.noise_suppression=1 webrtc.high_pass_filter=1 webrtc.extended_filter=1'

# --- SCO node discovery (native PipeWire; see discover_sco_nodes in endpoint.py) ---
_sco_uplink()   { pw-link -i 2>/dev/null | sed 's/:.*//' | grep -m1 '^bluez_output' || true; }  # sink: your voice -> far party
_sco_downlink() { pw-link -o 2>/dev/null | sed 's/:.*//' | grep -m1 '^bluez_input'  || true; }  # source: far party -> you

# Link every output port of $1 to the input ports of $2 (fans a mono source out
# to all sink channels; tolerant of channel-count mismatch). pw-link node-name
# form links matching ports; we enumerate to stay robust to mono<->stereo.
_link() {  # _link <out_node> <in_node>
    local out="$1" in="$2" op ip i=0
    local -a outs ins
    mapfile -t outs < <(pw-link -o 2>/dev/null | grep "^${out}:")
    mapfile -t ins  < <(pw-link -i 2>/dev/null | grep "^${in}:")
    if [[ ${#outs[@]} -eq 0 || ${#ins[@]} -eq 0 ]]; then
        echo "  ! no ports for ${out} -> ${in} (is the call up?)" >&2
        return 1
    fi
    for ip in "${ins[@]}"; do
        op="${outs[i]:-${outs[0]}}"        # reuse first out port if fewer outs than ins (mono->stereo)
        pw-link "$op" "$ip" 2>/dev/null && echo "  linked  $op  ->  $ip" || true
        ((i++)) || true
    done
}

_unlink() {  # _unlink <out_node> <in_node> — best-effort disconnect
    local out="$1" in="$2" op ip
    while read -r op; do
        while read -r ip; do
            pw-link -d "$op" "$ip" 2>/dev/null || true
        done < <(pw-link -i 2>/dev/null | grep "^${in}:")
    done < <(pw-link -o 2>/dev/null | grep "^${out}:")
}

# RMS amplitude (0..1) of a WAV via sox; optional 2nd arg = measure only the
# trailing N seconds (the post-convergence window of the adaptive filter).
_rms() {  # _rms <wav> [tail_seconds]
    local f="$1" tailsec="${2:-}"
    if [[ -n "$tailsec" ]] && sox "$f" /tmp/iris_aec_tail.wav trim "-${tailsec}" 2>/dev/null; then
        f=/tmp/iris_aec_tail.wav
    fi
    sox "$f" -n stat 2>&1 | awk '/RMS +amplitude/{print $3}'
}

up() {
    if [[ -s "$STATE" ]]; then
        echo "AEC already loaded (module $(awk '{print $1}' "$STATE")). Run '$0 down' first." >&2
        exit 1
    fi
    local mic spk args
    mic="${IRIS_AEC_MIC:-$(pactl get-default-source)}"
    spk="${IRIS_AEC_SPK:-$(pactl get-default-sink)}"
    args="${IRIS_AEC_ARGS:-$DEFAULT_AEC_ARGS}"
    echo "==> loading WebRTC AEC3 (iris_aec_sink / iris_aec_src)"
    echo "    mic (capture) : $mic"
    echo "    spk (playback): $spk"
    echo "    aec_args      : $args"
    local id
    id=$(pactl load-module module-echo-cancel \
        aec_method=webrtc \
        source_master="$mic" \
        sink_master="$spk" \
        source_name="$AEC_SRC" \
        sink_name="$AEC_SINK" \
        source_properties=device.description=Iris_AEC_Mic \
        sink_properties=device.description=Iris_AEC_Speaker \
        aec_args="$args")
    echo "$id $mic $spk" > "$STATE"
    echo "==> AEC ready (module $id). Iris's monitor + the far-party downlink both"
    echo "    feed iris_aec_sink (the reference). Now place the call, then: $0 bridge"
}

bridge() {
    [[ -s "$STATE" ]] || { echo "AEC not loaded — run '$0 up' first." >&2; exit 1; }
    local up_node down_node
    up_node="$(_sco_uplink)"; down_node="$(_sco_downlink)"
    if [[ -z "$up_node" || -z "$down_node" ]]; then
        echo "No live SCO nodes found — is an HFP call connected on the dongle?" >&2
        echo "  uplink (bluez_output): ${up_node:-<none>}"  >&2
        echo "  downlink (bluez_input): ${down_node:-<none>}" >&2
        exit 1
    fi
    echo "==> SCO nodes: downlink=$down_node  uplink=$up_node"
    # Invariant 1: far-party downlink -> AEC reference (and thus your speakers).
    # First drop any direct downlink->speaker route so the far party is heard
    # ONLY through the reference sink (else the direct copy echoes uncancelled).
    echo "==> routing far-party downlink into the AEC reference (iris_aec_sink)"
    while read -r sink; do
        [[ "$sink" == "$AEC_SINK" ]] && continue
        _unlink "$down_node" "$sink"
    done < <(pw-link -i 2>/dev/null | sed 's/:.*//' | sort -u)
    _link "$down_node" "$AEC_SINK"
    # Invariant 2: cleaned mic -> SCO uplink (what the far party hears).
    echo "==> routing the cleaned mic (iris_aec_src) onto the SCO uplink"
    _link "$AEC_SRC" "$up_node"
    echo "==> bridged. Verify with: $0 status"
}

unbridge() {
    local up_node down_node
    up_node="$(_sco_uplink)"; down_node="$(_sco_downlink)"
    [[ -n "$down_node" ]] && _unlink "$down_node" "$AEC_SINK"
    [[ -n "$up_node"   ]] && _unlink "$AEC_SRC" "$up_node"
    echo "==> SCO bridges removed."
}

status() {
    echo "── AEC module ───────────────────────────────────────────"
    if [[ -s "$STATE" ]]; then
        read -r id mic spk < "$STATE"
        echo "  module $id   mic=$mic   spk=$spk"
        pactl list short sources 2>/dev/null | grep -E "$AEC_SRC|$AEC_SINK" || true
    else
        echo "  (not loaded — run '$0 up')"
    fi
    echo "── SCO nodes ────────────────────────────────────────────"
    echo "  downlink (far party -> you) : $(_sco_downlink || echo '<none — no call?>')"
    echo "  uplink   (you -> far party) : $(_sco_uplink   || echo '<none — no call?>')"
    echo "── Reference feed (should include far-party downlink + Iris) ─"
    pw-link -l 2>/dev/null | grep -A3 "^${AEC_SINK}" | sed 's/^/  /' || echo "  (none)"
    echo "── Uplink feed (should be iris_aec_src, the cleaned mic) ─────"
    local up_node; up_node="$(_sco_uplink)"
    [[ -n "$up_node" ]] && pw-link -l 2>/dev/null | grep -B3 "^${up_node}" | sed 's/^/  /' || echo "  (no live uplink)"
}

selftest() {
    # Acoustic-loopback ERLE measurement — validates the canceller WITHOUT a call.
    # Plays telephony-band noise out the speakers (through iris_aec_sink, so it is
    # the AEC reference) and compares the residual in the cleaned mic (iris_aec_src)
    # to the raw mic. ERLE = 20*log10(raw/cleaned) dB = how much echo was removed.
    # Run with AGC OFF (webrtc.gain_control=0) and NO other audio playing, or the
    # numbers are muddied (AGC changes the gain; un-referenced audio like music is
    # not in the reference, so it shows up as uncancelled residual).
    [[ -s "$STATE" ]] || { echo "AEC not loaded — run '$0 up' first." >&2; exit 1; }
    command -v ffmpeg >/dev/null && command -v sox >/dev/null \
        || { echo "selftest needs ffmpeg + sox." >&2; exit 1; }
    local id mic spk; read -r id mic spk < "$STATE"
    local dur=8 tailsec=4 sig=/tmp/iris_aec_test.wav
    local raw=/tmp/iris_aec_raw.wav clean=/tmp/iris_aec_clean.wav floor=/tmp/iris_aec_floor.wav
    echo "AEC self-test (acoustic loopback ERLE) — mic=$mic  spk=$spk"
    echo "  Plays ~${dur}s of test noise out the speakers. AGC should be off; pause other audio."
    sox -n -r 48000 -c 2 "$sig" synth "$dur" pinknoise sinc 300-3400 gain -3 2>/dev/null
    echo "==> [1/2] noise floor — cleaned mic with no playback (${tailsec}s)…"
    ffmpeg -hide_banner -loglevel error -f pulse -i iris_aec_src -t "$tailsec" -ac 1 -ar 48000 -y "$floor" </dev/null
    local f_floor; f_floor=$(_rms "$floor")
    echo "==> [2/2] echo run — playing noise, capturing raw + cleaned mic (${dur}s)…"
    ffmpeg -hide_banner -loglevel error -f pulse -i "$mic"       -t "$dur" -ac 1 -ar 48000 -y "$raw"   </dev/null &
    ffmpeg -hide_banner -loglevel error -f pulse -i iris_aec_src -t "$dur" -ac 1 -ar 48000 -y "$clean" </dev/null &
    paplay --device="$AEC_SINK" "$sig"
    wait
    local f_raw f_clean; f_raw=$(_rms "$raw" "$tailsec"); f_clean=$(_rms "$clean" "$tailsec")
    python3 - "$f_raw" "$f_clean" "$f_floor" <<'PY'
import sys, math
raw, clean, floor = (float(x) if x else 0.0 for x in sys.argv[1:4])
db = lambda a, b: 20*math.log10(a/b) if a > 0 and b > 0 else float('nan')
print(f"  raw mic (echo present) : RMS {raw:.5f}")
print(f"  cleaned (residual)     : RMS {clean:.5f}")
print(f"  noise floor (silence)  : RMS {floor:.5f}")
erle = db(raw, clean)
over = db(clean, floor)
print(f"  ERLE (echo removed)    : {erle:5.1f} dB")
print(f"  residual above floor   : {over:5.1f} dB")
if erle >= 20 and (math.isnan(over) or over < 6):
    print("  VERDICT: strong — residual at/near the noise floor (eliminating ≈everything).")
elif erle >= 12:
    print("  VERDICT: decent — some residual above floor; tune (AGC off, check routing/delay).")
else:
    print("  VERDICT: weak — echo largely uncancelled. Check the reference routing first.")
PY
    echo "  (raw/cleaned measured over the trailing ${tailsec}s, after the filter converges.)"
}

# --- always-on mode: make the cancelled devices the system defaults ---
# After `up`, this points every app at the echo-cancelled mic + the reference
# sink, so echo cancellation is ambient and app-agnostic (no per-call bridge for
# app audio like Discord/Zoom — they just use the defaults). The SCO `bridge` is
# still needed for native bluez phone-call nodes. Trade-off: ALL audio routes
# through the canceller (music, videos too) and picks up a little latency.
# Intended to be run at login via a user service (see scripts/iris-aec.service).
default() {
    [[ -s "$STATE" ]] || { echo "AEC not loaded — run '$0 up' first." >&2; exit 1; }
    if [[ ! -s "$DEFAULTS" ]]; then          # save the pre-AEC defaults once
        { pactl get-default-source; pactl get-default-sink; } > "$DEFAULTS"
    fi
    pactl set-default-source "$AEC_SRC"
    pactl set-default-sink   "$AEC_SINK"
    echo "==> $AEC_SRC / $AEC_SINK are now the system defaults."
    echo "    Every app captures the echo-cancelled mic and plays into the AEC"
    echo "    reference — ambient, app-agnostic echo cancellation. '$0 down' restores."
}

_restore_defaults() {
    [[ -s "$DEFAULTS" ]] || return 0
    local src sink; { read -r src; read -r sink; } < "$DEFAULTS"
    [[ -n "$src"  ]] && pactl set-default-source "$src"  2>/dev/null || true
    [[ -n "$sink" ]] && pactl set-default-sink   "$sink" 2>/dev/null || true
    rm -f "$DEFAULTS"
    echo "==> restored previous default source/sink."
}

down() {
    unbridge || true
    _restore_defaults
    if [[ ! -s "$STATE" ]]; then
        echo "No saved AEC module." >&2
        pactl list short modules | grep -q module-echo-cancel \
            && { echo "Unloading stray module-echo-cancel by name." >&2; pactl unload-module module-echo-cancel 2>/dev/null || true; }
        exit 0
    fi
    local id; id=$(awk '{print $1}' "$STATE")
    pactl unload-module "$id" 2>/dev/null || true
    rm -f "$STATE"
    echo "==> AEC module $id unloaded."
}

case "${1:-}" in
    up)       up       ;;
    bridge)   bridge   ;;
    unbridge) unbridge ;;
    status)   status   ;;
    selftest) selftest ;;
    default)  default  ;;
    down)     down     ;;
    *) echo "usage: $0 {up|bridge|status|selftest|default|unbridge|down}" >&2; exit 2 ;;
esac
