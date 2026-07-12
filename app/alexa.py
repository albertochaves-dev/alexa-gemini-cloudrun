from typing import Any, Optional


def parse_request_type(payload: dict) -> str:
    return payload.get("request", {}).get("type", "")


def parse_intent_name(payload: dict) -> Optional[str]:
    return payload.get("request", {}).get("intent", {}).get("name")


def parse_slot_value(payload: dict, slot_name: str) -> Optional[str]:
    slots = payload.get("request", {}).get("intent", {}).get("slots", {})
    slot = slots.get(slot_name)
    if not slot:
        return None
    return slot.get("value")


def _escape_ssml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _output_speech(text: str, voice: Optional[str] = None) -> dict[str, str]:
    # When a voice is given, wrap the text in SSML so Gemini's answers can be
    # spoken with a distinct voice — audibly different from Alexa's own replies.
    if voice:
        return {
            "type": "SSML",
            "ssml": f'<speak><voice name="{voice}">{_escape_ssml(text)}</voice></speak>',
        }
    return {"type": "PlainText", "text": text}


def build_response(
    speech_text: str,
    *,
    end_session: bool = True,
    reprompt_text: Optional[str] = None,
    voice: Optional[str] = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "version": "1.0",
        "response": {
            "outputSpeech": _output_speech(speech_text, voice),
            "shouldEndSession": end_session,
        },
    }
    if reprompt_text:
        response["response"]["reprompt"] = {"outputSpeech": _output_speech(reprompt_text)}
    return response
