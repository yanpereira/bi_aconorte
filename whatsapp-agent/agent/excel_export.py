"""
Gera arquivos Excel (.xlsx) a partir dos mesmos relatórios usados no chat,
aplicando os mesmos filtros (período, dia específico, grupos, threshold de margem).
"""
import io

import pandas as pd

from agent.minio_kpis import (
    get_kpis, get_ranking_vendedores, get_ranking_clientes, get_ranking_produtos,
    get_menores_margens_cliente, get_menores_margens_produto, get_margens_abaixo_threshold,
    get_faturamento_diario, get_vendas_canceladas, get_analise_compras,
)

_TIPOS_LISTA = {
    "ranking_vendedores": lambda periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses:
        get_ranking_vendedores(periodo, top_n, data=data),
    "ranking_clientes": lambda periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses:
        get_ranking_clientes(periodo, top_n, data=data),
    "ranking_produtos": lambda periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses:
        get_ranking_produtos(periodo, top_n, data=data),
    "menores_margens_cliente": lambda periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses:
        get_menores_margens_cliente(periodo, top_n, data=data),
    "menores_margens_produto": lambda periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses:
        get_menores_margens_produto(periodo, top_n, data=data),
    "margens_abaixo_threshold": lambda periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses:
        get_margens_abaixo_threshold(threshold_margem_pct, periodo, data=data),
    "faturamento_diario": lambda periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses:
        get_faturamento_diario()["por_dia"],
    "vendas_canceladas": lambda periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses:
        get_vendas_canceladas(periodo, data=data)["por_vendedor"],
    "analise_compras": lambda periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses:
        get_analise_compras(grupos, cobertura_meses),
}


def _kpis_para_linhas(kpis: dict) -> list[dict]:
    """Achata o dict aninhado de get_kpis em linhas (seção | indicador | valor) para a planilha."""
    linhas = []
    for secao, valor in kpis.items():
        if secao == "vendas" and isinstance(valor, dict):
            for sub_periodo, dados in valor.items():
                if isinstance(dados, dict):
                    for chave, v in dados.items():
                        linhas.append({"secao": f"vendas_{sub_periodo}", "indicador": chave, "valor": v})
        elif isinstance(valor, dict):
            for chave, v in valor.items():
                linhas.append({"secao": secao, "indicador": chave, "valor": v})
    return linhas


def gerar_excel(tipo: str, periodo: str = "mes_atual", data: str | None = None, top_n: int = 5,
                 grupos: list[str] | None = None, threshold_margem_pct: float = 13.0,
                 cobertura_meses: int = 3) -> bytes:
    """Executa a mesma consulta usada no chat (consultar_dados) e devolve os bytes de um .xlsx."""
    montar_linhas = _TIPOS_LISTA.get(tipo)
    if montar_linhas:
        linhas = montar_linhas(periodo, data, top_n, grupos, threshold_margem_pct, cobertura_meses)
    else:
        linhas = _kpis_para_linhas(get_kpis(periodo, data=data))

    df = pd.DataFrame(linhas) if linhas else pd.DataFrame([{"aviso": "Nenhum dado encontrado para os filtros informados"}])

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=tipo[:31])
    buffer.seek(0)
    return buffer.getvalue()
