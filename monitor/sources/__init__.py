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


# Fontes que só existem para as TVs (26/10/2026: com config.TVS_DESLIGADAS elas não rodam; a TV que aparecer numa fonte
# mista sai no run.py logo depois da coleta)
FONTES_SO_TV = ("promobit.tv", "zoom", "magalu", "kabum", "vtex.fastshop", "vtex.lojatcl", "vtex.webcontinental",
                "amazon", "casasbahia", "mercadolivre", "aliexpress", "shopee")


def todas() -> list[Fonte]:
    from .. import config
    from . import (amazon, carrefour, hype, kabum, magalu, mercadolivre_loja, netshoes, pelando, playwright_sources,
                   promobit, psstore, telegram_public, telegram_user, vtex, zoom)

    fontes: list[Fonte] = [
        promobit.PromobitBusca(), promobit.PromobitCategoriaTV(), promobit.PromobitCategoriaPS5(),
        promobit.PromobitCupons(),
        pelando.PelandoBusca(), pelando.PelandoCupons(),
        zoom.Zoom(),
        magalu.Magalu(), magalu.MagaluProdutos(),
        kabum.KaBuM(), kabum.KaBuMProdutos(),
        vtex.Vtex("Fast Shop"), vtex.Vtex("Loja TCL"), vtex.Vtex("Webcontinental"),
        # PS5/GTA 6 (03/10/2026) e as lojas novas: Mais Correios e Americanas pelo EAN do catálogo todo (TVs também)
        *[vtex.VtexEan(nome) for nome in config.LOJAS_VTEX_EAN],
        carrefour.Carrefour(),
        psstore.PlayStationStore(),
        mercadolivre_loja.MercadoLivreLojaPlayStation(),
        # gift card da PlayStation Store para pagar o GTA 6 digital (26/10/2026)
        hype.HypeGiftCard(),
        telegram_public.TelegramPublico(),
        # ---- só no PC ----
        amazon.Amazon(), amazon.AmazonProdutos(),
        playwright_sources.CasasBahia(), playwright_sources.CasasBahiaProdutos(),
        netshoes.Netshoes(),
        playwright_sources.MercadoLivre(), playwright_sources.MercadoLivreProdutos(),
        playwright_sources.AliExpress(),
        playwright_sources.Shopee(),
        telegram_user.TelegramUsuario(),
    ]
    if config.TVS_DESLIGADAS:  # lido na hora: os testes trocam a chave
        fontes = [f for f in fontes if f.nome not in FONTES_SO_TV]
    return fontes


def por_modo(modo: str) -> list[Fonte]:
    if modo == "all":
        return todas()
    return [f for f in todas() if f.modo == modo]
