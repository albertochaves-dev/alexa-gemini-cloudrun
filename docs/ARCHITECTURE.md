# Architecture

## Request lifecycle

1. **Echo device → Alexa Cloud.** The user speaks. Amazon's ASR/NLU converts
   speech to an intent and slot values (`PreguntarGeminiIntent` with an
   `AMAZON.SearchQuery` slot named `pregunta`).
2. **Alexa Cloud → HTTPS endpoint.** Alexa sends a signed JSON POST to the
   skill endpoint (`https://momoru.dedyn.io/alexa`). The request carries
   `Signature` and `SignatureCertChainUrl` headers plus a `timestamp`.
3. **Firebase Hosting → Cloud Run.** The custom domain resolves to Firebase
   Hosting, which terminates TLS with an exact-hostname certificate and
   rewrites the request to the Cloud Run service.
4. **FastAPI backend.** Middleware applies rate limiting; the handler verifies
   the signature and timestamp, parses the intent, and dispatches.
5. **Gemini.** For a question intent, the backend calls Gemini and maps the
   answer into Alexa's response envelope (`outputSpeech`), keeping the session
   open for follow-ups.

## Component responsibilities

| Module            | Responsibility                                              |
| ----------------- | ----------------------------------------------------------- |
| `app/main.py`     | Routing, middleware, request dispatch, logging              |
| `app/alexa.py`    | Pure functions: parse request type/intent/slot, build reply |
| `app/gemini.py`   | Gemini client, prompt/config tuning                         |
| `app/security.py` | Signature verification, timestamp check, rate limiter       |
| `app/config.py`   | Environment-driven configuration                            |

The Alexa layer is intentionally made of **pure functions** so the request
parsing and response shaping are trivially unit-testable without HTTP or Gemini.

## The certificate problem

### Symptom

Pointing the Alexa skill directly at the Cloud Run URL produced a generic
*"no puedo conectar con la skill"* on device, and — via the ASK
`invoke-skill` diagnostic API — the precise cause:

```
Certificate for host 'alexa-gemini-xxx.a.run.app' contains wildcard '*.a.run.app'
```

### Root cause

Alexa's custom-endpoint validator enforces strict rules on the TLS certificate.
Cloud Run's built-in domains (`*.run.app`) present a **wildcard certificate**,
and `run.app` is on the **Public Suffix List** (the registry browsers use to
isolate cookies between unrelated tenants). Alexa treats a wildcard spanning a
public-suffix domain as untrustworthy — the same way a `*.com` certificate would
be. **Every free hostname inside Google Cloud** (`run.app`, `web.app`,
`appspot.com`) shares this exact property, so no amount of switching Google
products avoids it.

### Solution

Front Cloud Run with **Firebase Hosting** bound to a **custom domain**:

- A free `dedyn.io` subdomain (deSEC) is added as a Firebase Hosting custom
  domain. Firebase provisions a **single-host certificate** (`CN=momoru.dedyn.io`,
  no wildcard) that Alexa accepts.
- A Hosting `rewrite` rule proxies all traffic to the Cloud Run service, so the
  backend is unchanged and still benefits from Cloud Run autoscaling.

```json
// firebase.json
{
  "hosting": {
    "public": "public",
    "rewrites": [
      { "source": "**", "run": { "serviceId": "alexa-gemini", "region": "europe-southwest1" } }
    ]
  }
}
```

### Secondary gotcha: DNS provider correctness

The first DNS provider tried (**DuckDNS**) silently **drops `CAA` and `CNAME`
queries** — the nameservers return nothing instead of an authoritative "no
records" answer. Certificate authorities are *required* to check CAA before
issuing, so a dropped CAA query reads as "cannot verify" and issuance stalls
indefinitely (Firebase reported `DNS_SERVFAIL`). Moving to **deSEC**, whose
nameservers implement all query types correctly, allowed the ACME challenge and
certificate to complete in minutes.

**Takeaway:** "the A record resolves" is not sufficient for automated TLS — the
authoritative nameservers must answer *every* query type, including CAA.

## Latency engineering

Alexa aborts a skill response after roughly **8 seconds**. Early tests showed
backend latency of **~6.4 s** for a single question — dangerously close, and it
timed out on device.

The dominant cost was **Gemini 2.5 Flash's default "thinking" phase**. Disabling
it and constraining the output collapsed latency:

```python
types.GenerateContentConfig(
    system_instruction="…responde breve, máximo 3 frases, sin markdown…",
    max_output_tokens=300,
    thinking_config=types.ThinkingConfig(thinking_budget=0),  # ← the big win
)
```

Result: warm requests **~0.5 s**, cold starts **~2–3 s**, both comfortably
inside the budget.

| Change                         | Backend latency |
| ------------------------------ | --------------- |
| Default 2.5 Flash (thinking on)| ~6.4 s          |
| Thinking off + concise config  | ~0.5 s (warm)   |

## Rate limiting behind a proxy

A naive in-memory limiter keyed on `request.client.host` is broken behind
Firebase Hosting + Cloud Run: **every** request arrives from the same internal
proxy IP, so all traffic — legitimate Alexa calls *and* internet bot scanners
hitting the public domain — shares a single bucket. During testing, scanner
floods tripped the limit and returned `429` to real Alexa requests.

The limiter is therefore keyed on the **left-most `X-Forwarded-For` IP** (the
original client), isolating each source into its own bucket. Signature
verification remains the primary security control; rate limiting is a
defense-in-depth guard against abuse and accidental self-DoS.

## Security model

- **Signature verification** (`app/security.py`): validates the certificate
  chain URL against Amazon's allowed pattern, checks certificate validity dates,
  verifies the RSA-SHA1 signature over the raw body, and enforces a ±150 s
  timestamp tolerance. Toggled by `VERIFY_ALEXA_SIGNATURE` (on in production,
  off for local development).
- **Secrets**: the Gemini API key is never committed. Locally it lives in
  `.env` (git-ignored); in CI/CD it is a GitHub Actions secret injected as a
  Cloud Run environment variable at deploy time.
- **Least-privilege CI**: GitHub Actions authenticates via **Workload Identity
  Federation** — no long-lived service-account JSON key exists to leak.
