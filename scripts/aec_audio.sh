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

STATE="${XDG_RUNTIME_DIR:-/tmp}/iris_aec.module"   # holds: <module_id> <mic> <spk>
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

down() {
    unbridge || true
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
    down)     down     ;;
    *) echo "usage: $0 {up|bridge|status|unbridge|down}" >&2; exit 2 ;;
esac
