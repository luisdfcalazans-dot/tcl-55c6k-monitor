"""Gera a sessão do Telegram (Telethon) para ler grupos/canais privados com a SUA conta.

1. Crie um "app" em https://my.telegram.org/apps (pede login por SMS) e copie api_id e api_hash.
2. Rode:  python scripts/telegram_login.py
3. Informe telefone e o código que o Telegram enviar. O script imprime as linhas para colar no .env.

A sessão fica só no seu PC (.env está no .gitignore). Nunca a coloque no GitHub.
"""

from __future__ import annotations

import sys

try:
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient
except ImportError:
    sys.exit("instale antes: pip install telethon")


def main() -> None:
    api_id = input("api_id: ").strip()
    api_hash = input("api_hash: ").strip()
    with TelegramClient(StringSession(), int(api_id), api_hash) as cli:
        sessao = cli.session.save()
        eu = cli.get_me()
        print(f"\nLogado como {eu.first_name} (@{eu.username}).")
        print("\nSeus grupos e canais (use o @username ou o id na variável TELEGRAM_CHATS_USUARIO):")
        for d in cli.iter_dialogs(limit=80):
            if d.is_group or d.is_channel:
                ident = f"@{d.entity.username}" if getattr(d.entity, "username", None) else str(d.id)
                print(f"  {ident:<32} {d.name}")
        print("\nCole no arquivo .env:")
        print(f"TELEGRAM_API_ID={api_id}")
        print(f"TELEGRAM_API_HASH={api_hash}")
        print(f"TELEGRAM_SESSION={sessao}")
        print("TELEGRAM_CHATS_USUARIO=@canal1,-1001234567890")


if __name__ == "__main__":
    main()
