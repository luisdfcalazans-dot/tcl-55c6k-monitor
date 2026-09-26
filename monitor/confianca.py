"""Confiança nos anúncios da TV: quem é confiável, quem é reprovado e o veredito rápido para o resto.

Pedido do usuário (25/09/2026): verificar a legitimidade de TODOS os anúncios das TVs, em todas as lojas, antes de
alertar — e rápido, porque promoção verdadeira não espera. Nasceu do caso real de 25/09: anúncio da TCL C6K no Magalu
em nome de uma loja que não vende TVs, com homologação Anatel de um celular, "preço cheio" igual ao Pix do próprio
Magalu e 33% de desconto só no Pix/1x, modelo "Vários" e 0 avaliações (padrão de conta de vendedor invadida). O
monitor alertou (abaixo do alvo) e o anúncio virou o "menor já visto" do painel.

Um veredito por oferta de loja:
- "confiavel": vendedor da lista curada (monitor/listas_confianca.json) -> alerta na hora, sem checagem nenhuma;
- "reprovado": lista curada ou reprovado automático (state) -> descartado de cara (só log);
- "suspeito": vendedor desconhecido com sinais fortes -> UMA mensagem "possível golpe"; nunca conta para mínimo,
  histórico, painel ou resumo, e o vendedor vira reprovado automático (as próximas coletas o descartam na hora);
- "sem_risco_aparente": desconhecido que passou nas checagens -> alerta normal + linha "🔎 vendedor novo".

As checagens usam o que a coleta já tem (preços da rodada, ficha técnica, avaliações, dados do vendedor). Só para
vendedor NOVO com preço atraente, e só onde a loja deixa (Magalu), 1-2 requisições: a página da loja do vendedor
(o catálogo dele tem TV?) e o anúncio, quando a coleta não o abriu. O resultado fica no state por dias.

Texto neutro de propósito: o repositório é público e uma empresa listada pode ser vítima (conta invadida), não autora.
Esta é a API única de confiança: motivo_bloqueio(), classifica_por_lista(), avaliar(), veredito_de(),
pode_ir_ao_carrinho().
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, NamedTuple, Optional

from . import config

ARQ_LISTAS = Path(__file__).with_name("listas_confianca.json")

CONFIAVEL = "confiavel"
REPROVADO = "reprovado"
SUSPEITO = "suspeito"
SEM_RISCO = "sem_risco_aparente"
VEREDITOS_FORA = frozenset({SUSPEITO, REPROVADO})

# homologação Anatel da TCL C6K (página do Magalu 1P; o anúncio de 25/09 tinha 09573-24-00953, de um celular)
ANATEL_55C6K = "00738-24-06714"

FRACAO_MUITO_ABAIXO = 0.80   # preço abaixo de 80% da loja confiável mais barata da rodada = sinal forte
DESCONTO_SO_PIX = 0.25       # desconto só no Pix/1x acima disto (lojas reais dão 5-15%)
IGUAL_REAIS = 1.00           # "preço cheio" a até R$ 1 de um preço de loja confiável = copiado
PESO_MINIMO_KG = 3.0         # a 55C6K pesa 11,6 kg (17,2 kg com embalagem): ficha com menos que isso é de mentira
AVALIACOES_REF_MINIMAS = 100  # "0 avaliações" só pesa quando o anúncio da loja confiável tem muitas
VENDAS_MINIMAS = 50
VENDEDOR_NOVO_DIAS = 90
AVALIACOES_VENDEDOR_MINIMAS = 20  # Amazon: avaliações do vendedor

TTL_VEREDITO_DIAS = 3        # veredito "sem_risco_aparente" guardado no state
TTL_CATALOGO_DIAS = 7        # catálogo do vendedor (página da loja dele) guardado no state
TTL_CATALOGO_ERRO_H = 6      # falha ao ler o catálogo: não tenta de novo antes disso
TTL_FICHA_H = 24             # anúncio do Magalu aberto pela checagem: não reabre antes disso
MAX_VENDEDORES_COM_REDE = 2  # vendedores novos com requisição extra por rodada
REFERENCIA_OUTRO_MODO_H = 12  # ofertas confiáveis do outro modo que ainda servem de referência de preço

# lojas em que o anúncio é do vendedor (o id do anúncio identifica o vendedor): no Magalu o /p/<id>/ e no ML o
# item_id. Na Amazon e na Casas Bahia o mesmo ASIN/sku é de todos os vendedores, e o catálogo do ML (MLB48808732) de
# todas as opções: esses nunca podem ir para a lista de reprovados
LOJAS_ANUNCIO_POR_VENDEDOR = {"Magazine Luiza", "Mercado Livre"}

# categorias do Magalu (filtro "Categoria" da página da loja do vendedor)
_CAT_TV = {"ET"}
_CAT_ELETRONICOS = {"ET", "ED", "IN", "TE", "EA", "GA", "CF", "AR"}

_MODELO_GENERICO = re.compile(r"^(?:varios|diversos|outros?|generico|n/?a|nao se aplica|nao informado|-+|\.+)$")
_RE_OUTRO_RAMO = re.compile(
    r"brinqued|cosmetic|perfum|papelari|livrari|confec|vestuari|calcad|roupa|moda\b|farmac|drogari|aliment|"
    r"bebida|\bpet\b|petshop|veterin|joia|bijut|otica|floricult|padari|acougue|restaurant|academia|salao|"
    r"autopec|auto pec|tecido|armarinho|artesanat|festa|papel")


class Sinal(NamedTuple):
    codigo: str
    forte: bool
    texto: str


# ------------------------------------------------------------------------------------------------
# normalização e campos (a oferta pode ser Oferta, registro do state/latest ou linha do histórico)
# ------------------------------------------------------------------------------------------------

def _ascii(s: Any) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(s))


def nome_normalizado(s: Any) -> str:
    """Nome do vendedor comparável: sem acento, caixa, pontuação e o ruído que a página cola no nome
    ("Amazon.com.br Política de devolução", "Vendido por Magalu.", "... A classificação do vendedor é ...")."""
    t = _ascii(s)
    t = re.sub(r"a classificacao do vendedor.*$", "", t)
    t = re.sub(r"politica de devolucao|^\s*vendido por\s+", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def _campo(o: Any, nome: str) -> Any:
    return o.get(nome) if isinstance(o, dict) else getattr(o, nome, None)


def _extra(o: Any) -> dict:
    e = _campo(o, "extra")
    return e if isinstance(e, dict) else {}


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def melhor_preco(o: Any) -> Optional[float]:
    vals = [v for v in (_num(_campo(o, "preco")), _num(_campo(o, "preco_pix"))) if v]
    if vals:
        return min(vals)
    return _num(_campo(o, "melhor_preco"))


def _loja(o: Any) -> str:
    from .util import loja_canonica

    return loja_canonica(str(_campo(o, "loja") or ""))


_RE_VID_URL = re.compile(r"[?&](?:seller_id|smid|idLojista)=([^&#]+)", re.I)
_RE_ANUNCIO_URL = re.compile(r"/p/([0-9a-z]{6,})(?:/|$|\?|#)", re.I)


def vendedor_id(o: Any) -> str:
    """Id do vendedor normalizado: extra.vendedor_id, o parâmetro da URL (seller_id/smid/idLojista) ou, no Magalu, o
    fim do id da oferta ('<grupo>-<vendedor>'). Vazio quando não se sabe."""
    vid = _norm(_extra(o).get("vendedor_id"))
    if vid:
        return vid
    m = _RE_VID_URL.search(str(_campo(o, "url") or ""))
    if m:
        return _norm(m.group(1))
    oid = str(_campo(o, "id") or "")
    if _loja(o) == "Magazine Luiza" and "-" in oid:
        return _norm(oid.rsplit("-", 1)[-1])
    return ""


def anuncios_da_oferta(o: Any) -> set[str]:
    """Ids de anúncio que a oferta carrega (extra.anuncio/item_id, /p/<id>/ da URL, começo do id do Magalu)."""
    ex = _extra(o)
    out = {_norm(ex.get(k)) for k in ("anuncio", "item_id") if ex.get(k)}
    m = _RE_ANUNCIO_URL.search(str(_campo(o, "url") or ""))
    if m:
        out.add(_norm(m.group(1)))
    oid = str(_campo(o, "id") or "")
    if _loja(o) == "Magazine Luiza" and "-" in oid:
        out.add(_norm(oid.split("-", 1)[0]))
    return {a for a in out if a}


def _anuncio_proprio(o: Any) -> str:
    """O anúncio que identifica o VENDEDOR (só nas lojas em que cada vendedor tem o seu): no Magalu o /p/<id>/, no
    ML o item_id (nunca o catálogo, que é de todas as opções)."""
    loja = _loja(o)
    ex = _extra(o)
    if loja == "Magazine Luiza":
        if ex.get("anuncio"):
            return _norm(ex["anuncio"])
        m = _RE_ANUNCIO_URL.search(str(_campo(o, "url") or ""))
        return _norm(m.group(1)) if m else ""
    if loja == "Mercado Livre":
        item = _norm(ex.get("item_id"))
        return item if item and item != _norm(config.ML_CATALOGO_ID) else ""
    return ""


def chave_vendedor(o: Any) -> Optional[str]:
    """'<loja>|<id do vendedor>' (ou nome, ou anúncio): a chave do cache de vereditos e dos reprovados automáticos."""
    loja = _loja(o)
    vid = vendedor_id(o)
    if vid:
        return f"{loja}|{vid}"
    nome = nome_normalizado(_campo(o, "vendedor"))
    if nome:
        return f"{loja}|nome:{nome}"
    anuncio = _anuncio_proprio(o)
    return f"{loja}|anuncio:{anuncio}" if anuncio else None


def veredito_de(o: Any) -> Optional[str]:
    c = _extra(o).get("confianca")
    return c.get("veredito") if isinstance(c, dict) else None


def fora_de_preco(o: Any) -> bool:
    """Suspeito ou reprovado: nunca conta como preço (mínimo, histórico, painel, resumo, alerta de preço)."""
    return veredito_de(o) in VEREDITOS_FORA


# ------------------------------------------------------------------------------------------------
# listas curadas (monitor/listas_confianca.json) e reprovados automáticos (state)
# ------------------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def listas() -> dict:
    try:
        d = json.loads(ARQ_LISTAS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # lista quebrada não pode derrubar a coleta: fica sem lista (e avisa)
        print(f"[confiança] não li {ARQ_LISTAS.name}: {type(e).__name__}: {e}")
        d = {}
    return {"confiaveis": d.get("confiaveis") or {}, "reprovados": d.get("reprovados") or {}}


def recarrega_listas() -> None:
    listas.cache_clear()


def _entradas(tipo: str, loja: str) -> list[dict]:
    return [e for e in (listas()[tipo].get(loja) or []) if isinstance(e, dict)]


def _casa(e: dict, vid: str, nome: str, anuncios: set[str], estrito: bool) -> bool:
    """A entrada é deste vendedor/anúncio?

    estrito (confiáveis): quando a entrada e a oferta têm id do vendedor, só o id decide (nome igual com id diferente
    é outro vendedor). Não estrito (reprovados): qualquer pista basta (id, nome ou anúncio)."""
    ids = {_norm(i) for i in e.get("ids") or [] if _norm(i)}
    nomes = {nome_normalizado(n) for n in e.get("nomes") or [] if nome_normalizado(n)}
    if anuncios & {_norm(a) for a in e.get("anuncios") or [] if _norm(a)}:
        return True
    if estrito:
        if ids and vid:
            return vid in ids
        return bool(nome) and nome in nomes
    return (bool(vid) and vid in ids) or (bool(nome) and nome in nomes)


def _pistas(o: Any) -> tuple[str, str, str, set[str]]:
    return _loja(o), vendedor_id(o), nome_normalizado(_campo(o, "vendedor")), anuncios_da_oferta(o)


def entrada_confiavel(o: Any) -> Optional[dict]:
    loja, vid, nome, _anuncios = _pistas(o)
    for e in _entradas("confiaveis", loja):
        if _casa(e, vid, nome, set(), estrito=True):
            return e
    return None


def _entrada_reprovada(o: Any, auto: Iterable[dict] = ()) -> Optional[dict]:
    loja, vid, nome, anuncios = _pistas(o)
    for e in _entradas("reprovados", loja):
        if _casa(e, vid, nome, anuncios, estrito=False):
            return e
    if entrada_confiavel(o):   # a lista curada vence o reprovado automático
        return None
    for e in auto:
        if isinstance(e, dict) and _loja(e) == loja and _casa(e, vid, nome, anuncios, estrito=False):
            return e
    return None


_cache_auto: dict[str, tuple[tuple, list[dict]]] = {}


def reprovados_auto_dos_arquivos(pasta: Optional[Path] = None) -> list[dict]:
    """Reprovados automáticos gravados nos state_<modo>.json (os dois modos, só leitura; cache por mtime)."""
    pasta = Path(pasta or config.DIR_DADOS)
    out: list[dict] = []
    for modo in ("cloud", "pc"):
        arq = pasta / f"state_{modo}.json"
        try:
            st = arq.stat()
        except OSError:
            continue
        marca = (st.st_mtime_ns, st.st_size)
        guardado = _cache_auto.get(str(arq))
        if guardado and guardado[0] == marca:
            out += guardado[1]
            continue
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
            regs = ((d.get("confianca") or {}).get("reprovados_auto") or {}).values()
            lista = [r for r in regs if isinstance(r, dict)]
        except (OSError, ValueError, AttributeError):
            lista = []
        _cache_auto[str(arq)] = (marca, lista)
        out += lista
    return out


def motivo_bloqueio(o: Any, auto: Optional[Iterable[dict]] = None) -> Optional[str]:
    """Motivo quando a oferta (Oferta, registro do state/latest, linha do histórico ou o 'minimo') é de vendedor ou
    anúncio reprovado (lista curada ou reprovado automático); None se não é.

    auto: reprovados automáticos já carregados (Estado.reprovados_auto); None lê os state_<modo>.json de DIR_DADOS."""
    if auto is None:
        auto = reprovados_auto_dos_arquivos()
    e = _entrada_reprovada(o, auto)
    if e is None:
        return None
    return str(e.get("motivo") or "vendedor reprovado")


def classifica_por_lista(o: Any, auto: Optional[Iterable[dict]] = None) -> tuple[Optional[str], str]:
    """(CONFIAVEL | REPROVADO | None, motivo). Reprovado curado vence tudo; confiável curado vence o automático."""
    motivo = motivo_bloqueio(o, auto)
    if motivo:
        return REPROVADO, motivo
    e = entrada_confiavel(o)
    if e:
        return CONFIAVEL, str(e.get("motivo") or "lista de confiáveis")
    return None, ""


def reprovados_para_painel(auto: Iterable[dict] = ()) -> list[dict]:
    """Lista compacta (nomes já normalizados) para o painel filtrar linhas antigas de latest/histórico."""
    out = []
    for loja, entradas in listas()["reprovados"].items():
        for e in entradas:
            out.append({"loja": loja, "ids": sorted({_norm(i) for i in e.get("ids") or [] if _norm(i)}),
                        "nomes": sorted({nome_normalizado(n) for n in e.get("nomes") or [] if nome_normalizado(n)}),
                        "anuncios": sorted({_norm(a) for a in e.get("anuncios") or [] if _norm(a)})})
    for e in auto:
        if not isinstance(e, dict):
            continue
        out.append({"loja": _loja(e), "ids": sorted({_norm(i) for i in e.get("ids") or [] if _norm(i)}),
                    "nomes": sorted({nome_normalizado(n) for n in e.get("nomes") or [] if nome_normalizado(n)}),
                    "anuncios": sorted({_norm(a) for a in e.get("anuncios") or [] if _norm(a)})})
    return out


# ------------------------------------------------------------------------------------------------
# referências da rodada e sinais de risco
# ------------------------------------------------------------------------------------------------

def _fmt(v: float) -> str:
    from .util import fmt_preco

    return fmt_preco(v)


def _quem(o: Any) -> str:
    vend = str(_campo(o, "vendedor") or "").strip()
    loja = _loja(o)
    return f"{loja}/{vend}" if vend and nome_normalizado(vend) != nome_normalizado(loja) else loja


@dataclass
class Referencias:
    """O que as lojas confiáveis mostram nesta rodada (e na última do outro modo, se recente)."""

    menor: Optional[tuple[float, str]] = None           # (menor preço, quem)
    precos: list[tuple[float, str]] = field(default_factory=list)   # todos os preços (cartão e Pix), com quem
    avaliacoes: dict[str, int] = field(default_factory=dict)        # loja -> mais avaliações num anúncio confiável


def _e_agregador(o: Any) -> bool:
    from .estado import e_agregador

    return e_agregador(o)


def referencias(ofertas: Iterable[Any], extras: Iterable[Any] = ()) -> Referencias:
    ref = Referencias()
    for o in list(ofertas) + list(extras):
        if str(_campo(o, "tipo") or "") != "loja" or _campo(o, "ativo") is False or _e_agregador(o):
            continue
        v = veredito_de(o)
        if v is None:
            v = classifica_por_lista(o, ())[0]
        if v != CONFIAVEL:
            continue
        p = melhor_preco(o)
        if not p:
            continue
        quem = _quem(o)
        if ref.menor is None or p < ref.menor[0]:
            ref.menor = (p, quem)
        for x in (_num(_campo(o, "preco")), _num(_campo(o, "preco_pix"))):
            if x:
                ref.precos.append((x, quem))
        aval = (_extra(o).get("ficha") or {}).get("avaliacoes")
        if isinstance(aval, (int, float)):
            loja = _loja(o)
            ref.avaliacoes[loja] = max(ref.avaliacoes.get(loja, 0), int(aval))
    return ref


def _digitos(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _anatel_fmt(d: str) -> str:
    return f"{d[:5]}-{d[5:7]}-{d[7:]}" if len(d) == 12 else d


def _pct(x: float) -> str:
    return f"{round(x * 100):d}%"


def _data_br(iso: str) -> str:
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)", iso or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else (iso or "")


def _idade_dias(iso: Any) -> Optional[float]:
    from .util import dias_desde

    return dias_desde(str(iso)) if iso else None


_RE_TAMANHO = re.compile(r"(?<!\d)(\d{2})(?!\d)")


def _tamanho_na_ficha(ficha: dict) -> Optional[int]:
    for k in ("tamanho", "polegadas"):
        m = _RE_TAMANHO.search(str(ficha.get(k) or ""))
        if m:
            return int(m.group(1))
    m = re.search(r"(?<!\d)(\d{2})\s*c6k", _ascii(ficha.get("modelo")))
    return int(m.group(1)) if m else None


def sinais_da_oferta(o: Any, ref: Referencias, catalogo: Optional[dict] = None) -> tuple[list[Sinal], list[str]]:
    """(sinais de risco, checagens feitas) de uma oferta de vendedor desconhecido. Só usa dado já em mãos."""
    s: list[Sinal] = []
    feitas: list[str] = []
    ex = _extra(o)
    ficha = ex.get("ficha") if isinstance(ex.get("ficha"), dict) else {}
    melhor = melhor_preco(o)
    cartao = _num(_campo(o, "preco"))

    # 1) preço: muito abaixo da loja confiável mais barata; "preço cheio" copiado com desconto enorme só no Pix/1x
    if melhor and ref.menor:
        feitas.append("preço")
        r = melhor / ref.menor[0]
        if r < FRACAO_MUITO_ABAIXO:
            s.append(Sinal("preco_muito_abaixo", True,
                           f"preço {_fmt(melhor)} é {_pct(1 - r)} menor que o da loja confiável mais barata "
                           f"({_fmt(ref.menor[0])}, {ref.menor[1]})"))
    if melhor:
        cheios = sorted({v for v in (cartao, _num(ex.get("preco_de"))) if v and v > melhor + 0.5})
        copiado = None
        for c in cheios:
            desc = 1 - melhor / c
            if desc <= DESCONTO_SO_PIX:
                continue
            igual = next((q for v, q in ref.precos if abs(v - c) <= IGUAL_REAIS), None)
            if igual:
                copiado = (c, desc, igual)
                break
        if copiado:
            s.append(Sinal("preco_cheio_copiado", True,
                           f"“preço cheio” {_fmt(copiado[0])} igual ao de {copiado[2]}, com {_pct(copiado[1])} de "
                           f"desconto só no Pix/1x"))
        elif cartao and cartao > melhor and 1 - melhor / cartao > DESCONTO_SO_PIX:
            s.append(Sinal("desconto_so_no_pix", False, f"desconto de {_pct(1 - melhor / cartao)} só no Pix/1x"))

    # 2) ficha técnica do anúncio
    anatel = _digitos(ficha.get("anatel"))
    if anatel:
        feitas.append("Anatel")
        if len(anatel) >= 8 and anatel != _digitos(ANATEL_55C6K):
            s.append(Sinal("anatel_diferente", True,
                           f"certificado Anatel {_anatel_fmt(anatel)} não é o da 55C6K ({ANATEL_55C6K})"))
    modelo = str(ficha.get("modelo") or "").strip()
    if modelo:
        feitas.append("modelo")
        m = _ascii(modelo).strip()
        if _MODELO_GENERICO.match(m) or "c6k" not in _norm(m):
            s.append(Sinal("modelo_generico", False, f"modelo na ficha: '{modelo[:40]}'"))
    tam = _tamanho_na_ficha(ficha)
    if tam is not None:
        feitas.append("tamanho")
        if tam != 55:
            s.append(Sinal("tamanho_diferente", True, f"título diz 55\", mas a ficha/seleção do anúncio diz {tam}\""))
    peso = ficha.get("peso_kg")
    if isinstance(peso, (int, float)) and peso > 0:
        feitas.append("peso")
        if peso < PESO_MINIMO_KG:
            s.append(Sinal("peso_irreal", False, f"peso na ficha {str(peso).replace('.', ',')} kg (a TV tem ~12 kg)"))
    aval = ficha.get("avaliacoes")
    if isinstance(aval, (int, float)):
        feitas.append("avaliações")
        ref_aval = ref.avaliacoes.get(_loja(o), 0)
        if aval == 0 and ref_aval >= AVALIACOES_REF_MINIMAS:
            s.append(Sinal("sem_avaliacoes", False,
                           f"anúncio sem avaliações (o da loja confiável tem {ref_aval:,})".replace(",", ".")))
    if ficha.get("full") is False:
        feitas.append("Full")
        s.append(Sinal("sem_full", False, "não é enviado pela loja (sem Full)"))
    elif ficha.get("full") is True:
        feitas.append("Full")

    # 3) vendedor
    razao = str(ficha.get("razao_social") or "").strip()
    if razao:
        feitas.append("razão social")
        if _RE_OUTRO_RAMO.search(_ascii(razao)):
            s.append(Sinal("razao_social_de_outro_ramo", False, f"razão social de outro ramo ('{razao[:60]}')"))
    desde = ficha.get("vendedor_desde")
    idade = _idade_dias(desde)
    if idade is not None:
        feitas.append("idade da conta")
        if idade < VENDEDOR_NOVO_DIAS:
            s.append(Sinal("vendedor_recente", False, f"vendedor na loja só desde {_data_br(str(desde))}"))
    vendas = ficha.get("vendas_vendedor", ex.get("vendas_vendedor"))
    if isinstance(vendas, (int, float)):
        feitas.append("vendas")
        if vendas < VENDAS_MINIMAS:
            s.append(Sinal("poucas_vendas", False, f"vendedor com {int(vendas)} vendas"))
    aval_v = ficha.get("avaliacoes_vendedor")
    if isinstance(aval_v, (int, float)):
        feitas.append("avaliações do vendedor")
        if aval_v < AVALIACOES_VENDEDOR_MINIMAS:
            s.append(Sinal("vendedor_sem_historico", False, f"vendedor com {int(aval_v)} avaliações"))

    # 4) catálogo do vendedor (página da loja dele; só com checagem de rede)
    if catalogo and catalogo.get("total"):
        feitas.append("catálogo da loja")
        total, tv, eletro = int(catalogo["total"]), int(catalogo.get("tv") or 0), int(catalogo.get("eletronicos") or 0)
        if total >= 30 and tv / total < 0.02 and eletro / total < 0.10:
            principais = ", ".join((catalogo.get("principais") or [])[:3])
            s.append(Sinal("catalogo_sem_tv", True,
                           f"a loja do vendedor tem {total:,} itens e só {tv} de TV ({tv / total * 100:.1f}%)".replace(",", ".")
                           + (f"; vende sobretudo {principais}" if principais else "")))
    return s, feitas


def decide(sinais: list[Sinal]) -> str:
    """Suspeito: 2 sinais fortes, ou 1 forte com pelo menos 2 fracos. O resto passa (com os sinais anotados)."""
    fortes = sum(1 for x in sinais if x.forte)
    pontos = sum(2 if x.forte else 1 for x in sinais)
    return SUSPEITO if fortes >= 2 or (fortes >= 1 and pontos >= 4) else SEM_RISCO


# ------------------------------------------------------------------------------------------------
# checagens de rede (só vendedor novo com preço atraente; guardadas no state)
# ------------------------------------------------------------------------------------------------

class _Bloqueio(Exception):
    """A loja respondeu 403/429: nenhuma outra requisição de checagem nesta rodada."""


def _obter_padrao(url: str) -> str:
    import requests

    from .util import get_html

    try:
        return get_html(url, tentativas=1, timeout=20)
    except requests.HTTPError as e:
        st = e.response.status_code if e.response is not None else None
        if st in (403, 429):
            raise _Bloqueio(str(st)) from e
        raise


def resumo_catalogo_magalu(html: str) -> Optional[dict]:
    """Página da loja do vendedor no magazinevoce: total de itens e quantos são TV / eletrônicos (filtro Categoria)."""
    from .util import next_data

    nd = next_data(html) or {}
    s = ((((nd.get("props") or {}).get("pageProps") or {}).get("data") or {}).get("search") or {})
    if not isinstance(s, dict):
        return None
    try:
        total = int((s.get("pagination") or {}).get("records") or 0)
    except (TypeError, ValueError):
        total = 0
    cats: list[tuple[int, str, str]] = []
    for f in s.get("filters") or []:
        if isinstance(f, dict) and f.get("slug") == "category":
            for v in f.get("values") or []:
                if isinstance(v, dict) and v.get("id"):
                    try:
                        cats.append((int(v.get("count") or 0), str(v["id"]), str(v.get("label") or v["id"])))
                    except (TypeError, ValueError):
                        continue
    if not total and not cats:
        return None
    total = total or sum(c for c, _i, _l in cats)
    cats.sort(reverse=True)
    return {"total": total, "tv": sum(c for c, i, _l in cats if i in _CAT_TV),
            "eletronicos": sum(c for c, i, _l in cats if i in _CAT_ELETRONICOS),
            "principais": [lbl for _c, _i, lbl in cats[:4]]}


def _catalogo_magalu(vid: str, obter: Callable[[str], str]) -> Optional[dict]:
    from .sources.magalu import BASE_MV

    return resumo_catalogo_magalu(obter(f"{BASE_MV}/lojista/{vid}/"))


def _ficha_magalu(o: Any, vid: str, obter: Callable[[str], str]) -> Optional[dict]:
    """Abre o anúncio (com ?seller_id) quando a coleta não abriu: a ficha do vendedor desta oferta."""
    from .sources.magalu import _url_mv, com_vendedor, parse_produto

    det, _c = parse_produto(obter(_url_mv(com_vendedor(str(_campo(o, "url") or ""), vid))))
    if det is not None and _norm(det.extra.get("vendedor_id")) == vid:
        return det.extra.get("ficha") or None
    return None


# loja -> (lê o catálogo do vendedor, completa a ficha do anúncio). A Amazon responde 503 a HTTP na página do vendedor
# e o ML exige conta: nelas a checagem fica com o que a coleta já traz (avaliações/vendas do vendedor).
CHECAGENS_DE_REDE: dict[str, tuple[Callable, Callable]] = {"Magazine Luiza": (_catalogo_magalu, _ficha_magalu)}


# ------------------------------------------------------------------------------------------------
# a rodada: descartar reprovados, dar veredito a cada oferta, guardar no state
# ------------------------------------------------------------------------------------------------

def bloco_do_estado(estado: Any) -> dict:
    b = estado.dados.setdefault("confianca", {})
    for k in ("vendedores", "catalogos", "reprovados_auto", "fichas"):
        if not isinstance(b.get(k), dict):
            b[k] = {}
    return b


def _blocos_de_outros_modos(estado: Any) -> list[dict]:
    out = []
    for m in getattr(estado, "_outros_modos", lambda: [])():
        d = estado._arquivo_do_modo(f"state_{m}.json") or {}
        b = d.get("confianca")
        if isinstance(b, dict):
            out.append(b)
    return out


def reprovados_auto_do_estado(estado: Any) -> list[dict]:
    """Reprovados automáticos deste modo (em memória, inclusive os desta rodada) e do outro (state, só leitura)."""
    regs = list(bloco_do_estado(estado)["reprovados_auto"].values())
    for b in _blocos_de_outros_modos(estado):
        r = b.get("reprovados_auto")
        regs += list(r.values()) if isinstance(r, dict) else []
    return [r for r in regs if isinstance(r, dict)]


def _do_cache(estado: Any, secao: str, chave: str) -> Optional[dict]:
    regs = [bloco_do_estado(estado)[secao].get(chave)]
    regs += [(b.get(secao) or {}).get(chave) for b in _blocos_de_outros_modos(estado) if isinstance(b.get(secao), dict)]
    validos = [r for r in regs if isinstance(r, dict) and r.get("quando")]
    return max(validos, key=lambda r: r["quando"]) if validos else None


def _catalogo_em_cache(estado: Any, chave: str) -> Optional[dict]:
    r = _do_cache(estado, "catalogos", chave)
    if not r:
        return None
    idade = _idade_dias(r.get("quando"))
    if idade is None:
        return None
    if r.get("erro"):
        return r if idade * 24 < TTL_CATALOGO_ERRO_H else None
    return r if idade < TTL_CATALOGO_DIAS else None


def descarta_reprovados(estado: Any, ofertas: list) -> list:
    """Tira da rodada oferta (de loja ou postagem com link do anúncio) de vendedor/anúncio reprovado. Só log."""
    auto = reprovados_auto_do_estado(estado)
    liberadas = []
    for o in ofertas:
        motivo = motivo_bloqueio(o, auto)
        if motivo:
            print(f"[confiança] descartado {o.loja}/{o.vendedor or '?'} ({o.id}): {motivo[:160]}")
        else:
            liberadas.append(o)
    return liberadas


def _extras_de_referencia(estado: Any) -> list[dict]:
    """Ofertas confiáveis da última rodada do outro modo, se recente (referência de preço entre modos)."""
    out = []
    try:
        outras = estado.ofertas_diretas_de_outros_modos()
    except Exception:  # noqa: BLE001 - referência extra; sem ela fica só a rodada
        return []
    for d in outras:
        idade = _idade_dias(d.get("_visto"))
        if idade is not None and idade * 24 <= REFERENCIA_OUTRO_MODO_H:
            out.append(d)
    return out


def _atraente(o: Any, ref: Referencias, sinais: list[Sinal]) -> bool:
    p = melhor_preco(o)
    if not p:
        return False
    if ref.menor is None or p <= ref.menor[0] or p <= config.ALVO_PARCELADO:
        return True
    return any(x.forte for x in sinais)


def avaliar(estado: Any, ofertas: list, rede: bool = True, obter: Optional[Callable[[str], str]] = None,
            pausa_s: Optional[float] = None) -> dict:
    """Dá o veredito de cada oferta de loja (extra['confianca']) e guarda o que precisa no state.

    Confiável (lista) não passa por checagem nenhuma. Desconhecido: sinais com o que a coleta já tem; com `rede`,
    até MAX_VENDEDORES_COM_REDE vendedores novos de preço atraente ganham 1-2 requisições (o anúncio, se a coleta não
    o abriu, e o catálogo do vendedor), com a pausa da coleta entre elas e guardadas no state. Suspeito vira reprovado
    automático. Devolve {veredito: quantidade}."""
    obter_base = obter or _obter_padrao
    espera = config.MAGALU_PAUSA_S if pausa_s is None else pausa_s
    pedidos = [0]

    def pedir(url: str) -> str:
        if pedidos[0] and espera > 0:
            time.sleep(espera)
        pedidos[0] += 1
        return obter_base(url)

    bloco = bloco_do_estado(estado)
    auto = reprovados_auto_do_estado(estado)
    from .util import agora_iso

    agora = agora_iso()
    contagem: dict[str, int] = {}
    desconhecidas = []
    for o in ofertas:
        if o.tipo != "loja" or _e_agregador(o):
            continue
        v, _motivo = classifica_por_lista(o, auto)
        if v == CONFIAVEL:
            o.extra["confianca"] = {"veredito": CONFIAVEL}
            contagem[CONFIAVEL] = contagem.get(CONFIAVEL, 0) + 1
        elif v == REPROVADO:  # descarta_reprovados já tirou; se chegou aqui, fica fora de tudo
            o.extra["confianca"] = {"veredito": REPROVADO}
            contagem[REPROVADO] = contagem.get(REPROVADO, 0) + 1
        elif o.ativo and melhor_preco(o):  # esgotada/sem preço não alerta nem conta: nada a checar
            desconhecidas.append(o)
    if not desconhecidas:
        return contagem

    ref = referencias(ofertas, _extras_de_referencia(estado))
    usadas = 0
    bloqueado = False
    for o in sorted(desconhecidas, key=lambda x: melhor_preco(x) or 9e9):
        chave = chave_vendedor(o)
        loja = _loja(o)
        vid = vendedor_id(o)
        cat = _catalogo_em_cache(estado, chave) if chave else None
        sinais, feitas = sinais_da_oferta(o, ref, cat if cat and not cat.get("erro") else None)
        veredito = decide(sinais)
        checagem = CHECAGENS_DE_REDE.get(loja)
        if rede and checagem and vid and not bloqueado and veredito != SUSPEITO and usadas < MAX_VENDEDORES_COM_REDE \
                and _atraente(o, ref, sinais):
            ler_catalogo, ler_ficha = checagem
            gastou = False
            ficha = o.extra.get("ficha") if isinstance(o.extra.get("ficha"), dict) else {}
            anuncio = _anuncio_proprio(o) or chave
            ja_abriu = _do_cache(estado, "fichas", f"{chave}|{anuncio}")
            idade_ficha = _idade_dias(ja_abriu.get("quando")) if ja_abriu else None
            aberto_ha_pouco = idade_ficha is not None and idade_ficha * 24 < TTL_FICHA_H
            if "anatel" not in ficha and "avaliacoes" not in ficha and not aberto_ha_pouco:
                gastou = True
                try:
                    nova = ler_ficha(o, vid, pedir)
                    if nova:
                        o.extra["ficha"] = {**ficha, **nova}
                    bloco["fichas"][f"{chave}|{anuncio}"] = {"quando": agora, "ok": bool(nova)}
                except _Bloqueio:
                    bloqueado = True
                except Exception as e:  # noqa: BLE001 - checagem extra: falha não derruba a rodada
                    print(f"[confiança] não abri o anúncio de {_quem(o)}: {type(e).__name__}: {str(e)[:100]}")
            if cat is None and not bloqueado:
                gastou = True
                try:
                    lido = ler_catalogo(vid, pedir)
                    cat = {"quando": agora, **(lido or {"erro": "página da loja sem catálogo legível"})}
                except _Bloqueio:
                    bloqueado = True
                except Exception as e:  # noqa: BLE001
                    cat = {"quando": agora, "erro": f"{type(e).__name__}: {str(e)[:120]}"}
                if cat is not None and chave:
                    bloco["catalogos"][chave] = cat
            if bloqueado:
                print("[confiança] a loja bloqueou (403/429): sem mais checagens de rede nesta rodada")
            if gastou:
                usadas += 1
                sinais, feitas = sinais_da_oferta(o, ref, cat if cat and not cat.get("erro") else None)
                veredito = decide(sinais)
        info = {"veredito": veredito, "checagens": feitas, "sinais": [x.texto for x in sinais]}
        if cat and not cat.get("erro"):
            info["catalogo"] = {k: cat.get(k) for k in ("total", "tv")}
        o.extra["confianca"] = info
        contagem[veredito] = contagem.get(veredito, 0) + 1
        print(f"[confiança] {veredito}: {_quem(o)} ({o.id}) {_fmt(melhor_preco(o) or 0)}"
              + (f" — {'; '.join(info['sinais'])[:300]}" if info["sinais"] else "")
              + (f" [checagens: {', '.join(feitas)}]" if feitas else ""))
        if chave:
            reg = {"loja": loja, "vendedor": o.vendedor, "vendedor_id": vid or None, "veredito": veredito,
                   "sinais": info["sinais"], "quando": agora, "chave_oferta": o.chave, "preco": melhor_preco(o)}
            antes = bloco["vendedores"].get(chave)
            reg["primeira_vez"] = (antes or {}).get("primeira_vez") or agora
            bloco["vendedores"][chave] = reg
        if veredito == SUSPEITO:
            _reprova_automatico(bloco, o, info["sinais"], agora)
    # veredito "sem risco" velho sai do cache (o vendedor volta a ser checado do zero)
    for k in [k for k, r in bloco["vendedores"].items()
              if not isinstance(r, dict) or (_idade_dias(r.get("quando")) or 0) > TTL_VEREDITO_DIAS]:
        del bloco["vendedores"][k]
    for secao, ttl in (("catalogos", TTL_CATALOGO_DIAS), ("fichas", 1.0)):
        for k in [k for k, r in bloco[secao].items()
                  if not isinstance(r, dict) or (_idade_dias(r.get("quando")) or 0) > ttl]:
            del bloco[secao][k]
    return contagem


def _reprova_automatico(bloco: dict, o: Any, sinais: list[str], quando: str) -> None:
    """Suspeito vira reprovado automático (as próximas coletas o descartam de cara)."""
    chave = chave_vendedor(o)
    if not chave:
        return  # sem id, nome nem anúncio próprio (ex.: 'destaque' da busca da Amazon): nada que identifique
    vid = vendedor_id(o)
    anuncio = _anuncio_proprio(o)
    bloco["reprovados_auto"][chave] = {
        "loja": _loja(o), "ids": [vid] if vid else [], "nomes": [o.vendedor] if o.vendedor else [],
        "anuncios": [anuncio] if anuncio else [],
        "motivo": f"anúncio da TV com sinais de risco em {_data_br(quando)}: " + "; ".join(sinais),
        "desde": quando, "origem": "automatico", "chave_oferta": o.chave, "preco": melhor_preco(o),
    }


# ------------------------------------------------------------------------------------------------
# textos das mensagens e o carrinho
# ------------------------------------------------------------------------------------------------

def linha_vendedor_novo(o: Any) -> Optional[str]:
    """Linha extra do alerta de vendedor desconhecido que passou nas checagens (texto puro, sem HTML)."""
    c = _extra(o).get("confianca")
    if not isinstance(c, dict) or c.get("veredito") != SEM_RISCO:
        return None
    feitas = c.get("checagens") or []
    quem = "vendedor novo" if _campo(o, "vendedor") else "vendedor não identificado"
    linha = f"🔎 {quem}: " + (f"checagens ok ({', '.join(feitas)})" if feitas else "sem dados para checar")
    if c.get("sinais"):
        linha += " · atenção: " + "; ".join(c["sinais"])
    return linha


def sinais_de(o: Any) -> list[str]:
    c = _extra(o).get("confianca")
    return list(c.get("sinais") or []) if isinstance(c, dict) else []


def pode_ir_ao_carrinho(o: Any, todas: Iterable[Any] = (), auto: Optional[Iterable[dict]] = None) -> tuple[bool, str]:
    """Só anúncio confiável ou sem risco aparente vai ao carrinho; suspeito/reprovado nunca.

    Registro sem veredito (gravado antes desta checagem existir): a lista decide e, para desconhecido, os sinais com o
    que o registro traz, tendo `todas` (as ofertas dos latest) como referência de preço."""
    motivo = motivo_bloqueio(o, auto)
    if motivo:
        return False, motivo
    v = veredito_de(o)
    if v in VEREDITOS_FORA:
        return False, "anúncio " + v + ((": " + "; ".join(sinais_de(o))) if sinais_de(o) else "")
    if v in (CONFIAVEL, SEM_RISCO):
        return True, v
    if entrada_confiavel(o):
        return True, CONFIAVEL
    if _e_agregador(o):
        return True, "agregador"
    sinais, _feitas = sinais_da_oferta(o, referencias(todas))
    if decide(sinais) == SUSPEITO:
        return False, "anúncio suspeito: " + "; ".join(x.texto for x in sinais)
    return True, SEM_RISCO


