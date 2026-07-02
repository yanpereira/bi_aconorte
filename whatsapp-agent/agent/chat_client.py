"""
Chat conversacional com Claude + tool use para consultar o Power BI / MinIO.
Mantém histórico por remetente (in-memory, limitado a _MAX_TURNS turnos).
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import anthropic
from config import ANTHROPIC_API_KEY
from agent.minio_kpis import get_kpis
from agent.llm_client import _humanize_vendas, _humanize_estoque, _humanize_financeiro

log = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_MAX_TURNS = 10  # pares user/assistant mantidos por remetente

_histories: dict[str, list[dict]] = {}

# Carrega o contexto semântico completo do modelo de BI
_CONTEXT_FILE = Path(__file__).parent / "semantic_context.md"
_SEMANTIC_CONTEXT = _CONTEXT_FILE.read_text(encoding="utf-8") if _CONTEXT_FILE.exists() else ""

_SYSTEM = """Você é o assistente de BI da Aço Norte, uma distribuidora de aços do Ceará.
Responda em português do Brasil, de forma direta e amigável para WhatsApp.

Regras de formatação:
- Não use markdown (sem **, ##, ---) — WhatsApp não renderiza
- Use emojis com moderação para facilitar a leitura
- Para valores monetários: R$ 1.234,56 | Para percentuais: 12,34%
- Máximo de 60 caracteres por linha para não quebrar no celular
- Quando precisar de dados atuais (números do dia/mês), use a ferramenta get_bi_data
- Para perguntas conceituais sobre o modelo, métricas ou regras de negócio, responda usando o contexto abaixo

""" + (_SEMANTIC_CONTEXT if _SEMANTIC_CONTEXT else "")

_BI_TOOL = {
    "name": "get_bi_data",
    "description": (
        "Busca os KPIs atuais do Power BI da Aço Norte: vendas do mês, "
        "estoque e situação financeira. Use quando o usuário perguntar sobre "
        "números, metas, faturamento, estoque ou qualquer dado do negócio."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def _fetch_bi_tool_result() -> str:
    try:
        kpis = get_kpis()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        return json.dumps({
            "data_hora": now,
            "vendas_mes": json.loads(_humanize_vendas(kpis.get("vendas", {}))),
            "estoque": json.loads(_humanize_estoque(kpis.get("estoque", {}))),
            "financeiro": json.loads(_humanize_financeiro(kpis.get("financeiro", {}))),
        }, ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps({"erro": f"Não foi possível buscar os dados: {exc}"})


def chat_response(sender: str, message: str) -> str:
    """Processa uma mensagem e retorna a resposta do assistente."""
    history = _histories.setdefault(sender, [])
    history.append({"role": "user", "content": message})

    # Limita histórico para evitar crescimento ilimitado
    if len(history) > _MAX_TURNS * 2:
        history[:] = history[-(_MAX_TURNS * 2):]

    for _ in range(5):  # máximo de 5 rounds de tool use
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_SYSTEM,
            tools=[_BI_TOOL],
            messages=history,
        )

        if response.stop_reason == "tool_use":
            tool_block = next(b for b in response.content if b.type == "tool_use")
            log.info("Tool use: %s (sender=%s)", tool_block.name, sender)

            tool_result = _fetch_bi_tool_result()

            history.append({"role": "assistant", "content": response.content})
            history.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": tool_result,
                }],
            })
        else:
            text = next((b.text for b in response.content if b.type == "text"), "")
            history.append({"role": "assistant", "content": text})
            return text

    return "Desculpe, não consegui processar sua solicitação agora. Tente novamente."
