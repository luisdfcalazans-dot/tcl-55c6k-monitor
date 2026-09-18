"""Aceita SÓ a TCL 55C6K de 55 polegadas. Tudo o mais é descartado aqui."""

from __future__ import annotations

import re
from typing import Optional

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
    "barra de led", "barras de led", "fonte de alimenta", "backlight", "sucata",
    # estado do produto
    "reembalad", "mostruario", "recertificad", "remanufaturad", "avaria",
    *_MODELOS_OUTROS,
]
# peças escritas de vários jeitos: "peça", "peças", "pecas" ("para retirada de peças"), "t-con", "cabo flat",
# "barra led", "par de pés", "tela/painel avulso"
_RE_NEGATIVOS = [
    # placa da TV ("Placa principal", "Placa T-con"); "placa de vídeo" é outro produto (rodapé dos canais)
    ("placa", re.compile(r"\bplacas?\b(?!\s+de\s+video)")),
    ("peca", re.compile(r"\bpecas?\b")),
    ("t-con", re.compile(r"\bt-?con\b")),
    ("cabo flat", re.compile(r"\bcabos?\s+(?:flat|lvds)\b|\blvds\b")),
    ("barra de led", re.compile(r"\bbarras?\s+(?:de\s+)?leds?\b")),
    ("par de pes", re.compile(r"\bpar\s+de\s+(?:pes|pezinhos?)\b")),
    ("avulso", re.compile(r"\bavuls[oa]s?\b")),
    # "Alto Falante Tv Tcl 55c6k Original"; "com alto-falantes Onkyo" é recurso da TV
    ("alto-falante", re.compile(r"(?<!\bcom\s)(?<!\bc/\s)\balto[\s-]?falantes?\b")),
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
    r"botao|botoes|chicotes?|alto[\s-]?falantes?|tv\s*box|racks?|parafusos?"
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
    if m and not _RE_INICIO_RECURSOS.search(t):
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
# só são da 55C6K se a mensagem não tem outro produto.
# Não são cabeçalho: tamanho em condição de cupom ("a partir de 50 polegadas", "acima de", "até", "de 50 a 85");
# comparação ("R$ 700 mais barata que a 65C6K": a linha sai do bloco, que continua); linha de disponibilidade
# ("Disponível também em 65 e 75 polegadas"): sem preço, encerra o bloco da 55C6K (os preços acima ficam); com o
# próprio preço ("Também em 65\" por R$ 4.999"), só ela sai (e a linha "ou R$ ... no Pix" que a continua).
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

_UNIDADE = r"(?:\"|''|’’|pol\b|polegadas\b)"
# links e códigos de cupom não citam produto ("tidd.ly/45ab3cd", "cupom 50OFF100")
_RE_LINK = re.compile(r"https?://\S+|www\.\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+/\S*")
_RE_CUPOM_CODIGO = re.compile(r"(?:cupo(?:m|ns)|codigo|cod\.)\s*[:\-]?\s*[\"'“‘]?[a-z0-9]+")
# menções da 55C6K: o modelo, ou o tamanho 55 (só vale numa linha que não cita outro produto)
_RE_M55_MODELO = re.compile(r"(?<![a-z0-9])55\s?c6k(?![a-z0-9])")
_RE_M55_TAMANHO = re.compile(rf"(?<![a-z0-9.,$])55\s*{_UNIDADE}|\b(?:tvs?|tcl)\s+(?:de\s+)?55(?![\d.,a-z%])")
# menções de outro produto
# código de modelo com o tamanho colado (43S5K, 65C6K, 50P7K, 55P8K, 65QM8K, 50QNED70); com espaço ("55 HDR10+")
# não é código
_RE_OUTRO_CODIGO = re.compile(rf"(?<![a-z0-9])(?:{_TAMANHOS}|55)[a-z]{{1,5}}\d{{1,3}}[a-z]{{0,3}}(?![a-z0-9])"
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
_RE_DEPOIS_FAIXA = re.compile(r"^\s*(?:\"|''|pol\w*)?\s*(?:a|ate|-)\s*\d{2,3}\s*(?:\"|''|pol)")
# comparação: a menção vem numa frase comparativa ("mais barata que a 65C6K", "mais barata que muita TV de
# 65\"", "como uma TV de 65\"", "em relação à 65C6K"); "que" sozinho não basta ("Oferta que vale: TCL 43S5K")
_RE_ANTES_COMPARACAO = re.compile(
    r"(?:(?:(?:mais|menos)\s+\w+|menor|maior|melhor|pior|igual)\s+(?:do\s+)?que|\bcomo|parece(?:\s+com)?|"
    r"igual\s+(?:a|ao|as)|comparad[oa]s?\s+(?:a|com)|em\s+relacao\s+(?:a|ao|as|aos)|\bvs\.?|versus)"
    r"\s+(?:[a-z]+\s+){0,3}$")
_RE_DISPONIBILIDADE = re.compile(
    r"\btambem\b|disponive(?:l|is)|outr[oa]s?\s+(?:tamanhos?|medidas|polegadas|versoes|opcoes|modelos)|"
    r"\bversao\b|\bversoes\b|\bopcao\b|\bopcoes\b|\b(?:tem|temos|ha)\s+(?:a|o|as|os)\s+de\b")
# linha que continua a de cima ("💳 ou R$ 1.899 no Pix", "Pix: R$ 3.599")
_RE_CONTINUACAO = re.compile(r"^[^a-z0-9]*(?:ou\b|no\s+pix|pix\b|a\s+vista|no\s+boleto|boleto\b|no\s+cartao)")
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
                                         or _RE_DEPOIS_FAIXA.search(s[m.end():])):
                continue  # "Cupom válido para TVs a partir de 50 polegadas", "de 50 a 85\""
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


def _segmenta(linhas: list[str]) -> list[list[tuple[str, str]]]:
    """Para cada linha, os pedaços (dono, texto original). Donos: '55' (bloco da 55C6K), 'outro' (bloco de outro
    produto), 'disp' (depois de uma linha de disponibilidade sem preço: "Também em 65 e 75 polegadas"), 'fora'
    (comparação, ou disponibilidade com o próprio preço, e a linha que a continua) e 'antes' (antes do 1º
    cabeçalho)."""
    dono_atual = None           # dono das linhas sem menção
    dest_anterior = "antes"     # destino do fim da linha anterior (para a linha de continuação: "ou R$ ... no Pix")
    out = []
    for linha in linhas:
        n, mapa = _normaliza_com_mapa(linha)
        mencoes = _mencoes(n)
        disponibilidade = bool(_RE_DISPONIBILIDADE.search(n))
        disp_na_linha_55 = any(m[2] == "55" for m in mencoes) and disponibilidade
        if disp_na_linha_55:
            # "Smart TV TCL 55C6K (também em 65\" e 75\")": os outros tamanhos na linha da 55C6K não são cabeçalho
            mencoes = [(a, b, "comparacao" if d == "outro" and e == "tamanho" else d, e) for a, b, d, e in mencoes]
        cabecalhos = [m for m in mencoes if m[2] != "comparacao"]
        pedacos: list[tuple[str, str]] = []
        proximo = None              # destino da linha de continuação seguinte, se não for o do fim desta linha
        if not mencoes:
            dest = dest_anterior if _RE_CONTINUACAO.search(n) else (dono_atual or "antes")
            pedacos = [(dest, linha)]
        elif not any(m[2] == "55" for m in mencoes):
            if not cabecalhos:
                # comparação ("R$ 700 mais barata que a 65C6K"): a linha sai, o bloco continua (inclusive na
                # linha de continuação seguinte)
                pedacos, proximo = [("fora", linha)], (dono_atual or "antes")
            elif disponibilidade and all(m[3] == "tamanho" for m in cabecalhos):
                if preco_postagem(linha, PISO_PRECO_TV) is not None:
                    pedacos = [("fora", linha)]          # "Também em 65\" por R$ 4.999": só ela sai
                else:
                    dono_atual = "disp"                  # "Disponível também em 65 e 75": encerra o bloco
                    pedacos = [("disp", linha)]
            else:
                dono_atual = "outro"                     # cabeçalho de outro produto
                pedacos = [("outro", linha)]
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
            if pedacos[-1][0] == "fora":
                # a continuação de "... | também em 43\" por R$ 1.999" é do outro tamanho; a de uma comparação, não
                com_preco = preco_postagem(pedacos[-1][1], PISO_PRECO_TV) is not None
                proximo = "fora" if disp_na_linha_55 and com_preco else dono_atual
        dest_anterior = proximo or pedacos[-1][0]
        out.append(pedacos)
    return out


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


def bloco_55c6k(texto: str) -> Optional[tuple[str, str]]:
    """(título, trecho) da 55C6K numa mensagem livre, ou None se a mensagem não serve.

    None quando: alguma linha cita o estado do produto (usada, vitrine, defeito...) ou um combo; nenhuma linha é a
    55C6K pelo filtro de título; a mensagem tem outro produto e o bloco da 55C6K não tem preço; ou o único preço
    anunciado fica abaixo de R$ 1.500 (peça/acessório, não a TV).
    trecho: as linhas (ou pedaços de linha) do bloco da 55C6K. É dele que saem preço, parcelado e cupom.
    """
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    if not linhas:
        return None
    tudo = " ".join(normaliza(l) for l in linhas)
    if any(n in tudo for n in _NEGATIVOS_TEXTO_LIVRE):
        return None
    segs = _segmenta(linhas)
    titulo = _titulo(linhas, segs)
    if not titulo:
        return None
    donos_vistos = {d for sj in segs for d, _ in sj}
    # as linhas antes do 1º cabeçalho só são da 55C6K se a mensagem não tem outro produto
    donos = ("55",) if "outro" in donos_vistos else ("55", "antes")
    trecho = []
    for sj in segs:
        partes = [t.strip() for d, t in sj if d in donos and t.strip()]
        if partes:
            trecho.append(" ".join(partes))
    trecho = "\n".join(trecho)
    if donos_vistos & {"outro", "disp"} and preco_postagem(trecho, PISO_PRECO_TV) is None:
        return None  # o preço da 55C6K pode estar no bloco de outro produto: sem preço, nada de alerta
    if so_preco_abaixo_do_piso(trecho, PISO_PRECO_TV):
        return None  # "Tela de 55\" (modelo 55C6K) R$ 1.499": não é a TV
    return titulo, trecho


def linha_55c6k(texto: str) -> Optional[str]:
    """Linha-título da 55C6K numa mensagem livre, ou None se a mensagem não é da 55C6K."""
    achado = bloco_55c6k(texto)
    return achado[0] if achado else None
