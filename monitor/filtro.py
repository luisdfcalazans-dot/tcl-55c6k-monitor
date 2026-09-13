"""Aceita SÓ a TCL 55C6K de 55 polegadas. Tudo o mais é descartado aqui."""

from __future__ import annotations

import re

from .util import sem_acentos

# "C6K" como token (não pega C6KS, C655, etc.)
_RE_C6K = re.compile(r"c6k(?![a-z0-9])", re.I)
# "55" isolado de outros dígitos: pega 55C6K, 55", 55 pol, 55 polegadas
_RE_55 = re.compile(r"(?<!\d)55(?!\d)")
# literal 55C6K (com ou sem espaço)
_RE_55C6K = re.compile(r"(?<!\d)55\s*c6k(?![a-z0-9])", re.I)
# outros tamanhos citados junto com polegadas/aspas/C6K
_RE_OUTRO_TAMANHO = re.compile(
    r"(?<!\d)(32|40|43|50|58|65|70|75|85|98|100|115)\s*(?:[\"”″]|\s?pol|\s?polegadas|\s?c6k)", re.I
)

# Palavras que indicam que NÃO é a TV sozinha, nova
_NEGATIVOS = [
    "combo", "soundbar", "sound bar", "kit ", "usad", "recondicionad", "open box", "openbox",
    "vitrine", "seminov", "semi-nov", "suporte", "capa ", "controle remoto", "pelicula",
    "cabo hdmi", "base ", "pedestal", "peca ", "peça ", "tela quebrada", "defeito",
    "c655", "c6ks", "c7k", "c8k", "c9k", "p7k", "p8k", "q6k", "q7k", "x955", "s5k", "p755",
]


def normaliza(texto: str) -> str:
    return sem_acentos(texto or "").lower().replace("″", '"').replace("”", '"')


def eh_55c6k(texto: str) -> bool:
    """True se o texto se refere à TCL 55C6K (55") e não a combos, outros tamanhos ou acessórios."""
    t = normaliza(texto)
    if not _RE_C6K.search(t):
        return False
    if any(n in t for n in _NEGATIVOS):
        return False
    if _RE_55C6K.search(t):
        return True
    if not _RE_55.search(t):
        return False
    if _RE_OUTRO_TAMANHO.search(t):
        return False
    return True


def motivo_rejeicao(texto: str) -> str:
    """Só para depuração: explica por que um título foi descartado."""
    t = normaliza(texto)
    if not _RE_C6K.search(t):
        return "sem C6K"
    neg = [n for n in _NEGATIVOS if n in t]
    if neg:
        return f"negativo: {neg[0].strip()}"
    if _RE_55C6K.search(t):
        return ""
    if not _RE_55.search(t):
        return "sem 55"
    if _RE_OUTRO_TAMANHO.search(t):
        return "outro tamanho"
    return ""
