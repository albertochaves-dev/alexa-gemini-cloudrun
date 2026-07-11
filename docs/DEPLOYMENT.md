# Deployment guide

This guide takes you from an empty Google Cloud account to a working private
Alexa skill. Everything stays within free tiers.

- [1. Prerequisites](#1-prerequisites)
- [2. Provision Google Cloud](#2-provision-google-cloud)
- [3. Deploy the backend](#3-deploy-the-backend)
- [4. Custom domain + TLS (required for Alexa)](#4-custom-domain--tls-required-for-alexa)
- [5. CI/CD with GitHub Actions](#5-cicd-with-github-actions)
- [6. Configure the Alexa skill](#6-configure-the-alexa-skill)
- [7. Test](#7-test)

---

## 1. Prerequisites

| Tool | Purpose |
| ---- | ------- |
| [`gcloud`](https://cloud.google.com/sdk/docs/install) | Google Cloud CLI |
| [`gh`](https://cli.github.com/) | GitHub CLI (for CI/CD setup) |
| [`firebase`](https://firebase.google.com/docs/cli) | Firebase Hosting proxy |
| Docker *(optional)* | Local image builds; Cloud Build is used otherwise |
| A Gemini API key | Free at <https://aistudio.google.com/apikey> |
| An Amazon Developer account | <https://developer.amazon.com/alexa/console/ask> |

A Google Cloud **billing account** is required to enable Cloud Run and Artifact
Registry (Google mandates a card on file even for $0 usage). Usage in this
project stays inside the always-free tier; a budget alert is created as a safety
net.

## 2. Provision Google Cloud

The scripted path does everything in section 2 for you:

```bash
export PROJECT_ID="my-alexa-gemini"     # must be globally unique
export REGION="europe-southwest1"
export BILLING_ACCOUNT_ID="XXXXXX-XXXXXX-XXXXXX"   # gcloud billing accounts list

./scripts/setup-gcp.sh
```

It will:

- create the project and link billing,
- enable the required APIs (Cloud Run, Artifact Registry, Cloud Build, Firebase
  Hosting, Storage, Billing Budgets),
- create an Artifact Registry Docker repository,
- create a €5 budget alert.

<details>
<summary>Manual equivalent</summary>

```bash
gcloud projects create "$PROJECT_ID"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com firebasehosting.googleapis.com \
  storage.googleapis.com billingbudgets.googleapis.com
gcloud artifacts repositories create alexa-gemini \
  --repository-format=docker --location="$REGION"
```
</details>

## 3. Deploy the backend

Build with Cloud Build (no local Docker needed) and deploy:

```bash
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/alexa-gemini/alexa-gemini:latest"

gcloud builds submit --tag "$IMAGE" .

gcloud run deploy alexa-gemini \
  --image="$IMAGE" \
  --region="$REGION" \
  --allow-unauthenticated \
  --set-env-vars="GEMINI_API_KEY=$GEMINI_API_KEY,GEMINI_MODEL=gemini-2.5-flash,VERIFY_ALEXA_SIGNATURE=true"
```

Note the printed **Service URL** and smoke-test it:

```bash
curl -s "$SERVICE_URL/health"          # {"status":"ok"}
```

> Cross-compiling ARM → amd64 locally is slow; prefer `gcloud builds submit`,
> which builds natively on Google's infrastructure.

## 4. Custom domain + TLS (required for Alexa)

Alexa rejects Cloud Run's wildcard `*.run.app` certificate (see
[ARCHITECTURE.md](ARCHITECTURE.md#the-certificate-problem)). Front the service
with Firebase Hosting on a custom domain that gets an exact-hostname
certificate.

1. **Enable Firebase** on the project and deploy the Hosting proxy:

   ```bash
   firebase deploy --only hosting --project "$PROJECT_ID"
   ```

   (`firebase.json` already contains the `rewrite` to the Cloud Run service.)

2. **Get a free subdomain with a complete DNS implementation.** Use
   [deSEC](https://desec.io) (`something.dedyn.io`). Avoid providers that drop
   `CAA`/`CNAME` queries (e.g. DuckDNS) — certificate issuance will never
   complete.

3. **Register the custom domain** in Firebase Hosting (Console → Hosting → Add
   custom domain), then add the DNS records Firebase asks for at deSEC:
   - an `A` record → the IP Firebase provides (e.g. `199.36.158.100`),
   - a `TXT` record for ownership verification (e.g.
     `hosting-site=<your-site-id>`).

4. Wait for Firebase to report the certificate **active** (a few minutes), then
   verify:

   ```bash
   curl -s https://<your-subdomain>.dedyn.io/health   # {"status":"ok"}
   ```

## 5. CI/CD with GitHub Actions

CI/CD authenticates to GCP with **Workload Identity Federation** — keyless, no
service-account JSON to manage. The setup script provisions the pool, provider,
service account, and pushes the GitHub secrets/variables:

```bash
export GITHUB_REPO="albertochaves-dev/alexa-gemini-cloudrun"
export PROJECT_ID="my-alexa-gemini"
export REGION="europe-southwest1"

./scripts/setup-github-cicd.sh
```

It configures these on the repo:

| Kind     | Name                     | Purpose                              |
| -------- | ------------------------ | ------------------------------------ |
| Variable | `GCP_PROJECT_ID`         | Target project                       |
| Variable | `GCP_REGION`             | Cloud Run region                     |
| Variable | `CLOUD_RUN_SERVICE`      | Service name (`alexa-gemini`)        |
| Secret   | `WIF_PROVIDER`           | Workload Identity provider resource  |
| Secret   | `WIF_SERVICE_ACCOUNT`    | Deployer service-account email       |

The Gemini API key is **not** a GitHub secret — it lives in **Google Secret
Manager** (created by `setup-gcp.sh`) and is mounted into Cloud Run at deploy
time, so the key never touches the repository or CI logs.

Afterwards, every push to `main` runs [`ci.yml`](../.github/workflows/ci.yml)
(lint + tests) and [`deploy.yml`](../.github/workflows/deploy.yml) (build +
deploy).

## 6. Configure the Alexa skill

1. **Create the skill** at the
   [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask):
   Custom model, **Provision your own** hosting, primary locale **Spanish (ES)**.
2. **Interaction model** — import
   [`docs/alexa-interaction-model.json`](alexa-interaction-model.json)
   (JSON editor → paste → Save → Build).
   - Invocation name: `momoru`
   - Intent: `PreguntarGeminiIntent` with an `AMAZON.SearchQuery` slot `pregunta`.
   - `AMAZON.SearchQuery` **requires a carrier phrase** — a bare `{pregunta}`
     sample is rejected by Amazon. The model ships many natural carriers
     (`dime {pregunta}`, `cuéntame {pregunta}`, `momoru {pregunta}`, …).
3. **Endpoint** — Build → Endpoint → HTTPS, Default Region =
   `https://<your-subdomain>.dedyn.io/alexa`, SSL type = *"My development
   endpoint has a certificate from a trusted certificate authority"*. Save.
4. **Enable testing** — Test tab → toggle to **Development**.

## 7. Test

- **Simulator:** Test tab → type `abre momoru`, then `dime cuánto mide la torre eiffel`.
- **Echo device:** any Echo signed into the **same Amazon account** as the
  developer console picks up development-stage skills automatically — just say
  *"Alexa, abre momoru"*.

### Troubleshooting

| Symptom | Likely cause |
| ------- | ------------ |
| "No puedo conectar con la skill" | Endpoint cert rejected — verify you use the custom domain, not `*.run.app` |
| Skill not found by name | Interaction model not rebuilt after changing invocation name; or device locale ≠ `es-ES` |
| Question hangs / no answer | Latency > ~8 s — ensure Gemini "thinking" is disabled (it is in `app/gemini.py`) |
| Bare question ignored | `AMAZON.SearchQuery` needs a carrier phrase (`dime …`, `cuéntame …`) |

Inspect live backend logs:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="alexa-gemini"' \
  --project="$PROJECT_ID" --freshness=10m --order=asc \
  --format="value(timestamp, severity, httpRequest.status, httpRequest.latency, textPayload)"
```
