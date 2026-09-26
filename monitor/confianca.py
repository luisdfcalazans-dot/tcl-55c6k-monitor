"""Confiança nos anúncios: vendedores e anúncios bloqueados (sinais de fraude) nunca viram alerta nem vão ao carrinho.

Bloqueio emergencial de 25/09/2026: anúncios da TCL C6K no Magazine Luiza em nome da "Importados Lili"
(seller_id importadoslili). A loja é real, mas não vende TVs; o anúncio tinha homologação Anatel de um celular,
preço 33% abaixo do próprio Magalu, modelo "Vários" e 0 avaliações — padrão de conta de vendedor invadida.
O texto aqui é neutro de propósito: o repositório é público e a empresa pode ser vítima, não autora.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

# (loja canônica, id do vendedor na loja) -> motivo
VENDEDORES_BLOQUEADOS: dict[tuple[str, str], str] = {
    ("Magazine Luiza", "importadoslili"): "anúncio com sinais de fraude (conta de vendedor possivelmente invadida)",
}
# ids de anúncio (produto) bloqueados, qualquer vendedor que apareça neles
ANUNCIOS_BLOQUEADOS: dict[str, str] = {
    "kc3ca4k960": "anúncio com sinais de fraude (Importados Lili, 25/09/2026)",
    "kd12g2e47k": "anúncio com sinais de fraude (Importados Lili, 25/09/2026)",
}


def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def _campo(o: Any, nome: str) -> Any:
    return o.get(nome) if isinstance(o, dict) else getattr(o, nome, None)


def motivo_bloqueio(o: Any) -> Optional[str]:
    """Motivo quando a oferta (Oferta ou dict do latest) é de vendedor/anúncio bloqueado; None se não é."""
    loja = str(_campo(o, "loja") or "")
    extra = _campo(o, "extra") or {}
    url = str(_campo(o, "url") or "")
    oid = str(_campo(o, "id") or "")
    vendedor = _norm(_campo(o, "vendedor"))
    vid = _norm(extra.get("vendedor_id") if isinstance(extra, dict) else "")
    m = re.search(r"[?&]seller_id=([^&#]+)", url)
    vid_url = _norm(m.group(1)) if m else ""
    for (loja_b, vend_b), motivo in VENDEDORES_BLOQUEADOS.items():
        if loja != loja_b:
            continue
        alvo = _norm(vend_b)
        if alvo and alvo in {vid, vid_url, vendedor} | ({oid.rsplit("-", 1)[-1].lower()} if "-" in oid else set()):
            return motivo
    for anuncio, motivo in ANUNCIOS_BLOQUEADOS.items():
        if re.search(rf"/p/{re.escape(anuncio)}(?:/|$)", url) or oid.split("-", 1)[0].lower() == anuncio:
            return motivo
    return None
