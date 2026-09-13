"""Amazon.com.br: página do produto. Tenta HTTP simples; se vier sem preço, abre no Chrome (modo pc)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import config
from ..filtro import eh_55c6k
from ..models import Oferta
from ..util import get_html, parcelado_no_texto, parse_preco
from . import Fonte, Resultado


def parse_produto(html: str) -> Oferta | None:
    if "api-services-support@amazon.com" in html or "Digite os caracteres" in html:
        raise RuntimeError("Amazon devolveu captcha")
    soup = BeautifulSoup(html, "html.parser")
    titulo_el = soup.select_one("#productTitle")
    titulo = titulo_el.get_text(" ", strip=True) if titulo_el else ""
    if not eh_55c6k(titulo):
        return None
    preco = None
    bloco = soup.select_one("#corePriceDisplay_desktop_feature_div, #corePrice_feature_div, #apex_desktop")
    if bloco:
        off = bloco.select_one(".a-offscreen")
        if off:
            preco = parse_preco(off.get_text(strip=True))
        if not preco:
            w = bloco.select_one(".a-price-whole")
            f = bloco.select_one(".a-price-fraction")
            if w:
                preco = parse_preco(w.get_text(strip=True).replace(",", "") + ("," + f.get_text(strip=True) if f else ""))
    if not preco:
        m = re.search(r'"displayPrice":"R\$\s?([\d.,]+)"', html)
        if m:
            preco = parse_preco(m.group(1))
    disp = soup.select_one("#availability")
    disp_txt = disp.get_text(" ", strip=True).lower() if disp else ""
    ativo = "indispon" not in disp_txt
    if not preco:
        return None if not ativo else Oferta(fonte="amazon", tipo="loja", loja="Amazon", titulo=titulo,
                                              url=config.URL_AMAZON_PRODUTO, id="B0F7JZMVKF", ativo=False)
    vendedor = None
    mi = soup.select_one("#merchant-info, #sellerProfileTriggerId")
    if mi:
        vendedor = mi.get_text(" ", strip=True)[:60]
    texto = soup.get_text(" ", strip=True)
    return Oferta(
        fonte="amazon", tipo="loja", loja="Amazon", titulo=titulo, url=config.URL_AMAZON_PRODUTO, id="B0F7JZMVKF",
        preco=preco, parcelado=parcelado_no_texto(texto), ativo=ativo, vendedor=vendedor,
        extra={"disponibilidade": disp_txt[:80]},
    )


class Amazon(Fonte):
    nome = "amazon"
    modo = "pc"

    def coletar(self) -> Resultado:
        o = None
        try:
            o = parse_produto(get_html(config.URL_AMAZON_PRODUTO))
        except Exception:
            o = None
        if o is None or o.preco is None:
            # a Amazon às vezes entrega a página sem o bloco de preço para clientes sem cookies
            from .playwright_sources import _abrir

            html, _, _ = _abrir(config.URL_AMAZON_PRODUTO, esperar="#productTitle")
            o = parse_produto(html)
        return ([o] if o else []), []
