"""Amazon.com.br: todos os vendedores da 55C6K e da 65C6K (só leitura; a Amazon é "somente leitura" também no carrinho).

Descoberta (19/09/2026), por modelo (config.ASINS_AMAZON: 55C6K B0F7JZMVKF, 65C6K B0F7K7B2PD), até
config.AMAZON_MAX_CARGAS páginas por modelo e rodada:
1. a página do produto (HTTP): vendedor do destaque com cartão, Pix e parcelado completos;
2. o painel "Outras opções de compra" (aodAjaxMain) do ASIN principal, no Chrome (por HTTP deu 503
   em 2 de 3 tentativas): um vendedor por bloco (preço, Pix quando aparece, nome e id do vendedor);
3. no Chrome: a página do produto, se o HTTP veio sem preço; senão a busca (por HTTP dá 503), para
   outros ASINs do modelo.
Uma Oferta por ASIN+vendedor, id "<ASIN>-<id do vendedor>" e URL /dp/<ASIN>?smid=<id do vendedor>.
Na 65C6K o destaque é a própria Amazon (26/09): o bloco fixado do painel não tem link seller=, e o id do vendedor vem
do merchantID (da página, ou do campo escondido do bloco); "Amazon.com.br" sem id é a própria Amazon (A1ZZFT5FULY4LN).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import config, produtos
from ..filtro import modelo_do_titulo
from ..models import MODELO_PADRAO, Oferta
from ..util import get_html, parcelado_no_texto, parse_preco
from . import Fonte, Pular, Resultado, entrega

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


def modelo_do_asin(asin: str) -> str:
    """O modelo de um ASIN fixo (config.ASINS_AMAZON); ASIN desconhecido: 55C6K."""
    return next((m for m, a in config.ASINS_AMAZON.items() if a == asin), MODELO_PADRAO)


def _e_a_amazon(nome: str | None) -> bool:
    """'Amazon.com.br', 'Vendido por Amazon.com.br', 'Amazon.com.br Política de devolução': a própria Amazon."""
    n = re.sub(r"[^a-z0-9]+", "", (nome or "").lower())
    n = re.sub(r"^(?:enviadodeevendidopor|enviadoevendidopor|vendidopor)", "", n)
    return n.startswith("amazoncombr")


def parse_produto(html: str, asin: str = config.ASIN_AMAZON, modelo: str | None = None) -> Oferta | None:
    """Oferta do vendedor em destaque na página do produto. TV: o título tem de ser do modelo do ASIN (ou `modelo`).
    PS5/GTA 6 (`modelo` de fora das TVs): o produto do classificador do catálogo com o ASIN; e o prazo de entrega da
    página (data-csa-c-delivery-time, no CEP da sessão) vai para extra['entrega_texto']."""
    if "api-services-support@amazon.com" in html or "Digite os caracteres" in html:
        raise RuntimeError("Amazon devolveu captcha")
    modelo = modelo or modelo_do_asin(asin)
    soup = BeautifulSoup(html, "html.parser")
    titulo_el = soup.select_one("#productTitle")
    titulo = titulo_el.get_text(" ", strip=True) if titulo_el else ""
    detalhes: dict = {}
    if not produtos.eh_tv(modelo):
        c = produtos.classifica(titulo, "Amazon", id_loja=asin)
        if not c.produto or produtos.eh_tv(c.produto):
            return None
        modelo, detalhes = c.produto, dict(c.detalhes)
    elif modelo_do_titulo(titulo) != modelo:
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
            id=_id_oferta(asin, vendedor_id, None), ativo=False, extra=_extra(asin, vendedor_id), modelo=modelo)
    vendedor = None
    mi = soup.select_one("#merchant-info, #sellerProfileTriggerId")
    if mi:
        vendedor = mi.get_text(" ", strip=True)[:60]
    if not vendedor and vendedor_id == config.AMAZON_1P_ID:
        # a própria Amazon no destaque (65C6K, 26/09): a página não tem o link do perfil do vendedor, só o merchantID
        vendedor = "Amazon.com.br"
    unico = soup.select_one("#oneTimePaymentPrice_feature_div")
    melhor = soup.select_one("#best-offer-string-cc")
    cartao, pix, parcelado = separa_pix_cartao(
        preco, unico.get_text(" ", strip=True) if unico else "", melhor.get_text(" ", strip=True) if melhor else "")
    if parcelado is None and not pix:
        parcelado = parcelado_no_texto(soup.get_text(" ", strip=True))
    extra = _extra(asin, vendedor_id, disponibilidade=disp_txt[:80], destaque=True)
    if not produtos.eh_tv(modelo):
        if detalhes:
            extra["produto"] = detalhes
        prazo = soup.select_one("[data-csa-c-delivery-time]")
        if prazo is not None and prazo.get("data-csa-c-delivery-time"):
            extra["entrega_texto"] = str(prazo.get("data-csa-c-delivery-time"))[:60]
    return Oferta(
        fonte="amazon", tipo="loja", loja="Amazon", titulo=titulo, url=url_vendedor(asin, vendedor_id),
        id=_id_oferta(asin, vendedor_id, vendedor),
        preco=cartao, preco_pix=pix, parcelado=parcelado, ativo=ativo, vendedor=vendedor,
        extra=extra, modelo=modelo,
    )


def parse_ofertas(html: str, asin: str, titulo: str = "", modelo: str | None = None) -> list[Oferta]:
    """Um vendedor por bloco do painel de ofertas (#aod-pinned-offer e cada #aod-offer), só "Novo".

    O preço do bloco é o que o vendedor cobra; com a frase "à vista no Pix" ele é o do Pix e o do
    cartão fica vazio (a página do produto, com smid, completa). Sem a frase, é o preço de todos os meios.
    O painel é o do ASIN: o modelo é o dele (ou `modelo`).
    """
    if "api-services-support@amazon.com" in html or "Digite os caracteres" in html:
        raise RuntimeError("Amazon devolveu captcha")
    modelo = modelo or modelo_do_asin(asin)
    soup = BeautifulSoup(html, "html.parser")
    t = soup.select_one("#aod-asin-title-text, #aod-asin-title h5")
    titulo_painel = t.get_text(" ", strip=True) if t else ""
    if titulo_painel and modelo_do_titulo(titulo_painel) not in (None, modelo):
        # o painel é de outro modelo (outro ASIN): as ofertas dele não são desta TV
        print(f"[amazon] o painel de ofertas pedido para a {modelo} ({asin}) é de outro modelo: "
              f"{titulo_painel[:60]!r} — ignorado")
        return []
    titulo = titulo or titulo_painel
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
            # bloco sem link seller= (o da própria Amazon: ela não tem página de vendedor): o id vem do campo escondido
            # merchantID do bloco ou, sem ele, "Vendido por Amazon.com.br" é a própria Amazon
            mid = b.select_one("input[name='merchantID'], input#merchantID")
            vendedor_id = ((mid.get("value") or "").strip() or None) if mid else None
            if not vendedor_id and _e_a_amazon(vendedor):
                vendedor_id = config.AMAZON_1P_ID
        pix = any("pix" in s.lower() and ("vista" in s.lower() or "no pix" in s.lower())
                  for s in b.find_all(string=True) if s and "pix" in s.lower())
        mais = {"destaque": b.get("id") == "aod-pinned-offer"}
        ficha = _ficha_do_bloco(b)
        if ficha:
            mais["ficha"] = ficha
        o = Oferta(
            fonte="amazon", tipo="loja", loja="Amazon", titulo=titulo or f"TCL {modelo} ({asin})",
            url=url_vendedor(asin, vendedor_id), id=_id_oferta(asin, vendedor_id, vendedor),
            preco=None if pix else preco, preco_pix=preco if pix else None, vendedor=vendedor,
            extra=_extra(asin, vendedor_id, **mais), modelo=modelo,
        )
        out.setdefault(o.id, o)
    return list(out.values())


_RE_AVALIACOES_VENDEDOR = re.compile(r"\((\d{1,3}(?:\.\d{3})*|\d+)\s+avalia", re.I)
_RE_POSITIVAS = re.compile(r"(\d{1,3})\s*%\s+positiv", re.I)
_RE_ENVIADO = re.compile(r"^\s*Enviado\s+(?:pela|pelo|por)\s+", re.I)


def _ficha_do_bloco(b) -> dict:
    """Do bloco do painel de ofertas: avaliações do vendedor e quem envia ("Enviado pela Amazon" = Full), para a
    checagem de confiança de vendedor desconhecido (monitor/confianca.py). Nada de requisição extra: a página do
    vendedor (sp?seller=) e a vitrine (s?me=) dão 503 por HTTP."""
    f: dict = {}
    r = b.select_one("#aod-offer-seller-rating")
    txt = r.get_text(" ", strip=True) if r else ""
    m = _RE_AVALIACOES_VENDEDOR.search(txt)
    if m:
        f["avaliacoes_vendedor"] = int(m.group(1).replace(".", ""))
    m = _RE_POSITIVAS.search(txt)
    if m:
        f["positivas_pct"] = int(m.group(1))
    s = b.select_one("#aod-offer-shipsFrom")
    enviado = _RE_ENVIADO.sub("", s.get_text(" ", strip=True)).strip() if s else ""
    if enviado:
        f["enviado_por"] = enviado[:60]
        f["full"] = enviado.lower().startswith("amazon")
    return f


def parse_busca(html: str) -> list[Oferta]:
    """Cartões da busca: um por ASIN da 55C6K ou da 65C6K, com o modelo do título (vendedor do destaque não aparece no
    cartão)."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Oferta] = {}
    for c in soup.select("div[data-component-type='s-search-result'][data-asin]"):
        asin = (c.get("data-asin") or "").strip()
        h2 = c.select_one("h2")
        titulo = h2.get_text(" ", strip=True) if h2 else ""
        modelo = modelo_do_titulo(titulo)
        if not asin or asin in out or not modelo:
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
            parcelado=parc, extra=_extra(asin, None, origem="busca"), modelo=modelo,
        )
    return list(out.values())


_RE_ENTREGA_CARTAO = re.compile(r"\bEntrega\b[^:|]{0,30}:?\s*([^|]{0,40}?\b\d{1,2}\s+de\s+[a-zç]{3,9}\.?)", re.I)
_RE_PARCELA_CARTAO = re.compile(r"em at[ée] (\d{1,2})x de R\$ ?([\d.]+,\d{2})(?: R\$ ?[\d.]+,\d{2})?( sem juros)?", re.I)


def parse_busca_produtos(html: str) -> list[Oferta]:
    """Cartões da busca com um produto do catálogo que não é TV (PS5, pacotes com o GTA 6, o GTA 6, leitor): preço
    (Pix quando o cartão diz "à vista no Pix"; o do cartão é o total das parcelas sem juros), e o prazo de entrega do
    cartão ("Entrega GRÁTIS: seg., 16 de nov.", no CEP da sessão) em extra['entrega_texto']. Acessório, kit de jogo +
    controle, versão "International"/KSA ficam de fora (classificador)."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Oferta] = {}
    for c in soup.select("div[data-component-type='s-search-result'][data-asin]"):
        asin = (c.get("data-asin") or "").strip()
        h2 = c.select_one("h2")
        titulo = h2.get_text(" ", strip=True) if h2 else ""
        if not asin or asin in out or not titulo:
            continue
        cl = produtos.classifica(titulo, "Amazon", id_loja=asin)
        if not cl.produto or produtos.eh_tv(cl.produto):
            continue
        preco = _preco_do_bloco(c.select_one(".a-price:not(.a-text-price)"))
        if not preco:
            continue
        txt = re.sub(r"[\s|]+", " ", c.get_text(" ", strip=True).replace("\xa0", " "))
        pix = "vista no pix" in txt.lower()
        parc, cartao = None, None
        mp = _RE_PARCELA_CARTAO.search(txt)
        if mp and mp.group(3):
            parc = f"{mp.group(1)}x R$ {mp.group(2)} sem juros"
            cartao = round(int(mp.group(1)) * (parse_preco(mp.group(2)) or 0), 2) or None
        extra = _extra(asin, None, origem="busca")
        if cl.detalhes:
            extra["produto"] = dict(cl.detalhes)
        me = _RE_ENTREGA_CARTAO.search(txt)
        if me:
            extra["entrega_texto"] = me.group(1).strip()[:60]
        if pix:
            o_preco, o_pix = (cartao if cartao and cartao > preco + 0.005 else None), preco
        else:
            o_preco, o_pix = preco, None
        out[asin] = Oferta(
            fonte="amazon", tipo="loja", loja="Amazon", titulo=titulo, url=url_vendedor(asin, None),
            id=_id_oferta(asin, None, None), preco=o_preco, preco_pix=o_pix, parcelado=parc, extra=extra,
            modelo=cl.produto,
        )
    return list(out.values())


# CEP da sessão do Chrome (anônima) pela troca de endereço do próprio site (o "Atualizar CEP" do cabeçalho), de dentro
# da página: o token anti-CSRF do modal, depois o address-change. Devolve só se deu certo (o CEP não volta nem é
# impresso). Por HTTP simples a troca dá 503 (pesquisa de 03/10).
JS_CEP = """async ({cep}) => {
  const atual = (document.querySelector('#glow-ingress-line2')?.innerText || '').replace(/\\D/g, '');
  if (atual === cep) return {ok: true, mudou: false};
  const el = document.querySelector('#nav-global-location-data-modal-action');
  if (!el) return {ok: false, erro: 'sem o seletor de CEP'};
  let m;
  try { m = JSON.parse(el.getAttribute('data-a-modal')); } catch (e) { return {ok: false, erro: 'modal ilegível'}; }
  const r1 = await fetch(m.url, {headers: {'anti-csrftoken-a2z': (m.ajaxHeaders || {})['anti-csrftoken-a2z'] || ''},
                                credentials: 'include'});
  const h1 = await r1.text();
  const t = (h1.match(/CSRF_TOKEN\\s*:\\s*["']([^"']+)["']/) || [])[1];
  if (!t) return {ok: false, erro: 'sem token'};
  const r2 = await fetch('/portal-migration/hz/glow/address-change?actionSource=glow', {
    method: 'POST', credentials: 'include',
    headers: {'anti-csrftoken-a2z': t, 'content-type': 'application/json'},
    body: JSON.stringify({locationType: 'LOCATION_INPUT', zipCode: cep, deviceType: 'web', storeContext: 'videogames',
                          pageType: 'Detail', actionSource: 'glow'})});
  let j = {};
  try { j = await r2.json(); } catch (e) {}
  return {ok: !!(j && j.successful), mudou: true};
}"""


def _vendedores_da_busca(achados: dict[str, Oferta], erros: list[str], _abrir) -> int:
    """O cartão da busca não diz quem vende (id '<ASIN>-destaque'): sem o vendedor não há checagem de confiança. Abre o
    painel de ofertas dos ASINs sem vendedor (por HTTP; no Chrome se o HTTP falhar), primeiro o mais barato de cada
    produto e depois os outros, do mais perto da meta ao mais longe, até config.AMAZON_MAX_PAINEIS_PRODUTOS, e troca o
    cartão pelos vendedores do painel (com as avaliações e o Full de cada um). O do destaque (o vendedor do cartão)
    herda do cartão o preço no cartão, o parcelado e o prazo quando o preço é o mesmo. Devolve quantos painéis abriu."""
    def perto_da_meta(o: Oferta) -> float:
        a = produtos.alvos_da_oferta(o)
        meta = a.pix or a.parcelado
        return (o.preco_pix or o.preco) / meta if meta else float("inf")

    sem = [o for o in achados.values() if not o.vendedor and not o.extra.get("vendedor_id") and o.ativo
           and (o.preco_pix or o.preco)]
    sem.sort(key=lambda o: o.preco_pix or o.preco)
    primeiros, resto, vistos = [], [], set()
    for o in sem:
        (resto if o.modelo in vistos else primeiros).append(o)
        vistos.add(o.modelo)
    abertos = 0
    fila = sorted(primeiros, key=perto_da_meta) + sorted(resto, key=perto_da_meta)
    for o in fila[:config.AMAZON_MAX_PAINEIS_PRODUTOS]:
        asin = o.extra.get("asin")
        url = config.URL_AMAZON_OFERTAS.format(asin=asin)
        abertos += 1
        try:
            html = get_html(url, tentativas=1)
        except Exception:  # noqa: BLE001 - o painel por HTTP às vezes dá 503: no Chrome ele vem
            try:
                html = _abrir(url, esperar="#aod-offer, #aod-pinned-offer", ocioso_ms=4000)[0]
            except Pular:
                raise
            except Exception as e:  # noqa: BLE001
                erros.append(f"painel de ofertas {asin}: {type(e).__name__}: {e}"[:160])
                continue
        try:
            painel = parse_ofertas(html or "", asin, titulo=o.titulo, modelo=o.modelo)
        except RuntimeError as e:  # captcha
            erros.append(f"painel de ofertas {asin}: {e}")
            continue
        if not painel:
            continue
        cartao = o.preco_pix or o.preco
        for p in painel:
            if o.extra.get("produto"):
                p.extra["produto"] = dict(o.extra["produto"])
            if p.extra.get("destaque") and abs((p.preco_pix or p.preco or 0) - cartao) <= 0.01:
                if p.preco_pix and not p.preco and o.preco and o.preco > p.preco_pix + 0.005:
                    p.preco = o.preco
                p.parcelado = p.parcelado or o.parcelado
                if o.extra.get("entrega_texto"):
                    p.extra["entrega_texto"] = o.extra["entrega_texto"]
            achados.setdefault(p.id, p)
        achados.pop(o.id, None)
    return abertos


class Amazon(Fonte):
    nome = "amazon"
    modo = "pc"

    def coletar(self) -> Resultado:
        """Por modelo (config.ASINS_AMAZON), até config.AMAZON_MAX_CARGAS cargas: 1) página do produto por HTTP;
        2) painel de ofertas no Chrome; 3) no Chrome, a página do produto se o HTTP veio sem preço, senão a busca por
        outros ASINs do modelo. A mesma janela do Chrome serve aos dois modelos. O PS5/GTA 6 é a fonte AmazonProdutos."""
        from .playwright_sources import _abrir, sessao

        por_id: dict[str, Oferta] = {}
        erros: list[str] = []
        asins_fixos = set(config.ASINS_AMAZON.values())
        with sessao("default"):
            for modelo, asin in config.ASINS_AMAZON.items():
                self._coleta_do_modelo(modelo, asin, asins_fixos, por_id, erros, _abrir)
        if erros:
            print("[amazon] " + " | ".join(erros))
        if not por_id and erros:
            raise RuntimeError(erros[0])
        return list(por_id.values()), []

    def _coleta_do_modelo(self, modelo: str, asin: str, asins_fixos: set[str], por_id: dict[str, Oferta],
                          erros: list[str], _abrir) -> None:
        url_dp = f"https://www.amazon.com.br/dp/{asin}"
        url_aod = config.URL_AMAZON_OFERTAS.format(asin=asin)
        cargas = 0
        rot = "" if modelo == MODELO_PADRAO else f" {modelo}"
        do_modelo: dict[str, Oferta] = {}

        def http(url: str, rotulo: str) -> str | None:
            nonlocal cargas
            cargas += 1
            try:
                return get_html(url, tentativas=1)
            except Exception as e:  # noqa: BLE001 - 503 da Amazon para robô, rede
                erros.append(f"{rotulo}{rot} (HTTP): {type(e).__name__}: {e}"[:160])
                return None

        def chrome(url: str, esperar: str, rotulo: str) -> str | None:
            nonlocal cargas
            cargas += 1
            try:
                return _abrir(url, esperar=esperar, ocioso_ms=8000)[0]
            except Pular:
                raise
            except Exception as e:  # noqa: BLE001
                erros.append(f"{rotulo}{rot} (Chrome): {type(e).__name__}: {e}"[:160])
                return None

        def le_ofertas(html: str | None) -> bool:
            if not html:
                return False
            try:
                ofs = parse_ofertas(html, asin, modelo=modelo)
            except RuntimeError as e:  # captcha
                erros.append(f"ofertas{rot}: {e}")
                return False
            for o in ofs:
                do_modelo.setdefault(o.id, o)
            return bool(ofs)

        def le_produto(html: str | None) -> Oferta | None:
            if not html:
                return None
            try:
                o = parse_produto(html, asin, modelo)
            except RuntimeError as e:  # captcha
                erros.append(f"produto{rot}: {e}")
                return None
            return o

        dest = le_produto(http(url_dp, "produto"))
        # o painel por HTTP deu 503 em 2 de 3 tentativas em 19/09: no Chrome ele vem sempre
        le_ofertas(chrome(url_aod, "#aod-offer, #aod-pinned-offer", "ofertas"))
        if cargas < config.AMAZON_MAX_CARGAS:
            if dest is None or not (dest.preco or dest.preco_pix):
                # a Amazon às vezes entrega a página sem o bloco de preço para clientes sem cookies (na 65C6K, por
                # HTTP, sempre: 26/09) (anúncio indisponível continua valendo: ativo=False, sem preço)
                dest = le_produto(chrome(url_dp, "#productTitle", "produto")) or dest
            else:
                html = chrome(config.URLS_AMAZON_BUSCA.get(modelo, config.URL_AMAZON_BUSCA),
                              "div[data-component-type='s-search-result']", "busca")
                for o in parse_busca(html or ""):
                    # outros ASINs do modelo (os fixos das duas TVs têm a própria coleta)
                    if o.extra["asin"] not in asins_fixos and o.modelo == modelo:
                        do_modelo.setdefault(o.id, o)
        if dest is not None:
            self._junta_destaque(dest, do_modelo, asin)
        for k, o in do_modelo.items():
            por_id.setdefault(k, o)

    @staticmethod
    def _junta_destaque(dest: Oferta, por_id: dict[str, Oferta], asin: str) -> None:
        """A página do produto tem os dados completos (cartão, Pix, parcelado) do vendedor em destaque:
        ela substitui o bloco desse vendedor no painel, com o id do vendedor do painel se a página não
        trouxe o dela (evita duas linhas para o mesmo vendedor).

        Página SEM preço (HTTP e Chrome vieram sem o bloco de preço): ela não diz nada do preço do vendedor. Se o
        painel tem esse vendedor com preço, fica o do painel (senão o vendedor mais barato sumiria do latest)."""
        vid = dest.extra.get("vendedor_id")

        def _e_o_mesmo(o: Oferta) -> bool:
            """A oferta do painel é DESTE vendedor? Com os dois ids conhecidos, quem decide é o id: casar por
            nome (substring) apagaria do painel um vendedor diferente de nome parecido — 'Magalu.' comeria
            'Magalu Shop' (19/09, item B4). Sem id na oferta do painel, o nome é o que há."""
            oid = o.extra.get("vendedor_id")
            if vid and oid:
                return oid == vid
            return _mesmo_vendedor(o.vendedor, dest.vendedor)

        iguais = [o for o in por_id.values() if _e_o_mesmo(o)]
        if not iguais and not vid and not dest.vendedor:
            iguais = [o for o in por_id.values() if o.extra.get("destaque")]
        if not (dest.preco or dest.preco_pix) and any(o.preco or o.preco_pix for o in iguais):
            return
        if not vid:
            vid = next((o.extra["vendedor_id"] for o in iguais if o.extra.get("vendedor_id")), None)
            if vid:
                dest.id, dest.url = _id_oferta(asin, vid, None), url_vendedor(asin, vid)
                dest.extra["vendedor_id"] = vid
        for o in iguais:
            por_id.pop(o.id, None)
        if not dest.vendedor and iguais:
            dest.vendedor = iguais[0].vendedor
        ficha = next((o.extra["ficha"] for o in iguais if o.extra.get("ficha")), None)
        if ficha and not dest.extra.get("ficha"):
            dest.extra["ficha"] = ficha  # avaliações/envio do vendedor só vêm no painel
        por_id[dest.id] = dest


class AmazonProdutos(Fonte):
    """PS5 e GTA 6 na Amazon, no Chrome do PC (fonte própria: as cargas das TVs ficam como antes), até
    config.AMAZON_MAX_CARGAS_PRODUTOS páginas: a do GTA 6 (B0H6KT2RWH: vendedor, cartão, Pix, parcelado e o prazo de
    entrega; antes, o CEP de entrega na sessão, recarregando a página se ele mudou) e as buscas
    (config.URLS_AMAZON_BUSCA_PRODUTOS: os pacotes com o GTA 6 e os consoles, com o prazo do cartão da busca), e o painel
    de ofertas dos ASINs da busca, que dá o vendedor de cada preço (_vendedores_da_busca). O prazo é
    o do CEP da sessão: o de config.cep_entrega() quando a troca deu certo (sem a variável, o de referência), senão
    marcado como aproximado."""

    nome = "amazon.produtos"
    modo = "pc"

    def coletar(self) -> Resultado:
        from .playwright_sources import _abrir, _avaliar, sessao

        por_id: dict[str, Oferta] = {}
        erros: list[str] = []
        cep, referencia = entrega.cep()
        with sessao("default"):
            asin_gta = produtos.produto("GTA6_CODE_IN_BOX").ids_loja["Amazon"][0]
            url_gta = f"https://www.amazon.com.br/dp/{asin_gta}"
            cargas = 0
            html = None
            try:
                cargas += 1
                html = _abrir(url_gta, esperar="#productTitle", ocioso_ms=6000)[0]
                r = _avaliar(JS_CEP, {"cep": cep}) or {}
                cep_ok = bool(r.get("ok"))
                if r.get("mudou") and cep_ok and cargas < config.AMAZON_MAX_CARGAS_PRODUTOS:
                    cargas += 1
                    html = _abrir(url_gta, esperar="#productTitle", ocioso_ms=6000)[0]
                elif not cep_ok:
                    print(f"[amazon.produtos] não troquei o CEP da sessão ({r.get('erro') or 'sem resposta'}): "
                          "prazo aproximado")
            except Pular:
                raise
            except Exception as e:  # noqa: BLE001
                erros.append(f"GTA 6 (Chrome): {type(e).__name__}: {e}"[:160])
                cep_ok = False
            ref = referencia or not cep_ok
            achados: dict[str, Oferta] = {}
            if html:
                try:
                    o = parse_produto(html, asin_gta, "GTA6_CODE_IN_BOX")
                except RuntimeError as e:
                    erros.append(f"GTA 6: {e}")
                    o = None
                if o:
                    achados[o.id] = o
            for url in config.URLS_AMAZON_BUSCA_PRODUTOS:
                if cargas >= config.AMAZON_MAX_CARGAS_PRODUTOS:
                    break
                cargas += 1
                try:
                    hb = _abrir(url, esperar="div[data-component-type='s-search-result']", ocioso_ms=4000)[0]
                except Pular:
                    raise
                except Exception as e:  # noqa: BLE001
                    erros.append(f"busca do PS5/GTA 6: {type(e).__name__}: {e}"[:160])
                    continue
                for o in parse_busca_produtos(hb or ""):
                    # o ASIN já lido na página do produto (com o vendedor) vale mais que o cartão da busca
                    if not any(x.extra.get("asin") == o.extra.get("asin") for x in achados.values()):
                        achados.setdefault(o.id, o)
            paineis = _vendedores_da_busca(achados, erros, _abrir)
            for o in achados.values():
                txt = o.extra.pop("entrega_texto", None)
                if txt and entrega.precisa(o.modelo):
                    entrega.marca(o, entrega.data_por_extenso(txt), ref, "página da Amazon")
                por_id.setdefault(o.id, o)
            print(f"[amazon.produtos] {len(achados)} ofertas em {cargas} páginas e {paineis} painéis de ofertas")
        for o in por_id.values():
            o.fonte = self.nome
        if erros:
            print("[amazon.produtos] " + " | ".join(erros))
        if not por_id and erros:
            raise RuntimeError(erros[0])
        return list(por_id.values()), []
