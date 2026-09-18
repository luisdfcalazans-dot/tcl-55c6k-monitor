"""KaBuM!: API pública do catálogo."""

from __future__ import annotations

import time

from .. import config
from ..filtro import eh_55c6k
from ..models import Oferta
from ..util import get_json, parse_preco
from . import Fonte, Resultado


def parse_api(data: dict) -> Oferta | None:
    a = data.get("attributes") or {}
    titulo = a.get("title") or ""
    if not eh_55c6k(titulo) or not a.get("available", True):
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
    return Oferta(
        fonte="kabum", tipo="loja", loja="KaBuM!", titulo=titulo, url=config.URL_KABUM_PRODUTO,
        id=str(data.get("id") or "911482"), preco=preco,
        preco_pix=pix if pix and preco and pix < preco else None, parcelado=parcelado, vendedor=vendedor,
        extra=extra,
    )


class KaBuM(Fonte):
    nome = "kabum"

    def coletar(self) -> Resultado:
        o = parse_api(get_json(config.URL_KABUM_API))
        return ([o] if o else []), []
