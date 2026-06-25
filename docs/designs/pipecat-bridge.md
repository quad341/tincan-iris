# Pipecat brain bridge — validated decision + implementation brief

> **Status:** OQ-1 **validated by spike** (2026-06-25). Adopt Pipecat as the real-time
> voice spine; iris's `Brain` stays the brain *and* the ADR-0005 trust boundary.
> Hand-off for `tincan-iris/architect`: write the ADR + decompose into builder work.
>
> **Reads with:** [`voice-call-architecture.md`](voice-call-architecture.md) (mp6v.1,
> the system architecture) and PR #99 (the streaming-skill bridge this builds on).

## The decision
The real-time pipeline (VAD → STT → LLM → TTS, with interruption/turn-taking) is
**Pipecat**. We do **not** adopt LiveKit — its differentiators (WebRTC SFU, SIP telephony,
multi-participant) are exactly what we don't need; tincand owns the BT-SCO transport and feeds
PCM. The LLM stage is **iris's `Brain`**, wrapped as a Pipecat `LLMService` so the tiered
router and the propose→authorize→execute gate run *inside* the service. Pipecat transports
audio and never becomes the trust boundary.

This was the load-bearing uncertainty (would "adopt" quietly become "rebuild," and would the
gate survive an async pipeline?). It does not, and it does.

## What the spike proved (pipecat-ai 1.4.0, live warm Qwen, real `Pipeline`)
A `BrainLLMService` wrapping `Brain.respond_stream` was driven through a real
`Pipeline`/`PipelineTask`/`PipelineRunner`:

| Proof | Result |
|---|---|
| **Integration** | streamed `LLMTextFrame`s from the brain through the pipeline |
| **Barge-in** | uninterrupted = 3 frames; **interrupted after 1 = 1 frame** — an `InterruptionFrame` mid-stream cancels the turn, keeps what was already said, stops the rest |
| **Gate intact** | far party → *"That's something I can only do at the operator's request."*; **authorize() called exactly 1×** |

So the headline Pipecat value iris structurally lacks (full-duplex barge-in) works through our
brain, and ADR-0005 survives the async wrap.

## Validated shape (reference — productionize, don't ship verbatim)
The bridge is ~80 lines. The crux is the **sync↔async** boundary: the brain is synchronous
(blocking `urllib`), Pipecat is async — so the turn runs in a worker thread feeding an asyncio
queue, and barge-in sets a cancel flag the worker checks between sentence chunks.

```python
class BrainLLMService(LLMService):
    def __init__(self, brain, default_speaker="operator", **kwargs):
        super().__init__(**kwargs)
        self._brain, self._default_speaker = brain, default_speaker
        self._cancel: threading.Event | None = None

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            speaker = frame.user_id or self._default_speaker
            asyncio.create_task(self._run_turn(frame.text, speaker))   # don't await
        elif isinstance(frame, (InterruptionFrame, CancelFrame)):
            if self._cancel: self._cancel.set()                        # barge-in
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

    async def _run_turn(self, text, speaker):
        cancel = self._cancel = threading.Event()
        loop, q = asyncio.get_running_loop(), asyncio.Queue()
        def worker():
            try:
                for chunk in self._brain.respond_stream(text, speaker=speaker):  # gate is INSIDE
                    if cancel.is_set(): break
                    if chunk.text: loop.call_soon_threadsafe(q.put_nowait, ("chunk", chunk.text))
            finally:
                loop.call_soon_threadsafe(q.put_nowait, ("done", None))
        await self.push_frame(LLMFullResponseStartFrame())
        threading.Thread(target=worker, daemon=True).start()
        while True:
            kind, val = await q.get()
            if kind == "done" or cancel.is_set(): break
            if kind == "chunk": await self.push_frame(LLMTextFrame(val))
        await self.push_frame(LLMFullResponseEndFrame())
```

## Integration tax (known, bounded)
1. **Sync ↔ async** — worker thread + asyncio queue (above). Small, but it's the real cost.
2. **Barge-in granularity** — cancel lands between *sentence chunks* (~150 ms). True
   *mid-sentence* cancel needs an async HTTP client (aiohttp) against llama.cpp's streaming
   endpoint. Sentence-granularity is fine for v1; mid-sentence is a follow-up, not a blocker.
3. **`LLMSettings`** — Pipecat's `LLMService` base logs that settings fields (`model`,
   `temperature`, …) are `NOT_GIVEN`. A production wrapper initializes them in `__init__`
   (`None` for unsupported). Also quiet Pipecat's default DEBUG logging.

## Implementation scope (for the architect to plan)
- **ADR-0007** — "Adopt Pipecat for the real-time voice spine." Record the decision, the
  LiveKit rejection, and the gate-stays-in-the-brain invariant.
- **Module** — promote `BrainLLMService` into `iris/voice/pipecat_bridge.py` (or similar);
  initialize `LLMSettings`; quiet logging.
- **Dependency** — add `pipecat-ai` as an **optional extra** (`[voice]`), *not* a base
  install dep. iris's base must stay lean; the voice pipeline is opt-in.
- **Tests** (mirror #99's rigor, async): (a) streams `LLMTextFrame`s through a `Pipeline`;
  (b) `InterruptionFrame` mid-stream cancels (fewer frames, keeps the already-said);
  (c) the gate authorizes **once** and denies the far party — *inside* the service.
- **Decide** — aiohttp mid-sentence cancel now vs. follow-up (recommend follow-up).
- **Out of this bead** — wiring STT/TTS stages, the uplink mixer (tincand), profiles/tuning
  (those are separate mp6v children); this bead is just the **brain↔Pipecat seam**.

## Acceptance criteria
- `BrainLLMService` in iris, `pipecat-ai` an opt-in extra, base install unaffected.
- The three proofs above are green tests in CI.
- The ADR-0005 invariant holds: the gate is *only* in the brain; Pipecat never authorizes.
- No regression in the existing suite.

## Pointers
- `iris/brain.py` — `Brain.respond_stream` / `_stream_proposal` (the gate; shipped #99).
- `voice-call-architecture.md` §3–4 — the pipeline + brain-bridge design; §8 — the invariants.
- EERL budget (mp6v.2) and the latency bench (cohelper) — the two-call structure fits 800 ms.
