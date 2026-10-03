"""Catálogo dos produtos monitorados: a fonte ÚNICA de ids, nomes, famílias, metas, termos de busca, EANs, ids por loja
e regras do classificador.

Pedidos do usuário: TCL 55C6K (13/09), TCL 65C6K (26/09) e, em 03/10/2026, o PS5 em TODAS as versões (Slim Digital,
Slim com leitor, Pro, pacotes com o GTA 6, edições especiais e kits) e o GTA 6 em TODAS as formas (Code in Box para PS5,
digital Standard e Ultimate na PS Store, upgrade Standard -> Ultimate) e os caminhos para pagar menos (gift card da
PlayStation com desconto, leitor de disco avulso para o PS5 Digital/Pro). Metas aprovadas pelo usuário em 03/10 (Pix /
total parcelado sem juros); a pesquisa de 03/10 (lojas, histórico, cupons, entrega) está resumida aqui nas regras.

Oferta.modelo guarda o id do produto (registro antigo, sem o campo, é da 55C6K). Ids das TVs: '55C6K' e '65C6K' (os de
sempre); dos outros: as chaves de PRODUTOS. API para as fontes, o estado, as regras e o testador:
  - PRODUTOS, IDS, TVS, NAO_TVS, CARRINHO, produto(), nome(), curto(), familia(), secao(), eh_tv(), por_familia()
  - termos(fonte, familias=None), produto_por_ean(), produto_por_id_loja(), ids_da_loja(), catalogos_ml()
  - classifica(titulo, loja=None, ean=None, id_loja=None) -> Classificacao(produto, motivo, detalhes); as fontes gravam
    os detalhes em Oferta.extra['produto'] (base/extras/valor_extra do kit, valor_face do gift card)
  - extrai_produtos(texto, loja=None) -> {produto: Trecho(titulo, trecho, preambulo, detalhes)} (mensagem livre)
  - piso(), faixa(), preco_plausivel(), alvos_da_oferta(), preco_comparavel(), desconto_gift_card(), entrega(),
    linhas_da_oferta(), anota(), custo_final_gta(), para_painel()
  - entrega do GTA 6: a fonte grava Oferta.extra['entrega_prevista'] (ISO), ['entrega_ate_lancamento'] (bool) e
    ['cep_referencia'] (bool), com o CEP de config.cep_entrega() (variável CEP_ENTREGA; nunca gravar o CEP)

GTA 6: lançamento em 19/11/2026 (Rockstar, PlayStation.com e as lojas; não 19/10). A "versão física" no Brasil é
CODE IN BOX (caixa com código, sem disco; caixas a partir de 12/11 para o pré-carregamento). Para jogar à meia-noite a
caixa tem de chegar até 18/11 (20/11 é feriado nacional). Por isso a meta do Code in Box depende da entrega.

Este módulo não importa config, util nem filtro no carregamento (config importa este módulo); o que precisa deles é
importado dentro das funções.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any, Iterable, NamedTuple, Optional

from .models import MODELO_55, MODELO_65

# ---------------------------------------------------------------------------------------------------------------------
# famílias e datas
# ---------------------------------------------------------------------------------------------------------------------

FAMILIA_TV = "TV"
FAMILIA_PS5 = "PS5"
FAMILIA_GTA6 = "GTA6"
FAMILIA_ACESSORIO = "ACESSORIO"
FAMILIAS = (FAMILIA_TV, FAMILIA_PS5, FAMILIA_GTA6, FAMILIA_ACESSORIO)
# seções do painel (o acessório aparece junto do produto a que serve: leitor no PS5, gift card no GTA 6)
SECOES = {FAMILIA_TV: "TVs", FAMILIA_PS5: "PS5", FAMILIA_GTA6: "GTA 6"}

LANCAMENTO_GTA6 = "2026-11-19"      # 00:00 de Brasília (digital); Code in Box a partir de 12/11
ENTREGA_LIMITE_GTA6 = "2026-11-18"  # chegar até aqui = jogar à meia-noite do lançamento
# a Rockstar libera as caixas do Code in Box em 12/11 (pré-carregamento): na pré-venda, nenhuma caixa sai da loja antes
# disso, e o prazo da loja conta a partir daí (KaBuM: "o prazo começa a contar a partir de 12/11/26")
INICIO_ENVIO_GTA6 = "2026-11-12"
DESCONTO_GIFT_MINIMO = 0.15         # gift card da PlayStation: alerta (🎯) com 15% de desconto ou mais, em loja oficial
# lojas oficiais para gift card (decisão do usuário em 03/10): loja oficial PlayStation no Mercado Livre, Hype, Nuuvem e
# a própria PS Store. Eneba/UbiqPlay e afins: a postagem sai, sem 🎯
LOJAS_GIFT_OFICIAIS = ("PlayStation Store", "Hype", "Nuuvem", "Mercado Livre")
# valor dos extras de kits/edições especiais (regra da pesquisa de 03/10; palpite documentado): meta do console-base mais
# o valor real do extra
VALOR_EXTRA = {
    "controle": 300.0,        # cada DualSense a mais
    "leitor": 300.0,          # leitor de disco avulso (meta do leitor)
    "gta6": 345.0,            # GTA 6 Code in Box (meta do jogo entregue a tempo)
    "headset": 300.0,
    "edicao": 200.0,          # edição só visual (Wolverine, Ghost of Yotei, Fortnite, edição limitada)
    "jogo": 200.0,            # outro jogo no pacote (fora Astro Bot / Gran Turismo 7, que já vêm no console-base)
    "outro": 200.0,
}
FRACAO_CREDITO = 0.80         # crédito/vale da PS Store no kit conta 80% do valor de face


@dataclass(frozen=True)
class Produto:
    id: str
    nome: str
    familia: str
    curto: str                                   # rótulo curto (selo do painel, linhas do resumo)
    secao: str                                   # seção do painel: TV | PS5 | GTA6
    alvo_pix: Optional[float]                    # meta à vista / Pix (None: calculada por oferta)
    alvo_parcelado: Optional[float]              # meta do total parcelado sem juros
    excelente_pix: Optional[float] = None
    excelente_parcelado: Optional[float] = None
    alvo_pix_tardio: Optional[float] = None      # GTA Code in Box que chega DEPOIS de 18/11
    alvo_parcelado_tardio: Optional[float] = None
    faixa: tuple[float, float] = (0.0, 1e9)      # preço plausível (fora dela, não é este produto)
    preco_oficial: Optional[float] = None        # preço sugerido / da PS Store
    buscas: dict[str, tuple[str, ...]] = field(default_factory=dict)   # fonte -> termos de busca
    eans: tuple[str, ...] = ()
    ids_loja: dict[str, tuple[str, ...]] = field(default_factory=dict)  # loja canônica -> ids (anúncio, ASIN, sku...)
    compara_preco: bool = True     # mínimo, 🏆 e faixa entre lojas fazem sentido (kit e gift card misturam valores)
    digital: bool = False          # entregue na conta (PS Store): o custo é o efetivo, com gift card
    gta_fisico: bool = False       # traz o GTA 6 Code in Box: a entrega importa (até 18/11)
    base: Optional[str] = None     # kit/edição: o console-base (calculado por oferta quando None)
    temas: tuple[str, ...] = ()    # para cupons: o que um cupom "só de X" precisa citar para valer aqui
    # produto principal que o testador de cupons pode pôr no carrinho (1 unidade de cada; decisão de 03/10: as TVs, o
    # PS5 Digital, o PS5 com leitor, o PS5 Pro e o GTA 6 Code in Box)
    carrinho: bool = False


_BUSCAS_PS5 = {
    "promobit": ("playstation 5", "ps5 slim", "ps5 pro"),
    "pelando": ("ps5", "playstation 5"),
    "telegram": ("PS5", "PlayStation 5"),
}
_BUSCAS_GTA = {
    "promobit": ("gta vi", "gta 6", "grand theft auto vi"),
    # /busca/gta-6, /busca/gta-vi e /busca/grand-theft-auto-vi trazem conjuntos diferentes (pesquisa de 03/10)
    "pelando": ("gta 6", "grand theft auto vi", "gta vi"),
    "telegram": ("GTA", "Grand Theft Auto"),
}

PRODUTOS: dict[str, Produto] = {p.id: p for p in (
    # ---------------------------------------------------------------- TVs (13/09 e 26/09)
    Produto(
        MODELO_55, "TCL 55C6K", FAMILIA_TV, '55"', FAMILIA_TV, 2900.0, 3000.0, faixa=(1500.0, 20000.0),
        buscas={"promobit": ("55c6k", "tcl 55c6k", "tcl c6k 55"), "pelando": ("55c6k", "tcl 55c6k"),
                "magalu": ("tcl 55c6k", "55c6k", "tcl c6k 55", "smart tv tcl 55 mini led"), "vtex": ("55c6k",),
                "telegram": ("55C6K",)},
        eans=("7899968301747",),
        ids_loja={"Amazon": ("B0F7JZMVKF",), "Mercado Livre": ("MLB48808732",), "Casas Bahia": ("55069456",),
                  "KaBuM!": ("911482",), "Magazine Luiza": ("240162700",), "Zoom": ("13992267",)},
        temas=("tv",), carrinho=True),
    Produto(
        MODELO_65, "TCL 65C6K", FAMILIA_TV, '65"', FAMILIA_TV, 3300.0, 3500.0, faixa=(1500.0, 25000.0),
        buscas={"promobit": ("65c6k", "tcl 65c6k", "tcl c6k 65"), "pelando": ("65c6k", "tcl 65c6k"),
                "magalu": ("tcl 65c6k",), "vtex": ("65c6k",), "telegram": ("65C6K",)},
        eans=("7899968301754",),
        ids_loja={"Amazon": ("B0F7K7B2PD",), "Mercado Livre": ("MLB50368907",), "Casas Bahia": ("55069453",),
                  "KaBuM!": ("911480", "938060"), "Magazine Luiza": ("240162600",), "Zoom": ("13992309",),
                  "Mais Correios": ("900598", "900599")},
        temas=("tv",), carrinho=True),
    # ---------------------------------------------------------------- PS5 (03/10)
    Produto(
        "PS5_DIGITAL", "PS5 Slim Digital", FAMILIA_PS5, "PS5 Digital", FAMILIA_PS5, 3550.0, 3700.0,
        excelente_pix=3350.0, excelente_parcelado=3600.0, faixa=(2500.0, 7000.0), preco_oficial=4599.90,
        buscas={**_BUSCAS_PS5, "magalu": ("playstation 5",), "vtex": ("playstation 5",)},
        eans=("0711719021490", "0711719023876"),
        ids_loja={"Magazine Luiza": ("240604800", "240590700", "ac70gdd6je"),
                  "KaBuM!": ("989702", "939944", "1004851"),
                  "Amazon": ("B0GWNKJDCZ", "B0FPGF9J2J", "B0CQKJN2C6"),
                  "Netshoes": ("D32-286W-014", "D32-286N-014", "HTW-025Z-014"),
                  "Casas Bahia": ("1581976879", "1582493592"), "Americanas": ("8269631", "8299917", "8299907"),
                  "Carrefour": ("336324399", "340173928", "340058675", "340532210"),
                  "Mercado Livre": ("MLB4214670787", "MLB57081243"),  # item + catálogo
                  "Sam's Club": ("146554",), "Mais Correios": ("1474239",), "Fast Shop": ("181030", "141991")},
        temas=("console",), carrinho=True),
    Produto(
        "PS5_DISCO", "PS5 Slim com leitor", FAMILIA_PS5, "PS5 c/ leitor", FAMILIA_PS5, 3950.0, 4150.0,
        excelente_pix=3750.0, excelente_parcelado=4000.0, faixa=(2800.0, 8000.0), preco_oficial=5099.90,
        buscas={**_BUSCAS_PS5, "magalu": ("playstation 5",), "vtex": ("playstation 5",)},
        eans=("0711719022022", "0711719023630"),
        ids_loja={"Magazine Luiza": ("240590800", "240609000"),
                  "KaBuM!": ("934759", "1049973", "953110", "953109"), "Amazon": ("B0GWNFMG5L",),
                  "Netshoes": ("D32-286U-014", "D32-286X-014", "D32-2879-014"), "Americanas": ("8299908",),
                  "Carrefour": ("336324400",)},
        temas=("console",), carrinho=True),
    Produto(
        "PS5_PRO", "PS5 Pro", FAMILIA_PS5, "PS5 Pro", FAMILIA_PS5, 5950.0, 6100.0,
        excelente_pix=5800.0, excelente_parcelado=5900.0, faixa=(4500.0, 11000.0), preco_oficial=7499.90,
        buscas={**_BUSCAS_PS5, "magalu": ("ps5 pro",)},
        ids_loja={"KaBuM!": ("636960",), "Netshoes": ("D32-2878-014",), "Casas Bahia": ("1582830969",),
                  "Terabyte": ("1000046552",)},
        temas=("console",), carrinho=True),
    Produto(
        "PS5_DIGITAL_GTA6", "Pacote PS5 Digital + GTA 6", FAMILIA_PS5, "PS5 Digital + GTA 6", FAMILIA_PS5,
        4000.0, 4150.0, faixa=(3000.0, 8000.0), buscas=dict(_BUSCAS_PS5), ids_loja={"Amazon": ("B0H6LVH152",)},
        gta_fisico=True, temas=("console", "gta")),
    Produto(
        "PS5_DISCO_GTA6", "Pacote PS5 com leitor + GTA 6", FAMILIA_PS5, "PS5 c/ leitor + GTA 6", FAMILIA_PS5,
        4300.0, 4450.0, faixa=(3300.0, 8500.0), buscas=dict(_BUSCAS_PS5), ids_loja={"Amazon": ("B0H6LPVFWQ",)},
        gta_fisico=True, temas=("console", "gta")),
    Produto(
        # meta = meta do console-base + valor do extra (calculada por oferta: alvos_da_oferta)
        "PS5_KIT", "PS5 edição especial / kit", FAMILIA_PS5, "PS5 kit/edição", FAMILIA_PS5, None, None,
        faixa=(2500.0, 13000.0), buscas=dict(_BUSCAS_PS5), ids_loja={"KaBuM!": ("1065184",)},
        compara_preco=False, temas=("console",)),
    # ---------------------------------------------------------------- GTA 6 (03/10)
    Produto(
        "GTA6_CODE_IN_BOX", "GTA 6 PS5 Code in Box", FAMILIA_GTA6, "GTA 6 Code in Box", FAMILIA_GTA6, 345.0, 370.0,
        excelente_pix=325.0, excelente_parcelado=350.0, alvo_pix_tardio=300.0, alvo_parcelado_tardio=320.0,
        faixa=(200.0, 800.0), preco_oficial=449.90, buscas={**_BUSCAS_GTA, "magalu": ("gta vi",)},
        eans=("0710425676338",),
        ids_loja={"KaBuM!": ("1051619", "1066262", "TT000272PS5"), "Magazine Luiza": ("241923300",),
                  "Amazon": ("B0H6KT2RWH",), "Netshoes": ("POE-0002-006",), "Carrefour": ("340270416", "4484509"),
                  "Fast Shop": ("175223", "185443")},
        gta_fisico=True, temas=("gta", "jogo"), carrinho=True),
    Produto(
        "GTA6_DIGITAL", "GTA 6 digital Standard (PS Store)", FAMILIA_GTA6, "GTA 6 digital", FAMILIA_GTA6, 365.0, 365.0,
        faixa=(150.0, 600.0), preco_oficial=449.90, buscas=dict(_BUSCAS_GTA),
        ids_loja={"PlayStation Store": ("EP1004-PPSA01547_00-GTAVISTANDARD001",)}, digital=True, temas=("gta", "jogo")),
    Produto(
        "GTA6_ULTIMATE", "GTA 6 digital Ultimate (PS Store)", FAMILIA_GTA6, "GTA 6 Ultimate", FAMILIA_GTA6, 450.0, 450.0,
        faixa=(200.0, 800.0), preco_oficial=549.90, buscas=dict(_BUSCAS_GTA),
        ids_loja={"PlayStation Store": ("EP1004-PPSA01547_00-GTAVIULTIMATE001",)}, digital=True, temas=("gta", "jogo")),
    Produto(
        "GTA6_UPGRADE", "Upgrade GTA 6 Standard -> Ultimate", FAMILIA_GTA6, "GTA 6 upgrade", FAMILIA_GTA6, 85.0, 85.0,
        faixa=(30.0, 250.0), preco_oficial=100.0, buscas=dict(_BUSCAS_GTA),
        ids_loja={"PlayStation Store": ("EP1004-PPSA01547_00-ULTEDTIONUPGRADE",)}, digital=True, temas=("gta", "jogo")),
    # ---------------------------------------------------------------- acessórios (caminhos para pagar menos)
    Produto(
        # meta = 85% do valor de face (15% de desconto ou mais), só em loja oficial: alvos_da_oferta
        "GIFT_CARD_PSN", "Gift card PlayStation", FAMILIA_ACESSORIO, "Gift card PSN", FAMILIA_GTA6, None, None,
        faixa=(20.0, 1500.0),
        buscas={"promobit": ("gift card playstation",), "pelando": ("gift card playstation",),
                "telegram": ("gift card PlayStation",)},
        ids_loja={"Mercado Livre": ("MLB50200776",)}, compara_preco=False, temas=("gift",)),
    Produto(
        "LEITOR_PS5", "Leitor de disco do PS5", FAMILIA_ACESSORIO, "Leitor PS5", FAMILIA_PS5, 300.0, 320.0,
        faixa=(150.0, 1000.0),
        buscas={"promobit": ("leitor de disco ps5",), "pelando": ("leitor de disco ps5",),
                "telegram": ("leitor de disco",)},
        ids_loja={"KaBuM!": ("536958",), "Netshoes": ("D32-288O-014",)},
        temas=("leitor",)),
)}

IDS: tuple[str, ...] = tuple(PRODUTOS)
TVS: tuple[str, ...] = tuple(i for i, p in PRODUTOS.items() if p.familia == FAMILIA_TV)
NAO_TVS: tuple[str, ...] = tuple(i for i in IDS if i not in TVS)
# os produtos principais que o testador de cupons pode pôr no carrinho (1 unidade de cada)
CARRINHO: tuple[str, ...] = tuple(i for i, p in PRODUTOS.items() if p.carrinho)
# catálogos do Mercado Livre (página de produto com todas as opções de compra) além dos das TVs (config.ML_CATALOGOS):
# nunca são de um vendedor só (monitor/confianca.py)
CATALOGOS_ML_EXTRA: tuple[str, ...] = ("MLB57081243",)   # PS5 Slim Digital (loja oficial PlayStation vende nele)
# loja oficial PlayStation no Mercado Livre (official_store_id 1473): vendedor confiável do PS5 e do gift card
ML_PLAYSTATION_VENDEDOR = "1047493289"


# ---------------------------------------------------------------------------------------------------------------------
# consultas simples
# ---------------------------------------------------------------------------------------------------------------------

def produto(pid: Any) -> Optional[Produto]:
    return PRODUTOS.get(str(pid or "").strip().upper())


def nome(pid: Any) -> str:
    p = produto(pid)
    return p.nome if p else str(pid or "?")


def curto(pid: Any) -> str:
    p = produto(pid)
    return p.curto if p else str(pid or "?")


def familia(pid: Any) -> str:
    p = produto(pid)
    return p.familia if p else FAMILIA_TV


def secao(pid: Any) -> str:
    p = produto(pid)
    return p.secao if p else FAMILIA_TV


def eh_tv(pid: Any) -> bool:
    return familia(pid) == FAMILIA_TV


def por_familia(fam: str) -> tuple[str, ...]:
    return tuple(i for i, p in PRODUTOS.items() if p.familia == fam)


def por_secao(sec: str) -> tuple[str, ...]:
    return tuple(i for i, p in PRODUTOS.items() if p.secao == sec)


def faixa(pid: Any) -> tuple[float, float]:
    p = produto(pid)
    return p.faixa if p else (1500.0, 1e9)


def piso(pid: Any) -> float:
    """Menor valor que pode ser o preço do produto numa postagem livre (abaixo é peça, parcela, desconto...)."""
    return faixa(pid)[0]


def preco_plausivel(pid: Any, valor: Optional[float]) -> bool:
    if not valor:
        return False
    a, b = faixa(pid)
    return a <= valor <= b


def termos(fonte: str, familias: Optional[Iterable[str]] = None, ids: Optional[Iterable[str]] = None) -> list[str]:
    """Termos de busca da `fonte` (sem repetição), produto a produto na ordem do catálogo, intercalados por posição
    (o 1º termo de cada produto, depois o 2º...). `familias`/`ids` restringem os produtos."""
    fams = set(familias) if familias is not None else None
    escolhidos = [p for i, p in PRODUTOS.items()
                  if (fams is None or p.familia in fams) and (ids is None or i in set(ids))]
    listas = [list(p.buscas.get(fonte) or ()) for p in escolhidos]
    out: list[str] = []
    for k in range(max((len(x) for x in listas), default=0)):
        for x in listas:
            if k < len(x) and x[k].lower() not in {t.lower() for t in out}:
                out.append(x[k])
    return out


def termos_do_produto(pid: str, fonte: str) -> list[str]:
    p = produto(pid)
    return list(p.buscas.get(fonte) or ()) if p else []


def _ean_norm(ean: Any) -> str:
    return re.sub(r"\D", "", str(ean or "")).lstrip("0")


def produto_por_ean(ean: Any) -> Optional[str]:
    """Produto pelo código de barras (com ou sem os zeros à esquerda: 711719021490 = 0711719021490)."""
    e = _ean_norm(ean)
    if not e:
        return None
    for i, p in PRODUTOS.items():
        if any(_ean_norm(x) == e for x in p.eans):
            return i
    return None


def eans_por_produto(familias: Optional[Iterable[str]] = None) -> dict[str, str]:
    """{EAN: produto} (como o catálogo grava, com os zeros)."""
    fams = set(familias) if familias is not None else None
    return {e: i for i, p in PRODUTOS.items() if fams is None or p.familia in fams for e in p.eans}


def _id_norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _ascii(s))


def produto_por_id_loja(loja: Any, id_loja: Any) -> Optional[str]:
    """Produto pelo id do anúncio na loja (ASIN, /p/<id>/ do Magalu, id da KaBuM, código da Netshoes, item da VTEX,
    id da PS Store...). `loja`: nome canônico (config.LOJAS_CANONICAS); None procura em todas."""
    alvo = _id_norm(id_loja)
    if not alvo:
        return None
    for i, p in PRODUTOS.items():
        for lj, ids in p.ids_loja.items():
            if loja not in (None, "", lj):
                continue
            if any(_id_norm(x) == alvo for x in ids):
                return i
    return None


def ids_da_loja(loja: str, familias: Optional[Iterable[str]] = None) -> dict[str, str]:
    """{id do anúncio: produto} de uma loja (para as fontes visitarem os anúncios conhecidos)."""
    fams = set(familias) if familias is not None else None
    return {x: i for i, p in PRODUTOS.items() if fams is None or p.familia in fams for x in p.ids_loja.get(loja, ())}


def catalogos_ml() -> set[str]:
    """Ids de catálogo/anúncio do Mercado Livre do catálogo (os MLB...)."""
    return {x for p in PRODUTOS.values() for x in p.ids_loja.get("Mercado Livre", ())}


# ---------------------------------------------------------------------------------------------------------------------
# normalização
# ---------------------------------------------------------------------------------------------------------------------

def _ascii(s: Any) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def normaliza(texto: Any) -> str:
    """Minúsculo, sem acento, sem ®/™, espaços simples; 'PS 5' vira 'ps5', 'PlayStation5' vira 'playstation 5'."""
    t = _ascii(str(texto or "").replace("®", " ").replace("™", " ").replace("©", " "))
    t = re.sub(r"\bps\s+5\b", "ps5", t)
    t = re.sub(r"\bplay\s?station\s?5\b", "playstation 5", t)
    t = re.sub(r"\bplay\s+station\b", "playstation", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------------------------------------------------
# classificador (título + dados estruturados)
# ---------------------------------------------------------------------------------------------------------------------

class Classificacao(NamedTuple):
    produto: Optional[str]          # id do produto, ou None (não é nenhum produto monitorado)
    motivo: str                     # por que não é ('' quando é): "acessório: controle", "versão estrangeira: ksa"...
    detalhes: dict                  # base/extras/valor_extra (kit), valor_face (gift card), versao_incerta...


_PS5 = r"(?:\bps5\b|\bplaystation 5\b)"
_RE_PS5 = re.compile(_PS5)
_RE_GTA6 = re.compile(r"\bgta\s?(?:6|vi)(?![a-z0-9])|\bgrand theft auto\s*:?\s*(?:6|vi)(?![a-z0-9])")
_RE_GTA_OUTRO = re.compile(r"\bgta\b|\bgrand theft auto\b")
# estado/origem que nunca é o produto novo e nacional (no título ou no bloco da mensagem)
_RE_ESTADO = re.compile(
    r"\busad[oa]s?\b|\bseminov[oa]s?\b|\bsemi[\s-]nov[oa]s?\b|\brecondicionad[oa]s?\b|\brecertificad[oa]s?\b|"
    r"\brefurbished\b|\brenovad[oa]s?\b|\bvitrine\b|\bmostruario\b|\bcaixa aberta\b|\bopen\s?box\b|"
    r"\bembalagem (?:aberta|danificada|violada|avariada)\b|\bquase novo\b|\bgrade [abc]\b|\bdefeito\b|\bnao liga\b|"
    r"\bretirada de pecas\b|\breembalad[oa]s?\b|\bproduto de exposicao\b|\bavaria\b|\bsem caixa\b")
# conta compartilhada ("GTA 6 PS5 Conta Secundária", "Mídia Digital Primária", "conta alugada"): acesso à conta de outra
# pessoa, não o jogo (nem o Code in Box nem a compra na PS Store)
_RE_CONTA = re.compile(r"\bprimari[ao]s?\b|\bsecundari[ao]s?\b|\bconta (?:compartilhada|alugada|parceira)\b|"
                       r"\baluguel de conta\b|\bconta (?:psn )?(?:de terceiros|offline)\b")
# serviço vendido com o nome do produto ("Garantia Estendida - Console PS5", "Seguro Roubo e Furto Console PS5")
_RE_SERVICO_INICIO = re.compile(r"^[^a-z0-9]*(?:\[[^\]]*\]\s*)?(?:garantia|seguro|protecao|instalacao|servicos?|"
                                r"assistencia)\b")
_RE_ESTRANGEIRO = re.compile(
    r"\bksa\b|\binternational\b|\binternacional\b|\bimportad[oa]s?\b|\bversao (?:americana|europeia|japonesa|"
    r"asiatica|arabe|estrangeira|importada|chinesa)\b|\b(?:us|usa|eu|uk|jp|asia) version\b|\bjapan\b|"
    r"\bhong kong\b|\barabia saudita\b|\bsaudi\b|"
    # Amazon, 03/10: "Sony PlayStation 5 Slim Digital Edition Console - 825GB - Middle East"
    r"\bmiddle east\b|\boriente medio\b|\bgcc\b|\buae\b|\bemirados\b")
_RE_COLECIONADOR = re.compile(r"\b30\s?(?:o|th)?\s*aniversario\b|\b30th anniversary\b|\banniversary edition\b|"
                              r"\b30\s+anos\b")
# resumo de várias ofertas num título só ("ACHADOS MAGALU! PS5 Slim R$ 4.875, Galaxy S24 Ultra R$ 5.099 e Lavadora...",
# "SUPER OFERTAS SHOPEE com Até 70% OFF! Smart TV, GTA 6, Playstation 5 e Muito Mais!"): o preço não é de um produto
_RE_RESUMO = re.compile(r"\bachados\b|\bsuper ofertas\b|\be muito mais\b|\bofertas (?:do dia|imperdiveis|da semana)\b|"
                        r"\bselecao de ofertas\b|\blista de ofertas\b|\bvarios produtos\b|\bate [5-9]\d\s?% off\b")
_RE_OUTRO_PRODUTO_NO_TITULO = re.compile(r"\bsmart\s*tvs?\b|\bgalaxy\b|\biphone\b|\bnotebook\b|\blavadora\b|"
                                         r"\bgeladeira\b|\bcelular\b|\bair\s*fryer\b|\bxbox\b|\bnintendo\b")
# outros aparelhos e plataformas (03/10, lista da KaBuM: "Sony Playstation 3 Super Slim 500gb" virava PS5 Digital)
_RE_OUTRO_APARELHO = re.compile(
    r"\bps\s?4\b|\bplaystation 4\b|\bps\s?vr\s?2?\b|\bvr\s?2\b|\bplaystation vr\b|\bplaystation portal\b|"
    r"\bportal remote\b|\bxbox\b|\bseries [xs]\b|\bnintendo\b|\bswitch\b|\bsteam deck\b|\bps\s?3\b|\bpsp\b|\bps vita\b|"
    r"\bplaystation [1-3]\b|\bplaystation (?:one|vita|portable)\b|\bps\s?(?:one|1|2)\b")
# assinatura e serviço de streaming ("Ganhe até 30 Dias Grátis de NETFLIX - Filmes, Séries, GTA VI", @pelandobr 27/08)
_RE_ASSINATURA = re.compile(r"\bps\s?plus\b|\bplaystation plus\b|\bgame pass\b|\bassinatura\b|\bgta\s?\+|\bgta plus\b|"
                            r"\bnetflix\b|\bstreaming\b|\bdias? gratis\b|\bteste gratis\b")
# acessório: o 1º substantivo do título (depois de emoji, número, "novo", marca) é a peça
_ACESSORIOS = (
    r"controles?|joysticks?|dualsense|dual sense|dualshock|capas?|cases?|bolsas?|mochilas?|suportes?|bases?|"
    r"coolers?|ventoinhas?|ventiladores?|headsets?|fones?|cabos?|carregador(?:es)?|estac(?:ao|oes)|docks?|"
    r"peliculas?|skins?|adesivos?|grips?|volantes?|teclados?|mouse\s?pads?|mouses?|cameras?|microfones?|luvas?|"
    r"protetor(?:es)?|"
    r"tampas?|faceplates?|covers?|tapetes?|ssds?|hds?|cartao de memoria|memorias?|baterias?|fontes?|kit de "
    r"(?:acessorios|limpeza)|pulse|charging|stand|organizador(?:es)?|racks?|nichos?|mesas?|cadeiras?|"
    r"camisetas?|canecas?|posters?|livros?|guias?|mapas?|funkos?|action figures?|bonecos?|chaveiros?|moletons?|"
    r"bones?|quadros?|capinhas?|copos?|garrafas?|almofadas?|luminarias?|placas?|"
    # vistos na busca do Magalu/nocnoc em 03/10: decoração, cofrinho, pôster, capa em espanhol
    r"decoracao|decoracoes|cofrinhos?|posterzines?|cubiertas?|carcacas?|reemplazos?|artefatos?|resfriamento|"
    r"refrigeracao|ventilacao|"
    # produtos temáticos do GTA que faltavam (lista fechada de 03/10)
    r"camisas?|moletom|pelucias?|relogios?|lencol|lencois|toalhas?|travesseiros?|cobertor(?:es)?|mantas?|"
    r"jaquetas?|pijamas?|bermudas?|estatu(?:a|eta)s?|miniaturas?|replicas?|quebra[\s-]?cabecas?|cartaz(?:es)?|"
    r"pulseiras?")
_PREFIXO_TITULO = r"^[^a-z0-9]*(?:\[[^\]]*\]\s*)?(?:(?:novo|nova|original|oficial|sony|playstation|ps5|\d+\s*(?:x|un\w*)?|kit)\s+)*"
_RE_INICIO_ACESSORIO = re.compile(_PREFIXO_TITULO + rf"({_ACESSORIOS})(?![a-z0-9])")
_RE_PARA_PS5 = re.compile(r"\b(?:para|pra|p/|compativel com|compativeis com)\s+(?:o\s+|a\s+|os\s+)?"
                          r"(?:consoles?\s+)?(?:ps5|playstation)")
_RE_TEMATICO = re.compile(r"\b(?:camisetas?|canecas?|posters?|livros?|guias?|mapas?|funkos?|action figures?|bonecos?|"
                          r"chaveiros?|moletons?|bones?|quadros?|almofadas?|luminarias?|copos?|trilha sonora|"
                          r"steelbook|artbook|decoracao|decoracoes|decorativ[oa]s?|cofrinhos?|posterzines?|adesivos?|"
                          # os que faltavam (lista fechada de 03/10): roupa, cama e mesa, colecionáveis
                          r"camisas?|moletom|pelucias?|relogios?|lencol|lencois|toalhas?|travesseiros?|"
                          r"cobertor(?:es)?|mantas?|jaquetas?|pijamas?|bermudas?|estatu(?:a|eta)s?|miniaturas?|"
                          r"replicas?|quebra[\s-]?cabecas?|cartaz(?:es)?|pulseiras?)\b")
# peça/acessório citado DEPOIS do nome do GTA 6 ("GTA VI Mousepad Gamer 90x40", "Grand Theft Auto VI Suporte de
# Controle", "GTA 6 Skin PS5 Slim"): é o produto (lista fechada de 03/10; a busca do Magalu por "gta vi" traz mousepad e
# suporte de controle). Só as peças que nunca descrevem o jogo: "suporte a legendas", "skins exclusivas" (bônus do jogo),
# "capa exclusiva" e o controle (kit, visto à parte) não entram
_RE_PECA_COM_GTA = re.compile(
    r"\bmouse\s?pads?\b|\bmouses?\b|\bteclados?\b|\bheadsets?\b|\bfones?\s+(?:de\s+ouvido|gamer|bluetooth|sem fio)\b|"
    r"\bskins?\s+(?:adesiv\w*\s+)?(?:(?:para|pra|p/)\s+(?:o\s+)?)?(?:ps5|playstation|consoles?|controles?|dualsense)\b|"
    r"\bpeliculas?\b|\bcoolers?\b|\bventoinhas?\b|"
    r"\bsuportes?\s+(?:gamer\b|(?:para|pra|p/|de|do|da)\s+(?:o\s+|a\s+)?(?:controles?|headsets?|fones?|consoles?|ps5|"
    r"playstation|parede|tv|mesa|jogos?|games?)\b)|"
    r"\bcapas?\s+(?:protetora|(?:para|pra|p/|de|do|da)\s+(?:o\s+|a\s+)?(?:controles?|consoles?|ps5|playstation|"
    r"headsets?|fones?))\b|\bcapinhas?\b|"
    r"\bcabos?\b|\bcarregador(?:es)?\b|\bcadeiras?\b|\bmesas?\s+gamer\b|\btapetes?\b|\bmochilas?\b|\bbolsas?\b|"
    r"\bbase\s+(?:carregadora|de carregamento|vertical)\b|\bestac(?:ao|oes)\s+de\s+carregamento\b")
# jogo: o título começa por "jogo"/"game" ou é "<nome> - PlayStation 5" sem nada de console
_RE_INICIO_JOGO = re.compile(_PREFIXO_TITULO + r"(?:jogos?|games?|midia fisica|pre[\s-]?venda)\b")
# leitor de disco avulso no começo do título
_RE_LEITOR = re.compile(r"\b(?:leitor|unidade|drive)\s+(?:de\s+)?(?:disco|midia|blu[\s-]?ray)\b|\bdisc drive\b")
# o leitor como PEÇA (o produto em si), não como descrição do console: "com leitor", "sem leitor", "e leitor", "+ leitor"
# e "c/ leitor" descrevem o console (ou o kit Digital + leitor). Revisão de 03/10: o nome oficial da Sony é "Unidade de
# Disco para Consoles PS5 Digital Edition" e há "Leitor de Disco Ultra HD Blu-ray Console PS5 Slim": a palavra console
# no título não faz do leitor um console
_RE_LEITOR_PECA = re.compile(
    r"(?<!\bcom )(?<!\bsem )(?<!\be )(?<!\+ )(?<!\+)(?<!\bc/ )(?<!\bc/)"
    r"\b(?:leitor(?:es)?|unidades?|drives?)\s+(?:de\s+)?(?:dis[ck]os?|midias?|blu[\s-]?e?[\s-]?ray)\b|\bdisc drive\b")
# o núcleo "console" do título (o que aparece antes decide se o título é do console ou do leitor)
_RE_CONSOLE_NUCLEO = re.compile(r"\bconsoles?\b|\bvideo\s?games?\b|\b825\s?gb\b|\b1\s?tb\b|\b2\s?tb\b|\bcfi[\s-]?\d{4}")
# "Leitor de Disco + Console PS5 Digital": o kit (o console vem junto)
_RE_LEITOR_COM_CONSOLE = re.compile(r"(?:\+|\bcom\b|\bmais\b)\s*(?:o\s+|um\s+)?console\b")
# o leitor "para" o PS5 logo depois dele ("Leitor de Disco para PS5 Digital/Pro", "Unidade de Disco Blu-ray para console
# PS5", "PS5 Leitor de Disco para Console Digital"): é a peça, mesmo com o PS5 escrito antes
_RE_LEITOR_PARA = re.compile(r"\s*(?:[a-z0-9-]+\s+){0,3}?(?:para|pra|p/|compativel com|compativeis com)\s+"
                             r"(?:o\s+|a\s+|os\s+)?(?:consoles?\b|ps5\b|playstation\b)")
# o leitor como assunto de uma frase ("15% OFF no Leitor de Disco PS5", "desconto na Unidade de Disco"): a peça
_RE_PREPOSICAO_ANTES = re.compile(r"\b(?:no|na|nos|nas|em|do|da|dos|das|ao|pelo|pela)\s+$")
# o nome do PS5 escrito antes do leitor ("PS5 Slim Leitor de Disco 1TB"): o leitor descreve o console
_RE_PS5_ANTES = re.compile(r"\bps5\b|\bplaystation\b")
# a versão citada antes do leitor não tem leitor (Pro, Digital): "PlayStation 5 Pro Leitor de Disco" é a peça para ela
_RE_VERSAO_SEM_LEITOR = re.compile(r"\bpro\b|\bdigital\b")


def papel_do_leitor(texto: Any) -> Optional[str]:
    """Como o texto (título, cupom) cita o leitor de disco como peça: 'peca' (o leitor é o assunto: o leitor avulso,
    "R$ 62 OFF no Leitor de Disco PS5"), 'console' (descreve o console ou entra num kit: "PS5 Slim Leitor de Disco 1TB",
    "Leitor de Disco + Console PS5") ou None (não cita o leitor como peça; "com leitor", "+ leitor" ficam com quem
    chama). A mesma leitura do classificador (_e_o_leitor)."""
    t = normaliza(texto)
    if not _RE_LEITOR_PECA.search(t):
        return None
    return "peca" if _e_o_leitor(t) else "console"


def cita_leitor_avulso(texto: Any) -> bool:
    """O texto cita o leitor de disco como peça ("Leitor de Disco ... Console PS5", "Unidade de Disco para Consoles
    PS5"), não como descrição do console ("com leitor", "+ leitor"). O carrinho usa: uma linha assim nunca é um
    produto principal (o leitor da pessoa não pode virar o console do robô)."""
    return bool(_RE_LEITOR_PECA.search(normaliza(texto)))


def _e_o_leitor(t: str) -> bool:
    """O título é do leitor de disco avulso: o leitor é o ASSUNTO do título, não uma característica do console.

    - não é o leitor: "com/sem/c/ / + / e leitor" (o console ou o kit; _RE_LEITOR_PECA), o título que junta um console
      a ele ("Leitor + Console PS5") e o núcleo de console (palavra console, armazenamento, código CFI) antes dele
      ("Console PS5 Slim Leitor de Disco 1TB");
    - é o leitor: "leitor para o PS5" ("Leitor de Disco para PS5 Digital/Pro", "PS5 Leitor de Disco para Console
      Digital"), o leitor depois de preposição ("15% OFF no Leitor de Disco PS5"), o leitor antes do nome do PS5
      ("Leitor de Disco PS5 Slim", "Sony - Leitor de Disco Console PS5 Slim", "Unidade de Disco para Consoles PS5") e a
      versão sem leitor (Pro, Digital) seguida do leitor, sem nada de console depois ("PlayStation 5 Pro Leitor de
      Disco");
    - o nome do PS5 antes do leitor, sem nada disso, é o console com leitor ("PS5 Slim Leitor de Disco 1TB + 2 Jogos",
      "PlayStation 5 Slim - Leitor de Disco - 1TB"). 2ª conferência de 03/10: esses títulos viravam o leitor e o sanear
      descartava o console abaixo da meta (fora da faixa do leitor)."""
    ml = _RE_LEITOR_PECA.search(t)
    if not ml:
        return False
    antes, depois = t[:ml.start()], t[ml.end():]
    if _RE_LEITOR_COM_CONSOLE.search(depois) or _RE_CONSOLE_NUCLEO.search(antes):
        return False
    if _RE_LEITOR_PARA.match(depois) or _RE_PREPOSICAO_ANTES.search(antes):
        return True
    if not _RE_PS5_ANTES.search(antes):
        return True
    return bool(_RE_VERSAO_SEM_LEITOR.search(antes)) and not _RE_CONSOLE_NUCLEO.search(depois)
# gift card / cartão presente da PlayStation
_RE_GIFT = re.compile(
    r"\bgift\s?cards?\b|\bcart(?:ao|oes) (?:presente|psn|playstation|ps store|pre-?pago)\b|\bvale[\s-]presentes?\b|"
    r"\bpsn cards?\b|\b(?:credito|creditos|saldo) (?:na |da |de )?(?:psn|playstation|ps store)\b|"
    r"\bplaystation store card\b|\bcartao da playstation\b")
_RE_GIFT_OUTRA_LOJA = re.compile(r"\bxbox\b|\bnintendo\b|\bsteam\b|\bgoogle play\b|\bapple\b|\bitunes\b|\bifood\b|"
                                 r"\buber\b|\bnetflix\b|\bspotify\b|\broblox\b|\bfree ?fire\b|\briot\b|\bvalorant\b|"
                                 r"\bblizzard\b|\brazer\b|\bamazon\b|\bep?ic games\b")
# console: evidência forte (palavra console, armazenamento, Slim, Pro) e marcas de versão
_RE_CONSOLE_PALAVRA = re.compile(r"\bconsoles?\b|\bvideo\s?games?\b")
_RE_CONSOLE_FORTE = re.compile(
    r"\bconsoles?\b|\bvideo\s?games?\b|\b825\s?gb\b|\b1\s?tb\b|\b2\s?tb\b|\bslim\b|" + _PS5 + r"\s+pro\b|"
    r"\bcfi[\s-]?\d{4}|\b1000046552\b")
_RE_VERSAO = re.compile(r"\bdigital\b|\bsem leitor\b|\bcom leitor\b|\bleitor de dis[ck]o\b|\bmidia fisica\b|\bdis[ck]\b|"
                        r"\bdisco\b|\bstandard\b|\bedicao\b|\bbundle\b|\bpacote\b|\bkit\b|\bpro\b")
_RE_DIGITAL = re.compile(r"\bdigital\b|\bsem leitor\b|\b825\s?gb\b|\bcfi[\s-]?2\d{3}\s?b|\bdigital edition\b")
# o que diz "Digital" com todas as letras (o 825GB sozinho não: o PS5 Standard de 825GB tem leitor, 03/10 na KaBuM:
# "Console Sony Playstation 5 Standard 825gb E Leitor De Blue Ray")
_RE_DIGITAL_FORTE = re.compile(r"\bdigital\b|\bsem leitor\b|\bcfi[\s-]?2\d{3}\s?b|\bdigital edition\b")
_RE_DISCO = re.compile(r"\bcom leitor\b|\bleitor de dis[ck]o\b|\bmidia fisica\b|\bdis[ck]\b|\bdisco\b|\bstandard\b|"
                       r"\bcfi[\s-]?2\d{3}\s?a\b|\b1\s?tb\b|\bleitor de blu[\s-]?e?[\s-]?ray\b")
# extras de kit / edição especial. O controle que já vem com o console NÃO é extra: "+ 1 Controle Sony" (Netshoes,
# 03/10), "+ Controle Sem Fio DualSense Branco" (Shopee e Inpower: o console comum, revisão de 03/10) e "+ Controle"
# no singular, sem número. A mais: "+ 2 Controles", "com 2 controles", "+ mais um controle", "controle extra/adicional"
# e o DualSense Edge (nunca vem com o console)
_RE_EXTRA_CONTROLE = re.compile(
    r"\+\s*(?:[2-9]|dois|tres)\s+(?:controles|dualsense|dual sense)\b|"
    r"\b(?:mais|outro)\s+(?:um\s+)?controle\b|"
    r"\b(?:2|dois|two)\s+(?:controles|dualsense|dual sense|wireless controllers|controllers)\b|"
    r"\bcontroles?\s+(?:[a-z]+\s+){0,3}?(?:extras?|adiciona(?:l|is)|a mais)\b|"
    r"\bcom\s+(?:2|dois)\s+(?:controles|dualsense)\b|"
    r"\bdual\s?sense edge\b|\bcontrole edge\b")
_RE_EXTRA_LEITOR = re.compile(r"\+\s*(?:o\s+|um\s+)?(?:leitor|unidade|drive)\b|\be\s+leitor de dis[ck]o\b")
# crédito no kit: o da PS Store e o vale da própria loja ("+ Gift Card KaBuM: 500 Reais", rodada seca de 03/10)
_RE_EXTRA_CREDITO = re.compile(
    r"(?:vale|credito|creditos|gift\s?card|saldo|voucher|cartao presente)\s+(?:de\s+|em\s+|na\s+|da\s+)?"
    r"(?:(?:ps store|playstation store|playstation|psn|kabum|loja)\s*:?\s+)?(?:r\$\s?)?(\d{2,4})|"
    r"r\$\s?(\d{2,4})\s+(?:em|de)\s+(?:creditos?|saldo|vale|gift\s?card)")
_RE_EXTRA_HEADSET = re.compile(r"\+\s*(?:headset|fone|pulse)\b")
_RE_EDICAO = re.compile(r"\bwolverine\b|\bghost of yotei\b|\bfortnite\b|\bedicao (?:limitada|especial|colecionador)\b|"
                        r"\blimited edition\b|\bspecial edition\b|\bcobalt\b|\bmidnight black\b|\bchroma\b|"
                        r"\bcamuflad[oa]\b")
# o que já vem no console-base (pacote com 2 jogos digitais): não é extra
_RE_JOGOS_DA_BASE = re.compile(r"\b(?:2|dois)\s+jogos(?:\s+digitais)?\b|\bastro\s?bot\b|\bastro'?s playroom\b|"
                               r"\bgran turismo\s*7?\b|\bgt\s?7\b|\bcontroles? sem fio\b|\b1 controle\b|"
                               r"\bcom controle\b|\bcontrole dualsense\b")
_RE_OUTRO_EXTRA = re.compile(r"\+\s*(?:jogo\s+)?([a-z][a-z0-9' ]{2,})")

# GTA 6: edição e forma
_RE_UPGRADE = re.compile(r"\bupgrade\b|\bmelhoria\b|\bultedtionupgrade\b|\batualizacao para (?:a )?(?:edicao )?ultimate\b")
_RE_ULTIMATE = re.compile(r"\bultimate\b")
_RE_DIGITAL_GTA = re.compile(r"\bdigital\b|\bpsn\b|\bplaystation store\b|\bps store\b|\bdownload\b|\bchave\b|"
                             r"\bcodigo digital\b|\bconta (?:psn|playstation)\b")
_RE_FISICO_GTA = re.compile(r"\bcode in box\b|\bcodigo na caixa\b|\bmidia fisica\b|\bfisic[oa]\b|\bcaixa\b|\bbox\b")
_RE_KIT_GTA_ACESSORIO = re.compile(r"\+\s*(?:controle|dualsense|headset|fone|capa)\b|\bcom controle\b|"
                                   r"\b(?:e|com) dualsense\b")
# o brinde que acompanha o jogo ("Brinde Mapa", "+ brinde pôster e mapa"): sai antes de procurar produto temático
_RE_BRINDE_DO_JOGO = re.compile(r"(?:\bcom\s+|\+\s*)?\bbrindes?\b\s*:?\s*(?:exclusivos?\s+)?(?:[a-z]+\s*){1,3}")
# o GTA 6 é o brinde de outra compra
_RE_GTA_DE_BRINDE = re.compile(
    r"\b(?:gta\s?(?:6|vi)|grand theft auto\s*:?\s*(?:6|vi))\s+(?:de\s+|como\s+)?(?:brinde|gratis)\b|"
    r"\bganhe\s+(?:o\s+)?(?:jogo\s+)?(?:gta|grand theft)|\bbrindes?\s*:?\s+(?:o\s+)?(?:jogo\s+)?(?:gta|grand theft)")
_RE_OUTRO_PRODUTO_COM_GTA = re.compile(_RE_OUTRO_PRODUTO_NO_TITULO.pattern +
                                       r"|\bplaca de video\b|\brtx\s?\d|\bprocessador\b|\bpc gamer\b|\bmonitor\b")

_RE_VALOR_FACE = re.compile(r"r\$\s?(\d{2,4})(?:[.,]00)?(?!\s*(?:off|de desconto))|\b(\d{2,4})\s*(?:reais|brl)\b")


def _r(motivo: str, **det: Any) -> Classificacao:
    return Classificacao(None, motivo, det)


def _ok(pid: str, **det: Any) -> Classificacao:
    return Classificacao(pid, "", {k: v for k, v in det.items() if v not in (None, [], {}, "")})


def valor_face(texto: Any) -> Optional[float]:
    """Valor de face de um gift card no título ("Gift Card PlayStation R$ 300", "Cartão PSN 100 reais")."""
    m = _RE_VALOR_FACE.search(normaliza(texto))
    if not m:
        return None
    v = float(m.group(1) or m.group(2))
    return v if 10 <= v <= 2000 else None


def _extras_do_console(t: str, base: str, generico: bool = True) -> list[dict]:
    """Extras de um pacote de console (fora o que vem no console-base: 2 jogos digitais, Astro Bot, GT7, o controle
    que acompanha). `generico`: também o "+ <outro jogo>" (só no título; numa linha de cupom "+ frete" não é extra)."""
    out: list[dict] = []
    if _RE_GTA6.search(t) and base == "PS5_PRO":
        out.append({"tipo": "gta6", "valor": VALOR_EXTRA["gta6"]})
    n_controles = 0
    if re.search(r"\b(?:3|tres)\s+controles\b", t):
        n_controles = 2
    elif _RE_EXTRA_CONTROLE.search(t):
        n_controles = 1
    for _ in range(n_controles):
        out.append({"tipo": "controle", "valor": VALOR_EXTRA["controle"]})
    if _RE_EXTRA_LEITOR.search(t) and base != "PS5_DISCO":
        out.append({"tipo": "leitor", "valor": VALOR_EXTRA["leitor"]})
    m = _RE_EXTRA_CREDITO.search(t)
    if m:
        face = float(m.group(1) or m.group(2))
        out.append({"tipo": "credito", "valor": round(face * FRACAO_CREDITO, 2), "face": face})
    if _RE_EXTRA_HEADSET.search(t):
        out.append({"tipo": "headset", "valor": VALOR_EXTRA["headset"]})
    if _RE_EDICAO.search(t):
        out.append({"tipo": "edicao", "valor": VALOR_EXTRA["edicao"]})
    if not out and generico:
        # "+ <outro jogo>": o que vem depois do "+" que não é da base nem um extra conhecido
        limpo = _RE_JOGOS_DA_BASE.sub(" ", t)
        for m in _RE_OUTRO_EXTRA.finditer(limpo):
            resto = m.group(1).strip()
            # sobra do que já saiu como "da base" ("+ Controle Dualsense E 2 Jogos" -> "e"; "+ Jogo ASTRO BOT + Gran
            # Turismo 7" -> "jogo"): conectivo ou a palavra jogo sozinha não é outro jogo (rodada seca de 03/10)
            if re.fullmatch(r"(?:(?:e|com|mais|de|do|da|o|a|um|uma|jogos?)\b\s*)+", resto):
                continue
            # o que sobra de "+ 1 Controle Sony" (o controle que acompanha) também não é extra; nem a versão escrita
            # depois do pacote ("... DualSense + 2 Jogos Digitais Edição Digital", Magalu 240590700, 03/10)
            # "+ Controle", "+ Controle Sem Fio DualSense Branco": o controle que acompanha (os extras de controle já
            # foram vistos acima)
            if _RE_GTA6.match(resto) or re.match(r"(?:ps5|playstation|console|slim|digital|pro\b|r\$|\d|sony\b|"
                                                 r"branc[oa]\b|pret[oa]\b|bivolt\b|cor\b|edicao\b|edition\b|"
                                                 r"versao\b|standard\b|bundle\b|pacote\b|controles?\b|"
                                                 r"dual\s?sense\b|sem fio\b)", resto):
                continue
            out.append({"tipo": "jogo", "valor": VALOR_EXTRA["jogo"], "nome": resto[:40]})
            break
    return out


def _versao_do_console(t: str) -> tuple[str, bool]:
    """('PS5_PRO' | 'PS5_DIGITAL' | 'PS5_DISCO', versão incerta?). Sem nada que diga a versão: Digital (a meta mais
    baixa, então o 🎯 nunca é falso) com a versão incerta."""
    if re.search(_PS5 + r"\s+pro\b", t) or re.search(r"\b2\s?tb\b|\b1000046552\b", t) or \
            (re.search(r"\bpro\b", t) and not re.search(r"\bpro\s+controller\b|\bdualsense edge\b", t)):
        return "PS5_PRO", False
    # "com leitor" e afins só contam como versão com disco quando não é "+ leitor" (kit Digital + leitor avulso)
    disco = bool(_RE_DISCO.search(_RE_EXTRA_LEITOR.sub(" ", t)))
    if _RE_DIGITAL_FORTE.search(t):
        return "PS5_DIGITAL", False
    if disco:
        return "PS5_DISCO", False
    if _RE_DIGITAL.search(t):   # só o 825GB
        return "PS5_DIGITAL", False
    return "PS5_DIGITAL", True


def _classifica_console(t: str) -> Classificacao:
    base, incerta = _versao_do_console(t)
    if _RE_GTA6.search(t) and base in ("PS5_DIGITAL", "PS5_DISCO"):
        pid = "PS5_DIGITAL_GTA6" if base == "PS5_DIGITAL" else "PS5_DISCO_GTA6"
        extras = [e for e in _extras_do_console(t, base) if e["tipo"] != "gta6"]
        if extras:
            # pacote com GTA e mais alguma coisa: kit sobre o pacote
            return _ok("PS5_KIT", base=pid, extras=extras, valor_extra=sum(e["valor"] for e in extras),
                       versao_incerta=incerta)
        return _ok(pid, versao_incerta=incerta)
    extras = _extras_do_console(t, base)
    if extras:
        return _ok("PS5_KIT", base=base, extras=extras, valor_extra=sum(e["valor"] for e in extras),
                   versao_incerta=incerta)
    return _ok(base, versao_incerta=incerta)


def _classifica_gta(t: str, loja: str) -> Classificacao:
    if _RE_KIT_GTA_ACESSORIO.search(t):
        return _r("kit de jogo e acessório: o preço não é só do jogo")
    if re.search(r"\bxbox\b|\bseries [xs]\b", t) and not _RE_PS5.search(t):
        return _r("outro aparelho: GTA 6 de Xbox")
    incerta = not _RE_PS5.search(t) and loja != "PlayStation Store"   # na PS Store a plataforma é a do PS5
    if _RE_UPGRADE.search(t):
        return _ok("GTA6_UPGRADE", plataforma_incerta=incerta)
    if _RE_ULTIMATE.search(t):
        return _ok("GTA6_ULTIMATE", plataforma_incerta=incerta)
    digital = loja == "PlayStation Store" or (_RE_DIGITAL_GTA.search(t) and not _RE_FISICO_GTA.search(t))
    return _ok("GTA6_DIGITAL" if digital else "GTA6_CODE_IN_BOX", plataforma_incerta=incerta)


def _classifica_nao_tv(t: str, loja: str = "") -> Classificacao:
    """Classificador do PS5, do GTA 6, do gift card e do leitor (texto já normalizado)."""
    # "Jogo de Vídeo Game Take 2 ... Grand Theft Auto 5 para PS5" (nocnoc no Magalu, 03/10) é um jogo, não um console
    t = re.sub(r"\b(?:jogos?|videojogos?)\s+(?:de\s+)?video(?:\s?games?)?\b", "jogo", t)
    # "Jogo de Vídeo Ubisoft Anno 1800 Edição Console PS5" (nocnoc no Magalu, 03/10): a edição do jogo para console
    t = re.sub(r"\bedicao (?:para )?consoles?\b", "edicao", t)
    tem_ps = bool(_RE_PS5.search(t)) or bool(re.search(r"\bplaystation\b", t))
    gta = bool(_RE_GTA6.search(t))
    gift = bool(_RE_GIFT.search(t))
    if not (tem_ps or gta or gift or _RE_GTA_OUTRO.search(t) or _RE_LEITOR.search(t)):
        return _r("sem produto")
    if _RE_SERVICO_INICIO.search(t):
        return _r("serviço: " + _RE_SERVICO_INICIO.search(t).group(0).strip(" -[]"))
    if _RE_ESTADO.search(t):
        return _r("estado: " + _RE_ESTADO.search(t).group(0))
    if _RE_CONTA.search(t):
        return _r("conta compartilhada: " + _RE_CONTA.search(t).group(0))
    if _RE_ESTRANGEIRO.search(t):
        return _r("versão estrangeira: " + _RE_ESTRANGEIRO.search(t).group(0))
    if _RE_COLECIONADOR.search(t):
        return _r("edição de colecionador revendida: " + _RE_COLECIONADOR.search(t).group(0))
    if _RE_RESUMO.search(t) or (len(re.findall(r"r\$\s?\d", t)) >= 2 and _RE_OUTRO_PRODUTO_NO_TITULO.search(t)):
        return _r("resumo de várias ofertas")
    if _RE_ASSINATURA.search(t) and not _RE_CONSOLE_PALAVRA.search(t):
        return _r("assinatura: " + _RE_ASSINATURA.search(t).group(0))
    # leitor de disco avulso (o leitor-peça vem antes de qualquer núcleo de console, mesmo com "Console(s) PS5" depois)
    if _e_o_leitor(t):
        if not tem_ps:
            return _r("sem produto")
        return _ok("LEITOR_PS5")
    m = _RE_INICIO_ACESSORIO.search(t)
    if m and not _RE_CONSOLE_PALAVRA.search(t[:m.start(1)]):
        if _RE_TEMATICO.match(m.group(1)) and gta:
            return _r("produto temático: " + m.group(1))
        return _r("acessório: " + m.group(1))
    # o brinde do jogo ("GTA VI PS5 Pré-venda Mídia Física Brinde Mapa") não é o produto temático
    sem_brinde = _RE_BRINDE_DO_JOGO.sub(" ", t)
    if gta and not _RE_CONSOLE_PALAVRA.search(t):
        # a peça ou o produto temático em qualquer ponto de um título do GTA sem a palavra console ("GTA VI Mousepad
        # Gamer 90x40", "GTA VI Caneca PS5 Slim": o "PS5 Slim" ali é a plataforma da peça, não um pacote com o console)
        mp = _RE_PECA_COM_GTA.search(sem_brinde)
        if mp:
            return _r("acessório: " + mp.group(0))
        mt = _RE_TEMATICO.search(sem_brinde)
        if mt:
            return _r("produto temático: " + mt.group(0))
    # gift card (sem console no título: "Console PS5 + gift card de R$ 500" e "Kit PS5 Digital com R$ 500 em créditos
    # PS Store" são kit)
    console_no_titulo = bool(_RE_CONSOLE_FORTE.search(t)) or bool(
        _RE_PS5.search(t) and re.search(r"\b(?:digital|slim|pro|disco|disk|com leitor|midia fisica|kit|bundle|pacote)\b",
                                        t))
    if gift and not console_no_titulo:
        if _RE_GIFT_OUTRA_LOJA.search(t) and not re.search(r"\bplaystation\b|\bpsn\b|\bps store\b", t):
            return _r("gift card de outra loja")
        if not re.search(r"\bplaystation\b|\bpsn\b|\bps store\b|\bsony\b|\bps5\b", t):
            return _r("sem produto")
        return _ok("GIFT_CARD_PSN", valor_face=valor_face(t))
    console_forte = bool(_RE_CONSOLE_FORTE.search(t))
    if _RE_GTA_OUTRO.search(t) and not gta and not console_forte:
        # outro GTA (V, Trilogy, San Andreas...) antes do "para PS5" ("Jogo Grand Theft Auto 5 Para PS5" é outro jogo,
        # não acessório)
        return _r("outro jogo: " + _RE_GTA_OUTRO.search(t).group(0))
    if _RE_PARA_PS5.search(t) and not _RE_CONSOLE_PALAVRA.search(t[:_RE_PARA_PS5.search(t).start()]):
        return _r("acessório: " + _RE_PARA_PS5.search(t).group(0))
    outro = _RE_OUTRO_APARELHO.search(t)
    if outro and not (_RE_PS5.search(t) and (console_forte or gta)):
        return _r("outro aparelho: " + outro.group(0))
    if gta and not console_forte:
        # o GTA 6 de brinde na compra de outro produto ("Notebook Gamer + GTA VI de brinde", "Ganhe GTA VI na compra de
        # Placa de Vídeo"): o preço é do outro produto
        if _RE_GTA_DE_BRINDE.search(t) or _RE_OUTRO_PRODUTO_COM_GTA.search(t):
            return _r("o GTA 6 é brinde/parte de outro produto")
        return _classifica_gta(t, loja)   # o jogo (sem console no título); com console é o pacote
    if not tem_ps:
        return _r("sem produto")
    if _RE_INICIO_JOGO.search(t) and not _RE_CONSOLE_PALAVRA.search(t):
        return _r("outro jogo")
    if not _RE_PS5.search(t):
        # "Console PlayStation Slim" sem o 5: pode ser PS4 ou PS3 (a lista da KaBuM tem os dois)
        return _r("sem PS5 no título")
    # console: palavra "console", armazenamento, Slim, Pro; ou o título é só "PlayStation 5 (versão)"
    inicio_ps5 = bool(re.match(_PREFIXO_TITULO + r"(?:console\s+)?(?:sony\s+)?(?:ps5|playstation 5)\b", t))
    if console_forte or (inicio_ps5 and _RE_VERSAO.search(t)) or (inicio_ps5 and len(t) <= 40):
        if outro and not _RE_PS5.search(t):
            return _r("outro aparelho: " + outro.group(0))
        return _classifica_console(t)
    return _r("sem console no título (jogo ou acessório do PS5)")


@lru_cache(maxsize=8192)
def _classifica_titulo(t: str, loja: str) -> Classificacao:
    from .filtro import modelo_do_titulo, motivo_rejeicao

    tv = modelo_do_titulo(t)
    if tv:
        return _ok(tv)
    c = _classifica_nao_tv(normaliza(t), loja)
    if c.produto or c.motivo != "sem produto":
        return c
    # cita uma TV C6K que não é a 55" nem a 65" (vizinho, outro tamanho, acessório da TV): "outro" produto
    if re.search(r"c6k(?![a-z0-9])", normaliza(t)):
        return _r("TV de outro modelo: " + motivo_rejeicao(t, MODELO_55))
    return c


def classifica(titulo: Any, loja: Any = None, ean: Any = None, id_loja: Any = None) -> Classificacao:
    """O produto de um título de loja/postagem. Dados estruturados valem mais que o título: o EAN ou o id do anúncio na
    loja dizem QUAL produto é (o título ainda recusa o estado: usado, recondicionado, versão estrangeira...).

    Recusa: acessório (controle, capa, suporte, headset, SSD, "compatível com PS5"), outro jogo (GTA V, Trilogy,
    qualquer jogo que não o GTA 6), outro aparelho (PS4, PS VR2, PlayStation Portal, Xbox, Switch), assinatura (PS
    Plus, GTA+), estado (usado, seminovo, recondicionado, vitrine, caixa aberta, "Quase Novo"), versão estrangeira (KSA,
    International, importado), edição de colecionador revendida (30º aniversário), produto temático do GTA (camiseta,
    pôster...) e kit de jogo + acessório (GTA 6 + DualSense). Pacote com 2 jogos digitais / Astro Bot / GT7 fica no
    console-base; "+ GTA 6" vira o pacote com o GTA; edição especial (Wolverine, Ghost of Yotei, Fortnite, edição
    limitada), controle extra, crédito da PS Store, headset ou outro jogo viram PS5_KIT com o valor do extra."""
    from .util import loja_canonica

    lj = loja_canonica(str(loja)) if loja else ""
    titulo = str(titulo or "")
    hint = produto_por_ean(ean) if ean else None
    if not hint and id_loja:
        hint = produto_por_id_loja(lj or None, id_loja)
    c = _classifica_titulo(titulo, lj)
    c = Classificacao(c.produto, c.motivo, dict(c.detalhes))   # o resultado em cache não é compartilhado com quem altera
    if hint:
        t = normaliza(titulo)
        if not eh_tv(hint):
            for rx, rot in ((_RE_ESTADO, "estado"), (_RE_ESTRANGEIRO, "versão estrangeira"),
                            (_RE_COLECIONADOR, "edição de colecionador revendida"), (_RE_CONTA, "conta compartilhada"),
                            (_RE_SERVICO_INICIO, "serviço")):
                m = rx.search(t)
                if m:
                    return _r(f"{rot}: {m.group(0)}")
        if c.produto == hint:
            return c
        if hint == "PS5_KIT":
            return _ok(hint, **_kit_padrao(t))   # o id diz que é kit/edição: a base e o extra saem do título
        return _ok(hint)
    return c


def _kit_padrao(t: str) -> dict:
    base, incerta = _versao_do_console(t)
    extras = _extras_do_console(t, base) or [{"tipo": "edicao", "valor": VALOR_EXTRA["edicao"]}]
    return {"base": base, "extras": extras, "valor_extra": sum(e["valor"] for e in extras), "versao_incerta": incerta}


def produto_do_titulo(titulo: Any, loja: Any = None) -> Optional[str]:
    return classifica(titulo, loja).produto


def detalhes_de(o: Any) -> dict:
    """Detalhes da classificação de uma oferta (Oferta, registro do state/latest): os gravados no extra pela coleta
    (base, extras, valor_extra, valor_face...) ou, sem eles, os do título."""
    extra = (o.get("extra") if isinstance(o, dict) else getattr(o, "extra", None)) or {}
    det = extra.get("produto") if isinstance(extra.get("produto"), dict) else {}
    if det:
        return det
    titulo = o.get("titulo") if isinstance(o, dict) else getattr(o, "titulo", "")
    loja = o.get("loja") if isinstance(o, dict) else getattr(o, "loja", "")
    pid = _pid(o)
    c = _classifica_titulo(re.sub(r"^\[[^\]]*\]\s*", "", str(titulo or "")), str(loja or ""))
    if c.produto == pid:
        return dict(c.detalhes)
    if pid == "PS5_KIT":
        return _kit_padrao(normaliza(titulo))
    if pid == "GIFT_CARD_PSN":
        return {"valor_face": valor_face(titulo)} if valor_face(titulo) else {}
    return {}


def _pid(o: Any) -> str:
    from .models import modelo_de

    return modelo_de(o)


# ---------------------------------------------------------------------------------------------------------------------
# mensagem livre (Telegram): um bloco por produto
# ---------------------------------------------------------------------------------------------------------------------

class Trecho(NamedTuple):
    titulo: str      # linha-título do produto
    trecho: str      # as linhas do bloco dele (de onde saem preço, parcelado e cupom)
    preambulo: str   # linhas antes do 1º produto (o cupom delas vale para todos)
    detalhes: dict


# produto que não é dos monitorados, no começo da linha (abre o bloco de outro produto)
_RE_LINHA_OUTRO = re.compile(
    r"^[^a-z0-9]*(?:\d{1,2}\s*[-.)]\s*)?(?:notebook|laptop|celular|smartphone|iphone|ipad|tablet|galaxy|redmi|"
    r"motorola|xiaomi|airpods|echo dot|cadeira|mesa|geladeira|fogao|micro-?ondas|air\s*fryer|lavadora|"
    r"ar[\s-]condicionado|ventilador|aspirador|cafeteira|monitor|fones?|headset|mouse|teclado|ssd|hd externo|"
    r"pendrive|xbox|nintendo|kindle|smartwatch|relogio|caixa de som|impressora|roteador|camera|projetor|"
    r"placa de video|tenis|perfume|smart\s*tv|tv\b|televisor|controle|dualsense|jogo|game|soundbar|"
    # peças que abrem a linha de outro produto na mensagem do GTA ("🔥 GTA VI / Mousepad Gamer Grande 90x40 / R$ 249")
    r"mouse\s?pads?|peliculas?|skins?\s+(?:adesiv\w*\s+)?(?:(?:para|pra|p/)\s+)?(?:ps5|playstation|consoles?|controles?)|"
    r"suportes?\s+(?:gamer|(?:para|pra|p/|de)\s+(?:o\s+)?(?:controles?|headsets?|fones?|consoles?)))\b")


_RE_LINHA_OUTRO_APARELHO = re.compile(
    _PREFIXO_TITULO + r"(?:console\s+)?(?:ps\s?4|playstation 4|xbox|nintendo|switch|ps\s?vr|playstation vr|"
                      r"playstation portal|steam deck)\b")


def _linha_dona(linha: str, loja: str) -> tuple[Optional[str], Classificacao]:
    """(dono, classificação): o produto monitorado (não TV) que a linha cita, 'outro' quando a linha é o título de
    outro produto (uma TV, um acessório, outro jogo ou aparelho que abre a linha), ou None (linha de preço, cupom,
    descrição: "Compatível com jogos de PS4 e PS5" não abre bloco)."""
    c = classifica(linha, loja)
    if c.produto and not eh_tv(c.produto):
        return c.produto, c
    n = normaliza(linha)
    # "outro jogo: gta" (GTA V, Trilogy...) também abre o bloco de outro produto ("Grand Theft Auto V para PS5")
    if c.produto or c.motivo.startswith(("acessório", "TV de outro modelo", "produto temático", "outro jogo: ")) \
            or _RE_LINHA_OUTRO.search(n) or _RE_LINHA_OUTRO_APARELHO.search(n):
        return "outro", c
    return None, c


def _tem_preco(texto: str, pid: Optional[str]) -> bool:
    from .util import preco_postagem

    return preco_postagem(texto, piso(pid) if pid and pid != "outro" else 30.0) is not None


def extrai_produtos(texto: str, loja: Any = None) -> dict[str, Trecho]:
    """{produto: Trecho} de cada produto monitorado numa mensagem livre (canal do Telegram).

    As TVs saem da leitura de sempre (filtro.extrai_modelos). Os outros: cada linha que cita um produto (ou outro
    produto qualquer) abre um bloco, e as linhas seguintes são dele até o próximo; as linhas antes do 1º bloco são o
    preâmbulo (o cupom delas vale para todos). Preço antes do nome ("💰 R$ 3.599" / "PS5 Slim Digital"): quando a
    leitura de cima para baixo deixa algum bloco sem preço e nenhuma linha-título tem preço, a de baixo para cima vale.
    Bloco com estado de usado/estrangeiro é descartado. Numa mensagem com outro produto, bloco sem preço é descartado
    (o preço dele poderia ser o do outro)."""
    from .filtro import extrai_modelos
    from .util import loja_canonica

    out: dict[str, Trecho] = {}
    for m, (tit, tre, pre) in extrai_modelos(texto).items():
        out[m] = Trecho(tit, tre, pre, {})
    lj = loja_canonica(str(loja)) if loja else ""
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    if not linhas:
        return out
    donos: list[Optional[str]] = []
    classes: list[Classificacao] = []
    for l in linhas:
        d, c = _linha_dona(l, lj)
        donos.append(d)
        classes.append(c)
    produtos_vistos = [d for d in donos if d and d != "outro"]
    if not produtos_vistos:
        return out
    # leitura de cima para baixo: cada linha é do último cabeçalho acima dela
    atual: Optional[str] = None
    dono_linha: list[str] = []
    cabecalhos: list[int] = []
    for i, d in enumerate(donos):
        if d and d != atual:
            atual = d
            cabecalhos.append(i)
        dono_linha.append(atual or "antes")
    multi = len({d for d in donos if d}) > 1 or "outro" in donos
    precos = [_tem_preco(l, None) for l in linhas]

    def sem_preco(dl: list[str]) -> bool:
        return any(donos[c] != "outro" and not any(precos[j] and dl[j] == donos[c] for j in range(len(linhas)))
                   for c in cabecalhos)

    if multi and sem_preco(dono_linha) and not any(precos[c] for c in cabecalhos):
        # preço ANTES do nome ("💰 R$ 341" / "GTA 6 Code in Box" / "💰 R$ 3.599" / "PS5 Slim Digital"): as linhas de
        # preço logo acima de cada cabeçalho são dele, se todo cabeçalho tem as suas
        relido = list(dono_linha)
        for c in cabecalhos:
            j = c
            while j > 0 and donos[j - 1] is None and precos[j - 1]:
                j -= 1
            if j == c:
                break
            for k in range(j, c):
                relido[k] = donos[c]
        else:
            dono_linha = relido
    preambulo = "\n".join(l for l, d in zip(linhas, dono_linha) if d == "antes") if multi else ""
    for pid in dict.fromkeys(produtos_vistos):
        bloco = [l for l, d in zip(linhas, dono_linha) if d == pid or (not multi and d == "antes")]
        trecho = "\n".join(bloco)
        nt = normaliza(trecho)
        if _RE_ESTADO.search(nt) or _RE_ESTRANGEIRO.search(nt) or _RE_COLECIONADOR.search(nt) or _RE_CONTA.search(nt):
            continue   # usado, caixa aberta, versão estrangeira, conta compartilhada: não é o produto novo e nacional
        if familia(pid) == FAMILIA_GTA6 and _RE_PECA_COM_GTA.search(_RE_BRINDE_DO_JOGO.sub(" ", nt)):
            continue   # o bloco do GTA fala de uma peça ("🔥 GTA VI" / "Tapete Gamer 90x40" / "R$ 249"): o preço é dela
        if multi and not _tem_preco(trecho, pid):
            continue   # o preço dele pode estar no bloco de outro produto: sem preço, nada de alerta
        if _so_preco_abaixo(trecho, pid):
            continue
        idx = next(i for i, d in enumerate(donos) if d == pid)
        det = dict(classes[idx].detalhes)
        dono = pid
        if pid in ("PS5_DIGITAL", "PS5_DISCO", "PS5_PRO"):
            # extras escritos em outra linha do bloco ("+ 2 controles", "+ R$ 500 em créditos da PS Store")
            extras = _extras_do_console(nt, pid, generico=False)
            if extras:
                dono = "PS5_KIT"
                det = {"base": pid, "extras": extras, "valor_extra": sum(e["valor"] for e in extras)}
        if pid == "GIFT_CARD_PSN" and not det.get("valor_face"):
            vf = valor_face(linhas[idx]) or valor_face(trecho)
            if vf:
                det["valor_face"] = vf
        if dono not in out:
            out[dono] = Trecho(linhas[idx], trecho, preambulo, det)
    return out


def _so_preco_abaixo(trecho: str, pid: str) -> bool:
    """O bloco só anuncia um preço abaixo do piso do produto (parcela, acessório): não é o produto."""
    from .util import so_preco_abaixo_do_piso

    return so_preco_abaixo_do_piso(trecho, piso(pid)) if piso(pid) > 100 else False


# ---------------------------------------------------------------------------------------------------------------------
# entrega do GTA 6 (Code in Box e pacotes com o jogo)
# ---------------------------------------------------------------------------------------------------------------------

class Entrega(NamedTuple):
    classe: str                 # 'a_tempo' (até 18/11) | 'no_dia' (19/11) | 'depois' | 'desconhecida'
    data: Optional[str]         # ISO (prevista), quando se sabe
    origem: str                 # 'loja' (lida na loja) | 'estimativa' (tabela da pesquisa) | ''
    cep_referencia: bool        # prazo calculado com o CEP de referência (São Paulo), não o do usuário
    texto: str                  # linha da mensagem

    @property
    def a_tempo(self) -> Optional[bool]:
        return {"a_tempo": True, "no_dia": False, "depois": False}.get(self.classe)


# Prazos da pesquisa de 03/10/2026 (sem o CEP do usuário; CEP de referência de São Paulo). Palpite marcado como
# estimativa: a fonte da loja (cotação com o CEP) substitui. (loja, vendedor: regex do nome normalizado ou None para
# qualquer um / postagem, data ISO ou None, classe)
ENTREGA_ESTIMADA_GTA6: tuple[tuple[str, Optional[str], Optional[str], str], ...] = (
    ("Amazon", r"^(?:amazon(?:combr)?)?$", "2026-11-16", "a_tempo"),      # vendido pela Amazon: previsão 16/11
    ("KaBuM!", r"^(?:kabum)?$", "2026-11-17", "a_tempo"),                 # 1P: envia a partir de 12/11; 17/11 em SP
    ("KaBuM!", r"mercadoonlinesp", None, "depois"),                       # 3P: "enviado a partir de 20/11"
    ("Netshoes", None, "2026-11-30", "depois"),                           # ~30/11 (relatos de 25/11 a 08/12)
    ("Carrefour", None, None, "depois"),                                  # "envio a partir de 19 de novembro"
    ("Shopee", None, None, "depois"),                                     # 22/11 a 23/12, envia depois de 19/11
    ("Fast Shop", None, None, "depois"),                                  # Webfones: 39-40 dias úteis
)


def _data_br(iso: Optional[str]) -> str:
    m = re.match(r"\d{4}-(\d\d)-(\d\d)", iso or "")
    return f"{m.group(2)}/{m.group(1)}" if m else (iso or "?")


def _classe_da_data(iso: str) -> str:
    d = iso[:10]
    if d <= ENTREGA_LIMITE_GTA6:
        return "a_tempo"
    if d == LANCAMENTO_GTA6:
        return "no_dia"
    return "depois"


def entrega(o: Any) -> Optional[Entrega]:
    """Entrega do GTA 6 de uma oferta/postagem que traz o Code in Box (None para os outros produtos). Ordem: a data
    prevista lida pela coleta (extra['entrega_prevista'], ISO), o booleano extra['entrega_ate_lancamento'] e, sem
    nada da loja, a estimativa da pesquisa por loja/vendedor (prazo aproximado, CEP de referência)."""
    pid = _pid(o)
    p = produto(pid)
    if not p or not p.gta_fisico:
        return None
    extra = (o.get("extra") if isinstance(o, dict) else getattr(o, "extra", None)) or {}
    ref = bool(extra.get("cep_referencia"))
    data = str(extra.get("entrega_prevista") or "")[:10] or None
    if data and re.match(r"\d{4}-\d\d-\d\d$", data):
        if data < INICIO_ENVIO_GTA6:
            # antes de as caixas existirem (12/11): é o prazo contado a partir do dia da leitura, não a entrega da
            # pré-venda (as fontes já reprojetam; isto é a rede de segurança para dado gravado sem o ajuste)
            return Entrega("desconhecida", None, "loja", ref,
                           f"📦 Entrega: a loja mostrou {_data_br(data)}, antes de as caixas saírem (12/11) — "
                           "prazo desconhecido: confira antes de comprar (precisa chegar até 18/11)")
        classe = _classe_da_data(data)
        # prazo da loja reprojetado a partir de 12/11 (sources/entrega.ajusta_pre_venda): a mensagem diz
        nota = "contado a partir de 12/11" if "12/11" in str(extra.get("entrega_origem") or "") else ""
        return Entrega(classe, data, "loja", ref, _texto_entrega(classe, data, "loja", ref, nota))
    ate = extra.get("entrega_ate_lancamento")
    if isinstance(ate, bool):
        classe = "a_tempo" if ate else "depois"
        return Entrega(classe, None, "loja", ref, _texto_entrega(classe, None, "loja", ref))
    from .util import loja_canonica

    loja = loja_canonica(str((o.get("loja") if isinstance(o, dict) else getattr(o, "loja", "")) or ""))
    vend = re.sub(r"[^a-z0-9]", "", _ascii((o.get("vendedor") if isinstance(o, dict) else getattr(o, "vendedor", ""))))
    for lj, rx_vend, d, classe in ENTREGA_ESTIMADA_GTA6:
        if lj != loja or (rx_vend is not None and not re.search(rx_vend, vend)):
            continue
        return Entrega(classe, d, "estimativa", True, _texto_entrega(classe, d, "estimativa", True))
    return Entrega("desconhecida", None, "", ref, _texto_entrega("desconhecida", None, "", ref))


def _texto_entrega(classe: str, data: Optional[str], origem: str, ref: bool, nota: str = "") -> str:
    quando = f"previsão {_data_br(data)}" if data else ""
    if nota:
        quando = (quando + " " if quando else "") + f"({nota})"
    if origem == "estimativa":
        quando = (quando + " " if quando else "") + "(estimativa da pesquisa de 03/10)"
    elif ref:
        quando = (quando + " " if quando else "") + "(prazo aproximado, CEP de referência)"
    if classe == "a_tempo":
        fim = "chega a tempo ✅ (até 18/11; lançamento 19/11)"
    elif classe == "no_dia":
        fim = "⚠️ chega no dia 19/11: joga no dia, mas não à meia-noite"
    elif classe == "depois":
        fim = "⚠️ chega DEPOIS do lançamento (19/11)"
    else:
        fim = "prazo desconhecido: confira antes de comprar (precisa chegar até 18/11)"
    return "📦 Entrega: " + (f"{quando} — " if quando else "") + fim


# ---------------------------------------------------------------------------------------------------------------------
# metas por oferta e custo comparável
# ---------------------------------------------------------------------------------------------------------------------

class Alvo(NamedTuple):
    pix: Optional[float]
    parcelado: Optional[float]
    nota: str = ""             # o que decidiu a meta (entrega, extra do kit, desconto do gift card)


def _alvo_base(pid: str) -> tuple[Optional[float], Optional[float]]:
    from . import config

    return config.alvo_pix(pid), config.alvo_parcelado(pid)


def _loja_oficial_gift(o: Any) -> bool:
    from .util import loja_canonica

    loja = loja_canonica(str((o.get("loja") if isinstance(o, dict) else getattr(o, "loja", "")) or ""))
    if loja not in LOJAS_GIFT_OFICIAIS:
        return False
    if loja != "Mercado Livre":
        return True
    # no Mercado Livre, só a loja oficial PlayStation (vendedor 1047493289 / loja oficial 1473)
    extra = (o.get("extra") if isinstance(o, dict) else getattr(o, "extra", None)) or {}
    vend = _ascii((o.get("vendedor") if isinstance(o, dict) else getattr(o, "vendedor", "")) or "")
    campos = [(o.get(k) if isinstance(o, dict) else getattr(o, k, "")) for k in ("titulo", "cupom")]
    texto = _ascii(" ".join(str(x) for x in (*campos, extra.get("texto") or "") if x))
    # o vendedor da loja oficial, o texto que diz "loja oficial PlayStation/Sony" ou o cupom da campanha das lojas
    # oficiais do ML (LOJASOFICIAIS: o caso de 23/09, R$ 100 por R$ 85)
    return str(extra.get("vendedor_id") or "") == ML_PLAYSTATION_VENDEDOR or "playstation" in vend or \
        bool(re.search(r"loja oficial(?: da)? (?:playstation|sony)|\blojasoficiais\b", texto))


def alvos_da_oferta(o: Any, hoje: Optional[str] = None) -> Alvo:
    """A meta desta oferta: a do produto, com os casos que dependem da oferta:
    - GTA 6 Code in Box: R$ 345 / 370 se chega até 18/11 (ou prazo desconhecido, com o aviso para conferir); R$ 300 /
      320 se chega depois (ou já passou do lançamento);
    - kit/edição especial: meta do console-base + valor do extra;
    - gift card: 85% do valor de face, e só em loja oficial (fora dela, sem meta)."""
    pid = _pid(o)
    p = produto(pid)
    if p is None:
        return Alvo(None, None)
    if pid == "PS5_KIT":
        det = detalhes_de(o)
        base = det.get("base") or "PS5_DIGITAL"
        bp, bparc = _alvo_base(base)
        extra = float(det.get("valor_extra") or VALOR_EXTRA["edicao"])
        nota = f"meta do {nome(base)} + R$ {extra:.0f} do extra"
        return Alvo(bp + extra if bp else None, bparc + extra if bparc else None, nota)
    if pid == "GIFT_CARD_PSN":
        face = detalhes_de(o).get("valor_face")
        if not face:
            return Alvo(None, None, "sem o valor de face")
        if not _loja_oficial_gift(o):
            return Alvo(None, None, "loja não oficial para gift card")
        v = round(face * (1 - DESCONTO_GIFT_MINIMO), 2)
        return Alvo(v, v, f"{round(DESCONTO_GIFT_MINIMO * 100)}% de desconto sobre R$ {face:.0f}")
    pix, parc = _alvo_base(pid)
    if pid == "GTA6_CODE_IN_BOX":
        hoje = hoje or date.today().isoformat()
        e = entrega(o)
        if hoje > LANCAMENTO_GTA6 or (e and e.classe in ("depois", "no_dia")):
            return Alvo(p.alvo_pix_tardio, p.alvo_parcelado_tardio, "chega depois de 18/11")
        if e and e.classe == "desconhecida":
            return Alvo(pix, parc, "prazo desconhecido")
        return Alvo(pix, parc, "chega até 18/11")
    return Alvo(pix, parc)


# preço só para assinante (decisão do usuário em 03/10: ele só tem Nubank/NuPay; sem Prime, Meli+, Méliuz nem cliente
# ouro do Magalu): a postagem sai, sem 🎯, com o aviso
_RE_SO_ASSINANTE = re.compile(r"\bprime\b|\bmeli\s?\+|\bmeli mais\b|\bassinantes?\b|\bninja\b|\bcli(?:ente)?\.? ouro\b")


def exige_assinatura(o: Any) -> Optional[str]:
    """A assinatura que o preço da oferta exige ('prime', 'meli+', 'cliente ouro'...), pelo título e pelo cupom; None
    quando o preço é o público."""
    campos = [(o.get(k) if isinstance(o, dict) else getattr(o, k, "")) for k in ("titulo", "cupom")]
    m = _RE_SO_ASSINANTE.search(normaliza(" ".join(str(x) for x in campos if x)))
    if m:
        return m.group(0)
    # o código do cupom grudado ("PRIMEGAME5", "PRIMEGTA", "OFERTAMELIMAIS"; "PRIMEIRA..." é primeira compra)
    m = _RE_CODIGO_ASSINANTE.search(_ascii(campos[1] or ""))
    return {"melimais": "meli+"}.get(m.group(0), m.group(0)) if m else None


_RE_CODIGO_ASSINANTE = re.compile(r"prime(?!ir)|melimais|ninja")


def desconto_gift_card(ofertas: Iterable[Any], dias: float = 7.0) -> Optional[tuple[float, Any]]:
    """(maior desconto, oferta) de gift card da PlayStation em loja oficial entre as ofertas/postagens ativas e
    recentes da rodada. None sem nenhum."""
    from .util import dias_desde

    melhor: Optional[tuple[float, Any]] = None
    for o in ofertas:
        if _pid(o) != "GIFT_CARD_PSN":
            continue
        ativo = o.get("ativo", True) if isinstance(o, dict) else getattr(o, "ativo", True)
        if ativo is False:
            continue
        pub = o.get("publicado") if isinstance(o, dict) else getattr(o, "publicado", None)
        d = dias_desde(pub)
        if d is not None and d > dias:
            continue
        face = detalhes_de(o).get("valor_face")
        preco = _melhor_preco(o)
        if not face or not preco or preco >= face or not _loja_oficial_gift(o):
            continue
        desc = 1 - preco / face
        if desc > 0.6:
            continue   # desconto absurdo: não é referência
        if melhor is None or desc > melhor[0]:
            melhor = (desc, o)
    return melhor


def _melhor_preco(o: Any) -> Optional[float]:
    vals = []
    for k in ("preco", "preco_pix"):
        v = o.get(k) if isinstance(o, dict) else getattr(o, k, None)
        try:
            if v and float(v) > 0:
                vals.append(float(v))
        except (TypeError, ValueError):
            continue
    if vals:
        return min(vals)
    v = o.get("melhor_preco") if isinstance(o, dict) else None
    return float(v) if v else None


def preco_com_cupom_do_anuncio(o: Any) -> Optional[tuple[float, str]]:
    """(preço, código) com o cupom da página do anúncio (extra['preco_com_cupom'], gravado pela coleta: no Magalu, o
    GTA60 do GTA 6, o LU325 do PS5 Digital) nos produtos que não são TV, quando fica abaixo do melhor preço e o cupom não
    é só de assinante. É o preço público do anúncio com o cupom dele (a decisão de 03/10: comparar pelo custo final);
    nas TVs nada muda (o testador de cupons confere o cupom no carrinho, como antes). None sem cupom que valha."""
    pid = _pid(o)
    if eh_tv(pid) or produto(pid) is None:
        return None
    extra = (o.get("extra") if isinstance(o, dict) else getattr(o, "extra", None)) or {}
    v = extra.get("preco_com_cupom")
    try:
        v = float(v) if v else None
    except (TypeError, ValueError):
        v = None
    p = _melhor_preco(o)
    # o código é o do cupom que deu o preço (o anúncio pode ter um percentual antes); registro antigo: o cupom da oferta
    codigo = str(extra.get("cupom_preco") or (o.get("cupom") if isinstance(o, dict) else getattr(o, "cupom", ""))
                 or "").strip()
    if not v or not p or v >= p or not codigo or not preco_plausivel(pid, v):
        return None
    regra = normaliza(extra.get("cupom_regra") or "")
    if exige_assinatura(o) or _RE_SO_ASSINANTE.search(regra):
        return None
    validade = str(extra.get("cupom_validade") or "")[:10]
    if validade and validade < date.today().isoformat():
        return None   # o cupom do anúncio venceu
    m = _RE_COMPRA_MINIMA.search(regra)
    if m:
        from .util import parse_preco

        minimo = parse_preco(m.group(1))
        if minimo and minimo > p:
            return None   # compra mínima acima do preço do produto
    return round(v, 2), codigo


_RE_COMPRA_MINIMA = re.compile(r"(?:acima de|a partir de|minim[oa] de|compras? de)\s*r\$\s*([\d.,]+)")


def paga_com_gift_card(o: Any) -> bool:
    """O gift card da PlayStation paga esta oferta? Só a compra na própria PS Store (o saldo vai para a conta PSN).
    Chave ou código vendido por outra loja (Eneba, Nuuvem, revendedor do Mercado Livre) se paga com o meio de pagamento
    dela: o desconto do gift card não vale ali (revisão de 03/10)."""
    from .util import loja_canonica

    loja = loja_canonica(str((o.get("loja") if isinstance(o, dict) else getattr(o, "loja", "")) or ""))
    return loja == "PlayStation Store"


def preco_comparavel(o: Any, desconto_gift: Optional[float] = None) -> Optional[float]:
    """O preço que se compara com a meta: o melhor preço (Pix/à vista), ou o preço com o cupom da página do anúncio
    (preco_com_cupom_do_anuncio, só nos produtos que não são TV); no produto digital vendido na PS Store, o custo
    efetivo pagando com gift card comprado com o maior desconto visto (quando ele existe). Em outra loja o gift card
    não paga: vale o preço dela."""
    p = _melhor_preco(o)
    if p and desconto_gift and produto(_pid(o)) and produto(_pid(o)).digital and paga_com_gift_card(o):
        return round(p * (1 - desconto_gift), 2)
    cc = preco_com_cupom_do_anuncio(o)
    if cc:
        return cc[0]
    return p


def custo_digital_com_gift(desconto: float) -> dict[str, float]:
    """{produto digital: custo efetivo} pelo preço oficial da PS Store com o desconto do gift card."""
    return {i: round(p.preco_oficial * (1 - desconto), 2) for i, p in PRODUTOS.items()
            if p.digital and p.preco_oficial}


def _fmt(v: Optional[float]) -> str:
    from .util import fmt_preco

    return fmt_preco(v)


def distancia(valor: Optional[float], meta: Optional[float]) -> str:
    """'R$ 49,00 acima da meta' / 'R$ 51,00 abaixo da meta ✅' / 'na meta ✅'."""
    if not valor or not meta:
        return ""
    d = valor - meta
    if abs(d) < 0.5:
        return "na meta ✅"
    pct = f" ({abs(d) / meta * 100:.0f}%)"
    return f"{_fmt(abs(d))} acima da meta{pct}" if d > 0 else f"{_fmt(abs(d))} abaixo da meta ✅"


def linhas_da_oferta(o: Any, desconto_gift: Optional[tuple[float, Any]] = None) -> list[str]:
    """Linhas extras do alerta de um produto que não é TV: a meta e a distância até ela, a entrega do GTA 6 (chega a
    tempo?), o custo efetivo do digital com gift card e, no gift card, quanto o GTA digital sairia."""
    pid = _pid(o)
    p = produto(pid)
    if p is None or p.familia == FAMILIA_TV:
        return []
    out: list[str] = []
    alvo = alvos_da_oferta(o)
    desc = desconto_gift[0] if desconto_gift else None
    valor = preco_comparavel(o, desc)
    if p.digital and desc and valor != _melhor_preco(o):
        out.append(f"💳 Com gift card a {desc * 100:.0f}% de desconto: custo efetivo {_fmt(valor)}")
    elif p.digital and desc and not paga_com_gift_card(o) and p.preco_oficial:
        # chave/código de outra loja: o gift card não paga aqui; para comparar, a PS Store com o gift card
        out.append(f"💳 O gift card PSN só paga na PS Store: lá, com gift card a {desc * 100:.0f}% de desconto, "
                   f"sai por {_fmt(round(p.preco_oficial * (1 - desc), 2))}")
    cc = preco_com_cupom_do_anuncio(o)
    if cc and valor == cc[0]:
        out.append(f"🎟️ Com o cupom {cc[1]} do anúncio: {_fmt(cc[0])}")
    if alvo.pix:
        meta = f"🎯 Meta: Pix {_fmt(alvo.pix)}"
        if alvo.parcelado and abs(alvo.parcelado - alvo.pix) > 0.5:
            meta += f" · parcelado {_fmt(alvo.parcelado)}"
        dist = distancia(valor, alvo.pix)
        out.append(meta + (f" — {dist}" if dist else "") + (f" ({alvo.nota})" if alvo.nota else ""))
    elif alvo.nota:
        out.append(f"🎯 Sem meta: {alvo.nota}")
    assinatura = exige_assinatura(o)
    if assinatura:
        out.append(f"⚠️ preço exclusivo de assinatura ({assinatura}): não vale para você (só Nubank/NuPay)")
    det = detalhes_de(o)
    if det.get("versao_incerta"):
        out.append("ℹ️ versão do PS5 não identificada no título (meta da Digital; confira)")
    if det.get("plataforma_incerta"):
        out.append("ℹ️ plataforma não informada no título (confira se é a de PS5)")
    e = entrega(o)
    if e:
        out.append(e.texto)
    if pid == "GIFT_CARD_PSN":
        face, preco = det.get("valor_face"), _melhor_preco(o)
        if face and preco and preco < face:
            d = 1 - preco / face
            custos = custo_digital_com_gift(d)
            out.append(f"💳 Desconto de {d * 100:.0f}% sobre {_fmt(face)}: GTA 6 digital sairia por "
                       f"{_fmt(custos.get('GTA6_DIGITAL'))} (meta {_fmt(_alvo_base('GTA6_DIGITAL')[0])}), Ultimate "
                       f"{_fmt(custos.get('GTA6_ULTIMATE'))}, upgrade {_fmt(custos.get('GTA6_UPGRADE'))}")
            if not _loja_oficial_gift(o):
                out.append("⚠️ loja não oficial para gift card (a decisão é comprar só na PS Store, Hype, Nuuvem ou "
                           "na loja oficial PlayStation do Mercado Livre)")
    return out


def anota(ofertas: Iterable[Any]) -> None:
    """Grava no extra de cada oferta/postagem que não é TV o que o painel e o resumo usam (texto neutro, sem dado
    pessoal): 'produto' (detalhes da classificação), 'alvo' (meta desta oferta) e, no GTA 6 físico, 'entrega'."""
    for o in ofertas:
        pid = _pid(o)
        if eh_tv(pid) or produto(pid) is None:
            continue
        extra = o.extra if hasattr(o, "extra") else o.setdefault("extra", {})
        det = detalhes_de(o)
        if det and not isinstance(extra.get("produto"), dict):
            extra["produto"] = dict(det)
        a = alvos_da_oferta(o)
        extra["alvo"] = {"pix": a.pix, "parcelado": a.parcelado, "nota": a.nota}
        e = entrega(o)
        if e:
            extra["entrega"] = {"classe": e.classe, "data": e.data, "origem": e.origem,
                                "cep_referencia": e.cep_referencia, "texto": e.texto}


def custo_final_gta(ofertas: Iterable[Any]) -> list[dict]:
    """GTA 6 em todas as formas, pelo custo final (decisão do usuário em 03/10): o Code in Box de cada loja (Pix, com a
    entrega) e o digital pago com o melhor gift card de loja oficial visto. Só ofertas/postagens ativas."""
    ofertas = list(ofertas)
    gift = desconto_gift_card(ofertas)
    linhas: list[dict] = []
    for o in ofertas:
        pid = _pid(o)
        if familia(pid) != FAMILIA_GTA6 or pid == "GTA6_UPGRADE":
            continue   # o upgrade é um complemento (Standard -> Ultimate), não uma forma de ter o jogo
        ativo = o.get("ativo", True) if isinstance(o, dict) else getattr(o, "ativo", True)
        p = _melhor_preco(o)
        if ativo is False or not p or exige_assinatura(o):
            continue   # preço só de assinante (Prime, Meli+...) não é o custo final do usuário (só Nubank/NuPay)
        custo = preco_comparavel(o, gift[0] if gift else None)
        cc = preco_com_cupom_do_anuncio(o)
        e = entrega(o)
        loja = o.get("loja") if isinstance(o, dict) else o.loja
        forma = nome(pid)
        if produto(pid).digital and not paga_com_gift_card(o):
            # chave/código de outra loja: não é a compra na PS Store (o gift card não paga ali)
            forma = f"{forma.replace(' (PS Store)', '')} (código vendido por {loja})"
        linhas.append({
            "produto": pid, "forma": forma, "loja": loja,
            "tipo": (o.get("tipo") if isinstance(o, dict) else o.tipo),
            "url": (o.get("url") if isinstance(o, dict) else o.url), "preco": p, "custo_final": custo,
            "cupom": cc[1] if cc and custo == cc[0] else None,
            "entrega": e.classe if e else ("digital" if produto(pid).digital else None),
            "entrega_texto": e.texto if e else ("libera às 00:00 de 19/11 (digital)" if produto(pid).digital else ""),
            "meta": alvos_da_oferta(o).pix})
    if gift:
        d, og = gift
        for pid, custo in custo_digital_com_gift(d).items():
            if pid == "GTA6_UPGRADE":
                continue
            if not any(l["produto"] == pid and l["custo_final"] <= custo for l in linhas):
                linhas.append({"produto": pid, "forma": nome(pid) + " (preço oficial + gift card)",
                               "loja": "PlayStation Store", "tipo": "calculo",
                               "url": og.get("url") if isinstance(og, dict) else og.url,
                               "preco": produto(pid).preco_oficial, "custo_final": custo, "entrega": "digital",
                               "entrega_texto": f"gift card a {d * 100:.0f}% de desconto", "meta": _alvo_base(pid)[0]})
    # pelo custo final; no empate, a que chega a tempo (ou o digital, que libera à meia-noite) primeiro
    ordem = {"a_tempo": 0, "digital": 0, "desconhecida": 1, "no_dia": 2, "depois": 3}
    linhas.sort(key=lambda l: (l["custo_final"] or 9e9, ordem.get(l["entrega"] or "", 1)))
    return linhas[:30]


def para_painel() -> dict[str, dict]:
    """O catálogo resumido que vai no latest_<modo>.json (o painel não repete nada do catálogo no código dele)."""
    from . import config

    out = {}
    for i, p in PRODUTOS.items():
        out[i] = {"nome": p.nome, "curto": p.curto, "familia": p.familia, "secao": p.secao,
                  "alvo_pix": config.alvo_pix(i), "alvo_parcelado": config.alvo_parcelado(i),
                  "alvo_pix_tardio": p.alvo_pix_tardio, "alvo_parcelado_tardio": p.alvo_parcelado_tardio,
                  "compara_preco": p.compara_preco, "digital": p.digital, "gta_fisico": p.gta_fisico}
    return out
