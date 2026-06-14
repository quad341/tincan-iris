#!/usr/bin/env bash
# Virtual audio routing so Iris can join an app call (Discord/Zoom) — no Bluetooth.
#
# Creates a PipeWire null-sink "iris_mic"; the app uses its MONITOR as its mic.
# Iris's voice and (with `up`) your real mic both play into iris_mic, so the app
# transmits both. Iris still listens to your real mic for commands.
#
#   scripts/virtual_audio.sh up     # create iris_mic + loop your mic into it
#   scripts/virtual_audio.sh down   # tear it all down
#
# Then set the app's INPUT (mic) to "Monitor of Iris_Mic" and run:
#   IRIS_PLAYBACK_TARGET=iris_mic python -m iris.console
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
    cat <<EOF

Ready. Next:
  1. In Discord/Zoom, set the mic/input to:  Monitor of Iris_Mic
  2. Run:  IRIS_PLAYBACK_TARGET=iris_mic python -m iris.console
  3. Say "Iris, introduce yourself" — the call will hear her.
Tear down:  $0 down
EOF
}

down() {
    if [[ ! -s "$STATE" ]]; then
        echo "No saved modules — nothing to tear down." >&2
        exit 0
    fi
    while read -r id; do
        [[ -n "$id" ]] && pactl unload-module "$id" 2>/dev/null || true
    done < "$STATE"
    rm -f "$STATE"
    echo "==> removed iris virtual-audio modules."
}

case "${1:-}" in
    up) up ;;
    down) down ;;
    *) echo "usage: $0 {up|down}" >&2; exit 2 ;;
esac
