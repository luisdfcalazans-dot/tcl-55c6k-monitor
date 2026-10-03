"""Lojas que exigem navegador real (Akamai / anti-bot). Rodam só no PC, com o Chrome instalado.

Estratégia comum: abrir a página com um perfil persistente do Chrome, esperar carregar, e extrair
o que der: JSON-LD schema.org, __NEXT_DATA__/estado embutido, respostas JSON interceptadas e,
por fim, o texto renderizado. Cada loja é "melhor esforço": se falhar, a saúde da fonte registra.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .. import config, produtos
from ..filtro import eh_modelo, modelo_do_titulo
from ..models import MODELO_PADRAO, Oferta
from ..util import fmt_preco, jsonld_produtos, limpa_html, loja_canonica, parse_preco, precos_no_texto
from ..trava import PerfilOcupado, trava_perfil
from . import Fonte, Pular, Resultado

PERFIL = config.RAIZ / ".pw-profile"
MARCA_BLOQUEIO_ML = config.RAIZ / "logs" / "ml_bloqueado_em"   # existe enquanto o ML estiver "de castigo"
ESPERA_ML_SEGUNDOS = 2 * 3600


def _dir_perfil(perfil: str) -> Path:
    return PERFIL if perfil == "default" else config.RAIZ / f".pw-profile-{perfil}"


def _headless(headless: bool | None) -> bool:
    import os

    return os.environ.get("PW_HEADLESS", "0") == "1" if headless is None else headless


def _travar(pasta: Path):
    """Lock do perfil (ver monitor/trava.py). Perfil ocupado por outro processo = pular a fonte desta vez."""
    pasta.mkdir(exist_ok=True)
    try:
        trava = trava_perfil(pasta, espera_s=30)
        trava.__enter__()
    except PerfilOcupado as e:
        raise Pular(str(e)) from None
    return trava


def _lancar(pw, pasta: Path, headless: bool):
    return pw.chromium.launch_persistent_context(
        str(pasta), channel="chrome", headless=headless, locale="pt-BR", timezone_id="America/Sao_Paulo",
        viewport={"width": 1366, "height": 900},
        # janela fora da tela: o Chrome precisa estar "visível" para passar no Akamai, mas não atrapalha
        args=["--disable-blink-features=AutomationControlled", "--window-position=-32000,-32000"],
    )


def _carregar(page, url: str, padroes: list[str], esperar: str | None, scroll: bool,
              timeout_ms: int, ocioso_ms: int = 15000) -> tuple[str, str, list[Any]]:
    """Carrega uma URL numa aba já aberta e devolve (html, texto visível, JSONs capturados nesta carga)."""
    capturados: list[Any] = []

    def on_response(resp):
        try:
            if any(p in resp.url for p in padroes) and "json" in (resp.headers.get("content-type") or ""):
                capturados.append({"url": resp.url, "json": resp.json()})
        except Exception:
            pass

    if padroes:
        page.on("response", on_response)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=ocioso_ms)
        except Exception:
            pass
        if esperar:
            try:
                page.wait_for_selector(esperar, timeout=15000)
            except Exception:
                pass
        if scroll:
            for _ in range(4):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(700)
        html = page.content()
        texto = page.evaluate("() => document.body ? document.body.innerText : ''")
    finally:
        if padroes:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass
    return html, texto, capturados


class _Sessao:
    """Uma janela do Chrome reaproveitada por várias páginas da mesma loja numa rodada.

    Abrir o Chrome custa ~10 s; com 3 páginas por loja isso dobrava o tempo da coleta do PC.
    A janela só abre na 1ª página pedida (nos testes, com _abrir trocado, nada abre) e segura o lock
    do perfil até fechar. Entre uma página e outra há uma pausa (config.PAUSA_ENTRE_PAGINAS_MS).
    """

    def __init__(self, perfil: str, headless: bool | None):
        self.perfil, self.headless = perfil, _headless(headless)
        self.pw = self.ctx = self.page = self.trava = None
        self.cargas = 0

    def abrir(self, url, esperar, capturar, scroll, timeout_ms, ocioso_ms=15000):
        if self.page is None:
            self.trava = _travar(_dir_perfil(self.perfil))
            from playwright.sync_api import sync_playwright

            self.pw = sync_playwright().start()
            self.ctx = _lancar(self.pw, _dir_perfil(self.perfil), self.headless)
            self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        elif self.cargas:
            self.page.wait_for_timeout(config.PAUSA_ENTRE_PAGINAS_MS)
        self.cargas += 1
        return _carregar(self.page, url, capturar or [], esperar, scroll, timeout_ms, ocioso_ms)

    def fechar(self) -> None:
        for passo in (lambda: self.ctx and self.ctx.close(), lambda: self.pw and self.pw.stop()):
            try:
                passo()
            except Exception:
                pass
        if self.trava is not None:
            self.trava.__exit__(None, None, None)
        self.pw = self.ctx = self.page = self.trava = None


_SESSOES: dict[str, _Sessao] = {}


@contextmanager
def sessao(perfil: str = "default", headless: bool | None = None):
    """Dentro do `with`, todo _abrir(perfil=...) usa a MESMA janela do Chrome (aberta sob demanda)."""
    if perfil in _SESSOES:  # já aberta por quem chamou
        yield _SESSOES[perfil]
        return
    s = _SESSOES[perfil] = _Sessao(perfil, headless)
    try:
        yield s
    finally:
        _SESSOES.pop(perfil, None)
        s.fechar()


def _abrir(url: str, esperar: str | None = None, capturar: list[str] | None = None,
           scroll: bool = False, timeout_ms: int = 45000, headless: bool | None = None,
           perfil: str = "default", ocioso_ms: int = 15000) -> tuple[str, str, list[Any]]:
    """Abre a URL no Chrome e devolve (html, texto visível, JSONs capturados).

    Por padrão roda com janela (headed): o Akamai bloqueia o Chrome headless. PW_HEADLESS=1 força headless.
    `perfil` escolhe a pasta do perfil do Chrome (lojas que marcam o perfil ficam isoladas das outras).
    Dentro de `with sessao(perfil)`, reaproveita a janela aberta; fora, abre e fecha o Chrome.
    `ocioso_ms`: quanto esperar a rede sossegar (páginas secundárias com `esperar` podem usar menos).
    """
    if perfil in _SESSOES:
        return _SESSOES[perfil].abrir(url, esperar, capturar, scroll, timeout_ms, ocioso_ms)
    s = _Sessao(perfil, headless)
    try:
        return s.abrir(url, esperar, capturar, scroll, timeout_ms, ocioso_ms)
    finally:
        s.fechar()


def _avaliar(js: str, arg: Any = None, perfil: str = "default") -> Any:
    """Roda a função JavaScript `js` (com o argumento `arg`) na aba da sessão aberta do `perfil`, depois de um _abrir
    dentro de `with sessao(perfil)`, e devolve o resultado. Serve para pedir as APIs da própria loja de dentro da página
    (o navegador manda os cookies e o sensor do Akamai: preço da Netshoes, CEP da Amazon). Nos testes é trocado."""
    s = _SESSOES.get(perfil)
    if s is None or s.page is None:
        raise RuntimeError("nenhuma página aberta nesta sessão do Chrome")
    return s.page.evaluate(js, arg)


_RE_FIM_BLOCO = re.compile(
    r"Descri[çc][ãa]o do produto|Produtos? relacionad|Produtos? patrocinad|Quem (?:viu|comprou)|Recomenda|"
    r"Compre junto|Voc[êe] tamb[ée]m pode gostar|"
    # "Avaliações" só como título de seção, em linha própria. O "com 172 avaliações" das estrelas
    # fica ACIMA do preço na Casas Bahia e cortava o bloco antes dele.
    r"^[ \t]*Avalia[çc][õo]es(?:[ \t]+d[aeo]s?[ \t]+\w+)?[ \t]*$", re.I | re.M)


def _bloco_principal(texto: str, fim: re.Pattern = _RE_FIM_BLOCO) -> str:
    """Texto só do topo da página (bloco do produto), antes dos carrosséis de recomendados/patrocinados."""
    m = fim.search(texto or "")
    return texto[: m.start()] if m else (texto or "")[:4000]


def _precos_do_bloco_principal(texto: str) -> list[float]:
    """Preços só do topo da página (bloco do produto), antes dos carrosséis de recomendados.

    Sem esse corte, o menor preço da página costuma ser o de outra TV sugerida ao lado.
    """
    return [p for p in precos_no_texto(_bloco_principal(texto)) if p >= 1500]


# Preço desenhado em pedaços (spans/linhas separados): "R$ 3 . 499" (AliExpress), "R$\n3.491\n,\n03" (ML).
# Os centavos só são colados quando há espaço ANTES da vírgula ("3.491 , 03"): "R$ 3.599, 10x" fica como está.
_RE_PRECO_QUEBRADO = re.compile(r"R\$\s*(\d{1,3}(?:\s*\.\s*\d{3})*(?:,\d{2}|\s+,\s*\d{2})?)(?![\dxX])")


def _junta_precos(texto: str) -> str:
    """Cola os dígitos de preços quebrados: 'R$ 3 . 499' -> 'R$ 3.499'; 'R$ 621 , 90' -> 'R$ 621,90'."""
    return _RE_PRECO_QUEBRADO.sub(lambda m: "R$ " + re.sub(r"\s+", "", m.group(1)), texto or "")


_RE_PARCELA_JUROS = re.compile(
    r"(\d{1,2})\s*x\s*(?:de\s*)?R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)(?![\d,])(?:\s*(sem|com)\s+juros)?", re.I)


def _parcelado_sem_juros(texto: str) -> str | None:
    """Primeira parcela 'Nx R$ V sem juros' do texto.

    Opção "com juros" (Casas Bahia: '11x de R$ 399,83 com juros') ou sem rótulo (no ML, parcela sem
    'sem juros' é com juros) não serve: o parcelado da Oferta é sempre uma condição sem juros.
    """
    for m in _RE_PARCELA_JUROS.finditer(_junta_precos(texto)):
        if (m.group(3) or "").lower() == "sem" and int(m.group(1)) > 1:
            return f"{m.group(1)}x R$ {m.group(2)} sem juros"
    return None


def _json_apos(html: str, chave: str) -> Any:
    """Decodifica o valor JSON logo depois de `chave` (ex.: '"ProductPrice":') no HTML. None se não achar."""
    dec = json.JSONDecoder()
    i = html.find(chave)
    while i >= 0:
        j = i + len(chave)
        while j < len(html) and html[j] in " \t\r\n":
            j += 1
        try:
            return dec.raw_decode(html, j)[0]
        except ValueError:
            i = html.find(chave, i + 1)
    return None


def _aplica_cartao_pix(o: Oferta, cartao: float | None, pix: float | None) -> None:
    """preco = cartão; preco_pix = Pix (só quando menor).

    O preço já lido (JSON-LD ou bloco da página) só é trocado pelo de cartão se um dos dois valores
    bater com ele: assim um número de outro lugar da página nunca substitui o preço do produto.
    """
    if pix and cartao and pix >= cartao:
        pix = None
    ref = o.preco
    confere = ref is not None and any(v and abs(v - ref) < 0.01 for v in (cartao, pix))
    if cartao and confere:
        o.preco = cartao
    if pix and o.preco and pix < o.preco:
        o.preco_pix = pix


def _esgotado_jsonld(html: str) -> bool:
    for prod in jsonld_produtos(html):
        offers = prod.get("offers")
        lista = offers if isinstance(offers, list) else [offers] if offers else []
        for of in lista:
            if isinstance(of, dict) and re.search(r"OutOfStock|SoldOut|Discontinued", str(of.get("availability") or "")):
                return True
    return False


def _e_do_produto(titulo: str, modelo: str, loja: str = "", id_loja: str | None = None) -> bool:
    """O título é do `modelo`? TV: o filtro de sempre (eh_modelo). PS5/GTA 6 (03/10): o classificador do catálogo, com o
    id do anúncio na loja quando se sabe (recusa usado, estrangeiro, acessório)."""
    if produtos.eh_tv(modelo):
        return eh_modelo(titulo, modelo)
    return produtos.classifica(titulo, loja or None, id_loja=id_loja).produto == modelo


def _oferta_jsonld(html: str, fonte: str, loja: str, url: str, oid: str,
                   modelo: str = MODELO_PADRAO) -> Oferta | None:
    for prod in jsonld_produtos(html):
        nome = prod.get("name") or ""
        if not _e_do_produto(nome, modelo, loja, oid):
            continue
        ean = str(prod.get("gtin13") or prod.get("gtin") or prod.get("gtin14") or "").strip().lstrip("0").zfill(13)
        if config.EAN_POR_MODELO.get(ean) not in (None, modelo):
            continue  # o código de barras (EAN) é o da outra TV: o título está errado
        offers = prod.get("offers")
        lista = offers if isinstance(offers, list) else [offers] if offers else []
        for of in lista:
            if not isinstance(of, dict):
                continue
            preco = parse_preco(of.get("price") or of.get("lowPrice"))
            if not preco:
                continue
            disp = str(of.get("availability") or "")
            seller = of.get("seller")
            vend = seller.get("name") if isinstance(seller, dict) else None
            return Oferta(fonte=fonte, tipo="loja", loja=loja, titulo=nome, url=of.get("url") or url, id=oid,
                          preco=preco, ativo=("OutOfStock" not in disp and "SoldOut" not in disp), vendedor=vend,
                          modelo=modelo)
    return None


_ID_CASASBAHIA = "55069456"
_RE_CB_CARTAO = re.compile(r"^[^\n]*?R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})[^\n]*cart[ãa]o de cr[ée]dito", re.I | re.M)
_RE_CB_PIX = re.compile(r"R\$\s?([\d.]+,\d{2})\s*(?:no|à vista no|via)?\s*pix", re.I)


# quando a Casas Bahia bloqueou nesta execução (time.time()): a fonte do PS5 não abre mais páginas logo depois
_CB_BLOQUEADA_EM: float | None = None


def _marca_cb_bloqueada() -> None:
    import time as _t

    global _CB_BLOQUEADA_EM
    _CB_BLOQUEADA_EM = _t.time()


def _cb_bloqueada_ha_pouco(janela_s: float = 30 * 60) -> bool:
    import time as _t

    return _CB_BLOQUEADA_EM is not None and _t.time() - _CB_BLOQUEADA_EM < janela_s


def _cb_bloqueio(html: str, texto: str) -> bool:
    """Página de bloqueio do Akamai na Casas Bahia: a antiga ("Access Denied", "Reference #") e a de 26/09 ("Ops! Algo
    deu errado." com "Reference ID", folha de estilo /customdeny/), que a coleta gravava como item esgotado."""
    if "Access Denied" in html[:3000] or "Reference #" in texto[:500]:
        return True
    if "/customdeny/" in html[:5000]:
        return True
    return "Algo deu errado" in texto[:300] and "Reference ID" in texto


def _cb_parcelado_embutido(pp: dict) -> str | None:
    """Parcelamento sem juros da lista embutida (ProductPrice.installmentOptions). Nunca usa opção com juros.

    Prefere as condições de qualquer cartão; se só o cartão da loja ("Bandeira" = cartão Casas Bahia,
    as mesmas condições de storeCardConditions) tiver sem juros, isso vai escrito no texto.
    Entre as opções sem juros, fica a de 10x (a que as outras lojas mostram); sem ela, a de mais parcelas.
    """
    grupos = [g for g in (pp.get("installmentOptions") or []) if isinstance(g, dict)]

    def opcoes(g: dict) -> list[tuple[int, float]]:
        out = []
        for c in g.get("conditions") or []:
            if not isinstance(c, dict):
                continue
            n, v = c.get("qtyParcels"), parse_preco(c.get("price"))
            rotulo = f"{c.get('option') or ''} {c.get('formattedOption') or ''}".lower()
            if not isinstance(n, int) or n < 2 or not v or (c.get("monthlyInterest") or 0) != 0 or "com juros" in rotulo:
                continue
            out.append((n, v))
        return out

    tipo = lambda g: str(g.get("type") or "").lower()  # noqa: E731
    ordem = [(g, "") for g in grupos if tipo(g) not in ("bandeira", "cdc", "pix")] + \
            [(g, " (cartão Casas Bahia)") for g in grupos if tipo(g) == "bandeira"]
    for g, nota in ordem:
        ops = opcoes(g)
        if ops:
            n, v = next(((n, v) for n, v in ops if n == 10), max(ops))
            return f"{n}x {fmt_preco(v)} sem juros{nota}"
    return None


def _cb_precos_embutidos(html: str, sku: str = _ID_CASASBAHIA) -> tuple[float | None, float | None, str | None]:
    """(cartão, Pix, parcelado sem juros) do estado embutido "ProductPrice" da página da Casas Bahia.

    O price do JSON-LD é o preço no Pix (10% off); o de cartão ("por R$ 3.998,99 ... no cartão") só
    aparece aqui: sellPrice.priceWithoutDiscount, e o Pix em paymentMethodDiscount.sellPriceWithDiscount.
    """
    pp = _json_apos(html, '"ProductPrice":')
    if not isinstance(pp, dict):
        return None, None, None
    sp = pp.get("sellPrice") if isinstance(pp.get("sellPrice"), dict) else {}
    if sp.get("skuId") and str(sp.get("skuId")) != str(sku):
        return None, None, None  # preço de outro item
    cond = pp.get("cardConditions") if isinstance(pp.get("cardConditions"), dict) else {}
    cartao = parse_preco(sp.get("priceWithoutDiscount")) or parse_preco(cond.get("cash")) or parse_preco(sp.get("priceValue"))
    pmd = pp.get("paymentMethodDiscount") if isinstance(pp.get("paymentMethodDiscount"), dict) else {}
    pix = None
    if pmd.get("hasDiscount") and "pix" in str(pmd.get("discountDescription") or "").lower():
        pix = parse_preco(pmd.get("sellPriceWithDiscount"))
    return cartao, pix, _cb_parcelado_embutido(pp)


def _cb_sku_da_pagina(html: str) -> str | None:
    """Sku do preço embutido (ProductPrice.sellPrice.skuId), para não usar a página de outro item."""
    pp = _json_apos(html, '"ProductPrice":')
    sp = pp.get("sellPrice") if isinstance(pp, dict) and isinstance(pp.get("sellPrice"), dict) else {}
    return str(sp["skuId"]) if sp.get("skuId") else None


def _cb_vendedores(html: str) -> list[dict]:
    """Vendedores do item (lista "sellers" com "elected" = quem está no buy box; os outros são os
    "outros vendedores" da página). Cada um: {id, nome, eleito, preco}."""
    dec = json.JSONDecoder()
    i = html.find('"sellers":[{"id":')
    while i >= 0:
        try:
            lista = dec.raw_decode(html, i + len('"sellers":'))[0]
        except ValueError:
            lista = None
        if isinstance(lista, list) and lista and all(isinstance(s, dict) and "elected" in s for s in lista):
            out = []
            for s in lista:
                if s.get("id") is None:
                    continue
                out.append({"id": str(s["id"]), "nome": str(s.get("name") or s["id"]).strip(),
                            "eleito": bool(s.get("elected")), "preco": parse_preco(s.get("sellPrice")),
                            "ativo": s.get("buyButtonEnabled") is not False})
            return out
        i = html.find('"sellers":[{"id":', i + 1)
    return []


def _cb_url_vendedor(url: str, vendedor_id: str | None) -> str:
    """Página do item com o vendedor escolhido (idLojista=<id>, o parâmetro dos links de lojista da Via)."""
    base = (url or "").split("#")[0].split("?")[0]
    return f"{base}?idLojista={vendedor_id}" if vendedor_id else base


def _cb_id(sku: str, vendedor_id: str | None, vendedor: str | None) -> str:
    return f"{sku}-{vendedor_id or re.sub(r'[^a-z0-9]+', '', (vendedor or '').lower()) or 'destaque'}"


_RE_CB_SKU = re.compile(r"/p/(\d+)")


def _cb_parse_busca(html: str) -> list[Oferta]:
    """Cartões da busca da Casas Bahia (só dentro da grade de resultados, nunca carrossel): um por sku, da 55C6K ou da
    65C6K (o modelo sai do título; a busca "tcl-65c6k" traz muitos TCL de outros modelos e tamanhos).

    Cartão: "por R$ 3.998,99 ou em até 11x de R$ 399,83 ou" (cartão; parcela sem 'sem juros' = com juros)
    e "por R$ 3.599,09 No Pix". O vendedor não aparece no cartão.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    grade = soup.select_one("[data-testid=product-card-ProductsGrid]")
    if grade is None:
        return []
    out: dict[str, Oferta] = {}
    for card in grade.select("[data-testid=product-card-item]"):
        t = card.select_one(".product-card__title, h3")
        titulo = t.get_text(" ", strip=True) if t else ""
        link = card.select_one("a[href*='/p/']")
        href = (link.get("href") or "") if link else ""
        m = _RE_CB_SKU.search(href)
        modelo = modelo_do_titulo(titulo)
        if not m or not modelo or m.group(1) in out:
            continue
        inst = card.select_one("[data-testid=product-card-installment]")
        dest = card.select_one("[data-testid=product-card-highlight-price-section]")
        txt_inst = inst.get_text(" ", strip=True) if inst else ""
        txt_dest = dest.get_text(" ", strip=True) if dest else ""
        mc = re.search(r"R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})", txt_inst)
        cartao = parse_preco(mc.group(1)) if mc else None
        mp = re.search(r"R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})\s*No Pix", txt_dest, re.I)
        pix = parse_preco(mp.group(1)) if mp else None
        if not cartao:
            md = re.search(r"R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})", txt_dest)
            cartao = parse_preco(md.group(1)) if md and not mp else None
        if not (cartao or pix):
            continue
        sku = m.group(1)
        url = href.split("#")[0].split("?")[0]
        out[sku] = Oferta(
            fonte="casasbahia", tipo="loja", loja="Casas Bahia", titulo=titulo, url=url, id=_cb_id(sku, None, None),
            preco=cartao, preco_pix=pix if pix and cartao and pix < cartao else (pix if not cartao else None),
            parcelado=_parcelado_sem_juros(txt_inst),
            extra={"anuncio": sku, "sku": sku, "vendedor_id": None, "origem": "busca"}, modelo=modelo,
        )
    return list(out.values())


class CasasBahia(Fonte):
    """Casas Bahia (só coleta, sem carrinho). Até config.CASASBAHIA_MAX_CARGAS páginas na mesma janela:
    o item de cada modelo (config.SKUS_CASASBAHIA: 55069456 da 55C6K, 55069453 da 65C6K; buy box + "outros
    vendedores"), a busca de cada modelo por outros skus e a página do sku mais barato achado nas buscas. Proteções
    contra preço falso mantidas: esgotado não tem preço, a página de outro sku não vira preço e o texto da página só
    vale no bloco do produto (nunca carrossel). Na 65C6K o 12x sem juros aparece no grupo "Bandeira" (o cartão Casas
    Bahia, como na 55"): continua escrito "(cartão Casas Bahia)"."""

    nome = "casasbahia"
    modo = "pc"

    @staticmethod
    def _bloqueou(html: str, texto: str) -> bool:
        return _cb_bloqueio(html, texto)

    def coletar(self) -> Resultado:
        out: dict[str, Oferta] = {}
        skus = dict(config.SKUS_CASASBAHIA)
        fixos = set(skus.values())
        with sessao("default"):
            cargas = 0
            # 1) o item fixo de cada modelo (o da 55C6K primeiro: bloqueio nele derruba a fonte, como antes)
            for modelo, sku in skus.items():
                if cargas >= config.CASASBAHIA_MAX_CARGAS:
                    break
                url = config.URLS_CASASBAHIA_PRODUTO.get(modelo) or f"https://www.casasbahia.com.br/p/{sku}"
                cargas += 1
                if modelo == MODELO_PADRAO:
                    html, texto, _ = _abrir(url, esperar="h1")
                    if self._bloqueou(html, texto):
                        _marca_cb_bloqueada()
                        raise RuntimeError("Casas Bahia bloqueou (Akamai)")
                else:
                    try:
                        html, texto, _ = _abrir(url, esperar="h1", ocioso_ms=6000)
                    except Pular:
                        raise
                    except Exception as e:  # noqa: BLE001
                        print(f"[casasbahia] item da {modelo} ({sku}) falhou: {type(e).__name__}: {str(e)[:120]}")
                        continue
                    if self._bloqueou(html, texto):
                        print(f"[casasbahia] item da {modelo} ({sku}): página bloqueada")
                        continue
                for o in self._do_produto(html, texto, url, sku, modelo):
                    out.setdefault(o.id, o)
            # 2) a busca de cada modelo, por outros skus dele
            outros: dict[str, Oferta] = {}
            for modelo in skus:
                if cargas >= config.CASASBAHIA_MAX_CARGAS:
                    break
                cargas += 1
                try:
                    hb, tb, _ = _abrir(config.URLS_CASASBAHIA_BUSCA.get(modelo, config.URL_CASASBAHIA_BUSCA),
                                       esperar="[data-testid=product-card-item]", ocioso_ms=4000)
                    if not self._bloqueou(hb, tb):
                        for o in _cb_parse_busca(hb):
                            if o.extra["sku"] not in fixos and o.modelo == modelo:
                                outros.setdefault(o.extra["sku"], o)
                except Pular:
                    raise
                except Exception as e:  # noqa: BLE001
                    print(f"[casasbahia] busca da {modelo} falhou: {type(e).__name__}: {str(e)[:120]}")
            # 3) a página do sku mais barato achado nas buscas (as duas TVs juntas), enquanto houver carga
            for o in sorted(outros.values(), key=lambda o: o.melhor_preco or 1e9):
                if cargas < config.CASASBAHIA_MAX_CARGAS:
                    # a página do item completa vendedor, cartão x Pix e parcelado
                    cargas += 1
                    try:
                        hp, tp, _ = _abrir(o.url, esperar="h1", ocioso_ms=6000)
                        completos = self._do_produto(hp, tp, o.url, o.extra["sku"], o.modelo)
                    except Pular:
                        raise
                    except Exception as e:  # noqa: BLE001
                        print(f"[casasbahia] item {o.extra['sku']} falhou: {type(e).__name__}")
                        completos = []
                    if completos:
                        for c in completos:
                            out.setdefault(c.id, c)
                        continue
                out.setdefault(o.id, o)
        return list(out.values()), []

    @staticmethod
    def _do_produto(html: str, texto: str, url: str, sku: str, modelo: str = MODELO_PADRAO) -> list[Oferta]:
        """Ofertas de uma página de item do `modelo`: a do buy box (com cartão x Pix e parcelado) e uma por outro
        vendedor. Página de outro sku ou de outro produto/modelo não vira preço."""
        if _cb_bloqueio(html, texto):
            return []
        pagina_sku = _cb_sku_da_pagina(html)
        if pagina_sku and pagina_sku != str(sku):
            return []  # a página é de outro item
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        titulo = limpa_html(m.group(1)) if m else ""
        if titulo and not _e_do_produto(titulo, modelo, "Casas Bahia", sku):
            return []
        if not titulo and "application/ld+json" not in html and '"ProductPrice":' not in html:
            # a página não trouxe nada do produto (nem título, nem JSON-LD, nem o estado embutido): é falha de carga,
            # não item esgotado (revisão de 26/09: gravar "esgotado" tirava o item do painel e da comparação 55x65)
            print(f"[casasbahia] a página do item {sku} veio sem o produto; não gravo nada dele nesta rodada")
            return []
        vendedores = _cb_vendedores(html)
        eleito = next((v for v in vendedores if v["eleito"]), None)
        pp = _json_apos(html, '"ProductPrice":')
        sp = pp.get("sellPrice") if isinstance(pp, dict) and isinstance(pp.get("sellPrice"), dict) else {}
        vid = eleito["id"] if eleito else (str(sp["sellerId"]) if sp.get("sellerId") else None)

        def base(**kw) -> Oferta:
            padrao = f"Smart TV TCL {modelo}" if produtos.eh_tv(modelo) else produtos.nome(modelo)
            o = Oferta(fonte="casasbahia", tipo="loja", loja="Casas Bahia", titulo=titulo or padrao,
                       url=url, id=_cb_id(sku, vid, eleito["nome"] if eleito else None),
                       vendedor=eleito["nome"] if eleito else None, modelo=modelo, **kw)
            o.extra.update({"anuncio": sku, "sku": sku, "vendedor_id": vid})
            return o

        esgotado = _esgotado_jsonld(html)
        o = _oferta_jsonld(html, "casasbahia", "Casas Bahia", url, sku, modelo)
        if o is not None and not o.preco:
            o = None
        if o is None:
            if esgotado or not titulo:
                # esgotado: sem preço. NUNCA cair para o texto da página, que tem o carrossel
                # de recomendados e já trouxe o preço de outra TV como se fosse esta.
                x = base(ativo=False)
                x.extra["motivo"] = "esgotado"
                return [x]
            precos = _precos_do_bloco_principal(texto)
            if not precos:
                return [base(ativo=False)]
            o = base(preco=min(precos))
        else:
            vend_ld = o.vendedor
            o = base(preco=o.preco, ativo=o.ativo)
            o.vendedor = o.vendedor or vend_ld
        # cartão x Pix: o JSON-LD traz o preço do Pix. Primeiro o estado embutido; sem ele, o texto
        # do bloco do produto (nunca a página toda: os patrocinados têm preço e parcela de outras TVs).
        topo = _bloco_principal(texto)
        cartao, pix, parcelado = _cb_precos_embutidos(html, sku)
        if cartao is None:
            mc = _RE_CB_CARTAO.search(topo)
            cartao = parse_preco(mc.group(1)) if mc else None
        if pix is None:
            mpix = _RE_CB_PIX.search(topo)
            pix = parse_preco(mpix.group(1)) if mpix else None
        _aplica_cartao_pix(o, cartao, pix)
        o.parcelado = o.parcelado or parcelado or _parcelado_sem_juros(topo)
        if "indisponível" in texto.lower()[:5000] and "produto indisponível" in texto.lower():
            o.ativo = False
        ofertas = [o]
        # "outros vendedores": só o preço que a lista traz (cartão); Pix e parcelado ficam vazios
        for v in vendedores:
            if v["eleito"] or not v["preco"] or v["id"] == vid:
                continue
            x = Oferta(fonte="casasbahia", tipo="loja", loja="Casas Bahia", titulo=o.titulo,
                       url=_cb_url_vendedor(url, v["id"]), id=_cb_id(sku, v["id"], v["nome"]),
                       preco=v["preco"], vendedor=v["nome"], ativo=v["ativo"],
                       extra={"anuncio": sku, "sku": sku, "vendedor_id": v["id"], "origem": "outros_vendedores"},
                       modelo=modelo)
            ofertas.append(x)
        return ofertas


_RE_FIM_BLOCO_ML = re.compile(
    r"Op[çc][õo]es de compra|Produtos? relacionad|Quem (?:viu|comprou)|Voc[êe] tamb[ée]m pode gostar", re.I)
_RE_ML_OUTROS_MEIOS = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*em outros meios", re.I)
_RE_ML_PIX = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(?:no|com|via|à vista no)\s*pix", re.I)


def _ml_texto_modelo(sub: dict) -> str:
    """'10x {price_installments} sem juros' + values -> '10x R$ 374,90 sem juros' (subtítulos do ML)."""
    txt = str(sub.get("text") or "")
    vals = sub.get("values") if isinstance(sub.get("values"), dict) else {}

    def troca(m: re.Match) -> str:
        v = vals.get(m.group(1))
        if not isinstance(v, dict):
            return ""
        if v.get("type") == "price" and v.get("value") is not None:
            return fmt_preco(parse_preco(v.get("value")))
        return str(v.get("text") or "")

    return re.sub(r"\s+", " ", re.sub(r"\{(\w+)\}", troca, txt)).strip()


def _ml_oferta_selecionada(html: str) -> dict:
    """Vendedor e parcelado da opção ESCOLHIDA no buy box do ML (buy_box_offers, selected=true).

    Com várias opções ("Parcelamento sem juros" de uma loja, "Melhor preço" de outra), o primeiro
    "Vendido por" e a parcela da página são da opção não escolhida, e não do preço gravado.
    Devolve {"multiplas": bool, "item_id", "vendedor", "parcelado"} (chaves só quando achadas).
    """
    info: dict[str, Any] = {}
    bb = _json_apos(html, '"buy_box_offers":')
    itens = bb.get("items") if isinstance(bb, dict) else None
    if isinstance(itens, list) and itens:
        info["multiplas"] = len(itens) > 1
        sel = next((it for it in itens if isinstance(it, dict) and it.get("selected")), None)
        if sel:
            info["item_id"] = sel.get("item_id")
            for comp in sel.get("components") or []:
                if not isinstance(comp, dict) or comp.get("state") == "HIDDEN":
                    continue
                subs = [comp] if comp.get("id") == "seller" else []
                subs += [s for s in comp.get("subtitles") or [] if isinstance(s, dict)]
                for s in subs:
                    txt = _ml_texto_modelo(s)
                    if s.get("id") == "seller" or txt.startswith("Vendido por"):
                        vend = txt.replace("Vendido por", "", 1).strip()
                        if vend:
                            info["vendedor"] = vend
                    elif "sem juros" in txt.lower():
                        p = _parcelado_sem_juros(txt)
                        if p:
                            info["parcelado"] = p
    if not info.get("vendedor"):
        sd = _json_apos(html, '"seller_data":')
        ev = (((sd or {}).get("viewport_track") or {}).get("melidata_event") or {}).get("event_data") \
            if isinstance(sd, dict) else None
        if isinstance(ev, dict) and ev.get("shop_name") and (not info.get("item_id") or ev.get("item_id") == info["item_id"]):
            info["vendedor"] = str(ev["shop_name"]).strip()
    return info


def _ml_opcoes_buybox(html: str) -> list[dict]:
    """Todas as opções de compra do anúncio de catálogo do ML (buy_box_offers.items).

    O mesmo catálogo costuma ter "Melhor preço" (um vendedor, preço com desconto) e "Parcelamento sem
    juros" (outro vendedor, preço cheio em 10x). A página abre com UMA selecionada, e qual é muda de
    uma visita para outra; lendo só a selecionada, a opção mais barata some em metade das coletas.
    Cada item vira {item_id, tipo, selecionada, preco, preco_de, desconto, parcelado, vendedor}.
    """
    bb = _json_apos(html, '"buy_box_offers":')
    return _ml_opcoes_de_itens(bb.get("items") if isinstance(bb, dict) else None)


def _ml_opcoes_de_itens(itens: Any) -> list[dict]:
    """Itens de opção de compra do ML (buy box ou "Outras opções") no formato de _ml_opcoes_buybox."""
    out: list[dict] = []
    for it in itens or []:
        if not isinstance(it, dict) or not it.get("item_id"):
            continue
        op: dict[str, Any] = {"item_id": str(it["item_id"]), "tipo": it.get("type"),
                              "selecionada": bool(it.get("selected"))}
        if isinstance(it.get("title"), str) and it["title"].strip():
            op["titulo"] = it["title"].strip()
        for comp in it.get("components") or []:
            if not isinstance(comp, dict) or comp.get("state") == "HIDDEN":
                continue
            if comp.get("id") == "price" and isinstance(comp.get("price"), dict):
                op["preco"] = parse_preco(comp["price"].get("value"))
                op["preco_de"] = parse_preco(comp["price"].get("original_value"))
                op["desconto"] = bool(comp.get("discount_label"))
            if comp.get("id") in ("title", "header") and "titulo" not in op:
                bloco = comp.get("title") if isinstance(comp.get("title"), dict) else comp
                txt = str((bloco or {}).get("text") or "").strip()
                if txt:
                    op["titulo"] = txt
            subs = [comp] if comp.get("id") == "seller" else []
            subs += [s for s in comp.get("subtitles") or [] if isinstance(s, dict)]
            for s in subs:
                txt = _ml_texto_modelo(s)
                if s.get("id") == "seller" or txt.startswith("Vendido por"):
                    vend = txt.replace("Vendido por", "", 1).strip()
                    if vend:
                        op["vendedor"] = vend
                elif "sem juros" in txt.lower() and "parcelado" not in op:
                    p = _parcelado_sem_juros(txt)
                    if p:
                        op["parcelado"] = p
        if op.get("preco"):
            out.append(op)
    return out


_RE_ML_VENDAS = re.compile(r"(\d+(?:[.,]\d+)*)\s*(mil|m\b|milh)?", re.I)


def _ml_numero_vendas(txt: str) -> int | None:
    """Vendas do vendedor como o ML escreve: '0' -> 0; '+500' -> 500; '+50 mil' -> 50000; '+1 M' -> 1000000."""
    m = _RE_ML_VENDAS.search(txt or "")
    if not m:
        return None
    num = m.group(1)
    mult = {"mil": 1000, "m": 1_000_000, "milh": 1_000_000}.get((m.group(2) or "").lower(), 1)
    if mult == 1:
        return int(re.sub(r"[.,]", "", num))
    return int(float(num.replace(".", "").replace(",", ".")) * mult)


def _ml_vendedor(html: str) -> dict:
    """Vendedor do anúncio aberto, do componente seller_data: item_id, vendedor, vendedor_id, tipo e vendas.

    Serve para conferir anúncio fora do catálogo antes de aceitar um preço menor: conta nova com
    '0 Vendas' e preço 25% abaixo do mercado é o padrão de golpe (visto em 19/09/2026).
    """
    sd = _json_apos(html, '"seller_data":')
    if not isinstance(sd, dict):
        return {}
    ev = (((sd.get("viewport_track") or {}).get("melidata_event") or {}).get("event_data") or {})
    info: dict[str, Any] = {}
    if isinstance(ev, dict):
        if ev.get("item_id"):
            info["item_id"] = str(ev["item_id"])
        if ev.get("seller_id"):
            info["vendedor_id"] = str(ev["seller_id"])
        if ev.get("shop_name"):
            info["vendedor"] = str(ev["shop_name"]).strip()
        if ev.get("seller_type"):
            info["tipo"] = str(ev["seller_type"])
    for comp in sd.get("components") or []:
        if not isinstance(comp, dict) or comp.get("id") != "seller_status":
            continue
        for inf in comp.get("info") or []:
            if not isinstance(inf, dict):
                continue
            titulo = inf.get("title") if isinstance(inf.get("title"), dict) else {}
            sub = str((inf.get("subtitle") or {}).get("text") or "") if isinstance(inf.get("subtitle"), dict) else ""
            if sub.lower().startswith("venda"):
                v = _ml_numero_vendas(str(titulo.get("text") or ""))
                if v is not None:
                    info["vendas"] = v
    return info


def _ml_alternativas(html: str, capturados: list[Any], catalogo: str = "") -> list[dict]:
    """Opções de compra do catálogo além do buy box ("Outras opções de compra" = bbw_alternatives).

    Vem no HTML quando o ML já desenha a lista e, quando não, na resposta de /p/api/deferred que a
    página pede ao rolar. Os itens têm a mesma forma dos do buy box. Devolve o formato de _ml_opcoes_buybox.

    Só entra o que a resposta PROVA ser opção de compra deste catálogo: no HTML, o recorte do componente
    bbw_alternatives; nas capturas, o id do catálogo na resposta e uma lista debaixo do componente de
    opções (_listas_de_opcoes). A mesma resposta de /p/api/deferred traz o carrossel de recomendados, e
    aceitar qualquer lista com item_id fazia um produto recomendado virar anúncio da 55C6K, com o título
    e a URL da TV e um preço que não é dela (19/09; mesma classe do erro da Casas Bahia de 17/09).
    """
    out: dict[str, dict] = {}
    bbw = _json_apos(html, '"bbw_alternatives":')
    if isinstance(bbw, dict):
        for itens in _listas_de_itens(bbw):   # já recortado do componente do catálogo
            for op in _ml_opcoes_de_itens(itens):
                out.setdefault(op["item_id"], op)
    cat = str(catalogo or "")
    for c in capturados or []:
        j = c.get("json") if isinstance(c, dict) else None
        if j is None:
            continue
        if cat and cat not in str(c.get("url") or "") and cat not in json.dumps(j, ensure_ascii=False)[:200000]:
            print(f"[mercadolivre] resposta capturada sem o catálogo {cat}: não conta como opção de compra")
            continue
        for itens in _listas_de_opcoes(j):
            for op in _ml_opcoes_de_itens(itens):
                out.setdefault(op["item_id"], op)
    return list(out.values())


TETO_PRECO_ML = 2.5      # rede de segurança só para cima: acima disso não é a mesma TV
PISO_PRECO_ML = 900.0    # nenhuma 55" QD-Mini LED nova custa menos que isto (peça/acessório/erro de leitura)


def _titulo_de_outro_produto(titulo: str | None, modelo: str = MODELO_PADRAO) -> bool:
    """O título lido da opção é de OUTRO produto (que não a TV do `modelo` do catálogo)?

    Só derruba quando o texto parece mesmo nome de produto (tem cara de título e não passa no filtro do modelo).
    Rótulo curto do buy box ("Melhor preço", "Parcelamento sem juros") ou texto vazio não derruba opção legítima."""
    t = (titulo or "").strip()
    if not t or _e_do_produto(t, modelo, "Mercado Livre"):
        return False
    parece_titulo = len(t.split()) >= 4 or re.search(r"\b(tv|televis|polegada|monitor|smart)\b", t, re.I)
    return bool(parece_titulo)


def _preco_plausivel(preco: float | None, referencias: list[float]) -> bool:
    """O preço de uma "outra opção" do catálogo é possível para esta TV?

    Só corta o absurdo: valor de acessório/peça (piso fixo) e preço muito acima das outras ofertas. NÃO corta por
    ser barato demais em relação às outras — uma opção legítima bem mais barata é exatamente a promoção que o
    monitor existe para achar. Quem barra produto de outro anúncio é a prova de componente/catálogo e o título."""
    validos = [p for p in referencias if p]
    if not preco:
        return True
    if preco < PISO_PRECO_ML:
        return False
    return not validos or preco <= max(validos) * TETO_PRECO_ML


def _ml_total_de_opcoes(html: str) -> int | None:
    """N de "Ver N opções a partir de R$ X" (bbw_alternatives): quantas opções o catálogo tem ao todo."""
    bbw = _json_apos(html, '"bbw_alternatives":')
    rotulo = ((((bbw or {}).get("action") or {}).get("label") or {}).get("text") or "") if isinstance(bbw, dict) else ""
    m = re.search(r"(\d+)\s+op", str(rotulo))
    return int(m.group(1)) if m else None


_RE_COMPONENTE_OPCOES_ML = re.compile(r"alternative|buy_?box|buying_option", re.I)


def _listas_de_opcoes(obj: Any, dentro: bool = False, prof: int = 0) -> list[list]:
    """Listas de itens que estão debaixo de um componente de OPÇÕES DE COMPRA do catálogo.

    O nome do componente (bbw_alternatives, buy_box_offers, buying_options…) é a prova de que a lista é
    das opções daquele catálogo, e não do carrossel de recomendados que vem na mesma resposta."""
    if prof > 10:
        return []
    achadas: list[list] = []
    if isinstance(obj, list):
        if dentro and obj and all(isinstance(x, dict) and x.get("item_id") for x in obj):
            achadas.append(obj)
        else:
            for x in obj:
                achadas += _listas_de_opcoes(x, dentro, prof + 1)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            achadas += _listas_de_opcoes(v, dentro or bool(_RE_COMPONENTE_OPCOES_ML.search(str(k))), prof + 1)
    return achadas


def _listas_de_itens(obj: Any, prof: int = 0) -> list[list]:
    """Todas as listas de dicts com item_id dentro de obj (JSON do ML)."""
    if prof > 10:
        return []
    achadas: list[list] = []
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) and x.get("item_id") for x in obj):
            achadas.append(obj)
        else:
            for x in obj:
                achadas += _listas_de_itens(x, prof + 1)
    elif isinstance(obj, dict):
        for v in obj.values():
            achadas += _listas_de_itens(v, prof + 1)
    return achadas


class MercadoLivre(Fonte):
    """O ML marca perfis automatizados e passa a exigir login. Usa um perfil só dele, recriado quando bloqueado.
    Falhas aqui não geram aviso: as ofertas do ML também chegam via Promobit, Pelando e Telegram.

    Descoberta (19/09/2026), por modelo (config.ML_CATALOGOS: 55C6K MLB48808732, 65C6K MLB50368907; o da 65C7K,
    MLB49823182, é vizinho), até config.ML_MAX_CARGAS páginas na MESMA janela: (1) o catálogo com todas as opções de
    compra (buy box + "Outras opções"); (2) a busca, para anúncios fora do catálogo; (3) a página de um anúncio fora
    do catálogo mais barato que o catálogo, para conferir o vendedor antes de aceitar o preço. A 55C6K vem primeiro e
    deixa reservadas as páginas da 65C6K (catálogo e busca). No primeiro bloqueio a rodada para: nenhuma página a mais
    (o ML marca o perfil). A lista "/p/<catálogo>/s" pede login a perfil sem conta (conferido em 19/09), por isso não
    é usada. Uma Oferta por item_id.
    """

    nome = "mercadolivre"
    modo = "pc"
    alerta_falha = False

    @staticmethod
    def _bloqueado(html: str, texto: str) -> bool:
        return "suspicious-traffic" in html[:8000] or "Hubo un error" in texto[:300] or "Para continuar, acesse" in texto[:300]

    @staticmethod
    def _pede_login(html: str, texto: str) -> bool:
        return "/login/identification" in html[:20000] or "para iniciar sess" in (texto or "")[:600]

    def coletar(self) -> Resultado:
        import shutil
        import time as _t

        if MARCA_BLOQUEIO_ML.exists():
            restante = ESPERA_ML_SEGUNDOS - (_t.time() - MARCA_BLOQUEIO_ML.stat().st_mtime)
            if restante > 0:
                raise Pular(f"bloqueado pelo ML; nova tentativa em {restante/60:.0f} min")
        bloqueado = False
        out: list[Oferta] = []
        modelos = list(config.ML_CATALOGOS)
        with sessao("ml"):
            cargas = 0
            for i, modelo in enumerate(modelos):
                if cargas >= config.ML_MAX_CARGAS:
                    break
                # catálogo e busca de cada modelo que ainda falta ficam reservados
                teto = config.ML_MAX_CARGAS - 2 * (len(modelos) - i - 1)
                ofs, cargas, bloq = self._coleta_do_modelo(modelo, cargas, max(teto, cargas + 1), primeiro=i == 0)
                out += ofs
                if bloq:
                    bloqueado = True
                    break  # o ML marcou o perfil: nenhuma página a mais nesta rodada
        if bloqueado:
            shutil.rmtree(_dir_perfil("ml"), ignore_errors=True)  # perfil marcado: começa do zero na próxima
            MARCA_BLOQUEIO_ML.parent.mkdir(exist_ok=True)
            MARCA_BLOQUEIO_ML.write_text(_t.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
            if not out:
                raise RuntimeError("Mercado Livre pediu verificação anti-bot; próxima tentativa em 2 h")
            print("[mercadolivre] a página seguinte pediu verificação anti-bot; fica o que já veio e a próxima tentativa "
                  "é em 2 h")
        else:
            MARCA_BLOQUEIO_ML.unlink(missing_ok=True)
        unicas: dict[str, Oferta] = {}
        for o in out:
            unicas.setdefault(o.id, o)
        return list(unicas.values()), []

    def _coleta_do_modelo(self, modelo: str, cargas: int, teto: int, primeiro: bool) -> tuple[list[Oferta], int, bool]:
        """(ofertas, cargas usadas até aqui, bloqueado) de um modelo: catálogo, busca e conferência de vendedor, sem
        passar de `teto` páginas no total. Erro ao abrir o catálogo do 1º modelo sobe (como antes); o dos outros vai
        para o log."""
        cat_id = config.ML_CATALOGOS[modelo]
        url_cat = config.URLS_ML_CATALOGO.get(modelo) or f"https://www.mercadolivre.com.br/p/{cat_id}"
        try:
            html, texto, capt = _abrir(url_cat, esperar=".ui-pdp-price, .andes-money-amount",
                                       capturar=["/p/api/deferred"], perfil="ml")
        except Pular:
            raise
        except Exception as e:  # noqa: BLE001
            if primeiro:
                raise
            print(f"[mercadolivre] catálogo da {modelo} falhou: {type(e).__name__}: {str(e)[:120]}")
            return [], cargas + 1, False
        cargas += 1
        catalogo_ok = not self._bloqueado(html, texto)
        out = self._ofertas_do_catalogo(html, texto, capt, modelo) if catalogo_ok else []
        html2, texto2 = "", ""
        if cargas < teto:
            cargas += 1
            try:
                html2, texto2, _ = _abrir(config.URLS_ML_BUSCA.get(modelo, config.URL_ML_BUSCA),
                                          esperar=".ui-search-result, .poly-card", perfil="ml", ocioso_ms=6000)
            except Pular:
                raise
            except Exception as e:  # noqa: BLE001 - a busca é extra: o catálogo já foi lido
                print(f"[mercadolivre] busca da {modelo} falhou: {type(e).__name__}: {str(e)[:120]}")
        lista = [] if (not html2 or self._bloqueado(html2, texto2)) else self._parse_lista(html2, modelo)
        if html2:
            n_fora = sum(o.extra.get("catalogo") != cat_id for o in lista)
            print(f"[mercadolivre] busca: {len(lista)} anúncios da {modelo} ({n_fora} fora do catálogo)"
                  if lista else f"[mercadolivre] busca: nenhum anúncio da {modelo} (ou página bloqueada)")
        if not catalogo_ok and not lista:
            return [], cargas, True
        if not out:
            # catálogo bloqueado ou ilegível: o cartão do catálogo na busca vale pelo vencedor do buy box
            out = [o for o in lista if o.extra.get("catalogo") == cat_id]
        fora = [o for o in lista if o.extra.get("catalogo") != cat_id]
        aceitos, usadas = self._confere(fora, out, teto - cargas)
        return out + aceitos, cargas + usadas, False

    def _ofertas_do_catalogo(self, html: str, texto: str, capt: list[Any], modelo: str = MODELO_PADRAO) -> list[Oferta]:
        """Uma Oferta por opção de compra do catálogo do `modelo` (buy box e "Outras opções de compra"). Também os
        catálogos do PS5 (config.ML_CATALOGOS_PRODUTOS, fonte MercadoLivreProdutos)."""
        cat_id = {**config.ML_CATALOGOS, **config.ML_CATALOGOS_PRODUTOS}.get(modelo, config.ML_CATALOGO_ID)
        url_cat = config.URLS_ML_CATALOGO.get(modelo) or f"https://www.mercadolivre.com.br/p/{cat_id}"
        o = _oferta_jsonld(html, "mercadolivre", "Mercado Livre", url_cat, cat_id, modelo)
        if o is None:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            titulo = limpa_html(m.group(1)) if m else ""
            if _e_do_produto(titulo, modelo, "Mercado Livre", cat_id):
                mp = re.search(r'"price":\s*([\d.]+)', html)
                preco = parse_preco(mp.group(1)) if mp else None
                if not preco:
                    precos = [p for p in precos_no_texto(texto) if p >= 1500]
                    preco = min(precos) if precos else None
                if preco:
                    o = Oferta(fonte="mercadolivre", tipo="loja", loja="Mercado Livre", titulo=titulo,
                               url=url_cat, id=cat_id, preco=preco, modelo=modelo)
        if not o:
            return []
        # só o bloco do produto: abaixo dele vêm "Opções de compra" e o carrossel de relacionados
        topo = _junta_precos(_bloco_principal(texto, _RE_FIM_BLOCO_ML))
        sel = _ml_oferta_selecionada(html)
        mo = _RE_ML_OUTROS_MEIOS.search(topo)
        outros = parse_preco(mo.group(1)) if mo else None
        if outros and o.preco and outros > o.preco + 0.005:
            # "R$ 3.491,03 ... ou R$ 3.599 em outros meios": o preço anunciado (JSON-LD) é o do Pix
            o.preco_pix, o.preco = o.preco, outros
        else:
            mpix = _RE_ML_PIX.search(topo)
            pix = parse_preco(mpix.group(1)) if mpix else None
            if pix and o.preco and pix < o.preco:
                o.preco_pix = pix
        if sel.get("vendedor"):
            o.vendedor = sel["vendedor"]
        elif not sel.get("multiplas"):
            # com várias opções no buy box, o "Vendido por" do texto pode ser de outra opção
            mv = re.search(r"Vendido por\s+([^\n]{2,60})", texto)
            if mv:
                o.vendedor = mv.group(1).strip()
        o.parcelado = o.parcelado or sel.get("parcelado") or _parcelado_sem_juros(topo)
        vend = _ml_vendedor(html)
        ofertas = self._por_opcao(o, html, sel)
        if len(ofertas) == 1 and ofertas[0].id == cat_id and vend.get("item_id"):
            # uma opção só: o id é o item do vendedor (o mesmo que ela tem quando há várias opções)
            ofertas[0].id = vend["item_id"]
        # "Outras opções de compra" que não estão no buy box
        ja = {x.id for x in ofertas}
        refs = [x.melhor_preco for x in ofertas if x.melhor_preco]
        for op in _ml_alternativas(html, capt, cat_id):
            if op["item_id"] in ja:
                continue
            if _titulo_de_outro_produto(op.get("titulo"), modelo):
                print(f"[mercadolivre] opção {op['item_id']} com título de outro produto "
                      f"({op['titulo'][:60]!r}) — descartada")
                continue
            if not _preco_plausivel(op["preco"], refs):
                print(f"[mercadolivre] opção {op['item_id']} a {fmt_preco(op['preco'])} com preço impossível "
                      f"para esta TV — descartada")
                continue
            x = Oferta(fonte="mercadolivre", tipo="loja", loja="Mercado Livre", titulo=o.titulo, url=o.url,
                       id=op["item_id"], preco=op["preco"], parcelado=op.get("parcelado"), vendedor=op.get("vendedor"),
                       modelo=modelo)
            if op.get("desconto") and op.get("preco_de") and op["preco_de"] > op["preco"] + 0.005:
                x.preco, x.preco_pix = op["preco_de"], op["preco"]
            x.extra["opcao_ml"] = op.get("tipo") or "OUTRAS_OPCOES"
            ofertas.append(x)
            ja.add(x.id)
        n_opcoes = _ml_total_de_opcoes(html)
        if n_opcoes and n_opcoes > len(ofertas):
            # a lista completa (/p/<catálogo>/s) pede login a perfil sem conta (conferido em 19/09)
            print(f"[mercadolivre] o catálogo da {modelo} diz {n_opcoes} opções de compra; {len(ofertas)} visíveis "
                  "sem login")
        for x in ofertas:
            item = x.id if x.id.startswith("MLB") and x.id != cat_id else None
            x.url = _ml_url_item_do_catalogo(url_cat, item)
            x.modelo = modelo
            x.extra.update({"anuncio": item or cat_id, "item_id": item,
                            "catalogo": cat_id, "opcoes_no_catalogo": n_opcoes,
                            "vendedor_id": vend.get("vendedor_id") if item and item == vend.get("item_id") else None})
            if item and item == vend.get("item_id") and vend.get("vendas") is not None:
                x.extra["vendas_vendedor"] = vend["vendas"]  # checagem de confiança (monitor/confianca.py)
        return ofertas

    def _conferir_fora_do_catalogo(self, fora: list[Oferta], catalogo: list[Oferta], cargas: int) -> list[Oferta]:
        """Anúncios fora do catálogo. Os que custam menos que o catálogo só entram depois de conferir o
        vendedor na página do anúncio (até `cargas` páginas, do mais barato ao mais caro); vendedor com
        menos de config.ML_VENDAS_MINIMAS vendas, ou não conferido, fica de fora (e vai para o log)."""
        return self._confere(fora, catalogo, cargas)[0]

    def _confere(self, fora: list[Oferta], catalogo: list[Oferta], cargas: int) -> tuple[list[Oferta], int]:
        """_conferir_fora_do_catalogo e quantas páginas ela abriu."""
        disponiveis = cargas
        precos_cat = [o.melhor_preco for o in catalogo if o.melhor_preco]
        ref = min(precos_cat) if precos_cat else None
        aceitos: list[Oferta] = []
        for o in sorted(fora, key=lambda x: x.melhor_preco or 1e9):
            p = o.melhor_preco
            if p and ref is not None and p >= ref:
                o.extra["vendedor_conferido"] = False
                aceitos.append(o)
                continue
            if cargas <= 0:
                print(f"[mercadolivre] fora do catálogo NÃO conferido (sem páginas nesta rodada): {o.id} "
                      f"{fmt_preco(p)} — descartado")
                continue
            cargas -= 1
            try:
                html, texto, _ = _abrir(o.url, esperar=".ui-pdp-price, .andes-money-amount", perfil="ml",
                                        ocioso_ms=6000)
            except Pular:
                raise
            except Exception as e:  # noqa: BLE001
                print(f"[mercadolivre] não abriu {o.id}: {type(e).__name__} — descartado")
                continue
            if self._bloqueado(html, texto) or self._pede_login(html, texto):
                print(f"[mercadolivre] {o.id}: página pediu login/verificação — descartado")
                continue
            v = _ml_vendedor(html)
            vendas = v.get("vendas")
            if v.get("item_id") and v["item_id"] != o.id:
                # a página abriu outro item (ex.: redirecionou para um catálogo): vendedor não conferido
                print(f"[mercadolivre] {o.id}: a página mostrou o item {v['item_id']} — descartado")
                continue
            if vendas is None or vendas < config.ML_VENDAS_MINIMAS:
                print(f"[mercadolivre] {o.id} {fmt_preco(p)} vendido por {v.get('vendedor')!r} com "
                      f"{vendas} vendas — descartado (suspeito)")
                continue
            o.vendedor = v.get("vendedor") or o.vendedor
            o.extra.update({"vendedor_id": v.get("vendedor_id"), "vendas_vendedor": vendas,
                            "vendedor_conferido": True})
            aceitos.append(o)
        return aceitos, disponiveis - cargas

    @staticmethod
    def _por_opcao(o: Oferta, html: str, sel: dict) -> list[Oferta]:
        """Uma Oferta por opção do buy box, com id estável = item_id do vendedor.

        A opção selecionada mantém os valores já conferidos no texto da página (o). As outras vêm do
        JSON do buy box: com etiqueta de desconto e preço original maior, o original é o preço em outros
        meios e o valor é o do Pix (é assim que o ML mostra "R$ 3.491,03 · 3% OFF · ou R$ 3.599").
        Sem buy box legível, devolve só a oferta original.
        """
        import copy

        opcoes = _ml_opcoes_buybox(html)
        if not opcoes:
            return [o]
        out: list[Oferta] = []
        for op in opcoes:
            if op["selecionada"] or op["item_id"] == sel.get("item_id"):
                x = copy.copy(o)
                x.extra = dict(o.extra)
            else:
                x = Oferta(fonte="mercadolivre", tipo="loja", loja="Mercado Livre", titulo=o.titulo,
                           url=o.url, id="", preco=op["preco"], modelo=o.modelo)
                if op.get("desconto") and op.get("preco_de") and op["preco_de"] > op["preco"] + 0.005:
                    x.preco, x.preco_pix = op["preco_de"], op["preco"]
                x.parcelado = op.get("parcelado")
                x.vendedor = op.get("vendedor")
            x.id = op["item_id"]
            x.extra["opcao_ml"] = op.get("tipo")
            out.append(x)
        return out

    @staticmethod
    def _parse_lista(html: str, modelo: str = MODELO_PADRAO) -> list[Oferta]:
        """Resultados da busca do ML do `modelo` (pelo título): título, preço (inteiro + centavos em spans
        separados) e link. A busca de uma TV traz a outra também; ela tem a própria busca.

        Cartão de catálogo (/p/MLB...) traz o item vencedor no fragmento do link (wid=MLB...): o id da
        Oferta é esse item_id; cartão de anúncio avulso (produto.mercadolivre.com.br/MLB-...) usa o dele.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        out: dict[str, Oferta] = {}
        for card in soup.select("li.ui-search-layout__item, div.poly-card, .ui-search-result__wrapper"):
            t = card.select_one("a.poly-component__title, h2.poly-box, h2.ui-search-item__title, h3.poly-component__title-wrapper")
            if not t:
                continue
            titulo = t.get_text(" ", strip=True)
            if not eh_modelo(titulo, modelo):
                continue
            link_el = t if t.name == "a" else card.select_one("a[href*='mercadolivre.com.br']")
            href = (link_el.get("href") or "") if link_el else ""
            url = href.split("#")[0].split("?")[0]
            precos = []
            for bloco in card.select(".poly-price__current, .ui-search-price__second-line, .poly-component__price"):
                frac = bloco.select_one(".andes-money-amount__fraction")
                cents = bloco.select_one(".andes-money-amount__cents")
                if frac:
                    precos.append(parse_preco(frac.get_text(strip=True) + ("," + cents.get_text(strip=True) if cents else "")))
            if not precos:
                for frac in card.select(".andes-money-amount__fraction")[:2]:
                    precos.append(parse_preco(frac.get_text(strip=True)))
            precos = [p for p in precos if p and p >= 1000]
            if not precos:
                continue
            texto_card = _junta_precos(card.get_text(" ", strip=True))
            if re.search(r"\b(?:usado|recondicionado)\b", texto_card, re.I):
                continue  # só TV nova
            preco, pix = min(precos), None
            mo = _RE_ML_OUTROS_MEIOS.search(texto_card)
            outros = parse_preco(mo.group(1)) if mo else None
            if outros and outros > preco + 0.005:
                # "R$ 4.072 no Pix ou R$ 4.197 em outros meios": o preço em destaque é o do Pix
                preco, pix = outros, preco
            vend = card.select_one(".poly-component__seller")
            mcat = re.search(r"/p/(MLB\d+)", url)
            mwid = re.search(r"[#&?]wid=(MLB\d+)", href)
            oid = re.search(r"(MLB-?\d+)", url)
            extra: dict[str, Any] = {}
            if mcat:
                item = mwid.group(1) if mwid else None
                oid_s = item or mcat.group(1)
                extra = {"catalogo": mcat.group(1), "item_id": item, "anuncio": item or mcat.group(1)}
                url = _ml_url_item_do_catalogo(url, item)
            else:
                oid_s = oid.group(1).replace("-", "") if oid else url[-40:]
                extra = {"item_id": oid_s if oid else None, "anuncio": oid_s}
            extra["vendedor_id"] = None
            out.setdefault(oid_s, Oferta(
                fonte="mercadolivre", tipo="loja", loja="Mercado Livre", titulo=titulo,
                url=url or config.URLS_ML_BUSCA.get(modelo, config.URL_ML_BUSCA),
                id=oid_s, preco=preco, preco_pix=pix, parcelado=_parcelado_sem_juros(texto_card),
                vendedor=vend.get_text(" ", strip=True).replace("Por ", "") if vend else None, extra=extra,
                modelo=modelo,
            ))
        return list(out.values())


def _ml_url_item_do_catalogo(url_catalogo: str, item_id: str | None) -> str:
    """Link do catálogo que abre a opção deste vendedor (?pdp_filters=item_id%3A<MLB...>)."""
    base = (url_catalogo or "").split("#")[0].split("?")[0]
    return f"{base}?pdp_filters=item_id%3A{item_id}" if item_id else base


class AliExpress(Fonte):
    """Busca no AliExpress (inclui a loja da Magalu e a loja oficial TCL), uma por modelo
    (config.URLS_ALIEXPRESS_BUSCA; a 65C6K da Magalu Store é o item 1005009036343124). Melhor esforço."""

    nome = "aliexpress"
    modo = "pc"

    def coletar(self) -> Resultado:
        out: dict[str, Oferta] = {}
        with sessao("default"):
            for modelo, url in config.URLS_ALIEXPRESS_BUSCA.items():
                if modelo == MODELO_PADRAO:
                    html, _texto, _ = _abrir(url, scroll=True)   # a busca da 55C6K falhando, a fonte falha
                else:
                    try:
                        html, _texto, _ = _abrir(url, scroll=True)
                    except Pular:
                        raise
                    except Exception as e:  # noqa: BLE001
                        print(f"[aliexpress] busca da {modelo} falhou: {type(e).__name__}: {str(e)[:120]}")
                        continue
                for o in self._parse(html, modelo):
                    out.setdefault(o.id, o)
        return list(out.values()), []

    @staticmethod
    def _parse(html: str, modelo: str = MODELO_PADRAO) -> list[Oferta]:
        """Ofertas do `modelo` na página de busca (cada busca traz só o modelo dela; os outros cartões ficam de fora)."""
        out: dict[str, Oferta] = {}
        # 1) estado embutido: window._dida_config_._init_data_ ou _init_data_
        m = re.search(r"_init_data_\s*=\s*(\{.*?\});?\s*</script>", html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                data = None
            if data:
                itens = _achar_lista(data, lambda x: isinstance(x, dict) and ("productId" in x) and ("title" in x))
                for it in itens:
                    titulo = (it.get("title") or {}).get("displayTitle") if isinstance(it.get("title"), dict) else it.get("title")
                    titulo = titulo or ""
                    if not eh_modelo(titulo, modelo):
                        continue
                    prices = it.get("prices") or {}
                    sale = (prices.get("salePrice") or {}).get("minPrice") or (prices.get("salePrice") or {}).get("formattedPrice")
                    preco = parse_preco(sale)
                    loja = (it.get("store") or {}).get("storeName") or "AliExpress"
                    pid = str(it.get("productId"))
                    out[pid] = Oferta(fonte="aliexpress", tipo="loja", loja="AliExpress", titulo=titulo,
                                      url=f"https://pt.aliexpress.com/item/{pid}.html", id=pid, preco=preco, vendedor=loja,
                                      modelo=modelo)
        # 2) fallback: cartões renderizados
        if not out:
            for card in re.finditer(r'<a[^>]+href="([^"]*?/item/(\d+)\.html[^"]*)"[^>]*>(.*?)</a>', html, re.S):
                # o preço de venda vem em spans separados ("R$ 3 . 499"): sem colar, sobrava só o riscado
                bloco = _junta_precos(limpa_html(card.group(3)))
                if not eh_modelo(bloco, modelo):
                    continue
                precos = [p for p in precos_no_texto(bloco) if p >= 1000]
                pid = card.group(2)
                out.setdefault(pid, Oferta(fonte="aliexpress", tipo="loja", loja="AliExpress", titulo=bloco[:140],
                                           url=f"https://pt.aliexpress.com/item/{pid}.html", id=pid,
                                           preco=min(precos) if precos else None, modelo=modelo))
        return list(out.values())


class Shopee(Fonte):
    """Busca na Shopee interceptando a resposta JSON da API interna. Melhor esforço (pode exigir login)."""

    nome = "shopee"
    modo = "pc"

    def coletar(self) -> Resultado:
        import os
        if os.environ.get("SHOPEE", "0") != "1":
            return [], []  # a busca da Shopee exige login; ligue com SHOPEE=1 no .env se quiser tentar
        out: dict[str, Oferta] = {}
        texto = ""
        with sessao("default"):
            for url in config.URLS_SHOPEE_BUSCA.values():  # a 55C6K e a 65C6K (uma busca por modelo)
                _, texto, capt = _abrir(url, capturar=["/api/v4/search/search_items"], scroll=True)
                for c in capt:
                    for it in (c["json"].get("items") or []):
                        b = it.get("item_basic") or it
                        nome = b.get("name") or ""
                        modelo = modelo_do_titulo(nome)
                        if not modelo:
                            continue
                        preco = (b.get("price") or 0) / 100000 or None
                        iid, sid = b.get("itemid"), b.get("shopid")
                        out[str(iid)] = Oferta(fonte="shopee", tipo="loja", loja="Shopee", titulo=nome,
                                               url=f"https://shopee.com.br/product/{sid}/{iid}", id=str(iid),
                                               preco=preco, vendedor=b.get("shop_name") or None, modelo=modelo)
                if not out and ("login" in texto.lower()[:2000] or "entrar" in texto.lower()[:2000]):
                    raise RuntimeError("Shopee exigiu login para buscar")
        return list(out.values()), []


class CasasBahiaProdutos(Fonte):
    """PS5 na Casas Bahia (03/10/2026): a página de cada item do catálogo (monitor/produtos.py, ids da "Casas Bahia"), até
    config.CASASBAHIA_MAX_CARGAS_PRODUTOS, na mesma janela. A URL precisa de um slug qualquer antes do /p/<sku> (só
    "/p/<sku>" dá 404). Os PS5 de lá são quase todos de parceiros (Loja Gazin, Game Play Fulfillment): a confiança
    decide. Bloqueio do Akamai no 1º item derruba a fonte (como na das TVs); nos outros, vai para o log."""

    nome = "casasbahia.produtos"
    modo = "pc"

    def coletar(self) -> Resultado:
        if _cb_bloqueada_ha_pouco():
            raise Pular("a Casas Bahia bloqueou nesta rodada (Akamai): nada de abrir mais páginas")
        skus = list(produtos.ids_da_loja("Casas Bahia", config._NAO_TV).items())[:config.CASASBAHIA_MAX_CARGAS_PRODUTOS]
        out: dict[str, Oferta] = {}
        with sessao("default"):
            for i, (sku, modelo) in enumerate(skus):
                url = f"https://www.casasbahia.com.br/console-playstation-5/p/{sku}"
                try:
                    html, texto, _ = _abrir(url, esperar="h1", ocioso_ms=6000)
                except Pular:
                    raise
                except Exception as e:  # noqa: BLE001
                    if i == 0:
                        raise
                    print(f"[casasbahia.produtos] item {sku} falhou: {type(e).__name__}: {str(e)[:120]}")
                    continue
                if _cb_bloqueio(html, texto):
                    if i == 0:
                        _marca_cb_bloqueada()
                        raise RuntimeError("Casas Bahia bloqueou (Akamai)")
                    print(f"[casasbahia.produtos] item {sku}: página bloqueada")
                    continue
                for o in CasasBahia._do_produto(html, texto, url, sku, modelo):
                    o.fonte = self.nome
                    out.setdefault(o.id, o)
        return list(out.values()), []


class MercadoLivreProdutos(Fonte):
    """Catálogo do PS5 no Mercado Livre (config.ML_CATALOGOS_PRODUTOS), no perfil do ML, depois das TVs: só a página do
    catálogo (a lista/busca do ML pede verificação). Com o ML "de castigo" (logs/ml_bloqueado_em), espera; bloqueio aqui
    também põe o castigo de 2 h (o perfil foi marcado). Sem aviso de falha: o PS5 do ML também vem da vitrine da loja
    oficial (nuvem) e das postagens."""

    nome = "mercadolivre.produtos"
    modo = "pc"
    alerta_falha = False

    def coletar(self) -> Resultado:
        import shutil
        import time as _t

        if MARCA_BLOQUEIO_ML.exists():
            restante = ESPERA_ML_SEGUNDOS - (_t.time() - MARCA_BLOQUEIO_ML.stat().st_mtime)
            if restante > 0:
                raise Pular(f"bloqueado pelo ML; nova tentativa em {restante/60:.0f} min")
        out: dict[str, Oferta] = {}
        bloqueado = False
        coletor = MercadoLivre()
        with sessao("ml"):
            for modelo, cat in config.ML_CATALOGOS_PRODUTOS.items():
                html, texto, capt = _abrir(f"https://www.mercadolivre.com.br/p/{cat}",
                                           esperar=".ui-pdp-price, .andes-money-amount", capturar=["/p/api/deferred"],
                                           perfil="ml", ocioso_ms=8000)
                if coletor._bloqueado(html, texto) or coletor._pede_login(html, texto):
                    bloqueado = True
                    break
                for o in coletor._ofertas_do_catalogo(html, texto, capt, modelo):
                    o.fonte = self.nome
                    out.setdefault(o.id, o)
        if bloqueado:
            shutil.rmtree(_dir_perfil("ml"), ignore_errors=True)
            MARCA_BLOQUEIO_ML.parent.mkdir(exist_ok=True)
            MARCA_BLOQUEIO_ML.write_text(_t.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
            if not out:
                raise RuntimeError("Mercado Livre pediu verificação anti-bot no catálogo do PS5; próxima tentativa em 2 h")
        return list(out.values()), []


def _achar_lista(obj: Any, pred: Callable[[Any], bool], prof: int = 0) -> list[Any]:
    """Procura, em profundidade, listas cujos itens satisfaçam pred."""
    if prof > 8:
        return []
    if isinstance(obj, list):
        if obj and all(pred(x) for x in obj[:3]):
            return obj
        for x in obj:
            r = _achar_lista(x, pred, prof + 1)
            if r:
                return r
    elif isinstance(obj, dict):
        for v in obj.values():
            r = _achar_lista(v, pred, prof + 1)
            if r:
                return r
    return []
