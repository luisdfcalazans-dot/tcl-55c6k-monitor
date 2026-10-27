"""Hype: cartão presente (gift card) da PlayStation Store [Exclusivo Brasil], por HTTP (26/10/2026).

Pedido do usuário em 26/10: comprar o GTA 6 digital na PS Store pagando com gift card comprado com desconto. A pesquisa
de 26/10 confirmou que a PS Store BR aceita o saldo da carteira na pré-venda e apontou a Hype como loja oficial do cartão
(cartões de R$ 35 a R$ 700; R$ 450 e R$ 550 fecham a Standard e a Ultimate). Um pedido por rodada
(config.URL_HYPE_GIFT_PSN): a página é Next.js e cada cartão traz um "gtmProduct" (id, nome, preço original e de agora,
disponível, vendedor Sony) no payload do HTML, com o link do produto (/br/product/<slug>) logo antes dele. O cupom da
Hype (PSN10, PSN550...) não muda esse preço: ele chega pelos cupons do Promobit (slug "hype-games") e pelas postagens.
Só o que o classificador do catálogo diz ser GIFT_CARD_PSN (o valor de face sai do nome: "R$450 Gift Card ...").
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .. import config, produtos
from ..models import Oferta
from ..util import get_html
from . import Fonte, Resultado

BASE = "https://hype.games"
VENDEDOR = "Hype"
_RE_GTM = re.compile(r'"gtmProduct":(\{[^{}]*\})')
_RE_LINK = re.compile(r'/br/product/[a-z0-9-]+')


def _payload(html: str) -> str:
    """O HTML com as aspas do payload do Next.js desescapadas (o RSC vem dentro de strings JS: \\" -> ")."""
    return (html or "").replace('\\"', '"')


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def parse_pagina(html: str, url_pagina: str = "") -> list[Oferta]:
    """Ofertas de gift card PlayStation da página da categoria da Hype (um cartão por valor de face)."""
    t = _payload(html)
    out: dict[str, Oferta] = {}
    for m in _RE_GTM.finditer(t):
        try:
            g = json.loads(m.group(1))
        except ValueError:
            continue
        nome = str(g.get("name") or "").strip()
        pid = str(g.get("id") or g.get("sku") or "").strip()
        if not nome or not pid or pid in out:
            continue
        c = produtos.classifica(nome, VENDEDOR)
        if c.produto != "GIFT_CARD_PSN":
            continue
        atual, original = _num(g.get("currentPrice")), _num(g.get("originalPrice"))
        preco = atual or original
        if not preco:
            continue
        # o link do cartão é o /br/product/<slug> mais próximo ANTES do gtmProduct (o cartão é um bloco só)
        links = _RE_LINK.findall(t[max(0, m.start() - 4000):m.start()])
        url = BASE + links[-1] if links else (url_pagina or config.URL_HYPE_GIFT_PSN)
        extra = {"preco_tabela": original, "vendedor_marca": str(g.get("seller") or "")}
        if c.detalhes:
            extra["produto"] = dict(c.detalhes)
        out[pid] = Oferta(fonte="hype", tipo="loja", loja="Hype", titulo=nome, url=url, id=pid, preco=preco,
                          vendedor=VENDEDOR, ativo=g.get("avaliable", g.get("available", True)) is not False,
                          extra=extra, modelo="GIFT_CARD_PSN")
    return list(out.values())


class HypeGiftCard(Fonte):
    nome = "hype"
    modo = "cloud"
    alerta_falha = False   # a página é de vitrine (pode mudar de formato); o gift card também chega pelas postagens

    def coletar(self) -> Resultado:
        html = get_html(config.URL_HYPE_GIFT_PSN, tentativas=1)
        ofertas = parse_pagina(html, config.URL_HYPE_GIFT_PSN)
        if not ofertas:
            raise RuntimeError("nenhum gift card PlayStation na página da Hype (o formato mudou?)")
        faces = ", ".join(f"{(o.extra.get('produto') or {}).get('valor_face') or 0:.0f}" for o in ofertas)
        print(f"[hype] {len(ofertas)} gift cards PlayStation (R$ {faces})")
        return ofertas, []
