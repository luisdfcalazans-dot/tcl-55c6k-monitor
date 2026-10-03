"""Canais públicos do Telegram, lidos pela prévia web t.me/s/<canal> (não precisa de conta)."""

from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .. import config, produtos
from ..models import MODELO_PADRAO, Oferta
from ..util import cupom_no_texto, get_html, iso_normaliza, loja_canonica, parcelado_no_texto, preco_postagem
from . import Fonte, Resultado

# Lojas citadas no texto/links da postagem. As de marketplace que revendem estoque de outras (Netshoes vende o do
# Magalu; Mais Correios tem Ponto Frio, Casas Bahia...) vêm antes: o vendedor citado no texto não é a loja da compra
_LOJAS_NO_TEXTO = [
    ("maiscorreios", "Mais Correios"), ("mais correios", "Mais Correios"), ("netshoes", "Netshoes"),
    ("magazineluiza", "Magazine Luiza"), ("magalu", "Magazine Luiza"), ("amazon", "Amazon"),
    ("mercadolivre", "Mercado Livre"), ("mercado livre", "Mercado Livre"), ("kabum", "KaBuM!"),
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


def loja_no_texto(texto: str, links: list[str]) -> str:
    m = _RE_LINHA_LOJA.search(texto or "")
    if m:
        lj = loja_canonica(m.group(1))
        if lj and lj != "?":
            return lj
    alvo = (texto + " " + " ".join(links)).lower()
    for chave, nome in _LOJAS_NO_TEXTO:
        if chave in alvo:
            return nome
    return "?"


def _id_do_post(post: str, produto: str) -> str:
    """Id da postagem por produto: a mesma mensagem com vários produtos vira um id por produto (o da 55C6K é o de
    sempre, sem sufixo)."""
    return post if produto == MODELO_PADRAO else f"{post}#{produto}"


def parse_canal(html: str, canal: str) -> list[Oferta]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Oferta] = []
    for msg in soup.select(".tgme_widget_message[data-post]"):
        post = msg.get("data-post") or ""
        txt_el = msg.select_one(".tgme_widget_message_text")
        if not txt_el:
            continue
        for br in txt_el.find_all("br"):
            br.replace_with("\n")
        # preço riscado (<s>/<del>) é o preço antigo "De": fora do texto
        for riscado in txt_el.find_all(["s", "del", "strike"]):
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
        loja = loja_canonica(loja_no_texto(texto, links))
        # o filtro de título roda na linha-título (a descrição da TV, com "suporte a HDR10+" e "controle remoto",
        # derrubava postagens legítimas); estado do produto e combo valem em qualquer linha. Um bloco por produto
        # monitorado (55C6K, 65C6K, PS5, GTA 6...): a postagem com vários vira uma oferta por produto, cada uma com o
        # próprio preço
        achados = produtos.extrai_produtos(texto, loja)
        if not achados:
            continue
        t = msg.select_one("time[datetime]")
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
                publicado=iso_normaliza(t.get("datetime")) if t else None,
                extra=extra, modelo=produto,
            ))
    return out


def urls_de_busca(canais: list[str] | None = None, termos: list[str] | None = None) -> list[tuple[str, str]]:
    """(canal, URL) da busca por termo (t.me/s/<canal>?q=<termo>) de cada canal de muito volume e termo do catálogo.
    Cada busca traz as 20 postagens mais recentes com o termo, cobrindo semanas: a postagem que saiu da 1ª página entre
    uma rodada da nuvem e outra (o @pelandobr posta 7 a 10 por hora) ainda é vista. O GTA precisa de dois termos ("GTA"
    não acha "Grand Theft Auto VI")."""
    canais = config.TELEGRAM_CANAIS_BUSCA if canais is None else canais
    termos = produtos.termos("telegram") if termos is None else termos
    return [(c, f"https://t.me/s/{c}?q={quote(t)}") for c in canais for t in termos]


class TelegramPublico(Fonte):
    nome = "telegram.publico"

    def coletar(self) -> Resultado:
        out: dict[str, Oferta] = {}
        erros = []
        for canal in config.TELEGRAM_CANAIS_PUBLICOS:
            try:
                html = get_html(f"https://t.me/s/{canal}")
                for o in parse_canal(html, canal):
                    out.setdefault(o.chave, o)
            except Exception as e:  # um canal fora do ar não derruba os outros
                erros.append(f"{canal}: {e}")
        if erros and len(erros) == len(config.TELEGRAM_CANAIS_PUBLICOS):
            raise RuntimeError("; ".join(erros)[:300])
        # busca por termo nos canais de muito volume (a mesma postagem da 1ª página fica uma só, pela chave)
        n_busca, falhas = 0, 0
        for canal, url in urls_de_busca():
            try:
                for o in parse_canal(get_html(url), canal):
                    if o.chave not in out:
                        out[o.chave] = o
                        n_busca += 1
            except Exception:  # noqa: BLE001 - a busca é extra: a 1ª página do canal já foi lida
                falhas += 1
        if config.TELEGRAM_CANAIS_BUSCA:
            print(f"[telegram.publico] busca por termo: {n_busca} postagens a mais"
                  + (f", {falhas} buscas falharam" if falhas else ""))
        return list(out.values()), []
