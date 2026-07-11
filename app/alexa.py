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


def build_response(
    speech_text: str,
    *,
    end_session: bool = True,
    reprompt_text: Optional[str] = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": speech_text},
            "shouldEndSession": end_session,
        },
    }
    if reprompt_text:
        response["response"]["reprompt"] = {
            "outputSpeech": {"type": "PlainText", "text": reprompt_text}
        }
    return response
