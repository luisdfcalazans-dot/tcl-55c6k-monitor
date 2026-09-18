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
from ..util import fmt_preco, jsonld_produtos, limpa_html, loja_canonica, parse_preco, precos_no_texto
from ..trava import PerfilOcupado, trava_perfil
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
    try:
        trava = trava_perfil(pasta, espera_s=30)
        trava.__enter__()
    except PerfilOcupado as e:
        raise Pular(str(e)) from None
    try:
        return _abrir_no_perfil(url, pasta, headless, padroes, capturados, esperar, scroll, timeout_ms)
    finally:
        trava.__exit__(None, None, None)


def _abrir_no_perfil(url, pasta, headless, padroes, capturados, esperar, scroll, timeout_ms):
    from playwright.sync_api import sync_playwright

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


_ID_CASASBAHIA = "55069456"
_RE_CB_CARTAO = re.compile(r"^[^\n]*?R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})[^\n]*cart[ãa]o de cr[ée]dito", re.I | re.M)
_RE_CB_PIX = re.compile(r"R\$\s?([\d.]+,\d{2})\s*(?:no|à vista no|via)?\s*pix", re.I)


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


def _cb_precos_embutidos(html: str) -> tuple[float | None, float | None, str | None]:
    """(cartão, Pix, parcelado sem juros) do estado embutido "ProductPrice" da página da Casas Bahia.

    O price do JSON-LD é o preço no Pix (10% off); o de cartão ("por R$ 3.998,99 ... no cartão") só
    aparece aqui: sellPrice.priceWithoutDiscount, e o Pix em paymentMethodDiscount.sellPriceWithDiscount.
    """
    pp = _json_apos(html, '"ProductPrice":')
    if not isinstance(pp, dict):
        return None, None, None
    sp = pp.get("sellPrice") if isinstance(pp.get("sellPrice"), dict) else {}
    if sp.get("skuId") and str(sp.get("skuId")) != _ID_CASASBAHIA:
        return None, None, None  # preço de outro item
    cond = pp.get("cardConditions") if isinstance(pp.get("cardConditions"), dict) else {}
    cartao = parse_preco(sp.get("priceWithoutDiscount")) or parse_preco(cond.get("cash")) or parse_preco(sp.get("priceValue"))
    pmd = pp.get("paymentMethodDiscount") if isinstance(pp.get("paymentMethodDiscount"), dict) else {}
    pix = None
    if pmd.get("hasDiscount") and "pix" in str(pmd.get("discountDescription") or "").lower():
        pix = parse_preco(pmd.get("sellPriceWithDiscount"))
    return cartao, pix, _cb_parcelado_embutido(pp)


class CasasBahia(Fonte):
    nome = "casasbahia"
    modo = "pc"

    def coletar(self) -> Resultado:
        html, texto, _ = _abrir(config.URL_CASASBAHIA_PRODUTO, esperar="h1")
        if "Access Denied" in html[:3000] or "Reference #" in texto[:500]:
            raise RuntimeError("Casas Bahia bloqueou (Akamai)")
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        titulo = limpa_html(m.group(1)) if m else ""
        if titulo and not eh_55c6k(titulo):
            return [], []
        esgotado = _esgotado_jsonld(html)
        o = _oferta_jsonld(html, "casasbahia", "Casas Bahia", config.URL_CASASBAHIA_PRODUTO, "55069456")
        if o is not None and not o.preco:
            o = None
        if o is None:
            if esgotado or not titulo:
                # esgotado: sem preço. NUNCA cair para o texto da página, que tem o carrossel
                # de recomendados e já trouxe o preço de outra TV como se fosse esta.
                return [Oferta(fonte="casasbahia", tipo="loja", loja="Casas Bahia",
                               titulo=titulo or "Smart TV TCL 55C6K", url=config.URL_CASASBAHIA_PRODUTO,
                               id="55069456", ativo=False, extra={"motivo": "esgotado"})], []
            precos = _precos_do_bloco_principal(texto)
            if not precos:
                return [Oferta(fonte="casasbahia", tipo="loja", loja="Casas Bahia", titulo=titulo,
                               url=config.URL_CASASBAHIA_PRODUTO, id="55069456", ativo=False)], []
            o = Oferta(fonte="casasbahia", tipo="loja", loja="Casas Bahia", titulo=titulo,
                       url=config.URL_CASASBAHIA_PRODUTO, id="55069456", preco=min(precos))
        # cartão x Pix: o JSON-LD traz o preço do Pix. Primeiro o estado embutido; sem ele, o texto
        # do bloco do produto (nunca a página toda: os patrocinados têm preço e parcela de outras TVs).
        topo = _bloco_principal(texto)
        cartao, pix, parcelado = _cb_precos_embutidos(html)
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
        return [o], []


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
    itens = bb.get("items") if isinstance(bb, dict) else None
    out: list[dict] = []
    for it in itens or []:
        if not isinstance(it, dict) or not it.get("item_id"):
            continue
        op: dict[str, Any] = {"item_id": str(it["item_id"]), "tipo": it.get("type"),
                              "selecionada": bool(it.get("selected"))}
        for comp in it.get("components") or []:
            if not isinstance(comp, dict) or comp.get("state") == "HIDDEN":
                continue
            if comp.get("id") == "price" and isinstance(comp.get("price"), dict):
                op["preco"] = parse_preco(comp["price"].get("value"))
                op["preco_de"] = parse_preco(comp["price"].get("original_value"))
                op["desconto"] = bool(comp.get("discount_label"))
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
            out.extend(self._por_opcao(o, html, sel))
        return out, []

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
                           url=o.url, id="", preco=op["preco"])
                if op.get("desconto") and op.get("preco_de") and op["preco_de"] > op["preco"] + 0.005:
                    x.preco, x.preco_pix = op["preco_de"], op["preco"]
                x.parcelado = op.get("parcelado")
                x.vendedor = op.get("vendedor")
            x.id = op["item_id"]
            x.extra["opcao_ml"] = op.get("tipo")
            out.append(x)
        return out

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
            texto_card = _junta_precos(card.get_text(" ", strip=True))
            preco, pix = min(precos), None
            mo = _RE_ML_OUTROS_MEIOS.search(texto_card)
            outros = parse_preco(mo.group(1)) if mo else None
            if outros and outros > preco + 0.005:
                # "R$ 4.072 no Pix ou R$ 4.197 em outros meios": o preço em destaque é o do Pix
                preco, pix = outros, preco
            vend = card.select_one(".poly-component__seller")
            oid = re.search(r"(MLB-?\d+)", url)
            oid_s = oid.group(1).replace("-", "") if oid else url[-40:]
            out.setdefault(oid_s, Oferta(
                fonte="mercadolivre", tipo="loja", loja="Mercado Livre", titulo=titulo, url=url or config.URL_ML_BUSCA,
                id=oid_s, preco=preco, preco_pix=pix, parcelado=_parcelado_sem_juros(texto_card),
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
                # o preço de venda vem em spans separados ("R$ 3 . 499"): sem colar, sobrava só o riscado
                bloco = _junta_precos(limpa_html(card.group(3)))
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
