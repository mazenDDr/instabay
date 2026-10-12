# 0006: Scope calibration, preserve uncertainty and keep default judge-only

Status: accepted for Phase 6. No Phase 0 measurements or human gold set exist, so default
checks remain judge-only. Typed native adapters are opt-in; synthetic policies never enable
native engines. Fit confidence-correctness temperatures and thresholds solely on grouped
validation, evaluate untouched test cells, bind evidence to engine/brand/question/language,
and publish precision intervals, ECE and audit kappa. Use an application-level scalar fitter
rather than assuming Laya's native-logit utility signature transfers to Jev confidence.
The cascade persists raw/scoped calibrated answers and only uncertain/adverse question IDs
in escalation context; retain the existing full three-sample rubric when escalation occurs.
A System-1 pass stores no invented rubric sample. Stable 10% audits and one revision preserve
resumability; all routes still require human approval. D1 needs bilingual calibrated consensus,
D3 uncertainty holds untrusted text for review, and live reward/time inference stays separate.
A real 300-item/60-audit dataset and optional model measurements are HUMAN items, not fabricated
fixtures. See [implementation, sources and limits](../DECISIONS.md).
