from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Oferta:
    """Uma ocorrência da TV em algum lugar: preço numa loja ou postagem num site/canal."""

    fonte: str                 # promobit, pelando, zoom, magalu, kabum, vtex, telegram, amazon, casasbahia, ...
    tipo: str                  # "loja" (preço direto da loja) | "post" (postagem em site de promoção ou canal)
    loja: str                  # nome canônico da loja
    titulo: str
    url: str
    id: str                    # id único dentro da fonte
    preco: Optional[float] = None       # preço à vista/cartão anunciado
    preco_pix: Optional[float] = None   # preço no Pix/boleto, se diferente
    parcelado: Optional[str] = None     # ex.: "10x R$ 389,90 sem juros"
    cupom: Optional[str] = None
    publicado: Optional[str] = None     # ISO 8601
    ativo: bool = True
    vendedor: Optional[str] = None      # vendedor dentro de marketplace
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def chave(self) -> str:
        return f"{self.fonte}:{self.id}"

    @property
    def melhor_preco(self) -> Optional[float]:
        valores = [v for v in (self.preco, self.preco_pix) if v]
        return min(valores) if valores else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["chave"] = self.chave
        d["melhor_preco"] = self.melhor_preco
        return d


@dataclass
class Cupom:
    fonte: str
    loja: str                  # nome canônico
    codigo: str
    titulo: str
    url: str
    id: str
    regra: str = ""            # texto da regra (valor mínimo, categoria...)
    validade: Optional[str] = None
    publicado: Optional[str] = None
    especifico: bool = False   # True quando o cupom está atrelado ao produto (ex.: tag do Magalu)

    @property
    def chave(self) -> str:
        return f"{self.fonte}:{self.id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["chave"] = self.chave
        return d
