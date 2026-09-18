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

# Palavras que indicam que NÃO é a TV sozinha, nova. "display" e "para TV" aparecem no título da própria TV
# ("Display 144Hz", "ideal para TV e games"), por isso tela/display/painel só contam no começo do título
# (_RE_INICIO_ACESSORIO). "controle remoto" é negativo como na main, menos o recurso da TV ("com controle remoto",
# "controle remoto por voz"), que _RE_CONTROLE_RECURSO tira antes.
_NEGATIVOS = [
    "combo", "soundbar", "sound bar", "kit ", "usad", "recondicionad", "open box", "openbox",
    "vitrine", "seminov", "semi-nov", "suporte", "capa ", "pelicula", "controle remoto", "controles remotos",
    "cabo hdmi", "base ", "pedestal", "peca ", "tela quebrada", "defeito",
    # peças que não aparecem no título da TV
    "barra de led", "barras de led", "fonte de alimenta", "placa",
    # estado do produto
    "reembalad", "mostruario", "recertificad", "remanufaturad", "avaria",
    *_MODELOS_OUTROS,
]
# "com controle remoto" / "controle (remoto) por|de|com voz" é recurso da TV, não o controle vendido sozinho.
# No começo do título ("Controle por voz para TV ...") quem decide é _RE_INICIO_ACESSORIO, que olha o texto original.
_RE_CONTROLE_RECURSO = re.compile(
    r"(?:^|\s)(?:com|c/)\s+controles?\s+remotos?(?![a-z0-9])|"
    r"\bcontroles?\s+(?:remotos?\s+)?(?:com|por|de|via)\s+(?:comando\s+de\s+)?voz\b"
)

# "com suporte a HDR10+ / Dolby Vision / Wi-Fi / 4K / Bluetooth / HDMI 2.1" é recurso da TV, não o acessório.
# Só recursos técnicos conhecidos são perdoados: "suporte à parede", "suporte articulado" e "kit suporte"
# continuam barrados pelo negativo "suporte". "TV + Suporte ..." é combo, nunca recurso ("HDR10+ Suporte a" é).
_RECURSOS = (
    r"hdr|dolby|vision|atmos|dts|imax|hlg|wi-?fi|wireless|4k|8k|uhd|full\s*hd|bluetooth|hdmi|e?arc\b|usb|"
    r"vrr|allm|freesync|g-?sync|\d{2,3}\s*hz|google|android|alexa|airplay|chromecast|assistente|"
    r"comandos?\s+de\s+voz|controle\s+(?:por|de)\s+voz|voz\b|jogos|games?\b|modo\s+(?:jogo|game|filme|cinema)|"
    r"streaming|apps?\b|aplicativos|(?:multiplos\s+|diversos\s+|varios\s+)?formatos"
)
_RE_SUPORTE_A_RECURSO = re.compile(
    rf"(?<!\s\+\s)(?<!\s\+)\bsuporte\s+(?:(?:a|ao|aos|as|para|pra|de|do|com)\s+)?(?=(?:{_RECURSOS}))"
)

# Substantivos de peça/acessório e da própria TV
_ACESSORIOS = (
    r"controles?|comandos?|barras?|placas?|fontes?|suportes?|capas?|cabos?|peliculas?|kits?|bases?|"
    r"pedestal|pedestais|pecas?|protetor(?:es)?|adesivos?|modulos?|lampadas?|fitas?|antenas?|"
    r"conversor(?:es)?|adaptador(?:es)?|receptor(?:es)?|tampas?|carcacas?|molduras?|sensor(?:es)?|"
    r"botao|botoes|chicotes?|alto-?falantes?|tv\s*box|racks?"
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


def _acessorio(t: str, t_neg: str) -> str:
    """t normalizado (t_neg: sem os recursos da TV). Nome da peça/acessório se o título é de um, senão ''."""
    # o começo do título olha o texto original: "Suporte 4K para TV" / "Suporte USB 55C6K" são o suporte
    m = _RE_INICIO_ACESSORIO.search(t)
    if m:
        return m.group(1)
    for r in _RE_ACESSORIO_FRASE:
        m = r.search(t_neg)
        if m:
            return m.group(1)
    for m in _RE_1O_NOME.finditer(t_neg):
        if m.group(1):          # "com controle remoto": recurso da TV, segue procurando
            continue
        if m.group(2) and m.group(2).startswith(("controle", "comando")) and _RE_RECURSO_VOZ.match(t_neg, m.end()):
            continue            # "controle por voz": recurso da TV
        return m.group(2) or ""  # o 1º substantivo decide: peça (group 2) ou a TV ('')
    return ""


def _motivo(t: str) -> str:
    """t já normalizado. '' = é a 55C6K; senão o motivo da recusa."""
    if not _RE_C6K.search(t):
        return "sem C6K"
    t_neg = _RE_CONTROLE_RECURSO.sub(" ", _RE_SUPORTE_A_RECURSO.sub(" ", t))
    neg = [n for n in _NEGATIVOS if n in t_neg]
    if neg:
        return f"negativo: {neg[0].strip()}"
    ac = _acessorio(t, t_neg)
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

# O filtro completo de título roda só na linha-título: a descrição da própria TV usa palavras da lista de negativos
# ("Suporte a HDR10+", "controle remoto", "base", "pedestal de plástico", "Suporte de Parede: VESA 300x300").
# Em qualquer linha da mensagem valem o estado do produto e o combo, como na main.
_NEGATIVOS_TEXTO_LIVRE = [
    "usad", "recondicionad", "open box", "openbox", "vitrine", "seminov", "semi-nov", "tela quebrada", "defeito",
    "reembalad", "mostruario", "recertificad", "remanufaturad", "avaria",
    "combo", "soundbar", "sound bar", "kit ", "acompanha suporte",
]
# "55" como tamanho, para a linha do "C6K" que não diz o tamanho (não pega "R$ 55,00" nem "cupom 55OFF")
_RE_55_TAMANHO = re.compile(r'(?<![\d.,])55\s*(?:"|pol\b|polegadas)|\b(?:tv|tcl)\s+55(?![\d.,])')
# linha do "C6K" que começa pelo tamanho da tela ("📺 Tela de 55\" (modelo 55C6K)"): vale junto com a linha de cima
# quando ela é o título da TV ("🔥 Smart TV TCL QD-Mini LED"); sozinha é a tela de reposição
_RE_TELA_DE_55 = re.compile(r'^[^a-z0-9]*(?:tela|display)\s+de\s+55\s*(?:"|pol)')
_RE_TITULO_TV = re.compile(r"^[^a-z0-9]*(?:smart\s*tvs?|tvs?|televisor)(?![a-z0-9])")

# Outro produto: outro tamanho ou modelo, código de modelo de TV (43S5K, 50QNED70, 65P7K) ou o título de outra TV
# ("Smart TV Samsung Crystal", "Smart TV TCL 50 P7L"). Links e códigos de cupom saem antes ("tidd.ly/45ab3cd").
# Marca ou categoria soltas na frase não contam ("Melhor que muita TV da LG", "serve como monitor").
_RE_LINK = re.compile(r"https?://\S+|www\.\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+/\S*")
_RE_CUPOM_CODIGO = re.compile(r"cupom\s*[:\-]?\s*\S+")
_RE_CODIGO_MODELO = re.compile(rf"(?<![a-z0-9])(?:{_TAMANHOS}|55)[a-z]{{1,6}}\d[a-z0-9]{{0,6}}(?![a-z0-9])")
# título de outra TV: a marca ou o tamanho logo depois de "Smart TV" (só qualificadores no meio), para uma frase
# como "TV que bate LG e Samsung" não contar
_RE_OUTRA_TV = re.compile(
    r"^[^a-z0-9]*(?:smart\s*tvs?|tvs?|televisor(?:es)?)\s+"
    r"(?:(?:tcl|de|led|qled|oled|4k|8k|uhd|fhd|full\s+hd|hd|smart|mini\s*-?led|qd-?mini|crystal|neo|ultra|"
    r"\d{2,3}\s*(?:\"|pol\w*))\s+)*"
    r"(?:(?:samsung|lg|philips|aoc|philco|hisense|xiaomi|sony|panasonic|toshiba|multilaser|britania)\b|"
    rf"(?:{_TAMANHOS})(?![\d.,a-z%]))"
)
# pedaços de uma mesma linha ("55C6K: R$ 3.599 | Samsung 43\": R$ 1.799")
_RE_SEP = re.compile(r"\s*[|;•·]\s*")
# valor que pode ser o preço de um produto (parcelas ficam abaixo)
_RE_VALOR = re.compile(r"r\$\s?\d{1,3}(?:\.\d{3})+|r\$\s?\d{4,}")


def _cita_outro_produto(s: str) -> bool:
    """s: pedaço normalizado de uma linha. True se cita um produto que não é a 55C6K."""
    s = _RE_CUPOM_CODIGO.sub(" ", _RE_LINK.sub(" ", s))
    if not _RE_C6K.search(s) and _RE_OUTRA_TV.search(s):
        return True
    s = _RE_55C6K.sub(" ", _RE_PAR_BARRA.sub(" ", s))  # o par "55C6K e 65C6K" é a própria postagem
    return bool(_RE_OUTRO_C6K.search(s) or _RE_OUTRO_TAMANHO.search(s) or _RE_CODIGO_MODELO.search(s)
                or any(m in s for m in _MODELOS_OUTROS))


def bloco_55c6k(texto: str) -> Optional[tuple[str, str]]:
    """(título, trecho) da 55C6K numa mensagem livre, ou None se a mensagem não serve.

    None quando: alguma linha cita o estado do produto (usada, vitrine, defeito...) ou um combo; nenhuma linha
    passa no filtro de título; ou um pedaço de linha cita outro produto SEM trazer o preço dele (o preço vem
    nas linhas seguintes e não dá para saber de quem é: a mensagem inteira sai, como na main).
    trecho: a mensagem sem os pedaços de linha que citam outro produto junto com o próprio preço
    ("Também em 65\" por R$ 4.999", "43S5K: R$ 1.799"). É dele que saem preço, parcelado e cupom.
    """
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    norm = [normaliza(l) for l in linhas]
    if any(n in " ".join(norm) for n in _NEGATIVOS_TEXTO_LIVRE):
        return None
    titulo = None
    for i, l in enumerate(norm):
        if not _RE_C6K.search(l):
            continue
        ini = i - 1 if i > 0 and _RE_TELA_DE_55.match(l) and _RE_TITULO_TV.match(norm[i - 1]) else i
        l = " ".join(norm[ini:i + 1])
        motivo = _motivo(l)
        if motivo == "":
            titulo = " ".join(linhas[ini:i + 1])
        elif motivo == "sem 55" and not _cita_outro_produto(l):
            # "4K C6K Google TV": o tamanho está em outra linha que não fala de outro produto
            com_55 = [j for j, n in enumerate(norm) if _RE_55_TAMANHO.search(n) and not _cita_outro_produto(n)]
            if com_55:
                j = min(com_55, key=lambda k: abs(k - i))
                titulo = " ".join(linhas[k] for k in sorted({i, j}))
        if titulo:
            break
    if not titulo:
        return None
    trecho = []
    for linha in linhas:
        pedacos = []
        for p in _RE_SEP.split(linha):
            n = normaliza(p)
            if not n.strip():
                continue
            if _cita_outro_produto(n):
                if not _RE_VALOR.search(n):
                    return None  # outro produto com o preço nas linhas de baixo
                continue         # o valor deste pedaço é do outro produto
            pedacos.append(p)
        if pedacos:
            trecho.append(" | ".join(pedacos))
    return titulo, "\n".join(trecho)


def linha_55c6k(texto: str) -> Optional[str]:
    """Linha-título da 55C6K numa mensagem livre, ou None se a mensagem não é da 55C6K."""
    achado = bloco_55c6k(texto)
    return achado[0] if achado else None
