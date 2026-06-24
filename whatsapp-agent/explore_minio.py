"""
Script temporário para explorar o conteúdo do bucket MinIO.
Execute: python explore_minio.py
"""
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    from minio import Minio
    from minio.error import S3Error
except ImportError:
    print("ERRO: minio não instalado. Execute: pip install minio")
    sys.exit(1)

ENDPOINT   = os.environ["MINIO_ENDPOINT"]
ACCESS_KEY = os.environ["MINIO_ACCESS_KEY"]
SECRET_KEY = os.environ["MINIO_SECRET_KEY"]
SECURE     = os.getenv("MINIO_SECURE", "true").lower() == "true"
BUCKET     = os.environ["MINIO_BUCKET"]
PREFIX     = os.getenv("MINIO_PREFIX", "")

client = Minio(ENDPOINT, access_key=ACCESS_KEY, secret_key=SECRET_KEY, secure=SECURE)

print(f"\n=== Bucket: {BUCKET} | Endpoint: {ENDPOINT} ===\n")

objects = list(client.list_objects(BUCKET, prefix=PREFIX or "", recursive=True))
if not objects:
    print("Bucket vazio ou prefixo não encontrado.")
    sys.exit(0)

print(f"Total de objetos: {len(objects)}\n")
for obj in sorted(objects, key=lambda o: o.object_name):
    print(f"  {obj.object_name:60s}  {obj.size:>10,} bytes  {obj.last_modified}")

# Mostra conteúdo dos primeiros JSONs encontrados
print("\n=== Conteúdo dos JSONs ===\n")
json_files = [o.object_name for o in objects if o.object_name.endswith(".json")]
for name in json_files[:5]:
    print(f"--- {name} ---")
    try:
        resp = client.get_object(BUCKET, name)
        raw = resp.read()
        resp.close()
        data = json.loads(raw.decode("utf-8"))
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
    except Exception as e:
        print(f"  ERRO ao ler: {e}")
    print()
