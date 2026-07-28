"""
Chat conversacional com Claude + tool use para consultar dados do MinIO.
Mantém histórico por remetente (in-memory, limitado a _MAX_TURNS turnos).
"""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import config
from pathlib import Path

import anthropic
from config import ANTHROPIC_API_KEY
from agent.minio_kpis import (
    get_kpis, get_ranking_vendedores, get_ranking_clientes, get_ranking_produtos,
    get_menores_margens_cliente, get_menores_margens_produto, get_margens_abaixo_threshold,
    get_faturamento_diario, get_vendas_canceladas, get_analise_compras,
)
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
- Você traz relatórios, rankings, KPIs e análises diretamente na conversa — não precisa do Power BI aberto
- PROIBIDO criar seções, listas ou frases do tipo "não consigo", "não faço", "fora do escopo", "limitação", "mas NÃO", "não tenho acesso"
- Se alguém perguntar o que você faz: liste APENAS o que consegue fazer, nunca o que não faz
- O Power BI é o painel visual — você é o assistente que TRAZ os dados em texto/tabela/gráfico na conversa
- Quando o usuário fizer MÚLTIPLAS perguntas de uma vez, responda UMA por vez e ao final pergunte: "Quer ver o próximo relatório?"
- Se precisar de dados, chame a ferramenta antes de responder

Formato de gráfico (use quando os dados ficam mais claros visualmente):
- Rankings, comparativos e faturamento diário: use o bloco especial abaixo
- O sistema renderiza gráficos interativos automaticamente quando você usar esse formato

```chart
{"type": "bar", "titulo": "Título do gráfico", "dados": [{"nome": "Item A", "valor": 1000}, {"nome": "Item B", "valor": 800}], "chave_label": "nome", "chave_valor": "valor", "formato": "moeda"}
```

Tipos disponíveis: "bar" (ranking/comparativo), "line" (evolução no tempo)
Formato dos valores: "moeda" (R$), "numero", "percentual" (%)
Sempre inclua também a tabela markdown junto ao gráfico para detalhes.

""" + (_SEMANTIC_CONTEXT if _SEMANTIC_CONTEXT else "")

_BI_TOOL = {
    "name": "consultar_dados",
    "description": (
        "Consulta dados do BI da Aço Norte. Use para qualquer pergunta sobre "
        "vendas, rankings, margens, estoque, financeiro, cancelamentos ou análise de compras. "
        "Os filtros (por grupo, margem, período) são aplicados nos dados — não no Power BI."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tipo": {
                "type": "string",
                "enum": [
                    "kpis_gerais",
                    "ranking_vendedores", "ranking_clientes", "ranking_produtos",
                    "estoque", "financeiro",
                    "menores_margens_cliente", "menores_margens_produto",
                    "margens_abaixo_threshold",
                    "faturamento_diario",
                    "vendas_canceladas",
                    "analise_compras",
                ],
                "description": (
                    "Tipo de consulta: "
                    "kpis_gerais=resumo geral, "
                    "ranking_*=classificação por faturamento, "
                    "menores_margens_*=piores margens, "
                    "margens_abaixo_threshold=clientes/vendedores com margem abaixo de X%, "
                    "faturamento_diario=faturamento dia a dia no mês, "
                    "vendas_canceladas=cancelamentos do período, "
                    "analise_compras=o que precisa comprar com cobertura simulada"
                )
            },
            "periodo": {
                "type": "string",
                "enum": ["hoje", "mes_atual", "mes_anterior"],
                "description": "Período. Padrão: mes_atual"
            },
            "top_n": {
                "type": "integer",
                "description": "Qtd de itens no ranking (padrão: 5)"
            },
            "grupos": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filtro por grupos de produto (ex: ['TELHAS', 'VERGALHÕES', 'TRELIÇAS'])"
            },
            "threshold_margem_pct": {
                "type": "number",
                "description": "Percentual mínimo de margem para filtro (ex: 13 para 13%)"
            },
            "cobertura_meses": {
                "type": "integer",
                "description": "Meses de cobertura desejados na análise de compras (padrão: 3)"
            }
        },
        "required": ["tipo"]
    }
}


def _executar_consulta(tipo: str, periodo: str = "mes_atual", top_n: int = 5,
                       grupos: list | None = None, threshold_margem_pct: float = 13.0,
                       cobertura_meses: int = 3) -> str:
    try:
    now = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%d/%m/%Y %H:%M")

        if tipo == "ranking_vendedores":
            return json.dumps({"data_hora": now, "periodo": periodo, "ranking_vendedores": get_ranking_vendedores(periodo, top_n)}, ensure_ascii=False, indent=2)
        if tipo == "ranking_clientes":
            return json.dumps({"data_hora": now, "periodo": periodo, "ranking_clientes": get_ranking_clientes(periodo, top_n)}, ensure_ascii=False, indent=2)
        if tipo == "ranking_produtos":
            return json.dumps({"data_hora": now, "periodo": periodo, "ranking_produtos": get_ranking_produtos(periodo, top_n)}, ensure_ascii=False, indent=2)
        if tipo == "menores_margens_cliente":
            return json.dumps({"data_hora": now, "periodo": periodo, "menores_margens_cliente": get_menores_margens_cliente(periodo, top_n)}, ensure_ascii=False, indent=2)
        if tipo == "menores_margens_produto":
            return json.dumps({"data_hora": now, "periodo": periodo, "menores_margens_produto": get_menores_margens_produto(periodo, top_n)}, ensure_ascii=False, indent=2)
        if tipo == "margens_abaixo_threshold":
            return json.dumps({"data_hora": now, "periodo": periodo, "threshold_pct": threshold_margem_pct, "resultado": get_margens_abaixo_threshold(threshold_margem_pct, periodo)}, ensure_ascii=False, indent=2)
        if tipo == "faturamento_diario":
            return json.dumps({"data_hora": now, **get_faturamento_diario()}, ensure_ascii=False, indent=2)
        if tipo == "vendas_canceladas":
            return json.dumps({"data_hora": now, "periodo": periodo, **get_vendas_canceladas(periodo)}, ensure_ascii=False, indent=2)
        if tipo == "analise_compras":
            return json.dumps({"data_hora": now, "cobertura_simulada_meses": cobertura_meses, "grupos_filtro": grupos, "produtos": get_analise_compras(grupos, cobertura_meses)}, ensure_ascii=False, indent=2)

        kpis = get_kpis(periodo)
        vendas = kpis.get("vendas", {})
        if tipo == "estoque":
            return json.dumps({"data_hora": now, "estoque": _humanize_estoque(kpis.get("estoque", {}))}, ensure_ascii=False, indent=2)
        if tipo == "financeiro":
            return json.dumps({"data_hora": now, "periodo": periodo, "financeiro": _humanize_financeiro(kpis.get("financeiro", {}))}, ensure_ascii=False, indent=2)

        return json.dumps({
            "data_hora": now, "periodo": periodo,
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
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            tool_results = []
            for tool_block in tool_blocks:
                args = tool_block.input if isinstance(tool_block.input, dict) else {}
                log.info("Tool use: %s args=%s (sender=%s)", tool_block.name, args, sender)
                result = _executar_consulta(
                    tipo=args.get("tipo", "kpis_gerais"),
                    periodo=args.get("periodo", "mes_atual"),
                    top_n=args.get("top_n", 5),
                    grupos=args.get("grupos"),
                    threshold_margem_pct=args.get("threshold_margem_pct", 13.0),
                    cobertura_meses=args.get("cobertura_meses", 3),
                )
                tool_results.append({"type": "tool_result", "tool_use_id": tool_block.id, "content": result})

            history.append({"role": "assistant", "content": response.content})
            history.append({"role": "user", "content": tool_results})
        else:
            text = next((b.text for b in response.content if b.type == "text"), "")
            history.append({"role": "assistant", "content": text})
            return text

    return "Desculpe, não consegui processar sua solicitação agora. Tente novamente."
