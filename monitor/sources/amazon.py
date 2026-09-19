"""Amazon.com.br: todos os vendedores da 55C6K (só leitura; a Amazon é "somente leitura" também no carrinho).

Descoberta (19/09/2026), até config.AMAZON_MAX_CARGAS páginas por rodada:
1. a página do produto (HTTP): vendedor do destaque com cartão, Pix e parcelado completos;
2. o painel "Outras opções de compra" (aodAjaxMain) do ASIN principal, no Chrome (por HTTP deu 503
   em 2 de 3 tentativas): um vendedor por bloco (preço, Pix quando aparece, nome e id do vendedor);
3. no Chrome: a página do produto, se o HTTP veio sem preço; senão a busca (por HTTP dá 503), para
   outros ASINs da 55C6K.
Uma Oferta por ASIN+vendedor, id "<ASIN>-<id do vendedor>" e URL /dp/<ASIN>?smid=<id do vendedor>.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import config
from ..filtro import eh_55c6k
from ..models import Oferta
from ..util import get_html, parcelado_no_texto, parse_preco
from . import Fonte, Pular, Resultado

_RE_CARTAO = re.compile(
    r"R\$\s?([\d.]+,\d{2})\s+em\s+at[ée]\s+(\d{1,2})x\s+de\s+R\$\s?([\d.]+,\d{2})(\s+sem\s+juros)?", re.I)
_RE_SELLER = re.compile(r"[?&]seller=([A-Z0-9]{6,20})")
_RE_ASIN = re.compile(r"/dp/([A-Z0-9]{10})")


def separa_pix_cartao(destaque: float | None, txt_pagamento_unico: str, txt_melhor_oferta: str):
    """Layout da Amazon desde 18/09/2026: o número grande é o preço do Pix/NuPay ("à vista no Pix ou NuPay
    (10% off)", em #oneTimePaymentPrice_feature_div) e o do cartão vem em #best-offer-string-cc
    ("ou R$ 3.749,00 em até 12x de R$ 312,49 sem juros"). Sem a frase do Pix, o destaque é o preço do cartão.
    Devolve (preco_cartao, preco_pix, parcelado); parcelado None quando a frase não aparece."""
    m = _RE_CARTAO.search((txt_melhor_oferta or "").replace("\xa0", " "))
    cartao = parse_preco(m.group(1)) if m else None
    parcelado = f"{m.group(2)}x R$ {m.group(3)}{' sem juros' if m.group(4) else ''}" if m else None
    eh_pix = "pix" in (txt_pagamento_unico or "").lower()
    if not eh_pix:
        return destaque, None, parcelado
    if destaque is None:
        return cartao, None, parcelado
    if cartao and cartao >= destaque:
        return cartao, destaque, parcelado
    # só sabemos o do Pix: o do cartão fica vazio (nunca repetir o do Pix como se fosse cartão)
    return None, destaque, None


def url_vendedor(asin: str, vendedor_id: str | None) -> str:
    """Página do anúncio com a oferta deste vendedor em destaque (smid=<id>)."""
    base = f"https://www.amazon.com.br/dp/{asin}"
    return f"{base}?smid={vendedor_id}" if vendedor_id else base


def _id_oferta(asin: str, vendedor_id: str | None, vendedor: str | None) -> str:
    chave = vendedor_id or re.sub(r"[^a-z0-9]+", "", (vendedor or "").lower()) or "destaque"
    return f"{asin}-{chave}"


def _preco_do_bloco(el) -> float | None:
    """Preço de um .a-price: o texto de .a-offscreen ou, quando ele vem vazio (painel de ofertas),
    inteiro + centavos (.a-price-whole / .a-price-fraction)."""
    if el is None:
        return None
    off = el.select_one(".a-offscreen")
    p = parse_preco(off.get_text(strip=True)) if off else None
    if p:
        return p
    w, f = el.select_one(".a-price-whole"), el.select_one(".a-price-fraction")
    if not w:
        return None
    inteiro = re.sub(r"[^\d.]", "", w.get_text(strip=True))
    return parse_preco(inteiro + ("," + re.sub(r"\D", "", f.get_text(strip=True)) if f else ""))


def _mesmo_vendedor(a: str | None, b: str | None) -> bool:
    """'Magalu.' == 'Vendido por Magalu.' (a página e o painel escrevem o nome de jeitos diferentes)."""
    na = re.sub(r"[^a-z0-9]+", "", (a or "").lower())
    nb = re.sub(r"[^a-z0-9]+", "", (b or "").lower())
    return bool(na and nb) and (na in nb or nb in na)


def _extra(asin: str, vendedor_id: str | None, **mais) -> dict:
    return {"anuncio": asin, "asin": asin, "vendedor_id": vendedor_id, **mais}


def parse_produto(html: str, asin: str = config.ASIN_AMAZON) -> Oferta | None:
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
    mid = soup.select_one("#merchantID")
    vendedor_id = (mid.get("value") or "").strip() or None if mid else None
    if not vendedor_id:
        link = soup.select_one("#sellerProfileTriggerId")
        ms = _RE_SELLER.search(link.get("href") or "") if link else None
        vendedor_id = ms.group(1) if ms else None
    if not preco:
        return None if not ativo else Oferta(
            fonte="amazon", tipo="loja", loja="Amazon", titulo=titulo, url=url_vendedor(asin, vendedor_id),
            id=_id_oferta(asin, vendedor_id, None), ativo=False, extra=_extra(asin, vendedor_id))
    vendedor = None
    mi = soup.select_one("#merchant-info, #sellerProfileTriggerId")
    if mi:
        vendedor = mi.get_text(" ", strip=True)[:60]
    unico = soup.select_one("#oneTimePaymentPrice_feature_div")
    melhor = soup.select_one("#best-offer-string-cc")
    cartao, pix, parcelado = separa_pix_cartao(
        preco, unico.get_text(" ", strip=True) if unico else "", melhor.get_text(" ", strip=True) if melhor else "")
    if parcelado is None and not pix:
        parcelado = parcelado_no_texto(soup.get_text(" ", strip=True))
    return Oferta(
        fonte="amazon", tipo="loja", loja="Amazon", titulo=titulo, url=url_vendedor(asin, vendedor_id),
        id=_id_oferta(asin, vendedor_id, vendedor),
        preco=cartao, preco_pix=pix, parcelado=parcelado, ativo=ativo, vendedor=vendedor,
        extra=_extra(asin, vendedor_id, disponibilidade=disp_txt[:80], destaque=True),
    )


def parse_ofertas(html: str, asin: str, titulo: str = "") -> list[Oferta]:
    """Um vendedor por bloco do painel de ofertas (#aod-pinned-offer e cada #aod-offer), só "Novo".

    O preço do bloco é o que o vendedor cobra; com a frase "à vista no Pix" ele é o do Pix e o do
    cartão fica vazio (a página do produto, com smid, completa). Sem a frase, é o preço de todos os meios.
    """
    if "api-services-support@amazon.com" in html or "Digite os caracteres" in html:
        raise RuntimeError("Amazon devolveu captcha")
    soup = BeautifulSoup(html, "html.parser")
    if not titulo:
        t = soup.select_one("#aod-asin-title-text, #aod-asin-title h5")
        titulo = t.get_text(" ", strip=True) if t else ""
    out: dict[str, Oferta] = {}
    for b in soup.select("#aod-pinned-offer, #aod-offer"):
        cab = b.select_one("#aod-offer-heading")
        if cab and "novo" not in cab.get_text(" ", strip=True).lower():
            continue  # usado/recondicionado
        preco = _preco_do_bloco(b.select_one("[id^=aod-price-] .a-price:not(.a-text-price)")
                                or b.select_one(".a-price:not(.a-text-price)"))
        if not preco:
            continue
        sb = b.select_one("#aod-offer-soldBy")
        link = sb.select_one("a[href*='seller=']") if sb else None
        vendedor_id = None
        if link:
            ms = _RE_SELLER.search(link.get("href") or "")
            vendedor_id = ms.group(1) if ms else None
            vendedor = link.get_text(" ", strip=True)
        else:
            txt = sb.get_text(" ", strip=True) if sb else ""
            vendedor = re.sub(r"^\s*Vendido por\s*", "", txt).strip()[:60] or None
        pix = any("pix" in s.lower() and ("vista" in s.lower() or "no pix" in s.lower())
                  for s in b.find_all(string=True) if s and "pix" in s.lower())
        o = Oferta(
            fonte="amazon", tipo="loja", loja="Amazon", titulo=titulo or f"TCL 55C6K ({asin})",
            url=url_vendedor(asin, vendedor_id), id=_id_oferta(asin, vendedor_id, vendedor),
            preco=None if pix else preco, preco_pix=preco if pix else None, vendedor=vendedor,
            extra=_extra(asin, vendedor_id, destaque=b.get("id") == "aod-pinned-offer"),
        )
        out.setdefault(o.id, o)
    return list(out.values())


def parse_busca(html: str) -> list[Oferta]:
    """Cartões da busca: um por ASIN da 55C6K (vendedor do destaque não aparece no cartão)."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Oferta] = {}
    for c in soup.select("div[data-component-type='s-search-result'][data-asin]"):
        asin = (c.get("data-asin") or "").strip()
        h2 = c.select_one("h2")
        titulo = h2.get_text(" ", strip=True) if h2 else ""
        if not asin or asin in out or not eh_55c6k(titulo):
            continue
        preco = _preco_do_bloco(c.select_one(".a-price:not(.a-text-price)"))
        if not preco:
            continue
        txt = re.sub(r"[\s|]+", " ", c.get_text(" ", strip=True).replace("\xa0", " "))
        pix = "vista no pix" in txt.lower()
        parc = None
        # "em até 12x de R$ 312,41 R$312,41 sem juros" (o valor vem duas vezes: visível e para leitor de tela)
        mp = re.search(r"em at[ée] (\d{1,2})x de R\$ ?([\d.]+,\d{2})(?: R\$ ?[\d.]+,\d{2})?( sem juros)?", txt, re.I)
        if mp and mp.group(3):
            parc = f"{mp.group(1)}x R$ {mp.group(2)} sem juros"
        out[asin] = Oferta(
            fonte="amazon", tipo="loja", loja="Amazon", titulo=titulo, url=url_vendedor(asin, None),
            id=_id_oferta(asin, None, None), preco=None if pix else preco, preco_pix=preco if pix else None,
            parcelado=parc, extra=_extra(asin, None, origem="busca"),
        )
    return list(out.values())


class Amazon(Fonte):
    nome = "amazon"
    modo = "pc"

    def coletar(self) -> Resultado:
        """Até config.AMAZON_MAX_CARGAS cargas: 1) página do produto por HTTP; 2) painel de ofertas no
        Chrome; 3) no Chrome, a página do produto se o HTTP veio sem preço, senão a busca por outros ASINs."""
        from .playwright_sources import _abrir, sessao

        asin = config.ASIN_AMAZON
        url_dp = f"https://www.amazon.com.br/dp/{asin}"
        url_aod = config.URL_AMAZON_OFERTAS.format(asin=asin)
        cargas = 0
        por_id: dict[str, Oferta] = {}
        erros: list[str] = []

        def http(url: str, rotulo: str) -> str | None:
            nonlocal cargas
            cargas += 1
            try:
                return get_html(url, tentativas=1)
            except Exception as e:  # noqa: BLE001 - 503 da Amazon para robô, rede
                erros.append(f"{rotulo} (HTTP): {type(e).__name__}: {e}"[:160])
                return None

        def chrome(url: str, esperar: str, rotulo: str) -> str | None:
            nonlocal cargas
            cargas += 1
            try:
                return _abrir(url, esperar=esperar, ocioso_ms=8000)[0]
            except Pular:
                raise
            except Exception as e:  # noqa: BLE001
                erros.append(f"{rotulo} (Chrome): {type(e).__name__}: {e}"[:160])
                return None

        def le_ofertas(html: str | None) -> bool:
            if not html:
                return False
            try:
                ofs = parse_ofertas(html, asin)
            except RuntimeError as e:  # captcha
                erros.append(f"ofertas: {e}")
                return False
            for o in ofs:
                por_id.setdefault(o.id, o)
            return bool(ofs)

        def le_produto(html: str | None) -> Oferta | None:
            if not html:
                return None
            try:
                o = parse_produto(html, asin)
            except RuntimeError as e:  # captcha
                erros.append(f"produto: {e}")
                return None
            return o

        with sessao("default"):
            dest = le_produto(http(url_dp, "produto"))
            # o painel por HTTP deu 503 em 2 de 3 tentativas em 19/09: no Chrome ele vem sempre
            le_ofertas(chrome(url_aod, "#aod-offer, #aod-pinned-offer", "ofertas"))
            if cargas < config.AMAZON_MAX_CARGAS:
                if dest is None or not (dest.preco or dest.preco_pix):
                    # a Amazon às vezes entrega a página sem o bloco de preço para clientes sem cookies
                    # (anúncio indisponível continua valendo: ativo=False, sem preço)
                    dest = le_produto(chrome(url_dp, "#productTitle", "produto")) or dest
                else:
                    html = chrome(config.URL_AMAZON_BUSCA, "div[data-component-type='s-search-result']", "busca")
                    for o in parse_busca(html or ""):
                        if o.extra["asin"] != asin:
                            por_id.setdefault(o.id, o)
            if dest is not None:
                self._junta_destaque(dest, por_id, asin)
        if erros:
            print("[amazon] " + " | ".join(erros))
        if not por_id and erros:
            raise RuntimeError(erros[0])
        return list(por_id.values()), []

    @staticmethod
    def _junta_destaque(dest: Oferta, por_id: dict[str, Oferta], asin: str) -> None:
        """A página do produto tem os dados completos (cartão, Pix, parcelado) do vendedor em destaque:
        ela substitui o bloco desse vendedor no painel, com o id do vendedor do painel se a página não
        trouxe o dela (evita duas linhas para o mesmo vendedor)."""
        vid = dest.extra.get("vendedor_id")
        iguais = [o for o in por_id.values()
                  if (vid and o.extra.get("vendedor_id") == vid) or _mesmo_vendedor(o.vendedor, dest.vendedor)]
        if not iguais and not vid and not dest.vendedor:
            iguais = [o for o in por_id.values() if o.extra.get("destaque")]
        if not vid:
            vid = next((o.extra["vendedor_id"] for o in iguais if o.extra.get("vendedor_id")), None)
            if vid:
                dest.id, dest.url = _id_oferta(asin, vid, None), url_vendedor(asin, vid)
                dest.extra["vendedor_id"] = vid
        for o in iguais:
            por_id.pop(o.id, None)
        if not dest.vendedor and iguais:
            dest.vendedor = iguais[0].vendedor
        por_id[dest.id] = dest
