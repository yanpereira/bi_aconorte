"""
Teste interativo do chat conversacional — roda no terminal.
Uso: python test_chat.py
Digite 'sair' para encerrar.
"""
import sys
import os

# Garante que o diretório atual está no path para os imports relativos
sys.path.insert(0, os.path.dirname(__file__))

from agent.chat_client import chat_response

SENDER = "test_local"

print("=" * 50)
print("  Agente BI Aço Norte — Teste de Chat")
print("  (MinIO só funciona dentro do EasyPanel)")
print("  Digite 'sair' para encerrar.")
print("=" * 50)
print()

while True:
    try:
        msg = input("Você: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nEncerrando.")
        break

    if not msg:
        continue
    if msg.lower() in ("sair", "exit", "quit"):
        print("Até mais!")
        break

    print("Agente: ...", end="\r")
    resposta = chat_response(SENDER, msg)
    print(f"Agente: {resposta}")
    print()
