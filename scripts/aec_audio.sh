#!/usr/bin/env bash
# Acoustic Echo Cancellation for headphone-free HFP/SCO calls.
#
# Without headphones, Iris's voice comes out of the speaker and the mic picks it
# up — the far party hears an echo.  This loads PipeWire's WebRTC AEC module to
# cancel Iris's voice from the mic before it reaches the push-to-talk capture.
#
# Graph:
#   Iris voice ──► iris_aec_sink ──► your speakers
#                       │ (AEC reference)
#   your mic ──────► [module-echo-cancel] ──► iris_aec_src  ──► push-to-talk
#
# iris_aec_sink replaces the default sink for the operator monitor.
# iris_aec_src  replaces the default mic for push-to-talk capture.
#
# Usage:
#   scripts/aec_audio.sh up     # load the AEC module
#   scripts/aec_audio.sh down   # unload and restore
#
# Then launch Iris with:
#   IRIS_AUDIO=tincan-sco IRIS_AEC=1 python -m iris.console
#
# Verification (operator-gated — requires live HFP call + speakers):
#   1. Run scripts/aec_audio.sh up
#   2. Start an HFP call via tincan
#   3. Launch iris with IRIS_AEC=1
#   4. While Iris is speaking over the speakers, trigger push-to-talk —
#      your voice should be clear and Iris's voice should not echo back.
set -euo pipefail

STATE="${XDG_RUNTIME_DIR:-/tmp}/iris_aec.module"

up() {
    if pactl list short modules | grep -q "module-echo-cancel"; then
        echo "module-echo-cancel already loaded." >&2
        echo "Run '$0 down' first if you want to reload." >&2
        exit 1
    fi
    echo "==> loading WebRTC echo-canceller (iris_aec_sink / iris_aec_src)"
    pactl load-module module-echo-cancel \
        aec_method=webrtc \
        source_name="${IRIS_AEC_SRC:-iris_aec_src}" \
        sink_name="${IRIS_AEC_SINK:-iris_aec_sink}" \
        source_properties=device.description=Iris_AEC_Mic \
        sink_properties=device.description=Iris_AEC_Speaker \
        > "$STATE"
    echo "==> AEC ready. Module ID: $(cat "$STATE")"
    cat <<'EOF'

Ready.  Launch Iris with:
  IRIS_AUDIO=tincan-sco IRIS_AEC=1 python -m iris.console

Iris's monitor now routes through iris_aec_sink (the AEC reference sink).
Push-to-talk captures from iris_aec_src (echo-cancelled mic).
The far party hears a clean microphone — no Iris echo.

Tear down:  scripts/aec_audio.sh down
EOF
}

down() {
    if [[ ! -s "$STATE" ]]; then
        echo "No saved AEC module — nothing to unload." >&2
        # Fallback: unload by name in case the state file was lost.
        if pactl list short modules | grep -q "module-echo-cancel"; then
            echo "Found module-echo-cancel in pactl — unloading by name." >&2
            pactl unload-module module-echo-cancel 2>/dev/null || true
        fi
        exit 0
    fi
    id=$(cat "$STATE")
    pactl unload-module "$id" 2>/dev/null || true
    rm -f "$STATE"
    echo "==> AEC module $id unloaded."
}

case "${1:-}" in
    up)   up   ;;
    down) down ;;
    *) echo "usage: $0 {up|down}" >&2; exit 2 ;;
esac
