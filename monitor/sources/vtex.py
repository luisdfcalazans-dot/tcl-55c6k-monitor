"""Lojas na plataforma VTEX: API pública de catálogo.

- Fast Shop, Loja TCL, Webcontinental (fontes vtex.<loja>, desde 13/09): uma busca por modelo de TV (ft=55c6k,
  ft=65c6k), como antes.
- Pelo EAN (fonte VtexEan, config.LOJAS_VTEX_EAN, 03/10/2026), um pedido por rodada: Mais Correios e Americanas com TODO
  o catálogo (TVs, PS5, GTA 6); Fast Shop e Webcontinental só com o PS5/GTA 6 (vtex.fastshop.ps5,
  vtex.webcontinental.ps5). A busca por texto perde anúncios (Mais Correios: ft=65c6k achou 1, o EAN achou 3, inclusive
  o do Ponto Frio onde o usuário comprou a 65C6K). Vários fq=alternateIds_Ean no mesmo pedido valem como OU; o EAN vai
  com e sem o zero à esquerda (o PS5 está cadastrado como 711719023876 numa loja e 0711719023876 em outra).

O produto sai do código de barras do item quando ele é conhecido, senão do título: TV pelo filtro de sempre (o título
tem de ser de uma TV C6K: o combo "TV + soundbar" tem o mesmo EAN da TV); PS5/GTA 6 pelo classificador do catálogo
(monitor/produtos.py), que recusa usado, estrangeiro e acessório mesmo com o EAN.
Parcelado: só os meios de CARTÃO contam. A Fast Shop lista também "Outros Pagamentos APP Vendedor (12x - s/ juros)",
que não é cartão: o 12x sem juros dele aparecia como o parcelado da loja, que nos cartões é 10x (26/09). A Americanas
lista "Cartão Cliente A" (o cartão da loja, 3x) e "WH Google Pay": também não contam.
Pix: a parcela 1x do meio "Pix" (Fast Shop, Mais Correios, Americanas) ou o selo "X% no Pix".
GTA 6 (Code in Box e pacotes com ele): prazo de entrega pela simulação de frete do checkout (orderForms/simulation, sem
carrinho e sem login) com o CEP de config.cep_entrega(); "39bd" = 39 dias úteis a partir de hoje. Só a data que cai antes
de as caixas saírem (12/11, ou o envio informado na descrição) é reprojetada (sources/entrega.marca).
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Iterable, Optional

import requests

from .. import config, produtos
from ..filtro import eh_tv_c6k, modelo_do_titulo
from ..models import MODELO_PADRAO, Oferta
from ..util import HEADERS_JSON, get_json, loja_canonica, parse_preco, sem_acentos
from . import Fonte, Resultado, entrega

_RE_PIX = re.compile(r"(\d{1,2})\s*%\s*(?:no\s+|de\s+desconto\s+no\s+)?pix", re.I)
_RE_PAGTO_A_VISTA = re.compile(r"^\s*(?:pix|boleto)\b", re.I)
# meio de pagamento que não é cartão: Pix, boleto, vale, "Outros Pagamentos APP Vendedor", carteiras, crediário e o
# cartão da própria loja ("Cartão Cliente A" da Americanas)
_RE_NAO_E_CARTAO = re.compile(r"\b(?:pix|boleto|vale|outros?\s+pagamentos?|app|carteira|credi[aá]rio|carn[eê]|cdc|"
                              r"cashback|pontos|gift|debito|cliente|pay)\b", re.I)


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


def modelo_do_item(nome: str, item: dict, loja: str = "") -> str | None:
    """Produto do item: '55C6K', '65C6K', um id do catálogo do PS5/GTA 6 ('PS5_DIGITAL', 'GTA6_CODE_IN_BOX'...) ou None.

    TV: o EAN conhecido decide (o título só precisa ser de uma TV C6K); sem ele, o título. PS5/GTA 6: o classificador do
    catálogo com o EAN (o EAN diz qual produto; o título ainda recusa usado, estrangeiro e kit de outra coisa)."""
    ean = str(item.get("ean") or "").strip()
    modelo = config.EAN_POR_MODELO.get(ean)
    if modelo:
        return modelo if eh_tv_c6k(nome) else None
    tv = modelo_do_titulo(nome)
    if tv:
        return tv
    por_ean = produtos.produto_por_ean(ean) if ean else None
    if por_ean and produtos.eh_tv(por_ean):
        return None   # EAN de TV (sem os zeros) com um título que não é da C6K
    c = produtos.classifica(nome, loja or None, ean=ean or None)
    return c.produto if c.produto and not produtos.eh_tv(c.produto) else None


def parse_catalogo(data: list, loja: str, base: str, modelo: str | None = None, fonte: str = "vtex") -> list[Oferta]:
    """Ofertas da resposta da busca do catálogo. `modelo`: só as desse produto (None: as de todos)."""
    out: list[Oferta] = []
    for p in data or []:
        nome = p.get("productName") or ""
        for item in p.get("items") or []:
            m = modelo_do_item(nome, item, loja)
            if not m or (modelo is not None and m != modelo):
                continue
            detalhes = {} if produtos.eh_tv(m) else produtos.classifica(nome, loja, ean=item.get("ean") or None).detalhes
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
                extra = {"preco_de": parse_preco(of.get("ListPrice")), "ref": p.get("productReference"),
                         "ean": item.get("ean") or None}
                if not produtos.eh_tv(m):
                    # o que a simulação de frete precisa (sku e vendedor). O id do vendedor NÃO vai em vendedor_id: as
                    # listas de confiança destas lojas casam pelo nome (com o id, só o id decidiria)
                    extra.update({"sku": item.get("itemId"), "seller_id": s.get("sellerId") or None})
                    if detalhes:
                        extra["produto"] = detalhes
                    descr = sem_acentos(str(p.get("description") or "")).lower()
                    envio = entrega.envio_a_partir(descr) if entrega.precisa(m) else None
                    if envio:
                        extra["envio_a_partir"] = envio
                out.append(Oferta(
                    fonte=fonte, tipo="loja", loja=loja_canonica(loja), titulo=nome, url=link,
                    id=f"{loja}-{p.get('productId')}-{s.get('sellerId') or vendedor}",
                    preco=preco, preco_pix=pix, parcelado=parcelado, vendedor=vendedor,
                    extra=extra, modelo=m,
                ))
    return out


def eans_do_catalogo(familias: Optional[Iterable[str]] = None) -> list[str]:
    """Os EANs do catálogo para o fq=alternateIds_Ean, cada um com e sem os zeros à esquerda (sem repetição)."""
    out: list[str] = []
    for e in produtos.eans_por_produto(familias):
        d = re.sub(r"\D", "", e)
        for x in (d, d.lstrip("0")):
            if x and x not in out:
                out.append(x)
    return out


def url_por_ean(base: str, eans: Iterable[str]) -> str:
    q = "&".join(f"fq=alternateIds_Ean:{e}" for e in eans)
    return f"{base}/api/catalog_system/pub/products/search?{q}&_from=0&_to=49"


def simula_prazo(base: str, sku: str, vendedor: str, cep: str, timeout: int = 20,
                 inicio: Optional[date] = None) -> Optional[str]:
    """Prazo de entrega (data ISO) do item no CEP pela simulação do checkout (sem carrinho, sem login). A menor
    estimativa entre as opções de entrega (retirada não conta), contada a partir de HOJE (é como a loja conta: "39bd" é
    39 dias úteis depois do pedido). None quando a loja não responde ou não entrega.
    `inicio`: pré-venda (GTA 6 físico): só a data que cai ANTES do envio (12/11 ou o informado) é reprojetada a partir
    dele (entrega.ajusta_pre_venda); a que já cai depois vale como está. 2ª conferência de 03/10: contar toda estimativa
    a partir de 12/11 contava a espera da pré-venda duas vezes ("39bd" da Fast Shop virava 11/01/2027 em vez de 01/12)."""
    h = dict(HEADERS_JSON)
    h["Content-Type"] = "application/json"
    corpo = {"items": [{"id": str(sku), "quantity": 1, "seller": str(vendedor)}], "postalCode": cep, "country": "BRA"}
    r = requests.post(f"{base}/api/checkout/pub/orderForms/simulation?sc=1", json=corpo, headers=h, timeout=timeout)
    r.raise_for_status()
    datas = []
    hoje = entrega.hoje()
    for li in (r.json() or {}).get("logisticsInfo") or []:
        for s in li.get("slas") or []:
            if str(s.get("deliveryChannel") or "delivery") != "delivery":
                continue
            d = entrega.data_da_estimativa(s.get("shippingEstimate"), hoje)
            if d:
                datas.append(d)
    if not datas:
        return None
    menor = min(datas)
    if inicio:
        menor = entrega.ajusta_pre_venda(menor, base=hoje, inicio=inicio)[0]
    return menor


def completa_entrega(ofertas: list[Oferta], base: str, nome: str, maximo: int = 3) -> None:
    """Prazo do GTA 6 físico (o jogo e os pacotes) de até `maximo` ofertas (das mais baratas), com o CEP de entrega.
    A descrição que diz "envio a partir de 19/11" (ou depois) já basta: chega depois do lançamento, sem simular.
    Falha não derruba a coleta (a oferta fica com a estimativa da pesquisa)."""
    cep, referencia = entrega.cep()
    alvos = sorted((o for o in ofertas if entrega.precisa(o.modelo) and o.extra.get("sku")),
                   key=lambda o: o.melhor_preco or 9e9)[:maximo]
    for o in alvos:
        envio = o.extra.get("envio_a_partir")
        if envio and envio >= produtos.LANCAMENTO_GTA6:
            entrega.marca_envio_tardio(o)
            continue
        try:
            # a data contada de hoje, como a loja conta; entrega.marca reprojeta só a que cai antes de as caixas saírem
            # (12/11 ou o envio informado) e anota "(prazo contado a partir de 12/11...)" nela
            data = simula_prazo(base, o.extra["sku"], o.extra.get("seller_id") or "1", cep)
        except Exception as e:  # noqa: BLE001 - o prazo é extra: a oferta continua sem ele
            print(f"[{nome}] simulação de frete de {o.id} falhou: {type(e).__name__}")
            continue
        entrega.marca(o, data, referencia, "simulação de frete")


class Vtex(Fonte):
    modo = "cloud"

    def __init__(self, loja: str):
        self.loja = loja
        self.base = config.LOJAS_VTEX[loja]
        self.nome = f"vtex.{loja.lower().replace(' ', '')}"

    def coletar(self) -> Resultado:
        """Uma busca por modelo de TV (ft=55c6k, ft=65c6k), com pausa entre elas (a Webcontinental dá timeout com
        consultas seguidas). A busca da 55C6K falhando, a fonte falha como antes; a da 65C6K só vai para o log. O PS5/GTA
        6 destas lojas tem fonte própria (VtexEan, pelo EAN)."""
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


class VtexEan(Fonte):
    """Loja VTEX lida pelo EAN (config.LOJAS_VTEX_EAN): um pedido por rodada, com a URL de reserva quando a principal
    falha. Mais Correios e Americanas com o catálogo todo (TVs, PS5, GTA 6); Fast Shop e Webcontinental só com o
    PS5/GTA 6 (as TVs delas continuam na fonte Vtex de sempre)."""

    modo = "cloud"

    def __init__(self, nome: str):
        self.nome = nome
        self.loja, self.base, self.reserva, so_nao_tv = config.LOJAS_VTEX_EAN[nome]
        self.familias = config._NAO_TV if so_nao_tv else None

    def coletar(self) -> Resultado:
        eans = eans_do_catalogo(self.familias)
        erros = []
        for base in [b for b in (self.base, self.reserva) if b]:
            try:
                data = get_json(url_por_ean(base, eans))
            except Exception as e:  # noqa: BLE001
                erros.append(f"{base}: {type(e).__name__}: {str(e)[:100]}")
                continue
            ofertas = parse_catalogo(data, self.loja, self.base, fonte=self.nome)
            if self.familias is not None:
                ofertas = [o for o in ofertas if produtos.familia(o.modelo) in self.familias]
            completa_entrega(ofertas, base, self.nome)
            por_produto = ", ".join(f"{sum(o.modelo == m for o in ofertas)} {m}" for m in sorted({o.modelo for o in ofertas}))
            print(f"[{self.nome}] {len(ofertas)} ofertas pelo EAN" + (f" ({por_produto})" if por_produto else ""))
            return ofertas, []
        raise RuntimeError("; ".join(erros)[:300])
