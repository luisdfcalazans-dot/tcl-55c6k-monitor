"""Lista diária "🎟️ Cupons ativos" no Telegram (pedido de 08/11/2026).

Uma mensagem (ou mais, se passar de ~3800 caracteres) com SÓ os cupons ativos de cada loja: o código (em <code>, para
copiar com um toque) e o valor do desconto (15% OFF, R$ 20 OFF, compra mínima, teto, escopo curto). Não é a mensagem de
"Novo cupom aplicável" de regras.gerar_alertas: aqui entra todo cupom ativo da loja, sirva ou não no PS5/GTA 6.

De onde vêm os cupons (run.py): os desta rodada, os da última leitura de cada fonte no state deste modo (fonte que não
trouxe nada agora) e os do outro modo (latest_<outro>.json "cupons" e a última leitura de cada fonte no
state_<outro>.json; ver Estado.cupons_de_outros_modos). Tudo junto passa por:

- código que dá para digitar (sem "Resgate no link", "Direto no link", id em base64...); sem código, só o desconto
  automático declarado no título ("desconto automático", "aplicado automaticamente"). Na dúvida, fora;
- validade (do cupom ou "até DD/MM/AAAA" no texto) >= agora; sem validade, publicado nos últimos
  config.CUPONS_ATIVOS_DIAS dias. Cupom da página do anúncio (especifico) sem data fica: a fonte acabou de vê-lo;
- código datado (DDMM: TODOSITE0711, eletro0811, SITE0711TODO) vale só no dia: no Mercado Livre sempre, com o DDMM em
  qualquer lugar do código; nas outras lojas, só com o DDMM no fim, perto da data de publicação e sem validade
  explícita (o PS0707 da Hype, com validade, vale até ela);
- testador (cupons_carrinho.json): o código que a loja disse estar expirado/esgotado/inexistente nos últimos 2 dias, e
  que não foi aceito em nenhum teste nesse período, sai. "Não se aplica a este pedido" não prova nada (é do produto);
- duplicado (loja canônica + código em maiúsculas): entra se algum anúncio do código está ativo; fica o anúncio ativo com
  mais informação (desconto, mínimo, teto, validade; empate, o publicado mais recente), com o valor do anúncio mais
  completo do código, ativo ou não (o Promobit gera valores errados no título; o Pelando diz "R$ 400 OFF acima de
  R$ 2.500"). Desconto fixo absurdo (o preço do produto no lugar do desconto) vira "valor a conferir".

O texto: lojas que o monitor mais usa primeiro (ORDEM_LOJAS), depois as outras em ordem alfabética, uma linha em branco
entre lojas; dentro da loja, o maior desconto primeiro, e códigos com o mesmo valor na mesma linha. Tudo que vem de fora
passa por html.escape.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Optional

from . import config
from .estado import marca_cupom
from .models import rotulo_modelo
from .util import TZ_BR, agora, dias_desde, loja_canonica, sem_acentos

# lojas que o monitor mais usa, nesta ordem; as outras vêm depois, em ordem alfabética
ORDEM_LOJAS = ("Mercado Livre", "Amazon", "Magazine Luiza", "KaBuM!", "Shopee", "AliExpress", "Casas Bahia",
               "Americanas", "Fast Shop", "Nuuvem", "Hype", "Netshoes")
# desconto fixo acima disto, sem compra mínima que o justifique, é "valor a conferir"
DESCONTO_REAIS_PLAUSIVEL = 2000.0
LIMITE_MENSAGEM = 3800      # o notificar corta em 4000; sobra espaço para o "(2/3)" e para o HTML
DIAS_TESTADOR = 2            # resultado do testador que ainda vale para tirar um código da lista
CABECALHO = "🎟️ <b>Cupons ativos</b>"   # não começa com "🎟️ <b>Nov" (regras.e_mensagem_de_cupons fica False)
RODAPE = "<i>Códigos de lista (itens selecionados) só valem nos produtos da lista.</i>"
NENHUM = "Nenhum cupom ativo encontrado hoje."

# código que dá para digitar: letras, números, "-" e "_" (sem espaço, "=", "*"...)
_RE_CODIGO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,29}")
# cupom sem código que o título diz ser automático
_RE_AUTOMATICO = re.compile(r"desconto\s+automatico|aplicad[oa]s?\s+automaticamente|automaticamente\s+no\s+carrinho|"
                            r"\bsem\s+(?:precisar\s+de\s+)?(?:cupom|codigo)\b")
# DDMM no código: 4 dígitos sozinhos (nem 3, nem 5)
_RE_DDMM = re.compile(r"(?<!\d)(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])(?!\d)")
_RE_DDMM_NO_FIM = re.compile(r"(?<!\d)(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])$")
# validade escrita no texto: "até 18/11/2026", "Validade: até 18.11", "válido até o dia 30/11"
_RE_ATE_DATA = re.compile(r"\bate\s+(?:o\s+)?(?:dia\s+)?(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?!\d)(?![./]\d)")
# mensagem do testador que diz que o código não existe/acabou (não a que diz que não serve no produto testado)
_RE_EXPIRADO = re.compile(r"nao\s+esta\s+mais\s+disponivel|nao\s+estar\s+mais\s+ativo|nao\s+esta\s+mais\s+ativo|"
                          r"expirad|esgotad|encerrad|inexistente|nao\s+existe|invalido|erro\s+de\s+digitacao|"
                          r"confira\s+se\s+o\s+cupom\s+esta\s+correto")

# ---- valores ----
# "1.200", "1.200,50", "5.229.90" (milhar e centavos com ponto, como o Promobit escreve às vezes), "99,90", "350.00"
_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2}|\.\d{2}(?!\d))?|\d+(?:[.,]\d{1,2})?)"
_RE_PCT = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,2})?)\s*%")
_RE_REAIS = re.compile(
    r"r\$\s?" + _NUM + r"\s*(?:off|de\s+desconto|de\s+volta|em\s+desconto|reais\s+de\s+desconto)\b"
    r"|(?:economiz\w*|ganhe|desconto\s+de|oferece|concede|economia\s+de|abatimento\s+de)\s+(?:ate\s+)?r\$\s?" + _NUM)
# Pelando sem "OFF": "Cupom Aliexpress R$ 490 em R$ 3200", "R$ 785 acima de R$ R$ 4200"
_RE_REAIS_EM = re.compile(r"r\$\s?" + _NUM + r"\s+(?:off\s+)?(?:em|acima\s+de|a\s+partir\s+de|(?:nas|em)\s+compras\s+"
                          r"(?:acima\s+de|a\s+partir\s+de|de))\s+(?:r\$\s?)+" + _NUM)
# compra mínima: "acima de R$ 99", "a partir de", "compra mínima (de)", "mín. R$", "OFF em R$ 59", ", em R$ 59"
_RE_MINIMO = re.compile(
    r"(?:acima\s+de|a\s+partir\s+de|minim[oa](?:\s+de)?:?|min\.|compras?\s+(?:de|a\s+partir\s+de|acima\s+de))\s*"
    r"r\$\s?" + _NUM
    + r"|\b(?:off|desconto)\s+em\s+r\$\s?" + _NUM
    + r"|,\s*em\s+r\$\s?" + _NUM)
# teto do desconto: "limitado à R$ 100", "limite (de desconto:) R$ 500", "máximo (de) R$ 50", "máx. R$", "15% OFF até
# R$ 200", "(até R$ 200)" depois de um desconto em %
_RE_TETO = re.compile(
    r"(?:limitad[oa]|limite)(?:\s+de\s+desconto)?\s*(?:a|de|:)?\s*r\$\s?" + _NUM
    + r"|(?:desconto\s+)?(?:maxim[oa]|max\.)(?:\s+de)?(?:\s+desconto)?\s*:?\s*(?:de\s+)?r\$\s?" + _NUM
    + r"|%\s*(?:off)?\s*[,(]?\s*ate\s+r\$\s?" + _NUM
    + r"|\(\s*ate\s+r\$\s?" + _NUM + r"\s*(?:off\s*)?\)")
# teto da COMPRA (não do desconto): "compras de até R$ 1000", "itens de até R$ 99", "pedidos de no máximo R$ 300"
_RE_TETO_COMPRA = re.compile(r"\b(?:compras?|pedidos?|produtos?|itens?|carrinhos?)\s+(?:de\s+)?(?:ate|no\s+maximo)\s+"
                             r"r\$\s?" + _NUM)
_RE_FRETE = re.compile(r"\bfrete\s+gratis\b|\bentrega\s+gratis\b|\bfrete\s+gratuito\b")
_RE_DESCONTO_NO_FRETE = re.compile(r"\b(?:no|do|em|sobre\s+o)\s+frete\b|\bde\s+frete\b|\bcupom\s+de\s+frete\b")
# lista/seleção de produtos (no título; na regra, sem o aviso genérico do Pelando "a maioria dos cupons do ML...")
_RE_SELECAO = re.compile(r"\bselecionad[oa]s?\b|\bselecao\b|\b(?:produtos|itens)\s+(?:listad|participant|do\s+link|"
                         r"marcad|qualificad)|\blista\s+(?:selecionada|de\s+produtos|de\s+itens)\b|\bem\s+lista\b|"
                         r"\b(?:no|do)\s+link\b|\bconferir\s+lista\b")
_RE_AVISO_GENERICO = re.compile(r"maioria\s+dos\s+cupons")
_RE_SITE_TODO = re.compile(r"\b(?:todo\s+(?:o\s+)?site|site\s+todo|loja\s+toda|toda\s+(?:a\s+)?loja|"
                           r"todos\s+os\s+produtos|em\s+tudo|qualquer\s+produto|sem\s+restric\w*)\b")
_RE_APP = re.compile(r"\[\s*app\b|\bapp\s*[/\]]|\bno\s+app\b|\bpelo\s+app\b|"
                     r"\bvalido\s+(?:somente\s+|apenas\s+|so\s+)?no\s+app\b|\bcupom\s+\w+\s+app\b")
_RE_ASSINANTE = re.compile(r"\bprime\b|\bmeli\s?\+|\bmeli\s+mais\b|\bassinantes?\b")
_RE_NOVOS = re.compile(r"\b(?:1a|primeira)\s+compra\b|\bnov[oa]s\s+(?:clientes|usuarios|contas)\b|"
                       r"\b(?:clientes|usuarios|contas)\s+nov[oa]s\b")
_RE_WHATSAPP = re.compile(r"\bwhats\s?app\b|\bno\s+zap\b")
# o que sobra do título depois do desconto e não diz onde o cupom vale
_RE_RESTO_FORA = re.compile(
    r"\(?\s*(?:acima\s+de|a\s+partir\s+de|minim[oa](?:\s+de)?|min\.|compras?\s+(?:de|acima\s+de|a\s+partir\s+de))\s*"
    r"(?:r\$\s?)+" + _NUM + r"\s*\)?"
    r"|\(?\s*(?:limitad[oa]|limite)(?:\s+de\s+desconto)?\s*(?:a|de|:)?\s*r\$\s?" + _NUM + r"(?:\s*off)?\s*\)?"
    r"|\(?\s*(?:desconto\s+)?(?:maxim[oa]|max\.)(?:\s+de)?\s*:?\s*r\$\s?" + _NUM + r"\s*\)?"
    r"|\(?\s*ate\s+r\$\s?" + _NUM + r"(?:\s*off)?\s*\)?"
    r"|\b(?:em|r\$)\s+r\$\s?" + _NUM +
    r"|\bem\s+(?:suas\s+|nas\s+|todas\s+as\s+)?compras\b|\bnas\s+compras\b|\bem\s+seus\s+pedidos\b"
    r"|\b(?:com|aplicando|aplique|usando|use|utilizando|usar|ao\s+aplicar)\s+(?:o\s+|este\s+|esse\s+|um\s+)?"
    r"(?:cupom|codigo|voucher)\b.*$|\bcom\s+desconto\b.*$"
    r"|\bno\s+carrinho\b.*$|\+\s*pix\b|\bno\s+pix\b|\bvia\s+pix\b"
    r"|\b(?:na|no|da|do)\s+(?:mercado\s+livre|amazon|magalu|magazine\s+luiza|aliexpress|kabum!?|shopee|fast\s*shop|"
    r"casas\s+bahia|americanas|netshoes|nuuvem|hype)\b.*$"
    r"|\b(?:no|pelo)\s+app\b.*$|\[[^\]]*\]")
_RE_PALAVRA_FORA = re.compile(r"selecionad[oa]s?|mercado|livrer?|amazon|magalu|magazine|luiza|aliexpress|kabum|shopee|"
                              r"fastshop|netshoes|nuuvem|americanas|casas|bahia")
_CONECTIVOS = {"em", "na", "no", "nas", "nos", "para", "pra", "de", "da", "do", "das", "dos", "off", "e", "-", "a", "o",
               "com", "os", "as", "itens", "produtos", "desconto", "descontos", "extra", "categoria", "categorias"}
# escopo com estas palavras é frase do site ("sua primeira compra", "desconto no seu carrinho", "voucher Fast Shop",
# "economia", "aplicado"), não onde o cupom vale
_RE_ESCOPO_GENERICO = re.compile(r"\b(?:seu|sua|seus|suas|voce|vc|carrinho|compras?|pedidos?|economia|aplicad\w*|"
                                 r"aplicar|aproveit\w*|garant\w*|cupom|cupons|voucher|valido|valida|promocao|"
                                 r"promocoes|oferta|ofertas)\b")
_NEUTRAS = {"compras", "compra", "pedido", "pedidos", "site", "loja", "produtos", "produto", "itens", "item", "tudo",
            "carrinho", "suas", "seus", "todas", "todos", "cupom", "desconto", "oferta", "ofertas", "promocao", "app",
            "e", "de", "em", "na", "no", "para"}


def _base(c: str) -> str:
    """O caractere sem acento e minúsculo, um para um (o texto normalizado tem o mesmo tamanho do original)."""
    d = unicodedata.normalize("NFKD", c)
    b = next((x for x in d if not unicodedata.combining(x)), c)
    return (b if len(b) == 1 else c).lower()


def _norm1(s: str) -> str:
    return "".join(_base(c) for c in (s or ""))


def _valor(s: str) -> float:
    """'1.200' -> 1200; '99,90' -> 99.9; '350.00' -> 350; '5.229.90' -> 5229.9."""
    s = s.strip()
    if "," in s:
        return float(s.replace(".", "").replace(",", "."))
    if s.count(".") > 1:   # "5.229.90": milhar com ponto e centavos com ponto
        inteiro, cent = s.rsplit(".", 1)
        return float(inteiro.replace(".", "") + "." + cent)
    if re.fullmatch(r"\d{1,3}\.\d{3}", s):
        return float(s.replace(".", ""))
    return float(s)


def _primeiro(m: Optional[re.Match]) -> Optional[float]:
    if not m:
        return None
    g = next((g for g in m.groups() if g), None)
    try:
        return _valor(g) if g else None
    except ValueError:
        return None


def fmt_reais(v: float) -> str:
    """'R$ 1.200' (sem ',00'), 'R$ 99,90'."""
    if abs(v - round(v)) < 0.005:
        return "R$ " + f"{int(round(v)):,}".replace(",", ".")
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(v: float) -> str:
    return (f"{v:.0f}" if abs(v - round(v)) < 0.005 else f"{v:.1f}".replace(".", ",")) + "%"


@dataclass
class Valor:
    desconto: Optional[tuple[str, float]] = None   # ('%', 15.0) | ('R$', 10.0)
    minimo: Optional[float] = None
    teto: Optional[float] = None                   # teto do desconto ("limitado a R$ 100")
    teto_compra: Optional[float] = None            # "compras de até R$ 1.000"
    escopo: str = ""                               # "todo site", "som vídeo eletro", "itens selecionados"...
    selecao: bool = False
    so_frete: bool = False
    duvidoso: bool = False   # desconto em R$ que não pode ser verdade (o Promobit às vezes põe o preço do produto)
    marcas: list[str] = field(default_factory=list)   # "só no app", "Prime", "1ª compra", "WhatsApp"

    @property
    def legivel(self) -> bool:
        return self.desconto is not None or self.so_frete

    @property
    def peso(self) -> float:
        """Para ordenar (maior desconto primeiro): R$ fixo vale ele; % vale o teto ou, sem teto, o % de R$ 1.000."""
        if self.desconto is None or self.duvidoso:
            return 0.5 if self.so_frete else 0.0
        tipo, v = self.desconto
        if tipo == "R$":
            return v
        return self.teto if self.teto else v * 10

    @property
    def informacao(self) -> int:
        """Quanto o anúncio diz (para escolher entre duplicados): o desconto e a compra mínima pesam mais."""
        return 2 * (self.desconto is not None and not self.duvidoso) + 2 * (self.minimo is not None) + \
            (self.teto is not None) + bool(self.escopo)


def _escopo_do_titulo(titulo: str, fim_desconto: int) -> str:
    """O que o título diz sobre onde o cupom vale, depois do desconto: "Som Vídeo Eletro", "em Eletrônicos" ->
    "eletrônicos", "em Gift Cards na Nuuvem com cupom + PIX" -> "gift cards". '' se não sobra nada útil."""
    orig = titulo[fim_desconto:]
    norm = _norm1(orig)
    # apaga (com espaços, mantendo as posições) o que não é escopo
    chars = list(orig)
    for m in _RE_RESTO_FORA.finditer(norm):
        for i in range(m.start(), m.end()):
            chars[i] = " "
    resto = "".join(chars)
    # corta em pontuação que fecha a frase/abre outra condição
    resto = re.split(r"[|(:;!?]|\s[-–]\s|,|\.\s", resto)[0]
    # o nome da loja e a palavra "selecionados" (a marca "itens selecionados" já diz isso) não são escopo
    palavras = [p for p in resto.split() if not _RE_PALAVRA_FORA.fullmatch(_norm1(p).strip(".,!"))]
    while palavras and _norm1(palavras[0]).strip(".,") in _CONECTIVOS:
        palavras.pop(0)
    while palavras and _norm1(palavras[-1]).strip(".,") in _CONECTIVOS:
        palavras.pop()
    if not palavras or all(_norm1(p).strip(".,") in _NEUTRAS for p in palavras) \
            or not re.search(r"[^\W\d_]{3}", " ".join(palavras)) \
            or _RE_ESCOPO_GENERICO.search(_norm1(" ".join(palavras))):
        return ""
    texto = " ".join(palavras).strip(" .,-").lower()
    if len(texto) > 32:
        texto = texto[:32].rsplit(" ", 1)[0] + "…"
    return texto


def valor_do_cupom(titulo: str, regra: str = "") -> Valor:
    """Desconto, compra mínima, teto, escopo e marcas do cupom, lidos do título (e da regra quando o título não diz)."""
    from .regras import _conserta_mojibake

    titulo = _conserta_mojibake(titulo or "")
    regra = _conserta_mojibake(regra or "")
    t, r = _norm1(titulo), _norm1(regra)
    r_util = "" if _RE_AVISO_GENERICO.search(r) else r   # o aviso genérico do Pelando no ML não é a regra do cupom
    v = Valor()
    fim = None
    for txt, do_titulo in ((t, True), (r, False)):
        m = _RE_PCT.search(txt)
        if m and 0 < _valor(m.group(1)) <= 100:
            v.desconto = ("%", _valor(m.group(1)))
            fim = m.end() if do_titulo else None
            break
        m = _RE_REAIS.search(txt)
        if m:
            v.desconto = ("R$", _primeiro(m) or 0.0)
            fim = m.end() if do_titulo else None
            break
        m = _RE_REAIS_EM.search(txt)
        if m:
            v.desconto = ("R$", _valor(m.group(1)))
            v.minimo = _valor(m.group(2))
            fim = m.end() if do_titulo else None
            break
    if v.desconto and v.desconto[1] <= 0:
        v.desconto = None
    # mínimo e tetos: do título; se ele não diz, da regra
    for txt in (t, r):
        if v.minimo is None:
            mins = [x for x in (_primeiro(m) for m in _RE_MINIMO.finditer(txt)) if x]
            if mins:
                v.minimo = min(mins)
        if v.teto is None:
            v.teto = _primeiro(_RE_TETO.search(txt))
        if v.teto_compra is None:
            v.teto_compra = _primeiro(_RE_TETO_COMPRA.search(txt))
    if v.minimo is not None and v.minimo <= 1:
        v.minimo = None   # "acima de R$ 1" é sem mínimo
    if v.desconto and v.desconto[0] == "R$" and v.teto is not None and abs(v.teto - v.desconto[1]) < 0.01:
        v.teto = None     # "Economize até R$ 85" é o próprio desconto
    if v.teto is not None and v.teto_compra is not None and abs(v.teto - v.teto_compra) < 0.01:
        v.teto = None     # "10% OFF em compras de até R$ 1000": é o teto da compra
    # "ganhe R$ 5.229,90 OFF" sem compra mínima (ou maior que metade dela): é o preço do produto, não o desconto
    if v.desconto and v.desconto[0] == "R$" and v.desconto[1] > DESCONTO_REAIS_PLAUSIVEL \
            and (v.minimo is None or v.desconto[1] > v.minimo / 2):
        v.duvidoso = True
    # frete: "frete grátis" sem desconto no preço
    if _RE_FRETE.search(t) and v.desconto is None:
        v.so_frete = True
    elif v.desconto and v.desconto[0] == "R$" and _RE_DESCONTO_NO_FRETE.search(t) and not _RE_SITE_TODO.search(t):
        v.so_frete = True
    # escopo
    if _RE_SITE_TODO.search(t):
        v.escopo = "todo site"
    elif fim is not None:
        v.escopo = _escopo_do_titulo(titulo, fim)
    v.selecao = bool(_RE_SELECAO.search(t) or _RE_SELECAO.search(r_util))
    if v.selecao and v.escopo == "todo site" and not _RE_SELECAO.search(t):
        v.escopo = ""     # o título (gerado pelo site) diz "todo o site", a regra diz "produtos selecionados no link"
    texto = f"{t} {r_util}"
    if _RE_APP.search(texto):
        v.marcas.append("só no app")
    if _RE_ASSINANTE.search(texto):
        v.marcas.append("Prime/assinante")
    if _RE_NOVOS.search(texto):
        v.marcas.append("1ª compra")
    if _RE_WHATSAPP.search(texto):
        v.marcas.append("WhatsApp")
    return v


def texto_do_valor(v: Valor, titulo: str = "") -> str:
    """'15% OFF · mín. R$ 500 · até R$ 100 · som vídeo eletro' (texto puro, sem HTML). Sem desconto legível, o título
    resumido (até ~70 caracteres)."""
    partes: list[str] = []
    if v.so_frete:
        partes.append(f"{fmt_reais(v.desconto[1])} OFF no frete" if v.desconto else "frete grátis")
    elif v.desconto and v.duvidoso:
        partes.append(f"valor a conferir (o anúncio diz {fmt_reais(v.desconto[1])} OFF)")
    elif v.desconto:
        tipo, x = v.desconto
        partes.append(f"{_fmt_pct(x)} OFF" if tipo == "%" else f"{fmt_reais(x)} OFF")
    else:
        t = re.sub(r"\s+", " ", titulo or "").strip()
        partes.append(t if len(t) <= 70 else t[:69].rsplit(" ", 1)[0] + "…")
    if v.minimo:
        partes.append(f"mín. {fmt_reais(v.minimo)}")
    if v.teto and (not v.desconto or v.desconto[0] == "%" or v.so_frete):
        partes.append(f"até {fmt_reais(v.teto)}")
    if v.teto_compra:
        partes.append(f"compras até {fmt_reais(v.teto_compra)}")
    if v.legivel and v.escopo:
        partes.append(v.escopo)
    if v.selecao and "selecionad" not in v.escopo and "lista" not in v.escopo:
        partes.append("itens selecionados")
    partes += v.marcas
    return " · ".join(partes)


# ---- "ativo" ----
def codigo_valido(codigo: Any) -> bool:
    return bool(_RE_CODIGO.fullmatch(str(codigo or "").strip()))


def _data(iso: Any) -> Optional[datetime]:
    """ISO -> datetime com fuso (data sem hora vale até o fim do dia)."""
    s = str(iso or "").strip()
    if not s:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.fromisoformat(s).replace(hour=23, minute=59, second=59, tzinfo=TZ_BR)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ_BR)
    except ValueError:
        return None


def _data_ddmm(dia: int, mes: int, perto_de: date) -> Optional[date]:
    """A data DD/MM no ano mais perto de `perto_de` (dezembro/janeiro atravessam o ano)."""
    melhores = []
    for ano in (perto_de.year - 1, perto_de.year, perto_de.year + 1):
        try:
            melhores.append(date(ano, mes, dia))
        except ValueError:
            continue
    return min(melhores, key=lambda d: abs((d - perto_de).days)) if melhores else None


def validade_no_texto(reg: dict) -> Optional[datetime]:
    """"até 18/11/2026", "Validade: até 18.11" no título/regra (a maior data, fim do dia). Sem data -> None."""
    texto = _norm1(f"{reg.get('titulo') or ''} {reg.get('regra') or ''}")
    pub = _data(reg.get("publicado"))
    base = pub.date() if pub else agora().date()
    datas = []
    for m in _RE_ATE_DATA.finditer(texto):
        dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
        try:
            if ano:
                a = int(ano)
                d = date(a + 2000 if a < 100 else a, mes, dia)
            else:
                d = _data_ddmm(dia, mes, base)
        except ValueError:
            d = None
        if d:
            datas.append(d)
    if not datas:
        return None
    d = max(datas)
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ_BR)


def data_no_codigo(codigo: str, loja: str, publicado: Any = None) -> Optional[tuple[int, int]]:
    """(dia, mês) de um código datado ("TODOSITE0711" -> (7, 11)). No Mercado Livre o DDMM pode estar em qualquer
    lugar do código ("SITE0711TODO"); nas outras lojas só no fim, e só quando bate (até 7 dias) com a publicação."""
    cod = str(codigo or "")
    if loja_canonica(loja) == "Mercado Livre":
        m = _RE_DDMM.search(cod)
        return (int(m.group(1)), int(m.group(2))) if m else None
    m = _RE_DDMM_NO_FIM.search(cod)
    if not m:
        return None
    dia, mes = int(m.group(1)), int(m.group(2))
    pub = _data(publicado)
    if pub is None:
        return dia, mes
    d = _data_ddmm(dia, mes, pub.date())
    return (dia, mes) if d and -3 <= (d - pub.date()).days <= 7 else None


def expirados_no_testador(dados: Optional[dict] = None, dias: float = DIAS_TESTADOR) -> set[str]:
    """'Loja|CÓDIGO' que o testador (cupons_carrinho.json) viu expirado/esgotado/inexistente nos últimos `dias` dias e
    não viu aceito nenhuma vez nesse período. `dados` None: lê o arquivo (ausente ou quebrado: nada)."""
    if dados is None:
        try:
            dados = json.loads((config.DIR_DADOS / "cupons_carrinho.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
    if not isinstance(dados, dict):
        return set()
    ruins: set[str] = set()
    bons: set[str] = set()
    for chave_loja, bloco in dados.items():
        cupons = bloco.get("cupons") if isinstance(bloco, dict) else None
        if not isinstance(cupons, dict):
            continue
        loja = loja_canonica(chave_loja)
        for chave, reg in cupons.items():
            if not isinstance(reg, dict):
                continue
            d = dias_desde(reg.get("testado_em"))
            if d is None or d > dias:
                continue
            marca = marca_cupom(loja, str(chave).split("@", 1)[0])
            if reg.get("aceito") or reg.get("status") in ("aceito", "so_frete"):
                bons.add(marca)
            elif _RE_EXPIRADO.search(sem_acentos(str(reg.get("mensagem") or "")).lower()):
                ruins.add(marca)
    return ruins - bons


def motivo_inativo(reg: dict, expirados: set[str] = frozenset(), dias: Optional[float] = None) -> str:
    """'' quando o cupom está ativo; senão, o motivo ('sem código', 'vencido', 'código de 07/11'...)."""
    dias = config.CUPONS_ATIVOS_DIAS if dias is None else dias
    codigo = str(reg.get("codigo") or "").strip()
    loja = loja_canonica(str(reg.get("loja") or ""))
    texto = _norm1(f"{reg.get('titulo') or ''} {reg.get('regra') or ''} {codigo}")
    if not codigo_valido(codigo) and not _RE_AUTOMATICO.search(texto):
        return "sem código"
    if codigo_valido(codigo) and marca_cupom(loja, codigo) in expirados:
        return "expirado no testador"
    agora_ = agora()
    validade = _data(reg.get("validade")) or validade_no_texto(reg)
    if validade is not None and validade < agora_:
        return "vencido"
    ddmm = data_no_codigo(codigo, loja, reg.get("publicado")) if codigo_valido(codigo) else None
    if ddmm is not None and (loja == "Mercado Livre" or validade is None):
        return "" if ddmm == (agora_.day, agora_.month) else f"código de {ddmm[0]:02d}/{ddmm[1]:02d}"
    if validade is not None:
        return ""
    d = dias_desde(reg.get("publicado"))
    if d is None:
        return "" if reg.get("especifico") else "sem data"
    return "" if d <= dias else f"publicado há {d:.0f} dias"


def _como_dict(c: Any) -> Optional[dict]:
    if isinstance(c, dict):
        return c
    to = getattr(c, "to_dict", None)
    return to() if callable(to) else None


def cupons_ativos(regs: Iterable[Any], expirados: Optional[set[str]] = None,
                  dias: Optional[float] = None) -> dict[str, list[dict]]:
    """{loja: [cupons ativos, o maior desconto primeiro]}; cada cupom é o registro (dict) com '_valor' (Valor) e
    '_texto' (o valor pronto, sem HTML). `expirados`: None lê o testador."""
    from . import produtos

    if expirados is None:
        expirados = expirados_no_testador()
    # todos os anúncios de cada cupom (loja + código), ativos ou não
    grupos: dict[str, list[dict]] = {}
    for c in regs:
        reg = _como_dict(c)
        if not reg:
            continue
        if config.TVS_DESLIGADAS and reg.get("modelo") and produtos.eh_tv(str(reg["modelo"])):
            continue
        loja = loja_canonica(str(reg.get("loja") or ""))
        codigo = str(reg.get("codigo") or "").strip()
        chave = marca_cupom(loja, codigo) if codigo_valido(codigo) else \
            f"{loja}|AUTO:{re.sub(r'[^a-z0-9]+', ' ', _norm1(reg.get('titulo') or '')).strip()}"
        grupos.setdefault(chave, []).append({
            **reg, "loja": loja, "codigo": codigo if codigo_valido(codigo) else "",
            "_valor": valor_do_cupom(reg.get("titulo") or "", reg.get("regra") or ""),
            "_ativo": not motivo_inativo(reg, expirados, dias)})
    melhores: dict[str, dict] = {}
    for chave, grupo in grupos.items():
        ativos = [r for r in grupo if r["_ativo"]]
        if not ativos:
            continue
        melhor = _o_melhor(ativos)
        # o valor do anúncio que diz mais, mesmo que ele não conte como ativo (o mesmo código no Pelando, publicado há
        # mais dias, com "R$ 400 OFF acima de R$ 2.500", e no Promobit, com validade e um valor gerado errado)
        mais = _o_melhor(grupo)
        if mais is not melhor and mais["_valor"].informacao > melhor["_valor"].informacao:
            melhor = {**melhor, "_valor": mais["_valor"]}
        melhores[chave] = melhor
    por_loja: dict[str, list[dict]] = {}
    for reg in melhores.values():
        reg["_texto"] = texto_do_valor(reg["_valor"], reg.get("titulo") or "")
        por_loja.setdefault(reg["loja"], []).append(reg)
    for lista in por_loja.values():
        lista.sort(key=lambda r: (-r["_valor"].peso, not r.get("especifico"), r["_valor"].minimo or 0,
                                  r["codigo"].upper()))
    return por_loja


def _o_melhor(regs: list[dict]) -> dict:
    melhor = regs[0]
    for r in regs[1:]:
        if _melhor_registro(r, melhor):
            melhor = r
    return melhor


def _melhor_registro(a: dict, b: dict) -> bool:
    """O registro `a` diz mais que `b`? Mais informação (desconto, mínimo, teto, escopo, validade); empate, o mais
    novo."""
    ia = a["_valor"].informacao + bool(a.get("validade") or validade_no_texto(a))
    ib = b["_valor"].informacao + bool(b.get("validade") or validade_no_texto(b))
    if ia != ib:
        return ia > ib
    return str(a.get("publicado") or "") > str(b.get("publicado") or "")


def ordem_das_lojas(lojas: Iterable[str]) -> list[str]:
    """As lojas que o monitor mais usa primeiro (ORDEM_LOJAS), depois as outras em ordem alfabética."""
    pos = {l: i for i, l in enumerate(ORDEM_LOJAS)}
    return sorted(lojas, key=lambda l: (pos.get(l, len(pos)), sem_acentos(l).lower()))


def _texto_da_linha(reg: dict) -> str:
    """O que vem depois do código: o valor, o anúncio (cupom da página do produto) e o vencimento (até 31 dias)."""
    texto = reg.get("_texto") or texto_do_valor(reg.get("_valor") or Valor(), reg.get("titulo") or "")
    if reg.get("especifico"):
        modelo = reg.get("modelo")
        texto += f" · só no anúncio do {rotulo_modelo(str(modelo))}" if modelo else " · só no anúncio"
    validade = _data(reg.get("validade")) or validade_no_texto(reg)
    if validade is not None and (validade - agora()).days <= 31:
        texto += f" · vence {validade:%d/%m}"
    return texto


def _bloco(loja: str, regs: list[dict]) -> list[str]:
    """O título da loja e uma linha por valor: códigos diferentes com o MESMO valor (AEMEGA8, AFFNOV08 e Pelando8:
    R$ 580 OFF acima de R$ 3.700) ficam na mesma linha, cada um no seu <code>."""
    grupos: list[tuple[str, list[dict]]] = []
    onde: dict[str, int] = {}
    maximo = config.CUPONS_ATIVOS_MAX_POR_LOJA
    mostra = regs[:maximo] if maximo > 0 else regs
    for r in mostra:
        texto = _texto_da_linha(r)
        agrupa = bool(r.get("codigo")) and not r.get("especifico")
        if agrupa and texto in onde:
            grupos[onde[texto]][1].append(r)
            continue
        if agrupa:
            onde[texto] = len(grupos)
        grupos.append((texto, [r]))
    linhas = [f"🛒 <b>{html.escape(loja.upper(), quote=False)}</b> ({len(regs)})"]
    for texto, rs in grupos:
        if rs[0].get("codigo"):
            ini = "• " + " ou ".join(f"<code>{html.escape(r['codigo'], quote=False)}</code>" for r in rs)
        else:
            ini = "• <i>sem código (automático)</i>"
        linhas.append(f"{ini} — {html.escape(texto, quote=False)}" + (" ⭐" if rs[0].get("especifico") else ""))
    if len(mostra) < len(regs):
        linhas.append(f"<i>… e mais {len(regs) - len(mostra)} (os de menor desconto)</i>")
    return linhas


def mensagens(por_loja: dict[str, list[dict]], quando: Optional[datetime] = None,
              limite: int = LIMITE_MENSAGEM) -> list[str]:
    """O texto da lista, dividido em mensagens de até `limite` caracteres sem cortar uma loja no meio (a loja que
    sozinha não cabe é cortada entre linhas e continua com "(cont.)"). Sem cupom: uma mensagem dizendo isso."""
    quando = quando or agora()
    total = sum(len(v) for v in por_loja.values())
    cab = f"{CABECALHO} · {quando:%d/%m %H:%M}"
    if not total:
        return [f"{cab}\n{NENHUM}"]
    resumo = (f"<i>{total} cupo{'m' if total == 1 else 'ns'} em {len(por_loja)} loja{'' if len(por_loja) == 1 else 's'}"
              " · toque no código para copiar</i>")
    folga = 12   # " (10/10)" no cabeçalho
    cabe = limite - len(cab) - len(resumo) - folga - 4   # o maior bloco que cabe numa mensagem (até na primeira)
    blocos: list[str] = []
    for loja in ordem_das_lojas(por_loja):
        linhas = _bloco(loja, por_loja[loja])
        bloco = "\n".join(linhas)
        if len(bloco) <= cabe:
            blocos.append(bloco)
            continue
        # loja grande demais: corta entre linhas, repetindo o título com "(cont.)"
        titulo = linhas[0]
        atual = titulo
        for ln in linhas[1:]:
            if len(atual) + 1 + len(ln) > cabe:
                blocos.append(atual)
                atual = titulo.replace(f"({len(por_loja[loja])})", "(cont.)") + "\n" + ln
            else:
                atual += "\n" + ln
        blocos.append(atual)
    partes: list[list[str]] = [[resumo]]
    tamanho = len(cab) + folga + len(resumo)
    for bloco in blocos + [RODAPE]:
        if len(partes[-1]) > (1 if len(partes) == 1 else 0) and tamanho + 2 + len(bloco) > limite:
            partes.append([])
            tamanho = len(CABECALHO) + folga
        partes[-1].append(bloco)
        tamanho += 2 + len(bloco)
    n = len(partes)
    out = []
    for i, corpo in enumerate(partes, 1):
        topo = cab if i == 1 else CABECALHO
        if n > 1:
            topo += f" ({i}/{n})"
        if i == 1:
            out.append(topo + "\n" + corpo[0] + ("\n\n" + "\n\n".join(corpo[1:]) if corpo[1:] else ""))
        else:
            out.append(topo + "\n\n" + "\n\n".join(corpo))
    return out


def mensagens_cupons_ativos(regs: Iterable[Any], expirados: Optional[set[str]] = None,
                            quando: Optional[datetime] = None, limite: int = LIMITE_MENSAGEM) -> list[str]:
    """A lista "🎟️ Cupons ativos" pronta para o Telegram (uma ou mais mensagens)."""
    return mensagens(cupons_ativos(regs, expirados), quando, limite)
