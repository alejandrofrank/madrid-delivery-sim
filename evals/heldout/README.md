# Reserved release cohort

These 72 cases are reserved for release qualification. Daily development and PR
evals use `evals/adk`; the evaluator defaults to that development cohort. Run this
cohort only when qualifying a release, with fresh sessions for every attempt.
Do not tune prompts or policies against its failures. Add fixes and new regression
cases to development, then rotate and version the held-out cohort for the next
qualification if its results have influenced implementation decisions.

The cases vary order quantities, supplier identities/prices, complaint wording,
statuses and disruption timing. Expected outputs and tool trajectories are frozen
fixtures, not generated from candidate responses. `evals/splits.json` seals both
cohorts; tests reject overlapping input cases and accidental fixture edits.

This is a source-controlled reserved cohort, not a secret benchmark. Offline ADK
models exercise real runners and tool contracts but do not measure live-model
reasoning, cost or latency. A bootstrap run with no compatible baseline stores
evidence and makes no regression claim. Subsequent gates compare the exact same
fixture hashes, number of attempts and execution mode against a trusted release
artifact, not an artifact selected by the candidate pull request.
