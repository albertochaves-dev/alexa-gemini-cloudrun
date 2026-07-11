# Momoru — Alexa × Gemini Voice Assistant

[![CI](https://github.com/albertochaves-dev/alexa-gemini-cloudrun/actions/workflows/ci.yml/badge.svg)](https://github.com/albertochaves-dev/alexa-gemini-cloudrun/actions/workflows/ci.yml)
[![Deploy](https://github.com/albertochaves-dev/alexa-gemini-cloudrun/actions/workflows/deploy.yml/badge.svg)](https://github.com/albertochaves-dev/alexa-gemini-cloudrun/actions/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)

A private **Alexa skill** that turns any Echo device into a **Google Gemini**
voice assistant. Alexa forwards each spoken request to a **FastAPI** backend
running on **Google Cloud Run**, which validates the request, queries Gemini,
and returns a voice-ready answer — all on a **zero-cost** serverless footprint.

> Ask *"Alexa, open momoru"* and then talk to Gemini through your Echo Dot.

---

## Architecture

```
┌──────────┐   voice    ┌─────────────┐   HTTPS    ┌────────────────────┐
│ Echo Dot │ ─────────► │ Alexa Cloud │ ─────────► │ Custom domain      │
└──────────┘            │  (NLU/ASR)  │  (signed)  │ momoru.dedyn.io     │
      ▲                 └─────────────┘            │  └ Firebase Hosting │
      │ speech                                     │      (TLS proxy)    │
      │                                            └─────────┬──────────┘
      │                                                      │ rewrite
      │                                            ┌─────────▼──────────┐
      │                                            │ Cloud Run          │
      │                                            │  FastAPI backend   │
      │                                            │  • signature check │
      │                                            │  • rate limiting   │
      │                                            │  • Gemini client   │
      │                                            └─────────┬──────────┘
      │                                                      │ REST
      │            voice answer                     ┌────────▼──────────┐
      └─────────────────────────────────────────── │ Google Gemini API │
                                                    └───────────────────┘
```

Why the Firebase Hosting hop exists is the most interesting part of this
project — see [The certificate problem](#the-certificate-problem-a-real-world-gotcha).

## Tech stack

| Layer            | Technology                                  |
| ---------------- | ------------------------------------------- |
| Voice front-end  | Alexa Skills Kit (custom skill, `es-ES`)    |
| API              | FastAPI + Uvicorn (Python 3.12)             |
| LLM              | Google Gemini (`google-genai`, 2.5 Flash)   |
| Runtime          | Docker → Google Cloud Run (serverless)      |
| TLS / custom DNS | Firebase Hosting proxy + deSEC DNS          |
| CI/CD            | GitHub Actions + Workload Identity Federation |
| Security         | Request-signature verification, rate limiting |

## Features

- **Request signature verification** — validates Alexa's `Signature` /
  `SignatureCertChainUrl` headers and request timestamp on every call, exactly
  as Amazon requires for custom HTTPS endpoints.
- **Voice-optimized answers** — Gemini is instructed to reply in ≤3 sentences,
  no markdown, and runs with *thinking disabled* to stay well under Alexa's
  ~8-second response budget (dropped p99 latency from ~6.4 s to ~0.5 s).
- **Proxy-aware rate limiting** — keyed on the real client IP
  (`X-Forwarded-For`) so bot scanners hitting the public domain can't starve
  legitimate Alexa traffic.
- **Fully reproducible** — one script provisions the GCP project, another wires
  up keyless CI/CD. Deploy to *your own* account in minutes.
- **Zero-cost by design** — fits inside Cloud Run, Artifact Registry, Firebase
  Hosting, and Gemini free tiers.

## Quickstart (local)

```bash
git clone https://github.com/albertochaves-dev/alexa-gemini-cloudrun.git
cd alexa-gemini-cloudrun

python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # then paste your Gemini API key
# Get a free key at https://aistudio.google.com/apikey
# For local runs set VERIFY_ALEXA_SIGNATURE=false in .env

uvicorn app.main:app --reload
```

Send a test request (signature verification off locally):

```bash
curl -X POST http://localhost:8000/alexa \
  -H "Content-Type: application/json" \
  -d '{"request":{"type":"IntentRequest","timestamp":"2026-01-01T00:00:00Z",
       "intent":{"name":"PreguntarGeminiIntent",
       "slots":{"pregunta":{"value":"cuánto mide la torre eiffel"}}}}}'
```

## Tests & lint

```bash
pytest        # unit tests for the Alexa parsing/response layer and endpoint
ruff check .  # linting
```

## Deployment

Two paths, both documented in **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**:

1. **Automated CI/CD** — push to `main` and GitHub Actions builds the image and
   deploys to Cloud Run using keyless Workload Identity Federation.
2. **Manual** — `scripts/setup-gcp.sh` provisions everything, then a single
   `gcloud run deploy`.

The Alexa skill configuration (interaction model, endpoint, testing) is covered
in the same guide.

## The certificate problem (a real-world gotcha)

Alexa refuses to talk to a Cloud Run service directly. Cloud Run's default
`*.run.app` URLs are served with a **wildcard certificate over a domain on the
[Public Suffix List](https://publicsuffix.org/)**, and Alexa's endpoint
validator rejects exactly that combination:

```
Certificate for host 'xxx.run.app' contains wildcard '*.a.run.app'
```

No free hostname *inside* Google Cloud escapes this — every shared Google domain
(`run.app`, `web.app`, `appspot.com`) uses the same wildcard-over-public-suffix
setup. The fix is to front Cloud Run with **Firebase Hosting** bound to a
**custom domain** (a free `dedyn.io` subdomain from deSEC), which provisions an
**exact-hostname certificate** that Alexa accepts, and transparently proxies
requests to the Cloud Run service.

A second subtlety: the first DNS provider tried (DuckDNS) **silently drops CAA
and CNAME queries**, which makes automated certificate issuance impossible —
switching to a provider with a complete DNS implementation resolved it.

Full write-up in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Project structure

```
app/
├── main.py       # FastAPI app: POST /alexa, GET /health, middleware
├── alexa.py      # Alexa request parsing + response building
├── gemini.py     # Gemini client (thinking off, concise, voice-tuned)
├── security.py   # Signature verification, timestamp check, rate limiter
└── config.py     # Environment configuration
tests/            # pytest suite
docs/             # Architecture & deployment guides
scripts/          # Reproducible GCP + CI/CD setup
.github/workflows # CI (lint/test) and CD (build/deploy to Cloud Run)
```

## License

[MIT](LICENSE) © Alberto Chaves Herreros
