#!/usr/bin/env bash
# An explicitly started, bounded demo session. The EXIT trap removes billed runtime.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
seconds="${1:-120}"
[[ "$seconds" =~ ^[0-9]+$ ]] && (( seconds >= 1 && seconds <= 3600 )) || {
  echo 'Choose a session duration between 1 and 3600 seconds.' >&2; exit 2;
}
: "${MDS_BILLING_ACCOUNT:?Set the billing account for the dedicated Madrid project}"
project=$(terraform -chdir=infra/production output -raw project_id)
[[ "$project" == madrid-delivery-sim-* ]] || { echo 'Unexpected project; refusing.' >&2; exit 2; }
existing=$(terraform -chdir=infra/production state list)
if [[ "$existing" =~ google_cloud_run_v2_|google_artifact_registry_repository.app|google_sql_database_instance.live|google_vertex_ai_index.memory|google_bigquery_dataset.analytics ]]; then
  echo 'An environment is already active. Stop it explicitly before starting another session.' >&2
  exit 2
fi
region=$(terraform -chdir=infra/production output -raw region)
registry="$region-docker.pkg.dev"
python3 scripts/cloud_run_cap.py --project "$project" --billing-account "$MDS_BILLING_ACCOUNT" --verify-only

cleanup() {
  result=$?
  trap - EXIT INT TERM
  if [[ -n "${MDS_DOCKER_AUTH:-}" ]]; then
    DOCKER_CONFIG="$MDS_DOCKER_AUTH" docker logout "https://$registry" >/dev/null || true
  fi
  if ! terraform -chdir=infra/production apply -input=false -auto-approve -var=active=false; then
    echo 'TEARDOWN FAILED: run the stop command in docs/production/DEPLOYMENT.md immediately.' >&2
    exit 1
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# An empty image bootstraps the disposable registry without referencing a deleted digest.
terraform -chdir=infra/production apply -input=false -auto-approve -var=active=true -var=replay_image= -var=enable_live=false
repository=$(terraform -chdir=infra/production output -raw image_repository)
image="$repository/replay:session"
docker build -f infra/production/Dockerfile.replay -t "$image" .
docker run --rm --network none --entrypoint python "$image" -c 'from delivery.production import create_app; create_app()'
MDS_DOCKER_AUTH=$(mktemp -d)
gcloud auth print-access-token | DOCKER_CONFIG="$MDS_DOCKER_AUTH" docker login -u oauth2accesstoken --password-stdin "https://$registry"
DOCKER_CONFIG="$MDS_DOCKER_AUTH" docker push "$image"
digest=$(gcloud artifacts docker images describe "$image" --project "$project" --format='value(image_summary.digest)')
terraform -chdir=infra/production apply -input=false -auto-approve -var=active=true -var=enable_live=false -var="replay_image=$repository/replay@$digest"
url=$(terraform -chdir=infra/production output -raw replay_url)
python3 scripts/verify_replay.py "$url"
printf '\nDemo: %s\nAutomatic teardown in %s seconds. Press Enter to stop sooner.\n' "$url" "$seconds"
read -r -t "$seconds" _ || true
