import os
from dotenv import load_dotenv

load_dotenv()

# Azure AD (opcional — usado apenas se Power BI estiver ativo)
AZURE_TENANT_ID     = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID     = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")

# Power BI (opcional)
POWERBI_WORKSPACE_ID = os.getenv("POWERBI_WORKSPACE_ID", "")
POWERBI_DATASET_ID   = os.getenv("POWERBI_DATASET_ID", "")

# Anthropic
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Evolution API (opcional — usado apenas pelo webhook do WhatsApp)
EVOLUTION_API_URL  = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY  = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")

# Destinatários (opcional)
WHATSAPP_RECIPIENTS = [r.strip() for r in os.getenv("WHATSAPP_RECIPIENTS", "").split(",") if r.strip()]

# Scheduler
REPORT_TIMES = [t.strip() for t in os.getenv("REPORT_TIMES", "08:00").split(",")]
TIMEZONE     = os.getenv("TIMEZONE", "America/Sao_Paulo")

# Webhook
WEBHOOK_PORT  = int(os.getenv("WEBHOOK_PORT", "8000"))
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")

# MinIO
SAVE_MINIO_COPY  = os.getenv("SAVE_MINIO_COPY", "false").lower() == "true"
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_SECURE     = os.getenv("MINIO_SECURE", "true").lower() == "true"
MINIO_BUCKET     = os.getenv("MINIO_BUCKET", "aconorte")
MINIO_PREFIX     = os.getenv("MINIO_PREFIX", "")
