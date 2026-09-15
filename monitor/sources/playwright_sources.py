"""Lojas que exigem navegador real (Akamai / anti-bot). Rodam só no PC, com o Chrome instalado.

Estratégia comum: abrir a página com um perfil persistente do Chrome, esperar carregar, e extrair
o que der: JSON-LD schema.org, __NEXT_DATA__/estado embutido, respostas JSON interceptadas e,
por fim, o texto renderizado. Cada loja é "melhor esforço": se falhar, a saúde da fonte registra.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .. import config
from ..filtro import eh_55c6k
from ..models import Oferta
from ..util import jsonld_produtos, limpa_html, loja_canonica, parcelado_no_texto, parse_preco, precos_no_texto
from . import Fonte, Pular, Resultado

PERFIL = config.RAIZ / ".pw-profile"
MARCA_BLOQUEIO_ML = config.RAIZ / "logs" / "ml_bloqueado_em"   # existe enquanto o ML estiver "de castigo"
ESPERA_ML_SEGUNDOS = 2 * 3600


def _dir_perfil(perfil: str) -> Path:
    return PERFIL if perfil == "default" else config.RAIZ / f".pw-profile-{perfil}"


def _abrir(url: str, esperar: str | None = None, capturar: list[str] | None = None,
           scroll: bool = False, timeout_ms: int = 45000, headless: bool | None = None,
           perfil: str = "default") -> tuple[str, str, list[Any]]:
    """Abre a URL no Chrome e devolve (html, texto visível, JSONs capturados).

    Por padrão roda com janela (headed): o Akamai bloqueia o Chrome headless. PW_HEADLESS=1 força headless.
    `perfil` escolhe a pasta do perfil do Chrome (lojas que marcam o perfil ficam isoladas das outras).
    """
    import os
    from playwright.sync_api import sync_playwright

    if headless is None:
        headless = os.environ.get("PW_HEADLESS", "0") == "1"
    capturados: list[Any] = []
    padroes = capturar or []
    pasta = _dir_perfil(perfil)
    pasta.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(pasta), channel="chrome", headless=headless, locale="pt-BR", timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 900},
            # janela fora da tela: o Chrome precisa estar "visível" para passar no Akamai, mas não atrapalha
            args=["--disable-blink-features=AutomationControlled", "--window-position=-32000,-32000"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_response(resp):
            try:
                if any(p in resp.url for p in padroes) and "json" in (resp.headers.get("content-type") or ""):
                    capturados.append({"url": resp.url, "json": resp.json()})
            except Exception:
                pass

        if padroes:
            page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
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
        ctx.close()
    return html, texto, capturados


def _oferta_jsonld(html: str, fonte: str, loja: str, url: str, oid: str) -> Oferta | None:
    for prod in jsonld_produtos(html):
        nome = prod.get("name") or ""
        if not eh_55c6k(nome):
            continue
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
                          preco=preco, ativo=("OutOfStock" not in disp and "SoldOut" not in disp), vendedor=vend)
    return None


class CasasBahia(Fonte):
    nome = "casasbahia"
    modo = "pc"

    def coletar(self) -> Resultado:
        html, texto, _ = _abrir(config.URL_CASASBAHIA_PRODUTO, esperar="h1")
        if "Access Denied" in html[:3000] or "Reference #" in texto[:500]:
            raise RuntimeError("Casas Bahia bloqueou (Akamai)")
        o = _oferta_jsonld(html, "casasbahia", "Casas Bahia", config.URL_CASASBAHIA_PRODUTO, "55069456")
        if o is None:
            # fallback: título + preços do texto renderizado
            m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            titulo = limpa_html(m.group(1)) if m else ""
            if not eh_55c6k(titulo):
                return [], []
            precos = [p for p in precos_no_texto(texto) if p >= 1500]
            if not precos:
                return [Oferta(fonte="casasbahia", tipo="loja", loja="Casas Bahia", titulo=titulo,
                               url=config.URL_CASASBAHIA_PRODUTO, id="55069456", ativo=False)], []
            o = Oferta(fonte="casasbahia", tipo="loja", loja="Casas Bahia", titulo=titulo,
                       url=config.URL_CASASBAHIA_PRODUTO, id="55069456", preco=min(precos))
        mpix = re.search(r"R\$\s?([\d.]+,\d{2})\s*(?:no|à vista no|via)?\s*pix", texto, re.I)
        if mpix:
            pix = parse_preco(mpix.group(1))
            if pix and o.preco and pix < o.preco:
                o.preco_pix = pix
        o.parcelado = o.parcelado or parcelado_no_texto(texto)
        if "indisponível" in texto.lower()[:5000] and "produto indisponível" in texto.lower():
            o.ativo = False
        return [o], []


class MercadoLivre(Fonte):
    """O ML marca perfis automatizados e passa a exigir login. Usa um perfil só dele, recriado quando bloqueado.
    Falhas aqui não geram aviso: as ofertas do ML também chegam via Promobit, Pelando e Telegram."""

    nome = "mercadolivre"
    modo = "pc"
    alerta_falha = False

    @staticmethod
    def _bloqueado(html: str, texto: str) -> bool:
        return "suspicious-traffic" in html[:8000] or "Hubo un error" in texto[:300] or "Para continuar, acesse" in texto[:300]

    def coletar(self) -> Resultado:
        import shutil
        import time as _t

        if MARCA_BLOQUEIO_ML.exists():
            restante = ESPERA_ML_SEGUNDOS - (_t.time() - MARCA_BLOQUEIO_ML.stat().st_mtime)
            if restante > 0:
                raise Pular(f"bloqueado pelo ML; nova tentativa em {restante/60:.0f} min")
        html, texto, _ = _abrir(config.URL_ML_CATALOGO, esperar=".ui-pdp-price, .andes-money-amount", perfil="ml")
        if self._bloqueado(html, texto):
            html2, texto2, _ = _abrir(config.URL_ML_BUSCA, esperar=".ui-search-result, .poly-card", perfil="ml")
            itens = [] if self._bloqueado(html2, texto2) else self._parse_lista(html2)
            if itens:
                MARCA_BLOQUEIO_ML.unlink(missing_ok=True)
                return itens, []
            shutil.rmtree(_dir_perfil("ml"), ignore_errors=True)  # perfil marcado: começa do zero na próxima
            MARCA_BLOQUEIO_ML.parent.mkdir(exist_ok=True)
            MARCA_BLOQUEIO_ML.write_text(_t.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
            raise RuntimeError("Mercado Livre pediu verificação anti-bot; próxima tentativa em 2 h")
        MARCA_BLOQUEIO_ML.unlink(missing_ok=True)
        out: list[Oferta] = []
        o = _oferta_jsonld(html, "mercadolivre", "Mercado Livre", config.URL_ML_CATALOGO, "MLB48808732")
        if o is None:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            titulo = limpa_html(m.group(1)) if m else ""
            if eh_55c6k(titulo):
                mp = re.search(r'"price":\s*([\d.]+)', html)
                preco = parse_preco(mp.group(1)) if mp else None
                if not preco:
                    precos = [p for p in precos_no_texto(texto) if p >= 1500]
                    preco = min(precos) if precos else None
                if preco:
                    o = Oferta(fonte="mercadolivre", tipo="loja", loja="Mercado Livre", titulo=titulo,
                               url=config.URL_ML_CATALOGO, id="MLB48808732", preco=preco)
        if o:
            mv = re.search(r"Vendido por\s+([^\n]{2,60})", texto)
            if mv:
                o.vendedor = mv.group(1).strip()
            o.parcelado = o.parcelado or parcelado_no_texto(texto)
            mpix = re.search(r"([\d.]+,\d{2})\s*(?:no|com)\s*pix", texto, re.I)
            if mpix:
                pix = parse_preco(mpix.group(1))
                if pix and o.preco and pix < o.preco:
                    o.preco_pix = pix
            out.append(o)
        return out, []

    @staticmethod
    def _parse_lista(html: str) -> list[Oferta]:
        """Resultados da busca do ML: título, preço (inteiro + centavos em spans separados) e link."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        out: dict[str, Oferta] = {}
        for card in soup.select("li.ui-search-layout__item, div.poly-card, .ui-search-result__wrapper"):
            t = card.select_one("a.poly-component__title, h2.poly-box, h2.ui-search-item__title, h3.poly-component__title-wrapper")
            if not t:
                continue
            titulo = t.get_text(" ", strip=True)
            if not eh_55c6k(titulo):
                continue
            link_el = t if t.name == "a" else card.select_one("a[href*='mercadolivre.com.br']")
            url = (link_el.get("href") or "") if link_el else ""
            url = url.split("#")[0].split("?")[0]
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
            vend = card.select_one(".poly-component__seller")
            oid = re.search(r"(MLB-?\d+)", url)
            oid_s = oid.group(1).replace("-", "") if oid else url[-40:]
            out.setdefault(oid_s, Oferta(
                fonte="mercadolivre", tipo="loja", loja="Mercado Livre", titulo=titulo, url=url or config.URL_ML_BUSCA,
                id=oid_s, preco=min(precos), parcelado=parcelado_no_texto(card.get_text(" ", strip=True)),
                vendedor=vend.get_text(" ", strip=True).replace("Por ", "") if vend else None,
            ))
        return list(out.values())


class AliExpress(Fonte):
    """Busca no AliExpress (inclui a loja da Magalu e a loja oficial TCL). Melhor esforço."""

    nome = "aliexpress"
    modo = "pc"

    def coletar(self) -> Resultado:
        html, texto, _ = _abrir(config.URL_ALIEXPRESS_BUSCA, scroll=True)
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
                    if not eh_55c6k(titulo):
                        continue
                    prices = it.get("prices") or {}
                    sale = (prices.get("salePrice") or {}).get("minPrice") or (prices.get("salePrice") or {}).get("formattedPrice")
                    preco = parse_preco(sale)
                    loja = (it.get("store") or {}).get("storeName") or "AliExpress"
                    pid = str(it.get("productId"))
                    out[pid] = Oferta(fonte="aliexpress", tipo="loja", loja="AliExpress", titulo=titulo,
                                      url=f"https://pt.aliexpress.com/item/{pid}.html", id=pid, preco=preco, vendedor=loja)
        # 2) fallback: cartões renderizados
        if not out:
            for card in re.finditer(r'<a[^>]+href="([^"]*?/item/(\d+)\.html[^"]*)"[^>]*>(.*?)</a>', html, re.S):
                bloco = limpa_html(card.group(3))
                if not eh_55c6k(bloco):
                    continue
                precos = [p for p in precos_no_texto(bloco) if p >= 1000]
                pid = card.group(2)
                out.setdefault(pid, Oferta(fonte="aliexpress", tipo="loja", loja="AliExpress", titulo=bloco[:140],
                                           url=f"https://pt.aliexpress.com/item/{pid}.html", id=pid,
                                           preco=min(precos) if precos else None))
        return list(out.values()), []


class Shopee(Fonte):
    """Busca na Shopee interceptando a resposta JSON da API interna. Melhor esforço (pode exigir login)."""

    nome = "shopee"
    modo = "pc"

    def coletar(self) -> Resultado:
        import os
        if os.environ.get("SHOPEE", "0") != "1":
            return [], []  # a busca da Shopee exige login; ligue com SHOPEE=1 no .env se quiser tentar
        _, texto, capt = _abrir(config.URL_SHOPEE_BUSCA, capturar=["/api/v4/search/search_items"], scroll=True)
        out: dict[str, Oferta] = {}
        for c in capt:
            for it in (c["json"].get("items") or []):
                b = it.get("item_basic") or it
                nome = b.get("name") or ""
                if not eh_55c6k(nome):
                    continue
                preco = (b.get("price") or 0) / 100000 or None
                iid, sid = b.get("itemid"), b.get("shopid")
                out[str(iid)] = Oferta(fonte="shopee", tipo="loja", loja="Shopee", titulo=nome,
                                       url=f"https://shopee.com.br/product/{sid}/{iid}", id=str(iid), preco=preco,
                                       vendedor=b.get("shop_name") or None)
        if not out and ("login" in texto.lower()[:2000] or "entrar" in texto.lower()[:2000]):
            raise RuntimeError("Shopee exigiu login para buscar")
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
