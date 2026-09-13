"""Pelando: página de busca renderizada no servidor e páginas de cupom por loja."""

from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .. import config
from ..filtro import eh_55c6k
from ..models import Cupom, Oferta
from ..util import get_html, loja_canonica, parse_preco, tempo_relativo_para_iso
from . import Fonte, Resultado


def parse_busca(html: str) -> list[Oferta]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Oferta] = {}
    for a in soup.select("h3 a[data-deal-id]"):
        did = a.get("data-deal-id")
        titulo = a.get_text(" ", strip=True)
        if not did or not eh_55c6k(titulo):
            continue
        card = a.find_parent("li") or a.find_parent("article") or a.parent.parent
        inativo = (a.get("data-inactive") == "true") or bool(card.select_one('[class*="inactive-label"]'))
        preco = None
        st = card.select_one('[class*="deal-card-stamp"]')
        if st:
            preco = parse_preco(st.get_text("", strip=True).replace("R$", "").strip())
        loja = "?"
        lj = card.select_one('[class*="deal-card-store"] a')
        if lj:
            loja = lj.get_text(" ", strip=True)
        ts = card.select_one('[class*="timestamp"]')
        publicado = tempo_relativo_para_iso(ts.get_text(" ", strip=True)) if ts else None
        temp = card.select_one('[class*="deal-card-temperature"] span')
        out[did] = Oferta(
            fonte="pelando", tipo="post", loja=loja_canonica(loja), titulo=titulo,
            url=a.get("href") or f"https://www.pelando.com.br/d/{did}", id=did,
            preco=preco, publicado=publicado, ativo=not inativo,
            extra={"temperatura": temp.get_text(strip=True) if temp else None},
        )
    return list(out.values())


class PelandoBusca(Fonte):
    nome = "pelando.busca"

    def coletar(self) -> Resultado:
        vistos: dict[str, Oferta] = {}
        for q in config.BUSCAS[:2]:
            html = get_html(f"https://www.pelando.com.br/busca/{quote(q)}")
            for o in parse_busca(html):
                vistos.setdefault(o.chave, o)
        return list(vistos.values()), []


def parse_cupons(html: str, loja_padrao: str, url: str) -> list[Cupom]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Cupom] = []
    for art in soup.select("article.card"):
        cta = art.select_one("a.card__cta[data-coupon-id], a[data-coupon-id]")
        cod_el = art.select_one(".card__cta-hidden-text")
        if not cta or not cod_el:
            continue
        cod = cod_el.get_text(strip=True)
        if not cod or len(cod) < 3:
            continue
        status = cta.get("data-status") or "active"
        if status != "active":
            continue
        titulo_el = art.select_one(".card__title")
        desc_el = art.select_one(".card__description")
        autor = art.select_one(".card__author")
        quando = None
        if autor:
            m = re.search(r"h[áa]\s+(.+)$", autor.get_text(" ", strip=True))
            quando = tempo_relativo_para_iso(m.group(1)) if m else None
        out.append(Cupom(
            fonte="pelando", loja=loja_canonica(cta.get("data-store-name") or loja_padrao), codigo=cod,
            titulo=titulo_el.get_text(" ", strip=True) if titulo_el else cod, url=url,
            id=cta.get("data-coupon-id") or cod, regra=desc_el.get_text(" ", strip=True) if desc_el else "",
            publicado=quando,
        ))
    return out


class PelandoCupons(Fonte):
    nome = "pelando.cupons"

    def coletar(self) -> Resultado:
        cupons: list[Cupom] = []
        for slug in config.PELANDO_CUPONS_LOJAS:
            url = f"https://www.pelando.com.br/cupons-de-descontos/{slug}"
            try:
                html = get_html(url)
            except Exception:
                continue
            cupons.extend(parse_cupons(html, slug, url))
        return [], cupons
