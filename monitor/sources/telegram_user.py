"""Grupos e canais privados do Telegram, lidos com a SUA conta (Telethon). Só no PC, opcional.

Precisa de TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION (gerado por scripts/telegram_login.py)
e TELEGRAM_CHATS_USUARIO="@canal1,https://t.me/+convite,-1001234567890" no .env do PC.
"""

from __future__ import annotations

from .. import config
from ..filtro import eh_55c6k
from ..models import Oferta
from ..util import cupom_no_texto, loja_canonica, parcelado_no_texto, precos_no_texto
from . import Fonte, Resultado
from .telegram_public import loja_no_texto


class TelegramUsuario(Fonte):
    nome = "telegram.usuario"
    modo = "pc"

    def coletar(self) -> Resultado:
        if not (config.TELEGRAM_API_ID and config.TELEGRAM_API_HASH and config.TELEGRAM_SESSION and config.TELEGRAM_CHATS_USUARIO):
            return [], []  # não configurado: silêncio
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession

        out: list[Oferta] = []
        with TelegramClient(StringSession(config.TELEGRAM_SESSION), int(config.TELEGRAM_API_ID), config.TELEGRAM_API_HASH) as cli:
            for chat in config.TELEGRAM_CHATS_USUARIO:
                alvo: object = chat
                if chat.lstrip("-").isdigit():
                    alvo = int(chat)
                try:
                    ent = cli.get_entity(alvo)
                    nome = getattr(ent, "username", None) or getattr(ent, "title", None) or str(chat)
                    for m in cli.iter_messages(ent, limit=60):
                        texto = m.message or ""
                        if not texto or not eh_55c6k(texto):
                            continue
                        precos = [p for p in precos_no_texto(texto) if p >= 1000]
                        titulo = next((l for l in texto.splitlines() if "c6k" in l.lower()), texto.splitlines()[0])
                        link = f"https://t.me/{nome}/{m.id}" if getattr(ent, "username", None) else f"tg://privatepost?channel={abs(ent.id)}&post={m.id}"
                        out.append(Oferta(
                            fonte="telegram", tipo="post", loja=loja_canonica(loja_no_texto(texto, [])),
                            titulo=f"[{nome}] {titulo[:140]}", url=link, id=f"{ent.id}/{m.id}",
                            preco=min(precos) if precos else None, parcelado=parcelado_no_texto(texto),
                            cupom=cupom_no_texto(texto), publicado=m.date.isoformat(timespec="seconds") if m.date else None,
                            extra={"canal": nome, "texto": texto[:600]},
                        ))
                except Exception as e:
                    print(f"[telegram.usuario] {chat}: {e}")
        return out, []
