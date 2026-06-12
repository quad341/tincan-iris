# Security

## Running third-party models safely

tincan-iris loads third-party models (STT, TTS, LLM, embeddings). We treat them as
**untrusted code-adjacent artifacts** and contain them accordingly.

- **Download ≠ execute.** Model files are fetched over the network by *trusted tooling*
  (us), then loaded for inference with **no network access**. The two phases are kept
  separate.
- **No network egress during inference.** Model inference runs in a network-isolated
  sandbox — e.g. `unshare -n` (a fresh network namespace with no interfaces),
  `bwrap --unshare-net`, or a container with `--network none`. The process can use the
  GPU and read local files, but **cannot reach the internet** — so a compromised model
  or a parser bug in the inference engine cannot exfiltrate data or call home.
- **Non-executable formats only.** Prefer `.safetensors` and `.gguf` (pure tensor data,
  no code execution). Avoid pickle formats (`.bin` / `.ckpt` / `.pt`), which can run
  arbitrary code on load. The sandbox is still applied as defense-in-depth.
- **Threat model.** We accept that a bad model might disrupt the *local* machine
  (recoverable). The hard line is **no outbound network / no exfiltration.**

This applies to every provider that loads a model.

## Privacy of call data

Real phone numbers, contacts, transcripts, and call content stay **local** and are never
committed to the repository or sent to a service the user hasn't explicitly opted into.
Development tooling scrubs personal identifiers (numbers, contact names, Bluetooth device
names/MACs) before anything is pushed.

## Reporting

Found something? Open an issue (omit any real personal data) or contact the maintainer.
