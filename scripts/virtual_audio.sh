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
    echo "==> null-sink 'iris_ear' — set the app's OUTPUT here so Iris can hear the other party"
    pactl load-module module-null-sink \
        sink_name=iris_ear sink_properties=device.description=Iris_Ear >> "$STATE"
    echo "==> loopback: iris_ear -> your speakers ($spk) so you still hear the call"
    pactl load-module module-loopback \
        source=iris_ear.monitor sink="$spk" latency_msec=20 >> "$STATE"
    cat <<EOF

Ready. Next:
  1. In Discord/Vesktop:  microphone/input = Iris_Microphone,  output = Iris_Ear
  2. Run:  IRIS_PLAYBACK_TARGET=iris_out python -m iris.console
  3. Keys:  [l] hear you · [f] hear the respondent · [a] approve their commands
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

mute() {
    # Drop just the mic->iris_mic loopback: your mic is released (light off),
    # Iris's voice path stays. "Default talk, mute on command."
    local ids
    ids=$(pactl list short modules | awk '$2=="module-loopback" && /iris_mic/ {print $1}')
    if [[ -z "$ids" ]]; then
        echo "mic already muted (no iris loopback loaded)."
        return 0
    fi
    for id in $ids; do pactl unload-module "$id"; done
    echo "==> mic MUTED — your mic is released; the call no longer hears you (Iris still can speak)."
}

unmute() {
    if pactl list short modules | awk '$2=="module-loopback"' | grep -q iris_mic; then
        echo "mic already live."
        return 0
    fi
    pactl load-module module-loopback \
        source=@DEFAULT_SOURCE@ sink=iris_mic latency_msec=20 source_dont_move=true >/dev/null
    echo "==> mic LIVE — your mic feeds the call again."
}

case "${1:-}" in
    up) up ;;
    down) down ;;
    mute) mute ;;       # release your mic (drop the loopback); Iris's voice still works
    unmute) unmute ;;   # re-arm your mic to the call
    *) echo "usage: $0 {up|down|mute|unmute}" >&2; exit 2 ;;
esac
