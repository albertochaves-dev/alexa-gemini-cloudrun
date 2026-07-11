from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_launch_request():
    payload = {"request": {"type": "LaunchRequest", "timestamp": "2024-01-01T00:00:00Z"}}
    response = client.post("/alexa", json=payload)
    assert response.status_code == 200
    assert response.json()["response"]["shouldEndSession"] is False


def test_gemini_intent(monkeypatch):
    monkeypatch.setattr("app.main.ask_gemini", lambda question: "respuesta de prueba")
    payload = {
        "request": {
            "type": "IntentRequest",
            "intent": {
                "name": "PreguntarGeminiIntent",
                "slots": {"pregunta": {"value": "que hora es"}},
            },
        }
    }
    response = client.post("/alexa", json=payload)
    assert response.status_code == 200
    assert response.json()["response"]["outputSpeech"]["text"] == "respuesta de prueba"


def test_gemini_intent_missing_slot():
    payload = {
        "request": {
            "type": "IntentRequest",
            "intent": {"name": "PreguntarGeminiIntent", "slots": {}},
        }
    }
    response = client.post("/alexa", json=payload)
    assert response.status_code == 200
    assert response.json()["response"]["shouldEndSession"] is False


def test_stop_intent():
    payload = {"request": {"type": "IntentRequest", "intent": {"name": "AMAZON.StopIntent"}}}
    response = client.post("/alexa", json=payload)
    assert response.status_code == 200
    assert response.json()["response"]["shouldEndSession"] is True


def test_session_ended_request():
    payload = {"request": {"type": "SessionEndedRequest"}}
    response = client.post("/alexa", json=payload)
    assert response.status_code == 200
    assert response.json() == {"version": "1.0", "response": {}}
