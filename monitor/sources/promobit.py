"""Promobit: API pública de busca, categoria TV (__NEXT_DATA__) e cupons por loja."""

from __future__ import annotations

from urllib.parse import quote

from .. import config, produtos
from ..models import Cupom, Oferta
from ..util import get_html, get_json, iso_normaliza, loja_canonica, next_data, parse_preco
from . import Fonte, Resultado

_HEADERS = {"Origin": "https://www.promobit.com.br", "Referer": "https://www.promobit.com.br/"}


def _oferta_de_item(item: dict, ativo: bool) -> Oferta | None:
    """Itens da API (snake_case) e do __NEXT_DATA__ (camelCase) têm os mesmos campos. Só os produtos do catálogo (pelo
    título: as TVs, o PS5, o GTA 6, o gift card, o leitor); o id da postagem é único, então o de um produto não colide
    com o de outro."""
    g = lambda a, b: item.get(a) if item.get(a) is not None else item.get(b)  # noqa: E731
    titulo = (g("offer_title", "offerTitle") or "").strip()
    loja = g("store_name", "storeName") or "?"
    cl = produtos.classifica(titulo, loja)
    if not cl.produto:
        return None
    oid = g("offer_id", "offerId")
    slug = g("offer_slug", "offerSlug") or ""
    status = (g("offer_status_name", "offerStatusName") or "").upper()
    preco = parse_preco(g("offer_price", "offerPrice"))
    extra = {"preco_antigo": parse_preco(g("offer_old_price", "offerOldPrice")), "status": status}
    if cl.detalhes:
        extra["produto"] = cl.detalhes
    return Oferta(
        fonte="promobit", tipo="post",
        loja=loja_canonica(loja),
        titulo=titulo, url=f"https://www.promobit.com.br/oferta/{slug}/", id=str(oid),
        preco=preco, cupom=(g("offer_coupon", "offerCoupon") or None) or None,
        publicado=iso_normaliza(g("offer_published", "offerPublished")),
        ativo=ativo and status in ("", "APPROVED", "ACTIVE"),
        extra=extra, modelo=cl.produto,
    )


class PromobitBusca(Fonte):
    nome = "promobit.busca"

    def coletar(self) -> Resultado:
        vistos: dict[str, Oferta] = {}
        # os termos do catálogo (monitor/produtos.py): os das duas TVs ("tcl c6k 65" pega "65 Polegadas ... C6K" sem o
        # código colado), do PS5, do GTA 6 ("gta vi", "gta 6" e "grand theft auto vi" trazem conjuntos diferentes), do
        # gift card e do leitor; cada postagem fica com o produto do título dela, qualquer que seja a busca que a trouxe
        for q in produtos.termos("promobit"):
            data = get_json(f"https://api.promobit.com.br/search?q={quote(q)}", headers=_HEADERS)
            for item in data.get("active_offers") or []:
                o = _oferta_de_item(item, True)
                if o:
                    vistos.setdefault(o.chave, o)
            for item in data.get("finished_offers") or []:
                o = _oferta_de_item(item, False)
                if o:
                    vistos.setdefault(o.chave, o)
        return list(vistos.values()), []


def parse_categoria(html: str) -> list[Oferta]:
    """Ofertas do catálogo na página de uma categoria/subcategoria (__NEXT_DATA__ serverOffers)."""
    nd = next_data(html) or {}
    itens = (nd.get("props", {}).get("pageProps", {}) or {}).get("serverOffers") or []
    if isinstance(itens, dict):
        itens = itens.get("offers") or itens.get("data") or []
    out = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        o = _oferta_de_item(item, True)
        if o:
            out.append(o)
    return out


class PromobitCategoriaTV(Fonte):
    """Últimas ofertas da categoria TV: pega postagens novas antes de a busca indexar."""

    nome = "promobit.tv"

    def coletar(self) -> Resultado:
        return parse_categoria(get_html("https://www.promobit.com.br/promocoes/tv/s/")), []


class PromobitCategoriaPS5(Fonte):
    """Últimas ofertas da subcategoria PlayStation 5 (console, GTA 6, leitor, gift card): o mesmo formato da de TV
    (03/10/2026: 12 ofertas, as da Netshoes e da Amazon de 02-03/10 entre elas)."""

    nome = "promobit.ps5"

    def coletar(self) -> Resultado:
        return parse_categoria(get_html(config.URL_PROMOBIT_PS5)), []


class PromobitCupons(Fonte):
    nome = "promobit.cupons"

    def coletar(self) -> Resultado:
        cupons: list[Cupom] = []
        for slug in config.PROMOBIT_CUPONS_LOJAS:
            url = f"https://www.promobit.com.br/cupons/loja/{slug}/"
            try:
                html = get_html(url)
            except Exception:
                continue  # loja sem página de cupons
            nd = next_data(html) or {}
            lista = (nd.get("props", {}).get("pageProps", {}) or {}).get("serverCoupons") or []
            if isinstance(lista, dict):
                lista = lista.get("coupons") or []
            for c in lista:
                if not isinstance(c, dict):
                    continue
                cod = (c.get("couponCode") or "").strip()
                if not cod or (c.get("couponStatusName") or "APPROVED") != "APPROVED":
                    continue
                regra = " ".join(x for x in [c.get("couponDiscountOn"), c.get("couponInstructions")] if x).strip()
                cupons.append(Cupom(
                    fonte="promobit", loja=loja_canonica(c.get("storeName") or slug), codigo=cod,
                    titulo=(c.get("couponTitle") or "").strip(), url=url, id=str(c.get("couponId") or cod),
                    regra=regra, validade=iso_normaliza(c.get("couponUntil")),
                    publicado=iso_normaliza(c.get("couponPublished")),
                ))
        return [], cupons
