"""
Autentica com Power BI via Service Principal (MSAL) e executa queries DAX
contra o dataset do modelo semântico da Aço Norte.

Fonte primária: MinIO (dados já transferidos pelo pipeline de BI).
Fallback: Power BI REST API (MSAL + DAX).
"""
import logging
import msal
import requests
from config import (
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET,
    POWERBI_WORKSPACE_ID, POWERBI_DATASET_ID, SAVE_MINIO_COPY,
)

log = logging.getLogger(__name__)

_AUTHORITY  = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
_SCOPE      = ["https://analysis.windows.net/powerbi/api/.default"]
_EXECUTE_URL = (
    f"https://api.powerbi.com/v1.0/myorg/groups/{POWERBI_WORKSPACE_ID}"
    f"/datasets/{POWERBI_DATASET_ID}/executeQueries"
)

_msal_app: msal.ConfidentialClientApplication | None = None


def _get_msal_app() -> msal.ConfidentialClientApplication:
    global _msal_app
    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            AZURE_CLIENT_ID,
            authority=_AUTHORITY,
            client_credential=AZURE_CLIENT_SECRET,
        )
    return _msal_app


def _get_token() -> str:
    app = _get_msal_app()
    result = app.acquire_token_silent(_SCOPE, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=_SCOPE)
    if "access_token" not in result:
        raise RuntimeError(f"Falha ao obter token Power BI: {result.get('error_description')}")
    return result["access_token"]


def execute_dax(dax: str) -> list[dict]:
    """Executa uma query DAX e retorna lista de linhas como dicts."""
    token = _get_token()
    payload = {"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}}
    resp = requests.post(
        _EXECUTE_URL,
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    rows = data["results"][0]["tables"][0].get("rows", [])
    # Remove o prefixo "Medidas[" dos nomes de coluna retornados pela API
    return [{k.split("[")[-1].rstrip("]"): v for k, v in row.items()} for row in rows]


# ── Queries por domínio ───────────────────────────────────────────────────────

_DAX_VENDAS_MES = """
DEFINE
    VAR _mes = FORMAT(TODAY(), "YYYYMM")
EVALUATE
    CALCULATETABLE(
        ROW(
            "vlr_vendas",           [vlr_vendas],
            "vlr_meta",             [vlr_meta],
            "vlr_restante_meta",    [vlr_restante_meta],
            "pct_margem_bruta",     [%_margem_bruta],
            "vlr_margem_bruta",     [vlr_margem_bruta],
            "qtd_transacoes",       [qtd_transacoes],
            "vlr_ticket_medio",     [vlr_ticket_medio],
            "qtd_clientes",         [qtd_clientes],
            "qtd_vendedores",       [qtd_vendedores],
            "vlr_fat_mes_anterior", [Faturamento Mês Anterior],
            "vlr_fat_ano_anterior", [Faturamento Ano Anterior]
        ),
        dim_calendario[Anomes] = _mes
    )
"""

_DAX_ESTOQUE = """
EVALUATE
    ROW(
        "saldo_estoque_geral",              [saldo_estoque_geral],
        "vlr_estoque_compra",               [vlr_estoque],
        "vlr_estoque_venda",                [vlr_estoque_vendas],
        "qtd_prod_estoque_negativo",        [qtd_produtos_estoque_negativo],
        "qtd_prod_estoque_zerado",          [qtd_produtos_estoque_zerado],
        "qtd_prod_sem_venda_30_60d",        [qtd_produtos_sem_venda_mais_30_dias],
        "qtd_prod_sem_venda_60_90d",        [qtd_produtos_sem_venda_mais_60_dias],
        "qtd_prod_sem_venda_mais_90d",      [qtd_produtos_sem_venda_mais_90_dias],
        "qtd_pedidos_comprados",            [qtd_pedidos_comprados],
        "qtd_pedidos_recebidos",            [qtd_pedidos_recebidos]
    )
"""

_DAX_FINANCEIRO = """
DEFINE
    VAR _mes = FORMAT(TODAY(), "YYYYMM")
EVALUATE
    CALCULATETABLE(
        ROW(
            "vlr_saldo_caixa",   [vlr_saldo_caixa],
            "vlr_credito",       [vlr_credito],
            "vlr_debito",        [vlr_debito],
            "contas_a_pagar",    [contas_a_pagar],
            "contas_a_receber",  [contas_a_receber],
            "vlr_compras_mes",   [vlr_compras_mes],
            "cmv_compra",        [cmv_compra]
        ),
        dim_calendario[Anomes] = _mes
    )
"""


def get_all_kpis() -> dict:
    """
    Retorna todos os KPIs agrupados por domínio.
    Fonte primária: MinIO.  Fallback: Power BI API.
    """
    # 1 — tenta MinIO primeiro (mais rápido, sem dependência Azure)
    try:
        from agent.minio_client import get_kpis
        kpis = get_kpis()
        log.info("KPIs obtidos do MinIO.")
        return kpis
    except Exception as exc:
        log.warning("MinIO indisponível (%s). Consultando Power BI API...", exc)

    # 2 — Power BI REST API
    vendas     = execute_dax(_DAX_VENDAS_MES)
    estoque    = execute_dax(_DAX_ESTOQUE)
    financeiro = execute_dax(_DAX_FINANCEIRO)
    kpis = {
        "vendas":     vendas[0]     if vendas     else {},
        "estoque":    estoque[0]    if estoque    else {},
        "financeiro": financeiro[0] if financeiro else {},
    }

    # Salva cópia no MinIO para próximas consultas
    if SAVE_MINIO_COPY:
        try:
            from agent.minio_client import save_kpis
            save_kpis(kpis)
        except Exception as exc:
            log.warning("Falha ao salvar cópia no MinIO: %s", exc)

    return kpis
