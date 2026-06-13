"""Iris's audio layer — platform-agnostic endpoints + swappable STT/TTS.

The voice loop is mic -> STT -> brain -> TTS -> speaker. *Which* audio it taps
is just a binding (``AudioEndpoint``): tincan's Bluetooth SCO nodes, a
Discord/Zoom virtual device, or the local mic/speaker. The brain never changes.
"""
