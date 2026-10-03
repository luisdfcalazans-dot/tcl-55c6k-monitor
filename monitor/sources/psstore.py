"""PlayStation Store (digital, oficial): o preço do GTA 6 Standard, da Ultimate e da melhoria Standard -> Ultimate.

A página de cada produto (config.URL_PSSTORE_PRODUTO, ids do catálogo em monitor/produtos.py) responde por HTTP e traz o
preço no JSON-LD (offers.price). A melhoria para a Ultimate vem sem preço enquanto a loja não vende (03/10/2026): fica
de fora até ter preço. O custo efetivo (pagando com gift card comprado com desconto) é calculado nas regras.
"""

from __future__ import annotations

from typing import Optional

from .. import config, produtos
from ..models import Oferta
from ..util import get_html, jsonld_produtos, parse_preco
from . import Fonte, Resultado


def parse_produto(html: str, sku: str, url: str) -> Optional[Oferta]:
    for prod in jsonld_produtos(html):
        titulo = str(prod.get("name") or "")
        ofs = prod.get("offers")
        of = (ofs[0] if isinstance(ofs, list) and ofs else ofs) if ofs else {}
        preco = parse_preco((of or {}).get("price")) if isinstance(of, dict) else None
        if not titulo or not preco:
            continue
        c = produtos.classifica(titulo, "PlayStation Store", id_loja=prod.get("sku") or sku)
        if not c.produto or produtos.eh_tv(c.produto):
            continue
        extra = {"anuncio": sku}
        if c.detalhes:
            extra["produto"] = dict(c.detalhes)
        return Oferta(fonte="psstore", tipo="loja", loja="PlayStation Store", titulo=titulo, url=url, id=sku,
                      preco=preco, vendedor="PlayStation Store", extra=extra, modelo=c.produto)
    return None


class PlayStationStore(Fonte):
    nome = "psstore"

    def coletar(self) -> Resultado:
        out: list[Oferta] = []
        erros: list[str] = []
        ids = produtos.ids_da_loja("PlayStation Store", config._NAO_TV)
        for sku in ids:
            url = config.URL_PSSTORE_PRODUTO.format(id=sku)
            try:
                o = parse_produto(get_html(url, tentativas=1), sku, url)
            except Exception as e:  # noqa: BLE001
                erros.append(f"{sku}: {type(e).__name__}: {str(e)[:100]}")
                continue
            if o:
                out.append(o)
        if erros:
            print("[psstore] " + " | ".join(erros))
            if len(erros) == len(ids):
                raise RuntimeError(erros[0])
        return out, []
