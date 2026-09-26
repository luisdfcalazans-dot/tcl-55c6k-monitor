"""Confiança nos anúncios da TV: quem é confiável, quem é reprovado e o veredito rápido para o resto.

Pedido do usuário (25/09/2026): verificar a legitimidade de TODOS os anúncios das TVs, em todas as lojas, antes de
alertar — e rápido, porque promoção verdadeira não espera. Nasceu do caso real de 25/09: anúncio da TCL C6K no Magalu
em nome de uma loja que não vende TVs, com homologação Anatel de um celular, "preço cheio" igual ao Pix do próprio
Magalu e 33% de desconto só no Pix/1x, modelo "Vários" e 0 avaliações (padrão de conta de vendedor invadida). O
monitor alertou (abaixo do alvo) e o anúncio virou o "menor já visto" do painel.

Um veredito por oferta de loja:
- "confiavel": vendedor da lista curada (monitor/listas_confianca.json) -> alerta na hora, sem checagem nenhuma;
- "reprovado": lista curada ou reprovado automático (state) -> descartado de cara (só log);
- "suspeito": vendedor não confiável com QUALQUER sinal forte (preço até 80% da loja confiável mais barata já basta)
  ou muitos sinais fracos -> uma mensagem "possível golpe" (repetida só se o preço cair mais); nunca conta para
  mínimo, histórico, painel, resumo ou carrinho. Só vira reprovado automático (descartado de cara nas próximas
  coletas) com 2+ sinais fortes, um deles de identidade (Anatel/tamanho errados, loja sem TV no catálogo): preço baixo
  sozinho é reavaliado a cada rodada e o vendedor pode ser liberado pela lista de confiáveis;
- "sem_risco_aparente": desconhecido que passou nas checagens -> alerta normal + linha "🔎 vendedor novo".
Linha de agregador (Zoom) de loja sem fonte direta também passa pela checagem de preço (não há vendedor a checar).
Vendedor novo do Magalu que ficou sem a ficha (403, limite da rodada, anúncio que não abriu) ou sem o catálogo (403,
limite da rodada) e está abaixo da loja confiável mais barata também é suspeito nesta rodada ("não deu para checar"),
sem virar reprovado. Falha passageira na página da loja (timeout, 5xx, 404, ilegível) não conta: é "checagem da loja
pendente", tentada de novo na rodada seguinte (TTL_FALHA_MIN), como a do anúncio. A ficha lida (coleta ou checagem)
fica no state e vale nas rodadas em que a coleta só traz a busca. O cupom da página de um anúncio barrado não vai a
alerta, painel nem testador (cupom_barrado), e a postagem que leva a ele (ou cita o vendedor) não ganha 🎯
(postagem_barrada).

As checagens usam o que a coleta já tem (preços da rodada, ficha técnica, avaliações, dados do vendedor). Só para
vendedor NOVO com preço atraente, e só onde a loja deixa (Magalu), 1-2 requisições: a página da loja do vendedor
(o catálogo dele tem TV?) e o anúncio, quando a coleta não o abriu. O resultado fica no state por dias.

Texto neutro de propósito: o repositório é público e uma empresa listada pode ser vítima (conta invadida), não autora.
Esta é a API única de confiança: motivo_bloqueio(), classifica_por_lista(), avaliar(), veredito_de(),
pode_ir_ao_carrinho(), cupom_barrado(), postagem_barrada(). Com o listas_confianca.json ilegível valem as entradas de
RESERVA_LISTAS e o run.py avisa no Telegram (aviso_de_lista_quebrada).
"""

from __future__ import annotations

import copy
import html
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

FRACAO_MUITO_ABAIXO = 0.80   # preço até 80% da loja confiável mais barata da rodada = sinal forte (sozinho: suspeito)
DESCONTO_SO_PIX = 0.25       # desconto só no Pix/1x acima disto, sem "preço cheio" copiado: sinal fraco
# com o "preço cheio" (cartão) igual ao de uma loja confiável, desconto só no Pix/1x acima disto já é sinal forte
# (revisão 3 de 26/09). Lojas reais dão 5-12% no Pix (Magalu 5%, Webcontinental ~7%, Amazon 8-10%, Colombo 10%)
DESCONTO_SO_PIX_COPIADO = 0.15
IGUAL_REAIS = 1.00           # "preço cheio" a até R$ 1 de um preço de loja confiável = copiado
PESO_MINIMO_KG = 3.0         # a 55C6K pesa 11,6 kg (17,2 kg com embalagem): ficha com menos que isso é de mentira
AVALIACOES_REF_MINIMAS = 100  # "0 avaliações" só pesa quando o anúncio da loja confiável tem muitas
VENDAS_MINIMAS = 50
VENDEDOR_NOVO_DIAS = 90
AVALIACOES_VENDEDOR_MINIMAS = 20  # Amazon: avaliações do vendedor

TTL_VEREDITO_DIAS = 3        # veredito "sem_risco_aparente" guardado no state
TTL_CATALOGO_DIAS = 7        # catálogo do vendedor (página da loja dele) guardado no state
# falha passageira (timeout, 5xx, 404, página ilegível) ao ler o catálogo do vendedor ou abrir o anúncio: nova
# tentativa depois disto. Menos que os 15 min entre as rodadas da nuvem, para a tentativa ser a da rodada seguinte, e
# o bastante para uma execução repetida logo em seguida não insistir (revisão 3 de 26/09: eram 6 h no catálogo e 24 h no
# anúncio, e o vendedor limpo ficava como "possível golpe" esse tempo todo)
TTL_FALHA_MIN = 10
TTL_FICHA_H = 24             # anúncio do Magalu aberto (e lido) pela checagem: não reabre antes disso
TTL_FICHA_DIAS = 7           # ficha lida (coleta ou checagem) que ainda vale quando a coleta vem sem ela (só a busca)
AVISO_LISTA_QUEBRADA_H = 6   # o aviso de listas_confianca.json quebrado se repete no máximo a cada tanto
MAX_VENDEDORES_COM_REDE = 2  # vendedores novos com requisição extra por rodada
REFERENCIA_OUTRO_MODO_H = 12  # ofertas confiáveis do outro modo que ainda servem de referência de preço
FRACOS_PARA_SUSPEITO = 4     # sem sinal forte, só muitos sinais fracos juntos tornam o anúncio suspeito
QUEDA_NOVO_AVISO = 0.02      # o aviso de suspeito só se repete quando o preço cai isto desde o último aviso
TTL_AVISO_DIAS = 7           # aviso de suspeito que não aparece mais há tanto tempo sai do state
MAX_TVS_DO_INVASOR = 5       # anúncios de TV que um invasor cria na conta não fazem dela uma loja de TV
MIN_TVS_LOJA_DE_TV = 30      # loja com tantos anúncios de TV vende TV (o sinal de catálogo nunca dispara)

# sinais fortes de IDENTIDADE (o anúncio/vendedor não é o que diz ser): só com um deles, e mais outro forte, o suspeito
# vira reprovado automático. Preço (muito abaixo, "preço cheio" copiado) sozinho nunca reprova de vez.
SINAIS_DE_IDENTIDADE = frozenset({"anatel_diferente", "tamanho_diferente", "catalogo_sem_tv"})
# sinal forte que segura o preço nesta rodada mas não é prova de nada: nunca conta para o reprovado automático
SINAIS_SEM_PROVA = frozenset({"nao_checado"})

# campos da ficha do anúncio guardados no state (confianca.fichas) para as rodadas em que a coleta vem sem ficha. A
# razão social fica de fora: o state é público e ela só serve ao sinal fraco de "outro ramo"
CAMPOS_FICHA = ("anatel", "modelo", "tamanho", "peso_kg", "avaliacoes", "full", "vendedor_desde", "vendas_vendedor",
                "avaliacoes_vendedor", "nota_vendedor")

# lojas em que Oferta.preco pode ser o preço "de" (riscado) e não o do cartão desta oferta: no ML, a opção com desconto
# guarda o original em .preco. Nelas não há como saber se o desconto é "só no Pix/1x".
LOJAS_PRECO_PODE_SER_RISCADO = {"Mercado Livre"}

# lojas em que o anúncio é do vendedor (o id do anúncio identifica o vendedor): no Magalu o /p/<id>/ e no ML o
# item_id. Na Amazon e na Casas Bahia o mesmo ASIN/sku é de todos os vendedores, e o catálogo do ML (MLB48808732) de
# todas as opções: esses nunca podem ir para a lista de reprovados
LOJAS_ANUNCIO_POR_VENDEDOR = {"Magazine Luiza", "Mercado Livre"}

# categorias do Magalu (filtro "Categoria" da página da loja do vendedor). "Eletro de TV" é a linha de quem vende TV
# (TV e Vídeo, Eletrodomésticos, Eletroportáteis, Ar e Ventilação, Áudio); celular, informática, games e câmeras não
# contam: loja de capinha/cabo não vira loja de TV (revisão de 26/09)
_CAT_TV = {"ET"}
_CAT_ELETRONICOS = {"ET", "ED", "EP", "AR", "EA"}

_MODELO_GENERICO = re.compile(r"^(?:varios|diversos|outros?|generico|n/?a|nao se aplica|nao informado|-+|\.+)$")
# só no começo da palavra: "otica" não casa com "Robotica", nem "festa" com "Manifesta"
_RE_OUTRO_RAMO = re.compile(
    r"\b(?:brinqued|cosmetic|perfum|papelari|livrari|confec|vestuari|calcad|roupa|moda\b|farmac|drogari|aliment|"
    r"bebida|pet\b|petshop|veterin|joia|bijut|otica|floricult|padari|acougue|restaurant|academia|salao|"
    r"autopec|auto pec|tecido|armarinho|artesanat|festa|papel)")


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
    """O anúncio que é SÓ deste vendedor, ou vazio. Nunca o anúncio do buy box de outro vendedor (revisão de 26/09: o
    vendedor da lista product.offers do Magalu vem com o /p/<id>/ do anúncio do Magalu 1P; reprovar esse id bloquearia
    o 1P e todo vendedor limpo do mesmo anúncio).
    - Magalu: o /p/<id>/ quando a coleta viu que a lista de vendedores do anúncio só tem ele (extra.anuncio_exclusivo);
    - ML: o item_id quando a coleta o ligou a este vendedor (vendedor_id só vem quando o item é dele), nunca o catálogo.
    Amazon/Casas Bahia: o ASIN/sku é de todos os vendedores."""
    loja = _loja(o)
    ex = _extra(o)
    if loja == "Magazine Luiza":
        return _norm(ex.get("anuncio")) if ex.get("anuncio_exclusivo") and vendedor_id(o) else ""
    if loja == "Mercado Livre":
        item = _norm(ex.get("item_id"))
        return item if item and item != _norm(config.ML_CATALOGO_ID) and _norm(ex.get("vendedor_id")) else ""
    return ""


def chave_vendedor(o: Any) -> Optional[str]:
    """'<loja>|<id do vendedor>' (ou '<loja>|nome:<nome>'): a chave do cache de vereditos e dos reprovados automáticos.
    None quando a oferta não diz quem vende (o anúncio sozinho não identifica o vendedor)."""
    loja = _loja(o)
    vid = vendedor_id(o)
    if vid:
        return f"{loja}|{vid}"
    nome = nome_normalizado(_campo(o, "vendedor"))
    return f"{loja}|nome:{nome}" if nome else None


def chave_aviso(o: Any) -> str:
    """Chave do aviso de suspeito no state: o vendedor ou, sem ele, a própria oferta."""
    return chave_vendedor(o) or f"{_loja(o)}|oferta:{_campo(o, 'chave') or _campo(o, 'id') or _campo(o, 'url')}"


def veredito_de(o: Any) -> Optional[str]:
    c = _extra(o).get("confianca")
    return c.get("veredito") if isinstance(c, dict) else None


def fora_de_preco(o: Any) -> bool:
    """Suspeito ou reprovado: nunca conta como preço (mínimo, histórico, painel, resumo, alerta de preço)."""
    return veredito_de(o) in VEREDITOS_FORA


def identidade_em_duvida(o: Any) -> bool:
    """Reprovado, ou suspeito por sinal de IDENTIDADE (Anatel/tamanho de outro produto, loja sem TV): o anúncio não é
    o que diz ser, então nem os preços que ele mostrou antes valem. Suspeito só pelo preço de agora, não."""
    c = _extra(o).get("confianca")
    if not isinstance(c, dict):
        return False
    return c.get("veredito") == REPROVADO or (c.get("veredito") == SUSPEITO
                                              and bool(set(c.get("codigos") or []) & SINAIS_DE_IDENTIDADE))


# ------------------------------------------------------------------------------------------------
# listas curadas (monitor/listas_confianca.json) e reprovados automáticos (state)
# ------------------------------------------------------------------------------------------------

# Reserva no código (revisão de 26/09): o listas_confianca.json é editado à mão; com um erro de sintaxe, as duas listas
# sumiriam e o bloqueio curado junto. Com o arquivo ilegível valem estas entradas (cópia de entradas do arquivo, o que
# tests/test_confianca.py confere) e o monitor avisa no Telegram (aviso_de_lista_quebrada).
RESERVA_LISTAS: dict = {
    "confiaveis": {
        "Magazine Luiza": [{"ids": ["magazineluiza"], "nomes": ["Magalu", "Magazine Luiza"],
                            "motivo": "a própria loja (reserva do código)"}],
        "Amazon": [{"ids": ["A1ZZFT5FULY4LN"], "nomes": ["Amazon.com.br", "Amazon"],
                    "motivo": "a própria loja (reserva do código)"}],
        "Mercado Livre": [{"ids": ["480263032"], "nomes": ["Mercado Livre"],
                           "motivo": "a própria loja (reserva do código)"}],
        "Casas Bahia": [{"ids": ["10037"], "nomes": ["Casas Bahia"], "motivo": "a própria loja (reserva do código)"}],
        "KaBuM!": [{"nomes": ["KaBuM!", "KaBuM"], "motivo": "a própria loja (reserva do código)"}],
        "Fast Shop": [{"nomes": ["Fast Shop"], "motivo": "a própria loja (reserva do código)"}],
        "Loja TCL": [{"nomes": ["TCL - Brasil", "Loja TCL"],
                      "motivo": "loja oficial do fabricante (reserva do código)"}],
        "Webcontinental": [{"nomes": ["Webcontinental"], "motivo": "a própria loja (reserva do código)"}],
    },
    "reprovados": {
        "Magazine Luiza": [{"ids": ["importadoslili"], "nomes": ["Importados Lili"],
                            "anuncios": ["kc3ca4k960", "kd12g2e47k"],
                            "motivo": "anúncio da TV com sinais de risco em 25/09/2026 (reserva do código; a empresa "
                                      "pode ser vítima de conta invadida)", "desde": "2026-09-25"}],
    },
}


@lru_cache(maxsize=1)
def listas() -> dict:
    """{'confiaveis', 'reprovados', 'erro'}. Arquivo ilegível ou fora do formato: a reserva do código, com 'erro'."""
    try:
        d = json.loads(ARQ_LISTAS.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError("o arquivo tem de ser um objeto JSON")
        for tipo in ("confiaveis", "reprovados"):
            if not isinstance(d.get(tipo), dict):
                raise ValueError(f"'{tipo}' tem de ser um objeto {{loja: [entradas]}}")
            for loja, entradas in d[tipo].items():
                if not isinstance(entradas, list) or not all(isinstance(e, dict) for e in entradas):
                    raise ValueError(f"{tipo}['{loja}'] tem de ser uma lista de objetos")
        return {"confiaveis": d["confiaveis"], "reprovados": d["reprovados"], "erro": None}
    except (OSError, ValueError) as e:  # lista quebrada não pode derrubar a coleta nem soltar o bloqueio curado
        erro = f"{type(e).__name__}: {e}"[:300]
        print(f"[confiança] não li {ARQ_LISTAS.name} ({erro}): usando a reserva do código")
        return {**copy.deepcopy(RESERVA_LISTAS), "erro": erro}


def recarrega_listas() -> None:
    listas.cache_clear()


def erro_das_listas() -> Optional[str]:
    """O erro de leitura do listas_confianca.json (None quando leu)."""
    return listas().get("erro")


def aviso_de_lista_quebrada(estado: Any) -> Optional[str]:
    """Mensagem do Telegram quando o listas_confianca.json não carregou (no máximo a cada AVISO_LISTA_QUEBRADA_H)."""
    from .util import agora_iso

    b = bloco_do_estado(estado)
    erro = erro_das_listas()
    if not erro:
        b.pop("lista_quebrada_avisada", None)
        return None
    idade = _idade_dias(b.get("lista_quebrada_avisada"))
    if idade is not None and idade * 24 < AVISO_LISTA_QUEBRADA_H:
        return None
    b["lista_quebrada_avisada"] = agora_iso()
    return ("⚠️ <b>monitor/listas_confianca.json não carregou</b>\n"
            f"<code>{html.escape(erro)}</code>\n"
            "Até corrigir o arquivo valem só as entradas de reserva do código (as próprias lojas como confiáveis e o "
            "bloqueio curado de 25/09); os outros vendedores passam pelas checagens como vendedor novo.")


def _entradas(tipo: str, loja: str) -> list[dict]:
    return [e for e in (listas()[tipo].get(loja) or []) if isinstance(e, dict)]


def _casa(e: dict, vid: str, nome: str, anuncios: set[str], estrito: bool, automatico: bool = False) -> bool:
    """A entrada é deste vendedor/anúncio?

    estrito (confiáveis): quando a oferta traz o id do vendedor, só o id decide. O nome de exibição é escolhido pelo
    vendedor (na Amazon qualquer um pode se chamar "Fast Shop Loja Oficial"): nome só vale para oferta sem id.
    Não estrito (reprovados): id ou nome do vendedor; o anúncio da lista curada vale para qualquer oferta nele. O
    anúncio de um reprovado AUTOMÁTICO só vale para oferta que não diz quem vende (postagem, linha antiga): oferta de
    outro vendedor no mesmo anúncio não é dele."""
    ids = {_norm(i) for i in e.get("ids") or [] if _norm(i)}
    nomes = {nome_normalizado(n) for n in e.get("nomes") or [] if nome_normalizado(n)}
    if estrito:
        if vid:
            return vid in ids
        return bool(nome) and nome in nomes
    if (bool(vid) and vid in ids) or (bool(nome) and nome in nomes):
        return True
    if anuncios & {_norm(a) for a in e.get("anuncios") or [] if _norm(a)}:
        return not automatico or (not vid and not nome)
    return False


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
        if isinstance(e, dict) and _loja(e) == loja and _casa(e, vid, nome, anuncios, estrito=False, automatico=True):
            return e
    return None


def e_do_reprovado_auto(e: dict, o: Any) -> bool:
    """A oferta/linha do histórico `o` é do reprovado automático `e`? A mesma regra do bloqueio (_casa), sem as listas
    curadas: serve para achar as linhas de um vendedor liberado."""
    loja, vid, nome, anuncios = _pistas(o)
    return isinstance(e, dict) and _loja(e) == loja and _casa(e, vid, nome, anuncios, estrito=False, automatico=True)


def liberado_pela_lista(e: dict) -> bool:
    """O reprovado automático `e` agora é de vendedor da lista de confiáveis (o usuário liberou um falso positivo)."""
    ids = [i for i in e.get("ids") or [] if _norm(i)]
    pistas: list[dict] = [{"loja": e.get("loja"), "vendedor": None, "extra": {"vendedor_id": i}} for i in ids]
    if not ids:
        pistas += [{"loja": e.get("loja"), "vendedor": n} for n in e.get("nomes") or [] if nome_normalizado(n)]
    return any(entrada_confiavel(p) for p in pistas)


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
    return [r for r in out if not liberado_pela_lista(r)]


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
    """Lista compacta (nomes já normalizados) para o painel filtrar linhas antigas de latest/histórico.

    Reprovado automático: sai quando o vendedor foi posto em confiáveis (o painel não conhece a lista de confiáveis),
    não leva nome igual ao de um confiável da loja (nome de exibição é escolhido pelo vendedor) e vai marcado
    'automatico' (o anúncio dele só esconde linha sem vendedor; ver _casa)."""
    out = []
    for loja, entradas in listas()["reprovados"].items():
        for e in entradas:
            out.append({"loja": loja, "ids": sorted({_norm(i) for i in e.get("ids") or [] if _norm(i)}),
                        "nomes": sorted({nome_normalizado(n) for n in e.get("nomes") or [] if nome_normalizado(n)}),
                        "anuncios": sorted({_norm(a) for a in e.get("anuncios") or [] if _norm(a)})})
    for e in auto:
        if not isinstance(e, dict) or liberado_pela_lista(e):
            continue
        loja = _loja(e)
        de_confiavel = {nome_normalizado(n) for c in _entradas("confiaveis", loja) for n in c.get("nomes") or []}
        out.append({"loja": loja, "ids": sorted({_norm(i) for i in e.get("ids") or [] if _norm(i)}),
                    "nomes": sorted({nome_normalizado(n) for n in e.get("nomes") or [] if nome_normalizado(n)}
                                    - de_confiavel),
                    "anuncios": sorted({_norm(a) for a in e.get("anuncios") or [] if _norm(a)}),
                    "origem": "automatico"})
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


def _numeros_anatel(campo: Any) -> list[str]:
    """Os números de homologação do campo Anatel da ficha (12 dígitos, com o zero à esquerda que falte). O campo pode
    trazer mais de um (TV e controle remoto, que a ficha junta com ' | ')."""
    out = []
    for t in re.findall(r"\d[\d.\-]*\d", str(campo or "")):
        d = _digitos(t)
        if 9 <= len(d) <= 12:
            out.append(d.zfill(12))
    return out


def anatel_confere(campo: Any) -> Optional[bool]:
    """A homologação da 55C6K está no campo Anatel da ficha? None sem número legível. Outros números no mesmo campo
    (controle, módulo) e a falta do zero à esquerda não contam contra (revisão de 26/09)."""
    alvo = _digitos(ANATEL_55C6K)
    todos = _digitos(campo)
    if len(todos) < 8:
        return None
    return alvo in todos or alvo in _numeros_anatel(campo)


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


def sinais_da_oferta(o: Any, ref: Referencias, catalogo: Optional[dict] = None,
                     so_preco: bool = False) -> tuple[list[Sinal], list[str]]:
    """(sinais de risco, checagens feitas) de uma oferta de vendedor desconhecido. Só usa dado já em mãos.
    so_preco: só a comparação com as lojas confiáveis (linha de agregador: não há vendedor nem ficha a checar)."""
    s: list[Sinal] = []
    feitas: list[str] = []
    ex = _extra(o)
    ficha = ex.get("ficha") if isinstance(ex.get("ficha"), dict) else {}
    melhor = melhor_preco(o)
    # "preço cheio" é só o preço do cartão DESTA oferta. O preço "de" (ListPrice do Magalu/VTEX) e o riscado do ML
    # (que o coletor grava em .preco) não contam: "de R$ 4.099 por R$ 2.700" vale para qualquer pagamento, e 4.099
    # costuma ser o preço de lista de todo mundo (revisão de 26/09)
    cartao = None if _loja(o) in LOJAS_PRECO_PODE_SER_RISCADO else _num(_campo(o, "preco"))

    # 1) preço: muito abaixo da loja confiável mais barata; "preço cheio" copiado com desconto enorme só no Pix/1x
    if melhor and ref.menor:
        feitas.append("preço")
        r = melhor / ref.menor[0]
        if r <= FRACAO_MUITO_ABAIXO:
            s.append(Sinal("preco_muito_abaixo", True,
                           f"preço {_fmt(melhor)} é {_pct(1 - r)} menor que o da loja confiável mais barata "
                           f"({_fmt(ref.menor[0])}, {ref.menor[1]})"))
    if so_preco:
        return s, feitas
    if melhor and cartao and cartao > melhor + 0.5:
        desc = 1 - melhor / cartao
        # o "copiado" é o que faz do desconto um sinal forte: sem ele, só um desconto enorme (fraco)
        igual = next((q for v, q in ref.precos if abs(v - cartao) <= IGUAL_REAIS), None) \
            if desc > DESCONTO_SO_PIX_COPIADO else None
        if igual:
            s.append(Sinal("preco_cheio_copiado", True,
                           f"“preço cheio” {_fmt(cartao)} igual ao de {igual}, com {_pct(desc)} de desconto só no "
                           f"Pix/1x"))
        elif desc > DESCONTO_SO_PIX:
            s.append(Sinal("desconto_so_no_pix", False, f"desconto de {_pct(desc)} só no Pix/1x"))

    # 2) ficha técnica do anúncio
    if _digitos(ficha.get("anatel")):
        feitas.append("Anatel")
        if anatel_confere(ficha.get("anatel")) is False:
            numeros = _numeros_anatel(ficha.get("anatel")) or [_digitos(ficha.get("anatel"))]
            s.append(Sinal("anatel_diferente", True,
                           f"certificado Anatel {', '.join(_anatel_fmt(n) for n in numeros[:3])} não é o da 55C6K "
                           f"({ANATEL_55C6K})"))
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
        m = _RE_OUTRO_RAMO.search(_ascii(razao))
        if m:
            # só o ramo, sem o nome da empresa: o sinal vai para o latest/state públicos e a empresa pode ser vítima
            ramo = re.match(r"[a-z]+", _ascii(razao)[m.start():])
            s.append(Sinal("razao_social_de_outro_ramo", False,
                           f"razão social de outro ramo ({ramo.group() if ramo else 'não é de eletro'})"))
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
        # poucas TVs: até as que o próprio invasor anunciou (loja pequena passa de 2% com 4 anúncios) ou menos de 2%
        poucas_tvs = tv < MIN_TVS_LOJA_DE_TV and (tv <= MAX_TVS_DO_INVASOR or tv / total < 0.02)
        if total >= 30 and poucas_tvs and eletro / total < 0.10:
            principais = ", ".join((catalogo.get("principais") or [])[:3])
            s.append(Sinal("catalogo_sem_tv", True,
                           f"a loja do vendedor tem {total:,} itens e só {tv} de TV ({tv / total * 100:.1f}%)".replace(",", ".")
                           + (f"; vende sobretudo {principais}" if principais else "")))
    return s, feitas


def decide(sinais: list[Sinal]) -> str:
    """Suspeito: QUALQUER sinal forte (preço até 80% da loja confiável mais barata já basta, revisão de 26/09) ou
    FRACOS_PARA_SUSPEITO sinais fracos juntos. O resto passa, com os sinais fracos anotados na linha 🔎."""
    fortes = sum(1 for x in sinais if x.forte)
    fracos = len(sinais) - fortes
    return SUSPEITO if fortes >= 1 or fracos >= FRACOS_PARA_SUSPEITO else SEM_RISCO


def reprova(sinais: list[Sinal]) -> bool:
    """O suspeito vira reprovado automático (descartado de cara nas próximas coletas, sem nova checagem)? Só com 2+
    sinais fortes, um deles de IDENTIDADE (Anatel/tamanho de outro produto, loja sem TV no catálogo). Sinal de preço
    sozinho nunca reprova de vez: uma promoção de verdade de vendedor desconhecido limpo fica suspeita, é reavaliada a
    cada rodada e pode ser liberada pondo o vendedor em confiáveis."""
    fortes = [x for x in sinais if x.forte and x.codigo not in SINAIS_SEM_PROVA]
    return len(fortes) >= 2 and any(x.codigo in SINAIS_DE_IDENTIDADE for x in fortes)


def _tem_identidade(ficha: Any) -> bool:
    """A ficha traz o que identifica o anúncio (homologação Anatel ou avaliações da página)? A da busca do Magalu
    não traz."""
    return isinstance(ficha, dict) and ("anatel" in ficha or "avaliacoes" in ficha)


def _sinal_sem_checagem(o: Any, ref: Referencias, cat: Optional[dict], porque: str) -> Optional[Sinal]:
    """Vendedor novo numa loja com checagem de rede (Magalu) que ficou sem a ficha do anúncio ou sem o catálogo da loja
    (403, limite da rodada, rede desligada) e está ABAIXO da loja confiável mais barata (sem referência: no alvo):
    sinal forte que segura 🎯/🏆/🔻, mínimo e carrinho nesta rodada, sem ser prova (reavaliado na próxima; revisão de
    26/09: o anúncio só da busca, depois de um 403, passava como "checagens ok (preço)").

    Catálogo com falha passageira (timeout, 5xx, 404, página ilegível; cat com 'erro') não conta: é "checagem da loja
    pendente", tentada de novo na rodada seguinte (revisão 3 de 26/09). A ficha que falta continua contando: sem ela
    não há Anatel nem avaliações para conferir."""
    p = melhor_preco(o)
    if not p:
        return None
    if ref.menor is not None and p >= ref.menor[0]:
        return None
    if ref.menor is None and p > config.ALVO_PARCELADO:
        return None
    faltou = []
    if not _tem_identidade(_extra(o).get("ficha")):
        faltou.append("a ficha do anúncio")
    if not cat:
        faltou.append("o catálogo da loja do vendedor")
    if not faltou:
        return None
    onde = (f"abaixo da loja confiável mais barata ({_fmt(ref.menor[0])}, {ref.menor[1]})" if ref.menor
            else "no alvo, sem loja confiável para comparar")
    return Sinal("nao_checado", True, f"não deu para checar {' nem '.join(faltou)} ({porque}) e o preço {_fmt(p)} "
                                      f"está {onde}; nova tentativa na próxima rodada")


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


def _magalu_bloqueou_ha_pouco() -> bool:
    """A coleta do Magalu desta execução (ou de há pouco) levou 403/429: não insistir com a checagem."""
    from .sources import magalu

    return magalu.bloqueio_recente()


# loja -> (lê o catálogo do vendedor, completa a ficha do anúncio, a loja bloqueou há pouco?). A Amazon responde 503
# a HTTP na página do vendedor e o ML exige conta: nelas a checagem fica com o que a coleta já traz (avaliações/vendas
# do vendedor).
CHECAGENS_DE_REDE: dict[str, tuple[Callable, Callable, Callable[[], bool]]] = {
    "Magazine Luiza": (_catalogo_magalu, _ficha_magalu, _magalu_bloqueou_ha_pouco)}


# ------------------------------------------------------------------------------------------------
# a rodada: descartar reprovados, dar veredito a cada oferta, guardar no state
# ------------------------------------------------------------------------------------------------

def bloco_do_estado(estado: Any) -> dict:
    b = estado.dados.setdefault("confianca", {})
    for k in ("vendedores", "catalogos", "reprovados_auto", "fichas", "avisos"):
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
    """Reprovados automáticos deste modo (em memória, inclusive os desta rodada) e do outro (state, só leitura), menos
    os que o usuário liberou pondo o vendedor na lista de confiáveis."""
    regs = list(bloco_do_estado(estado)["reprovados_auto"].values())
    for b in _blocos_de_outros_modos(estado):
        r = b.get("reprovados_auto")
        regs += list(r.values()) if isinstance(r, dict) else []
    return [r for r in regs if isinstance(r, dict) and not liberado_pela_lista(r)]


def _tira_liberados(bloco: dict) -> list[dict]:
    """Reprovado automático cujo vendedor entrou na lista de confiáveis sai do state deste modo (devolve os que saíram)."""
    saiu = []
    for k in [k for k, r in bloco["reprovados_auto"].items() if isinstance(r, dict) and liberado_pela_lista(r)]:
        print(f"[confiança] {k} liberado pela lista de confiáveis: sai dos reprovados automáticos")
        saiu.append(bloco["reprovados_auto"].pop(k))
    return saiu


def _liberados_de_outros_modos(estado: Any) -> list[dict]:
    """Reprovados automáticos do outro modo já liberados pela lista (saem do state dele na próxima rodada dele)."""
    out = []
    for b in _blocos_de_outros_modos(estado):
        r = b.get("reprovados_auto")
        out += [e for e in (r.values() if isinstance(r, dict) else []) if isinstance(e, dict) and liberado_pela_lista(e)]
    return out


def _do_cache(estado: Any, secao: str, chave: str) -> Optional[dict]:
    regs = [bloco_do_estado(estado)[secao].get(chave)]
    regs += [(b.get(secao) or {}).get(chave) for b in _blocos_de_outros_modos(estado) if isinstance(b.get(secao), dict)]
    validos = [r for r in regs if isinstance(r, dict) and r.get("quando")]
    return max(validos, key=lambda r: r["quando"]) if validos else None


def _chave_ficha(o: Any, chave: str) -> str:
    """Chave do cache da ficha: o vendedor e o anúncio da URL (a busca e a página do anúncio dão a mesma)."""
    m = _RE_ANUNCIO_URL.search(str(_campo(o, "url") or ""))
    anuncio = _norm(_extra(o).get("anuncio")) or (_norm(m.group(1)) if m else "")
    return f"{chave}|{anuncio or '-'}"


def _ficha_em_cache(reg: Optional[dict]) -> Optional[dict]:
    """A ficha guardada, se ainda vale (TTL_FICHA_DIAS)."""
    if not isinstance(reg, dict) or not isinstance(reg.get("ficha"), dict) or not reg["ficha"]:
        return None
    idade = _idade_dias(reg.get("ficha_em"))
    return reg["ficha"] if idade is not None and idade < TTL_FICHA_DIAS else None


def _catalogo_em_cache(estado: Any, chave: str) -> Optional[dict]:
    r = _do_cache(estado, "catalogos", chave)
    if not r:
        return None
    idade = _idade_dias(r.get("quando"))
    if idade is None:
        return None
    if r.get("erro"):
        return r if idade * 24 * 60 < TTL_FALHA_MIN else None
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


def _diretas(estado: Any, ofertas: list) -> set[str]:
    """Lojas com fonte direta (a linha do agregador delas não é preço; ver estado.conta_como_preco)."""
    try:
        return set(estado.lojas_diretas_conhecidas(ofertas))
    except Exception:  # noqa: BLE001 - sem saber, trata toda loja do agregador como coberta (não checa nem conta)
        return {_loja(o) for o in ofertas}


def _avalia_agregadas(agregadas: list, ref: Referencias, contagem: dict) -> None:
    """Linha de agregador (Zoom) de loja sem fonte direta: não há vendedor nem ficha, só a comparação de preço com as
    lojas confiáveis. Muito abaixo -> suspeita (fora de alerta de preço, mínimo e painel); senão, a linha 🔎."""
    for o in agregadas:
        sinais, feitas = sinais_da_oferta(o, ref, so_preco=True)
        veredito = decide(sinais)
        o.extra["confianca"] = {"veredito": veredito, "checagens": feitas, "sinais": [x.texto for x in sinais],
                                "agregador": True}
        contagem[veredito] = contagem.get(veredito, 0) + 1
        print(f"[confiança] {veredito}: agregador {o.fonte}/{_loja(o)} ({o.id}) {_fmt(melhor_preco(o) or 0)}"
              + (f" — {'; '.join(x.texto for x in sinais)[:200]}" if sinais else ""))


def avaliar(estado: Any, ofertas: list, rede: bool = True, obter: Optional[Callable[[str], str]] = None,
            pausa_s: Optional[float] = None) -> dict:
    """Dá o veredito de cada oferta de loja (extra['confianca']) e guarda o que precisa no state.

    Confiável (lista) não passa por checagem nenhuma. Desconhecido: sinais com o que a coleta já tem; com `rede`,
    até MAX_VENDEDORES_COM_REDE vendedores novos de preço atraente ganham 1-2 requisições (o anúncio, se a coleta não
    o abriu, e o catálogo do vendedor), com a pausa da coleta entre elas e guardadas no state. Suspeito com sinais de
    identidade vira reprovado automático (ver reprova()). Agregador de loja sem fonte direta: só a checagem de preço.
    Devolve {veredito: quantidade}."""
    obter_base = obter or _obter_padrao
    espera = config.MAGALU_PAUSA_S if pausa_s is None else pausa_s
    pedidos = [0]

    def pedir(url: str) -> str:
        if pedidos[0] and espera > 0:
            time.sleep(espera)
        pedidos[0] += 1
        return obter_base(url)

    bloco = bloco_do_estado(estado)
    # vendedor liberado pela lista de confiáveis: as linhas dele no histórico (o reprovado automático não as apaga)
    # voltam a contar para o mínimo
    liberados = _tira_liberados(bloco) + _liberados_de_outros_modos(estado)
    restaura = getattr(estado, "restaura_minimo_de_liberados", None)
    if liberados and callable(restaura):
        restaura(liberados)
    auto = reprovados_auto_do_estado(estado)
    from .util import agora_iso

    agora = agora_iso()
    contagem: dict[str, int] = {}
    desconhecidas = []
    agregadas = []
    diretas: Optional[set[str]] = None
    for o in ofertas:
        if o.tipo != "loja":
            continue
        if _e_agregador(o):
            if o.ativo and melhor_preco(o):
                if diretas is None:
                    diretas = _diretas(estado, ofertas)
                if _loja(o) not in diretas:
                    agregadas.append(o)
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
    if desconhecidas or agregadas:
        ref = referencias(ofertas, _extras_de_referencia(estado))
        if agregadas and ref.menor:  # sem nenhuma loja confiável de referência não há o que comparar
            _avalia_agregadas(agregadas, ref, contagem)
        _avalia_desconhecidas(estado, bloco, desconhecidas, ref, contagem, agora, rede, pedir)
    _limpa_caches(bloco)
    return contagem


def _avalia_desconhecidas(estado: Any, bloco: dict, desconhecidas: list, ref: Referencias, contagem: dict, agora: str,
                          rede: bool, pedir: Callable[[str], str]) -> None:
    usadas = 0
    bloqueado = False
    for o in sorted(desconhecidas, key=lambda x: melhor_preco(x) or 9e9):
        chave = chave_vendedor(o)
        loja = _loja(o)
        vid = vendedor_id(o)
        ficha = o.extra.get("ficha") if isinstance(o.extra.get("ficha"), dict) else {}
        # a ficha lida numa rodada anterior (coleta ou checagem) vale quando esta coleta só trouxe a busca (revisão de
        # 26/09: sem isto, o anúncio com Anatel de outro produto virava "sem risco" na rodada seguinte)
        chave_ficha = _chave_ficha(o, chave) if chave else None
        reg_ficha = _do_cache(estado, "fichas", chave_ficha) if chave_ficha else None
        fresca = _tem_identidade(ficha)
        guardada = None if fresca else _ficha_em_cache(reg_ficha)
        if guardada:
            o.extra["ficha"] = ficha = {**guardada, **ficha}
        abriu: Optional[bool] = None
        falha_anuncio = ""
        cat = _catalogo_em_cache(estado, chave) if chave else None
        sinais, feitas = sinais_da_oferta(o, ref, cat if cat and not cat.get("erro") else None)
        checagem = CHECAGENS_DE_REDE.get(loja)
        if rede and checagem and vid and not bloqueado and checagem[2]():
            bloqueado = True
            print(f"[confiança] a coleta de {loja} levou 403/429 há pouco: sem checagem de rede nesta rodada")
        # a checagem de rede traz provas (catálogo, ficha) para quem ainda não tem o bastante para ser reprovado
        if rede and checagem and vid and not bloqueado and not reprova(sinais) and usadas < MAX_VENDEDORES_COM_REDE \
                and _atraente(o, ref, sinais):
            ler_catalogo, ler_ficha, _bloqueou = checagem
            gastou = False
            idade_aberto = _idade_dias((reg_ficha or {}).get("aberto_em"))
            # anúncio lido: não reabre por TTL_FICHA_H; falha passageira (erro ou página sem a ficha): na rodada seguinte
            ttl_aberto_h = TTL_FICHA_H if (reg_ficha or {}).get("ok") else TTL_FALHA_MIN / 60
            aberto_ha_pouco = idade_aberto is not None and idade_aberto * 24 < ttl_aberto_h
            if aberto_ha_pouco and not (reg_ficha or {}).get("ok"):
                falha_anuncio = "o anúncio não abriu há pouco"
            if not _tem_identidade(ficha) and not aberto_ha_pouco:
                gastou = True
                try:
                    nova = ler_ficha(o, vid, pedir)
                    abriu = bool(nova)
                    if nova:
                        o.extra["ficha"] = ficha = {**ficha, **nova}
                        fresca = fresca or _tem_identidade(nova)
                    else:
                        falha_anuncio = "página do anúncio ilegível"
                except _Bloqueio:
                    bloqueado = True
                except Exception as e:  # noqa: BLE001 - checagem extra: falha não derruba a rodada
                    abriu = False
                    falha_anuncio = f"falha ao abrir o anúncio: {type(e).__name__}"
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
        # sem sinal forte, mas sem a ficha ou o catálogo e abaixo da confiável mais barata: não passa como
        # "checagens ok"
        if checagem and not any(x.forte for x in sinais):
            porque = ("a loja bloqueou as consultas (403/429)" if bloqueado else
                      "checagem de rede desligada" if not rede else
                      falha_anuncio if falha_anuncio else
                      "limite de checagens da rodada" if usadas >= MAX_VENDEDORES_COM_REDE else
                      "a página não trouxe os dados")
            falta = _sinal_sem_checagem(o, ref, cat, porque)
            if falta:
                sinais.append(falta)
        veredito = decide(sinais)
        info = {"veredito": veredito, "checagens": feitas, "sinais": [x.texto for x in sinais],
                "codigos": [x.codigo for x in sinais]}
        if cat and not cat.get("erro"):
            info["catalogo"] = {k: cat.get(k) for k in ("total", "tv")}
        elif checagem and cat:
            info["catalogo_pendente"] = True   # falha passageira na página da loja: nova tentativa na rodada seguinte
        if guardada:
            info["ficha_guardada"] = True
        if veredito == SUSPEITO and reprova(sinais) and chave:
            info["reprovado_auto"] = True
        o.extra["confianca"] = info
        contagem[veredito] = contagem.get(veredito, 0) + 1
        print(f"[confiança] {veredito}{' (reprovado automático)' if info.get('reprovado_auto') else ''}: "
              f"{_quem(o)} ({o.id}) {_fmt(melhor_preco(o) or 0)}"
              + (f" — {'; '.join(info['sinais'])[:300]}" if info["sinais"] else "")
              + (f" [checagens: {', '.join(feitas)}]" if feitas else ""))
        if chave_ficha and (fresca or abriu is not None):
            reg = dict(bloco["fichas"].get(chave_ficha) or reg_ficha or {})
            if fresca:
                reg["ficha"] = {k: ficha[k] for k in CAMPOS_FICHA if k in ficha}
                reg["ficha_em"] = agora
            if abriu is not None:
                reg["aberto_em"], reg["ok"] = agora, abriu
            reg["quando"] = agora
            bloco["fichas"][chave_ficha] = reg
        if chave:
            reg = {"loja": loja, "vendedor": o.vendedor, "vendedor_id": vid or None, "veredito": veredito,
                   "sinais": info["sinais"], "quando": agora, "chave_oferta": o.chave, "preco": melhor_preco(o)}
            antes = bloco["vendedores"].get(chave)
            reg["primeira_vez"] = (antes or {}).get("primeira_vez") or agora
            bloco["vendedores"][chave] = reg
        if info.get("reprovado_auto"):
            _reprova_automatico(bloco, o, info["sinais"], agora)


def _limpa_caches(bloco: dict) -> None:
    # veredito "sem risco" velho sai do cache (o vendedor volta a ser checado do zero)
    for k in [k for k, r in bloco["vendedores"].items()
              if not isinstance(r, dict) or (_idade_dias(r.get("quando")) or 0) > TTL_VEREDITO_DIAS]:
        del bloco["vendedores"][k]
    for secao, ttl in (("catalogos", TTL_CATALOGO_DIAS), ("fichas", TTL_FICHA_DIAS)):
        for k in [k for k, r in bloco[secao].items()
                  if not isinstance(r, dict) or (_idade_dias(r.get("quando")) or 0) > ttl]:
            del bloco[secao][k]
    for k in [k for k, r in bloco["avisos"].items()
              if not isinstance(r, dict) or (_idade_dias(r.get("visto")) or 0) > TTL_AVISO_DIAS]:
        del bloco["avisos"][k]


def _reprova_automatico(bloco: dict, o: Any, sinais: list[str], quando: str) -> None:
    """Suspeito com sinais de identidade vira reprovado automático (as próximas coletas o descartam de cara). A chave é
    o VENDEDOR; o anúncio só vai junto quando é só dele (_anuncio_proprio)."""
    chave = chave_vendedor(o)
    if not chave:
        return  # sem id nem nome (ex.: 'destaque' da busca da Amazon, opção do ML sem vendedor): nada que identifique
    vid = vendedor_id(o)
    anuncio = _anuncio_proprio(o)
    bloco["reprovados_auto"][chave] = {
        "loja": _loja(o), "ids": [vid] if vid else [], "nomes": [o.vendedor] if o.vendedor else [],
        "anuncios": [anuncio] if anuncio else [],
        "motivo": f"anúncio da TV com sinais de risco em {_data_br(quando)}: " + "; ".join(sinais),
        "desde": quando, "origem": "automatico", "chave_oferta": o.chave, "preco": melhor_preco(o),
    }


def _pagina_e_vendedor(url: Any) -> tuple[str, str]:
    """(caminho da URL sem query, vendedor da URL): a oferta do vendedor da página e o cupom dela têm os dois iguais."""
    u = str(url or "").strip()
    m = _RE_VID_URL.search(u)
    return u.lower().split("#", 1)[0].split("?", 1)[0].rstrip("/"), (_norm(m.group(1)) if m else "")


def cupom_barrado(c: Any, ofertas: Iterable[Any] = (), auto: Optional[Iterable[dict]] = None) -> Optional[str]:
    """Motivo quando o cupom é da página de um anúncio barrado (reprovado ou suspeito); None se não é.

    No Magalu o cupom do anúncio (seller.tags) é do vendedor do buy box da página e vem com o link dela: o alerta, o
    painel e o testador levariam a pessoa ao anúncio barrado (revisão de 26/09). Cupom do site ou de postagem (sem
    anúncio) passa. `ofertas`: as da rodada, inclusive as descartadas por reprovado (run.py passa as coletadas)."""
    if not _campo(c, "especifico"):
        return None
    loja = _loja(c)
    pista = {"loja": loja, "url": _campo(c, "url"), "tipo": "cupom"}
    if not anuncios_da_oferta(pista):
        return None
    lista = list(auto) if auto is not None else None
    motivo = motivo_bloqueio(pista, lista)
    if motivo:
        return motivo
    pagina = _pagina_e_vendedor(_campo(c, "url"))
    for o in ofertas:
        if _loja(o) != loja or str(_campo(o, "tipo") or "") != "loja" or _pagina_e_vendedor(_campo(o, "url")) != pagina:
            continue
        v = veredito_de(o)
        if v in VEREDITOS_FORA:
            return f"cupom da página de anúncio {v}"
        m = motivo_bloqueio(o, lista)
        if m:
            return m
    return None


def _loja_do_link(url: str, padrao: str) -> str:
    """A loja pelo domínio do link (o link do Telegram pode ser de outra loja que a do texto); senão, `padrao`."""
    from urllib.parse import urlsplit

    from .util import loja_canonica

    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        host = ""
    loja = loja_canonica(host) if host else ""
    return loja if loja in set(config.LOJAS_CANONICAS.values()) else padrao


def _palavras(s: Any) -> str:
    return f" {re.sub(r'[^a-z0-9]+', ' ', _ascii(s)).strip()} "


def _nome_citavel(nome: Any, loja: str) -> bool:
    """O nome do vendedor serve para achá-lo no texto da postagem? Não quando é curto, é o nome da loja ou o de um
    confiável dela (nome de exibição é escolhido pelo vendedor: um suspeito chamado "Magalu" não pode tirar o 🎯 de
    toda postagem que fala do Magalu)."""
    n = nome_normalizado(nome)
    if len(n) < 5 or n == nome_normalizado(loja):
        return False
    return n not in {nome_normalizado(x) for e in _entradas("confiaveis", loja) for x in e.get("nomes") or []}


def postagem_barrada(p: Any, ofertas: Iterable[Any] = (), auto: Optional[Iterable[dict]] = None) -> Optional[str]:
    """Motivo quando a postagem (Pelando, Promobit, Telegram) leva a um anúncio que esta rodada julgou suspeito ou
    reprovado, ou cita o vendedor dele pelo nome; None se não (revisão 3 de 26/09: o laço de postagens só olhava o
    preço, e o anúncio suspeito saía como "📣 Promoção postada 🎯" com o mesmo link do aviso ⚠️).

    Links: a URL da postagem e os links do texto (Telegram, extra.links). Casa pelo vendedor da URL
    (?seller_id/smid/idLojista) ou, sem vendedor na URL, pelo anúncio (/p/<id>/) quando o barrado é o vendedor que a
    página abre (o do buy box, cuja URL não traz ?seller_id, ou o dono exclusivo do anúncio). Assim o suspeito da lista
    de vendedores do anúncio do Magalu 1P não tira o 🎯 da postagem do 1P. A lista curada e os reprovados automáticos
    valem para os links (o do Telegram não passa pelo descarta_reprovados, que só vê a URL da postagem).
    `ofertas`: as de loja da rodada, com veredito; `auto`: reprovados automáticos (None: os dos state_<modo>.json)."""
    lista = list(auto) if auto is not None else reprovados_auto_dos_arquivos()
    catalogo_ml = _norm(config.ML_CATALOGO_ID)
    barradas = [o for o in ofertas if str(_campo(o, "tipo") or "") == "loja" and veredito_de(o) in VEREDITOS_FORA
                and not _e_agregador(o)]
    loja_post = _loja(p)
    links = [str(_campo(p, "url") or "")] + [str(u) for u in (_extra(p).get("links") or []) if u]
    for url in [u for u in links if u]:
        loja = _loja_do_link(url, loja_post)
        pista = {"loja": loja, "url": url, "tipo": "post"}
        vid = vendedor_id(pista)
        anuncios = anuncios_da_oferta(pista) - {catalogo_ml}
        for o in barradas:
            if _loja(o) != loja:
                continue
            if vid:
                casa = vid == vendedor_id(o)
            else:
                vend_na_url = _pagina_e_vendedor(_campo(o, "url"))[1]
                do_buy_box = set() if vend_na_url else anuncios_da_oferta({"loja": loja, "url": _campo(o, "url")})
                casa = bool(anuncios & ((do_buy_box | {_anuncio_proprio(o)}) - {"", catalogo_ml}))
            if casa:
                return f"o link leva a anúncio com sinais de risco nesta rodada ({_quem(o)})"
        if motivo_bloqueio(pista, lista):
            return "o link leva a anúncio reprovado (sinais de risco)"
    # o nome do vendedor barrado no texto da postagem ("vendido por ...")
    texto = _palavras(" ".join(str(x) for x in (_campo(p, "titulo"), _extra(p).get("texto"), _campo(p, "vendedor"))
                               if x))
    nomes = [(_loja(o), str(_campo(o, "vendedor") or "")) for o in barradas]
    nomes += [(loja, str(n)) for loja, entradas in listas()["reprovados"].items() for e in entradas
              for n in e.get("nomes") or []]
    nomes += [(_loja(e), str(n)) for e in lista if isinstance(e, dict) for n in e.get("nomes") or []]
    for loja, nome in nomes:
        if loja_post not in ("", "?", loja) or not _nome_citavel(nome, loja):
            continue
        if _palavras(nome) in texto:
            return f"a postagem cita o vendedor {nome.strip()}, com sinais de risco"
    return None


def descarta_cupons_barrados(estado: Any, cupons: list, ofertas: Iterable[Any]) -> list:
    """Tira da rodada o cupom da página de anúncio reprovado/suspeito (ver cupom_barrado). Só log."""
    auto = reprovados_auto_do_estado(estado)
    ofertas = list(ofertas)
    out = []
    for c in cupons:
        motivo = cupom_barrado(c, ofertas, auto)
        if motivo:
            print(f"[confiança] cupom {c.codigo} descartado (página de anúncio barrado): {motivo[:140]}")
        else:
            out.append(c)
    return out


def deve_avisar(estado: Any, o: Any) -> bool:
    """O aviso ⚠️ deste anúncio suspeito sai agora? Na primeira vez e quando o preço cai QUEDA_NOVO_AVISO ou mais desde
    o último aviso. Nas outras rodadas (a nuvem coleta a cada 15 min) o suspeito continua fora de tudo, sem repetir a
    mensagem. Guarda em state['confianca']['avisos'] (por vendedor ou, sem ele, pela oferta)."""
    from .util import agora_iso

    p = melhor_preco(o)
    if not p:
        return False
    avisos = bloco_do_estado(estado)["avisos"]
    chave = chave_aviso(o)
    agora = agora_iso()
    antes = avisos.get(chave)
    ultimo = _num(antes.get("preco")) if isinstance(antes, dict) else None
    if ultimo and p > ultimo * (1 - QUEDA_NOVO_AVISO):
        antes["visto"] = agora
        return False
    avisos[chave] = {"preco": p, "avisado_em": agora, "visto": agora, "loja": _loja(o),
                     "vendedor": _campo(o, "vendedor")}
    return True


# ------------------------------------------------------------------------------------------------
# textos das mensagens e o carrinho
# ------------------------------------------------------------------------------------------------

def linha_vendedor_novo(o: Any) -> Optional[str]:
    """Linha extra do alerta de vendedor desconhecido (ou linha de agregador) que passou nas checagens (texto puro)."""
    c = _extra(o).get("confianca")
    if not isinstance(c, dict) or c.get("veredito") != SEM_RISCO:
        return None
    feitas = c.get("checagens") or []
    if c.get("agregador"):
        quem = "linha de agregador (vendedor não identificado)"
    else:
        quem = "vendedor novo" if _campo(o, "vendedor") else "vendedor não identificado"
    if c.get("catalogo_pendente"):
        # a página da loja do vendedor falhou (timeout, 5xx, 404, ilegível): não é sinal, é checagem por fazer
        linha = f"🔎 {quem}: checagem da loja pendente (nova tentativa na próxima rodada)" + \
            (f"; checagens ok ({', '.join(feitas)})" if feitas else "")
    else:
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
    sinais, _feitas = sinais_da_oferta(o, referencias(todas), so_preco=_e_agregador(o))
    if decide(sinais) == SUSPEITO:
        return False, "anúncio suspeito: " + "; ".join(x.texto for x in sinais)
    return True, SEM_RISCO


