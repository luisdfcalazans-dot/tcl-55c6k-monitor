"""Netshoes (grupo Magalu): PS5, GTA 6 e leitor, no Chrome do PC (por HTTP simples dá 403 do Akamai).

Vende o estoque do próprio Magalu (vendedor "Magalu Oficial", sellerId 29198) com 10% no Pix (pesquisa de 03/10/2026).
Uma página por rodada (config.URL_NETSHOES_BUSCA, a busca "playstation 5", que traz os consoles, o GTA 6 e o leitor)
e, de dentro dela, as APIs da própria loja (o navegador manda os cookies e o sensor do Akamai; nenhuma outra página):
- preço: /frdmprcsts/<código>/alternative/lazy?state=<UF> -> vendedor, salePrice (Pix, em centavos),
  finalPriceWithoutPaymentBenefitDiscount (cartão), installment (parcelas sem juros), preSale, peso e medidas;
- prazo do GTA 6: /pdp-api/api/shipping/calculate?...&zipCode=<CEP> (os mesmos parâmetros que a página usa) ->
  minDeliveryDate/maxDeliveryDate. O CEP vem de config.cep_entrega() e nunca é impresso.
Os cartões da busca vêm sem preço (o preço carrega depois, por API): o título e o tipo saem dos atributos do link
(data-name, data-producttype). Códigos do catálogo que a busca não trouxe (o Pro, outras versões) também são
consultados (sem oferta, ficam de fora).
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from .. import config, produtos
from ..models import Oferta
from ..util import fmt_preco
from . import Fonte, Pular, Resultado, entrega

BASE = "https://www.netshoes.com.br"
_RE_CODIGO = re.compile(r"-([A-Z0-9]{3}-[A-Z0-9]{4}-[A-Z0-9]{3})$")

JS_PRECOS = """async ({codigos, uf}) => {
  const out = {};
  for (const c of codigos) {
    try {
      const r = await fetch(`/frdmprcsts/${c}/alternative/lazy?state=${uf}`, {credentials: 'include'});
      out[c] = r.ok ? await r.json() : {erro: r.status};
    } catch (e) { out[c] = {erro: String(e).slice(0, 80)}; }
  }
  return out;
}"""

JS_GET = """async (url) => {
  try {
    const r = await fetch(url, {credentials: 'include'});
    return r.ok ? await r.json() : {erro: r.status};
  } catch (e) { return {erro: String(e).slice(0, 80)}; }
}"""


def bloqueio(html: str, texto: str) -> bool:
    return "Access Denied" in (html or "")[:3000] or "Reference #" in (texto or "")[:500]


def parse_busca(html: str) -> list[dict]:
    """Cartões da busca: {codigo, titulo, url, tipo} (o preço vem depois, pela API de preço)."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, dict] = {}
    for card in soup.select("div.card[data-code]"):
        a = card.select_one("a[href*='/p/']")
        cod = (card.get("data-code") or "").strip()
        if not a or not cod or cod in out:
            continue
        titulo = (a.get("data-name") or card.get_text(" ", strip=True) or "").strip()
        out[cod] = {"codigo": cod, "titulo": titulo, "url": BASE + (a.get("href") or "").split("?")[0],
                    "tipo": (a.get("data-producttype") or "").strip()}
    return list(out.values())


def _reais(centavos: Any) -> Optional[float]:
    try:
        v = float(centavos) / 100
    except (TypeError, ValueError):
        return None
    return round(v, 2) if v > 0 else None


def oferta_do_preco(cartao: dict, preco: dict) -> Optional[Oferta]:
    """Oferta de um cartão (código, título, url) com a resposta da API de preço; None sem oferta/preço."""
    if not isinstance(preco, dict) or preco.get("erro") or not preco.get("sellerId"):
        return None
    c = produtos.classifica(cartao["titulo"], "Netshoes", id_loja=cartao["codigo"])
    if not c.produto or produtos.eh_tv(c.produto):
        return None
    pix = _reais(preco.get("salePrice"))
    cheio = _reais(preco.get("finalPriceWithoutPaymentBenefitDiscount")) or _reais(preco.get("listPrice"))
    if not (pix or cheio):
        return None
    if str(preco.get("paymentMethod") or "").upper() != "PIX" or (pix and cheio and pix >= cheio):
        cartao_preco, pix = (cheio or pix), None
    else:
        cartao_preco = cheio
    parc = preco.get("installment") or {}
    n = parc.get("numberOfInstallments") or 0
    parcelado = None
    if isinstance(n, int) and n > 1 and cartao_preco and abs((_reais(parc.get("fullAmountInCents")) or 0) - cartao_preco) < 1:
        parcelado = f"{n}x {fmt_preco(_reais(parc.get('amountInCents')))} sem juros"
    extra = {"anuncio": cartao["codigo"], "sku": preco.get("sku"), "vendedor_id": str(preco.get("sellerId")),
             "preco_de": _reais(preco.get("listPrice")), "pre_venda": bool(preco.get("preSale")),
             "_frete": {"peso": preco.get("weightInGrams"), "altura": preco.get("heightInCm"),
                        "largura": preco.get("widthInCm"), "profundidade": preco.get("depthInCm"),
                        "lista": preco.get("listPrice"), "cheio": preco.get("finalPriceWithoutPaymentBenefitDiscount"),
                        "tipo": cartao.get("tipo") or ""}}
    if c.detalhes:
        extra["produto"] = dict(c.detalhes)
    return Oferta(fonte="netshoes", tipo="loja", loja="Netshoes", titulo=cartao["titulo"], url=cartao["url"],
                  id=f"{cartao['codigo']}-{preco.get('sellerId')}", preco=cartao_preco, preco_pix=pix,
                  parcelado=parcelado, vendedor=str(preco.get("sellerName") or "") or None, extra=extra,
                  modelo=c.produto)


def url_frete(o: Oferta, cep: str) -> Optional[str]:
    """A URL da cotação de frete da página do produto (os mesmos parâmetros que a Netshoes usa) para este CEP."""
    f = o.extra.get("_frete") or {}
    if not o.extra.get("sku") or not o.extra.get("vendedor_id"):
        return None
    tipo = quote(str(f.get("tipo") or "Jogos para Consoles").replace(" ", "+"))
    return (f"/pdp-api/api/shipping/calculate?sku={quote(str(o.extra['sku']))}&preSale="
            f"{'true' if o.extra.get('pre_venda') else 'false'}&hasPersona=false&department=Games&productType={tipo}"
            f"&headerType=PDP_MANUAL&sellerId={o.extra['vendedor_id']}&skuPrice={int(f.get('lista') or 0)}"
            f"&weight={int(f.get('peso') or 0)}&height={int(f.get('altura') or 0)}&width={int(f.get('largura') or 0)}"
            f"&depth={int(f.get('profundidade') or 0)}&priceWithDiscounts={int(f.get('cheio') or 0)}&zipCode={cep}")


def data_do_frete(resposta: Any) -> Optional[str]:
    """A data de entrega (ISO) da resposta da cotação: o maior maxDeliveryDate da opção mais rápida."""
    if not isinstance(resposta, dict):
        return None
    datas = []
    for opcoes in resposta.values():
        for op in opcoes if isinstance(opcoes, list) else []:
            if isinstance(op, dict):
                d = str(op.get("maxDeliveryDate") or op.get("minDeliveryDate") or "")[:10]
                if re.match(r"\d{4}-\d\d-\d\d$", d):
                    datas.append(d)
    return min(datas) if datas else None


MARCA_BLOQUEIO = config.RAIZ / "logs" / "netshoes_bloqueado_em"   # existe enquanto a Netshoes estiver bloqueando
ESPERA_BLOQUEIO_S = 2 * 3600


class Netshoes(Fonte):
    """Melhor esforço: o Akamai da Netshoes recusou o Chrome automatizado de um perfil novo na checagem de 03/10 (a
    mesma página abre num navegador comum). Bloqueio = espera de 2 h (logs/netshoes_bloqueado_em), sem aviso de falha:
    a Netshoes também chega pelas postagens (Promobit, Pelando, Telegram)."""

    nome = "netshoes"
    modo = "pc"
    alerta_falha = False

    def coletar(self) -> Resultado:
        import time as _t

        from .playwright_sources import _abrir, _avaliar, sessao

        if MARCA_BLOQUEIO.exists():
            restante = ESPERA_BLOQUEIO_S - (_t.time() - MARCA_BLOQUEIO.stat().st_mtime)
            if restante > 0:
                raise Pular(f"a Netshoes bloqueou há pouco; nova tentativa em {restante / 60:.0f} min")

        def marca_bloqueio(motivo: str) -> RuntimeError:
            MARCA_BLOQUEIO.parent.mkdir(exist_ok=True)
            MARCA_BLOQUEIO.write_text(_t.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
            return RuntimeError(f"Netshoes bloqueou (Akamai): {motivo}; nova tentativa em 2 h")

        cep, referencia = entrega.cep()
        uf = entrega.uf_do_cep(cep)
        with sessao("default"):
            html, texto, _ = _abrir(config.URL_NETSHOES_BUSCA, esperar="div.card[data-code]", ocioso_ms=6000)
            if bloqueio(html, texto):
                raise marca_bloqueio("busca")
            cartoes = {c["codigo"]: c for c in parse_busca(html)}
            # os do catálogo que a busca não trouxe (o título vem do catálogo)
            for cod, pid in produtos.ids_da_loja("Netshoes", config._NAO_TV).items():
                cartoes.setdefault(cod, {"codigo": cod, "titulo": produtos.nome(pid), "url": f"{BASE}/p/{cod}",
                                         "tipo": ""})
            escolhidos = [c for c in cartoes.values()
                          if (produtos.classifica(c["titulo"], "Netshoes", id_loja=c["codigo"]).produto or "TV")
                          not in produtos.TVS + ("TV",)]
            escolhidos = escolhidos[:config.NETSHOES_MAX_PRECOS]
            precos = _avaliar(JS_PRECOS, {"codigos": [c["codigo"] for c in escolhidos], "uf": uf}) or {}
            if precos and all(isinstance(v, dict) and v.get("erro") == 403 for v in precos.values()):
                raise marca_bloqueio("consulta de preço")
            ofertas = [o for o in (oferta_do_preco(c, precos.get(c["codigo"])) for c in escolhidos) if o]
            for o in ofertas:
                if not entrega.precisa(o.modelo):
                    continue
                u = url_frete(o, cep)
                if not u:
                    continue
                try:
                    data = data_do_frete(_avaliar(JS_GET, u))
                except Exception as e:  # noqa: BLE001 - o prazo é extra
                    print(f"[netshoes] cotação de frete de {o.id} falhou: {type(e).__name__}")
                    continue
                entrega.marca(o, data, referencia, "cotação de frete")
        MARCA_BLOQUEIO.unlink(missing_ok=True)
        for o in ofertas:
            o.extra.pop("_frete", None)
        sem_oferta = len(escolhidos) - len(ofertas)
        print(f"[netshoes] {len(cartoes)} cartões, {len(ofertas)} ofertas"
              + (f" ({sem_oferta} sem oferta agora)" if sem_oferta else ""))
        return ofertas, []
