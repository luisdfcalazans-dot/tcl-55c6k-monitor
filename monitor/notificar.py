"""Envio de alertas pelo Bot API do Telegram. Sem token, imprime no console."""

from __future__ import annotations

import time

import requests

from . import config


def _sem_segredo(s: str) -> str:
    """Tira o token do bot de qualquer texto que vá para log."""
    import re

    token = config.TELEGRAM_BOT_TOKEN
    if token:
        s = s.replace(token, "<token>")
    return re.sub(r"bot\d{6,}:[A-Za-z0-9_-]{20,}", "bot<token>", s)


def enviar(texto: str, silencioso: bool = False) -> bool:
    token = config.TELEGRAM_BOT_TOKEN
    chats = [c.strip() for c in config.TELEGRAM_CHAT_ID.split(",") if c.strip()]
    if not token or not chats:
        print("[notificar] (sem TELEGRAM_BOT_TOKEN/CHAT_ID) ->\n" + texto + "\n")
        return False
    ok = True
    for chat in chats:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat,
                    "text": texto[:4000],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "disable_notification": silencioso,
                },
                timeout=20,
            )
            if r.status_code == 429:
                time.sleep(int(r.json().get("parameters", {}).get("retry_after", 3)) + 1)
                r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  json={"chat_id": chat, "text": texto[:4000], "parse_mode": "HTML",
                                        "disable_web_page_preview": True}, timeout=20)
            if r.status_code != 200:
                # tenta sem HTML (caso algum caractere tenha quebrado a marcação)
                r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  json={"chat_id": chat, "text": texto[:4000], "disable_web_page_preview": True},
                                  timeout=20)
            ok = ok and r.status_code == 200
            if r.status_code != 200:
                print(f"[notificar] falha {r.status_code}: {_sem_segredo(r.text[:200])}")
        except requests.RequestException as e:
            # a mensagem da exceção inclui a URL da API, que tem o token: nunca imprimir crua
            print(f"[notificar] erro de rede: {type(e).__name__}: {_sem_segredo(str(e))[:200]}")
            ok = False
        time.sleep(1.1)
    return ok
