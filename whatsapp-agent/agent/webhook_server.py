"""
Servidor webhook FastAPI — recebe mensagens da Evolution API e responde via Claude.
"""
import logging

from fastapi import FastAPI, Request, HTTPException

import config
from agent.chat_client import chat_response
from agent.whatsapp_client import send_message

log = logging.getLogger(__name__)

app = FastAPI(title="BI Aço Norte — WhatsApp Agent", docs_url=None, redoc_url=None)


def _extract_text(message: dict) -> str:
    """Extrai o texto de diferentes tipos de mensagem da Evolution API."""
    return (
        message.get("conversation")
        or message.get("extendedTextMessage", {}).get("text")
        or message.get("imageMessage", {}).get("caption")
        or ""
    ).strip()


@app.post("/webhook")
async def webhook(request: Request):
    # Validação de token (opcional, mas recomendado)
    if config.WEBHOOK_TOKEN:
        token = (
            request.headers.get("apikey")
            or request.headers.get("authorization", "").removeprefix("Bearer ")
            or request.query_params.get("token")
        )
        if token != config.WEBHOOK_TOKEN:
            raise HTTPException(status_code=403, detail="Unauthorized")

    payload = await request.json()

    event = payload.get("event")
    instance = payload.get("instance")

    # Ignora eventos que não são mensagens recebidas ou de outra instância
    if event != "messages.upsert" or instance != config.EVOLUTION_INSTANCE:
        return {"status": "ignored"}

    data = payload.get("data", {})
    key = data.get("key", {})

    # Ignora mensagens enviadas por nós mesmos
    if key.get("fromMe"):
        return {"status": "ignored"}

    remote_jid: str = key.get("remoteJid", "")
    # Extrai o número do JID: "5511999999999@s.whatsapp.net" → "5511999999999"
    sender = remote_jid.split("@")[0]

    # Só responde a destinatários autorizados
    if sender not in config.WHATSAPP_RECIPIENTS:
        log.debug("Remetente não autorizado: %s", sender)
        return {"status": "ignored"}

    text = _extract_text(data.get("message", {}))
    if not text:
        return {"status": "ignored"}

    log.info("Mensagem de %s: %.60s", sender, text)

    try:
        reply = chat_response(sender, text)
        send_message(remote_jid, reply)
        log.info("Resposta enviada para %s", sender)
    except Exception as exc:
        log.error("Erro ao processar mensagem de %s: %s", sender, exc)

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "instance": config.EVOLUTION_INSTANCE}
