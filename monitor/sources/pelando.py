"""Pelando: página de busca renderizada no servidor e páginas de cupom por loja."""

from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .. import config, produtos
from ..models import Cupom, Oferta
from ..util import get_html, loja_canonica, parse_preco, tempo_relativo_para_iso
from . import Fonte, Resultado

# discussão (/t/...: "65c6k por R$3.999 em 15x sem juros é bom negócio?") usa o mesmo cartão das ofertas, mas não é
# oferta: viraria um "📣 postagem nova" com o preço de quem perguntou (levantamento de 26/09)
_RE_DISCUSSAO = re.compile(r"^(?:https?://[^/]+)?/t/", re.I)


def parse_busca(html: str) -> list[Oferta]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Oferta] = {}
    for a in soup.select("h3 a[data-deal-id]"):
        did = a.get("data-deal-id")
        titulo = a.get_text(" ", strip=True)
        if _RE_DISCUSSAO.match(a.get("href") or ""):
            continue
        if not did:
            continue
        card = a.find_parent("li") or a.find_parent("article") or a.parent.parent
        loja = "?"
        lj = card.select_one('[class*="deal-card-store"] a')
        if lj:
            loja = lj.get_text(" ", strip=True)
        # o produto do catálogo pelo título (TVs, PS5, GTA 6, gift card, leitor); a loja ajuda no GTA digital (PS Store)
        cl = produtos.classifica(titulo, loja)
        if not cl.produto:
            continue
        inativo = (a.get("data-inactive") == "true") or bool(card.select_one('[class*="inactive-label"]'))
        preco = None
        st = card.select_one('[class*="deal-card-stamp"]')
        if st:
            preco = parse_preco(st.get_text("", strip=True).replace("R$", "").strip())
        ts = card.select_one('[class*="timestamp"]')
        publicado = tempo_relativo_para_iso(ts.get_text(" ", strip=True)) if ts else None
        temp = card.select_one('[class*="deal-card-temperature"] span')
        extra = {"temperatura": temp.get_text(strip=True) if temp else None}
        if cl.detalhes:
            extra["produto"] = cl.detalhes
        out[did] = Oferta(
            fonte="pelando", tipo="post", loja=loja_canonica(loja), titulo=titulo,
            url=a.get("href") or f"https://www.pelando.com.br/d/{did}", id=did,
            preco=preco, publicado=publicado, ativo=not inativo, extra=extra, modelo=cl.produto,
        )
    return list(out.values())


class PelandoBusca(Fonte):
    nome = "pelando.busca"
    modo = "pc"  # o Pelando devolve 403 para IPs de datacenter (GitHub Actions); de casa funciona

    def coletar(self) -> Resultado:
        vistos: dict[str, Oferta] = {}
        # os termos do catálogo (monitor/produtos.py): as duas primeiras buscas de cada TV ("55c6k", "tcl 55c6k",
        # "65c6k", "tcl 65c6k") e as do PS5, do GTA 6 ("gta 6" não acha "Grand Theft Auto VI": vão os dois) e do gift card
        for q in produtos.termos("pelando"):
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
    modo = "pc"

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
