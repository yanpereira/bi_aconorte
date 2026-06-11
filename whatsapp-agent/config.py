import os
from dotenv import load_dotenv

load_dotenv()

# Azure AD
AZURE_TENANT_ID     = os.environ["AZURE_TENANT_ID"]
AZURE_CLIENT_ID     = os.environ["AZURE_CLIENT_ID"]
AZURE_CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]

# Power BI
POWERBI_WORKSPACE_ID = os.environ["POWERBI_WORKSPACE_ID"]
POWERBI_DATASET_ID   = os.environ["POWERBI_DATASET_ID"]

# Anthropic
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Evolution API
EVOLUTION_API_URL  = os.environ["EVOLUTION_API_URL"].rstrip("/")
EVOLUTION_API_KEY  = os.environ["EVOLUTION_API_KEY"]
EVOLUTION_INSTANCE = os.environ["EVOLUTION_INSTANCE"]

# Destinatários
WHATSAPP_RECIPIENTS = [r.strip() for r in os.environ["WHATSAPP_RECIPIENTS"].split(",")]

# Scheduler
REPORT_TIMES = [t.strip() for t in os.getenv("REPORT_TIMES", "08:00").split(",")]
TIMEZONE     = os.getenv("TIMEZONE", "America/Sao_Paulo")

# Webhook
WEBHOOK_PORT  = int(os.getenv("WEBHOOK_PORT", "8000"))
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
