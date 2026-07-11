import logging

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import JSONResponse

from app.alexa import build_response, parse_intent_name, parse_request_type, parse_slot_value
from app.config import (
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    VERIFY_ALEXA_SIGNATURE,
)
from app.gemini import ask_gemini
from app.security import RateLimiter, verify_alexa_signature, verify_timestamp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alexa")

app = FastAPI(title="Alexa Gemini Skill")
rate_limiter = RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)

SLOT_NAME = "pregunta"
WELCOME_TEXT = "Hola, soy tu asistente con inteligencia artificial. ¿Qué quieres preguntarme?"
HELP_TEXT = "Puedes preguntarme lo que quieras y te responderé usando inteligencia artificial."
GOODBYE_TEXT = "Hasta luego."
FALLBACK_TEXT = "No te he entendido. ¿Puedes repetirlo?"
ERROR_TEXT = "Ha ocurrido un error al conectar con la inteligencia artificial."


def _client_key(request: Request) -> str:
    # Detrás de Firebase Hosting/Cloud Run, request.client.host es siempre la IP
    # interna del proxy, así que todo el tráfico compartiría un único cubo. Usamos
    # la IP original del cliente (primer salto de X-Forwarded-For) para separar
    # cada origen (Alexa vs. escáneres de bots) en su propio límite.
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not rate_limiter.allow(_client_key(request)):
        logger.warning("rate_limited key=%s path=%s", _client_key(request), request.url.path)
        return JSONResponse(status_code=429, content={"detail": "Too many requests"})
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/alexa")
async def alexa_endpoint(request: Request) -> dict:
    body = await request.body()

    if VERIFY_ALEXA_SIGNATURE:
        signature = request.headers.get("Signature")
        cert_url = request.headers.get("SignatureCertChainUrl")
        if not signature or not cert_url or not verify_alexa_signature(cert_url, signature, body):
            logger.warning("signature_invalid")
            raise HTTPException(status_code=403, detail="Invalid request signature")

    payload = await request.json()

    if VERIFY_ALEXA_SIGNATURE:
        timestamp = payload.get("request", {}).get("timestamp", "")
        if not verify_timestamp(timestamp):
            logger.warning("timestamp_invalid ts=%s", timestamp)
            raise HTTPException(status_code=403, detail="Request timestamp outside tolerance")

    request_type = parse_request_type(payload)
    intent_name = parse_intent_name(payload) if request_type == "IntentRequest" else None
    slot_value = parse_slot_value(payload, SLOT_NAME) if intent_name else None
    logger.info(
        "request type=%s intent=%s slot_filled=%s slot_len=%s",
        request_type,
        intent_name,
        bool(slot_value),
        len(slot_value) if slot_value else 0,
    )

    if request_type == "LaunchRequest":
        return build_response(WELCOME_TEXT, end_session=False, reprompt_text=WELCOME_TEXT)

    if request_type == "IntentRequest":
        if intent_name == "AMAZON.HelpIntent":
            return build_response(HELP_TEXT, end_session=False, reprompt_text=HELP_TEXT)

        if intent_name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return build_response(GOODBYE_TEXT)

        if intent_name == "PreguntarGeminiIntent":
            if not slot_value:
                return build_response(FALLBACK_TEXT, end_session=False, reprompt_text=FALLBACK_TEXT)
            try:
                answer = ask_gemini(slot_value)
            except Exception:
                logger.exception("gemini_error")
                return build_response(ERROR_TEXT, end_session=False, reprompt_text="¿Algo más?")
            return build_response(answer, end_session=False, reprompt_text="¿Algo más?")

        return build_response(FALLBACK_TEXT, end_session=False, reprompt_text=FALLBACK_TEXT)

    if request_type == "SessionEndedRequest":
        return {"version": "1.0", "response": {}}

    raise HTTPException(status_code=400, detail="Unsupported request type")
