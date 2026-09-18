"""Canais públicos do Telegram, lidos pela prévia web t.me/s/<canal> (não precisa de conta)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from .. import config
from ..filtro import bloco_55c6k
from ..models import Oferta
from ..util import (PISO_PRECO_TV, cupom_no_texto, get_html, iso_normaliza, loja_canonica, parcelado_no_texto,
                    preco_postagem)
from . import Fonte, Resultado

_LOJAS_NO_TEXTO = [
    ("magazineluiza", "Magazine Luiza"), ("magalu", "Magazine Luiza"), ("amazon", "Amazon"),
    ("mercadolivre", "Mercado Livre"), ("mercado livre", "Mercado Livre"), ("kabum", "KaBuM!"),
    ("casasbahia", "Casas Bahia"), ("casas bahia", "Casas Bahia"), ("fastshop", "Fast Shop"), ("fast shop", "Fast Shop"),
    ("aliexpress", "AliExpress"), ("shopee", "Shopee"), ("pontofrio", "Ponto"), ("ponto frio", "Ponto"),
    ("extra.com", "Extra"), ("carrefour", "Carrefour"), ("americanas", "Americanas"), ("lojatcl", "Loja TCL"),
]


def loja_no_texto(texto: str, links: list[str]) -> str:
    alvo = (texto + " " + " ".join(links)).lower()
    for chave, nome in _LOJAS_NO_TEXTO:
        if chave in alvo:
            return nome
    return "?"


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
        texto = txt_el.get_text(" ", strip=False)
        texto = "\n".join(l.strip() for l in texto.splitlines() if l.strip())
        # o filtro de título roda na linha-título (a descrição da TV, com "suporte a HDR10+" e "controle remoto",
        # derrubava postagens legítimas); estado do produto e combo valem em qualquer linha
        achado = bloco_55c6k(texto)
        if not achado:
            continue
        # preço, parcelado e cupom saem do trecho sem os valores de outros produtos: numa postagem com várias
        # TVs, o menor valor da mensagem era o de outra TV e virava alerta 🎯 falso
        titulo, trecho = achado
        links = [a.get("href") for a in txt_el.find_all("a", href=True) if "t.me/" not in a.get("href")]
        t = msg.select_one("time[datetime]")
        # menor candidato do bloco da 55C6K (fora mínimo/teto do cupom, desconto, parcela, preço "De" e valores
        # abaixo de R$ 1.500, que não podem ser o preço desta TV)
        preco = preco_postagem(trecho, PISO_PRECO_TV)
        out.append(Oferta(
            fonte=f"telegram", tipo="post", loja=loja_canonica(loja_no_texto(texto, links)),
            titulo=f"[{canal}] {titulo[:140]}", url=f"https://t.me/{post}", id=post,
            preco=preco, parcelado=parcelado_no_texto(trecho), cupom=cupom_no_texto(trecho),
            publicado=iso_normaliza(t.get("datetime")) if t else None,
            extra={"canal": canal, "links": links[:3], "texto": texto[:600]},
        ))
    return out


class TelegramPublico(Fonte):
    nome = "telegram.publico"

    def coletar(self) -> Resultado:
        out: list[Oferta] = []
        erros = []
        for canal in config.TELEGRAM_CANAIS_PUBLICOS:
            try:
                html = get_html(f"https://t.me/s/{canal}")
                out.extend(parse_canal(html, canal))
            except Exception as e:  # um canal fora do ar não derruba os outros
                erros.append(f"{canal}: {e}")
        if erros and len(erros) == len(config.TELEGRAM_CANAIS_PUBLICOS):
            raise RuntimeError("; ".join(erros)[:300])
        return out, []
