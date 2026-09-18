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

# outros modelos (TCL e parecidos) que aparecem junto nas buscas e nas postagens
_MODELOS_OUTROS = ["c655", "c6ks", "c7k", "c8k", "c9k", "p7k", "p8k", "q6k", "q7k", "x955", "s5k", "p755"]

# Palavras que indicam que NÃO é a TV sozinha, nova. Só entra aqui o que não aparece no título da própria TV:
# "controle remoto", "display" e "para TV" aparecem ("com Controle Remoto por Voz", "Display 144Hz"), por isso
# peça/acessório é reconhecido pelo substantivo do produto (_RE_INICIO_ACESSORIO e _RE_1O_NOME), não em qualquer lugar.
_NEGATIVOS = [
    "combo", "soundbar", "sound bar", "kit ", "usad", "recondicionad", "open box", "openbox",
    "vitrine", "seminov", "semi-nov", "suporte", "capa ", "pelicula",
    "cabo hdmi", "base ", "pedestal", "peca ", "tela quebrada", "defeito",
    # peças que não aparecem no título da TV
    "barra de led", "barras de led", "fonte de alimenta", "placa",
    # estado do produto
    "reembalad", "mostruario", "recertificad", "remanufaturad", "avaria",
    *_MODELOS_OUTROS,
]

# "com suporte a HDR10+ / Dolby Vision / Wi-Fi / 4K / Bluetooth / HDMI 2.1" é recurso da TV, não o acessório.
# Só recursos técnicos conhecidos são perdoados: "suporte à parede", "suporte articulado" e "kit suporte"
# continuam barrados pelo negativo "suporte".
_RECURSOS = (
    r"hdr|dolby|vision|atmos|dts|imax|hlg|wi-?fi|wireless|4k|8k|uhd|full\s*hd|bluetooth|hdmi|e?arc\b|usb|"
    r"vrr|allm|freesync|g-?sync|\d{2,3}\s*hz|google|android|alexa|airplay|chromecast|assistente|"
    r"comandos?\s+de\s+voz|controle\s+(?:por|de)\s+voz|voz\b|jogos|games?\b|modo\s+(?:jogo|game|filme|cinema)|"
    r"streaming|apps?\b|aplicativos|(?:multiplos\s+|diversos\s+|varios\s+)?formatos"
)
_RE_SUPORTE_A_RECURSO = re.compile(
    rf"\bsuporte\s+(?:(?:a|ao|aos|as|para|pra|de|do|com)\s+)?(?=(?:{_RECURSOS}))"
)

# Substantivos de peça/acessório e da própria TV
_ACESSORIOS = (
    r"controles?|comandos?|barras?|placas?|fontes?|suportes?|capas?|cabos?|peliculas?|kits?|bases?|"
    r"pedestal|pedestais|pecas?|protetor(?:es)?|adesivos?|modulos?|lampadas?|fitas?|antenas?|"
    r"conversor(?:es)?|adaptador(?:es)?|receptor(?:es)?|tampas?|carcacas?|molduras?|sensor(?:es)?|"
    r"botao|botoes|chicotes?|alto-?falantes?|tv\s*box"
)
_NOME_TV = r"smart\s*tvs?(?!\s*box)|tvs?(?!\s*box)|televis(?:or|ores|ao|oes)|polegadas|mini\s*-?led|qled|qd-?mini|\d{2}\s*\""
# título que começa pelo nome da peça (inclui tela/display/painel, que no meio do título podem ser recurso)
_RE_INICIO_ACESSORIO = re.compile(
    r"^[^a-z0-9]*(?:(?:novos?|novas?|original|originais|\d{1,2}\s*(?:x|un\w*)?)\s+)*"
    rf"({_ACESSORIOS}|telas?|displays?|painel|paineis)(?![a-z0-9])"
)
# 1º substantivo do título: se é peça/acessório, não é a TV ("Controle remoto para TV TCL 55C6K",
# "TCL 55C6K Controle Remoto"). "com controle remoto"/"c/ comando de voz" é recurso da TV e é pulado.
_RE_1O_NOME = re.compile(rf"(?<![a-z0-9])(?:(com|c/)\s+)?(?:({_ACESSORIOS})|{_NOME_TV})(?![a-z0-9])")
# "controle por voz" / "comando de voz" no meio do título é recurso da TV (no começo, _RE_INICIO_ACESSORIO barra)
_RE_RECURSO_VOZ = re.compile(r"\s+(?:remoto\s+)?(?:por|de|com)\s+voz\b")
_RE_ACESSORIO_FRASE = [
    # "Para TV TCL 55C6K ..." no começo do título
    re.compile(r"^[^a-z0-9]*((?:para|pra|p/)\s*(?:as?\s+|os?\s+)?(?:smart\s*)?tvs?)\b"),
    # "tela/display/painel ... para TV"
    re.compile(r"\b((?:telas?|displays?|painel|paineis)\b.{0,40}?\b(?:para|pra|p/)\s*(?:as?\s+)?(?:smart\s*)?tvs?)\b"),
    re.compile(r"\b(compativel\s+(?:com\s+)?(?:as?\s+|os?\s+)?(?:smart\s*)?(?:tvs?|televis\w*|tcl))\b"),
]


def normaliza(texto: str) -> str:
    return sem_acentos(texto or "").lower().replace("″", '"').replace("”", '"')


def _acessorio(t: str) -> str:
    """t normalizado. Nome da peça/acessório se o título é de um, senão ''."""
    m = _RE_INICIO_ACESSORIO.search(t)
    if m:
        return m.group(1)
    for r in _RE_ACESSORIO_FRASE:
        m = r.search(t)
        if m:
            return m.group(1)
    for m in _RE_1O_NOME.finditer(t):
        if m.group(1):          # "com controle remoto": recurso da TV, segue procurando
            continue
        if m.group(2) and m.group(2).startswith(("controle", "comando")) and _RE_RECURSO_VOZ.match(t, m.end()):
            continue            # "controle por voz": recurso da TV
        return m.group(2) or ""  # o 1º substantivo decide: peça (group 2) ou a TV ('')
    return ""


def _motivo(t: str) -> str:
    """t já normalizado. '' = é a 55C6K; senão o motivo da recusa."""
    if not _RE_C6K.search(t):
        return "sem C6K"
    t_neg = _RE_SUPORTE_A_RECURSO.sub(" ", t)
    neg = [n for n in _NEGATIVOS if n in t_neg]
    if neg:
        return f"negativo: {neg[0].strip()}"
    ac = _acessorio(t_neg)
    if ac:
        return f"acessório: {ac.strip()}"
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


# ---------------------------------------------------------------- mensagem livre (Telegram)

# A descrição da própria TV usa palavras da lista de negativos ("suporte a HDR10+", "base", "pedestal de
# plástico"). Por isso o filtro completo roda só na linha-título; no resto da mensagem valem apenas os sinais
# de estado do produto.
_NEGATIVOS_TEXTO_LIVRE = [
    "recondicionad", "open box", "openbox", "seminov", "semi-nov", "reembalad", "mostruario",
    "recertificad", "remanufaturad", "avaria", "tela quebrada", "com defeito",
]
# quantas linhas em volta do "C6K" procurar o tamanho quando ele está em outra linha
_RAIO_JANELA = 3
# "55" como tamanho numa janela da mensagem (não pega "R$ 55,00" nem "cupom 55OFF")
_RE_55_JANELA = re.compile(r'(?<![\d.,])55\s*(?:"|pol\b|polegadas)|\b(?:tv|tcl)\s+55(?![\d.,])')

# Outro produto numa postagem com várias ofertas: outro modelo/tamanho, outra marca de TV ou outra categoria.
_RE_CODIGO_MODELO = re.compile(r"(?<![a-z0-9])\d{2,3}[a-z]{1,5}\d[a-z0-9]{0,6}(?![a-z0-9])")  # 43S5K, 50QNED70
_RE_OUTRA_MARCA_TV = re.compile(
    r"\b(?:samsung|lg|philips|aoc|philco|hisense|xiaomi|sony|panasonic|toshiba|multilaser|britania)\b")
_RE_OUTRA_CATEGORIA = re.compile(
    r"\b(?:soundbar|notebook|celular|smartphone|iphone|geladeira|refrigerador|fogao|micro-?ondas|air\s*fryer|"
    r"fritadeira|aspirador|ventilador|ar[\s-]condicionado|lavadora|lava\s+e\s+seca|cafeteira|tablet|ipad|"
    r"fone\s+de\s+ouvido|headset|caixa\s+de\s+som|projetor|monitor)\b")
# título de outra TV com o tamanho sem aspas ("Smart TV TCL 50 P7L: R$ 2.069"); só em linha sem "C6K"
_RE_OUTRA_TV_TITULO = re.compile(
    rf"^[^a-z0-9]*(?:[a-z]+\s*\|\s*)?(?:smart\s*tv|tv|televisor)\b.*?(?<![\d.,$])(?:{_TAMANHOS})(?![\d.,a-z%])"
)
# separadores de trechos numa mesma linha ("55C6K: R$ 3.599 | Samsung 43\": R$ 1.799")
_RE_SEP_TRECHO = re.compile(r"\s*[|;•·]\s*|\s+[/–—-]\s+")


def _cita_outro_produto(t: str) -> bool:
    """t normalizado. True se cita um produto que não é a 55C6K."""
    if not _RE_C6K.search(t) and _RE_OUTRA_TV_TITULO.search(t):
        return True
    t = _RE_55C6K.sub(" ", _RE_PAR_BARRA.sub(" ", t))
    return bool(_RE_OUTRO_C6K.search(t) or _RE_OUTRO_TAMANHO.search(t) or any(m in t for m in _MODELOS_OUTROS)
                or _RE_CODIGO_MODELO.search(t) or _RE_OUTRA_MARCA_TV.search(t) or _RE_OUTRA_CATEGORIA.search(t))


def _trecho_da_linha(linha: str) -> str:
    """Linha-título que também cita outro produto: só o pedaço da 55C6K (até o próximo produto)."""
    partes = [p for p in _RE_SEP_TRECHO.split(linha) if p.strip()]
    norm = [normaliza(p) for p in partes]
    k = next((j for j, p in enumerate(norm) if _RE_C6K.search(p)), None)
    if k is None:
        return linha
    fim = next((j for j in range(k + 1, len(partes)) if _cita_outro_produto(norm[j])), len(partes))
    return " | ".join(partes[k:fim])


def bloco_55c6k(texto: str) -> Optional[tuple[str, str]]:
    """(título, trecho) da 55C6K numa mensagem livre, ou None se a mensagem não é da 55C6K.

    título: a linha que cita a 55C6K e passa no filtro. Se ela não diz o tamanho ("4K C6K Google TV"), procura
    o 55 numa janela de ~3 linhas em volta (a mensagem inteira se ela só fala de um produto), sem atravessar
    a linha de outro produto.
    trecho: de onde saem preço, parcelado e cupom. Mensagem só da 55C6K: a mensagem toda, começando pelo título
    (as linhas de cima vão para o fim). Mensagem com vários produtos: do título até a linha do próximo produto,
    para o preço de outro produto nunca virar o preço da 55C6K.
    """
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    norm = [normaliza(l) for l in linhas]
    tudo = " ".join(norm)
    if any(n in tudo for n in _NEGATIVOS_TEXTO_LIVRE):
        return None
    outros = {i for i, l in enumerate(norm) if _cita_outro_produto(l)}
    for i, l in enumerate(norm):
        if not _RE_C6K.search(l):
            continue
        motivo = _motivo(l)
        if motivo == "":
            ini, titulo = i, linhas[i]
        elif motivo == "sem 55":
            antes = [j for j in outros if j < i]
            depois = [j for j in outros if j > i]
            if outros - {i}:
                lo = max(i - _RAIO_JANELA, max(antes) + 1 if antes else 0)
                hi = min(i + _RAIO_JANELA + 1, min(depois) if depois else len(linhas))
            else:
                lo, hi = 0, len(linhas)
            janela = " ".join(norm[lo:hi])
            if _RE_OUTRO_TAMANHO.search(janela) or _RE_OUTRO_C6K.search(janela):
                continue
            com_55 = [j for j in range(lo, hi) if _RE_55_JANELA.search(norm[j])]
            if not com_55:
                continue
            j55 = min(com_55, key=lambda j: abs(j - i))
            ini = min(i, j55)
            titulo = " ".join(linhas[ini: max(i, j55) + 1])
        else:
            continue
        if not (outros - set(range(ini, i + 1))) and i not in outros:
            trecho = "\n".join(linhas[ini:] + linhas[:ini])
        else:
            fim = next((j for j in range(i + 1, len(linhas)) if j in outros), len(linhas))
            trecho = "\n".join(linhas[ini:i] + [_trecho_da_linha(linhas[i])] + linhas[i + 1: fim])
        return titulo, trecho
    return None


def linha_55c6k(texto: str) -> Optional[str]:
    """Linha-título da 55C6K numa mensagem livre, ou None se a mensagem não é da 55C6K."""
    achado = bloco_55c6k(texto)
    return achado[0] if achado else None
