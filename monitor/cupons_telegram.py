"""Cupons citados nos posts dos canais públicos do Telegram (pedido de 08/11/2026: "faça a varredura também nos cupons
que aparecem nas mensagens dos grupos do telegram").

Só funções puras: a fonte (monitor/sources/telegram_public.py) lê a prévia t.me/s/<canal>, e cada mensagem passa por
citacoes_do_post(); consolida() junta as citações de todos os canais num Cupom por (loja, CÓDIGO, valor), que vai para
a lista diária "🎟️ Cupons ativos" (monitor/lista_cupons.py) e NUNCA para o alerta de "Novo cupom aplicável"
(config.FONTES_CUPOM_SO_LISTA: seria um alerta a cada post).

Padrões (levantados nas prévias de 08/11/2026):

1. linha "valor + mínimo + código(s)": '🏷 R$ 785 OFF em R$ 4200: AFFNOV11', '🎟R$800 OFF em R$4000: IFP1ZYZM',
   '🔹R$ 16 off acima de R$ 80: ISKANDAR1 |IFPQWR8M | AEMEGA1', '🏷 25% OFF , Limite de R$ 500 OFF : MUITOBARATO',
   '🎟️ R$ 670 OFF em R$ 4.200 - Cupom: AFFNOV22'. Códigos alternativos (" ou ", ",", "/", "|") viram cupons separados com
   o mesmo título;
2. código na linha de baixo: 'R$785 de desconto em R$4200' / 'AFFNOV11'; '💸 R$ 670 OFF acima de R$ 4200' /
   '🎟️ Cupom: AFFNOV22';
3. código antes do valor: 'AFFNOV04 R$ 125 OFF acima de R$ 740', '📝 TAMOSJUNTO 👉 10% OFF';
4. post de produto: '🎟 Cupom: AFFNOV11 + 740 moedas no app', 'R$ 228,55 com cupom:' / 'JOGOS0811' (título: "cupom
   citado no post de <produto> por R$ X"; as moedas e o "cupom da loja" ficam de fora);
5. cabeçalho de seção: a loja ('🚨 Cupons novos AliExpress', '#Kabum') e a validade ('Válidos de 10/11 até 12/11',
   '(11/11 À 12/11)', '⏰ Vai até 18.11.2026') valem para as linhas de baixo até o próximo cabeçalho; data escrita só
   depois de todos os códigos (rodapé) vale para o post inteiro;
6. esgotado: 'O cupom IFP43VOM esgotou', '❌Cupom Esgotado❌', o código riscado (<s>); "quem resgatou" vira restrição.

Código: 4 a 20 letras/dígitos, com pelo menos 1 dígito, ou logo depois de "Cupom:"/":" (ou dentro de <code>), em
maiúsculas; nunca uma palavra da lista negra (CUPOM, PIX, APP, OFF, LINK, MOEDAS, nome de loja...). A loja do código:
prefixo de código da plataforma (AFFNOV9, AEMEGA8, AESUPER5, IFPxxxxx = AliExpress) > cabeçalho da seção > hashtag >
domínio do link (s.click.aliexpress, meli.la, s.shopee, amzn.to...). Sem loja conhecida, o código fica de fora.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from . import config
from .models import Cupom
from .util import _NAO_E_CUPOM, _RE_MODELO_TV, sem_acentos

# ---- loja ----
# trecho do link -> loja (encurtadores e domínios das próprias lojas). Genéricos (cupom.cc, seuhardware.com/s/, cutt.ly,
# encurtou.com, linktr.ee, tidd.ly) não dizem a loja: valem o cabeçalho e a hashtag
_LOJA_DO_LINK = (
    ("aliexpress.", "AliExpress"), ("meli.la/", "Mercado Livre"), ("mercadolivre.com", "Mercado Livre"),
    ("shopee.com", "Shopee"), ("amzn.to/", "Amazon"), ("amazon.com", "Amazon"), ("link.amazon", "Amazon"),
    ("magazineluiza.com", "Magazine Luiza"), ("magazinevoce.com", "Magazine Luiza"), ("-magalu", "Magazine Luiza"),
    ("kabum", "KaBuM!"),
)
# nome da loja num cabeçalho ("Cupons renovados Shopee", "#Kabum", "🏪 Loja: #AliExpress")
_LOJAS_NO_CABECALHO = (
    (re.compile(r"ali\s?express"), "AliExpress"), (re.compile(r"mercado\s*livre|\bmeli\b|\bml\b"), "Mercado Livre"),
    (re.compile(r"shopee"), "Shopee"), (re.compile(r"magalu|magazine\s*luiza"), "Magazine Luiza"),
    (re.compile(r"amazon"), "Amazon"), (re.compile(r"kabum"), "KaBuM!"), (re.compile(r"casas\s*bahia"), "Casas Bahia"),
    (re.compile(r"americanas"), "Americanas"), (re.compile(r"netshoes"), "Netshoes"), (re.compile(r"nuuvem"), "Nuuvem"),
    (re.compile(r"fast\s*shop"), "Fast Shop"),
)
# códigos da própria plataforma (valem em qualquer loja dentro dela): AFFNOV11, AEMEGA8, AESUPER5, IFP1ZYZM
_PREFIXOS_PLATAFORMA = (
    (re.compile(r"AFF(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\d{1,2}|AEMEGA\d{1,2}|AESUPER\d{1,2}|"
                r"IFP[A-Z0-9]{5}"), "AliExpress"),
)

# ---- código ----
_NAO_CODIGO = {sem_acentos(p).upper() for p in _NAO_E_CUPOM} | {
    "CUPOM", "CUPONS", "QUENTINHOS", "DESCRI", "ANTES", "PIX", "APP", "OFF", "BRASIL", "MAGALU", "LINK", "LINKS",
    "NERDIMPORTADOS", "AMAZON", "SHOPEE", "KABUM", "ALIEXPRESS", "LIVRE", "MELI", "MOEDA", "MOEDAS", "ESGOTOU",
    "ESGOTADOS", "RENOVADOS", "ESPECIAIS", "EVENTO", "RESGATADO", "LIMITE", "ACIMA", "PARTIR", "PEDIDOS", "COMPRAS",
    "VALIDOS", "VALIDA", "ANUNCIO", "SELECIONE", "SEGUINDO", "COMPRA", "MINIMA", "REAIS", "AQUI", "CLIQUE", "PARCELADO",
    "JUROS", "VEZES", "NOVOS", "COMPRADORES", "LOJA", "LOJAS", "OFICIAL", "SITE", "TODO",
}
# "825GB", "120Hz", "4K": medida de produto, não código
_RE_MEDIDA = re.compile(r"\d+(?:[.,]\d+)?(?:GB|TB|MB|HZ|MM|CM|ML|KG|G|W|V|X|K|P|MAH|POL|LITROS?|L)")
_RE_TOKEN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|[,/|+]")
_CONECTIVOS = {"OU", "E", "OR"}

# ---- valor ----
_N = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
# "R$ 785 OFF em R$ 4200", "R$785 de desconto em R$4200", "R$40 off em pedidos acima de R$250", "25% OFF , Limite de
# R$ 500 OFF", "10% OFF acima de R$79, limite R$30", "15% OFF em R$ 500, Limite de R$ 100 OFF"
_RE_VALOR = re.compile(
    r"(?:R\$\s?" + _N + r"\s*(?:OFF\b|de\s+desconto\b)|(?<![\d,.])(\d{1,2}(?:[.,]\d)?)\s*%\s*(?:OFF\b|de\s+desconto\b))"
    r"(?:\s*,?\s*(?:em|acima\s+de|a\s+partir\s+de|(?:em|para|nas)\s+(?:pedidos|compras)\s+(?:acima\s+de|a\s+partir\s+de|"
    r"de))\s*R\$\s?" + _N + r")?"
    r"(?:\s*,?\s*(?:limite(?:\s+de)?|limitado\s+a|at[eé]|desconto\s+m[aá]x(?:imo)?\.?:?)\s*R\$\s?" + _N
    + r"(?:\s*OFF\b)?)?",
    re.I)
# "Compra mínima: R$149 | Desconto máx: R$200" (Iskandar, ML em 3 linhas)
_RE_MINIMO_SOLTO = re.compile(r"compra\s+m[ií]nima:?\s*R\$\s?" + _N, re.I)
_RE_TETO_SOLTO = re.compile(r"desconto\s+m[aá]x(?:imo)?\.?:?\s*R\$\s?" + _N, re.I)
_RE_PRECO = re.compile(r"R\$\s?" + _N)
# o que vem antes dos códigos depois do valor: "- Cupom:", ": ", "Use o cupom"
_RE_ANTES_DOS_CODIGOS = re.compile(r"^[\s:\-–—=>👉➡️]*(?:(?:use|usem|resgate)\s+(?:o\s+)?)?(?:cupo(?:m|ns)\b\s*"
                                   r"(?:no\s+app\b)?\s*)?[:\-–—]?\s*", re.I)
# marcador de cupom num post de produto: "🎟 Cupom: X", "Use cupom: X", "com cupom X", "Usem o cupom: X"
_RE_MARCADOR = re.compile(r"(?<![a-z])cupo(?:m|ns)\b", re.I)

# ---- status e escopo ----
_RE_ESGOTADO = re.compile(r"esgot|totalmente\s+resgatad|\bacabou\b|❌")
_RE_RESGATOU = re.compile(r"quem\s+(?:ja\s+)?resgatou")
_RE_SELECAO = re.compile(r"valido\s+na\s+lista|(?:itens|produtos)\s+selecionados|"
                         r"ative\s+em\s+algum\s+produto")
_RE_CABECALHO = re.compile(r"cupo|#|\bloja\s*:")
_RE_DATA = re.compile(r"(?<![\d$])(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?![\d,]|\s*x\b)")
_RE_LOJA_DO_CUPOM = re.compile(r"cupo(?:m|ns)\s+da\s+loja", re.I)


@dataclass
class Citacao:
    """Um código citado num post: o que o post diz dele."""

    loja: str
    codigo: str
    titulo: str
    canal: str
    post: str                       # "canal/123" (o link é https://t.me/<post>)
    publicado: Optional[str] = None  # ISO (horário de Brasília)
    tipo: str = "lista"             # "lista" (linha com valor) | "produto" (post de produto)
    chave_valor: str = "post"       # "R785-4200", "P10-149-200"; "post" sem valor
    regra: str = ""
    validade: Optional[str] = None  # AAAA-MM-DD (fim do dia)
    inicio: Optional[str] = None    # AAAA-MM-DD (começo do dia)
    esgotado: bool = False
    resgatou: bool = False
    linha: str = ""                 # a linha do post, como veio


# ---------------------------------------------------------------------------------------------------------------------
def _norm(s: str) -> str:
    return sem_acentos(s or "").lower()


def loja_do_codigo(codigo: str) -> Optional[str]:
    """AliExpress para os códigos da própria plataforma (AFFNOV11, AEMEGA8, AESUPER5, IFP1ZYZM); None nos outros."""
    cod = (codigo or "").upper()
    for rx, loja in _PREFIXOS_PLATAFORMA:
        if rx.fullmatch(cod):
            return loja
    return None


def loja_dos_links(links: Iterable[str]) -> Optional[str]:
    """A loja dos links do post, quando todos os links conhecidos são de uma loja só; None sem link conhecido ou com
    links de lojas diferentes."""
    achadas = set()
    for link in links or []:
        lk = (link or "").lower()
        for chave, loja in _LOJA_DO_LINK:
            if chave in lk:
                achadas.add(loja)
                break
    return achadas.pop() if len(achadas) == 1 else None


def loja_do_cabecalho(linha: str) -> Optional[str]:
    """A loja de uma linha de cabeçalho ("🚨 Cupons novos AliExpress", "#Kabum", "🏪 Loja: #AliExpress"); None se a
    linha não é cabeçalho (sem "cupom"/"#"/"Loja:", ou com valor de desconto)."""
    n = _norm(linha)
    if not _RE_CABECALHO.search(n) or _RE_VALOR.search(linha):
        return None
    for rx, loja in _LOJAS_NO_CABECALHO:
        if rx.search(n):
            return loja
    return None


def _hashtag_loja(texto: str) -> Optional[str]:
    """A loja da hashtag do post ("#Kabum", "#AliExpress")."""
    for m in re.finditer(r"#(\w+)", _norm(texto)):
        for rx, loja in _LOJAS_NO_CABECALHO:
            if rx.search(m.group(1)):
                return loja
    return None


def _codigo(tok: str, explicito: bool, em_code: set[str]) -> Optional[str]:
    """O código em maiúsculas, se `tok` pode ser um. Com dígito: maiúsculas, minúsculas ou misturado começando por letra
    ("peperaio1", "Pelando8"). Sem dígito: só em maiúsculas e com sinal explícito (logo depois de "Cupom:"/":" ou
    dentro de <code>)."""
    t = tok.strip("-")
    up = t.upper()
    if not 4 <= len(t) <= 20 or not re.search(r"[A-Z]", up) or up in _NAO_CODIGO:
        return None
    if _RE_MODELO_TV.fullmatch(up) or _RE_MEDIDA.fullmatch(up):
        return None
    if re.search(r"\d", t):
        return up if (t.isupper() or t[0].isalpha()) else None
    if up in em_code:
        return up
    return up if explicito and t.isupper() and len(t) >= 5 else None


def _codigos_em(texto: str, explicito: bool, em_code: set[str]) -> tuple[list[tuple[str, bool]], bool]:
    """Os códigos no começo de `texto`: [(código, veio depois de '+')] e se o texto acabou nos códigos (só sobrou emoji
    e pontuação). Para na primeira palavra que não é código nem conectivo ("+ 740 moedas no app", "+ Cupom da loja")."""
    out: list[tuple[str, bool]] = []
    mais = False
    for m in _RE_TOKEN.finditer(texto):
        tok = m.group()
        if tok in ",/|":
            continue
        if tok == "+":
            mais = True
            continue
        if tok.upper() in _CONECTIVOS and out:
            continue
        cod = _codigo(tok, explicito, em_code)
        if cod is None:
            return out, False
        if cod not in (c for c, _m in out):
            out.append((cod, mais))
        mais = False
    return out, True


def _so_codigos(linha: str, explicito: bool, em_code: set[str], parcial: bool = False) -> list[tuple[str, bool]]:
    """Os códigos de uma linha que só tem código(s) ("AFFNOV11", "IFPR2XGX IFPE6TPU", "🎟️ Cupom: AFFNOV22",
    "🏷 Cupom: FF5E8II49K", "🎟 CUPOM: COMPRAHOJE"); [] se a linha tem outra coisa. `parcial` (a linha de cima terminou
    em "com cupom:"): os códigos do começo bastam ("TAMOSJUNTO + CUPOM DE R$ 200 OFF DA LOJA")."""
    if _RE_VALOR.search(linha) and not parcial:
        return []
    m = re.match(r"^[^\w]*(?:(?:use|usem|resgate)\s+(?:o\s+)?)?cupo(?:m|ns)\b\s*(?:no\s+app\b)?\s*:", linha, re.I)
    if m:
        linha, explicito = linha[m.end():], True
    elif not parcial and re.search(r"[A-Za-z]{2,}", linha) and _RE_MARCADOR.search(linha):
        return []
    cods, tudo = _codigos_em(re.sub(r"^[^\w]+", "", linha), explicito, em_code)
    return cods if cods and (tudo or parcial) else []


def _valor_da_linha(m: re.Match) -> tuple[str, Optional[float], Optional[float], Optional[float], str]:
    """(tipo, desconto, mínimo, teto, chave do valor) de um _RE_VALOR."""
    from .lista_cupons import _valor

    def num(g):
        try:
            return _valor(g) if g else None
        except ValueError:
            return None

    if m.group(1):
        tipo, desc = "R$", num(m.group(1))
    else:
        tipo, desc = "%", num(m.group(2))
    minimo, teto = num(m.group(3)), num(m.group(4))
    if minimo is not None and minimo <= 1:
        minimo = None   # "em R$1" (o Xavier escreve assim o "sem mínimo")
    return tipo, desc, minimo, teto, chave_do_valor(tipo, desc, minimo, teto)


def chave_do_valor(tipo: str, desc: Optional[float], minimo: Optional[float], teto: Optional[float]) -> str:
    """'R785-4200', 'P10-149-200': o valor no id do cupom. O teto só no %: "R$ 10 OFF a partir de R$ 99, Limite de
    R$ 10" é o mesmo cupom que "R$ 10 OFF em R$ 99"."""
    if desc is None:
        return "post"
    return ("R" if tipo == "R$" else "P") + f"{desc:g}-{(minimo or 0):g}" + (f"-{teto:g}" if teto and tipo == "%" else "")


def titulo_do_valor(tipo: str, desc: float, minimo: Optional[float], teto: Optional[float]) -> str:
    """Título canônico ("R$ 785 OFF acima de R$ 4.200", "10% OFF acima de R$ 149, limite de R$ 200"): o mesmo valor
    escrito de jeitos diferentes nos canais vira o mesmo texto (e a lista_cupons lê desconto, mínimo e teto dele)."""
    from .lista_cupons import _fmt_pct, fmt_reais

    t = (fmt_reais(desc) if tipo == "R$" else _fmt_pct(desc)) + " OFF"
    if minimo:
        t += f" acima de {fmt_reais(minimo)}"
    if teto and tipo == "%":
        t += f", limite de {fmt_reais(teto)}"
    return t


def _faixa_de_datas(linha: str, base: date) -> Optional[tuple[Optional[date], Optional[date]]]:
    """(início, fim) de uma linha de validade: "Válidos de 10/11 até 12/11", "Ativa dia 10.11 vai até 12.11",
    "(11/11 À 12/11)", "⏰ Vai até 18.11.2026", "Vale até 18/11 ou enquanto durarem". None sem faixa."""
    from .lista_cupons import _data_ddmm

    n = _norm(linha)
    datas = []
    for m in _RE_DATA.finditer(n):
        if re.search(r"r\$\s*$", n[:m.start()]):
            continue
        dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= dia <= 31 and 1 <= mes <= 12):
            continue
        try:
            d = date(int(ano) + (2000 if int(ano) < 100 else 0), mes, dia) if ano else _data_ddmm(dia, mes, base)
        except ValueError:
            d = None
        if d:
            datas.append((m, d))
    if len(datas) >= 2:
        sep = n[datas[0][0].end():datas[1][0].start()]
        if len(sep) <= 24 and re.search(r"\b(?:ate|a)\b|[-–]", sep):
            ini, fim = datas[0][1], datas[1][1]
            return (ini, fim) if ini <= fim else (fim, ini)
    if datas and re.search(r"\bate\b", n[:datas[0][0].start()]):
        return None, datas[0][1]
    return None


def _produto_e_preco(linhas: list[str], ate: int) -> tuple[str, str]:
    """(nome curto do produto, preço) de um post de produto: a 1ª linha antes do cupom que não é link, preço, cabeçalho
    nem chamada ("Pronto para libertar das amarras da sociedade!" fica de fora quando há outra linha), sem emoji e com
    até 6 palavras; e o 1º "R$" das linhas até `ate` que não é valor de cupom."""
    from .lista_cupons import _valor, fmt_reais

    candidatas = [l for l in linhas[:max(ate, 1)]
                  if not re.search(r"https?://|R\$", l) and not loja_do_cabecalho(l) and not _RE_MARCADOR.search(l)
                  and not _RE_VALOR.search(l) and re.search(r"[^\W\d_]{3}", l)]
    sem_chamada = [l for l in candidatas if not re.search(r"[!?]\s*$", l)]
    nome = ""
    if candidatas:
        palavras = re.sub(r"^[^\w]+", "", (sem_chamada or candidatas)[0]).replace("%", "").split()[:6]
        while len(palavras) > 1 and re.fullmatch(r"[\d.,]+", palavras[-1]):
            palavras.pop()   # "... 825GB 1" (o "1 Controle" cortado no meio)
        nome = " ".join(palavras)
        if len(nome) > 45:
            nome = nome[:45].rsplit(" ", 1)[0]
    preco = ""
    for ln in linhas[1:ate + 1]:
        if _RE_VALOR.search(ln):
            continue
        m = _RE_PRECO.search(ln)
        if m:
            try:
                preco = fmt_reais(_valor(m.group(1)))
            except ValueError:
                preco = ""
            break
    return nome.strip(" -–,."), preco


def citacoes_do_post(texto: str, links: Iterable[str], canal: str, post: str, publicado: Optional[str] = None,
                     codes: Iterable[str] = (), riscados: Iterable[str] = ()) -> list[Citacao]:
    """Os cupons citados num post do Telegram. `texto`: o texto do post, com as quebras de linha e com o texto riscado
    (o código riscado é cupom esgotado); `codes`: o que estava em <code> (o código, mesmo sem dígito); `riscados`: o
    texto dos <s>/<del>; `publicado`: ISO da data do post."""
    from .lista_cupons import _data

    linhas = [re.sub(r"[ \t\u00a0]+", " ", l).strip() for l in (texto or "").splitlines()]
    linhas = [l for l in linhas if l]
    if not linhas:
        return []
    em_code = {c.strip().upper() for c in codes if c and c.strip()}
    risc = {t.upper() for r in riscados for t in re.findall(r"[A-Za-z0-9]{4,20}", r or "")}
    pub = _data(publicado)
    base = pub.date() if pub else date.today()
    links = list(links or [])
    loja_post = _hashtag_loja(texto) or loja_dos_links(links)
    sec_loja: Optional[str] = None
    sec_regra = ""
    # validade do evento (linha de data sem "cupom": "Vendas Oficiais: 01.11 até 18.11") e da seção atual ("CUPONS
    # ESPECIAIS (Válidos de 10/11 até 12/11)"); o cabeçalho "CUPONS REGULARES" volta para a do evento
    evento: tuple[Optional[date], Optional[date]] = (None, None)
    sec_ini: Optional[date] = None
    sec_fim: Optional[date] = None
    rodape: Optional[tuple[Optional[date], Optional[date]]] = None   # data escrita depois do último código
    out: list[Citacao] = []
    consumidas: set[int] = set()   # linhas de código já usadas por uma linha de cima
    notas_esgotado = notas_resgatou = notas_selecao = False

    def emite(cods: list[tuple[str, bool]], i: int, titulo: str, tipo: str, chave_valor: str, linha: str,
              explicita: Optional[tuple[Optional[date], Optional[date]]] = None) -> None:
        nonlocal rodape
        plataforma = next((loja_do_codigo(c) for c, _m in cods if loja_do_codigo(c)), None)
        tem_plataforma = plataforma is not None
        n_linha = _norm(linha) + " " + (_norm(linhas[i + 1]) if i + 1 < len(linhas) else "")
        for cod, depois_de_mais in cods:
            loja = loja_do_codigo(cod) or plataforma or sec_loja or loja_post
            if not loja:
                continue
            # "LIBRETX5X3DD + AEMEGA6": o primeiro é cupom de UMA loja dentro do AliExpress (só nos itens dela)
            if loja == "AliExpress" and tem_plataforma and not loja_do_codigo(cod) and tipo == "produto" \
                    and (depois_de_mais or any(m for _c, m in cods)):
                continue
            ini, fim = explicita if explicita else (sec_ini, sec_fim)
            out.append(Citacao(
                loja=loja, codigo=cod, titulo=titulo, canal=canal, post=post, publicado=publicado, tipo=tipo,
                chave_valor=chave_valor, regra=sec_regra, validade=fim.isoformat() if fim else None,
                inicio=ini.isoformat() if ini else None,
                esgotado=bool(cod in risc or _RE_ESGOTADO.search(_norm(linha))),
                resgatou=bool(_RE_RESGATOU.search(n_linha)), linha=linha[:200]))
        rodape = None

    def codigos_do_marcador(i: int, ln: str) -> list[tuple[str, bool]]:
        """Os códigos de "🎟 Cupom: AFFNOV11 + 740 moedas no app", "R$ 3.837,02 com cupom: AFFNOV22", "com cupom
        AFFNOV09", ou da linha de baixo quando a linha acaba no marcador ("R$ 228,55 com cupom:" / "JOGOS0811")."""
        mk = _RE_MARCADOR.search(ln)
        if not mk or _RE_LOJA_DO_CUPOM.search(ln[max(0, mk.start() - 2):mk.end() + 8]):
            return []
        depois = ln[mk.end():]
        dois_pontos = re.match(r"^\s*(?:no\s+app\s*)?:", depois, re.I) or re.match(r"^[^:]{0,15}:", depois)
        if dois_pontos:
            cods, _tudo = _codigos_em(depois[dois_pontos.end():], True, em_code)
        else:
            cods, _tudo = _codigos_em(re.sub(r"^\s*(?:de\s+)?", "", depois), False, em_code)
            cods = [(c, mm) for c, mm in cods if re.search(r"\d", c) or c in em_code]
        if not cods and i + 1 < len(linhas) and (ln.rstrip().endswith(":") or not re.search(r"\w", depois)):
            cods = _so_codigos(linhas[i + 1], True, em_code, parcial=ln.rstrip().endswith(":"))
            if cods:
                consumidas.add(i + 1)
        return cods

    for i, ln in enumerate(linhas):
        if i in consumidas:
            continue
        n = _norm(ln)
        m = _RE_VALOR.search(ln)
        if m:
            tipo_v, desc, minimo, teto, chave = _valor_da_linha(m)
            if minimo is None or teto is None:
                # ML em 3 linhas: "📝 TAMOSJUNTO 👉 10% OFF" / "Tecnologia" / "Compra mínima: R$149 | Desconto máx: R$200"
                for prox in linhas[i + 1:i + 3]:
                    if _RE_VALOR.search(prox):
                        break
                    mm, mt = _RE_MINIMO_SOLTO.search(prox), _RE_TETO_SOLTO.search(prox)
                    if mm or mt:
                        from .lista_cupons import _valor
                        minimo = minimo if minimo is not None else (_valor(mm.group(1)) if mm else None)
                        teto = teto if teto is not None else (_valor(mt.group(1)) if mt else None)
                        chave = chave_do_valor(tipo_v, desc, minimo, teto)
                        break
            if desc:
                titulo = titulo_do_valor(tipo_v, desc, minimo, teto)
                resto = _RE_ANTES_DOS_CODIGOS.sub("", ln[m.end():], count=1)
                cods, _tudo = _codigos_em(resto, True, em_code)
                if not cods:
                    # código antes do valor: "AFFNOV04 R$ 125 OFF acima de R$ 740", "📝 TAMOSJUNTO 👉 10% OFF"
                    antes = ln[:m.start()]
                    seta = bool(re.search(r"(?:👉|➡|->|:)\s*$", antes.strip()))
                    c_antes, tudo = _codigos_em(re.sub(r"^[^\w]+", "", antes), seta, em_code)
                    if c_antes and tudo:
                        cods = c_antes
                if not cods and i + 1 < len(linhas):
                    # código na linha de baixo: "R$785 de desconto em R$4200" / "AFFNOV11"
                    cods = _so_codigos(linhas[i + 1], ln.rstrip().endswith(":"), em_code)
                    if cods:
                        consumidas.add(i + 1)
                if cods:
                    emite(cods, i, titulo, "lista", chave, ln, _faixa_de_datas(ln, base))
                    continue
        # post de produto: o código depois do marcador "Cupom" (ou na linha de baixo)
        cods = codigos_do_marcador(i, ln)
        if cods:
            nome, preco = _produto_e_preco(linhas, i)
            if _RE_ESGOTADO.search(n) and not nome:
                titulo = "cupom citado como esgotado no Telegram"
            elif nome:
                titulo = f"cupom citado no post de {nome}" + (f" por {preco}" if preco else "")
            else:
                titulo = "cupom citado no Telegram"
            emite(cods, i, titulo, "produto", "post", ln)
            continue
        if m:
            continue
        if _RE_ESGOTADO.search(n) or _RE_RESGATOU.search(n):
            # aviso solto ("❌Cupom Esgotado❌", "- Para quem resgatou ontem no APP")
            notas_esgotado |= bool(_RE_ESGOTADO.search(n))
            notas_resgatou |= bool(_RE_RESGATOU.search(n))
            continue
        # cabeçalho: loja e/ou validade da seção (vale até o próximo cabeçalho)
        loja_cab = loja_do_cabecalho(ln)
        faixa = _faixa_de_datas(ln, base)
        cupons_no_titulo = bool(re.search(r"\bcupo(?:m|ns)\b", n))
        if loja_cab or faixa or cupons_no_titulo:
            if loja_cab:
                sec_loja = loja_cab
            if faixa and not cupons_no_titulo:
                evento = faixa   # data do evento: vale para as seções sem data própria
            sec_ini, sec_fim = faixa or evento
            if faixa:
                rodape = faixa
            sec_regra = re.sub(r"^[^\w(#]+", "", ln)[:80]
            continue
        notas_esgotado |= bool(_RE_ESGOTADO.search(n))
        notas_resgatou |= bool(_RE_RESGATOU.search(n))
        notas_selecao |= bool(_RE_SELECAO.search(n))

    # data só no rodapé (depois do último código): vale para o post inteiro
    if rodape is not None:
        ini, fim = rodape
        for c in out:
            if c.validade is None and c.inicio is None:
                c.validade = fim.isoformat() if fim else None
                c.inicio = ini.isoformat() if ini else None
    # aviso solto no post ("❌Cupom Esgotado❌", "para quem resgatou ontem no APP", "Válido na Lista"): vale para os
    # códigos dele quando o post fala de poucos códigos (numa lista grande o aviso é de um só)
    poucos = len({c.codigo for c in out}) <= 2
    for c in out:
        if poucos and notas_esgotado:
            c.esgotado = True
        if poucos and notas_resgatou:
            c.resgatou = True
        if notas_selecao:
            c.regra = (c.regra + " · " if c.regra else "") + "itens selecionados"
    return out


def _grupos_de_canais(canais: Iterable[str]) -> int:
    """Quantos grupos diferentes citaram: canais que repostam o mesmo texto (config.TELEGRAM_GRUPOS_ESPELHO) contam um."""
    ids = set()
    for c in canais:
        cl = c.lower()
        idx = next((i for i, g in enumerate(config.TELEGRAM_GRUPOS_ESPELHO) if cl in {x.lower() for x in g}), None)
        ids.add(f"g{idx}" if idx is not None else cl)
    return len(ids)


def consolida(citacoes: Iterable[Citacao]) -> list[Cupom]:
    """Um Cupom por (loja, CÓDIGO, valor): o mesmo código com o mesmo valor em vários canais (e espelhos) vira um só,
    com a citação ativa mais recente (publicado, link do post, título); valores diferentes do mesmo código ficam em
    registros separados (a lista mostra "outro anúncio diz…"). Esgotado: a citação de esgotado mais nova que todas as
    citações ativas do código marca 'esgotado_em' (a lista tira o código, e de qualquer fonte, se nada mais novo diz que
    voltou). Código só citado como esgotado vira um registro inativo (para tirar o mesmo código de outras fontes)."""
    unicas: dict[tuple, Citacao] = {}
    for c in citacoes:
        unicas.setdefault((c.post, c.codigo, c.chave_valor), c)
    grupos: dict[tuple[str, str, str], list[Citacao]] = {}
    esgotado_em: dict[tuple[str, str], str] = {}
    for c in unicas.values():
        if c.esgotado:
            k = (c.loja, c.codigo)
            esgotado_em[k] = max(esgotado_em.get(k, ""), c.publicado or "")
        grupos.setdefault((c.loja, c.codigo, c.chave_valor), []).append(c)
    com_ativa = {(lj, cod) for (lj, cod, _cv), g in grupos.items() if any(not c.esgotado for c in g)}
    out: list[Cupom] = []
    for (loja, cod, cv), g in grupos.items():
        ativas = [c for c in g if not c.esgotado]
        if not ativas and (loja, cod) in com_ativa:
            continue   # o "esgotou" já vai no registro que tem a citação ativa
        ref = max(ativas or g, key=lambda c: c.publicado or "")
        canais = sorted({c.canal for c in g}, key=str.lower)
        extra: dict = {"canais": canais, "n_grupos": _grupos_de_canais(canais), "tipo": ref.tipo, "linha": ref.linha}
        esg = esgotado_em.get((loja, cod))
        ultima_ativa = max((c.publicado or "" for c in ativas), default="")
        if esg is not None and (not ativas or esg >= ultima_ativa):
            extra["esgotado_em"] = esg or ref.publicado
        if ref.inicio:
            extra["inicio"] = ref.inicio
        regra = ref.regra
        if any(c.resgatou for c in (ativas or g)):
            regra = (regra + " · " if regra else "") + "só para quem resgatou"
        validades = [c.validade for c in (ativas or g) if c.validade]
        out.append(Cupom(
            fonte="telegram", loja=loja, codigo=cod, titulo=ref.titulo, url=f"https://t.me/{ref.post}",
            id=f"{loja}|{cod}|{cv}", regra=regra[:160], validade=max(validades) if validades else None,
            publicado=ref.publicado, extra=extra))
    out.sort(key=lambda c: (c.loja, c.codigo, c.id))
    return out
