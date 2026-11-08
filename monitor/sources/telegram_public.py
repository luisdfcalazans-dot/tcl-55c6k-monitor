"""Canais públicos do Telegram, lidos pela prévia web t.me/s/<canal> (não precisa de conta).

Desde 08/11/2026 a fonte devolve também os cupons citados nos posts (monitor/cupons_telegram.py): linhas de lista de
cupons ("🏷 R$ 785 OFF em R$ 4200: AFFNOV11") e o "Cupom: X" dos posts de produto. Eles vão só para a lista diária
"🎟️ Cupons ativos" (config.FONTES_CUPOM_SO_LISTA), nunca para o alerta de cupom novo."""

from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .. import config, cupons_telegram, produtos
from ..models import MODELO_PADRAO, Cupom, Oferta
from ..util import cupom_no_texto, get_html, iso_normaliza, loja_canonica, parcelado_no_texto, preco_postagem
from . import Fonte, Resultado

# Lojas citadas no texto/links da postagem. As de marketplace que revendem estoque de outras (Netshoes vende o do
# Magalu; Mais Correios tem Ponto Frio, Casas Bahia...) vêm antes: o vendedor citado no texto não é a loja da compra
_LOJAS_NO_TEXTO = [
    ("maiscorreios", "Mais Correios"), ("mais correios", "Mais Correios"), ("netshoes", "Netshoes"),
    ("magazineluiza", "Magazine Luiza"), ("magalu", "Magazine Luiza"), ("amazon", "Amazon"), ("amzn.to", "Amazon"),
    # meli.la: encurtador do Mercado Livre (todos os links de ML do @linguicapromocoes, 08/11/2026)
    ("mercadolivre", "Mercado Livre"), ("mercado livre", "Mercado Livre"), ("meli.la", "Mercado Livre"),
    ("kabum", "KaBuM!"),
    ("casasbahia", "Casas Bahia"), ("casas bahia", "Casas Bahia"), ("fastshop", "Fast Shop"), ("fast shop", "Fast Shop"),
    ("aliexpress", "AliExpress"), ("shopee", "Shopee"), ("pontofrio", "Ponto"), ("ponto frio", "Ponto"),
    ("extra.com", "Extra"), ("carrefour", "Carrefour"), ("americanas", "Americanas"), ("lojatcl", "Loja TCL"),
    # PS5 / GTA 6 (pesquisa de 03/10/2026)
    ("store.playstation.com", "PlayStation Store"), ("playstation store", "PlayStation Store"),
    ("ps store", "PlayStation Store"), ("nuuvem", "Nuuvem"), ("hype games", "Hype"), ("hypegames", "Hype"),
    ("eneba", "Eneba"), ("sams club", "Sam's Club"), ("sam's club", "Sam's Club"), ("samsclub", "Sam's Club"),
    ("terabyte", "Terabyte"), ("inpower", "Inpower"), ("havan", "Havan"), ("loja vivo", "Loja Vivo"),
    ("pichau", "Pichau"), ("ibyte", "iBYTE"),
]
# linha da loja no formato do canal oficial do Pelando (@pelandobr): "📍 Mais Correios"
_RE_LINHA_LOJA = re.compile(r"^\s*📍\s*(.+?)\s*$", re.M)
# domínio de marketplace no link: a loja da compra é ele, mesmo que o texto cite o vendedor de dentro dele ("PS5 vendido
# pela Magalu Store" com link s.click.aliexpress é AliExpress, não Magazine Luiza; revisão de 08/11/2026)
_LOJAS_NO_LINK = (("aliexpress.", "AliExpress"), ("meli.la/", "Mercado Livre"), ("mercadolivre.com", "Mercado Livre"),
                  ("shopee.com", "Shopee"), ("amzn.to/", "Amazon"), ("amazon.com", "Amazon"))


def loja_no_texto(texto: str, links: list[str]) -> str:
    m = _RE_LINHA_LOJA.search(texto or "")
    if m:
        lj = loja_canonica(m.group(1))
        if lj and lj != "?":
            return lj
    no_link = {nome for link in links for chave, nome in _LOJAS_NO_LINK if chave in (link or "").lower()}
    if len(no_link) == 1:
        return no_link.pop()
    alvo = (texto + " " + " ".join(links)).lower()
    for chave, nome in _LOJAS_NO_TEXTO:
        if chave in alvo:
            return nome
    return "?"


def _id_do_post(post: str, produto: str) -> str:
    """Id da postagem por produto: a mesma mensagem com vários produtos vira um id por produto (o da 55C6K é o de
    sempre, sem sufixo)."""
    return post if produto == MODELO_PADRAO else f"{post}#{produto}"


def _mensagens(html: str) -> list[dict]:
    """As mensagens da prévia t.me/s/<canal>: {'post', 'texto' (sem o riscado, como sempre), 'texto_cupons' (com o
    riscado: o código riscado é cupom esgotado), 'links', 'codes' (o que estava em <code>), 'riscados', 'publicado'}."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for msg in soup.select(".tgme_widget_message[data-post]"):
        post = msg.get("data-post") or ""
        txt_el = msg.select_one(".tgme_widget_message_text")
        if not txt_el:
            continue
        for br in txt_el.find_all("br"):
            br.replace_with("\n")
        codes = [c.get_text(" ", strip=True) for c in txt_el.find_all("code")]
        riscados_el = txt_el.find_all(["s", "del", "strike"])
        riscados = [r.get_text(" ", strip=True) for r in riscados_el]
        texto_cupons = re.sub(r"[ \t]{2,}", " ", txt_el.get_text(" ", strip=False))
        texto_cupons = "\n".join(l.strip() for l in texto_cupons.splitlines() if l.strip())
        # preço riscado (<s>/<del>) é o preço antigo "De": fora do texto
        for riscado in riscados_el:
            riscado.decompose()
        # a busca por termo (?q=) destaca o termo com <mark>, que parte o título em pedaços ("Auto  GTA  6"): sem ele, e
        # com os espaços repetidos que os pedaços deixam colapsados (só nessas páginas: a 1ª página fica como sempre)
        destaques = txt_el.find_all("mark")
        for mk in destaques:
            mk.unwrap()
        texto = txt_el.get_text(" ", strip=False)
        if destaques:
            texto = re.sub(r"[ \t]{2,}", " ", texto)
        texto = "\n".join(l.strip() for l in texto.splitlines() if l.strip())
        links = [a.get("href") for a in txt_el.find_all("a", href=True) if "t.me/" not in a.get("href")]
        t = msg.select_one("time[datetime]")
        out.append({"post": post, "texto": texto, "texto_cupons": texto_cupons, "links": links, "codes": codes,
                    "riscados": riscados, "publicado": iso_normaliza(t.get("datetime")) if t else None})
    return out


def _ofertas_da_mensagem(m: dict, canal: str) -> list[Oferta]:
    post, texto, links = m["post"], m["texto"], m["links"]
    loja = loja_canonica(loja_no_texto(texto, links))
    # o filtro de título roda na linha-título (a descrição da TV, com "suporte a HDR10+" e "controle remoto",
    # derrubava postagens legítimas); estado do produto e combo valem em qualquer linha. Um bloco por produto
    # monitorado (55C6K, 65C6K, PS5, GTA 6...): a postagem com vários vira uma oferta por produto, cada uma com o
    # próprio preço
    achados = produtos.extrai_produtos(texto, loja)
    out: list[Oferta] = []
    for produto, (titulo, trecho, preambulo, detalhes) in achados.items():
        # preço, parcelado e cupom saem do trecho sem os valores de outros produtos: numa postagem com várias
        # TVs, o menor valor da mensagem era o de outra TV e virava alerta 🎯 falso. O cupom das linhas antes do
        # 1º produto ("Use o Cupom: X" acima das linhas "55''" / "65''") vale para todos.
        # menor candidato do bloco (fora mínimo/teto do cupom, desconto, parcela, preço "De" e valores abaixo do
        # piso do produto: R$ 1.500 na TV, R$ 2.500 no PS5, R$ 200 no GTA...)
        preco = preco_postagem(trecho, produtos.piso(produto))
        extra = {"canal": canal, "links": links[:3], "texto": texto[:600]}
        if detalhes:
            extra["produto"] = detalhes
        out.append(Oferta(
            fonte="telegram", tipo="post", loja=loja,
            titulo=f"[{canal}] {titulo[:140]}", url=f"https://t.me/{post}",
            id=_id_do_post(post, produto),
            preco=preco, parcelado=parcelado_no_texto(trecho),
            cupom=cupom_no_texto(trecho) or cupom_no_texto(preambulo),
            publicado=m["publicado"],
            extra=extra, modelo=produto,
        ))
    return out


def parse_canal_e_cupons(html: str, canal: str) -> tuple[list[Oferta], list[cupons_telegram.Citacao]]:
    """(ofertas de produto, cupons citados) de uma página da prévia. A extração de cupom é uma passada separada sobre o
    mesmo texto: o post que é só lista de cupons (sem produto) também conta, e as ofertas não mudam."""
    ofertas: list[Oferta] = []
    citacoes: list[cupons_telegram.Citacao] = []
    for m in _mensagens(html):
        ofertas += _ofertas_da_mensagem(m, canal)
        try:
            citacoes += cupons_telegram.citacoes_do_post(m["texto_cupons"], m["links"], canal, m["post"],
                                                         m["publicado"], m["codes"], m["riscados"])
        except Exception as e:  # noqa: BLE001 - um post estranho não derruba a leitura do canal
            print(f"[telegram.publico] cupons do post {m['post']}: {type(e).__name__}: {str(e)[:120]}")
    return ofertas, citacoes


def parse_canal(html: str, canal: str) -> list[Oferta]:
    return parse_canal_e_cupons(html, canal)[0]


def citacoes_do_html(html: str, canal: str) -> list[cupons_telegram.Citacao]:
    """Só os cupons de uma página (canais só de cupom e buscas por "OFF")."""
    return parse_canal_e_cupons(html, canal)[1]


def urls_de_busca(canais: list[str] | None = None, termos: list[str] | None = None) -> list[tuple[str, str]]:
    """(canal, URL) da busca por termo (t.me/s/<canal>?q=<termo>) de cada canal de muito volume e termo do catálogo.
    Cada busca traz as 20 postagens mais recentes com o termo, cobrindo semanas: a postagem que saiu da 1ª página entre
    uma rodada da nuvem e outra (o @pelandobr posta 7 a 10 por hora) ainda é vista. O GTA precisa de dois termos ("GTA"
    não acha "Grand Theft Auto VI")."""
    canais = config.TELEGRAM_CANAIS_BUSCA if canais is None else canais
    # (TVs desligadas, 26/10/2026: sem os termos das TVs)
    termos = produtos.termos("telegram", produtos.familias_monitoradas()) if termos is None else termos
    return [(c, f"https://t.me/s/{c}?q={quote(t)}") for c in canais for t in termos]


def urls_de_busca_de_cupons(canais_lidos: list[str]) -> list[tuple[str, str]]:
    """(canal, URL) das buscas por termo ("OFF") nos canais que postam listas de cupons e estão sendo lidos (canais
    públicos ou só de cupom): pegam a lista que saiu da 1ª página entre uma rodada e outra."""
    lidos = {c.lower() for c in canais_lidos}
    return [(c, f"https://t.me/s/{c}?q={quote(t)}") for c in config.TELEGRAM_BUSCA_CUPONS_CANAIS
            if c.lower() in lidos for t in config.TELEGRAM_BUSCA_CUPONS_TERMOS]


class TelegramPublico(Fonte):
    nome = "telegram.publico"

    def coletar(self) -> Resultado:
        out: dict[str, Oferta] = {}
        citacoes: list[cupons_telegram.Citacao] = []
        erros = []
        for canal in config.TELEGRAM_CANAIS_PUBLICOS:
            try:
                html = get_html(f"https://t.me/s/{canal}")
                ofs, cits = parse_canal_e_cupons(html, canal)
                for o in ofs:
                    out.setdefault(o.chave, o)
                citacoes += cits
            except Exception as e:  # um canal fora do ar não derruba os outros
                erros.append(f"{canal}: {e}")
        if erros and len(erros) == len(config.TELEGRAM_CANAIS_PUBLICOS):
            raise RuntimeError("; ".join(erros)[:300])
        # busca por termo nos canais de muito volume (a mesma postagem da 1ª página fica uma só, pela chave)
        n_busca, falhas = 0, 0
        for canal, url in urls_de_busca():
            try:
                ofs, cits = parse_canal_e_cupons(get_html(url), canal)
                citacoes += cits
                for o in ofs:
                    if o.chave not in out:
                        out[o.chave] = o
                        n_busca += 1
            except Exception:  # noqa: BLE001 - a busca é extra: a 1ª página do canal já foi lida
                falhas += 1
        if config.TELEGRAM_CANAIS_BUSCA:
            print(f"[telegram.publico] busca por termo: {n_busca} postagens a mais"
                  + (f", {falhas} buscas falharam" if falhas else ""))
        return list(out.values()), self._cupons(citacoes)

    @staticmethod
    def _cupons(citacoes: list[cupons_telegram.Citacao]) -> list[Cupom]:
        """Os cupons citados nos posts (pedido de 08/11/2026): os das páginas já lidas, os dos canais só de cupom
        (config.TELEGRAM_CANAIS_CUPONS) e os das buscas por "OFF" nos canais de listas que estão sendo lidos. Falha
        aqui não derruba as ofertas."""
        lidos = list(dict.fromkeys(config.TELEGRAM_CANAIS_PUBLICOS))
        ja = {x.lower() for x in lidos}
        extras = [c for c in config.TELEGRAM_CANAIS_CUPONS if c.lower() not in ja]
        urls = [(c, f"https://t.me/s/{c}") for c in extras] + urls_de_busca_de_cupons(lidos + extras)
        falhas = 0
        for canal, url in urls:
            try:
                citacoes = citacoes + citacoes_do_html(get_html(url), canal)
            except Exception:  # noqa: BLE001 - página extra, só de cupons
                falhas += 1
        try:
            cupons = cupons_telegram.consolida(citacoes)
        except Exception as e:  # noqa: BLE001 - os cupons não derrubam as ofertas da fonte
            print(f"[telegram.publico] cupons não consolidados: {type(e).__name__}: {str(e)[:160]}")
            return []
        if citacoes or urls:
            print(f"[telegram.publico] cupons: {len(citacoes)} citações, {len(cupons)} cupons"
                  + (f" ({len(urls)} páginas só de cupom" + (f", {falhas} falharam)" if falhas else ")") if urls else ""))
        return cupons
