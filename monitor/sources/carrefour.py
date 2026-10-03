"""Carrefour: a busca (HTML) e a página de cada produto (JSON-LD + o bloco de preço), por HTTP.

A API VTEX do Carrefour dá 403 (Cloudflare), mas a busca e a página do produto respondem 200 por HTTP (03/10/2026):
- busca (config.URL_CARREFOUR_BUSCA): cartões <a data-testid="search-product-card" href="/produto/<slug>-<sku>"> com
  o título (<h2>), o preço do Pix ("R$ X à vista no Pix") e o do cartão ("ou R$ Y em até Nx de R$ Z sem juros [no
  Cartão Carrefour]"). O cartão da busca não diz quem vende;
- página do produto (até config.CARREFOUR_MAX_PRODUTOS por rodada: os do catálogo primeiro, depois os mais baratos;
  o slug não importa, só o sku no fim): JSON-LD (preço do cartão, gtin, sku, disponibilidade), "Vendido e entregue
  por <strong>Carrefour</strong>", o Pix e o parcelado sem juros (o "nos nossos Cartões" é do cartão da loja e fica de
  fora) e a descrição, onde o GTA 6 diz "ENVIO A PARTIR DE 19 DE NOVEMBRO" (chega depois do lançamento).
Só os produtos do catálogo que não são TV (o classificador recusa controle, óculos VR2, jogo de outro título...).
"""

from __future__ import annotations

import re
import time
from typing import Optional

from bs4 import BeautifulSoup

from .. import config, produtos
from ..models import Oferta
from ..util import get_html, jsonld_produtos, limpa_html, parse_preco
from . import Fonte, Resultado, entrega

BASE = "https://www.carrefour.com.br"
_RE_SKU = re.compile(r"/produto/[^\"'#?]*?-(\d{6,})(?:[/?#]|$)")
_NUM = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})"
_RE_PIX = re.compile(r"R\$\s?" + _NUM + r"\s*a vista no pix", re.I)
_RE_PARCELADO = re.compile(r"ou\s+R\$\s?" + _NUM + r"\s+em at[ée]\s+(\d{1,2})\s*x\s+de\s+R\$\s?" + _NUM +
                           r"\s+sem juros(?P<loja>\s+n[oa]s?\s+(?:nossos\s+)?cart(?:ao|oes|ão|ões)(?:\s+carrefour)?)?",
                           re.I)
# a própria loja: "Vendido e entregue por <strong>Carrefour</strong>"; parceiro: "... por <a href=".../parceiro/<ID>">nome</a>"
_RE_VENDEDOR = re.compile(r"Vendido\s+(?:e\s+entregue\s+)?por(?:<!--\s*-->)?\s*(?:<strong[^>]*>|<a\s[^>]*?href=\"[^\"]*?"
                          r"/parceiro/([^\"/?]+)[^\"]*\"[^>]*>)\s*([^<]{2,60}?)\s*</(?:strong|a)>", re.I)


def _texto(html_trecho: str) -> str:
    from ..util import sem_acentos

    return re.sub(r"\s+", " ", sem_acentos(limpa_html(html_trecho)))


def precos_do_texto(texto: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """(cartão, Pix, parcelado sem juros) de um texto de preço do Carrefour ("R$ 4.369,90 à vista no Pix 5 % OFF ou R$
    4.599,89 em até 10 x de R$ 459,98 sem juros"). O parcelado só no cartão da loja não conta."""
    m = _RE_PIX.search(texto)
    pix = parse_preco(m.group(1)) if m else None
    cartao = parcelado = None
    for mp in _RE_PARCELADO.finditer(texto):
        cartao = cartao or parse_preco(mp.group(1))
        if not mp.group("loja") and int(mp.group(2)) > 1:
            parcelado = f"{mp.group(2)}x R$ {mp.group(3)} sem juros"
            cartao = parse_preco(mp.group(1))
            break
    return cartao, pix, parcelado


def parse_busca(html: str) -> list[dict]:
    """Cartões da busca: {sku, url, titulo, cartao, pix} (todos; o classificador escolhe depois)."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, dict] = {}
    for a in soup.select('a[data-testid="search-product-card"][href*="/produto/"]'):
        m = _RE_SKU.search(a.get("href") or "")
        h2 = a.select_one("h2")
        if not m or not h2 or m.group(1) in out:
            continue
        cartao, pix, _parc = precos_do_texto(_texto(str(a)))
        out[m.group(1)] = {"sku": m.group(1), "url": BASE + a["href"].split("?")[0].split("#")[0],
                           "titulo": h2.get_text(" ", strip=True), "cartao": cartao, "pix": pix}
    return list(out.values())


def parse_produto(html: str, sku: str, url: str) -> Optional[Oferta]:
    """Oferta da página do produto (só se for um produto do catálogo que não é TV)."""
    prod = next((p for p in jsonld_produtos(html) if p.get("name")), None)
    if not prod:
        return None
    titulo = str(prod.get("name") or "")
    c = produtos.classifica(titulo, "Carrefour", ean=prod.get("gtin") or prod.get("gtin13") or None,
                            id_loja=sku)
    if not c.produto or produtos.eh_tv(c.produto):
        return None
    ofs = prod.get("offers")
    of = (ofs[0] if isinstance(ofs, list) and ofs else ofs) if ofs else {}
    of = of if isinstance(of, dict) else {}
    disp = str(of.get("availability") or "")
    preco_ld = parse_preco(of.get("price"))
    i = html.find("vista no Pix")
    bloco = _texto(html[max(0, i - 1500): i + 1500]) if i >= 0 else ""
    cartao, pix, parcelado = precos_do_texto(bloco)
    cartao = cartao or preco_ld
    if pix and cartao and pix >= cartao:
        pix = None
    if not (cartao or pix):
        return None
    mv = _RE_VENDEDOR.search(html)
    vendedor = mv.group(2).strip() if mv else None
    extra: dict = {"sku": sku, "anuncio": sku, "ean": prod.get("gtin") or None}
    if mv and mv.group(1):
        extra["vendedor_id"] = mv.group(1)   # parceiro (a própria loja não tem link nem id: casa pelo nome)
    if c.detalhes:
        extra["produto"] = dict(c.detalhes)
    o = Oferta(fonte="carrefour", tipo="loja", loja="Carrefour", titulo=titulo, url=url, id=sku, preco=cartao,
               preco_pix=pix, parcelado=parcelado, vendedor=vendedor,
               ativo=not re.search(r"OutOfStock|SoldOut|Discontinued", disp), extra=extra, modelo=c.produto)
    envio = entrega.envio_a_partir(limpa_html(str(prod.get("description") or "")))
    if envio and envio >= produtos.LANCAMENTO_GTA6:
        entrega.marca_envio_tardio(o)
    return o


class Carrefour(Fonte):
    nome = "carrefour"

    def coletar(self) -> Resultado:
        """A busca (1 pedido) e a página dos produtos (os do catálogo e os mais baratos da busca, até o limite)."""
        cartoes = []
        erros: list[str] = []
        try:
            cartoes = parse_busca(get_html(config.URL_CARREFOUR_BUSCA))
        except Exception as e:  # noqa: BLE001 - os do catálogo ainda podem ser lidos
            erros.append(f"busca: {type(e).__name__}: {str(e)[:120]}")
        na_busca: dict[str, dict] = {}
        for cd in cartoes:
            cl = produtos.classifica(cd["titulo"], "Carrefour", id_loja=cd["sku"])
            if cl.produto and not produtos.eh_tv(cl.produto):
                na_busca[cd["sku"]] = dict(cd, produto=cl.produto, detalhes=cl.detalhes)
        fila = [s for s in produtos.ids_da_loja("Carrefour", config._NAO_TV) if s.isdigit() and len(s) >= 8]
        fila += [cd["sku"] for cd in sorted(na_busca.values(), key=lambda x: x["pix"] or x["cartao"] or 9e9)]
        fila = list(dict.fromkeys(fila))[:config.CARREFOUR_MAX_PRODUTOS]
        por_id: dict[str, Oferta] = {}
        for i, sku in enumerate(fila):
            if i and config.CARREFOUR_PAUSA_S > 0:
                time.sleep(config.CARREFOUR_PAUSA_S)
            url = na_busca.get(sku, {}).get("url") or config.URL_CARREFOUR_PRODUTO.format(sku=sku)
            try:
                o = parse_produto(get_html(url, tentativas=1), sku, url)
            except Exception as e:  # noqa: BLE001
                erros.append(f"{sku}: {type(e).__name__}: {str(e)[:100]}")
                continue
            if o:
                por_id[o.id] = o
        # os da busca que não foram abertos: o preço do cartão da busca, sem o vendedor
        for sku, cd in na_busca.items():
            if sku in por_id or not (cd["cartao"] or cd["pix"]):
                continue
            pix = cd["pix"] if cd["pix"] and (not cd["cartao"] or cd["pix"] < cd["cartao"]) else None
            extra = {"sku": sku, "anuncio": sku, "origem": "busca"}
            if cd["detalhes"]:
                extra["produto"] = dict(cd["detalhes"])
            por_id[sku] = Oferta(fonte="carrefour", tipo="loja", loja="Carrefour", titulo=cd["titulo"], url=cd["url"],
                                 id=sku, preco=cd["cartao"] or cd["pix"], preco_pix=pix, extra=extra,
                                 modelo=cd["produto"])
        ofertas = list(por_id.values())
        if erros:
            print("[carrefour] " + " | ".join(erros))
        if not ofertas and erros:
            raise RuntimeError(erros[0])
        return ofertas, []
