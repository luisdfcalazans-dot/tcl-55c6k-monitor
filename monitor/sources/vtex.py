"""Lojas na plataforma VTEX (Fast Shop, Loja TCL, Webcontinental): API pública de catálogo, uma busca por modelo.

O modelo sai do código de barras do item (EAN, config.EAN_POR_MODELO; a 65C6K é 7899968301754) quando ele é conhecido,
senão do título; o título sempre tem de ser de uma TV C6K (o combo "TV + soundbar" tem o mesmo EAN da TV).
Parcelado: só os meios de CARTÃO contam. A Fast Shop lista também "Outros Pagamentos APP Vendedor (12x - s/ juros)",
que não é cartão: o 12x sem juros dele aparecia como o parcelado da loja, que nos cartões é 10x (26/09).
"""

from __future__ import annotations

import re
import time

from .. import config
from ..filtro import eh_tv_c6k, modelo_do_titulo
from ..models import MODELO_PADRAO, Oferta
from ..util import get_json, loja_canonica, parse_preco, sem_acentos
from . import Fonte, Resultado

_RE_PIX = re.compile(r"(\d{1,2})\s*%\s*(?:no\s+|de\s+desconto\s+no\s+)?pix", re.I)
_RE_PAGTO_A_VISTA = re.compile(r"^\s*(?:pix|boleto)\b", re.I)
# meio de pagamento que não é cartão: Pix, boleto, vale, "Outros Pagamentos APP Vendedor", carteiras e crediário
_RE_NAO_E_CARTAO = re.compile(r"\b(?:pix|boleto|vale|outros?\s+pagamentos?|app|carteira|credi[aá]rio|carn[eê]|cdc|"
                              r"cashback|pontos|gift|debito)\b", re.I)


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


def _parcelado_do_cartao(offer: dict) -> str | None:
    """Maior parcelamento sem juros nos meios de CARTÃO ('10x R$ 400,90 sem juros'); None sem parcelamento sem juros."""
    inst = [i for i in offer.get("Installments") or [] if (i.get("InterestRate") or 0) == 0
            and not _RE_NAO_E_CARTAO.search(sem_acentos(str(i.get("PaymentSystemName") or "")))]
    if not inst:
        return None
    m = max(inst, key=lambda i: i.get("NumberOfInstallments") or 0)
    if (m.get("NumberOfInstallments") or 0) <= 1:
        return None
    return f"{m['NumberOfInstallments']}x R$ {m['Value']:.2f}".replace(".", ",") + " sem juros"


def _teasers(offer: dict) -> list[str]:
    nomes = []
    for t in offer.get("Teasers") or []:
        nomes.append(t.get("<Name>k__BackingField") or t.get("Name") or t.get("name") or "")
    for t in offer.get("DiscountHighLight") or []:
        nomes.append(t.get("<Name>k__BackingField") or t.get("Name") or "")
    return [n for n in nomes if n]


def modelo_do_item(nome: str, item: dict) -> str | None:
    """'55C6K', '65C6K' ou None: o EAN conhecido decide (o título só precisa ser de uma TV C6K); sem ele, o título."""
    ean = str(item.get("ean") or "").strip()
    modelo = config.EAN_POR_MODELO.get(ean)
    if modelo:
        return modelo if eh_tv_c6k(nome) else None
    return modelo_do_titulo(nome)


def parse_catalogo(data: list, loja: str, base: str, modelo: str | None = None) -> list[Oferta]:
    """Ofertas da resposta da busca do catálogo. `modelo`: só as desse modelo (None: as dos dois)."""
    out: list[Oferta] = []
    for p in data or []:
        nome = p.get("productName") or ""
        for item in p.get("items") or []:
            m = modelo_do_item(nome, item)
            if not m or (modelo is not None and m != modelo):
                continue
            for s in item.get("sellers") or []:
                of = s.get("commertialOffer") or {}
                preco = parse_preco(of.get("Price"))
                if not preco or (of.get("AvailableQuantity") or 0) <= 0:
                    continue
                parcelado = _parcelado_do_cartao(of)
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
                    extra={"preco_de": parse_preco(of.get("ListPrice")), "ref": p.get("productReference"),
                           "ean": item.get("ean") or None},
                    modelo=m,
                ))
    return out


class Vtex(Fonte):
    modo = "cloud"

    def __init__(self, loja: str):
        self.loja = loja
        self.base = config.LOJAS_VTEX[loja]
        self.nome = f"vtex.{loja.lower().replace(' ', '')}"

    def coletar(self) -> Resultado:
        """Uma busca por modelo (ft=55c6k, ft=65c6k), com pausa entre elas (a Webcontinental dá timeout com consultas
        seguidas). A busca da 55C6K falhando, a fonte falha como antes; a da 65C6K só vai para o log."""
        out: dict[str, Oferta] = {}
        for i, (modelo, termo) in enumerate(config.VTEX_TERMOS.items()):
            if i and config.VTEX_PAUSA_S > 0:
                time.sleep(config.VTEX_PAUSA_S)
            try:
                data = get_json(f"{self.base}/api/catalog_system/pub/products/search?ft={termo}")
            except Exception as e:  # noqa: BLE001
                if modelo == MODELO_PADRAO:
                    raise
                print(f"[{self.nome}] busca da {modelo} falhou: {type(e).__name__}: {str(e)[:120]}")
                continue
            for o in parse_catalogo(data, self.loja, self.base, modelo):
                out.setdefault(o.chave, o)
        return list(out.values()), []
