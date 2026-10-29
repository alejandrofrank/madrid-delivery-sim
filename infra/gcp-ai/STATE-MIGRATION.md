# Analytics state migration

The combined module supports both receipt exports (`enable_bigquery`, default
dataset `delivery_analytics`) and streaming observability (`enable_analytics`,
dataset `mds_analytics`). Their retention, identities and tables remain separate.
One Terraform resource owns each API even when both features are enabled.

Fresh state and state from the receipt-export branch need no dataset move.
Before using state created by the standalone `feat/otel-bigquery` branch, inspect
the existing dataset **before running a plan**:

```bash
terraform -chdir=infra/gcp-ai state show 'google_bigquery_dataset.analytics[0]'
```

If and only if its `dataset_id` is `mds_analytics`, back up the private state and
move that dataset to its new address:

```bash
terraform -chdir=infra/gcp-ai state pull > infra/gcp-ai/pre-observability-merge.tfstate
terraform -chdir=infra/gcp-ai state mv \
  'google_bigquery_dataset.analytics[0]' \
  'google_bigquery_dataset.observability[0]'
```

Do not move `delivery_analytics` or another receipt dataset. The two branches
previously used the same dataset address for different physical datasets, so a
single unconditional `moved` block cannot safely distinguish them. A migration
must not replace or delete either dataset. Keep the state backup private and
outside Git, as with all other Terraform state.

The four streaming table instances and streaming API registrations have explicit
`moved` blocks because their old keys identify them unambiguously. Review the
next plan with the same feature flags and retention settings as the deployment;
existing datasets and tables should show moves rather than replacement. If both
the source and destination API addresses already exist in state, inspect their
project/service IDs and resolve the duplicate state registration before planning;
do not recreate or disable the shared API.

Parking requires explicit retirement of both datasets and both trace options.
Back up retained data, stop exporters and preserve billing/runtime flags during
the reviewed cleanup. Protected streaming tables first require a separate apply
with `analytics_deletion_protection=false`; ordinary `gcp_demo.py stop` never
removes them automatically.
