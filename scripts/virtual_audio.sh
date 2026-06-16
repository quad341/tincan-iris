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

AEC_STATE="${XDG_RUNTIME_DIR:-/tmp}/iris_virtual_aec.modules"

aec_up() {
    # Requires virtual_audio.sh up to already be running.
    # Loads WebRTC AEC + AGC + NS for the virtual-audio path:
    #   1. Removes the raw mic loopback (@DEFAULT_SOURCE@ -> iris_mic).
    #   2. Loads module-echo-cancel: mic=@DEFAULT_SOURCE@, reference=@DEFAULT_SINK@.monitor
    #      → iris_va_aec_src (cleaned mic) + iris_va_aec_sink (reference sink).
    #   3. Adds a new loopback: iris_va_aec_src -> iris_mic (call hears clean mic).
    # iris_out drives @DEFAULT_SINK@ (Iris's voice + far party) — so the AEC reference
    # automatically includes all speaker bleed without any routing change.
    if ! pactl list short sinks | grep -qw iris_mic; then
        echo "iris_mic not found — run '$0 up' first." >&2
        exit 1
    fi
    if [[ -s "$AEC_STATE" ]]; then
        echo "AEC already active — run '$0 aec-down' first." >&2
        exit 1
    fi
    : > "$AEC_STATE"

    # 1. Remove the raw mic->iris_mic loopback; iris_va_aec_src replaces it.
    local mic_ids
    mic_ids=$(pactl list short modules | awk '$2=="module-loopback" && /iris_mic/ {print $1}')
    for id in $mic_ids; do
        pactl unload-module "$id" 2>/dev/null || true
    done

    # 2. WebRTC AEC: reference = @DEFAULT_SINK@.monitor (Iris + far party on speakers).
    echo "==> loading WebRTC AEC + AGC + NS (iris_va_aec_src / iris_va_aec_sink)"
    pactl load-module module-echo-cancel \
        aec_method=webrtc \
        use_agc=true \
        use_ns=true \
        source_name="${IRIS_VA_AEC_SRC:-iris_va_aec_src}" \
        sink_name="${IRIS_VA_AEC_SINK:-iris_va_aec_sink}" \
        source_properties=device.description=Iris_VA_AEC_Mic \
        sink_properties=device.description=Iris_VA_AEC_Speaker \
        >> "$AEC_STATE"

    # 3. Clean mic -> iris_mic so the call hears the echo-cancelled operator voice.
    echo "==> loopback: iris_va_aec_src -> iris_mic (clean operator mic -> call)"
    pactl load-module module-loopback \
        source="${IRIS_VA_AEC_SRC:-iris_va_aec_src}" sink=iris_mic latency_msec=20 \
        >> "$AEC_STATE"

    cat <<'EOF'

AEC active.  Launch Iris with:
  IRIS_PLAYBACK_TARGET=iris_out IRIS_VA_AEC=1 python -m iris.console

Iris's operator capture uses iris_va_aec_src (echo-cancelled, AGC-normalised, denoised).
The call loopback feeds iris_va_aec_src -> iris_mic (far party hears a clean mic).
Iris's own voice (iris_out -> speakers) and the far party are automatically the AEC reference.

Tear down AEC:  scripts/virtual_audio.sh aec-down
Tear down all:  scripts/virtual_audio.sh aec-down && scripts/virtual_audio.sh down
EOF
}

aec_down() {
    if [[ ! -s "$AEC_STATE" ]]; then
        echo "No saved AEC modules — nothing to tear down." >&2
        # Fallback: unload by name in case state file was lost.
        if pactl list short modules | grep -q "module-echo-cancel"; then
            echo "Found module-echo-cancel in pactl — unloading by name." >&2
            pactl unload-module module-echo-cancel 2>/dev/null || true
        fi
        exit 0
    fi
    # Unload in reverse load order (loopback before echo-cancel).
    tac "$AEC_STATE" | while read -r id; do
        [[ -n "$id" ]] && pactl unload-module "$id" 2>/dev/null || true
    done
    rm -f "$AEC_STATE"
    echo "==> AEC modules removed."
    # Restore the raw mic loopback so the call still hears the operator.
    if pactl list short sinks | grep -qw iris_mic; then
        pactl load-module module-loopback \
            source=@DEFAULT_SOURCE@ sink=iris_mic latency_msec=20 source_dont_move=true >/dev/null
        echo "==> raw mic loopback restored (@DEFAULT_SOURCE@ -> iris_mic)."
    fi
}

case "${1:-}" in
    up) up ;;
    down) down ;;
    mute) mute ;;         # release your mic (drop the loopback); Iris's voice still works
    unmute) unmute ;;     # re-arm your mic to the call
    aec-up) aec_up ;;    # add WebRTC AEC + AGC + NS for speaker-mode operation
    aec-down) aec_down ;; # remove AEC and restore raw mic loopback
    *) echo "usage: $0 {up|down|mute|unmute|aec-up|aec-down}" >&2; exit 2 ;;
esac
