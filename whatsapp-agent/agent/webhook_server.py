"""
Servidor webhook FastAPI — recebe mensagens da Evolution API e responde via Claude.
Também expõe POST /chat para o web app compras-aconorte.
"""
import io
import logging

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from agent.chat_client import chat_response, get_usage_stats
from agent.excel_export import gerar_excel
from agent.minio_kpis import debug_vendas_hoje
from agent.whatsapp_client import send_message

log = logging.getLogger(__name__)

app = FastAPI(title="BI Aço Norte — WhatsApp Agent", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    sender: str = "web_user"


@app.post("/chat")
async def chat(req: ChatRequest):
    """Endpoint para o web app — recebe pergunta, devolve resposta da IA."""
    try:
        reply = chat_response(req.sender, req.message)
        return {"reply": reply}
    except Exception as exc:
        log.error("Erro no /chat: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


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


@app.get("/usage")
async def usage():
    """Retorna o consumo de tokens acumulado desde o último restart."""
    stats = get_usage_stats()
    # Preços claude-sonnet-4-6: $3/M input, $0.30/M cached read, $15/M output
    total = stats["total"]
    cached = total.get("cached", 0)
    normal_input = total["input"] - cached
    custo_usd = (normal_input / 1_000_000 * 3) + (cached / 1_000_000 * 0.30) + (total["output"] / 1_000_000 * 15)
    return {**stats, "custo_estimado_usd": round(custo_usd, 4)}


@app.get("/relatorio/excel")
async def relatorio_excel(
    tipo: str = "kpis_gerais",
    periodo: str = "mes_atual",
    data: str | None = None,
    top_n: int = 5,
    grupos: str | None = None,
    threshold_margem_pct: float = 13.0,
    cobertura_meses: int = 3,
):
    """
    Gera um .xlsx do relatório pedido, aplicando os mesmos filtros da consulta via chat.
    `periodo=dia_especifico` + `data=AAAA-MM-DD` gera o relatório de um dia qualquer do mês.
    `grupos` é uma lista separada por vírgula (ex.: TELHAS,VERGALHÕES).
    """
    try:
        grupos_lista = [g.strip() for g in grupos.split(",")] if grupos else None
        conteudo = gerar_excel(
            tipo=tipo, periodo=periodo, data=data, top_n=top_n,
            grupos=grupos_lista, threshold_margem_pct=threshold_margem_pct,
            cobertura_meses=cobertura_meses,
        )
    except Exception as exc:
        log.error("Erro ao gerar Excel (tipo=%s periodo=%s data=%s): %s", tipo, periodo, data, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    sufixo_data = f"_{data}" if data else ""
    nome_arquivo = f"{tipo}_{periodo}{sufixo_data}.xlsx"
    return StreamingResponse(
        io.BytesIO(conteudo),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@app.get("/debug/vendas")
async def debug_vendas():
    """Diagnóstico: retorna números brutos do fat_vendas para hoje."""
    try:
        return debug_vendas_hoje()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
async def health():
    return {"status": "ok", "instance": config.EVOLUTION_INSTANCE}
