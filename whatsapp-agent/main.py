"""
Agente BI → WhatsApp — Aço Norte

Fluxo:
  1. Busca KPIs do Power BI via REST API (DAX queries)
  2. Envia para o Claude (Anthropic) gerar o relatório em linguagem natural
  3. Distribui o relatório via Evolution API (WhatsApp)

Execução agendada via APScheduler conforme REPORT_TIMES no .env.
Também pode ser disparado manualmente: python main.py --now
"""
import argparse
import logging
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from agent.powerbi_client import get_all_kpis
from agent.llm_client import generate_report
from agent.whatsapp_client import broadcast, check_instance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def run_report() -> None:
    log.info("Iniciando ciclo de relatório — %s", datetime.now().strftime("%d/%m/%Y %H:%M"))

    if not check_instance():
        log.error("Evolution API não conectada. Verifique a instância '%s'.", config.EVOLUTION_INSTANCE)
        return

    log.info("Buscando KPIs do Power BI...")
    try:
        kpis = get_all_kpis()
    except Exception as exc:
        log.error("Erro ao buscar KPIs: %s", exc)
        return

    log.info("Gerando relatório com Claude...")
    try:
        report = generate_report(kpis)
    except Exception as exc:
        log.error("Erro ao gerar relatório: %s", exc)
        return

    log.info("Enviando para %d destinatário(s)...", len(config.WHATSAPP_RECIPIENTS))
    results = broadcast(config.WHATSAPP_RECIPIENTS, report)
    for r in results:
        if r["status"] == "ok":
            log.info("  ✓ Enviado para %s", r["recipient"])
        else:
            log.warning("  ✗ Falha para %s: %s", r["recipient"], r["error"])


def _parse_cron(time_str: str) -> tuple[str, str]:
    """Converte 'HH:MM' em (hora, minuto) para o CronTrigger."""
    hour, minute = time_str.split(":")
    return hour, minute


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente BI WhatsApp — Aço Norte")
    parser.add_argument(
        "--now", action="store_true",
        help="Executa o relatório imediatamente e encerra"
    )
    args = parser.parse_args()

    if args.now:
        run_report()
        return

    scheduler = BlockingScheduler(timezone=config.TIMEZONE)

    for time_str in config.REPORT_TIMES:
        hour, minute = _parse_cron(time_str)
        scheduler.add_job(
            run_report,
            CronTrigger(hour=hour, minute=minute, timezone=config.TIMEZONE),
            id=f"report_{time_str}",
            name=f"Relatório {time_str}",
            max_instances=1,
        )
        log.info("Relatório agendado para %s (TZ: %s)", time_str, config.TIMEZONE)

    log.info("Scheduler iniciado. Aguardando próximo horário...")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Encerrado pelo usuário.")
        sys.exit(0)


if __name__ == "__main__":
    main()
