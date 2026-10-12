# ADR 0009: measured real inference and recorded motion previews

The user explicitly requested real LLM generation and real resort video, and approved photo
crops. Run those native experiments on gpu-box, retaining offline tests and stored post approval.
Use its already cached, revision-pinned Qwen model behind a loopback-only service reached through
SSH; no hosted keys were present. Preserve schema-validated raw responses separately from
editorial corrections. Keep API fees separate from unmeasured electricity/hardware cost. The
prepared GPU environment uses Python 3.11, while the application requires Python 3.12. Therefore
the standalone Wan experiment records its actual conda packages, model file hashes, conditioning,
implementation and settings before rendering; it makes no Docker or GPU replay guarantee.
CPU import verifies that recipe, source crop and clip bytes, stores a separate post recipe and
retains AI disclosure. Crop approval never attests to generated-video fidelity or post approval.
The native production adapter's pinned-Docker requirements remain intact. Failed visual trials
remain evidence, not usable marketing claims or calibrated benchmark improvements.
