"""
Atalhos de perguntas frequentes que os próprios usuários podem salvar pelo chat
(comandos /salvar, /atalhos, /apagar em chat_client.py), sem precisar editar código.

Persistidos como um único JSON no MinIO (mesmo bucket usado pelos dados de BI) para
sobreviver a reinícios e redeploys do serviço. Mantidos em cache no processo depois
da primeira leitura — salvar/apagar atualiza o cache e regrava o objeto no MinIO.
"""
import io
import json
import logging
import re
from typing import Optional

import urllib3
from minio import Minio
from minio.error import S3Error

import config

log = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_OBJECT_NAME = "atalhos_chat.json"

_minio: Optional[Minio] = None
_cache: Optional[dict[str, str]] = None


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


def nome_normalizado(nome: str) -> str:
    """Normaliza o nome do atalho: minúsculo, sem barra/espaços/acentuação, só [a-z0-9_]."""
    nome = nome.strip().lstrip("/").lower()
    nome = re.sub(r"\s+", "_", nome)
    nome = re.sub(r"[^a-z0-9_]", "", nome)
    return nome


def _ler_do_minio() -> dict[str, str]:
    try:
        resp = _client().get_object(config.MINIO_BUCKET, _OBJECT_NAME)
        try:
            return json.loads(resp.read().decode("utf-8"))
        finally:
            resp.close()
            resp.release_conn()
    except S3Error:
        return {}
    except Exception as e:
        log.warning("Falha ao carregar atalhos do MinIO (usando cache vazio): %s", e)
        return {}


def _gravar_no_minio(atalhos: dict[str, str]) -> None:
    raw = json.dumps(atalhos, ensure_ascii=False, indent=2).encode("utf-8")
    _client().put_object(
        config.MINIO_BUCKET, _OBJECT_NAME, io.BytesIO(raw),
        length=len(raw), content_type="application/json",
    )


def carregar_atalhos() -> dict[str, str]:
    """Retorna {nome: pergunta}. Lê do MinIO só na primeira chamada do processo."""
    global _cache
    if _cache is None:
        _cache = _ler_do_minio()
    return _cache


def salvar_atalho(nome: str, pergunta: str) -> str:
    """Salva/atualiza um atalho e persiste no MinIO. Retorna o nome normalizado."""
    nome_norm = nome_normalizado(nome)
    if not nome_norm:
        raise ValueError("Nome de atalho inválido — use letras, números ou _ (ex: margens5).")
    pergunta = pergunta.strip()
    if not pergunta:
        raise ValueError("A pergunta do atalho não pode ficar vazia.")
    atalhos = carregar_atalhos()
    atalhos[nome_norm] = pergunta
    _gravar_no_minio(atalhos)
    log.info("Atalho salvo: %s", nome_norm)
    return nome_norm


def remover_atalho(nome: str) -> bool:
    """Remove um atalho salvo. Retorna True se existia."""
    nome_norm = nome_normalizado(nome)
    atalhos = carregar_atalhos()
    if nome_norm in atalhos:
        del atalhos[nome_norm]
        _gravar_no_minio(atalhos)
        log.info("Atalho removido: %s", nome_norm)
        return True
    return False
