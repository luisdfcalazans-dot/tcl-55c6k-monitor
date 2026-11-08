"""Cupons citados nos posts dos canais públicos do Telegram (pedido de 08/11/2026: "faça a varredura também nos cupons
que aparecem nas mensagens dos grupos do telegram").

Só funções puras: a fonte (monitor/sources/telegram_public.py) lê a prévia t.me/s/<canal>, e cada mensagem passa por
citacoes_do_post(); consolida() junta as citações de todos os canais num Cupom por (loja, CÓDIGO, valor), que vai para
a lista diária "🎟️ Cupons ativos" (monitor/lista_cupons.py) e NUNCA para o alerta de "Novo cupom aplicável"
(config.FONTES_CUPOM_SO_LISTA: seria um alerta a cada post).

Padrões (levantados nas prévias de 08/11/2026):

1. linha "valor + mínimo + código(s)": '🏷 R$ 785 OFF em R$ 4200: AFFNOV11', '🎟R$800 OFF em R$4000: IFP1ZYZM',
   '🔹R$ 16 off acima de R$ 80: ISKANDAR1 |IFPQWR8M | AEMEGA1', '🏷 25% OFF , Limite de R$ 500 OFF : MUITOBARATO',
   '🎟️ R$ 670 OFF em R$ 4.200 - Cupom: AFFNOV22', '10% de desconto em R$79(Limite de R$30)', 'R$ 785 OFF (mín. R$
   4.200): AFFNOV11'. Códigos alternativos (" ou ", ",", "/", "|") viram cupons separados com o mesmo título; os códigos
   vêm depois do ÚLTIMO ":" da linha;
2. código na linha de baixo: 'R$785 de desconto em R$4200' / 'AFFNOV11'; '💸 R$ 670 OFF acima de R$ 4200' /
   '🎟️ Cupom: AFFNOV22';
3. código antes do valor: 'AFFNOV04 R$ 125 OFF acima de R$ 740', '📝 TAMOSJUNTO 👉 10% OFF' (a linha de baixo, antes
   da "Compra mínima", é a categoria: '📝 HOJECONSTRU 👉 15% OFF' / 'Indústria e comércio');
4. post de produto: '🎟 Cupom: AFFNOV11 + 740 moedas no app', 'R$ 228,55 com cupom:' / 'JOGOS0811' (título: "cupom
   citado no post de <produto> por R$ X"; as moedas e o "cupom da loja" ficam de fora). A linha de desconto do PRODUTO
   ('🔻 22% de desconto', '✅ Por R$ 3.690 (R$ 785 OFF)', '💰 R$ 200 de desconto no PIX') não é o valor do cupom;
5. cabeçalho de seção: a loja ('🚨 Cupons novos AliExpress', '#Kabum') e a validade ('Válidos de 10/11 até 12/11',
   '(11/11 À 12/11)', '⏰ Vai até 18.11.2026') valem para as linhas de baixo até o próximo cabeçalho; data escrita só
   depois de todos os códigos (rodapé) vale para o post inteiro. Data só conta em linha que fala de validade (o "6.7''"
   e o "até 4.4GHz" do título do produto não são data);
6. esgotado só quando o post diz do cupom: 'O cupom IFP43VOM esgotou', 'Cupom: SUPERMELI ESGOTADO', 'MELIPROMO -
   ESGOTADO - COMECOU12H - ATIVO' (o status vale para o código da esquerda), '❌Cupom Esgotado❌' (linha só com o
   status: vale para o post), o código riscado (<s>). "antes que (o estoque) esgote", "se esgotar", "esgotando", "NÃO
   ACABOU", "ACABOU A BRIGA" e o "❌ De: R$..." do preço antigo não são esgotado. "Cupom X esgotou" sem loja conhecida
   vale para o mesmo código em qualquer loja (LOJA_QUALQUER). "quem resgatou" vira restrição.

Código: 4 a 20 letras/dígitos ASCII, com pelo menos 1 dígito, ou logo depois de "Cupom:"/":" (ou dentro de <code>), em
maiúsculas, e a linha acaba nos códigos; nunca uma palavra da lista negra (CUPOM, PIX, APP, OFF, LINK, MOEDAS, SOMENTE,
nome de loja...). A loja do código: prefixo de código da plataforma (AFFNOV9, AEMEGA8, AESUPER5, IFPxxxxx = AliExpress)
> cabeçalho da seção > hashtag > domínio do link (s.click.aliexpress, meli.la, s.shopee, amzn.to...). Sem loja
conhecida, o código fica de fora (menos o "esgotou").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, NamedTuple, Optional

from . import config
from .models import Cupom
from .util import _NAO_E_CUPOM, _RE_MODELO_TV, sem_acentos

# "esgotou" de um código sem loja conhecida ("Cupom MELIPROMO3111 esgotou ‼️", post curto sem link): vale para o mesmo
# código em qualquer loja (lista_cupons.cupons_ativos)
LOJA_QUALQUER = "*"

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
    # instrução no lugar do código ("R$ 20 OFF em R$ 100: SOMENTE NO APP", "Cupom: CONFIRA", "Cupom: PEGUE AQUI")
    "SOMENTE", "APENAS", "ATIVE", "ATIVAR", "CONFIRA", "GARANTA", "PEGUE", "PEGAR", "DISPONIVEL", "AUTOMATICO", "VEJA",
    "ABAIXO", "CARRINHO", "PAGINA", "HOJE",
}
# "825GB", "120Hz", "4K": medida de produto, não código
_RE_MEDIDA = re.compile(r"\d+(?:[.,]\d+)?(?:GB|TB|MB|HZ|MM|CM|ML|KG|G|W|V|X|K|P|MAH|POL|LITROS?|L)")
# modelo de placa/processador sozinho na linha de baixo de um valor ("R$ 100 OFF em R$ 1.000" / "RX7600")
_RE_MODELO_PRODUTO = re.compile(r"(?:RTX|GTX|RX|GT)\d{3,4}(?:TI|XT|XTX|S|SUPER)?|I[3579]\d{4,5}[A-Z]{0,2}|"
                                r"R[3579]\d{4}[A-Z0-9]{0,3}")
# palavras com acento inteiras ("AUTOMÁTICO" não vira "AUTOM"); "-" junta pedaços ("CFI-2014")
_RE_TOKEN = re.compile(r"[^\W_]+(?:-[^\W_]+)*|[,/|+]")
_CONECTIVOS = {"OU", "E", "OR"}
# status escrito na própria lista de códigos ("MELIPROMO - ESGOTADO - COMECOU12H - ATIVO", "Cupom X esgotou"): o
# esgotado vale para o código da esquerda; os outros só não interrompem a lista
_STATUS_ESGOTADO = {"ESGOTADO", "ESGOTADA", "ESGOTADOS", "ESGOTADAS", "ESGOTOU", "ESGOTARAM", "ACABOU"}
_STATUS_OUTROS = {"ATIVO", "ATIVA", "ATIVOS", "ATIVADO", "NOVO", "NOVA", "VOLTOU", "RENOVADO", "FUNCIONANDO"}

# ---- valor ----
_N = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
# "R$ 785 OFF em R$ 4200", "R$785 de desconto em R$4200", "R$40 off em pedidos acima de R$250", "25% OFF , Limite de
# R$ 500 OFF", "10% OFF acima de R$79, limite R$30", "15% OFF em R$ 500, Limite de R$ 100 OFF", "10% de desconto em
# R$79(Limite de R$30)", "R$ 785 OFF (mín. R$ 4.200)", "R$ 785 OFF | Mínimo R$ 4.200", "15% OFF em R$ 500 (máx. R$ 100)",
# "R$ 50 OFF com compra mínima de R$ 249"
_RE_VALOR = re.compile(
    r"(?:R\$\s?" + _N + r"\s*(?:OFF\b|de\s+desconto\b)|(?<![\d,.])(\d{1,2}(?:[.,]\d)?)\s*%\s*(?:OFF\b|de\s+desconto\b))"
    r"(?:[\s,(|]*(?:em|acima\s+de|a\s+partir\s+de|(?:em|para|nas)\s+(?:pedidos|compras)\s+(?:acima\s+de|a\s+partir\s+de|"
    r"de)|(?:com\s+)?compra\s+m[ií]nima(?:\s+de)?:?|m[ií]n(?:imo)?\.?(?:\s+de)?:?)\s*R\$\s?" + _N + r"\)?)?"
    r"(?:[\s,(|]*(?:(?:com\s+)?limite(?:\s+de)?|limitado\s+a|at[eé]|desconto\s+m[aá]x(?:imo)?\.?:?|"
    r"m[aá]x(?:imo)?\.?(?:\s+de)?:?)"
    r"\s*R\$\s?" + _N + r"(?:\s*OFF\b)?\)?)?",
    re.I)
# "Compra mínima: R$149 | Desconto máx: R$200" (Iskandar, ML em 3 linhas)
_RE_MINIMO_SOLTO = re.compile(r"compra\s+m[ií]nima:?\s*R\$\s?" + _N, re.I)
_RE_TETO_SOLTO = re.compile(r"desconto\s+m[aá]x(?:imo)?\.?:?\s*R\$\s?" + _N, re.I)
# mínimo/teto que sobrou entre o valor e os códigos ("R$ 50 OFF em Eletrônicos acima de R$ 500: X")
_RE_MINIMO_RESTO = re.compile(r"(?:acima\s+de|a\s+partir\s+de|m[ií]n(?:imo|ima)?\.?(?:\s+de)?:?)\s*R\$\s?" + _N, re.I)
_RE_TETO_RESTO = re.compile(r"(?:limite(?:\s+de)?|limitado\s+a|m[aá]x(?:imo)?\.?(?:\s+de)?:?)\s*R\$\s?" + _N, re.I)
_RE_PRECO = re.compile(r"R\$\s?" + _N)
# o que vem antes dos códigos depois do valor: "- Cupom:", ": ", "Use o cupom"
_RE_ANTES_DOS_CODIGOS = re.compile(r"^[\s:\-–—=>👉➡️]*(?:(?:use|usem|resgate)\s+(?:o\s+)?)?(?:cupo(?:m|ns)\b\s*"
                                   r"(?:no\s+app\b)?\s*)?[:\-–—]?\s*", re.I)
# marcador de cupom num post de produto: "🎟 Cupom: X", "Use cupom: X", "com cupom X", "Usem o cupom: X"
_RE_MARCADOR = re.compile(r"(?<![a-z])cupo(?:m|ns)\b", re.I)

# ---- status e escopo ----
# o post diz que o CUPOM esgotou: "O cupom X esgotou", "cupom *DESCONTO18* esgotado", "Cupons acabaram", "esgotou o
# cupom" (o "PS5 esgotou na Amazon, mas tem no ML com cupom X" não é)
_RE_CUPOM_ESGOTADO = re.compile(
    r"\bcupo(?:m|ns)\b([^.!?\n]{0,30}?)\b(?:esgot(?:ou|aram|ad[oa]s?)|acab(?:ou|aram)|totalmente\s+resgatad[oa]s?)\b|"
    r"\b(?:esgot(?:ou|aram)|acab(?:ou|aram))\s+(?:o|os)\s+cupo(?:m|ns)\b")
# linha que é só o status ("❌Cupom Esgotado❌", "❌ ESGOTADO ❌", "Acabou!", "Totalmente resgatado"): vale para o post
_RE_SO_STATUS = re.compile(
    r"(?:(?:atualizacao|update|editado)\s+)?(?:(?:o|os|a|as|esse|este)\s+)?(?:cupo(?:m|ns)\s+)?"
    r"(?:(?:ja|foi|foram|esta|estao|agora)\s+)*(?:esgotad[oa]s?|esgotou|esgotaram|acabou|acabaram|encerrad[oa]s?|"
    r"totalmente\s+resgatad[oa]s?)(?:\s+(?:hoje|ja|agora))?")
_RE_RESGATOU = re.compile(r"quem\s+(?:ja\s+)?resgatou")
_RE_SELECAO = re.compile(r"valido\s+na\s+lista|(?:itens|produtos)\s+selecionados|"
                         r"ative\s+em\s+algum\s+produto")
# o resto da linha de valor que diz onde/para quem o cupom vale (vai para a regra: "Placas de video selecionadas na
# lista abaixo", "somente no app", "novos compradores")
_RE_NOTA_DO_RESTO = re.compile(r"selecionad|categori|\blista\b|nov[oa]s?\s+(?:clientes|compradores|usuarios)|"
                               r"primeira\s+compra|\bapp\b|whats|\bprime\b|assinante|resgatou")
_RE_CABECALHO = re.compile(r"cupo|#|\bloja\s*:")
_RE_DATA = re.compile(r"(?<![\d$])(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?![\d,]|\s*x\b)")
# número com unidade logo depois não é data: "6.7''", "4.4GHz", "5.1 canais", "2.0 W"
_RE_UNIDADE = re.compile(r"\s*(?:ghz|mhz|hz|''|\"|”|pol\b|polegadas|mp\b|l\b|w\b|v\b|gb|tb|mb|mm|cm|kg|g\b|k\b|mah|"
                         r"%|ch\b|canais|\+)")
# a linha fala de validade: "Válidos de 10/11 até 12/11", "Ativa dia 10.11 vai até 12.11", "CUPONS (11/11 À 12/11)",
# "⏰ Vai até 18.11", "Vale até 18/11", "Vendas Oficiais: 01.11.2026 até 18.11.2026"
_RE_DIZ_VALIDADE = re.compile(r"valid|\bvale\b|\bvai\s+ate\b|\bativ|expira|termina|encerra|cupo|\bperiodo\b|\bprazo\b|"
                              r"\bvendas\b|\bevento\b|\bpromo|⏰|⏳|📅|🗓")
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


class _Cod(NamedTuple):
    """Um código achado numa linha: o grupo (cada "+" abre outro: "LIBRETX5X3DD + AEMEGA6 ou AFFNOV06" tem o cupom da
    loja no grupo 0 e os da plataforma no 1) e se a própria lista diz que ele esgotou."""

    codigo: str
    grupo: int = 0
    esgotado: bool = False


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


def _diz_cupom_esgotado(n: str) -> bool:
    """A linha (normalizada) diz que o cupom esgotou ("O cupom X esgotou", "cupom *X* esgotado")? "cupom ainda não
    esgotou" não."""
    for m in _RE_CUPOM_ESGOTADO.finditer(n):
        meio = m.group(1) or ""
        antes = n[max(0, m.start() - 12):m.start()]
        if re.search(r"\bnao\b", meio) or re.search(r"\b(?:nao|se|caso)\s+$", antes):
            continue
        return True
    return False


def _so_status(n: str) -> bool:
    """A linha (normalizada) é só o status de esgotado ("❌Cupom Esgotado❌", "❌ ESGOTADO ❌", "Acabou!")?"""
    w = " ".join(re.sub(r"[^\w\s]", " ", n).split())
    return bool(w) and bool(_RE_SO_STATUS.fullmatch(w))


def _codigo(tok: str, explicito: bool, em_code: set[str]) -> Optional[str]:
    """O código em maiúsculas, se `tok` pode ser um. Com dígito: maiúsculas, minúsculas ou misturado começando por letra
    ("peperaio1", "Pelando8"). Sem dígito: só em maiúsculas e com sinal explícito (logo depois de "Cupom:"/":" ou
    dentro de <code>). Palavra com acento nunca é código."""
    t = tok.strip("-")
    if not t.isascii():
        return None
    up = t.upper()
    if not 4 <= len(t) <= 20 or not re.search(r"[A-Z]", up) or up in _NAO_CODIGO:
        return None
    if _RE_MODELO_TV.fullmatch(up) or _RE_MEDIDA.fullmatch(up) or _RE_MODELO_PRODUTO.fullmatch(up):
        return None
    if re.search(r"\d", t):
        return up if (t.isupper() or t[0].isalpha()) else None
    if up in em_code:
        return up
    return up if explicito and t.isupper() and len(t) >= 5 else None


class _Achados(NamedTuple):
    """O que _codigos_em achou: os códigos, se o texto acabou neles (só sobrou emoji e pontuação), se a lista traz
    status e se a palavra que parou a lista vem depois de um separador ("TAMOSJUNTO (10% OFF...)", "X + 740 moedas")."""

    cods: list[_Cod]
    tudo: bool
    status: bool
    delimitado: bool


def _codigos_em(texto: str, explicito: bool, em_code: set[str]) -> _Achados:
    """Os códigos no começo de `texto` (e o resto de _Achados). Para na primeira palavra que não é código, conectivo nem
    status ("+ 740 moedas no app", "+ Cupom da loja"); o status ("MELIPROMO - ESGOTADO - COMECOU12H - ATIVO") marca o
    código da esquerda."""
    out: list[_Cod] = []
    grupo = 0
    com_status = False
    fim = 0
    for m in _RE_TOKEN.finditer(texto):
        tok = m.group()
        if tok in ",/|":
            continue
        if tok == "+":
            grupo += 1
            continue
        up = sem_acentos(tok).upper()
        if up in _CONECTIVOS and out:
            continue
        if up in _STATUS_ESGOTADO:
            if out:
                out[-1] = out[-1]._replace(esgotado=True)
            com_status = True
            continue
        if up in _STATUS_OUTROS:
            com_status = True
            continue
        cod = _codigo(tok, explicito, em_code)
        if cod is None:
            return _Achados(out, False, com_status, bool(out) and bool(re.search(r"[(+\-–—|]", texto[fim:m.start()])))
        if cod not in (c.codigo for c in out):
            out.append(_Cod(cod, grupo))
        fim = m.end()
    return _Achados(out, True, com_status, False)


def _com_sinal(a: _Achados, em_code: set[str]) -> list[_Cod]:
    """Código só de letras vale quando a linha acaba nos códigos (ou num separador: "TAMOSJUNTO (10% OFF, ...)") ou ele
    está em <code>: "R$ 20 OFF em R$ 100: SOMENTE NO APP" não tem código."""
    if a.tudo or a.delimitado:
        return a.cods
    return [c for c in a.cods if re.search(r"\d", c.codigo) or c.codigo in em_code]


def _so_codigos(linha: str, explicito: bool, em_code: set[str], parcial: bool = False) -> tuple[list[_Cod], bool]:
    """Os códigos de uma linha que só tem código(s) ("AFFNOV11", "IFPR2XGX IFPE6TPU", "🎟️ Cupom: AFFNOV22",
    "🏷 Cupom: FF5E8II49K", "🎟 CUPOM: COMPRAHOJE", "Cupons: MELIPROMO - ESGOTADO - COMECOU12H - ATIVO") e se a lista
    traz status; [] se a linha tem outra coisa. `parcial` (a linha de cima terminou em "com cupom:"): os códigos do começo
    bastam ("TAMOSJUNTO + CUPOM DE R$ 200 OFF DA LOJA")."""
    if _RE_VALOR.search(linha) and not parcial:
        return [], False
    m = re.match(r"^[^\w]*(?:(?:use|usem|resgate)\s+(?:o\s+)?)?cupo(?:m|ns)\b\s*(?:no\s+app\b)?\s*:", linha, re.I)
    if m:
        linha, explicito = linha[m.end():], True
    elif not parcial and re.search(r"[A-Za-z]{2,}", linha) and _RE_MARCADOR.search(linha):
        return [], False
    a = _codigos_em(re.sub(r"^[^\w]+", "", linha), explicito, em_code)
    return (a.cods if a.cods and (a.tudo or parcial) else []), a.status


def _valor_da_linha(m: re.Match) -> tuple[str, Optional[float], Optional[float], Optional[float]]:
    """(tipo, desconto, mínimo, teto) de um _RE_VALOR."""
    if m.group(1):
        tipo, desc = "R$", _num(m.group(1))
    else:
        tipo, desc = "%", _num(m.group(2))
    return tipo, desc, _num(m.group(3)), _num(m.group(4))


def _num(g: Optional[str]) -> Optional[float]:
    from .lista_cupons import _valor

    try:
        return _valor(g) if g else None
    except ValueError:
        return None


def chave_do_valor(tipo: str, desc: Optional[float], minimo: Optional[float], teto: Optional[float]) -> str:
    """'R785-4200', 'P10-149-200': o valor no id do cupom. O teto só no %: "R$ 10 OFF a partir de R$ 99, Limite de
    R$ 10" é o mesmo cupom que "R$ 10 OFF em R$ 99"."""
    if desc is None:
        return "post"
    return ("R" if tipo == "R$" else "P") + f"{desc:g}-{(minimo or 0):g}" + (f"-{teto:g}" if teto and tipo == "%" else "")


def titulo_do_valor(tipo: str, desc: float, minimo: Optional[float], teto: Optional[float], escopo: str = "") -> str:
    """Título canônico ("R$ 785 OFF acima de R$ 4.200", "10% OFF acima de R$ 149, limite de R$ 200", "15% OFF em
    Indústria e comércio acima de R$ 79, limite de R$ 60"): o mesmo valor escrito de jeitos diferentes nos canais vira o
    mesmo texto (e a lista_cupons lê desconto, mínimo, teto e escopo dele)."""
    from .lista_cupons import _fmt_pct, fmt_reais

    t = (fmt_reais(desc) if tipo == "R$" else _fmt_pct(desc)) + " OFF"
    if escopo:
        t += (" " if re.match(r"(?i)(?:em|no|na|nos|nas|para|pra)\b", escopo) else " em ") + escopo
    if minimo:
        t += f" acima de {fmt_reais(minimo)}"
    if teto and tipo == "%":
        t += f", limite de {fmt_reais(teto)}"
    return t


def _limpa_resto(s: str) -> str:
    """O resto da linha de valor sem emoji, sem "Cupom"/"Use o cupom" e sem o mínimo/teto; '' se não sobra texto."""
    s = re.split(r"[.!?;]\s|🔽|⬇|👇", s + " ")[0]
    s = _RE_MINIMO_RESTO.sub(" ", s)
    s = _RE_TETO_RESTO.sub(" ", s)
    s = re.sub(r"(?i)\b(?:use|usem|resgate)\s+(?:o\s+)?cupo(?:m|ns)\b|\bcupo(?:m|ns)\b|\bresgate\s+(?:aqui|no\s+link)\b",
               " ", s)
    s = re.sub(r"[^\w\s&,/+'-]", " ", s)
    s = " ".join(s.split()).strip(" -–—,/+")
    return s if re.search(r"[^\W\d_]{3}", s) else ""


def _escopo_e_nota(resto: str) -> tuple[str, str]:
    """(escopo para o título, nota para a regra) do resto da linha de valor: "em Eletrônicos" vira escopo ("R$ 50 OFF em
    Eletrônicos acima de R$ 500"); "Placas de video selecionadas na lista abaixo", "somente no app" viram nota (a lista
    lê "selecionad", "no app", "novos compradores" na regra). O resto que não diz nada disso fica de fora."""
    s = _limpa_resto(resto)
    if not s:
        return "", ""
    if re.match(r"(?i)(?:em|na|no|nos|nas|para|pra)\s+[^\W\d_]{3}", s) and len(s) <= 50 \
            and not re.search(r"(?i)\bat[eé]\b|\d\s*x\b|\bvezes\b|\bpix\b", s):
        return s, ""
    return "", (s[:80] if _RE_NOTA_DO_RESTO.search(_norm(s)) else "")


def _categoria(linha: str) -> str:
    """A linha de categoria do formato do Iskandar ("Tecnologia", "Indústria e comércio", "Casa & decor") entre a linha
    do código e a "Compra mínima"; '' se a linha é outra coisa."""
    ln = re.sub(r"^[^\w]+", "", linha).strip()
    if not ln or len(ln) > 40 or re.search(r"R\$|https?://|:|\d", ln) or _RE_MARCADOR.search(ln):
        return ""
    return ln if re.search(r"[^\W\d_]{3}", ln) else ""


def _faixa_de_datas(linha: str, base: date) -> Optional[tuple[Optional[date], Optional[date]]]:
    """(início, fim) de uma linha de validade: "Válidos de 10/11 até 12/11", "Ativa dia 10.11 vai até 12.11",
    "(11/11 À 12/11)", "⏰ Vai até 18.11.2026", "Vale até 18/11 ou enquanto durarem". None sem faixa, e em linha que não
    fala de validade (título de produto com "Câmera De Até 50mp ... 6.7''", "Turbo até 4.4GHz", "Bluetooth até 5.3").
    O "11.11" do nome do evento ("PROMO 11.11(01/11 À 18/11)") não conta quando a linha traz outra faixa."""
    from .lista_cupons import _data_ddmm

    n = _norm(linha)
    so_datas = not re.search(r"[a-z]{3,}", re.sub(r"\b(?:de|a|ate|as|do|dia|e)\b", " ", _RE_DATA.sub(" ", n)))
    if not (_RE_DIZ_VALIDADE.search(n) or so_datas):
        return None
    datas = []
    for m in _RE_DATA.finditer(n):
        if re.search(r"r\$\s*$", n[:m.start()]) or _RE_UNIDADE.match(n, m.end()):
            continue
        dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= dia <= 31 and 1 <= mes <= 12):
            continue
        try:
            d = date(int(ano) + (2000 if int(ano) < 100 else 0), mes, dia) if ano else _data_ddmm(dia, mes, base)
        except ValueError:
            d = None
        if d:
            datas.append((m, d, dia == mes and not ano and "." in m.group(0)))
    if len(datas) >= 3:
        datas = [x for x in datas if not x[2]] or datas   # "11.11" do evento
    if len(datas) >= 2:
        sep = n[datas[0][0].end():datas[1][0].start()]
        if len(sep) <= 24 and re.search(r"\b(?:ate|a|as)\b|[-–]", sep):
            ini, fim = datas[0][1], datas[1][1]
            return (ini, fim) if ini <= fim else (fim, ini)
    if datas and re.search(r"\bate\s+(?:o\s+)?(?:dia\s+)?$", n[:datas[0][0].start()]):
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


def _desconto_do_produto(ln: str, m: re.Match, minimo: Optional[float], teto: Optional[float],
                         cods_na_linha: bool) -> bool:
    """A linha de valor é o desconto do PRODUTO (preço antigo x novo), não um cupom? "🔻 22% de desconto", "🔻 R$ 1.059
    OFF" ou "💰 R$ 200 de desconto no PIX" logo acima de "🎟 Cupom: X", "✅ Por R$ 3.690 (R$ 785 OFF)". Só sem compra
    mínima e sem teto, e sem "cupom" antes do valor ("CUPOM 10% OFF - Placas de vídeo" é cupom)."""
    if minimo is not None or teto is not None:
        return False
    antes, depois = _norm(ln[:m.start()]), _norm(ln[m.end():])
    if re.search(r"\bcupo", antes):
        return False
    if _RE_PRECO.search(ln[:m.start()]) or re.search(r"\bpor\b|\(\s*$", antes) \
            or re.match(r"\s*(?:(?:no|via|pagando\s+no)\s+pix\b|a\s+vista\b|\))", depois):
        return True
    return not cods_na_linha


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

    def emite(cods: list[_Cod], i: int, titulo: str, tipo: str, chave_valor: str, linha: str,
              explicita: Optional[tuple[Optional[date], Optional[date]]] = None, com_status: bool = False,
              nota: str = "") -> None:
        nonlocal rodape
        plataforma = next((loja_do_codigo(c.codigo) for c in cods if loja_do_codigo(c.codigo)), None)
        grupos_plat = {c.grupo for c in cods if loja_do_codigo(c.codigo)}
        n_linha = _norm(linha) + " " + (_norm(linhas[i + 1]) if i + 1 < len(linhas) else "")
        # "Cupom X esgotou" na própria linha (sem status por código: "MELIPROMO - ESGOTADO - COMECOU12H - ATIVO" diz de
        # cada um)
        esg_linha = not com_status and _diz_cupom_esgotado(_norm(linha))
        for c in cods:
            esgotado = bool(c.esgotado or c.codigo in risc or esg_linha)
            loja = loja_do_codigo(c.codigo) or plataforma or sec_loja or loja_post
            if not loja:
                if not esgotado:
                    continue
                loja = LOJA_QUALQUER   # "Cupom MELIPROMO3111 esgotou": tira o código de qualquer loja
            # "LIBRETX5X3DD + AEMEGA6 ou AFFNOV06": o grupo sem código da plataforma é cupom de UMA loja dentro do
            # AliExpress (só nos itens dela); "ISKANDAR4 ou AFFNOV04 ou AEMEGA4 + M1RC35BR": o ISKANDAR4 fica
            if loja == "AliExpress" and grupos_plat and c.grupo not in grupos_plat and tipo == "produto":
                continue
            ini, fim = explicita if explicita else (sec_ini, sec_fim)
            regra = sec_regra + (" · " + nota if sec_regra and nota else nota)
            out.append(Citacao(
                loja=loja, codigo=c.codigo, titulo=titulo, canal=canal, post=post, publicado=publicado, tipo=tipo,
                chave_valor=chave_valor, regra=regra, validade=fim.isoformat() if fim else None,
                inicio=ini.isoformat() if ini else None, esgotado=esgotado,
                resgatou=bool(_RE_RESGATOU.search(n_linha)), linha=linha[:200]))
        rodape = None

    def codigos_do_marcador(i: int, ln: str) -> tuple[list[_Cod], bool]:
        """Os códigos de "🎟 Cupom: AFFNOV11 + 740 moedas no app", "R$ 3.837,02 com cupom: AFFNOV22", "com cupom
        AFFNOV09", "CUPOM MELIPROMO ESGOTADO", ou da linha de baixo quando a linha acaba no marcador ("R$ 228,55 com
        cupom:" / "JOGOS0811"); e se a lista traz status por código."""
        mk = _RE_MARCADOR.search(ln)
        if not mk or _RE_LOJA_DO_CUPOM.search(ln[max(0, mk.start() - 2):mk.end() + 8]):
            return [], False
        depois = ln[mk.end():]
        dois_pontos = re.match(r"^\s*(?:no\s+app\s*)?:", depois, re.I) or re.match(r"^[^:]{0,15}:", depois)
        if dois_pontos:
            a = _codigos_em(depois[dois_pontos.end():], True, em_code)
            cods, status = _com_sinal(a, em_code), a.status
        else:
            a = _codigos_em(re.sub(r"^\s*(?:de\s+)?", "", depois), True, em_code)
            # sem ":", só com dígito, em <code> ou com o status logo depois ("CUPOM MELIPROMO ESGOTADO")
            cods = [c for c in a.cods if re.search(r"\d", c.codigo) or c.codigo in em_code or c.esgotado]
            status = a.status
        if not cods and i + 1 < len(linhas) and (ln.rstrip().endswith(":") or not re.search(r"\w", depois)):
            cods, status = _so_codigos(linhas[i + 1], True, em_code, parcial=ln.rstrip().endswith(":"))
            if cods:
                consumidas.add(i + 1)
        return cods, status

    for i, ln in enumerate(linhas):
        if i in consumidas:
            continue
        n = _norm(ln)
        m = _RE_VALOR.search(ln)
        if m:
            tipo_v, desc, minimo, teto = _valor_da_linha(m)
            if minimo is not None and minimo <= 1:
                minimo = None   # "em R$1" (o Xavier escreve assim o "sem mínimo")
            resto = ln[m.end():]
            # os códigos vêm depois do último ":" ("R$ 785 OFF (mín. R$ 4.200): AFFNOV11"); o que fica antes é o resto
            # da linha (escopo, nota, mínimo/teto escritos de outro jeito)
            antes_cods, resto_cods = resto.rsplit(":", 1) if ":" in resto else ("", resto)
            if minimo is None and antes_cods:
                minimo = _num(next(iter(_RE_MINIMO_RESTO.findall(antes_cods)), None))
            if teto is None and antes_cods:
                teto = _num(next(iter(_RE_TETO_RESTO.findall(antes_cods)), None))
            categoria = ""
            if minimo is None or teto is None:
                # ML em 3 linhas: "📝 TAMOSJUNTO 👉 10% OFF" / "Tecnologia" / "Compra mínima: R$149 | Desconto máx: R$200"
                for j, prox in enumerate(linhas[i + 1:i + 3]):
                    if _RE_VALOR.search(prox):
                        break
                    mm, mt = _RE_MINIMO_SOLTO.search(prox), _RE_TETO_SOLTO.search(prox)
                    if mm or mt:
                        minimo = minimo if minimo is not None else (_num(mm.group(1)) if mm else None)
                        teto = teto if teto is not None else (_num(mt.group(1)) if mt else None)
                        if j == 1:
                            categoria = _categoria(linhas[i + 1])
                        break
            if desc:
                chave = chave_do_valor(tipo_v, desc, minimo, teto)
                resto_cods = _RE_ANTES_DOS_CODIGOS.sub("", resto_cods, count=1)
                a = _codigos_em(resto_cods, True, em_code)
                cods, status = _com_sinal(a, em_code), a.status
                na_linha = bool(cods)
                if not cods:
                    # código antes do valor: "AFFNOV04 R$ 125 OFF acima de R$ 740", "📝 TAMOSJUNTO 👉 10% OFF"
                    antes = ln[:m.start()]
                    seta = bool(re.search(r"(?:👉|➡|->|:)\s*$", antes.strip()))
                    a = _codigos_em(re.sub(r"^[^\w]+", "", antes), seta, em_code)
                    if a.cods and a.tudo:
                        cods, na_linha, status = a.cods, True, a.status
                if not _desconto_do_produto(ln, m, minimo, teto, na_linha):
                    if not cods and i + 1 < len(linhas):
                        # código na linha de baixo: "R$785 de desconto em R$4200" / "AFFNOV11"
                        cods, status = _so_codigos(linhas[i + 1], ln.rstrip().endswith(":"), em_code)
                        if cods:
                            consumidas.add(i + 1)
                    if cods:
                        escopo, nota = _escopo_e_nota(antes_cods if ":" in resto else ("" if na_linha else resto))
                        titulo = titulo_do_valor(tipo_v, desc, minimo, teto, categoria or escopo)
                        emite(cods, i, titulo, "lista", chave, ln, _faixa_de_datas(ln, base), status, nota)
                        continue
        # post de produto: o código depois do marcador "Cupom" (ou na linha de baixo)
        cods, status = codigos_do_marcador(i, ln)
        if cods:
            nome, preco = _produto_e_preco(linhas, i)
            esg = all(c.esgotado or c.codigo in risc for c in cods) or (not status and _diz_cupom_esgotado(n))
            if esg and not nome:
                titulo = "cupom citado como esgotado no Telegram"
            elif nome:
                titulo = f"cupom citado no post de {nome}" + (f" por {preco}" if preco else "")
            else:
                titulo = "cupom citado no Telegram"
            emite(cods, i, titulo, "produto", "post", ln, com_status=status)
            continue
        if m:
            continue
        if _so_status(n):
            # "❌Cupom Esgotado❌" (o promotop edita o post original): vale para o post (se ele fala de poucos códigos)
            notas_esgotado = True
            continue
        if _RE_RESGATOU.search(n):
            # "- Para quem resgatou ontem no APP"
            notas_resgatou = True
            continue
        if _RE_CUPOM_ESGOTADO.search(n):
            continue   # "Cupom esgotou, use o outro" sem dizer qual: não marca ninguém
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
    voltou); 'ultima_ativa' guarda a citação ativa mais nova (o state mantém um "esgotou" antigo até aparecer uma mais
    nova que ele). Código só citado como esgotado vira um registro inativo (para tirar o mesmo código de outras fontes);
    o "esgotou" sem loja (LOJA_QUALQUER) vale também para o código citado em qualquer loja. A validade vem das citações
    de lista (a do post de produto só quando não há outra)."""
    unicas: dict[tuple, Citacao] = {}
    for c in citacoes:
        unicas.setdefault((c.post, c.codigo, c.chave_valor, c.loja), c)
    lojas_do_codigo: dict[str, set[str]] = {}
    for c in unicas.values():
        if c.loja != LOJA_QUALQUER:
            lojas_do_codigo.setdefault(c.codigo, set()).add(c.loja)
    grupos: dict[tuple[str, str, str], list[Citacao]] = {}
    esgotado_em: dict[tuple[str, str], str] = {}
    for c in unicas.values():
        if c.esgotado:
            alvos = {c.loja} | (lojas_do_codigo.get(c.codigo, set()) if c.loja == LOJA_QUALQUER else set())
            for lj in alvos:
                esgotado_em[(lj, c.codigo)] = max(esgotado_em.get((lj, c.codigo), ""), c.publicado or "")
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
        if ultima_ativa:
            extra["ultima_ativa"] = ultima_ativa
        if esg is not None and (not ativas or esg >= ultima_ativa):
            extra["esgotado_em"] = esg or ref.publicado
        if ref.inicio:
            extra["inicio"] = ref.inicio
        regra = ref.regra
        if any(c.resgatou for c in (ativas or g)):
            regra = (regra + " · " if regra else "") + "só para quem resgatou"
        base = ativas or g
        validades = [c.validade for c in base if c.validade and c.tipo == "lista"] or \
            [c.validade for c in base if c.validade]
        out.append(Cupom(
            fonte="telegram", loja=loja, codigo=cod, titulo=ref.titulo, url=f"https://t.me/{ref.post}",
            id=f"{loja}|{cod}|{cv}", regra=regra[:160], validade=max(validades) if validades else None,
            publicado=ref.publicado, extra=extra))
    out.sort(key=lambda c: (c.loja, c.codigo, c.id))
    return out
