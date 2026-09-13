"""Zoom/Buscapé: a página do produto traz JSON-LD com todas as ofertas (loja + preço)."""

from __future__ import annotations

import re

from .. import config
from ..models import Oferta
from ..util import get_html, jsonld_produtos, loja_canonica, parse_preco
from . import Fonte, Resultado

_RE_MEDIA = re.compile(r"m[ée]dia[^R$]{0,60}R\$\s?([\d.]+,\d{2})", re.I)


def parse_produto(html: str) -> list[Oferta]:
    out: list[Oferta] = []
    for prod in jsonld_produtos(html):
        offers = prod.get("offers")
        if isinstance(offers, dict):
            lista = offers.get("offers") or [offers]
        else:
            lista = offers or []
        for of in lista:
            if not isinstance(of, dict):
                continue
            preco = parse_preco(of.get("price") or of.get("lowPrice"))
            loja = of.get("offeredBy") or (of.get("seller") or {}).get("name") if isinstance(of.get("seller"), dict) else of.get("offeredBy")
            if not preco or not loja:
                continue
            oid = str(of.get("id") or of.get("@id") or f"{loja}-{preco}")
            out.append(Oferta(
                fonte="zoom", tipo="loja", loja=loja_canonica(str(loja)), titulo=of.get("name") or prod.get("name") or "",
                url=of.get("url") or config.URL_ZOOM, id=oid, preco=preco,
            ))
    m = _RE_MEDIA.search(html)
    if m and out:
        for o in out:
            o.extra["media_40_dias"] = parse_preco(m.group(1))
    return out


class Zoom(Fonte):
    nome = "zoom"

    def coletar(self) -> Resultado:
        html = get_html(config.URL_ZOOM)
        return parse_produto(html), []
