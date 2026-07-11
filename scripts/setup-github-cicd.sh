#!/usr/bin/env bash
#
# Configure keyless CI/CD: a Workload Identity Federation pool/provider bound to
# your GitHub repository, a least-privilege deployer service account, and the
# GitHub Actions variables/secrets the workflows expect.
#
# Idempotent: safe to re-run. Requires `gcloud` and `gh`, both authenticated.
#
# Required environment variables:
#   GITHUB_REPO   owner/repo (e.g. albertochaves-dev/alexa-gemini-cloudrun)
#   PROJECT_ID    GCP project id (same as setup-gcp.sh)
#   REGION        Cloud Run region
#
set -euo pipefail

: "${GITHUB_REPO:?set GITHUB_REPO as owner/repo}"
: "${PROJECT_ID:?set PROJECT_ID}"
: "${REGION:?set REGION}"

POOL_ID="github-pool"
PROVIDER_ID="github-provider"
SA_NAME="github-deployer"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUD_RUN_SERVICE="alexa-gemini"

gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

echo "==> Creating deployer service account (if needed)"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$SA_NAME" \
       --display-name="GitHub Actions deployer"

# A freshly created service account is not immediately usable as an IAM member
# (eventual consistency), so binding roles can fail with "does not exist".
# Retry each binding until the account has propagated.
grant_role() {
  local role="$1"
  local i
  for i in $(seq 1 8); do
    if gcloud projects add-iam-policy-binding "$PROJECT_ID" \
         --member="serviceAccount:${SA_EMAIL}" \
         --role="$role" --condition=None >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  echo "   ERROR: could not grant $role" >&2
  return 1
}

echo "==> Granting deploy roles (with propagation retries)"
for role in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/cloudbuild.builds.editor \
  roles/storage.admin \
  roles/iam.serviceAccountUser \
  roles/logging.viewer; do
  echo "   - $role"
  grant_role "$role"
done

echo "==> Creating Workload Identity pool/provider (if needed)"
gcloud iam workload-identity-pools describe "$POOL_ID" --location=global >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create "$POOL_ID" \
       --location=global --display-name="GitHub Actions pool"

gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --location=global --workload-identity-pool="$POOL_ID" >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
       --location=global --workload-identity-pool="$POOL_ID" \
       --display-name="GitHub provider" \
       --issuer-uri="https://token.actions.githubusercontent.com" \
       --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
       --attribute-condition="assertion.repository=='${GITHUB_REPO}'"

echo "==> Allowing $GITHUB_REPO to impersonate the deployer SA"
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPO}" >/dev/null

WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"

echo "==> Setting GitHub Actions variables and secrets on $GITHUB_REPO"
gh variable set GCP_PROJECT_ID    --repo "$GITHUB_REPO" --body "$PROJECT_ID"
gh variable set GCP_REGION        --repo "$GITHUB_REPO" --body "$REGION"
gh variable set CLOUD_RUN_SERVICE --repo "$GITHUB_REPO" --body "$CLOUD_RUN_SERVICE"
gh secret   set WIF_PROVIDER        --repo "$GITHUB_REPO" --body "$WIF_PROVIDER"
gh secret   set WIF_SERVICE_ACCOUNT --repo "$GITHUB_REPO" --body "$SA_EMAIL"

echo ""
echo "Done. Push to main (or run the Deploy workflow) to build & deploy."
