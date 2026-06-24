"""
Lê dados de KPI do bucket MinIO.
Suporta múltiplos formatos: JSON único, arquivos por categoria, parquet via pandas.
"""
import json
import logging
from typing import Optional

from minio import Minio
from minio.error import S3Error

log = logging.getLogger(__name__)

_minio: Optional[Minio] = None


def _client() -> Minio:
    global _minio
    if _minio is None:
        import config
        _minio = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_SECURE,
        )
    return _minio


def _full(name: str) -> str:
    import config
    prefix = (config.MINIO_PREFIX or "").rstrip("/")
    return f"{prefix}/{name}" if prefix else name


def _read_json(object_name: str) -> dict:
    import config
    resp = _client().get_object(config.MINIO_BUCKET, object_name)
    try:
        return json.loads(resp.read().decode("utf-8"))
    finally:
        resp.close()
        resp.release_conn()


def _list_all() -> list[str]:
    import config
    prefix = config.MINIO_PREFIX or ""
    objs = _client().list_objects(config.MINIO_BUCKET, prefix=prefix, recursive=True)
    return sorted(o.object_name for o in objs)


def _try_json(name: str) -> Optional[dict]:
    try:
        return _read_json(_full(name))
    except S3Error:
        return None


def _latest_by_prefix(prefix: str) -> Optional[str]:
    """Retorna o nome do objeto mais recente com dado prefixo."""
    import config
    full_prefix = _full(prefix)
    objs = list(_client().list_objects(config.MINIO_BUCKET, prefix=full_prefix, recursive=True))
    if not objs:
        return None
    objs.sort(key=lambda o: o.last_modified, reverse=True)
    return objs[0].object_name


def get_kpis() -> dict:
    """
    Descobre e retorna o dicionário de KPIs do MinIO.

    Ordem de tentativas:
    1. kpis.json (arquivo único agregado)
    2. vendas.json + estoque.json + financeiro.json (separados)
    3. Arquivo mais recente com sufixo _kpis.json ou kpi*.json
    4. Primeiro JSON encontrado no bucket (fallback)
    """
    # 1 — arquivo único combinado
    for candidate in ("kpis.json", "kpis/latest.json", "latest.json"):
        data = _try_json(candidate)
        if data and any(k in data for k in ("vendas", "estoque", "financeiro")):
            log.info("KPIs lidos de '%s'", _full(candidate))
            return data

    # 2 — arquivos separados por categoria
    cats = {}
    for cat in ("vendas", "estoque", "financeiro"):
        for candidate in (f"{cat}.json", f"{cat}/latest.json", f"latest/{cat}.json"):
            data = _try_json(candidate)
            if isinstance(data, dict):
                cats[cat] = data
                log.info("KPI '%s' lido de '%s'", cat, _full(candidate))
                break

    if len(cats) == 3:
        return cats

    if cats:
        log.warning("Apenas %d categoria(s) encontrada(s): %s", len(cats), list(cats))
        return cats

    # 3 — arquivo mais recente com padrão kpi*/vendas*/estoque*/financeiro*
    for prefix in ("kpi", "vendas", "estoque", "financeiro"):
        latest = _latest_by_prefix(prefix)
        if latest and latest.endswith(".json"):
            data = _read_json(latest)
            if isinstance(data, dict):
                log.info("KPIs (prefixo '%s') lidos de '%s'", prefix, latest)
                # Se vier tudo num arquivo, retorna direto
                if any(k in data for k in ("vendas", "estoque", "financeiro")):
                    return data
                cats[prefix] = data

    if cats:
        return cats

    # 4 — fallback: primeiro JSON disponível
    all_objs = _list_all()
    log.info("Objetos encontrados no bucket: %s", all_objs)
    json_objs = [o for o in all_objs if o.endswith(".json")]
    if json_objs:
        log.warning("Usando JSON de fallback: %s", json_objs[0])
        return _read_json(json_objs[0])

    raise FileNotFoundError(
        f"Nenhum arquivo JSON de KPI encontrado no bucket. "
        f"Objetos disponíveis: {all_objs}"
    )


def save_kpis(kpis: dict, object_name: str = "kpis.json") -> None:
    """Salva o dicionário de KPIs no MinIO como JSON."""
    import config
    import io
    raw = json.dumps(kpis, ensure_ascii=False, indent=2).encode("utf-8")
    full_name = _full(object_name)
    _client().put_object(
        config.MINIO_BUCKET,
        full_name,
        io.BytesIO(raw),
        length=len(raw),
        content_type="application/json",
    )
    log.info("KPIs salvos em '%s/%s'", config.MINIO_BUCKET, full_name)
