# Research and evidence

This document maps primary research to implementation choices. Sources were checked on
2026-10-12. Published results belong to their authors' experiments; they are not Insta Bay
measurements. The repository's verified evidence is offline fixtures, synthetic policy trials,
API contracts and CPU render tests. Real model/Arabic quality, paid costs and native GPU results
remain absent. [Benchmark protocol](../bench/README.md) and [go-live prerequisites](GO_LIVE.md)
explain what evidence would be needed to change that status.

## Decisions supported by research

| Question | Primary source | Project choice and limitation |
|---|---|---|
| How should plans adapt? | [A Tutorial on Thompson Sampling](https://arxiv.org/abs/1707.02038) | Sample beliefs to balance exploration/exploitation, then apply deterministic planning constraints. The factored model and 20-observation fractional update are project assumptions, not a claim that the paper proves resort uplift. |
| Can feedback improve a draft? | [Self-Refine](https://arxiv.org/abs/2303.17651) | Keep one bounded feedback/revision pass, log the original verdict and recheck changed copy. Canned revision fixtures prove control flow; real improvement is unmeasured. |
| Can an LLM grade copy? | [G-Eval](https://arxiv.org/abs/2303.16634) | Use a structured rubric and independent human labels before trusting scores. This repository uses three rubric samples; it does not reproduce G-Eval's complete evaluation method or human correlation. |
| Why separate writer and grader evidence? | [LLM Evaluators Recognize and Favor Their Own Generations](https://arxiv.org/abs/2404.13076) | Self-preference motivates a different model family plus human audits. Merely changing a model label in a fixture does not establish independence. |
| Why calibrate confidence? | [On Calibration of Modern Neural Networks](https://arxiv.org/abs/1706.04599) | Fit only on validation and report held-out behavior. Our dependency-free fitter scales reported-confidence correctness logits; it is not native class-logit calibration from the paper. |
| Should prompt tuning replace the bandit? | [GEPA](https://arxiv.org/abs/2507.19457) | Reflective prompt search is a future content-prompt experiment. It never selects marketing arms or replaces Thompson sampling. GEPA is not implemented here. |
| Is spec-compliant video faithful? | [VBench-2.0](https://arxiv.org/abs/2503.21755) | Separate media encoding from semantic/temporal fidelity. Our actual spec checks and luminance proxy are not a VBench-2.0 reproduction or native quality score. |

These studies motivate engineering hypotheses. They do not establish this system's real benefit.
The simulator was committed before the optimizer; test worlds were not changed to make the
chosen policy win. The frozen benchmark compares fixed, uniform, Thompson, oracle and two
leakage policies over paired worlds with seed-level bootstrap intervals. Its leakage-ablation
interval crosses zero, so it does not establish a D1 benefit even under ideal synthetic labels.
The positive synthetic optimizer uplift is not an Instagram causal result.

## Primary implementation references

[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) document durable
checkpoint/thread IDs and resume. Insta Bay keeps authorization in its database rather than
accepting a resume payload as a human decision. Restart/refusal tests verify that boundary.

The [TypeSafe introduction](https://docs.typesafe.ai/introduction) describes typed decision
primitives. [Laya source at the inspected revision](https://github.com/NandhaKishorM/laya/tree/682ac6719faa5b1c04b529501feb93e58ee91f3d)
informs the optional local adapter. Full hosted wire/current runtime compatibility and actual
Arabic performance remain unverified; source inspection is not a deployment measurement.
[Decision documentation](DECISIONS.md) records the specific normalization/scoping choices.

[Diffusers reproducibility guidance](https://huggingface.co/docs/diffusers/en/using-diffusers/reusing_seeds)
limits expectations of seeded replay across environments. The product guarantee is verified L0
artifact caching; CPU tests compare uncached decoded frames on their own runtime. No GPU L1
or cross-machine equivalence is established. [Wan pipeline documentation](https://huggingface.co/docs/diffusers/en/api/pipelines/wan)
and [ComfyUI routes](https://docs.comfy.org/development/comfyui-server/comms_routes) inform guarded
adapter code. Model fit/FLF/node compatibility needs human spikes on the actual box.

The official [Meta publishing documentation](https://developers.facebook.com/docs/instagram-platform/content-publishing)
and [insights documentation](https://developers.facebook.com/docs/instagram-platform/insights)
could not be retrieved during this verification. Prior adapter work consulted the
[official Meta Postman collection](https://www.postman.com/meta/instagram/overview).
Current API versions, login scopes, quotas and media/metric availability remain human verification
items. Example config values are conservative assumptions, not freshly verified platform facts.
No third-party blog, video leaderboard or illustrative pricing is treated as proof of API support.

## Experiments needed before stronger claims

1. **Grader and Arabic labels:** obtain blinded independent human ratings for fixed text, record
   real native/MT pairs, then report agreement and uncertainty. Empty label fields stay null.
2. **Decision cascade:** record at least 300 real bilingual items (>=40% Arabic) with at least
   60 human audits; group counterparts before tuning. Report accepted precision/intervals,
   escalation, calibration error, agreement and actual latency/cost. Poor cells remain judge-only.
3. **Native video:** use approved identical keyframes/motion prompts, verify actual model/runtime
   pins and memory fit, compare uncached frame hashes, and independently assess semantic/temporal
   defects. Only then evaluate paid alternatives with blind preferences and measured prices.
4. **Live learning:** define a bounded reward for overlapping interaction counts and prove exact
   executed-arm attribution before connecting real observations to posteriors. Raw ratios may
   exceed one; silently clipping them into the simulator's reward would change the experiment.
5. **Prompt tuning:** freeze train/dev/test groups and a calibrated grader before a GEPA study.
   Keep the simulator, policy and human test set fixed; report paired changes, including null results.

# HUMAN: record raw provenance and results in `docs/adr/0000-spikes.md` and private measurement
artifacts. Never turn fixture scores, source claims or a model seed into verified production facts.
