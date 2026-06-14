#!/usr/bin/env bash
# Virtual audio routing so Iris can join an app call (Discord/Zoom) — no Bluetooth.
#
# Graph (no Bluetooth, headphones recommended to avoid acoustic echo):
#   your mic ──loopback──┐
#                        ▼
#   Iris ──► iris_out ──► iris_mic ──► .monitor ──► the app's microphone
#                  └────► your speakers   (so YOU hear Iris too)
#   the app's output ──► your speakers     (so you hear the far end, as usual)
#
# So: the call hears you + Iris; you hear the far end + Iris; Iris hears you.
#
#   scripts/virtual_audio.sh up     # set it all up
#   scripts/virtual_audio.sh down   # tear it all down
#
# Then set the app's INPUT (mic) to "Monitor of Iris_Mic" and run:
#   IRIS_PLAYBACK_TARGET=iris_out python -m iris.console
set -euo pipefail

STATE="${XDG_RUNTIME_DIR:-/tmp}/iris_virtual_audio.modules"

up() {
    if pactl list short sinks | grep -qw iris_mic; then
        echo "iris_mic already exists — run '$0 down' first." >&2
        exit 1
    fi
    : > "$STATE"
    echo "==> null-sink 'iris_mic' (the app's microphone = its monitor)"
    pactl load-module module-null-sink \
        sink_name=iris_mic sink_properties=device.description=Iris_Mic >> "$STATE"
    echo "==> loopback: your mic (@DEFAULT_SOURCE@) -> iris_mic (so the call hears you too)"
    pactl load-module module-loopback \
        source=@DEFAULT_SOURCE@ sink=iris_mic latency_msec=20 source_dont_move=true >> "$STATE"
    local spk
    spk="$(pactl get-default-sink)"
    echo "==> combine-sink 'iris_out' = iris_mic + your speakers ($spk) — so you hear Iris too"
    pactl load-module module-combine-sink \
        sink_name=iris_out slaves="iris_mic,$spk" \
        sink_properties=device.description=Iris_Out >> "$STATE"
    echo "==> remap-source 'Iris_Microphone' (apps hide raw monitors; this shows as a real mic)"
    pactl load-module module-remap-source \
        master=iris_mic.monitor source_name=iris_mic_src \
        source_properties=device.description=Iris_Microphone >> "$STATE"
    cat <<EOF

Ready. Next:
  1. In Discord/Vesktop, set the mic/input to:  Iris_Microphone
  2. Run:  IRIS_PLAYBACK_TARGET=iris_out python -m iris.console
  3. Say "Iris, introduce yourself" — you'll hear her, and so will the call.
Tear down:  $0 down
EOF
}

down() {
    if [[ ! -s "$STATE" ]]; then
        echo "No saved modules — nothing to tear down." >&2
        exit 0
    fi
    # Unload in reverse load order (combine-sink before its slave iris_mic).
    tac "$STATE" | while read -r id; do
        [[ -n "$id" ]] && pactl unload-module "$id" 2>/dev/null || true
    done
    rm -f "$STATE"
    echo "==> removed iris virtual-audio modules."
}

case "${1:-}" in
    up) up ;;
    down) down ;;
    *) echo "usage: $0 {up|down}" >&2; exit 2 ;;
esac
