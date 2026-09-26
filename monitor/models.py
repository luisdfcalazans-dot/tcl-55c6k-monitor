from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Modelos monitorados (pedido de 26/09/2026: a 65C6K entrou junto com a 55C6K). Registro antigo, sem o campo, é da 55C6K.
MODELO_55 = "55C6K"
MODELO_65 = "65C6K"
MODELOS = (MODELO_55, MODELO_65)
MODELO_PADRAO = MODELO_55
POLEGADAS = {MODELO_55: 55, MODELO_65: 65}
MODELO_POR_POLEGADA = {v: k for k, v in POLEGADAS.items()}


def modelo_de(o: Any) -> str:
    """Modelo de uma Oferta, registro do state/latest, linha do histórico ou 'minimo' (dict). Sem o campo (dado gravado
    antes de 26/09/2026) ou com valor desconhecido: 55C6K."""
    m = o.get("modelo") if isinstance(o, dict) else getattr(o, "modelo", None)
    m = str(m or "").strip().upper()
    return m if m in MODELOS else MODELO_PADRAO


def rotulo_modelo(modelo: str) -> str:
    """'TCL 65C6K' (texto das mensagens)."""
    return f"TCL {modelo}"


@dataclass
class Oferta:
    """Uma ocorrência da TV em algum lugar: preço numa loja ou postagem num site/canal."""

    fonte: str                 # promobit, pelando, zoom, magalu, kabum, vtex, telegram, amazon, casasbahia, ...
    tipo: str                  # "loja" (preço direto da loja) | "post" (postagem em site de promoção ou canal)
    loja: str                  # nome canônico da loja
    titulo: str
    url: str
    id: str                    # id único dentro da fonte E do modelo (a mesma postagem com as duas TVs vira dois ids)
    preco: Optional[float] = None       # preço à vista/cartão anunciado
    preco_pix: Optional[float] = None   # preço no Pix/boleto, se diferente
    parcelado: Optional[str] = None     # ex.: "10x R$ 389,90 sem juros"
    cupom: Optional[str] = None
    publicado: Optional[str] = None     # ISO 8601
    ativo: bool = True
    vendedor: Optional[str] = None      # vendedor dentro de marketplace
    extra: dict[str, Any] = field(default_factory=dict)
    modelo: str = MODELO_PADRAO         # "55C6K" | "65C6K"

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
    modelo: Optional[str] = None  # cupom do produto: o modelo do anúncio (None = cupom do site/loja, vale para os dois)

    @property
    def chave(self) -> str:
        return f"{self.fonte}:{self.id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["chave"] = self.chave
        return d
