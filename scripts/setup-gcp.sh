#!/usr/bin/env bash
#
# Provision the Google Cloud resources for the Alexa × Gemini backend.
# Idempotent: safe to re-run. Requires the `gcloud` CLI, authenticated
# (`gcloud auth login`).
#
# Required environment variables:
#   PROJECT_ID           Globally-unique GCP project id to create/use
#   REGION               Cloud Run region (e.g. europe-southwest1)
#   BILLING_ACCOUNT_ID   Billing account to link (gcloud billing accounts list)
#   GEMINI_API_KEY       Gemini API key (stored in Secret Manager, not the repo)
#
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
: "${REGION:?set REGION}"
: "${BILLING_ACCOUNT_ID:?set BILLING_ACCOUNT_ID}"
: "${GEMINI_API_KEY:?set GEMINI_API_KEY}"

AR_REPO="alexa-gemini"
SECRET_NAME="gemini-api-key"

echo "==> Creating project $PROJECT_ID (if it does not exist)"
gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1 \
  || gcloud projects create "$PROJECT_ID" --name="Alexa Gemini Skill"

echo "==> Linking billing account"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"

gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Enabling APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  firebasehosting.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  billingbudgets.googleapis.com

echo "==> Creating Artifact Registry repo (if needed)"
gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$AR_REPO" \
       --repository-format=docker --location="$REGION" \
       --description="Alexa Gemini skill images"

echo "==> Storing Gemini API key in Secret Manager"
if gcloud secrets describe "$SECRET_NAME" >/dev/null 2>&1; then
  printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add "$SECRET_NAME" --data-file=-
else
  printf '%s' "$GEMINI_API_KEY" | gcloud secrets create "$SECRET_NAME" --data-file=-
fi

echo "==> Granting the Cloud Run runtime service account access to the secret"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" >/dev/null

echo "==> Creating a €5 budget alert (best-effort)"
gcloud billing budgets create \
  --billing-account="$BILLING_ACCOUNT_ID" \
  --display-name="Alexa Gemini Skill - alert" \
  --budget-amount=5EUR \
  --filter-projects="projects/${PROJECT_ID}" \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=1.0 >/dev/null 2>&1 || echo "   (budget alert skipped)"

echo ""
echo "Done. Next: build & deploy the backend, then run scripts/setup-github-cicd.sh"
