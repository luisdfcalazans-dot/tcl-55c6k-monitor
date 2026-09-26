"""KaBuM!: API pública do catálogo, um anúncio por id (config.KABUM_PRODUTOS: a 55C6K e os dois da 65C6K)."""

from __future__ import annotations

import time

from .. import config
from ..filtro import modelo_do_titulo
from ..models import MODELO_PADRAO, Oferta
from ..util import get_json, parse_preco
from . import Fonte, Resultado


def parse_api(data: dict, modelo: str = MODELO_PADRAO) -> Oferta | None:
    """Oferta do anúncio da API, se ele é do `modelo` pelo título (65C7K, vizinho da 65C6K no mesmo vendedor, não é)."""
    a = data.get("attributes") or {}
    titulo = a.get("title") or ""
    if modelo_do_titulo(titulo) != modelo or not a.get("available", True):
        return None
    preco = parse_preco(a.get("price"))
    pix = parse_preco(a.get("price_with_discount"))
    oferta = a.get("offer") or {}
    agora = time.time()
    em_oferta = bool(oferta) and (oferta.get("starts_at") or 0) <= agora <= (oferta.get("ends_at") or 0) \
        and (oferta.get("quantity_available") is None or oferta.get("quantity_available", 1) > 0)
    extra = {"preco_tabela": preco, "openbox": a.get("is_openbox")}
    if em_oferta:
        extra["oferta"] = oferta.get("name")
        preco = parse_preco(oferta.get("price")) or preco
        pix = parse_preco(oferta.get("price_with_discount")) or pix
    parcelado = a.get("max_installment") or None
    if parcelado and "sem juros" not in parcelado:
        parcelado = f"{parcelado} sem juros"
    # anúncio de marketplace (seller_type 3P): quem vende é o lojista parceiro, e ele muda sem aviso
    vendedor: str | None = "KaBuM!"
    if a.get("is_marketplace"):
        vendedor = str((a.get("marketplace") or {}).get("seller_name") or "").strip() or None
    pid = str(data.get("id") or config.KABUM_PRODUTOS[MODELO_PADRAO][0])
    return Oferta(
        fonte="kabum", tipo="loja", loja="KaBuM!", titulo=titulo, url=config.URL_KABUM_PRODUTO_BASE + pid,
        id=pid, preco=preco,
        preco_pix=pix if pix and preco and pix < preco else None, parcelado=parcelado, vendedor=vendedor,
        extra=extra, modelo=modelo,
    )


class KaBuM(Fonte):
    nome = "kabum"

    def coletar(self) -> Resultado:
        """Um pedido por anúncio (3 no total). Anúncio que falha não derruba os outros; todos falhando, a fonte falha."""
        out: list[Oferta] = []
        erros: list[str] = []
        for modelo, ids in config.KABUM_PRODUTOS.items():
            for pid in ids:
                try:
                    o = parse_api(get_json(config.URL_KABUM_API_BASE + pid), modelo)
                except Exception as e:  # noqa: BLE001 - rede/HTTP: registra e segue para o próximo anúncio
                    erros.append(f"{pid}: {type(e).__name__}: {e}"[:160])
                    continue
                if o:
                    out.append(o)
        if erros:
            print("[kabum] " + " | ".join(erros))
            if len(erros) == sum(len(ids) for ids in config.KABUM_PRODUTOS.values()):
                raise RuntimeError(erros[0])
        return out, []
