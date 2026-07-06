"""
Chat conversacional com Claude + tool use para consultar dados do MinIO.
Mantém histórico por remetente (in-memory, limitado a _MAX_TURNS turnos).
"""
import json
import logging
from datetime import datetime
from pathlib import Path

import anthropic
from config import ANTHROPIC_API_KEY
from agent.minio_kpis import get_kpis, get_ranking_vendedores, get_ranking_clientes, get_ranking_produtos
from agent.llm_client import _humanize_vendas, _humanize_estoque, _humanize_financeiro

log = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_MAX_TURNS = 5

_histories: dict[str, list[dict]] = {}

_usage: dict[str, dict] = {}
_usage_total: dict[str, int] = {"input": 0, "cached": 0, "output": 0, "calls": 0}


def get_usage_stats() -> dict:
    return {"total": dict(_usage_total), "por_usuario": dict(_usage)}


_CONTEXT_FILE = Path(__file__).parent / "semantic_context.md"
_SEMANTIC_CONTEXT = _CONTEXT_FILE.read_text(encoding="utf-8") if _CONTEXT_FILE.exists() else ""

_SYSTEM = """Você é o assistente de BI da Aço Norte, uma distribuidora de aços do Ceará.
Responda em português do Brasil, de forma direta e amigável.

Regras de formatação:
- Use markdown para estruturar respostas: **negrito**, tabelas (|col|col|), listas
- Tabelas são ideais para rankings e comparativos — use sempre que listar mais de 3 itens
- Para valores monetários: R$ 1.234,56 | Para percentuais: 12,34%
- Seja conciso: destaque os números mais importantes primeiro
- Quando precisar de dados, use a ferramenta consultar_dados com os parâmetros corretos

Regras de comportamento:
- NUNCA liste suas limitações ou o que não consegue fazer
- Foque sempre no que você PODE responder
- Se precisar de dados, chame a ferramenta antes de responder
- Para rankings, sempre mostre em formato de tabela ordenada

""" + (_SEMANTIC_CONTEXT if _SEMANTIC_CONTEXT else "")

_BI_TOOL = {
    "name": "consultar_dados",
    "description": (
        "Consulta dados do BI da Aço Norte. Use para responder qualquer pergunta "
        "sobre vendas, rankings, estoque, financeiro ou comparativos de períodos."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tipo": {
                "type": "string",
                "enum": ["kpis_gerais", "ranking_vendedores", "ranking_clientes", "ranking_produtos", "estoque", "financeiro"],
                "description": "Tipo de consulta: kpis_gerais para totais, ranking_* para classificações, estoque/financeiro para dados específicos"
            },
            "periodo": {
                "type": "string",
                "enum": ["hoje", "mes_atual", "mes_anterior"],
                "description": "Período da consulta. Padrão: mes_atual"
            },
            "top_n": {
                "type": "integer",
                "description": "Quantidade de itens no ranking (padrão: 5)"
            }
        },
        "required": ["tipo"]
    }
}


def _executar_consulta(tipo: str, periodo: str = "mes_atual", top_n: int = 5) -> str:
    try:
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        if tipo == "ranking_vendedores":
            dados = get_ranking_vendedores(periodo, top_n)
            return json.dumps({"data_hora": now, "periodo": periodo, "ranking_vendedores": dados}, ensure_ascii=False, indent=2)

        if tipo == "ranking_clientes":
            dados = get_ranking_clientes(periodo, top_n)
            return json.dumps({"data_hora": now, "periodo": periodo, "ranking_clientes": dados}, ensure_ascii=False, indent=2)

        if tipo == "ranking_produtos":
            dados = get_ranking_produtos(periodo, top_n)
            return json.dumps({"data_hora": now, "periodo": periodo, "ranking_produtos": dados}, ensure_ascii=False, indent=2)

        kpis = get_kpis(periodo)
        vendas = kpis.get("vendas", {})

        if tipo == "estoque":
            return json.dumps({"data_hora": now, "estoque": _humanize_estoque(kpis.get("estoque", {}))}, ensure_ascii=False, indent=2)

        if tipo == "financeiro":
            return json.dumps({"data_hora": now, "periodo": periodo, "financeiro": _humanize_financeiro(kpis.get("financeiro", {}))}, ensure_ascii=False, indent=2)

        # kpis_gerais
        return json.dumps({
            "data_hora": now,
            "periodo": periodo,
            "vendas_hoje": json.loads(_humanize_vendas(vendas.get("hoje", {}))),
            "vendas_periodo": json.loads(_humanize_vendas(vendas.get("mes", {}))),
            "estoque": json.loads(_humanize_estoque(kpis.get("estoque", {}))),
            "financeiro": json.loads(_humanize_financeiro(kpis.get("financeiro", {}))),
        }, ensure_ascii=False, indent=2)

    except Exception as exc:
        return json.dumps({"erro": f"Não foi possível buscar os dados: {exc}"})


def chat_response(sender: str, message: str) -> str:
    history = _histories.setdefault(sender, [])
    history.append({"role": "user", "content": message})

    if len(history) > _MAX_TURNS * 2:
        history[:] = history[-(_MAX_TURNS * 2):]

    for _ in range(5):
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=[_BI_TOOL],
            messages=history,
        )

        u = response.usage
        cached = getattr(u, "cache_read_input_tokens", 0) or 0
        sender_stats = _usage.setdefault(sender, {"input": 0, "cached": 0, "output": 0, "calls": 0})
        sender_stats["input"]  += u.input_tokens
        sender_stats["cached"] += cached
        sender_stats["output"] += u.output_tokens
        sender_stats["calls"]  += 1
        _usage_total["input"]  += u.input_tokens
        _usage_total["cached"] += cached
        _usage_total["output"] += u.output_tokens
        _usage_total["calls"]  += 1
        log.info("Tokens [%s] in=%d cached=%d out=%d | total in=%d out=%d",
                 sender, u.input_tokens, cached, u.output_tokens,
                 _usage_total["input"], _usage_total["output"])

        if response.stop_reason == "tool_use":
            tool_block = next(b for b in response.content if b.type == "tool_use")
            args = tool_block.input if isinstance(tool_block.input, dict) else {}
            log.info("Tool use: %s args=%s (sender=%s)", tool_block.name, args, sender)

            result = _executar_consulta(
                tipo=args.get("tipo", "kpis_gerais"),
                periodo=args.get("periodo", "mes_atual"),
                top_n=args.get("top_n", 5),
            )

            history.append({"role": "assistant", "content": response.content})
            history.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_block.id, "content": result}],
            })
        else:
            text = next((b.text for b in response.content if b.type == "text"), "")
            history.append({"role": "assistant", "content": text})
            return text

    return "Desculpe, não consegui processar sua solicitação agora. Tente novamente."
