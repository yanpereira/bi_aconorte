"""
Calcula KPIs e rankings a partir dos arquivos Parquet no MinIO.
"""
import io
from datetime import datetime
from typing import Optional

import urllib3
import pandas as pd
from minio import Minio

import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_minio: Optional[Minio] = None


def _client() -> Minio:
    global _minio
    if _minio is None:
        _minio = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_SECURE,
            http_client=urllib3.PoolManager(cert_reqs="CERT_NONE"),
        )
    return _minio


def _read(name: str) -> pd.DataFrame:
    resp = _client().get_object(config.MINIO_BUCKET, name)
    df = pd.read_parquet(io.BytesIO(resp.read()))
    resp.close()
    return df


def _filtrar_periodo(df: pd.DataFrame, coluna: str, periodo: str) -> pd.DataFrame:
    now = datetime.now()
    df[coluna] = pd.to_datetime(df[coluna])
    if periodo == "hoje":
        return df[df[coluna].dt.date == now.date()]
    if periodo == "mes_anterior":
        m = now.month - 1 if now.month > 1 else 12
        y = now.year if now.month > 1 else now.year - 1
        return df[(df[coluna].dt.year == y) & (df[coluna].dt.month == m)]
    # mes_atual (padrão)
    return df[(df[coluna].dt.year == now.year) & (df[coluna].dt.month == now.month)]


def _resumo_vendas(df: pd.DataFrame) -> dict:
    vlr = float(df["vlr_venda_total"].sum())
    custo = float((df["qtd_venda"] * df["vlr_custo"]).sum())
    margem = vlr - custo
    qtd = int(df["cd_venda"].nunique())
    return {
        "vlr_vendas":       round(vlr, 2),
        "vlr_custo":        round(custo, 2),
        "vlr_margem_bruta": round(margem, 2),
        "pct_margem_bruta": round(margem / vlr, 4) if vlr else 0,
        "qtd_transacoes":   qtd,
        "vlr_ticket_medio": round(vlr / qtd, 2) if qtd else 0,
        "qtd_clientes":     int(df["cd_cliente"].nunique()),
        "qtd_vendedores":   int(df["cd_vendedor"].nunique()),
    }


def get_kpis(periodo: str = "mes_atual") -> dict:
    now = datetime.now()
    result: dict = {}

    # VENDAS
    try:
        vendas = _read("fat_vendas.parquet")
        cur_dia = _filtrar_periodo(vendas.copy(), "dt_venda", "hoje")
        cur_mes = _filtrar_periodo(vendas.copy(), "dt_venda", periodo)

        prev_m = now.month - 1 if now.month > 1 else 12
        prev_y = now.year if now.month > 1 else now.year - 1
        vendas["dt_venda"] = pd.to_datetime(vendas["dt_venda"])
        prev = vendas[(vendas["dt_venda"].dt.year == prev_y) & (vendas["dt_venda"].dt.month == prev_m)]

        result["vendas"] = {
            "hoje": _resumo_vendas(cur_dia),
            "mes":  {**_resumo_vendas(cur_mes), "vlr_fat_mes_anterior": round(float(prev["vlr_venda_total"].sum()), 2)},
        }
    except Exception as e:
        result["vendas"] = {"erro": str(e)}

    # ESTOQUE
    try:
        estoques = _read("fat_estoques.parquet")
        produtos = _read("dim_produtos.parquet")
        merged   = estoques.merge(
            produtos[["cd_produto", "preco_compra", "preco_venda"]],
            left_on="idProduto", right_on="cd_produto", how="left",
        )
        pos = merged[merged["estoque"] > 0]
        result["estoque"] = {
            "saldo_estoque_geral":       round(float(estoques["estoque"].sum()), 2),
            "vlr_estoque_compra":        round(float((pos["estoque"] * pos["preco_compra"]).sum()), 2),
            "vlr_estoque_venda":         round(float((pos["estoque"] * pos["preco_venda"]).sum()), 2),
            "qtd_prod_estoque_negativo": int((estoques["estoque"] < 0).sum()),
            "qtd_prod_estoque_zerado":   int((estoques["estoque"] == 0).sum()),
        }
    except Exception as e:
        result["estoque"] = {"erro": str(e)}

    # FINANCEIRO
    try:
        caixa = _read("caixa.parquet")
        mes    = _filtrar_periodo(caixa.copy(), "dtLancamento", periodo)
        mes    = mes[mes["status"] == "P"]
        caixa["dtLancamento"] = pd.to_datetime(caixa["dtLancamento"])
        aberto = caixa[caixa["status"] == "A"]
        vlr_cred = float(mes[mes["tipo"] == "C"]["valor"].sum())
        vlr_deb  = float(mes[mes["tipo"] == "D"]["valor"].sum())
        result["financeiro"] = {
            "vlr_credito":      round(vlr_cred, 2),
            "vlr_debito":       round(vlr_deb, 2),
            "vlr_saldo_caixa":  round(vlr_cred - vlr_deb, 2),
            "contas_a_receber": round(float(aberto[aberto["tipo"] == "C"]["valor"].sum()), 2),
            "contas_a_pagar":   round(float(aberto[aberto["tipo"] == "D"]["valor"].sum()), 2),
        }
    except Exception as e:
        result["financeiro"] = {"erro": str(e)}

    return result


def get_ranking_vendedores(periodo: str = "mes_atual", top_n: int = 5) -> list[dict]:
    vendas = _read("fat_vendas.parquet")
    df = _filtrar_periodo(vendas, "dt_venda", periodo)
    grupo = df.groupby("nm_vendedor").agg(
        faturamento=("vlr_venda_total", "sum"),
        transacoes=("cd_venda", "nunique"),
        clientes=("cd_cliente", "nunique"),
    ).reset_index().sort_values("faturamento", ascending=False).head(top_n)
    grupo["margem"] = df.groupby("nm_vendedor").apply(
        lambda x: float((x["vlr_venda_total"].sum() - (x["qtd_venda"] * x["vlr_custo"]).sum()) / x["vlr_venda_total"].sum())
        if x["vlr_venda_total"].sum() > 0 else 0
    ).reindex(grupo["nm_vendedor"]).values
    return [
        {
            "pos": i + 1,
            "vendedor": row["nm_vendedor"],
            "faturamento": round(float(row["faturamento"]), 2),
            "transacoes": int(row["transacoes"]),
            "clientes": int(row["clientes"]),
            "margem_pct": round(float(row["margem"]) * 100, 1),
        }
        for i, row in grupo.iterrows()
    ]


def get_ranking_clientes(periodo: str = "mes_atual", top_n: int = 10) -> list[dict]:
    vendas = _read("fat_vendas.parquet")
    df = _filtrar_periodo(vendas, "dt_venda", periodo)
    grupo = df.groupby(["cd_cliente", "nm_cliente"]).agg(
        faturamento=("vlr_venda_total", "sum"),
        transacoes=("cd_venda", "nunique"),
    ).reset_index().sort_values("faturamento", ascending=False).head(top_n)
    return [
        {
            "pos": i + 1,
            "cliente": row["nm_cliente"],
            "faturamento": round(float(row["faturamento"]), 2),
            "transacoes": int(row["transacoes"]),
        }
        for i, row in enumerate(grupo.to_dict("records"))
    ]


def get_ranking_produtos(periodo: str = "mes_atual", top_n: int = 10) -> list[dict]:
    vendas = _read("fat_vendas.parquet")
    df = _filtrar_periodo(vendas, "dt_venda", periodo)
    grupo = df.groupby(["cd_produto", "nm_produto"]).agg(
        faturamento=("vlr_venda_total", "sum"),
        quantidade=("qtd_venda", "sum"),
        custo_total=("vlr_custo", lambda x: float((x * df.loc[x.index, "qtd_venda"]).sum())),
    ).reset_index().sort_values("faturamento", ascending=False).head(top_n)
    resultado = []
    for i, row in enumerate(grupo.to_dict("records")):
        fat = float(row["faturamento"])
        custo = float(row["custo_total"])
        resultado.append({
            "pos": i + 1,
            "produto": row["nm_produto"],
            "faturamento": round(fat, 2),
            "quantidade": round(float(row["quantidade"]), 2),
            "margem_pct": round((fat - custo) / fat * 100, 1) if fat else 0,
        })
    return resultado
