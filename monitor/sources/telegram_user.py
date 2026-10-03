"""Grupos e canais privados do Telegram, lidos com a SUA conta (Telethon). Só no PC, opcional.

Precisa de TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION (gerado por scripts/telegram_login.py)
e TELEGRAM_CHATS_USUARIO="@canal1,https://t.me/+convite,-1001234567890" no .env do PC.
"""

from __future__ import annotations

from .. import config, produtos
from ..models import MODELO_PADRAO, Oferta
from ..util import cupom_no_texto, loja_canonica, parcelado_no_texto, preco_postagem
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
                        if not texto:
                            continue
                        loja = loja_canonica(loja_no_texto(texto, []))
                        # um bloco por produto do catálogo (as TVs, o PS5, o GTA 6...), como nos canais públicos
                        for produto, (titulo, trecho, preambulo, detalhes) in produtos.extrai_produtos(texto, loja).items():
                            link = f"https://t.me/{nome}/{m.id}" if getattr(ent, "username", None) else f"tg://privatepost?channel={abs(ent.id)}&post={m.id}"
                            mid = f"{ent.id}/{m.id}"
                            extra = {"canal": nome, "texto": texto[:600]}
                            if detalhes:
                                extra["produto"] = detalhes
                            out.append(Oferta(
                                fonte="telegram", tipo="post", loja=loja,
                                titulo=f"[{nome}] {titulo[:140]}", url=link,
                                id=mid if produto == MODELO_PADRAO else f"{mid}#{produto}",
                                preco=preco_postagem(trecho, produtos.piso(produto)), parcelado=parcelado_no_texto(trecho),
                                cupom=cupom_no_texto(trecho) or cupom_no_texto(preambulo),
                                publicado=m.date.isoformat(timespec="seconds") if m.date else None,
                                extra=extra, modelo=produto,
                            ))
                except Exception as e:
                    print(f"[telegram.usuario] {chat}: {e}")
        return out, []
