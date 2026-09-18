"""Aceita SÓ a TCL 55C6K de 55 polegadas. Tudo o mais é descartado aqui."""

from __future__ import annotations

import re
from typing import Optional

from .util import sem_acentos

_TAMANHOS = r"32|40|43|50|58|65|70|75|85|98|100|115"

# "C6K" como token (não pega C6KS, C655, etc.)
_RE_C6K = re.compile(r"c6k(?![a-z0-9])", re.I)
# "55" isolado de outros dígitos: pega 55C6K, 55", 55 pol, 55 polegadas
_RE_55 = re.compile(r"(?<!\d)55(?!\d)")
# literal 55C6K (com ou sem espaço)
_RE_55C6K = re.compile(r"(?<!\d)55\s*c6k(?![a-z0-9])", re.I)
# outros tamanhos citados junto com polegadas/aspas/C6K
_RE_OUTRO_TAMANHO = re.compile(
    rf"(?<!\d)({_TAMANHOS})\s*(?:[\"”″]|\s?pol|\s?polegadas|\s?c6k)", re.I
)
# outro tamanho colado ao modelo (65C6K, 75 C6K). Mesmo com "55C6K" no texto, é anúncio de vários
# tamanhos ou acessório "compatível com 55c6k 65c6k 75c6k..."
_RE_OUTRO_C6K = re.compile(rf"(?<!\d)({_TAMANHOS})\s*c6k(?![a-z0-9])", re.I)
# exceção: o par "55C6K/65C6K" ou "55C6K ou 65C6K" (postagem que cobre as duas medidas) continua aceito
_SEP_PAR = r"\s*(?:/|\bou\b|\be\b)\s*"
_RE_PAR_BARRA = re.compile(
    rf"(?<!\d)55\s*c6k{_SEP_PAR}(?:{_TAMANHOS})\s*c6k|(?<!\d)(?:{_TAMANHOS})\s*c6k{_SEP_PAR}55\s*c6k", re.I
)

# Palavras que indicam que NÃO é a TV sozinha, nova
_NEGATIVOS = [
    "combo", "soundbar", "sound bar", "kit ", "usad", "recondicionad", "open box", "openbox",
    "vitrine", "seminov", "semi-nov", "suporte", "capa ", "controle", "pelicula",
    "cabo hdmi", "base ", "pedestal", "peca ", "peça ", "tela quebrada", "defeito",
    # peças e acessórios
    "barra de led", "barras de led", "fonte de alimenta", "placa", "display", "tela para",
    # estado do produto
    "reembalad", "mostruario", "recertificad", "remanufaturad", "avaria",
    "c655", "c6ks", "c7k", "c8k", "c9k", "p7k", "p8k", "q6k", "q7k", "x955", "s5k", "p755",
]
# "com suporte a Dolby Vision / HDR10+" é recurso da TV, não o acessório "suporte de parede"
_RE_SUPORTE_A_RECURSO = re.compile(r"\bsuporte\s+(?:a|ao|aos|as)\s")
# acessórios: título que começa pelo nome da peça, "para TV", "compatível com TV/TCL"
_RE_ACESSORIO = [
    re.compile(
        r"^[^a-z0-9]*(controle|comando|barras?|placa|fonte|tela|display|painel|suporte|capa|cabo|"
        r"pelicula|kit|base|pedestal|pecas?|protetor|adesivo|modulo|lampada)\b"
    ),
    re.compile(r"\b(?:para|pra|p/)\s*(?:as?\s+|os?\s+)?(?:smart\s*)?(?:tvs?|televis\w*)\b"),
    re.compile(r"\bcompativel\s+(?:com\s+)?(?:as?\s+|os?\s+)?(?:smart\s*)?(?:tvs?|televis\w*|tcl)\b"),
]


def normaliza(texto: str) -> str:
    return sem_acentos(texto or "").lower().replace("″", '"').replace("”", '"')


def _motivo(t: str) -> str:
    """t já normalizado. '' = é a 55C6K; senão o motivo da recusa."""
    if not _RE_C6K.search(t):
        return "sem C6K"
    t_neg = _RE_SUPORTE_A_RECURSO.sub(" ", t)
    neg = [n for n in _NEGATIVOS if n in t_neg]
    if neg:
        return f"negativo: {neg[0].strip()}"
    for r in _RE_ACESSORIO:
        m = r.search(t)
        if m:
            return f"acessório: {(m.group(1) if r.groups else m.group(0)).strip()}"
    if _RE_55C6K.search(t):
        outros = {m.group(1) for m in _RE_OUTRO_C6K.finditer(t)}
        if outros and not (len(outros) == 1 and _RE_PAR_BARRA.search(t)):
            return "vários tamanhos"
        return ""
    if not _RE_55.search(t):
        return "sem 55"
    if _RE_OUTRO_TAMANHO.search(t):
        return "outro tamanho"
    return ""


def eh_55c6k(texto: str) -> bool:
    """True se o texto se refere à TCL 55C6K (55") e não a combos, outros tamanhos ou acessórios."""
    return _motivo(normaliza(texto)) == ""


def motivo_rejeicao(texto: str) -> str:
    """Só para depuração: explica por que um título foi descartado."""
    return _motivo(normaliza(texto))


# Mensagem livre (Telegram): a descrição da própria TV usa palavras da lista de negativos
# ("suporte a HDR10+", "controle remoto por voz", "base", "pedestal de plástico"). Por isso o filtro
# completo roda só na linha-título; no resto da mensagem valem apenas os sinais de estado do produto.
_NEGATIVOS_TEXTO_LIVRE = [
    "recondicionad", "open box", "openbox", "seminov", "semi-nov", "reembalad", "mostruario",
    "recertificad", "remanufaturad", "avaria", "tela quebrada", "com defeito",
]


def linha_55c6k(texto: str) -> Optional[str]:
    """Linha-título da 55C6K numa mensagem livre, ou None se a mensagem não é da 55C6K.

    Testa cada linha que cita C6K; se nenhuma passa sozinha (ex.: o tamanho está na linha de cima),
    tenta uma janela curta com a linha anterior e a seguinte, e devolve essa janela como título.
    """
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    if any(n in normaliza(texto) for n in _NEGATIVOS_TEXTO_LIVRE):
        return None
    com_c6k = [i for i, l in enumerate(linhas) if _RE_C6K.search(normaliza(l))]
    for i in com_c6k:
        if eh_55c6k(linhas[i]):
            return linhas[i]
    for i in com_c6k:
        janela = " ".join(linhas[max(0, i - 1): i + 2])
        if eh_55c6k(janela):
            return janela
    return None
