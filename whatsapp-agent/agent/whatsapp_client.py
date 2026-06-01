"""
Envia mensagens via Evolution API (self-hosted).
Suporta números individuais e grupos (@g.us).
"""
import requests
from config import EVOLUTION_API_URL, EVOLUTION_API_KEY, EVOLUTION_INSTANCE

_HEADERS = {
    "apikey": EVOLUTION_API_KEY,
    "Content-Type": "application/json",
}


def send_message(recipient: str, text: str) -> dict:
    """
    Envia texto para um número ou grupo.
    recipient: '5511999999999' para indivíduo ou 'ID@g.us' para grupo.
    """
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    payload = {
        "number": recipient,
        "text": text,
        "delay": 1200,  # ms de delay para parecer digitação humana
    }
    resp = requests.post(url, json=payload, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def broadcast(recipients: list[str], text: str) -> list[dict]:
    """Envia a mesma mensagem para múltiplos destinatários."""
    results = []
    for recipient in recipients:
        try:
            result = send_message(recipient, text)
            results.append({"recipient": recipient, "status": "ok", "data": result})
        except requests.HTTPError as e:
            results.append({"recipient": recipient, "status": "error", "error": str(e)})
    return results


def check_instance() -> bool:
    """Verifica se a instância da Evolution API está conectada."""
    url = f"{EVOLUTION_API_URL}/instance/connectionState/{EVOLUTION_INSTANCE}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        state = resp.json().get("instance", {}).get("state", "")
        return state == "open"
    except requests.RequestException:
        return False
