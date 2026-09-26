"""Zoom/Buscapé: a página do produto traz JSON-LD com todas as ofertas (loja + preço).

O Zoom é um AGREGADOR, não uma loja: o preço pode estar defasado ou atribuído à loja errada. Toda oferta
daqui sai com extra["agregador"] = True, e estado/alertas/painel preferem a fonte direta da mesma loja.
"""

from __future__ import annotations

import re

from .. import config
from ..models import MODELO_PADRAO, Oferta
from ..util import fmt_preco, get_html, jsonld_produtos, loja_canonica, next_data, parse_preco
from . import Fonte, Resultado

_RE_MEDIA = re.compile(r"m[ée]dia[^R$]{0,60}R\$\s?([\d.]+,\d{2})", re.I)


def _estado_ofertas(html: str) -> dict[str, dict]:
    """offerList do estado da página (__NEXT_DATA__ → initialReduxState.offers), indexado pelo id da oferta.

    Traz o que o JSON-LD não traz: totalPrice (cartão), numParcels, parcelValue e hasInterest.
    """
    props = (next_data(html) or {}).get("props") or {}
    redux = props.get("initialReduxState") or (props.get("pageProps") or {}).get("initialReduxState") or {}
    lista = (redux.get("offers") or {}).get("offerList") or []
    return {str(o["id"]): o for o in lista if isinstance(o, dict) and o.get("id") is not None}


def _precos_do_estado(st: dict, preco_jsonld: float) -> tuple[float, float | None, str | None]:
    """(preco no cartão, preco_pix, parcelado) a partir de uma oferta do offerList.

    "price" é o menor preço (Pix/à vista) e "totalPrice" o preço no cartão. O parcelado só é guardado
    quando é sem juros: hasInterest=False, ou parcelas que somam o preço do cartão (o Zoom marca
    hasInterest=True sempre que o parcelado passa do preço à vista, mesmo quando a loja não cobra juros).
    """
    avista = parse_preco(st.get("price")) or preco_jsonld
    total = parse_preco(st.get("totalPrice")) or avista
    if total > avista + 0.5:
        preco, pix = total, avista
    else:
        preco, pix = avista, None
    parcelado = None
    try:
        n = int(st.get("numParcels") or 0)
    except (TypeError, ValueError):
        n = 0
    valor = parse_preco(st.get("parcelValue"))
    if n > 1 and valor:
        fecha = abs(n * valor - preco) <= max(1.0, preco * 0.005)
        if st.get("hasInterest") is False or fecha:
            parcelado = f"{n}x {fmt_preco(valor)} sem juros"
    return preco, pix, parcelado


def parse_produto(html: str, modelo: str = MODELO_PADRAO, url_produto: str | None = None) -> list[Oferta]:
    """Ofertas da página de produto do Zoom (uma página por modelo: config.URLS_ZOOM)."""
    out: list[Oferta] = []
    url_produto = url_produto or config.URLS_ZOOM.get(modelo, config.URL_ZOOM)
    estado = _estado_ofertas(html)
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
            pix = parcelado = None
            if oid in estado:
                preco, pix, parcelado = _precos_do_estado(estado[oid], preco)
            out.append(Oferta(
                fonte="zoom", tipo="loja", loja=loja_canonica(str(loja)), titulo=of.get("name") or prod.get("name") or "",
                url=of.get("url") or url_produto, id=oid, preco=preco, preco_pix=pix, parcelado=parcelado,
                extra={"agregador": True}, modelo=modelo,
            ))
    m = _RE_MEDIA.search(html)
    if m and out:
        for o in out:
            o.extra["media_40_dias"] = parse_preco(m.group(1))
    return out


class Zoom(Fonte):
    """Uma página de produto por modelo. A da 65C6K tem slug próprio (…-qd-mini-led-65-…): com o slug da 55" trocado,
    o Zoom responde 200 com uma página de BUSCA, sem JSON-LD, e o parser devolveria nada sem erro — por isso o aviso no
    log quando a página de um modelo vem vazia."""

    nome = "zoom"

    def coletar(self) -> Resultado:
        out: dict[str, Oferta] = {}
        for modelo, url in config.URLS_ZOOM.items():
            try:
                html = get_html(url)
            except Exception as e:  # noqa: BLE001
                if modelo == MODELO_PADRAO:
                    raise  # a página da 55C6K falhando, a fonte falha como antes
                print(f"[zoom] página da {modelo} falhou: {type(e).__name__}: {str(e)[:120]}")
                continue
            ofs = parse_produto(html, modelo, url)
            if not ofs:
                print(f"[zoom] a página da {modelo} veio sem ofertas (slug mudou? {url})")
            for o in ofs:
                if o.id in {x.id for x in out.values() if x.modelo != modelo}:
                    o.id = f"{o.id}-{modelo}"   # o mesmo id de oferta nas duas páginas: cada modelo com o seu
                out.setdefault(o.chave, o)
        return list(out.values()), []
