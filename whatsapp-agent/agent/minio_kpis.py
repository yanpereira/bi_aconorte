"""
Calcula KPIs a partir dos arquivos Parquet no MinIO.
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


def get_kpis() -> dict:
    now = datetime.now()
    year, month = now.year, now.month
    result: dict = {}

    # VENDAS
    try:
        vendas = _read("fat_vendas.parquet")
        vendas["dt_venda"] = pd.to_datetime(vendas["dt_venda"])

        hoje = now.date()
        cur_dia = vendas[vendas["dt_venda"].dt.date == hoje]
        cur_mes = vendas[(vendas["dt_venda"].dt.year == year) & (vendas["dt_venda"].dt.month == month)]

        def _resumo(df: pd.DataFrame) -> dict:
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

        prev_m = month - 1 if month > 1 else 12
        prev_y = year if month > 1 else year - 1
        prev   = vendas[(vendas["dt_venda"].dt.year == prev_y) & (vendas["dt_venda"].dt.month == prev_m)]

        result["vendas"] = {
            "hoje": _resumo(cur_dia),
            "mes":  {**_resumo(cur_mes), "vlr_fat_mes_anterior": round(float(prev["vlr_venda_total"].sum()), 2)},
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
        caixa["dtLancamento"] = pd.to_datetime(caixa["dtLancamento"])

        mes    = caixa[(caixa["dtLancamento"].dt.year == year) & (caixa["dtLancamento"].dt.month == month) & (caixa["status"] == "P")]
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
