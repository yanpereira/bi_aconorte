"""
Chat conversacional com Claude + tool use para consultar dados do MinIO.
Mantém histórico por remetente (in-memory, limitado a _MAX_TURNS turnos).
"""
import json
import logging
import re
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
import config
from pathlib import Path

import anthropic
from config import ANTHROPIC_API_KEY
from agent import atalhos_store
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
- Quando o usuário pedir dados de um dia específico do mês (ex: "margens do dia 15", "vendas de 15/07"), use consultar_dados com periodo="dia_especifico" e data="AAAA-MM-DD" (use o ano/mês atual informado no contexto abaixo se o usuário não especificar)
- IMPORTANTE — datas relativas: use periodo="hoje" para "hoje", periodo="ontem" para "ontem" e periodo="anteontem" para "anteontem" — o servidor calcula a data certa, não tente calcular essas datas você mesmo nem use dia_especifico para elas. Ao escrever a resposta, use a data mostrada em "data_referencia"/"data_hora" do resultado da ferramenta (não invente a data de cabeça).
- Quando o usuário pedir para "gerar", "exportar", "baixar" ou "salvar em Excel/planilha" um relatório, use a ferramenta exportar_planilha_excel com os mesmos filtros já discutidos na conversa, e devolva o link como um markdown de download (ex: "[Baixar planilha](url)")
- O usuário pode salvar perguntas frequentes como atalhos, sem sua ajuda: "/salvar nome = pergunta completa" salva, "/nome" usa o atalho depois, "/atalhos" lista os salvos, "/apagar nome" remove. Se alguém perguntar como reusar uma pergunta sem digitar tudo de novo, explique esse formato.

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
                "enum": ["hoje", "ontem", "anteontem", "mes_atual", "mes_anterior", "dia_especifico"],
                "description": "Período. Padrão: mes_atual. Use 'ontem'/'anteontem' para os dias relativos (o servidor calcula a data — nunca calcule 'ontem' manualmente com dia_especifico). Use 'dia_especifico' junto com o parâmetro 'data' para qualquer outro dia do mês."
            },
            "data": {
                "type": "string",
                "description": "Data no formato AAAA-MM-DD. Só é usado quando periodo='dia_especifico' (ex: usuário pergunta 'margens do dia 15/07/2026')."
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

_EXCEL_TOOL = {
    "name": "exportar_planilha_excel",
    "description": (
        "Gera o link para baixar em Excel (.xlsx) o mesmo relatório que consultar_dados traria, "
        "aplicando os mesmos filtros (tipo, período, dia específico, grupos, threshold de margem). "
        "Use quando o usuário pedir para gerar, exportar, baixar ou salvar em Excel/planilha."
    ),
    "input_schema": _BI_TOOL["input_schema"],
}


def _gerar_link_excel(tipo: str, periodo: str = "mes_atual", data: str | None = None, top_n: int = 5,
                       grupos: list | None = None, threshold_margem_pct: float = 13.0,
                       cobertura_meses: int = 3) -> str:
    params = {
        "tipo": tipo, "periodo": periodo, "top_n": top_n,
        "threshold_margem_pct": threshold_margem_pct, "cobertura_meses": cobertura_meses,
    }
    if data:
        params["data"] = data
    if grupos:
        params["grupos"] = ",".join(grupos)
    caminho = "/relatorio/excel?" + urllib.parse.urlencode(params)
    if config.PUBLIC_BASE_URL:
        url = config.PUBLIC_BASE_URL + caminho
    else:
        # Sem PUBLIC_BASE_URL configurada, o link fica relativo e não abre no WhatsApp.
        log.warning("PUBLIC_BASE_URL não configurada — link de Excel será relativo e pode não funcionar no WhatsApp")
        url = caminho
    return json.dumps({"url_excel": url}, ensure_ascii=False)


def _executar_consulta(tipo: str, periodo: str = "mes_atual", data: str | None = None, top_n: int = 5,
                       grupos: list | None = None, threshold_margem_pct: float = 13.0,
                       cobertura_meses: int = 3) -> str:
    try:
        now = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%d/%m/%Y %H:%M")

        if tipo == "ranking_vendedores":
            return json.dumps({"data_hora": now, "periodo": periodo, "ranking_vendedores": get_ranking_vendedores(periodo, top_n, data=data)}, ensure_ascii=False, indent=2)
        if tipo == "ranking_clientes":
            return json.dumps({"data_hora": now, "periodo": periodo, "ranking_clientes": get_ranking_clientes(periodo, top_n, data=data)}, ensure_ascii=False, indent=2)
        if tipo == "ranking_produtos":
            return json.dumps({"data_hora": now, "periodo": periodo, "ranking_produtos": get_ranking_produtos(periodo, top_n, data=data)}, ensure_ascii=False, indent=2)
        if tipo == "menores_margens_cliente":
            return json.dumps({"data_hora": now, "periodo": periodo, "menores_margens_cliente": get_menores_margens_cliente(periodo, top_n, data=data)}, ensure_ascii=False, indent=2)
        if tipo == "menores_margens_produto":
            return json.dumps({"data_hora": now, "periodo": periodo, "menores_margens_produto": get_menores_margens_produto(periodo, top_n, data=data)}, ensure_ascii=False, indent=2)
        if tipo == "margens_abaixo_threshold":
            return json.dumps({"data_hora": now, "periodo": periodo, "threshold_pct": threshold_margem_pct, "resultado": get_margens_abaixo_threshold(threshold_margem_pct, periodo, data=data)}, ensure_ascii=False, indent=2)
        if tipo == "faturamento_diario":
            return json.dumps({"data_hora": now, **get_faturamento_diario()}, ensure_ascii=False, indent=2)
        if tipo == "vendas_canceladas":
            return json.dumps({"data_hora": now, "periodo": periodo, **get_vendas_canceladas(periodo, data=data)}, ensure_ascii=False, indent=2)
        if tipo == "analise_compras":
            return json.dumps({"data_hora": now, "cobertura_simulada_meses": cobertura_meses, "grupos_filtro": grupos, "produtos": get_analise_compras(grupos, cobertura_meses)}, ensure_ascii=False, indent=2)

        kpis = get_kpis(periodo, data=data)
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


# Comandos padrão: atalhos de texto que expandem para a frase completa, para não
# precisar digitá-la toda vez (ex.: um botão no app pode simplesmente enviar "margens5").
# Além destes fixos, qualquer usuário pode criar os seus próprios com /salvar — ver
# _tratar_comando_atalho abaixo e agent/atalhos_store.py.
_COMANDOS_PADRAO = {
    "margens5": "Faça o relatório das 5 menores % margens de produtos e clientes de hoje, coloque também faturamento e margem bruta",
}

_RE_SALVAR_ATALHO = re.compile(r"^/salvar\s+([^\s=:]+)\s*[:=]\s*(.+)$", re.IGNORECASE | re.DOTALL)
_RE_APAGAR_ATALHO = re.compile(r"^/apagar\s+(\S+)$", re.IGNORECASE)


def _expandir_comando_padrao(texto: str) -> str:
    chave = atalhos_store.nome_normalizado(texto)
    if not chave:
        return texto
    if chave in _COMANDOS_PADRAO:
        return _COMANDOS_PADRAO[chave]
    try:
        pergunta_salva = atalhos_store.carregar_atalhos().get(chave)
    except Exception as e:
        log.warning("Falha ao consultar atalhos salvos: %s", e)
        pergunta_salva = None
    return pergunta_salva or texto


def _tratar_comando_atalho(message: str) -> str | None:
    """
    Trata comandos de gestão de atalhos sem chamar o Claude:
      /salvar nome = pergunta completa   → salva
      /atalhos                           → lista os salvos
      /apagar nome                       → remove
    Retorna a resposta pronta, ou None se a mensagem não for um desses comandos
    (nesse caso o fluxo normal de chat_response continua).
    """
    texto = message.strip()
    baixo = texto.lower()

    if baixo in ("/atalhos", "/meusatalhos", "/comandos"):
        atalhos = {**_COMANDOS_PADRAO, **atalhos_store.carregar_atalhos()}
        if not atalhos:
            return "Você ainda não tem atalhos salvos. Para criar um, envie:\n/salvar nome = sua pergunta completa"
        linhas = [f"• */{nome}* → {pergunta}" for nome, pergunta in sorted(atalhos.items())]
        return (
            "📌 *Atalhos salvos:*\n" + "\n".join(linhas) +
            "\n\nPara usar, é só mandar /nome. Para criar outro: /salvar nome = pergunta. Para apagar: /apagar nome"
        )

    m = _RE_SALVAR_ATALHO.match(texto)
    if m:
        nome_bruto, pergunta = m.groups()
        try:
            nome = atalhos_store.salvar_atalho(nome_bruto, pergunta)
        except ValueError as e:
            return f"⚠️ {e}"
        except Exception as e:
            log.error("Erro ao salvar atalho: %s", e)
            return "⚠️ Não consegui salvar o atalho agora, tenta de novo daqui a pouco."
        return f"✅ Atalho */{nome}* salvo! É só mandar */{nome}* que eu já trago essa pergunta pra você."

    m = _RE_APAGAR_ATALHO.match(texto)
    if m:
        nome_bruto = m.group(1)
        nome = atalhos_store.nome_normalizado(nome_bruto)
        try:
            removido = atalhos_store.remover_atalho(nome_bruto)
        except Exception as e:
            log.error("Erro ao apagar atalho: %s", e)
            return "⚠️ Não consegui apagar o atalho agora, tenta de novo daqui a pouco."
        if removido:
            return f"🗑️ Atalho */{nome}* apagado."
        if nome in _COMANDOS_PADRAO:
            return f"*/{nome}* é um atalho padrão do sistema, não dá pra apagar."
        return f"Não encontrei nenhum atalho chamado */{nome}*."

    return None


def chat_response(sender: str, message: str) -> str:
    resposta_comando = _tratar_comando_atalho(message)
    if resposta_comando is not None:
        history = _histories.setdefault(sender, [])
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": resposta_comando})
        return resposta_comando

    message = _expandir_comando_padrao(message)

    history = _histories.setdefault(sender, [])
    history.append({"role": "user", "content": message})

    if len(history) > _MAX_TURNS * 2:
        history[:] = history[-(_MAX_TURNS * 2):]

    now = datetime.now(ZoneInfo(config.TIMEZONE))
    dias_semana = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
    contexto_data = (
        f"Contexto atual: hoje é {dias_semana[now.weekday()]}, {now.strftime('%d/%m/%Y')} "
        f"({now.strftime('%H:%M')}, fuso {config.TIMEZONE}). "
        "Use esse ano/mês quando o usuário citar um dia do mês sem especificar qual mês."
    )

    for _ in range(5):
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=[
                {"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": contexto_data},
            ],
            tools=[_BI_TOOL, _EXCEL_TOOL],
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
                funcao = _gerar_link_excel if tool_block.name == "exportar_planilha_excel" else _executar_consulta
                result = funcao(
                    tipo=args.get("tipo", "kpis_gerais"),
                    periodo=args.get("periodo", "mes_atual"),
                    data=args.get("data"),
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
