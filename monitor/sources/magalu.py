"""Magazine Luiza via o espelho magazinevoce.com.br (mesmo catálogo, sem bloqueio Akamai).

Descoberta (19/09/2026, pedido do usuário: "não precisa se ater a somente um anúncio"):
- várias buscas (config.MAGALU_TERMOS), com a página seguinte quando há e a 1ª trouxe a TV;
- os anúncios da 55C6K vistos nos últimos 14 dias (docs/data/state_cloud.json, só leitura) e os
  fixos de config.MAGALU_ANUNCIOS_EXTRA, usando o slug guardado (slug falso dá 404 no magazinevoce);
- a página de cada anúncio: uma Oferta por vendedor em product.offers (não só o do buy box);
- para vendedor que não é o do buy box, a página com ?seller_id=<id> (o seletor que o site usa)
  completa cartão, parcelado e cupons, se sobrar requisição.
Ordem: buscas, anúncio fixo, os da busca, os do EXTRA, páginas de vendedor, e só então os do estado (muitos já
saíram do ar). Tudo com limite de requisições por rodada (config.MAGALU_MAX_REQUISICOES) e pausa entre elas;
403/429 encerra a rodada na hora. Duas variações de 55" do mesmo grupo e vendedor têm o mesmo id: fica a mais
barata.
Cupons do anúncio: seller.tags type=coupon (ex.: LU250), como antes.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import quote_plus

import requests

from .. import config
from ..filtro import eh_55c6k
from ..models import Cupom, Oferta
from ..util import dias_desde, get_html, iso_normaliza, next_data, parse_preco
from . import Fonte, Resultado

BASE_MV = "https://www.magazinevoce.com.br/magazinecanaltechbr"
_RE_ID = re.compile(r"/p/([0-9a-z]+)(?:/|$|\?)", re.I)


def _url_magalu(path: str) -> str:
    # "/magazinecanaltechbr/slug/p/123/et/elit/" -> "https://www.magazineluiza.com.br/slug/p/123/et/elit/"
    p = re.sub(r"^/[^/]+/", "/", path or "")
    return "https://www.magazineluiza.com.br" + p


def _url_mv(url: str) -> str:
    """URL do magazinevoce para um anúncio (aceita URL do magazineluiza.com.br ou path do magazinevoce)."""
    u = (url or "").split("#")[0]
    if u.startswith("https://www.magazinevoce.com.br/"):
        return u
    if u.startswith("/magazinecanaltechbr/"):
        return "https://www.magazinevoce.com.br" + u
    path = re.sub(r"^https?://[^/]+", "", u)
    return BASE_MV + (path if path.startswith("/") else "/" + path)


def id_anuncio(url: str) -> str:
    """Id do anúncio no Magalu = o <id> de /p/<id>/ (é o que a sacola devolve como item)."""
    m = _RE_ID.search(url or "")
    return m.group(1) if m else ""


def com_vendedor(url: str, vendedor_id: str) -> str:
    """URL do anúncio com o vendedor escolhido (?seller_id=<id>, o mesmo seletor do site)."""
    base = (url or "").split("#")[0].split("?")[0]
    return f"{base}?seller_id={vendedor_id}" if vendedor_id else base


def _parcelado(inst: dict) -> str | None:
    if inst.get("quantity") and inst.get("amount"):
        sj = " sem juros" if str(inst.get("interest", "0")).startswith("0") else ""
        return f"{inst['quantity']}x R$ {str(inst['amount']).replace('.', ',')}{sj}"
    return None


# a variação do Magalu é de TAMANHO? ("Polegadas"/inch, ou valor como 55", 55 pol, 55 polegadas)
_RE_VARIACAO_TAMANHO = re.compile(r"polegad|\binch\b|tamanho", re.I)
_RE_VALOR_POLEGADAS = re.compile(r"(?<!\d)\d{2,3}\s*(?:[\"”″]|''|pol)", re.I)


def _variacao_de_tamanho(v: dict) -> bool:
    """Só numa variação de tamanho o valor ('55"') diz o tamanho do produto.

    Se o Magalu passar a variar cor/voltagem/combo, decidir por ela apagaria o anúncio inteiro da coleta,
    sem aviso nenhum — aí quem decide é o título (19/09, item B2)."""
    if _RE_VARIACAO_TAMANHO.search(f"{v.get('label') or ''} {v.get('type') or ''}"):
        return True
    return bool(_RE_VALOR_POLEGADAS.search(str(v.get("value") or "")))


def _e_55(p: dict) -> bool:
    """Só a 55C6K de 55": título e, quando o produto lista variações DE TAMANHO, a variação desta página."""
    if not eh_55c6k(p.get("title") or ""):
        return False
    var_id = str(p.get("variationId") or "")
    for v in p.get("variations") or []:
        if isinstance(v, dict) and str(v.get("id")) == var_id and v.get("value") and _variacao_de_tamanho(v):
            return re.search(r"(?<!\d)55(?!\d)", str(v["value"])) is not None
    return True


def _ficha_tecnica(p: dict) -> dict[str, str]:
    """Ficha técnica do anúncio (product.factsheet) achatada: {nome do campo sem acento, minúsculo: valor}."""
    from ..util import sem_acentos

    out: dict[str, str] = {}

    def visita(no: dict) -> None:
        for e in no.get("elements") or []:
            if not isinstance(e, dict):
                continue
            if e.get("keyName") and e.get("elements"):
                vals = [str(x.get("value")) for x in e["elements"]
                        if isinstance(x, dict) and not x.get("isHtml") and x.get("value") not in (None, "")]
                if vals:
                    out.setdefault(sem_acentos(str(e["keyName"])).lower().strip(), " | ".join(vals)[:120])
            visita(e)

    for secao in p.get("factsheet") or []:
        if isinstance(secao, dict):
            visita(secao)
    return out


def _dados_do_vendedor(seller: dict) -> dict:
    """Razão social, desde quando vende, vendas e nota do vendedor (seller.details), para a checagem de confiança."""
    det = (seller or {}).get("details") or {}
    if not isinstance(det, dict):
        return {}
    out: dict = {}
    if det.get("legalName"):
        out["razao_social"] = str(det["legalName"])[:80]
    if det.get("sellerSince"):
        out["vendedor_desde"] = str(det["sellerSince"])[:10]
    for campo, chave in (("totalSales", "vendas_vendedor"), ("score", "nota_vendedor")):
        if isinstance(det.get(campo), (int, float)):
            out[chave] = det[campo]
    return out


def _ficha(p: dict) -> dict:
    """O que a página (ou a busca) já traz para checar a legitimidade do anúncio sem requisição extra: homologação
    Anatel, modelo e tamanho da ficha, avaliações, peso e os dados do vendedor. Ver monitor/confianca.py (caso de
    25/09/2026: Anatel de celular, modelo 'Vários', 0 avaliações, peso 0,1 kg, loja de outro ramo)."""
    f: dict = {}
    ft = _ficha_tecnica(p)
    for k, v in ft.items():
        if "anatel" in k and "anatel" not in f:
            f["anatel"] = v
    modelo = ft.get("modelo") or ft.get("referencia")
    if modelo:
        f["modelo"] = modelo
    tam = ft.get("polegadas") or ft.get("tamanho da tela") or ft.get("tamanho")
    if not tam:
        for a in p.get("attributes") or []:
            if isinstance(a, dict) and _variacao_de_tamanho({"label": a.get("label"), "type": a.get("type"),
                                                             "value": a.get("current")}) and a.get("current"):
                tam = str(a["current"])
                break
    if tam:
        f["tamanho"] = tam
    rating = p.get("rating")
    if isinstance(rating, dict) and isinstance(rating.get("count"), (int, float)):
        f["avaliacoes"] = int(rating["count"])
    dims = p.get("dimensions")
    if isinstance(dims, dict) and isinstance(dims.get("weight"), (int, float)) and dims["weight"] > 0:
        f["peso_kg"] = dims["weight"]
    f.update(_dados_do_vendedor(p.get("seller") or {}))
    return f


def _oferta(p: dict) -> Oferta | None:
    """Oferta do vendedor do buy box (o que a página/busca mostra com preço, Pix e parcelado)."""
    titulo = p.get("title") or ""
    if not eh_55c6k(titulo) or not p.get("available", True):
        return None
    price = p.get("price") or {}
    inst = p.get("installment") or {}
    seller = p.get("seller") or {}
    vendedor = seller.get("description") or seller.get("id") or "?"
    cartao = parse_preco(price.get("fullPrice"))
    pix = parse_preco(price.get("bestPrice"))
    url = _url_magalu(p.get("path") or p.get("url") or "")
    return Oferta(
        fonte="magalu", tipo="loja", loja="Magazine Luiza", titulo=titulo,
        url=url, id=f"{p.get('id')}-{seller.get('id') or vendedor}",
        preco=cartao, preco_pix=pix if pix and cartao and pix < cartao else (pix if not cartao else None),
        parcelado=_parcelado(inst), vendedor=vendedor,
        extra={"preco_de": parse_preco(price.get("price")), "1p": seller.get("category") == "1p",
               "anuncio": id_anuncio(url), "vendedor_id": seller.get("id") or None, "ficha": _ficha(p)},
    )


def _oferta_vendedor(p: dict, of: dict) -> Oferta | None:
    """Oferta de um vendedor da lista product.offers que NÃO é o do buy box.

    A lista só traz o preço do Pix (bestPrice, "no Pix") e o preço "de"; o do cartão costuma vir null.
    Sem o do cartão, ele fica vazio (nunca repetir o do Pix como se fosse cartão) e o parcelado também.
    """
    sel = of.get("seller") or {}
    sid = sel.get("id")
    if not sid:
        return None
    price = of.get("price") or {}
    melhor = parse_preco(price.get("bestPrice"))
    cheio = parse_preco(price.get("fullPrice"))
    eh_pix = "pix" in str(price.get("paymentMethodDescription") or "").lower()
    if eh_pix:
        cartao, pix = cheio, melhor
        if pix and cartao and pix >= cartao:
            pix = None
    else:
        cartao, pix = cheio or melhor, None
    if not (cartao or pix):
        return None
    url = com_vendedor(_url_magalu(p.get("path") or p.get("url") or ""), sid)
    return Oferta(
        fonte="magalu", tipo="loja", loja="Magazine Luiza", titulo=p.get("title") or "",
        url=url, id=f"{p.get('id')}-{sid}", preco=cartao, preco_pix=pix,
        vendedor=sel.get("description") or sid,
        extra={"preco_de": parse_preco(price.get("price")), "1p": sel.get("category") == "1p",
               "anuncio": id_anuncio(url), "vendedor_id": sid, "so_lista_de_vendedores": True,
               # a ficha da página é do anúncio do buy box: deste vendedor só os dados dele
               "ficha": _dados_do_vendedor(sel)},
    )


def _cupons(p: dict) -> list[Cupom]:
    cupons: list[Cupom] = []
    for tag in (p.get("seller") or {}).get("tags") or []:
        if tag.get("type") == "coupon" and tag.get("code"):
            cupons.append(Cupom(
                fonte="magalu", loja="Magazine Luiza", codigo=tag["code"], titulo=tag.get("message") or tag["code"],
                url=_url_magalu(p.get("path") or ""), id=f"{tag['code']}-{(tag.get('endDate') or '')[:10]}",
                regra=tag.get("message") or "", validade=iso_normaliza(tag.get("endDate")),
                publicado=iso_normaliza(tag.get("startDate")), especifico=True,
            ))
    return cupons


def _aplica_cupom(o: Oferta, p: dict, cupons: list[Cupom]) -> None:
    """Cupom do anúncio na oferta e o preço estimado com o primeiro cupom de valor absoluto."""
    if not cupons:
        return
    o.cupom = cupons[0].codigo
    for tag in (p.get("seller") or {}).get("tags") or []:
        if tag.get("type") == "coupon" and tag.get("discountType") == "absolute" and tag.get("discountValue"):
            base = o.preco_pix or o.preco
            if base:
                o.extra["preco_com_cupom"] = round(base - float(tag["discountValue"]), 2)
                o.extra["cupom_regra"] = cupons[0].regra
            break


def _dados(html: str) -> dict:
    nd = next_data(html) or {}
    return ((nd.get("props") or {}).get("pageProps") or {}).get("data") or {}


def info_busca(html: str) -> tuple[list[dict], int, int]:
    """(produtos, página, total de páginas) da busca do magazinevoce."""
    s = _dados(html).get("search") or {}
    pag = s.get("pagination") or {}
    try:
        pagina, paginas = int(pag.get("page") or 1), int(pag.get("pages") or 1)
    except (TypeError, ValueError):
        pagina, paginas = 1, 1
    return [p for p in s.get("products") or [] if isinstance(p, dict)], pagina, paginas


def parse_busca(html: str) -> list[Oferta]:
    out = []
    for p in info_busca(html)[0]:
        o = _oferta(p) if _e_55(p) else None
        if o:
            out.append(o)
    return out


def parse_produto(html: str) -> tuple[Oferta | None, list[Cupom]]:
    """Oferta do vendedor do buy box e os cupons do anúncio (compatível com a versão de 13/09)."""
    p = _dados(html).get("product") or {}
    if not p:
        return None, []
    o = _oferta(p) if _e_55(p) else None
    cupons = _cupons(p)
    if o:
        _aplica_cupom(o, p, cupons)
    return o, cupons


def parse_produto_todas(html: str) -> tuple[list[Oferta], list[Cupom], list[str]]:
    """Todas as ofertas de um anúncio: o buy box (completo) e cada outro vendedor de product.offers.

    Devolve (ofertas, cupons, paths de outras variações de 55" disponíveis). Produto indisponível,
    de outro tamanho ou que não é a 55C6K devolve listas vazias.
    """
    p = _dados(html).get("product") or {}
    if not p or not p.get("available", True) or not _e_55(p):
        return [], [], []
    principal, cupons = parse_produto(html)
    ofertas: list[Oferta] = [principal] if principal else []
    buybox = ((p.get("seller") or {}).get("id")) or ""
    vistos = {buybox}
    for of in p.get("offers") or []:
        if not isinstance(of, dict):
            continue
        sid = (of.get("seller") or {}).get("id") or ""
        if not sid or sid in vistos:
            continue
        vistos.add(sid)
        o = _oferta_vendedor(p, of)
        if o:
            ofertas.append(o)
    var_id = str(p.get("variationId") or "")
    variacoes = []
    for v in p.get("variations") or []:
        if not isinstance(v, dict) or str(v.get("id")) in ("", var_id) or not v.get("available", True):
            continue
        if not _variacao_de_tamanho(v):
            continue   # cor/voltagem/combo não é "outro tamanho" para visitar (19/09, item B2)
        if re.search(r"(?<!\d)55(?!\d)", str(v.get("value") or "")) and eh_55c6k((v.get("path") or "").replace("-", " ")):
            variacoes.append("/magazinecanaltechbr/" + str(v["path"]).lstrip("/"))
    return ofertas, cupons, variacoes


def anuncios_do_estado(dias: float = 14.0, arquivo=None) -> list[str]:
    """URLs dos anúncios do Magalu vistos nos últimos `dias` dias (mais recentes primeiro). Só leitura."""
    arq = arquivo or (config.DIR_DADOS / "state_cloud.json")
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    regs = []
    for chave, reg in (dados.get("ofertas") or {}).items():
        if not str(chave).startswith("magalu:") or not isinstance(reg, dict) or reg.get("tipo") != "loja":
            continue
        idade = dias_desde(reg.get("ultima_vez"))
        if idade is None or idade > dias or not id_anuncio(reg.get("url") or ""):
            continue
        regs.append((reg.get("ultima_vez") or "", reg["url"]))
    regs.sort(reverse=True)
    return [u for _, u in regs]


def _seller_da_url(url: str) -> str:
    m = re.search(r"[?&]seller_id=([^&#]+)", url or "")
    return m.group(1) if m else ""


def _guarda(por_id: dict[str, Oferta], o: Oferta) -> None:
    """Grava a oferta pelo id, sem perder a mais barata quando dois anúncios diferentes dão o mesmo id.

    O id é '<product.id>-<vendedor>' e product.id é o do GRUPO de variações (240162800 para a página
    /p/240162700/): duas variações de 55" do mesmo grupo e do mesmo vendedor dariam o mesmo id. Aí fica a mais
    barata. Do MESMO anúncio (/p/), a leitura mais nova substitui (a página completa o que veio da busca)."""
    atual = por_id.get(o.id)
    if atual is None or atual.extra.get("anuncio") == o.extra.get("anuncio") or \
            (o.melhor_preco or 9e9) < (atual.melhor_preco or 9e9):
        por_id[o.id] = o


class _Orcamento:
    """Conta as requisições da rodada e faz a pausa entre elas (educação com o site)."""

    def __init__(self, maximo: int, pausa_s: float):
        self.maximo, self.pausa_s, self.usadas = maximo, pausa_s, 0
        self.bloqueado = False

    @property
    def sobra(self) -> int:
        return 0 if self.bloqueado else self.maximo - self.usadas

    def get(self, url: str) -> str | None:
        """HTML da URL; None quando acabou o orçamento ou o anúncio não existe mais (404/410).

        403/429 (bloqueio ou excesso de requisições): o orçamento da rodada acaba na hora e o erro sobe.
        Insistir só piora o bloqueio."""
        if self.sobra <= 0:
            return None
        if self.usadas:
            time.sleep(self.pausa_s)
        self.usadas += 1
        try:
            return get_html(url, tentativas=1)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):
                return None
            if status in (403, 429):
                self.bloqueado = True
            raise


class Magalu(Fonte):
    nome = "magalu"

    def coletar(self) -> Resultado:
        orc = _Orcamento(config.MAGALU_MAX_REQUISICOES, config.MAGALU_PAUSA_S)
        erros: list[str] = []
        por_id: dict[str, Oferta] = {}
        cupons: dict[str, Cupom] = {}
        # anúncio -> URL do magazinevoce; a ordem do dicionário é a prioridade de visita
        principal = _url_mv(config.URL_MAGALU_PRODUTO)
        candidatos: dict[str, str] = {id_anuncio(principal): principal}
        da_busca: list[tuple[float, str, str]] = []

        def tenta(url: str) -> str | None:
            try:
                return orc.get(url)
            except Exception as e:  # noqa: BLE001 - rede/HTTP: registra e segue para o próximo
                erros.append(f"{type(e).__name__}: {e}"[:200])
                return None

        # 1) buscas (com a página seguinte quando a 1ª já trouxe a TV)
        buscas = 0
        for termo in config.MAGALU_TERMOS:
            pagina = 1
            while buscas < config.MAGALU_MAX_BUSCAS:
                url = f"{BASE_MV}/busca/{quote_plus(termo)}/" + (f"?page={pagina}" if pagina > 1 else "")
                buscas += 1
                html = tenta(url)
                if not html:
                    break
                prods, pag, paginas = info_busca(html)
                achou = False
                for p in prods:
                    if not _e_55(p):
                        continue
                    o = _oferta(p)
                    path = p.get("path") or p.get("url") or ""
                    if not o or not id_anuncio(path):
                        continue
                    achou = True
                    _guarda(por_id, o)
                    da_busca.append((o.melhor_preco or 1e9, id_anuncio(path), _url_mv(path)))
                if not (achou and pag < paginas):
                    break
                pagina += 1
        for _, aid, u in sorted(da_busca):
            candidatos.setdefault(aid, u)
        for u in config.MAGALU_ANUNCIOS_EXTRA:
            if id_anuncio(u):
                candidatos.setdefault(id_anuncio(u), _url_mv(u))
        # anúncios que só a memória (estado) conhece: por último, depois das páginas de vendedor (passo 3),
        # porque muitos já saíram do ar e gastariam o orçamento da rodada
        do_estado = [(id_anuncio(u), _url_mv(u)) for u in anuncios_do_estado()
                     if id_anuncio(u) and id_anuncio(u) not in candidatos]

        visitados: set[str] = set()
        pendentes_vendedor: list[tuple[float, Oferta]] = []
        vendedores_feitos: set[str] = set()

        # 2) página de cada anúncio: todos os vendedores (e variações de 55" ainda não vistas)
        def visitar(fila: list[tuple[str, str]]) -> None:
            while fila and orc.sobra > 0:
                aid, url = fila.pop(0)
                if aid in visitados:
                    continue
                visitados.add(aid)
                html = tenta(url)
                if not html:
                    continue
                ofs, cps, variacoes = parse_produto_todas(html)
                pedido = _seller_da_url(url)
                for c in cps:
                    cupons.setdefault(c.chave, c)
                for o in ofs:
                    if pedido and o.extra.get("vendedor_id") == pedido and not _seller_da_url(o.url):
                        # página aberta com ?seller_id (anúncio do estado ou do EXTRA): o link guarda o vendedor,
                        # senão ele abre com o vendedor padrão e o testador não consegue escolher este
                        o.url = com_vendedor(o.url, pedido)
                    _guarda(por_id, o)
                    if o.extra.get("so_lista_de_vendedores"):
                        pendentes_vendedor.append((o.melhor_preco or 1e9, o))
                for path in variacoes:
                    if id_anuncio(path) not in visitados:
                        fila.append((id_anuncio(path), _url_mv(path)))

        # 3) vendedores fora do buy box, do mais barato ao mais caro: a página com ?seller_id completa
        #    cartão, parcelado e cupons deste vendedor
        def completar_vendedores() -> None:
            for _, o in sorted(pendentes_vendedor, key=lambda t: t[0]):
                if orc.sobra <= 0:
                    break
                if o.url in vendedores_feitos or por_id.get(o.id) is not o:
                    continue  # já completado, ou a mesma chave ficou com uma variação mais barata
                vendedores_feitos.add(o.url)
                sid = o.extra.get("vendedor_id") or ""
                html = tenta(com_vendedor(_url_mv(o.url), sid))
                if not html:
                    continue
                det, cps = parse_produto(html)
                if det and det.extra.get("vendedor_id") == sid:
                    det.url = com_vendedor(det.url, sid)
                    det.id = o.id
                    _guarda(por_id, det)
                    for c in cps:
                        cupons.setdefault(c.chave, c)

        visitar(list(candidatos.items()))
        completar_vendedores()
        visitar(do_estado)
        completar_vendedores()

        ofertas = list(por_id.values())
        print(f"[magalu] {orc.usadas} requisições, {len(visitados)} anúncios abertos, {len(ofertas)} ofertas"
              + (f", {len(erros)} erros" if erros else ""))
        if not ofertas and erros:
            raise RuntimeError(f"Magalu: nenhuma oferta; {erros[0]}")
        return ofertas, list(cupons.values())
