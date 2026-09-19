"""Aceita SÓ a TCL 55C6K de 55 polegadas. Tudo o mais é descartado aqui."""

from __future__ import annotations

import re
from typing import NamedTuple, Optional

from .util import PISO_PRECO_TV, preco_postagem, sem_acentos, so_preco_abaixo_do_piso

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
    "cabo hdmi", "base ", "pedestal", "tela quebrada", "defeito",
    # peças que não aparecem no título da TV
    "barra de led", "barras de led", "fonte de alimenta", "sucata", "difusor",
    # estado do produto
    "reembalad", "mostruario", "recertificad", "remanufaturad", "avaria",
    *_MODELOS_OUTROS,
]
# "Peça já", "peça o seu": o verbo pedir, não a peça
_PECA = r"pecas?(?!\s+(?:ja|agora|o\s+seu|a\s+sua|aqui)\b)"
# estado do produto escrito de outros jeitos (anúncio de marketplace): tela trincada/rachada/quebrada, queimada,
# listras, sem imagem, não liga, para conserto/reparo, caixa aberta, embalagem danificada, exposição, grade B
_RE_ESTADO = [
    ("trincada", re.compile(r"\btrincad[oa]s?\b")),
    ("rachada", re.compile(r"\brachad[oa]s?\b")),
    ("quebrada", re.compile(r"\bquebrad[oa]s?\b")),
    ("queimada", re.compile(r"\bqueimad[oa]s?\b")),
    ("listras", re.compile(r"\blistras?\b|\blistrad[oa]s?\b")),
    ("sem imagem", re.compile(r"\bsem\s+(?:imagem|video)\b")),
    ("nao liga", re.compile(r"\bnao\s+(?:liga|funciona|acende)\b")),
    ("conserto", re.compile(r"\bconsertos?\b|\breparos?\b")),
    ("caixa aberta", re.compile(r"\b(?:caixa|embalagem)\s+(?:aberta|danificada|avariada|violada|amassada)\b")),
    ("danificada", re.compile(r"\bdanificad[oa]s?\b|\bamassad[oa]s?\b|\barranhad[oa]s?\b")),
    ("exposicao", re.compile(r"\bexposicao\b")),
    ("grade b", re.compile(r"\bgrade\s*:?\s*[bc]\b")),
]
# peças escritas de vários jeitos: "peça", "peças", "pecas" ("para retirada de peças"), "t-con", "cabo flat",
# "barra led", "par de pés", "tela/painel avulso"
_RE_NEGATIVOS = [
    # placa da TV ("Placa principal", "Placa T-con"); "placa de vídeo" é outro produto (rodapé dos canais)
    ("placa", re.compile(r"\bplacas?\b(?!\s+de\s+video)")),
    ("peca", re.compile(rf"\b{_PECA}\b")),
    ("t-con", re.compile(r"\bt-?con\b")),
    ("cabo flat", re.compile(r"\bcabos?\s+(?:flat|lvds)\b|\blvds\b")),
    ("barra de led", re.compile(r"\bbarras?\s+(?:de\s+)?leds?\b")),
    ("par de pes", re.compile(r"\bpar\s+de\s+(?:pes|pezinhos?)\b")),
    ("avulso", re.compile(r"\bavuls[oa]s?\b")),
    # "Tv Tcl 55c6k Alto Falante Original", "Backlight Tv Tcl 55c6k"; os recursos da TV ("Alto-Falantes Onkyo 2.1",
    # "com alto-falantes", "QD-Mini LED Backlight") saem antes, em _RE_RECURSO_SOM_LUZ
    ("alto-falante", re.compile(r"\balto[\s-]?falantes?\b")),
    ("backlight", re.compile(r"\bbacklight\b")),
    *_RE_ESTADO,
]
# alto-falantes e backlight como recurso da TV: "com alto-falantes", "Alto-Falantes Onkyo 2.1", "Mini LED Backlight"
_RE_RECURSO_SOM_LUZ = re.compile(
    r"(?:com|c/)\s+alto[\s-]?falantes?|"
    r"alto[\s-]?falantes?\s+(?:onkyo|dolby|jbl|harman|embutid\w*|integrad\w*|frontais|laterais|estereo|\d)|"
    r"(?:mini[\s-]?led|qd-?mini(?:[\s-]?led)?)\s+backlight|backlight\s+(?:(?:qd-?)?mini|full\s+array)"
)
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
    rf"pedestal|pedestais|{_PECA}|protetor(?:es)?|adesivos?|modulos?|lampadas?|fitas?|antenas?|"
    r"conversor(?:es)?|adaptador(?:es)?|receptor(?:es)?|tampas?|carcacas?|molduras?|sensor(?:es)?|"
    r"botao|botoes|chicotes?|alto[\s-]?falantes?|tv\s*box|racks?|parafusos?|lentes?|difusor(?:es|as?)?|"
    r"backlights?"
)
_NOME_TV = r"smart\s*tvs?(?!\s*box)|tvs?(?!\s*box)|televis(?:or|ores|ao|oes)|polegadas|mini\s*-?led|qled|qd-?mini|\d{2}\s*\""
# título que começa pelo nome da peça (inclui tela/display/painel, que no meio do título podem ser recurso, e o
# pé/pezinho da TV)
_RE_INICIO_ACESSORIO = re.compile(
    r"^[^a-z0-9]*(?:(?:novos?|novas?|original|originais|\d{1,2}\s*(?:x|un\w*)?)\s+)*"
    rf"({_ACESSORIOS}|telas?|displays?|painel|paineis|pes?|pezinhos?)(?![a-z0-9])"
)
# ... menos quando o começo é uma lista de recursos da TV antes do modelo: "Controle por voz, 144Hz e Mini LED: TCL
# 55C6K" (o controle vendido sozinho é "Controle por voz para TV ...", "Controle por voz original")
_RE_INICIO_RECURSOS = re.compile(
    r"^[^a-z0-9]*(?:controles?|comandos?)\s+(?:remotos?\s+)?(?:por|de|com|via)\s+(?:comando\s+de\s+)?voz"
    r"\s*(?:[,;:]|\s+e\s)"
)
# ... ou quando o título é "<recursos da TV>: <a TV>" (formato do Pelando/Promobit): "Tela Mini LED de 55 polegadas:
# TCL 55C6K por R$ 2.899", "Display 144Hz, Mini LED e Google TV: TCL 55C6K". A peça vendida sozinha não tem lista
# de recursos antes dos dois-pontos, ou tem "para TV", "compatível", "original", "reposição" nela.
_RE_RECURSO_TV = re.compile(r"\d{2,3}\s*hz|mini\s*-?led|qd-?mini|qled|oled|\b[48]k\b|uhd|google\s*tv|android\s*tv|hdr|"
                            r"dolby|hdmi|wi-?fi|bluetooth|imax|vrr|allm")
_RE_CABECA_DE_PECA = re.compile(r"\b(?:para|pra|p/)\s+(?:as?\s+|os?\s+)?(?:smart\s*)?tvs?\b|compativel|original|"
                                r"reposicao|substitui|\bpecas?\b|avuls")
_RE_TV_DEPOIS_DOIS_PONTOS = re.compile(r"^[^a-z0-9]*(?:smart\s*tvs?|tvs?|tcl|televisor)(?![a-z0-9])")


def _cabeca_de_recursos(t: str) -> bool:
    """True se t é "<recursos da TV>: <Smart TV/TV/TCL ...>" (ver acima)."""
    cabeca, sep, resto = t.partition(":")
    return bool(sep and _RE_RECURSO_TV.search(cabeca) and not _RE_CABECA_DE_PECA.search(cabeca)
                and _RE_TV_DEPOIS_DOIS_PONTOS.match(resto))


# 1º substantivo do título: se é peça/acessório, não é a TV ("Controle remoto para TV TCL 55C6K",
# "TCL 55C6K Controle Remoto"). "com controle remoto"/"c/ comando de voz" é recurso da TV e é pulado. Só a cabeça
# do título conta (até a 1ª vírgula): depois dela vem a lista de recursos ("..., sensor de luz ambiente, ...").
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
    if m and not _RE_INICIO_RECURSOS.search(t) and not _cabeca_de_recursos(t):
        return m.group(1)
    for r in _RE_ACESSORIO_FRASE:
        m = r.search(t_neg)
        if m:
            return m.group(1)
    for m in _RE_1O_NOME.finditer(t_neg.split(",", 1)[0]):
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
    t_neg = _RE_RECURSO_SOM_LUZ.sub(" ", t_neg)
    neg = [n for n in _NEGATIVOS if n in t_neg] + [n for n, r in _RE_NEGATIVOS if r.search(t_neg)]
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
#
# A mensagem é SEGMENTADA POR PRODUTO, linha a linha. Um "cabeçalho de produto" é uma linha que cita um código de
# modelo de TV (43S5K, 65C6K, 50P7K, 55P8K, 65QM8K), uma TV de outro tamanho (43", 65 polegadas, "TV de 43") ou o
# título de uma TV de outra marca ("Smart TV Samsung ..."). Cada linha pertence ao cabeçalho mais próximo ACIMA
# dela: o bloco da 55C6K vai do cabeçalho dela até o cabeçalho do próximo produto. Uma linha que cita a 55C6K e
# outro produto é cortada na menção do outro (o que vem antes fica com a 55C6K). As linhas antes do 1º cabeçalho
# só são da 55C6K se a mensagem não tem outro produto; o código de cupom delas vale para todos ("Use o Cupom: X"
# acima das linhas "55''" e "65''").
# Preço ANTES do nome ("💥 R$ 3.599 no Pix" / "Smart TV TCL 55C6K" / "💥 R$ 1.799 no Pix" / "Smart TV TCL 43S5K"):
# se a leitura de cima para baixo deixa algum cabeçalho sem preço e a de baixo para cima é coerente (todo cabeçalho
# sem preço na própria linha e com linha(s) de preço logo acima, e nenhuma linha de preço fora delas), vale a de
# baixo para cima. Se nenhuma das duas é coerente, a de cima para baixo decide (e o bloco sem preço descarta).
# Não são cabeçalho: tamanho em condição de cupom ("a partir de 50 polegadas", "acima de", "até", "de 50 a 85",
# "de 50\" ou mais", "50\" pra cima"); comparação ("R$ 700 mais barata que a 65C6K", "Metade do preço da 65C6K",
# "Sucessora da C755", "Mesmo processador da QM7K": a linha sai do bloco, que continua); linha de disponibilidade
# ("Disponível também em 65 e 75 polegadas") sem preço: encerra o bloco da 55C6K quando ele já tem preço (os de cima
# ficam) ou quando cita um tamanho MENOR que 55 (o preço de baixo pode ser o dela, mais barato: 🎯 falso); só com
# tamanhos maiores e antes do preço, é um aparte e o bloco continua (o preço de uma TV maior nunca daria 🎯 falso).
# Com o próprio preço ("Também em 65\" por R$ 4.999"), só ela sai (e a linha "ou R$ ... no Pix" que a continua).
# Linha de um produto que não é TV com o próprio preço ("💻 Notebook Acer Aspire 5 — R$ 2.499") sai do bloco.
# "Tela: 55\" | Modelo: 55C6K" / "Tela de 55\" (modelo 55C6K)" é linha da 55C6K, seja qual for a linha de cima.
# A mensagem só é descartada pela segmentação quando tem outro produto e o bloco da 55C6K não tem preço.

# Em qualquer linha da mensagem valem o estado do produto e o combo, como na main. O filtro completo de título roda
# só na linha-título: a descrição da própria TV usa palavras da lista de negativos ("Suporte a HDR10+", "controle
# remoto", "base", "pedestal de plástico", "Suporte de Parede: VESA 300x300").
_NEGATIVOS_TEXTO_LIVRE = [
    "usad", "recondicionad", "open box", "openbox", "vitrine", "seminov", "semi-nov", "tela quebrada", "defeito",
    "reembalad", "mostruario", "recertificad", "remanufaturad", "avaria",
    "combo", "soundbar", "sound bar", "kit ", "acompanha suporte",
]
# o estado escrito de outros jeitos (_RE_ESTADO dos títulos), linha a linha; "quebrado"/"queimado" só colados na
# tela/TV ("Preço quebrado", "Queimadão" não são o estado da TV)
_RE_ESTADO_TEXTO_LIVRE = re.compile(
    r"\btrincad[oa]s?\b|\brachad[oa]s?\b|\blistras?\s+na\s+tela\b|"
    r"\b(?:para|pra|p/)\s+(?:conserto|reparo)\b|\bretirada\s+de\s+pecas\b|\bsucata\b|"
    r"\b(?:caixa|embalagem)\s+(?:aberta|danificada|avariada|violada|amassada)\b|\bdanificad[oa]s?\b|"
    r"\bproduto\s+de\s+exposicao\b|\bgrade\s*:?\s*[bc]\b|"
    r"\b(?:tela|display|painel)\s+(?:\w+\s+)?(?:quebrad|queimad)[oa]s?\b|"
    r"\b(?:tv|televisao|televisor)\s+(?:quebrad|queimad)[oa]s?\b")

_UNIDADE = r"(?:\"|''|’’|pol\b|polegadas\b)"
# links e códigos de cupom não citam produto ("tidd.ly/45ab3cd", "cupom 50OFF100")
_RE_LINK = re.compile(r"https?://\S+|www\.\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+/\S*")
_RE_CUPOM_CODIGO = re.compile(r"(?:cupo(?:m|ns)|codigo|cod\.)\s*[:\-]?\s*[\"'“‘]?[a-z0-9]+")
# menções da 55C6K: o modelo, ou o tamanho 55 (só vale numa linha que não cita outro produto)
_RE_M55_MODELO = re.compile(r"(?<![a-z0-9])55\s?c6k(?![a-z0-9])")
_RE_M55_TAMANHO = re.compile(rf"(?<![a-z0-9.,$])55\s*{_UNIDADE}|\b(?:tvs?|tcl)\s+(?:de\s+)?55(?![\d.,a-z%])")
# menções de outro produto
# código de modelo com o tamanho colado (43S5K, 65C6K, 50P7K, 55P8K, 65QM8K, 50QNED70); com espaço ("55 HDR10+")
# não é código, nem medida ("VESA 100x100")
_RE_OUTRO_CODIGO = re.compile(rf"(?<![a-z0-9])(?:{_TAMANHOS}|55)(?!x\d)[a-z]{{1,5}}\d{{1,3}}[a-z]{{0,3}}(?![a-z0-9])"
                              rf"|(?<![a-z0-9])(?:{_TAMANHOS})\s+c6k(?![a-z0-9])")
# modelo TCL sem o tamanho: série (C, P, Q, QM, S, X, T, V) + dígito + K/L/KS (C7K, P8K, QM8K, S5K, P7L) ou
# C/P + 3 dígitos (C655, C855, P755). A C6K não conta.
_RE_OUTRO_MODELO = re.compile(r"(?<![a-z0-9])(?!c6k(?![a-z0-9]))(?:(?:c|p|q|qm|s|x|t|v)\d(?:ks|k|l)|[cp]\d{3}|x955)"
                              r"(?![a-z0-9])")
# outra tela: qualquer medida em polegadas de 20 a 119 que não seja 55 (TV de 43", monitor de 27"), ou "TV de 43"
_RE_OUTRO_TAM = re.compile(rf"(?<![a-z0-9.,$])(?!55(?!\d))(?:[2-9]\d|1[01]\d)\s*{_UNIDADE}|"
                           rf"\b(?:tvs?|televisor(?:es)?)\s+(?:(?:de|tcl)\s+)?(?:{_TAMANHOS})(?![\d.,a-z%])")
_QUALIFICADORES = (r"tcl|de|da|do|led|qled|oled|4k|8k|uhd|fhd|full\s+hd|hd|smart|mini\s*-?led|qd-?mini|crystal|neo|"
                   r"ultra|\d{2,3}\s*(?:\"|pol\w*)")
_MARCAS = r"samsung|lg|philips|aoc|philco|hisense|xiaomi|sony|panasonic|toshiba|multilaser|britania|roku|jvc|sharp"
# título de outra TV: a marca logo depois de "Smart TV" (só qualificadores no meio), no começo de uma frase da
# linha. "Melhor que muita TV da LG" / "TV que bate LG e Samsung" não contam
_RE_OUTRA_MARCA = re.compile(rf"(?:^|(?<=[|/•·;:(—–]))[^a-z]*(?:smart\s*)?(?:tvs?|televisor(?:es)?)\s+"
                             rf"(?:(?:{_QUALIFICADORES})\s+)*(?:{_MARCAS})\b")
# contexto logo antes da menção
_RE_ANTES_CONDICAO = re.compile(
    r"(?:a\s+partir\s+(?:de|das?|dos?)|acima\s+(?:de|das?|dos?)|\bate|maiores?\s+(?:que|de|do)|mais\s+de|entre|"
    r"\bde\s+\d{2,3}\s*(?:\"|pol\w*)?\s*(?:a|ate|-))\s*(?:(?:as?|os?)\s+)?(?:tvs?\s+(?:de\s+)?)?$")
# condição de cupom depois do tamanho: faixa ("de 50 a 85\"") ou "50\" ou mais", "50\" pra cima", "50\"+"
# medida de um móvel ("Cabe no rack de 60\"? Sim", "estante para TVs de 65\"") não é outra TV
_RE_ANTES_MOVEL = re.compile(r"\b(?:racks?|estantes?|mesas?|moveis|movel|paineis|cabem?)\b[^|•·;:!?]*$")
_RE_DEPOIS_FAIXA = re.compile(r"^\s*(?:\"|''|pol\w*)?\s*(?:(?:a|ate|-)\s*\d{2,3}\s*(?:\"|''|pol)|"
                              r"ou\s+(?:mais|maior(?:es)?|acima|superior(?:es)?)\b|(?:pra|para)\s+cima\b|"
                              r"em\s+diante\b|\+)")
# comparação: a menção vem numa frase comparativa ("mais barata que a 65C6K", "mais barata que muita TV de
# 65\"", "como uma TV de 65\"", "em relação à 65C6K", "Metade do preço da 65C6K", "Sucessora da C755", "Brilho
# superior ao da C755", "Mesmo processador da QM7K", "Custa menos que a 50P7K"); "que" sozinho não basta ("Oferta
# que vale: TCL 43S5K")
_RE_ANTES_COMPARACAO = re.compile(
    r"(?:(?:(?:mais|menos)\s+\w+|menor|maior|melhor|pior|igual)\s+(?:do\s+)?que|(?:mais|menos)\s+(?:do\s+)?que|"
    r"\bcomo|parece(?:\s+com)?|igual\s+(?:a|ao|as)|comparad[oa]s?\s+(?:a|com)|em\s+relacao\s+(?:a|ao|as|aos)|"
    r"\bvs\.?|versus|metade\s+do\s+preco|\bdobro|\bsucessor[a]?|\bantecessor[a]?|\bsubstitut[oa]|\bsubstitui|"
    r"\bherdeir[oa]|\bevolucao|\bsuperior|\binferior|\bmesm[oa]s?|\bconcorrente|\bconcorre\s+com|\brival|"
    r"\bsimilar|\bparecid[oa]|\bno\s+lugar)"
    r"\s+(?:[a-z]+\s+){0,3}$")
_RE_DISPONIBILIDADE = re.compile(
    r"\btambem\b|disponive(?:l|is)|outr[oa]s?\s+(?:tamanhos?|medidas|polegadas|versoes|opcoes|modelos)|"
    r"\bversao\b|\bversoes\b|\bopcao\b|\bopcoes\b|\b(?:tem|temos|ha)\s+(?:a|o|as|os)\s+de\b")
# linha de cupom e "TVs de N" no plural (as TVs em geral): "Cupom TV100 para TVs de 43\""
_RE_LINHA_CUPOM = re.compile(r"\bcupo(?:m|ns)\b|\bcodigo\b|\bcod\.")
_RE_TVS_GENERICO = re.compile(r"(?:^|\b)(?:tvs|televisores)\s+(?:(?:de|com|tcl)\s+)?(?=\d|$)")
# brinde da oferta ("Ganhe um Monitor 27\" de brinde"): aparte, não cabeçalho de outro produto
_RE_BRINDE = re.compile(r"\bbrindes?\b|\bde\s+presente\b")
# linha que continua a de cima ("💳 ou R$ 1.899 no Pix", "Pix: R$ 3.599")
_RE_CONTINUACAO = re.compile(r"^[^a-z0-9]*(?:ou\b|no\s+pix|pix\b|a\s+vista|no\s+boleto|boleto\b|no\s+cartao)")
# produto que não é TV no começo da linha ("💻 Notebook Acer Aspire 5 — R$ 2.499", "🪑 Cadeira Gamer — R$ 1.899")
_RE_OUTRO_ITEM = re.compile(
    r"^[^a-z0-9]*(?:\d{1,2}\s*[-.)]\s*)?(?:notebook|laptop|chromebook|macbook|celular|smartphone|iphone|ipad|tablet|"
    r"cadeira|mesa|escrivaninha|geladeira|refrigerador|freezer|fogao|cooktop|micro-?ondas|forno|air\s*fryer|"
    r"fritadeira|lavadora|lava\s+e\s+seca|maquina\s+de\s+lavar|secadora|ar[\s-]condicionado|ventilador|aspirador|"
    r"robo\s+aspirador|cafeteira|liquidificador|batedeira|panela|monitor|fones?|headset|headphone|mouse|teclado|"
    r"ssd|hd\s+externo|pendrive|console|playstation|ps[45]|xbox|nintendo|kindle|smartwatch|relogio|"
    r"caixa\s+de\s+som|impressora|roteador|camera|projetor|placa\s+de\s+video|tenis|perfume|bicicleta|colchao|"
    r"sofa|racks?|estantes?|home\s+theater)\b")
# separadores de frase numa linha, onde o corte entre dois produtos é feito
_RE_SEP_LINHA = re.compile(r"[|•·;,(]|\s/\s|\s[-—–]\s")
# linha de ficha técnica da própria TV: "Tela: 55\" | Modelo: 55C6K", "Tela de 55\" (modelo 55C6K)"
_RE_LINHA_FICHA = re.compile(rf"^[^a-z0-9]*(?:tela|display|tamanho)\s*(?:de|:|-)?\s*55\s*{_UNIDADE}")
_RE_PECA_AVULSA = re.compile(r"original|reposicao|substitui|compativel|\bpecas?\b|avuls|troca")
_RE_NOME_TV = re.compile(rf"(?<![a-z0-9])(?:{_NOME_TV})(?![a-z0-9])")


def _normaliza_com_mapa(linha: str) -> tuple[str, list[int]]:
    """Linha normalizada e, para cada caractere dela, a posição correspondente na linha original."""
    norm, mapa = [], []
    for i, c in enumerate(linha):
        n = normaliza(c)
        norm.append(n)
        mapa.extend([i] * len(n))
    mapa.append(len(linha))
    return "".join(norm), mapa


def _apaga(s: str, r: re.Pattern) -> str:
    """Troca por espaços (mantém as posições) o que casa com r."""
    return r.sub(lambda m: " " * len(m.group()), s)


def _mencoes(n: str) -> list[tuple[int, int, str, str]]:
    """Menções de produto numa linha normalizada: (início, fim, dono, espécie).
    dono: '55' (a 55C6K), 'outro' (cabeçalho de outro produto) ou 'comparacao'. espécie: modelo, tamanho, marca."""
    s = _apaga(_apaga(n, _RE_LINK), _RE_CUPOM_CODIGO)
    pares = [m.span() for m in _RE_PAR_BARRA.finditer(s)]
    brutas: list[tuple[int, int, str, str]] = [(a, b, "55", "modelo") for a, b in pares]
    for m in _RE_M55_MODELO.finditer(s):
        if not any(a <= m.start() < b for a, b in pares):
            brutas.append((m.start(), m.end(), "55", "modelo"))
    for r, especie in ((_RE_OUTRO_CODIGO, "modelo"), (_RE_OUTRO_MODELO, "modelo"), (_RE_OUTRO_TAM, "tamanho"),
                       (_RE_OUTRA_MARCA, "marca")):
        for m in r.finditer(s):
            if any(a <= m.start() < b for a, b in pares) or re.fullmatch(r"55\s?c6k", m.group()):
                continue
            if especie == "tamanho" and (_RE_ANTES_CONDICAO.search(s[max(0, m.start() - 40):m.start()])
                                         or _RE_DEPOIS_FAIXA.search(s[m.end():])
                                         or _RE_ANTES_MOVEL.search(s[max(0, m.start() - 40):m.start()])
                                         or (_RE_LINHA_CUPOM.search(n) and "r$" not in n and (
                                             _RE_TVS_GENERICO.match(m.group())
                                             or _RE_TVS_GENERICO.search(s[max(0, m.start() - 16):m.start()])))):
                # "Cupom válido para TVs a partir de 50 polegadas", "de 50 a 85\"", "de 50\" ou mais" e, numa linha
                # de cupom sem valor, "TVs de 43\"" (as TVs em geral, no plural: condição do cupom, não outro
                # produto; "TVs de 43\" com cupom: R$ 1.799" continua sendo outro produto com o próprio preço)
                continue
            if especie == "modelo" and re.fullmatch(rf"(?:{_TAMANHOS})\s*c6k", m.group()):
                especie = "tamanho"  # 65C6K: a mesma TV em outro tamanho
            brutas.append((m.start(), m.end(), "outro", especie))
    if not any(d == "outro" for _, _, d, _ in brutas):
        brutas += [(m.start(), m.end(), "55", "tamanho") for m in _RE_M55_TAMANHO.finditer(s)]
    out = []
    for a, b, dono, especie in sorted(brutas):
        if out and a < out[-1][1]:
            continue  # sobreposta a uma menção anterior ("tv tcl 50" e "50 p7l")
        if _RE_ANTES_COMPARACAO.search(s[max(0, a - 40):a]):
            dono = "comparacao"
        out.append((a, b, dono, especie))
    return out


def _corte(s: str, ini: int, fim: int) -> int:
    """Onde cortar entre o fim de uma menção (ini) e o começo da seguinte (fim): no último separador de frase
    entre as duas, ou no começo da seguinte."""
    ultimo = None
    for m in _RE_SEP_LINHA.finditer(s, ini, fim):
        ultimo = m.start()
    return fim if ultimo is None else ultimo


def _tem_preco(t: str) -> bool:
    return preco_postagem(t, PISO_PRECO_TV) is not None


def _tamanhos(n: str, mencoes: list[tuple[int, int, str, str]]) -> list[int]:
    """Tamanhos em polegadas citados pelas menções de tamanho (65", "65 polegadas", "TV de 43", 65C6K)."""
    out = []
    for a, b, _, especie in mencoes:
        m = re.search(r"\d{2,3}", n[a:b]) if especie == "tamanho" else None
        if m:
            out.append(int(m.group()))
    return out


class _Linha(NamedTuple):
    pedacos: list[tuple[str, str]]  # (dono, texto original)
    cabecalho: bool                 # cita um produto que abre bloco (a 55C6K ou outro)
    continuacao: bool               # continua a linha de cima ("ou R$ ... no Pix", "Pix: R$ ...")


def _segmenta_linhas(linhas: list[str]) -> list[_Linha]:
    """Leitura de cima para baixo. Para cada linha, os pedaços (dono, texto original). Donos: '55' (bloco da 55C6K),
    'outro' (bloco de outro produto), 'disp' (depois de uma linha de disponibilidade que encerra o bloco: "Também
    tem a de 43 polegadas"), 'fora' (comparação, aparte de disponibilidade, disponibilidade ou item com o próprio
    preço, e a linha que continua estes dois) e 'antes' (antes do 1º cabeçalho)."""
    dono_atual = None           # dono das linhas sem menção
    dest_anterior = "antes"     # destino do fim da linha anterior (para a linha de continuação: "ou R$ ... no Pix")
    preco_55 = False            # o bloco da 55C6K (ou o começo da mensagem) já tem preço
    out = []
    for linha in linhas:
        n, mapa = _normaliza_com_mapa(linha)
        mencoes = _mencoes(n)
        continuacao = bool(_RE_CONTINUACAO.search(n))
        disponibilidade = bool(_RE_DISPONIBILIDADE.search(n))
        disp_na_linha_55 = any(m[2] == "55" for m in mencoes) and disponibilidade
        if disp_na_linha_55:
            # "Smart TV TCL 55C6K (também em 65\" e 75\")": os outros tamanhos na linha da 55C6K não são cabeçalho
            mencoes = [(a, b, "comparacao" if d == "outro" and e == "tamanho" else d, e) for a, b, d, e in mencoes]
        if _RE_BRINDE.search(n):
            # "Monitor LG 27\" de brinde": o brinde é um aparte da oferta, não outro produto à venda
            mencoes = [(a, b, "comparacao" if d == "outro" else d, e) for a, b, d, e in mencoes]
        cabecalhos = [m for m in mencoes if m[2] != "comparacao"]
        pedacos: list[tuple[str, str]] = []
        proximo = None              # destino da linha de continuação seguinte, se não for o do fim desta linha
        cabecalho = False
        if not mencoes:
            if _RE_OUTRO_ITEM.search(n) and _tem_preco(linha):
                pedacos, proximo = [("fora", linha)], "fora"     # "💻 Notebook Acer Aspire 5 — R$ 2.499"
            else:
                dest = dest_anterior if continuacao else (dono_atual or "antes")
                pedacos = [(dest, linha)]
        elif not any(m[2] == "55" for m in mencoes):
            if not cabecalhos:
                # comparação ("R$ 700 mais barata que a 65C6K"): a linha sai, o bloco continua (inclusive na
                # linha de continuação seguinte)
                pedacos, proximo = [("fora", linha)], (dono_atual or "antes")
            elif disponibilidade and all(m[3] == "tamanho" for m in cabecalhos):
                if _tem_preco(linha):
                    pedacos = [("fora", linha)]          # "Também em 65\" por R$ 4.999": só ela sai
                elif (not preco_55 and dono_atual in (None, "55")
                      and all(t > 55 for t in _tamanhos(n, cabecalhos))):
                    # "Também disponível em 65\" e 75\"" antes do preço: aparte, o bloco continua
                    pedacos, proximo = [("fora", linha)], (dono_atual or "antes")
                else:
                    dono_atual = "disp"                  # "Também tem a de 43": encerra o bloco
                    pedacos = [("disp", linha)]
            else:
                dono_atual = "outro"                     # cabeçalho de outro produto
                pedacos = [("outro", linha)]
                cabecalho = True
        else:
            # linha com a 55C6K: corta nas menções de outro produto (o que vem antes fica com a 55C6K)
            pos = 0
            dono = next((m[2] for m in cabecalhos), "55")
            fim_ant = 0
            for a, b, d, _ in mencoes:
                novo = "fora" if d == "comparacao" else d
                if novo != dono:
                    c = a if novo == "fora" else _corte(n, fim_ant, a)
                    if c > pos:
                        pedacos.append((dono, linha[mapa[pos]:mapa[c]]))
                    pos, dono = c, novo
                fim_ant = b
            pedacos.append((dono, linha[mapa[pos]:]))
            dono_atual = cabecalhos[-1][2] if cabecalhos else dono_atual
            cabecalho = bool(cabecalhos)
            if pedacos[-1][0] == "fora":
                # a continuação de "... | também em 43\" por R$ 1.999" é do outro tamanho; a de uma comparação, não
                com_preco = _tem_preco(pedacos[-1][1])
                proximo = "fora" if disp_na_linha_55 and com_preco else dono_atual
        dest_anterior = proximo or pedacos[-1][0]
        if any(d in ("55", "antes") and _tem_preco(t) for d, t in pedacos):
            preco_55 = True
        out.append(_Linha(pedacos, cabecalho, continuacao))
    return out


def _segmenta(linhas: list[str]) -> list[list[tuple[str, str]]]:
    """Os pedaços (dono, texto original) de cada linha, na leitura de cima para baixo (ver _segmenta_linhas)."""
    return [l.pedacos for l in _segmenta_linhas(linhas)]


def _texto_do_bloco(linha: _Linha) -> str:
    return " ".join(t for d, t in linha.pedacos if d not in ("fora", "disp"))


def _le_de_baixo(ls: list[_Linha]) -> Optional[list[list[tuple[str, str]]]]:
    """Releitura de uma mensagem com o preço ANTES do nome de cada produto, ou None se ela não é desse formato.

    Só quando a leitura de cima para baixo é incoerente (algum cabeçalho fica sem preço até o próximo) e a de baixo
    para cima é coerente: nenhum cabeçalho tem preço na própria linha, todo cabeçalho tem logo acima dele uma
    sequência de linhas de preço (que não começa por uma linha de continuação, "ou R$ ..."), e não sobra linha de
    preço fora dessas sequências. Cada sequência passa ao dono do cabeçalho de baixo; o resto fica como estava."""
    cabs = [i for i, l in enumerate(ls) if l.cabecalho]
    if len(cabs) < 2:
        return None
    precos = [_tem_preco(_texto_do_bloco(l)) for l in ls]
    fins = cabs[1:] + [len(ls)]
    if all(any(precos[j] for j in range(c, f)) for c, f in zip(cabs, fins)):
        return None  # de cima para baixo todo cabeçalho tem preço
    corridas: dict[int, range] = {}
    for c in cabs:
        if precos[c]:
            return None  # cabeçalho com o próprio preço: não é o formato "preço antes do nome"
        j = c
        while j > 0 and not ls[j - 1].cabecalho and precos[j - 1]:
            j -= 1
        while j < c and ls[j].continuacao:
            j += 1
        if j == c:
            return None
        corridas[c] = range(j, c)
    nas_corridas = {j for r in corridas.values() for j in r}
    if any(precos[j] and not ls[j].cabecalho and j not in nas_corridas for j in range(len(ls))):
        return None  # preço solto depois do último cabeçalho ou entre um cabeçalho e a sequência seguinte
    novo = [list(l.pedacos) for l in ls]
    for c, r in corridas.items():
        dono = next((d for d, _ in ls[c].pedacos if d in ("55", "outro")), None)
        if dono is None:
            return None
        for j in r:
            novo[j] = [(d if d in ("fora", "disp") else dono, t) for d, t in novo[j]]
    return novo


def _titulo(linhas: list[str], segs: list[list[tuple[str, str]]]) -> Optional[str]:
    """Linha-título da 55C6K (original), ou None se nenhuma linha da mensagem é a 55C6K."""
    norm = [normaliza(l) for l in linhas]
    for i, n in enumerate(norm):
        if not _RE_C6K.search(n):
            continue
        parte = normaliza(" ".join(t for d, t in segs[i] if d in ("55", "antes")))
        if not _RE_C6K.search(parte):
            continue
        # ficha técnica: "Tela: 55\" | Modelo: 55C6K", "Tela de 55\" (modelo 55C6K)" (não a tela de reposição)
        if _RE_LINHA_FICHA.search(n) and _RE_55C6K.search(n) and not _RE_PECA_AVULSA.search(n) and (
                "modelo" in n or (i > 0 and _RE_NOME_TV.search(norm[i - 1]))):
            return f"{linhas[i - 1]} {linhas[i]}" if i > 0 and not _RE_C6K.search(norm[i - 1]) else linhas[i]
        motivo = _motivo(parte)
        if motivo == "":
            return linhas[i]
        if motivo == "sem 55":
            # "Modelo C6K": o tamanho está numa linha da própria 55C6K ('Smart TV TCL 55"', 'Tela de 55"')
            com_55 = [j for j, sj in enumerate(segs) if any(d in ("55", "antes") for d, _ in sj)
                      and _RE_M55_TAMANHO.search(normaliza(" ".join(t for d, t in sj if d in ("55", "antes"))))]
            if com_55:
                j = min(com_55, key=lambda k: abs(k - i))
                return " ".join(linhas[k] for k in sorted({i, j}))
    return None


def extrai_55c6k(texto: str) -> Optional[tuple[str, str, str]]:
    """(título, trecho, preâmbulo) da 55C6K numa mensagem livre, ou None se a mensagem não serve.

    None quando: alguma linha cita o estado do produto (usada, vitrine, defeito, tela trincada...) ou um combo;
    nenhuma linha é a 55C6K pelo filtro de título; a mensagem tem outro produto e o bloco da 55C6K não tem preço,
    ou tem preço antes do 1º produto sem leitura coerente (nem de cima para baixo nem de baixo para cima); ou o
    único preço anunciado fica abaixo de R$ 1.500 (peça/acessório, não a TV).
    trecho: as linhas (ou pedaços de linha) do bloco da 55C6K. É dele que saem preço, parcelado e cupom.
    preâmbulo: numa mensagem com outro produto, as linhas antes do 1º cabeçalho (fora do trecho); só o código de
    cupom delas vale, e só quando o trecho não tem um.
    """
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    if not linhas:
        return None
    tudo = " ".join(normaliza(l) for l in linhas)
    if any(n in tudo for n in _NEGATIVOS_TEXTO_LIVRE):
        return None
    if any(_RE_ESTADO_TEXTO_LIVRE.search(normaliza(l)) for l in linhas):
        return None  # tela trincada, para conserto, caixa aberta... (linha a linha)
    ls = _segmenta_linhas(linhas)
    segs = [l.pedacos for l in ls]
    if any(d == "outro" for sj in segs for d, _ in sj):
        relido = _le_de_baixo(ls)
        if relido is not None:
            segs = relido
        elif (any(all(d == "antes" for d, _ in l.pedacos) and _tem_preco(_texto_do_bloco(l)) for l in ls)
              and not all(_tem_preco(_texto_do_bloco(l)) for l in ls if l.cabecalho)):
            # preço antes do 1º produto, mas a leitura de baixo para cima não fecha e os produtos não trazem o
            # preço na própria linha: não dá para saber de quem é cada preço ("R$ 3.599" / 55C6K / "ou R$ 3.799"
            # / "R$ 1.799" / 43S5K / "ou R$ 1.899" daria o 1.799 da 43S5K)
            return None
    titulo = _titulo(linhas, segs)
    if not titulo:
        return None
    donos_vistos = {d for sj in segs for d, _ in sj}
    # as linhas antes do 1º cabeçalho só são da 55C6K se a mensagem não tem outro produto
    donos = ("55",) if "outro" in donos_vistos else ("55", "antes")
    trecho, preambulo = [], []
    for sj in segs:
        partes = [t.strip() for d, t in sj if d in donos and t.strip()]
        if partes:
            trecho.append(" ".join(partes))
        if "antes" not in donos:
            partes = [t.strip() for d, t in sj if d == "antes" and t.strip()]
            if partes:
                preambulo.append(" ".join(partes))
    trecho = "\n".join(trecho)
    if donos_vistos & {"outro", "disp"} and not _tem_preco(trecho):
        return None  # o preço da 55C6K pode estar no bloco de outro produto: sem preço, nada de alerta
    if so_preco_abaixo_do_piso(trecho, PISO_PRECO_TV):
        return None  # "Tela de 55\" (modelo 55C6K) R$ 1.499": não é a TV
    return titulo, trecho, "\n".join(preambulo)


def bloco_55c6k(texto: str) -> Optional[tuple[str, str]]:
    """(título, trecho) da 55C6K numa mensagem livre, ou None se a mensagem não serve (ver extrai_55c6k)."""
    achado = extrai_55c6k(texto)
    return achado[:2] if achado else None


def linha_55c6k(texto: str) -> Optional[str]:
    """Linha-título da 55C6K numa mensagem livre, ou None se a mensagem não é da 55C6K."""
    achado = extrai_55c6k(texto)
    return achado[0] if achado else None
