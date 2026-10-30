# madrid-delivery-sim public-readiness review

On October 30, 2026, Gitleaks 8.30.1 scanned all local Git refs: 177 commits
and 10.69 MB of historical changes. It reported three candidates, all verified
as SHA-256 source-file fingerprints in the A2A evidence receipt, with **zero
confirmed credentials**. Each fingerprint matches the corresponding file at
revision `3c61889`. The [counts-only receipt](evidence/public-readiness.json)
records the exact findings and scanner image. Pattern scans cannot prove the
absence of every possible secret. No history was rewritten; repository visibility
remains private.

The working tree no longer contains the four full-repository snapshots under
`artifacts/`, `codex_run.log`, the generated ChatGPT image, or the extra `.env.*`
files. Local run receipts remain in ignored `artifacts/` because the evidence UI
uses them. Private catalogue data remains ignored in `data/local/`.

`.gitignore` excludes artifacts, logs and every `.env` variant at every depth,
with `.env.example` as the only environment-template exception. That template
contains no credentials. The former duplicate `config/local.env.example` has
been removed. Private Terraform variables, state, plans and working directories
remain excluded. The operator's canonical `.env` stays local and ignored.

Cleanup preserved the extra Jev credential file and an old patch backup outside
the repository. Paid-experiment execution markers moved to ignored
`data/local/operator/adk-experiments/`; the launcher migrates the old marker
directory on upgrade and refuses ambiguous duplicate directories. This retains
the safeguards against repeating paid experiments. No paid run was performed.

## Contributor tooling

The duplicated Impeccable distributions in `.cursor/skills` and `.github/skills`,
their generic agent definitions and automatic hooks were removed and ignored.
Contributors do not need bundled Windows executables or editor automation to
build, test or change this project. `AGENTS.md`, the small Bash editor rule,
`DESIGN.md`, `PRODUCT.md` and the design documentation remain because they state
project-specific conventions. Existing design-review evidence remains available
for understanding the current UI; it does not install or execute tooling.

The project name is **madrid-delivery-sim** in the README, roadmap, contributor
documents and application labels. Bakiano references remain only where they
describe the external catalogue source, provenance, historical evidence or a
named simulated fleet.

## Recheck before publishing

Run these from Bash. The scanner has no network access and receives only Git
history, plus an empty output directory; local credentials are not mounted.

```bash
git ls-files 'codex_run.log' '*.tfplan' '*.tfstate*' '.env*' '**/.env*'
git check-ignore .env .env.local nested/.env.production artifacts/probe.log
mkdir -p artifacts/security
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "$PWD/.git:/repo/.git:ro" -v "$PWD/artifacts/security:/reports" \
  ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f \
  git /repo --log-opts=--all --redact=100 \
  --report-format json --report-path /reports/history.json
```

The first command should list only `.env.example`. The raw scan currently returns
three fingerprint candidates; inspect new findings rather than broadly suppressing
API-related files. If a real credential is found, report and revoke or rotate it;
history rewriting requires separate approval.
