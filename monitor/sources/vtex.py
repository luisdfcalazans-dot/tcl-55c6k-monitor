"""Lojas na plataforma VTEX (Fast Shop, Loja TCL, Webcontinental): API pública de catálogo."""

from __future__ import annotations

import re

from .. import config
from ..filtro import eh_55c6k
from ..models import Oferta
from ..util import get_json, loja_canonica, parse_preco, sem_acentos
from . import Fonte, Resultado

_RE_PIX = re.compile(r"(\d{1,2})\s*%\s*(?:no\s+|de\s+desconto\s+no\s+)?pix", re.I)
_RE_PAGTO_A_VISTA = re.compile(r"^\s*(?:pix|boleto)\b", re.I)


def _pix_nas_parcelas(offer: dict) -> float | None:
    """Menor preço à vista (Pix/boleto em 1x) listado em Installments.

    A Fast Shop não usa teaser: o desconto do Pix só aparece como a parcela 1x do PaymentSystemName "Pix".
    """
    valores = []
    for i in offer.get("Installments") or []:
        nome = sem_acentos(str(i.get("PaymentSystemName") or ""))
        if (i.get("NumberOfInstallments") or 0) == 1 and _RE_PAGTO_A_VISTA.match(nome):
            v = parse_preco(i.get("Value"))
            if v:
                valores.append(v)
    return min(valores) if valores else None


def _teasers(offer: dict) -> list[str]:
    nomes = []
    for t in offer.get("Teasers") or []:
        nomes.append(t.get("<Name>k__BackingField") or t.get("Name") or t.get("name") or "")
    for t in offer.get("DiscountHighLight") or []:
        nomes.append(t.get("<Name>k__BackingField") or t.get("Name") or "")
    return [n for n in nomes if n]


def parse_catalogo(data: list, loja: str, base: str) -> list[Oferta]:
    out: list[Oferta] = []
    for p in data or []:
        nome = p.get("productName") or ""
        if not eh_55c6k(nome):
            continue
        for item in p.get("items") or []:
            for s in item.get("sellers") or []:
                of = s.get("commertialOffer") or {}
                preco = parse_preco(of.get("Price"))
                if not preco or (of.get("AvailableQuantity") or 0) <= 0:
                    continue
                inst = [i for i in of.get("Installments") or [] if (i.get("InterestRate") or 0) == 0]
                parcelado = None
                if inst:
                    m = max(inst, key=lambda i: i.get("NumberOfInstallments") or 0)
                    if (m.get("NumberOfInstallments") or 0) > 1:
                        parcelado = f"{m['NumberOfInstallments']}x R$ {m['Value']:.2f}".replace(".", ",") + " sem juros"
                pix_teaser = None
                for t in _teasers(of):
                    mm = _RE_PIX.search(t)
                    if mm:
                        pix_teaser = round(preco * (1 - int(mm.group(1)) / 100), 2)
                        break
                opcoes_pix = [v for v in (pix_teaser, _pix_nas_parcelas(of)) if v and v < preco]
                pix = min(opcoes_pix) if opcoes_pix else None
                vendedor = s.get("sellerName") or loja
                link = p.get("link") or (base + "/" + (p.get("linkText") or "") + "/p")
                out.append(Oferta(
                    fonte="vtex", tipo="loja", loja=loja_canonica(loja), titulo=nome, url=link,
                    id=f"{loja}-{p.get('productId')}-{s.get('sellerId') or vendedor}",
                    preco=preco, preco_pix=pix, parcelado=parcelado, vendedor=vendedor,
                    extra={"preco_de": parse_preco(of.get("ListPrice")), "ref": p.get("productReference")},
                ))
    return out


class Vtex(Fonte):
    modo = "cloud"

    def __init__(self, loja: str):
        self.loja = loja
        self.base = config.LOJAS_VTEX[loja]
        self.nome = f"vtex.{loja.lower().replace(' ', '')}"

    def coletar(self) -> Resultado:
        data = get_json(f"{self.base}/api/catalog_system/pub/products/search?ft=55c6k")
        return parse_catalogo(data, self.loja, self.base), []
