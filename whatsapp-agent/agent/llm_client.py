"""
Usa a API da Anthropic (Claude) para transformar os KPIs do Power BI
em um relatório em linguagem natural, pronto para envio no WhatsApp.
"""
import json
from datetime import datetime
import anthropic
from config import ANTHROPIC_API_KEY

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_SYSTEM_PROMPT = """Você é o assistente de BI da Aço Norte, uma distribuidora de aços.
Sua função é transformar dados do Power BI em mensagens claras e objetivas para WhatsApp.

Regras obrigatórias:
- Escreva em português do Brasil
- Use emojis relevantes para facilitar a leitura visual no WhatsApp
- Seja direto: destaque os números mais importantes primeiro
- Sinalize claramente o que está BOM (✅), ATENÇÃO (⚠️) ou CRÍTICO (🚨)
- Para valores monetários use o formato R$ 1.234,56
- Para percentuais use o formato 12,34%
- Não use markdown (sem **, ##, ---) — WhatsApp não renderiza
- Separe seções com uma linha em branco
- Máximo de 60 caracteres por linha para não quebrar no celular
"""

_USER_TEMPLATE = """Data/hora: {timestamp}

Dados extraídos do Power BI — Aço Norte:

=== VENDAS (mês atual) ===
{vendas_json}

=== ESTOQUE ===
{estoque_json}

=== FINANCEIRO (mês atual) ===
{financeiro_json}

Gere um relatório completo com:
1. Saudação com a data
2. Bloco VENDAS com faturamento vs meta, margem e ticket médio
3. Bloco ESTOQUE com alertas de ruptura e produtos parados
4. Bloco FINANCEIRO com saldo, contas a pagar/receber
5. Frase de encerramento com o principal ponto de atenção do dia
"""


def _fmt_currency(v) -> str:
    if v is None:
        return "—"
    return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    return f"{float(v) * 100:.2f}%".replace(".", ",")


def _humanize_vendas(d: dict) -> str:
    return json.dumps({
        "Faturamento":          _fmt_currency(d.get("vlr_vendas")),
        "Meta do mês":          _fmt_currency(d.get("vlr_meta")),
        "Restante para meta":   _fmt_currency(d.get("vlr_restante_meta")),
        "Margem bruta":         _fmt_pct(d.get("pct_margem_bruta")),
        "Margem R$":            _fmt_currency(d.get("vlr_margem_bruta")),
        "Transações":           d.get("qtd_transacoes"),
        "Ticket médio":         _fmt_currency(d.get("vlr_ticket_medio")),
        "Clientes ativos":      d.get("qtd_clientes"),
        "Vendedores ativos":    d.get("qtd_vendedores"),
        "Faturamento mês ant.": _fmt_currency(d.get("vlr_fat_mes_anterior")),
        "Faturamento ano ant.": _fmt_currency(d.get("vlr_fat_ano_anterior")),
    }, ensure_ascii=False, indent=2)


def _humanize_estoque(d: dict) -> str:
    return json.dumps({
        "Saldo total (qtd)":        d.get("saldo_estoque_geral"),
        "Valor estoque (compra)":   _fmt_currency(d.get("vlr_estoque_compra")),
        "Valor estoque (venda)":    _fmt_currency(d.get("vlr_estoque_venda")),
        "Produtos c/ estoque neg.": d.get("qtd_prod_estoque_negativo"),
        "Produtos zerados":         d.get("qtd_prod_estoque_zerado"),
        "Sem venda 30-60 dias":     d.get("qtd_prod_sem_venda_30_60d"),
        "Sem venda 60-90 dias":     d.get("qtd_prod_sem_venda_60_90d"),
        "Sem venda +90 dias":       d.get("qtd_prod_sem_venda_mais_90d"),
        "Pedidos em aberto":        d.get("qtd_pedidos_comprados"),
        "Pedidos recebidos":        d.get("qtd_pedidos_recebidos"),
    }, ensure_ascii=False, indent=2)


def _humanize_financeiro(d: dict) -> str:
    return json.dumps({
        "Saldo caixa":       _fmt_currency(d.get("vlr_saldo_caixa")),
        "Entradas":          _fmt_currency(d.get("vlr_credito")),
        "Saídas":            _fmt_currency(d.get("vlr_debito")),
        "Contas a pagar":    _fmt_currency(d.get("contas_a_pagar")),
        "Contas a receber":  _fmt_currency(d.get("contas_a_receber")),
        "Compras no mês":    _fmt_currency(d.get("vlr_compras_mes")),
        "CMV":               _fmt_currency(d.get("cmv_compra")),
    }, ensure_ascii=False, indent=2)


def generate_report(kpis: dict) -> str:
    """Recebe os KPIs agrupados e retorna o texto do relatório para WhatsApp."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    user_message = _USER_TEMPLATE.format(
        timestamp=now,
        vendas_json=_humanize_vendas(kpis.get("vendas", {})),
        estoque_json=_humanize_estoque(kpis.get("estoque", {})),
        financeiro_json=_humanize_financeiro(kpis.get("financeiro", {})),
    )

    message = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text
