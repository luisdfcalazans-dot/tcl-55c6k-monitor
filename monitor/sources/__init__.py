"""Registro das fontes. Cada fonte tem nome, modo (cloud | pc) e um método coletar()."""

from __future__ import annotations

from typing import Callable

from ..models import Cupom, Oferta

Resultado = tuple[list[Oferta], list[Cupom]]


class Pular(Exception):
    """A fonte decidiu não coletar desta vez (ex.: esperando passar um bloqueio). Não conta como falha."""


class Fonte:
    nome = "base"
    modo = "cloud"
    alerta_falha = True  # False para fontes instáveis por natureza (não avisa "falhou 3 vezes")

    def coletar(self) -> Resultado:  # pragma: no cover
        raise NotImplementedError


def todas() -> list[Fonte]:
    from . import amazon, kabum, magalu, pelando, playwright_sources, promobit, telegram_public, telegram_user, vtex, zoom

    fontes: list[Fonte] = [
        promobit.PromobitBusca(), promobit.PromobitCategoriaTV(), promobit.PromobitCupons(),
        pelando.PelandoBusca(), pelando.PelandoCupons(),
        zoom.Zoom(),
        magalu.Magalu(),
        kabum.KaBuM(),
        vtex.Vtex("Fast Shop"), vtex.Vtex("Loja TCL"), vtex.Vtex("Webcontinental"),
        telegram_public.TelegramPublico(),
        # ---- só no PC ----
        amazon.Amazon(),
        playwright_sources.CasasBahia(),
        playwright_sources.MercadoLivre(),
        playwright_sources.AliExpress(),
        playwright_sources.Shopee(),
        telegram_user.TelegramUsuario(),
    ]
    return fontes


def por_modo(modo: str) -> list[Fonte]:
    if modo == "all":
        return todas()
    return [f for f in todas() if f.modo == modo]
