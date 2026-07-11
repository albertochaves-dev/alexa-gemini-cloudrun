from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, GEMINI_MODEL

_client = None

SYSTEM_INSTRUCTION = (
    "Eres un asistente de voz que responde a través de un altavoz Alexa. "
    "Responde en español, de forma breve y directa, en un máximo de 3 frases. "
    "No uses listas, markdown ni emojis: tu respuesta se leerá en voz alta."
)

_GENERATION_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    max_output_tokens=300,
    # gemini-2.5-flash razona ("thinking") por defecto y añade varios segundos;
    # lo desactivamos para responder dentro del límite de tiempo de Alexa.
    thinking_config=types.ThinkingConfig(thinking_budget=0),
)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def ask_gemini(prompt: str) -> str:
    client = _get_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=_GENERATION_CONFIG,
    )
    text = (response.text or "").strip()
    return text or "No he podido generar una respuesta."
