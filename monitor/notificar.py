"""Envio de alertas pelo Bot API do Telegram. Sem token, imprime no console."""

from __future__ import annotations

import time

import requests

from . import config


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
                print(f"[notificar] falha {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            print(f"[notificar] erro de rede: {e}")
            ok = False
        time.sleep(1.1)
    return ok
