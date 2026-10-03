"""KaBuM!: API pública do catálogo e a lista de consoles PlayStation.

- TVs (fonte "kabum", desde 13/09): um pedido por anúncio (config.KABUM_PRODUTOS: a 55C6K e os dois da 65C6K).
- PS5, GTA 6 e leitor (fonte "kabum.produtos", 03/10/2026):
  * a lista /gamer/playstation/consoles-playstation: um pedido traz todos os consoles da loja (o __NEXT_DATA__ traz
    pageProps.data como TEXTO JSON: catalogServer.data), com vendedor (KaBuM! ou parceiro) e oferta relâmpago;
  * a API do produto para o que o catálogo conhece e a lista não trouxe (o GTA 6, o leitor, o kit): pré-venda em
    is_pre_order / date_pre_order;
  * o prazo do GTA 6 físico pela cotação de frete (shipping/v4/quotation, sem login nem cookie) com o CEP de
    config.cep_entrega() (o CEP nunca é impresso).
Oferta relâmpago só para assinante Prime Ninja (isPrimeExclusive) não vale: o usuário não assina.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import requests

from .. import config, produtos
from ..filtro import modelo_do_titulo
from ..models import MODELO_PADRAO, Oferta
from ..util import HEADERS_JSON, get_html, get_json, limpa_html, next_data, parse_preco
from . import Fonte, Resultado, entrega


def _monta(titulo: str, pid: str, a: dict, modelo: str, fonte: str = "kabum", detalhes: Optional[dict] = None,
           agora: Optional[float] = None) -> Oferta:
    preco = parse_preco(a.get("price"))
    pix = parse_preco(a.get("price_with_discount"))
    oferta = a.get("offer") or {}
    agora = time.time() if agora is None else agora
    em_oferta = bool(oferta) and (oferta.get("starts_at") or 0) <= agora <= (oferta.get("ends_at") or 0) \
        and (oferta.get("quantity_available") is None or oferta.get("quantity_available", 1) > 0) \
        and not oferta.get("is_prime_exclusive")
    extra: dict[str, Any] = {"preco_tabela": preco, "openbox": a.get("is_openbox")}
    if em_oferta:
        extra["oferta"] = oferta.get("name")
        preco = parse_preco(oferta.get("price")) or preco
        pix = parse_preco(oferta.get("price_with_discount")) or pix
    parcelado = a.get("max_installment") or None
    if parcelado and "sem juros" not in parcelado:
        parcelado = f"{parcelado} sem juros"
    # anúncio de marketplace (seller_type 3P): quem vende é o lojista parceiro, e ele muda sem aviso
    vendedor: str | None = "KaBuM!"
    if a.get("is_marketplace"):
        vendedor = str((a.get("marketplace") or {}).get("seller_name") or "").strip() or None
    if not produtos.eh_tv(modelo):
        # o id do parceiro fica fora de vendedor_id: a lista de confiança da KaBuM casa pelo nome (com o id, só o id
        # decidiria, e a Fast Shop/Gazin entraram por nome)
        mk = a.get("marketplace") or {}
        extra["kabum_seller_id"] = str(mk.get("seller_id") or "0") if a.get("is_marketplace") else "0"
        # a cotação de frete de parceiro exige o id da oferta dele (marketplace.product_id / offerIdMarketplace)
        extra["kabum_oferta_id"] = int(mk.get("product_id") or 0) if a.get("is_marketplace") else 0
        envios = []
        if a.get("is_pre_order"):
            extra["pre_venda"] = True
            dpo = a.get("date_pre_order")
            if isinstance(dpo, (int, float)) and dpo > 0:
                from datetime import datetime

                from ..util import TZ_BR

                envios.append(datetime.fromtimestamp(dpo, TZ_BR).date().isoformat())
        if entrega.precisa(modelo):
            # o parceiro que escreve "SERÁ ENVIADO A PARTIR DO DIA 20/11/2026" na descrição (MERCADOONLINESP, 03/10)
            envio_txt = entrega.envio_a_partir(limpa_html(str(a.get("description") or ""))[:4000])
            if envio_txt:
                envios.append(envio_txt)
        if envios:
            extra["envio_a_partir"] = max(envios)
        if detalhes:
            extra["produto"] = detalhes
    return Oferta(
        fonte=fonte, tipo="loja", loja="KaBuM!", titulo=titulo, url=config.URL_KABUM_PRODUTO_BASE + pid,
        id=pid, preco=preco,
        preco_pix=pix if pix and preco and pix < preco else None, parcelado=parcelado, vendedor=vendedor,
        extra=extra, modelo=modelo,
    )


def parse_api(data: dict, modelo: str = MODELO_PADRAO, fonte: str = "kabum") -> Oferta | None:
    """Oferta do anúncio da API. TV: só se ele é do `modelo` pelo título (65C7K, vizinho da 65C6K no mesmo vendedor, não
    é). PS5/GTA 6: o produto do classificador do catálogo com o id da KaBuM (anúncio "caixa aberta" fica de fora)."""
    a = data.get("attributes") or {}
    titulo = a.get("title") or ""
    pid = str(data.get("id") or config.KABUM_PRODUTOS[MODELO_PADRAO][0])
    if produtos.eh_tv(modelo):
        if modelo_do_titulo(titulo) != modelo or not a.get("available", True):
            return None
        return _monta(titulo, pid, a, modelo, fonte)
    if not a.get("available", True) or a.get("is_openbox"):
        return None
    c = produtos.classifica(titulo, "KaBuM!", id_loja=pid)
    if not c.produto or produtos.eh_tv(c.produto):
        return None
    return _monta(titulo, pid, a, c.produto, fonte, c.detalhes)


def _atributos_da_lista(it: dict) -> dict:
    """Um item da lista (catalogServer.data, camelCase) no formato dos atributos da API (snake_case)."""
    flags = it.get("flags") or {}
    of = it.get("offer") or {}
    oferta = None
    if of:
        oferta = {"price": of.get("price"), "price_with_discount": of.get("priceWithDiscount"),
                  "starts_at": of.get("startsAt"), "ends_at": of.get("endsAt"),
                  "quantity_available": of.get("quantityAvailable"), "name": of.get("name"),
                  "is_prime_exclusive": of.get("isPrimeExclusive")}
    return {"title": it.get("name"), "available": it.get("available", True), "price": it.get("price"),
            "price_with_discount": it.get("priceWithDiscount"), "offer": oferta,
            "max_installment": it.get("maxInstallment"), "is_marketplace": bool(flags.get("isMarketplace")),
            "marketplace": {"seller_name": it.get("sellerName"), "seller_id": it.get("sellerId"),
                            "product_id": it.get("offerIdMarketplace")},
            "is_openbox": bool(flags.get("isOpenbox")), "is_pre_order": bool(flags.get("isPreOrder")),
            "date_pre_order": it.get("preOrderDate"), "description": it.get("description")}


def parse_lista(html: str, fonte: str = "kabum.produtos") -> list[Oferta]:
    """Ofertas de PS5 (e o que mais for do catálogo) da página de lista da KaBuM."""
    nd = next_data(html) or {}
    dados = ((nd.get("props") or {}).get("pageProps") or {}).get("data")
    if isinstance(dados, str):
        try:
            dados = json.loads(dados)
        except ValueError:
            dados = None
    itens = (((dados or {}).get("catalogServer") or {}).get("data")) or []
    out: list[Oferta] = []
    for it in itens:
        if not isinstance(it, dict) or not it.get("code"):
            continue
        o = parse_api({"id": it["code"], "attributes": _atributos_da_lista(it)}, "PS5_DIGITAL", fonte)
        if o and not produtos.eh_tv(o.modelo):
            out.append(o)
    return out


def prazo_cotacao(code: str, vendedor: str, vendedor_id: str, cep: str, oferta_id: int = 0,
                  timeout: int = 20) -> Optional[str]:
    """Data ISO da entrega mais cedo (fora a "Entrega Agendada") da cotação de frete da KaBuM no CEP. Parceiro precisa
    do id da oferta dele (`oferta_id`); a KaBuM (seller_id "0") e o Magalu (1000) aceitam 0."""
    corpo = {"zip_code": cep, "sellers": [{"seller_name": vendedor, "seller_id": str(vendedor_id),
                                           "products": [{"code": int(code), "quantity": 1,
                                                         "offer_id": int(oferta_id or 0)}]}],
             "client": {"id": "", "session": "", "type": "F", "is_prime": False}, "store": 1, "origin": "product"}
    h = dict(HEADERS_JSON)
    h.update({"Content-Type": "application/json", "Origin": "https://www.kabum.com.br",
              "Referer": "https://www.kabum.com.br/"})
    r = requests.post(config.URL_KABUM_FRETE, json=corpo, headers=h, timeout=timeout)
    r.raise_for_status()
    datas = []
    for q in (r.json() or {}).get("quotes") or []:
        for d in q.get("deliveries") or []:
            if str(d.get("type") or "").upper() == "AGENDADO":
                continue
            iso = entrega.data_por_extenso(d.get("arrival_date") or d.get("expected_arrival_date"))
            if iso:
                datas.append(iso)
    return min(datas) if datas else None


def completa_entrega(ofertas: list[Oferta]) -> None:
    """Prazo do GTA 6 físico com o CEP de entrega (uma cotação por anúncio). Anúncio que só envia a partir do lançamento
    (pré-venda com data >= 19/11) já é "chega depois", sem cotar."""
    cep, referencia = entrega.cep()
    for o in ofertas:
        if not entrega.precisa(o.modelo):
            continue
        envio = o.extra.get("envio_a_partir")
        if envio and envio >= produtos.LANCAMENTO_GTA6:
            entrega.marca_envio_tardio(o)
            continue
        vid = o.extra.get("kabum_seller_id") or "0"
        nome = o.vendedor or "KaBuM!"
        try:
            data = prazo_cotacao(o.id, nome, vid, cep, o.extra.get("kabum_oferta_id") or 0)
        except Exception as e:  # noqa: BLE001 - o prazo é extra: a oferta continua sem ele
            print(f"[kabum] cotação de frete de {o.id} falhou: {type(e).__name__}")
            continue
        entrega.marca(o, data, referencia, "cotação de frete")


class KaBuM(Fonte):
    nome = "kabum"

    def coletar(self) -> Resultado:
        """Um pedido por anúncio (3 no total). Anúncio que falha não derruba os outros; todos falhando, a fonte falha."""
        out: list[Oferta] = []
        erros: list[str] = []
        for modelo, ids in config.KABUM_PRODUTOS.items():
            for pid in ids:
                try:
                    o = parse_api(get_json(config.URL_KABUM_API_BASE + pid), modelo)
                except Exception as e:  # noqa: BLE001 - rede/HTTP: registra e segue para o próximo anúncio
                    erros.append(f"{pid}: {type(e).__name__}: {e}"[:160])
                    continue
                if o:
                    out.append(o)
        if erros:
            print("[kabum] " + " | ".join(erros))
            if len(erros) == sum(len(ids) for ids in config.KABUM_PRODUTOS.values()):
                raise RuntimeError(erros[0])
        return out, []


class KaBuMProdutos(Fonte):
    """PS5, GTA 6 e leitor na KaBuM: a lista de consoles (1 pedido), a API dos anúncios do catálogo que a lista não
    trouxe (GTA 6, leitor, kit) e a cotação de frete do GTA 6."""

    nome = "kabum.produtos"

    def coletar(self) -> Resultado:
        por_id: dict[str, Oferta] = {}
        erros: list[str] = []
        try:
            for o in parse_lista(get_html(config.URL_KABUM_LISTA_CONSOLES), self.nome):
                por_id.setdefault(o.id, o)
        except Exception as e:  # noqa: BLE001
            erros.append(f"lista: {type(e).__name__}: {str(e)[:120]}")
        for pid, esperado in produtos.ids_da_loja("KaBuM!", config._NAO_TV).items():
            if not pid.isdigit() or pid in por_id:
                continue
            try:
                o = parse_api(get_json(config.URL_KABUM_API_BASE + pid), esperado, self.nome)
            except Exception as e:  # noqa: BLE001
                erros.append(f"{pid}: {type(e).__name__}: {str(e)[:100]}")
                continue
            if o:
                por_id.setdefault(o.id, o)
        ofertas = list(por_id.values())
        completa_entrega(ofertas)
        if erros:
            print("[kabum.produtos] " + " | ".join(erros))
        if not ofertas and erros:
            raise RuntimeError(erros[0])
        return ofertas, []
