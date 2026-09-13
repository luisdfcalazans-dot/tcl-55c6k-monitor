"""Magazine Luiza via o espelho magazinevoce.com.br (mesmo catálogo, sem bloqueio Akamai).

Busca: lista todos os vendedores (Magalu 1P e marketplace) com preço Pix e parcelamento.
Produto do Magalu: traz cupons atrelados ao produto (seller.tags type=coupon).
"""

from __future__ import annotations

import re

from .. import config
from ..filtro import eh_55c6k
from ..models import Cupom, Oferta
from ..util import get_html, iso_normaliza, next_data, parse_preco
from . import Fonte, Resultado


def _url_magalu(path: str) -> str:
    # "/magazinecanaltechbr/slug/p/123/et/elit/" -> "https://www.magazineluiza.com.br/slug/p/123/et/elit/"
    p = re.sub(r"^/[^/]+/", "/", path or "")
    return "https://www.magazineluiza.com.br" + p


def _oferta(p: dict) -> Oferta | None:
    titulo = p.get("title") or ""
    if not eh_55c6k(titulo) or not p.get("available", True):
        return None
    price = p.get("price") or {}
    inst = p.get("installment") or {}
    seller = p.get("seller") or {}
    vendedor = seller.get("description") or seller.get("id") or "?"
    cartao = parse_preco(price.get("fullPrice"))
    pix = parse_preco(price.get("bestPrice"))
    parcelado = None
    if inst.get("quantity") and inst.get("amount"):
        sj = " sem juros" if str(inst.get("interest", "0")).startswith("0") else ""
        parcelado = f"{inst['quantity']}x R$ {str(inst['amount']).replace('.', ',')}{sj}"
    return Oferta(
        fonte="magalu", tipo="loja", loja="Magazine Luiza", titulo=titulo,
        url=_url_magalu(p.get("path") or p.get("url") or ""), id=f"{p.get('id')}-{seller.get('id') or vendedor}",
        preco=cartao, preco_pix=pix if pix and cartao and pix < cartao else (pix if not cartao else None),
        parcelado=parcelado, vendedor=vendedor,
        extra={"preco_de": parse_preco(price.get("price")), "1p": seller.get("category") == "1p"},
    )


def parse_busca(html: str) -> list[Oferta]:
    nd = next_data(html) or {}
    prods = (((nd.get("props") or {}).get("pageProps") or {}).get("data") or {}).get("search", {}).get("products") or []
    out = []
    for p in prods:
        o = _oferta(p)
        if o:
            out.append(o)
    return out


def parse_produto(html: str) -> tuple[Oferta | None, list[Cupom]]:
    nd = next_data(html) or {}
    p = (((nd.get("props") or {}).get("pageProps") or {}).get("data") or {}).get("product") or {}
    if not p:
        return None, []
    o = _oferta(p)
    cupons: list[Cupom] = []
    for tag in (p.get("seller") or {}).get("tags") or []:
        if tag.get("type") == "coupon" and tag.get("code"):
            cupons.append(Cupom(
                fonte="magalu", loja="Magazine Luiza", codigo=tag["code"], titulo=tag.get("message") or tag["code"],
                url=_url_magalu(p.get("path") or ""), id=f"{tag['code']}-{(tag.get('endDate') or '')[:10]}",
                regra=tag.get("message") or "", validade=iso_normaliza(tag.get("endDate")),
                publicado=iso_normaliza(tag.get("startDate")), especifico=True,
            ))
    if o and cupons:
        o.cupom = cupons[0].codigo
        desc = cupons[0]
        for c in cupons:
            if str(tag.get("discountType")) == "absolute" and o.melhor_preco:
                pass
        # preço estimado com cupom absoluto
        for tag in (p.get("seller") or {}).get("tags") or []:
            if tag.get("type") == "coupon" and tag.get("discountType") == "absolute" and tag.get("discountValue"):
                base = o.preco_pix or o.preco
                if base:
                    o.extra["preco_com_cupom"] = round(base - float(tag["discountValue"]), 2)
                    o.extra["cupom_regra"] = desc.regra
                break
    return o, cupons


class Magalu(Fonte):
    nome = "magalu"

    def coletar(self) -> Resultado:
        ofertas = parse_busca(get_html(config.URL_MAGALU_BUSCA))
        o1p, cupons = parse_produto(get_html(config.URL_MAGALU_PRODUTO))
        if o1p:
            # substitui a entrada da busca pelo produto (que tem cupom)
            ofertas = [o for o in ofertas if o.id != o1p.id] + [o1p]
        return ofertas, cupons
