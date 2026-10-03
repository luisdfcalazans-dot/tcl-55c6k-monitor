"""Mercado Livre: a vitrine da loja oficial PlayStation (official_store_id 1473, vendedor 1047493289), por HTTP.

Um pedido por rodada (config.URL_ML_LOJA_PLAYSTATION). A vitrine traz ~15 cartões (poly-card) com título, link do
catálogo com o item da loja (pdp_filters=item_id:MLB...), o preço "Agora" (o do Pix quando o cartão diz "X% OFF no
Pix") e o "ou R$ Y em Nx R$ Z sem juros". A lista com filtro de loja e a API do ML dão antirrobô/403 (pesquisa de 03/10):
não são usadas. Página de verificação ("account-verification", "suspicious-traffic") é falha, sem aviso no Telegram
(o PS5 do ML também chega pelo Chrome do PC e pelas postagens).
Só os produtos do catálogo que não são TV (o classificador recusa controle, jogo, VR2, Portal...).
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from .. import config, produtos
from ..models import Oferta
from ..util import get_html, parse_preco
from . import Fonte, Resultado

_RE_ITEM = re.compile(r"item_id(?:%3A|:)(MLB\d+)", re.I)
_RE_CATALOGO = re.compile(r"/p/(MLB\d+)")
_RE_AGORA = re.compile(r"Agora:\s*(\d+)\s*reais(?:\s*com\s*(\d{1,2})\s*centavos)?", re.I)
_NUM = r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)"
_RE_OU = re.compile(r"ou\s+R\$\s?" + _NUM + r"\s+em\s+(\d{1,2})x\s+R\$\s?" + _NUM + r"\s+sem juros", re.I)
_RE_SO_PARCELA = re.compile(r"(?<!em )\b(\d{1,2})x\s+R\$\s?" + _NUM + r"\s+sem juros", re.I)
VENDEDOR = "Loja oficial PlayStation"


def _limpo(texto: str) -> str:
    """Texto do cartão com os centavos colados ("R$ 459 , 99" -> "R$ 459,99")."""
    t = re.sub(r"(\d)\s*,\s*(\d{2})\b", r"\1,\2", texto or "")
    return re.sub(r"\s+", " ", t)


def _valor_agora(card) -> Optional[float]:
    for el in card.select("[aria-label]"):
        m = _RE_AGORA.search(el.get("aria-label") or "")
        if m:
            return float(m.group(1)) + (int(m.group(2)) / 100 if m.group(2) else 0)
    return None


def bloqueada(html: str) -> bool:
    cab = (html or "")[:30000]
    return "account-verification" in cab or "suspicious-traffic" in cab or "/gz/account" in cab


def parse_loja(html: str) -> list[Oferta]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Oferta] = {}
    for card in soup.select("div.poly-card"):
        t = card.select_one("a.poly-component__title, h3 a, h2 a")
        if not t:
            continue
        titulo = t.get_text(" ", strip=True)
        href = t.get("href") or ""
        mi, mc = _RE_ITEM.search(href), _RE_CATALOGO.search(href)
        item = mi.group(1) if mi else None
        if not item and not mc:
            continue
        oid = item or mc.group(1)
        if oid in out:
            continue   # a vitrine repete o carrossel
        c = produtos.classifica(titulo, "Mercado Livre", id_loja=item or (mc.group(1) if mc else None))
        if not c.produto or produtos.eh_tv(c.produto):
            continue
        texto = _limpo(card.get_text(" ", strip=True))
        agora = _valor_agora(card)
        mo = _RE_OU.search(texto)
        cartao = parse_preco(mo.group(1)) if mo else None
        parcelado = f"{mo.group(2)}x R$ {mo.group(3)} sem juros" if mo else None
        if not parcelado:
            mp = _RE_SO_PARCELA.search(texto)
            if mp and int(mp.group(1)) > 1:
                parcelado = f"{mp.group(1)}x R$ {mp.group(2)} sem juros"
        if not agora:
            continue
        no_pix = bool(re.search(r"OFF\s+no\s+Pix", texto, re.I))
        if no_pix and cartao and cartao > agora + 0.005:
            preco, pix = cartao, agora
        else:
            preco, pix = (cartao or agora), None
        url = href.split("#")[0]
        extra = {"item_id": item, "catalogo": mc.group(1) if mc else None, "anuncio": item or oid,
                 "vendedor_id": produtos.ML_PLAYSTATION_VENDEDOR, "loja_oficial": "PlayStation"}
        if c.detalhes:
            extra["produto"] = dict(c.detalhes)
        out[oid] = Oferta(fonte="mercadolivre.playstation", tipo="loja", loja="Mercado Livre", titulo=titulo, url=url,
                          id=oid, preco=preco, preco_pix=pix, parcelado=parcelado, vendedor=VENDEDOR, extra=extra,
                          modelo=c.produto)
    return list(out.values())


class MercadoLivreLojaPlayStation(Fonte):
    nome = "mercadolivre.playstation"
    modo = "cloud"
    alerta_falha = False   # o ML às vezes pede verificação a IP de nuvem; o PS5 do ML também vem pelo PC e pelos posts

    def coletar(self) -> Resultado:
        html = get_html(config.URL_ML_LOJA_PLAYSTATION, tentativas=1)
        if bloqueada(html):
            raise RuntimeError("o Mercado Livre pediu verificação (antirrobô) na vitrine da loja oficial")
        ofertas = parse_loja(html)
        print(f"[mercadolivre.playstation] {len(ofertas)} ofertas da loja oficial")
        return ofertas, []
