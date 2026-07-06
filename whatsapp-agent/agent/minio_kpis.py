"""
Calcula KPIs e relatórios a partir dos arquivos Parquet no MinIO.
"""
import io
from datetime import datetime, timedelta
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
    df = df.copy()
    df[coluna] = pd.to_datetime(df[coluna])
    if periodo == "hoje":
        return df[df[coluna].dt.date == now.date()]
    if periodo == "mes_anterior":
        m = now.month - 1 if now.month > 1 else 12
        y = now.year if now.month > 1 else now.year - 1
        return df[(df[coluna].dt.year == y) & (df[coluna].dt.month == m)]
    return df[(df[coluna].dt.year == now.year) & (df[coluna].dt.month == now.month)]


def _carregar_vendas_com_nomes() -> pd.DataFrame:
    """Retorna fat_vendas com nomes de produto, cliente e vendedor."""
    vendas = _read("fat_vendas.parquet")
    produtos = _read("dim_produtos.parquet")[["cd_produto", "ds_produto", "ds_grupo", "preco_compra", "preco_venda"]]
    pessoas = _read("dim_pessoas.parquet")[["cd_pessoa", "ds_pessoa"]]

    clientes = pessoas.rename(columns={"cd_pessoa": "cd_cliente", "ds_pessoa": "nm_cliente"})
    vendedores = pessoas.rename(columns={"cd_pessoa": "cd_vendedor", "ds_pessoa": "nm_vendedor"})

    vendas = vendas.merge(produtos, on="cd_produto", how="left")
    vendas = vendas.merge(clientes, on="cd_cliente", how="left")
    vendas = vendas.merge(vendedores, on="cd_vendedor", how="left")
    vendas["dt_venda"] = pd.to_datetime(vendas["dt_venda"])
    return vendas


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


# ─── KPIs GERAIS ────────────────────────────────────────────────────────────

def get_kpis(periodo: str = "mes_atual") -> dict:
    now = datetime.now()
    result: dict = {}

    try:
        vendas = _carregar_vendas_com_nomes()
        cur_dia = vendas[vendas["dt_venda"].dt.date == now.date()]
        cur_per = _filtrar_periodo(vendas, "dt_venda", periodo)

        prev_m = now.month - 1 if now.month > 1 else 12
        prev_y = now.year if now.month > 1 else now.year - 1
        prev = vendas[(vendas["dt_venda"].dt.year == prev_y) & (vendas["dt_venda"].dt.month == prev_m)]

        result["vendas"] = {
            "hoje": _resumo_vendas(cur_dia),
            "mes":  {**_resumo_vendas(cur_per), "vlr_fat_mes_anterior": round(float(prev["vlr_venda_total"].sum()), 2)},
        }
    except Exception as e:
        result["vendas"] = {"erro": str(e)}

    try:
        estoques = _read("fat_estoques.parquet")
        produtos = _read("dim_produtos.parquet")
        merged = estoques.merge(produtos[["cd_produto", "preco_compra", "preco_venda"]], left_on="idProduto", right_on="cd_produto", how="left")
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

    try:
        caixa = _read("caixa.parquet")
        mes = _filtrar_periodo(caixa, "dtLancamento", periodo)
        mes = mes[mes["status"] == "P"]
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


# ─── RANKINGS ───────────────────────────────────────────────────────────────

def _prep(df: pd.DataFrame) -> pd.DataFrame:
    """Pré-calcula custo total para evitar lambdas com referência externa."""
    df = df.copy()
    df["custo_total"] = df["qtd_venda"] * df["vlr_custo"]
    return df


def get_ranking_vendedores(periodo: str = "mes_atual", top_n: int = 5) -> list[dict]:
    df = _prep(_filtrar_periodo(_carregar_vendas_com_nomes(), "dt_venda", periodo))
    grupo = df.groupby("nm_vendedor").agg(
        faturamento=("vlr_venda_total", "sum"),
        custo=("custo_total", "sum"),
        transacoes=("cd_venda", "nunique"),
        clientes=("cd_cliente", "nunique"),
    ).reset_index().sort_values("faturamento", ascending=False).head(top_n)
    result = []
    for i, row in enumerate(grupo.to_dict("records")):
        fat, custo = float(row["faturamento"]), float(row["custo"])
        result.append({
            "posicao": i + 1,
            "vendedor": row["nm_vendedor"],
            "faturamento": round(fat, 2),
            "margem_pct": round((fat - custo) / fat * 100, 1) if fat else 0,
            "pedidos": int(row["transacoes"]),
            "clientes": int(row["clientes"]),
        })
    return result


def get_ranking_clientes(periodo: str = "mes_atual", top_n: int = 10) -> list[dict]:
    df = _prep(_filtrar_periodo(_carregar_vendas_com_nomes(), "dt_venda", periodo))
    grupo = df.groupby(["cd_cliente", "nm_cliente"]).agg(
        faturamento=("vlr_venda_total", "sum"),
        transacoes=("cd_venda", "nunique"),
    ).reset_index().sort_values("faturamento", ascending=False).head(top_n)
    return [
        {"posicao": i + 1, "cliente": r["nm_cliente"], "faturamento": round(float(r["faturamento"]), 2), "pedidos": int(r["transacoes"])}
        for i, r in enumerate(grupo.to_dict("records"))
    ]


def get_ranking_produtos(periodo: str = "mes_atual", top_n: int = 10) -> list[dict]:
    df = _prep(_filtrar_periodo(_carregar_vendas_com_nomes(), "dt_venda", periodo))
    grupo = df.groupby(["cd_produto", "ds_produto", "ds_grupo"]).agg(
        faturamento=("vlr_venda_total", "sum"),
        quantidade=("qtd_venda", "sum"),
        custo=("custo_total", "sum"),
    ).reset_index().sort_values("faturamento", ascending=False).head(top_n)
    result = []
    for i, row in enumerate(grupo.to_dict("records")):
        fat, custo = float(row["faturamento"]), float(row["custo"])
        result.append({
            "posicao": i + 1,
            "produto": row["ds_produto"],
            "grupo": row["ds_grupo"],
            "faturamento": round(fat, 2),
            "quantidade": round(float(row["quantidade"]), 2),
            "margem_pct": round((fat - custo) / fat * 100, 1) if fat else 0,
        })
    return result


# ─── MARGENS ────────────────────────────────────────────────────────────────

def get_menores_margens_cliente(periodo: str = "mes_atual", top_n: int = 5) -> list[dict]:
    df = _prep(_filtrar_periodo(_carregar_vendas_com_nomes(), "dt_venda", periodo))
    grupo = df.groupby(["cd_cliente", "nm_cliente"]).agg(
        faturamento=("vlr_venda_total", "sum"), custo=("custo_total", "sum"),
    ).reset_index()
    grupo["margem_pct"] = (grupo["faturamento"] - grupo["custo"]) / grupo["faturamento"] * 100
    grupo = grupo[grupo["faturamento"] > 0].sort_values("margem_pct").head(top_n)
    return [
        {"posicao": i + 1, "cliente": r["nm_cliente"], "faturamento": round(float(r["faturamento"]), 2), "margem_pct": round(float(r["margem_pct"]), 1)}
        for i, r in enumerate(grupo.to_dict("records"))
    ]


def get_menores_margens_produto(periodo: str = "mes_atual", top_n: int = 5) -> list[dict]:
    df = _prep(_filtrar_periodo(_carregar_vendas_com_nomes(), "dt_venda", periodo))
    grupo = df.groupby(["cd_produto", "ds_produto"]).agg(
        faturamento=("vlr_venda_total", "sum"), custo=("custo_total", "sum"),
    ).reset_index()
    grupo["margem_pct"] = (grupo["faturamento"] - grupo["custo"]) / grupo["faturamento"] * 100
    grupo = grupo[grupo["faturamento"] > 0].sort_values("margem_pct").head(top_n)
    return [
        {"posicao": i + 1, "produto": r["ds_produto"], "faturamento": round(float(r["faturamento"]), 2), "margem_pct": round(float(r["margem_pct"]), 1)}
        for i, r in enumerate(grupo.to_dict("records"))
    ]


def get_margens_abaixo_threshold(threshold_pct: float = 13.0, periodo: str = "mes_atual") -> list[dict]:
    df = _prep(_filtrar_periodo(_carregar_vendas_com_nomes(), "dt_venda", periodo))
    grupo = df.groupby(["cd_cliente", "nm_cliente", "cd_vendedor", "nm_vendedor"]).agg(
        faturamento=("vlr_venda_total", "sum"), custo=("custo_total", "sum"),
    ).reset_index()
    grupo["margem_pct"] = (grupo["faturamento"] - grupo["custo"]) / grupo["faturamento"] * 100
    abaixo = grupo[(grupo["faturamento"] > 0) & (grupo["margem_pct"] < threshold_pct)].sort_values("margem_pct")
    return [
        {"cliente": r["nm_cliente"], "vendedor": r["nm_vendedor"], "faturamento": round(float(r["faturamento"]), 2), "margem_pct": round(float(r["margem_pct"]), 1)}
        for r in abaixo.to_dict("records")
    ]


# ─── FATURAMENTO DIÁRIO ─────────────────────────────────────────────────────

def get_faturamento_diario() -> dict:
    vendas = _read("fat_vendas.parquet")
    vendas["dt_venda"] = pd.to_datetime(vendas["dt_venda"])
    now = datetime.now()
    mes = vendas[(vendas["dt_venda"].dt.year == now.year) & (vendas["dt_venda"].dt.month == now.month)]
    por_dia = mes.groupby(mes["dt_venda"].dt.date).agg(
        faturamento=("vlr_venda_total", "sum"),
        pedidos=("cd_venda", "nunique"),
    ).reset_index().sort_values("dt_venda")
    dias_com_venda = len(por_dia)
    total = float(por_dia["faturamento"].sum())
    media_dia = total / dias_com_venda if dias_com_venda else 0
    return {
        "por_dia": [
            {"data": str(r["dt_venda"]), "faturamento": round(float(r["faturamento"]), 2), "pedidos": int(r["pedidos"])}
            for r in por_dia.to_dict("records")
        ],
        "total_mes": round(total, 2),
        "media_diaria": round(media_dia, 2),
        "dias_com_venda": dias_com_venda,
    }


# ─── VENDAS CANCELADAS ──────────────────────────────────────────────────────

def get_vendas_canceladas(periodo: str = "mes_atual") -> dict:
    canceladas = _read("fat_vendas_canceladas.parquet")
    produtos = _read("dim_produtos.parquet")[["cd_produto", "ds_produto", "ds_grupo"]]
    pessoas = _read("dim_pessoas.parquet")[["cd_pessoa", "ds_pessoa"]]
    clientes = pessoas.rename(columns={"cd_pessoa": "cd_cliente", "ds_pessoa": "nm_cliente"})
    vendedores = pessoas.rename(columns={"cd_pessoa": "cd_vendedor", "ds_pessoa": "nm_vendedor"})
    canceladas = canceladas.merge(produtos, on="cd_produto", how="left")
    canceladas = canceladas.merge(clientes, on="cd_cliente", how="left")
    canceladas = canceladas.merge(vendedores, on="cd_vendedor", how="left")

    df = _filtrar_periodo(canceladas, "dt_venda", periodo)
    total_vlr = float(df["vlr_venda_total"].sum())
    qtd_pedidos = int(df["cd_venda"].nunique())

    por_vendedor = df.groupby("nm_vendedor").agg(
        valor=("vlr_venda_total", "sum"), pedidos=("cd_venda", "nunique")
    ).reset_index().sort_values("valor", ascending=False).head(10)

    return {
        "total_cancelado": round(total_vlr, 2),
        "qtd_pedidos_cancelados": qtd_pedidos,
        "por_vendedor": [
            {"vendedor": r["nm_vendedor"], "valor_cancelado": round(float(r["valor"]), 2), "pedidos": int(r["pedidos"])}
            for r in por_vendedor.to_dict("records")
        ],
    }


# ─── ANÁLISE DE COMPRAS ─────────────────────────────────────────────────────

def get_analise_compras(grupos: list[str] | None = None, cobertura_meses: int = 3) -> list[dict]:
    """Produtos ativos com venda média (90 dias) e simulação de cobertura."""
    now = datetime.now()
    dias_90 = now - timedelta(days=90)

    vendas = _read("fat_vendas.parquet")
    vendas["dt_venda"] = pd.to_datetime(vendas["dt_venda"])
    vendas_90 = vendas[vendas["dt_venda"] >= dias_90]

    estoques = _read("fat_estoques.parquet")
    produtos = _read("dim_produtos.parquet")

    if grupos:
        grupos_upper = [g.upper() for g in grupos]
        produtos = produtos[produtos["ds_grupo"].str.upper().isin(grupos_upper)]

    # Venda média mensal por produto (90 dias / 3 meses)
    venda_media = vendas_90.groupby("cd_produto")["qtd_venda"].sum() / 3

    # Estoque atual
    estoque_atual = estoques.groupby("idProduto")["estoque"].sum()

    merged = produtos[produtos["status"] == "S"][["cd_produto", "ds_produto", "ds_grupo", "preco_compra"]].copy()
    merged["venda_media_mensal"] = merged["cd_produto"].map(venda_media).fillna(0)
    merged["estoque_atual"] = merged["cd_produto"].map(estoque_atual).fillna(0)
    merged["cobertura_meses"] = merged.apply(
        lambda r: round(r["estoque_atual"] / r["venda_media_mensal"], 1) if r["venda_media_mensal"] > 0 else 999, axis=1
    )
    merged["qtd_comprar"] = merged.apply(
        lambda r: max(0, round((cobertura_meses * r["venda_media_mensal"]) - r["estoque_atual"], 2))
        if r["venda_media_mensal"] > 0 else 0, axis=1
    )
    merged["vlr_compra_estimado"] = (merged["qtd_comprar"] * merged["preco_compra"]).round(2)

    # Só mostra quem precisa comprar ou tem cobertura baixa
    precisa = merged[(merged["qtd_comprar"] > 0) | (merged["cobertura_meses"] < cobertura_meses)]
    precisa = precisa.sort_values("cobertura_meses").head(30)

    return [
        {
            "produto": r["ds_produto"],
            "grupo": r["ds_grupo"],
            "estoque_atual": round(float(r["estoque_atual"]), 2),
            "venda_media_mensal": round(float(r["venda_media_mensal"]), 2),
            "cobertura_atual_meses": float(r["cobertura_meses"]),
            "qtd_sugerida_compra": float(r["qtd_comprar"]),
            "valor_estimado_compra": round(float(r["vlr_compra_estimado"]), 2),
        }
        for r in precisa.to_dict("records")
    ]
