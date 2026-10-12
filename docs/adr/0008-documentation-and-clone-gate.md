# ADR 0008: reproducible documentation and an isolated clone gate

Document current code and measured scope, preserving historical phase reports and benchmark
bytes. Separate a development validation image from the UID 10001 runtime image. The validation
image is built from a clean committed checkout, keeps that checkout's Git metadata for hooks,
prepares locked dependencies during build and runs setup/demo/tests/lint with networking disabled.
Acceptance verifies a persistent human-approval stop and zero normal-demo approvals/publications,
then reports machine-readable evidence. No host environment, cache, token, GPU or prior database
is used. Add an explicit CI gate and one runnable command; keep production provider/recording,
real calibration/video QA and live learning in the backlog instead of expanding Phase 8 into
unapproved feature work. Completion of the eight offline build gates is not a go-live approval.
