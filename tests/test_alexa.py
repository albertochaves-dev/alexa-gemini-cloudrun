from app.alexa import build_response, parse_intent_name, parse_request_type, parse_slot_value


def test_build_response_default_ends_session():
    resp = build_response("hola")
    assert resp["response"]["shouldEndSession"] is True
    assert resp["response"]["outputSpeech"]["text"] == "hola"


def test_build_response_with_reprompt():
    resp = build_response("hola", end_session=False, reprompt_text="repite")
    assert resp["response"]["shouldEndSession"] is False
    assert resp["response"]["reprompt"]["outputSpeech"]["text"] == "repite"


def test_parse_request_type():
    payload = {"request": {"type": "LaunchRequest"}}
    assert parse_request_type(payload) == "LaunchRequest"


def test_parse_intent_name():
    payload = {"request": {"intent": {"name": "PreguntarGeminiIntent"}}}
    assert parse_intent_name(payload) == "PreguntarGeminiIntent"


def test_parse_slot_value():
    payload = {
        "request": {
            "intent": {"slots": {"pregunta": {"name": "pregunta", "value": "que hora es"}}}
        }
    }
    assert parse_slot_value(payload, "pregunta") == "que hora es"


def test_parse_slot_value_missing():
    payload = {"request": {"intent": {"slots": {}}}}
    assert parse_slot_value(payload, "pregunta") is None
