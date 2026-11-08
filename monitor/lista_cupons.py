"""Lista diária "🎟️ Cupons ativos" no Telegram (pedido de 08/11/2026).

Uma mensagem (ou mais, se passar de ~3800 caracteres) com SÓ os cupons ativos de cada loja: o código (em <code>, para
copiar com um toque) e o valor do desconto (15% OFF, R$ 20 OFF, compra mínima, teto, escopo curto). Não é a mensagem de
"Novo cupom aplicável" de regras.gerar_alertas: aqui entra todo cupom ativo da loja, sirva ou não no PS5/GTA 6.

De onde vêm os cupons (run.py): os desta rodada, os da última leitura de cada fonte no state deste modo (fonte que não
trouxe nada agora) e os do outro modo (latest_<outro>.json "cupons" e a última leitura de cada fonte no
state_<outro>.json; ver Estado.cupons_de_outros_modos). Tudo junto passa por:

- código que dá para digitar (sem "Resgate no link", "Direto no link", id em base64...); sem código, só o desconto
  automático declarado no título ("desconto automático", "aplicado automaticamente"). Na dúvida, fora;
- validade (do cupom ou "até DD/MM/AAAA" / "até o fim do mês" no texto) >= agora; a validade do cupom que parece
  data-padrão do anúncio (publicado há mais de VALIDADE_PADRAO_IDADE dias e validade em 31/12 ou a mais de
  VALIDADE_PADRAO_SPAN dias da publicação) não conta. Sem validade, publicado nos últimos config.CUPONS_ATIVOS_DIAS
  dias; no Pelando, que só mostra (e o coletor só lê) cupom com status ativo, config.CUPONS_ATIVOS_DIAS_PELANDO dias.
  Cupom da página do anúncio (especifico) sem data fica: a fonte acabou de vê-lo;
- código datado (DDMM: TODOSITE0711, eletro0811, SITE0711TODO) vale só no dia: no Mercado Livre sempre, com o DDMM em
  qualquer lugar do código; nas outras lojas, só com o DDMM no fim, perto da data de publicação e sem validade
  explícita (o PS0707 da Hype, com validade, vale até ela);
- testador (cupons_carrinho.json): o código que a loja disse estar expirado/esgotado/inexistente nos últimos 2 dias, e
  que não foi aceito em nenhum teste nesse período, sai. "Não se aplica a este pedido" não prova nada (é do produto);
- duplicado (loja canônica + código em maiúsculas): entra se algum anúncio do código está ativo; fica o anúncio ativo com
  mais informação (desconto, mínimo, teto, validade; empate, o publicado mais recente), com o valor do anúncio mais
  completo do código, ativo ou não (o título do anúncio no Promobit às vezes traz outro valor; o Pelando diz "R$ 400
  OFF acima de R$ 2.500"). Dois anúncios igualmente completos com valores diferentes: o outro valor vai junto ("outro
  anúncio diz R$ 670 OFF"). Desconto fixo acima do plausível (o preço do produto no lugar do desconto) vira "valor a
  conferir".

O valor: o desconto do título ("até 60%" de vitrine só quando nada diz o valor do cupom: a regra "10% DE DESCONTO" vale
mais, e sem ela sai "até 60% OFF"); onde vale vem do que segue o desconto ("em Eletrônicos") ou, sem isso, do produto que
vem antes ("Meta Quest 3 512GB com R$ 500 de desconto") ou da regra do Promobit ("R$ 100 OFF ASICS DYNABLAST 6").

O texto: lojas que o monitor mais usa primeiro (ORDEM_LOJAS), depois as outras em ordem alfabética, uma linha em branco
entre lojas; dentro da loja, os cupons do anúncio monitorado (⭐), depois os gerais (todo site, sem restrição) e por fim
os de lista, categoria ou produto, cada grupo com o maior desconto primeiro; códigos com o mesmo valor na mesma linha
(até MAX_CODIGOS_POR_LINHA); no máximo config.CUPONS_ATIVOS_MAX_POR_LOJA linhas por loja. Tudo que vem de fora passa
por html.escape.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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
MAX_CODIGOS_POR_LINHA = 6    # códigos com o mesmo valor numa linha; o 7º abre outra linha (a linha nunca passa da mensagem)
# validade de anúncio antigo que parece data-padrão (31/12, ou +2 anos): publicado há mais disto...
VALIDADE_PADRAO_IDADE = 60
# ...e validade a mais disto da publicação (ou em 31/12): conta como sem validade
VALIDADE_PADRAO_SPAN = 180
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
# validade escrita no texto: "até 18/11/2026", "Validade: até 18.11", "válido até o dia 30/11" (não "em até 10/12 vezes")
_RE_ATE_DATA = re.compile(r"\bate\s+(?:o\s+)?(?:dia\s+)?(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?!\d)(?![./]\d)"
                          r"(?!\s*(?:x\b|vezes\b|parcelas\b))")
# "Oferta válida até o fim do mês": o último dia do mês da publicação
_RE_FIM_DO_MES = re.compile(r"\bate\s+o\s+(?:fim|final)\s+(?:do|deste)\s+mes\b")
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
    r"|(?:economiz\w*|ganhe|desconto\s+de|oferece|concede|economia\s+de|abatimento\s+de|cupom\s+de)\s+(?:ate\s+)?"
    r"r\$\s?" + _NUM)
# Pelando sem "OFF": "Cupom Aliexpress R$ 490 em R$ 3200", "R$ 785 acima de R$ R$ 4200", "R$ 30 para compras acima de"
_RE_REAIS_EM = re.compile(r"r\$\s?" + _NUM + r"\s+(?:off\s+)?(?:em|acima\s+de|a\s+partir\s+de|(?:nas|em|para)\s+compras\s+"
                          r"(?:acima\s+de|a\s+partir\s+de|de))\s+(?:r\$\s?)+" + _NUM)
# o desconto vem logo depois de "até" ("Até 60% OFF", "Garanta até R$ 100 de desconto"): é o máximo da vitrine
_RE_ATE_ANTES = re.compile(r"\bate\s+(?:de\s+)?$")
# "100%" do nome do produto ("Whey 100% Pure", "100% algodão"): só é desconto com off/desconto logo depois
_RE_PCT_DESCONTO_DEPOIS = re.compile(r"\s*(?:off\b|de\s+desconto|desconto)")
# teto do desconto em % escrito depois de outra coisa: "15% OFF no Pix até R$ 200"
_RE_ATE_REAIS = re.compile(r"\bate\s+r\$\s?" + _NUM)
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
    + r"|\(\s*ate\s+r\$\s?" + _NUM + r"\s*(?:off\s*)?\)"
    + r"|\b(?:frete|entrega)\s+(?:gratis|gratuit[oa])\s+(?:de\s+)?ate\s+r\$\s?" + _NUM)
# teto da COMPRA (não do desconto): "compras de até R$ 1000", "itens de até R$ 99", "pedidos de no máximo R$ 300"
_RE_TETO_COMPRA = re.compile(r"\b(?:compras?|pedidos?|produtos?|itens?|carrinhos?)\s+(?:de\s+)?(?:ate|no\s+maximo)\s+"
                             r"r\$\s?" + _NUM)
_RE_FRETE = re.compile(r"\bfrete\s+gratis\b|\bentrega\s+gratis\b|\bfrete\s+gratuito\b")
_RE_DESCONTO_NO_FRETE = re.compile(r"\b(?:no|do|em|sobre\s+o)\s+frete\b|\bde\s+frete\b|\bcupom\s+de\s+frete\b")
# lista/seleção de produtos (no título; na regra, sem o aviso genérico do Pelando "a maioria dos cupons do ML...")
_RE_SELECAO = re.compile(r"\bselecionad[oa]s?\b|\bselecao\b|\b(?:produtos|itens)\s+(?:listad|participant|do\s+link|"
                         r"marcad|qualificad)|\blista\s+(?:selecionada|de\s+produtos|de\s+itens)\b|\bem\s+lista\b|"
                         r"\b(?:no|do)\s+link\b|\bconferir\s+lista\b|\bda\s+lista\b|\bparticipantes\b")
_RE_AVISO_GENERICO = re.compile(r"maioria\s+dos\s+cupons")
_RE_SITE_TODO = re.compile(r"\b(?:todo\s+(?:o\s+)?site|site\s+todo|loja\s+toda|toda\s+(?:a\s+)?loja|"
                           r"todos\s+os\s+produtos|todas\s+as\s+lojas|em\s+tudo|qualquer\s+produto|sem\s+restric\w*)\b")
_RE_APP = re.compile(r"\[\s*app\b|\bapp\s*[/\]]|\bno\s+app\b|\bpelo\s+app\b|"
                     r"\bvalido\s+(?:somente\s+|apenas\s+|so\s+)?no\s+app\b|\bcupom\s+\w+\s+app\b")
_RE_ASSINANTE = re.compile(r"\bprime\b|\bmeli\s?\+|\bmeli\s+mais\b|\bassinantes?\b")
_RE_NOVOS = re.compile(r"\b(?:1a|primeira)\s+compra\b|\bnov[oa]s\s+(?:clientes|usuarios|contas|compradores)\b|"
                       r"\b(?:clientes|usuarios|contas|compradores)\s+nov[oa]s\b")
_RE_WHATSAPP = re.compile(r"\bwhats\s?app\b|\bno\s+zap\b")
# "Cupom funcionando para quem resgatou no início da promoção" (canais do Telegram): só serve a quem já resgatou
_RE_RESGATOU = re.compile(r"\bquem\s+(?:ja\s+)?resgatou\b")
MARCA_RESGATOU = "só p/ quem resgatou"
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
    # frete e parcelamento não dizem onde o cupom vale ("+ frete grátis", "no frete", "em até 10x sem juros")
    r"|\+?\s*\b(?:e\s+|com\s+)?(?:frete|entrega)\s+(?:gratis|gratuit[oa])\b(?:\s+(?:de\s+)?ate\s+r\$\s?" + _NUM + r")?"
    r"|\b(?:no|do|de|o)\s+frete\b|\b(?:em\s+)?ate\s+\d{1,2}\s*x\b.*$|\bsem\s+juros\b.*$"
    r"|\b(?:na|no|da|do)\s+(?:mercado\s+livre|amazon|magalu|magazine\s+luiza|aliexpress|kabum!?|shopee|fast\s*shop|"
    r"casas\s+bahia|americanas|netshoes|nuuvem|hype)\b.*$"
    r"|\b(?:no|pelo)\s+app\b.*$|\[[^\]]*\]"
    r"|\b(?:participantes?|qualificad[oa]s?|listad[oa]s?|elegiveis)\b.*$")
# nome de loja com duas palavras ("Fast Shop", "Hype Games"): sai inteiro (o "shop" do "Pet Shop" fica)
_RE_LOJA_FRASE = re.compile(r"\bfast\s*shop\b|\bhype\s+games\b|\bmercado\s+li[vb]re\b|\bmagazine\s+luiza\b|"
                            r"\bcasas\s+bahia\b")
_RE_PALAVRA_FORA = re.compile(r"selecionad[oa]s?|mercado|livrer?|libre|amazon|magalu|magazine|luiza|aliexpress|kabum|shopee|"
                              r"fastshop|netshoes|nuuvem|americanas|casas|bahia|hype")
_CONECTIVOS = {"em", "na", "no", "nas", "nos", "para", "pra", "de", "da", "do", "das", "dos", "off", "e", "-", "a", "o",
               "com", "os", "as", "itens", "produtos", "desconto", "descontos", "extra", "categoria", "categorias",
               "exclusivo", "exclusiva", "exclusivos", "todas", "todos", "versoes", "versao", "produto", "+"}
# escopo com estas palavras é frase do site ("sua primeira compra", "desconto no seu carrinho", "voucher Fast Shop",
# "economia", "aplicado"), não onde o cupom vale
_RE_ESCOPO_GENERICO = re.compile(r"\b(?:seu|sua|seus|suas|voce|vc|carrinho|compras?|pedidos?|economia|aplicad\w*|"
                                 r"aplicar|aproveit\w*|garant\w*|cupom|cupons|voucher|valido|valida|promocao|"
                                 r"promocoes|oferta|ofertas|lista|link|usuarios|clientes|vendid\w*|entregue\w*|"
                                 r"exceto|utilizad\w*|carteira|expira\w*|clic\w*|clique|ver\s+mais|regulamento)\b")
_NEUTRAS = {"compras", "compra", "pedido", "pedidos", "site", "loja", "produtos", "produto", "itens", "item", "tudo",
            "carrinho", "suas", "seus", "todas", "todos", "cupom", "desconto", "oferta", "ofertas", "promocao", "app",
            "e", "de", "em", "na", "no", "para"}
# o produto ANTES do desconto ("Adquira o Meta Quest 3 512GB com R$500 de desconto", "Faça um upgrade com o Intel Core
# i5-12600K e 15% OFF", "Válido para o produto Notebook Lenovo..."): saem as palavras de chamada do começo...
_CHAMADA = {"adquira", "garanta", "garante", "compre", "aproveite", "leve", "ganhe", "obtenha", "receba", "confira",
            "pegue", "turbine", "faca", "consiga", "tenha", "ter", "ative", "aplique", "use", "usar", "economize",
            "economizar", "seu", "sua", "seus", "suas", "setup", "upgrade", "um", "uma", "o", "a", "os", "as", "com", "no",
            "na", "nos", "nas", "em", "para", "pra", "e", "de", "do", "da", "dos", "das", "valido", "valida", "exclusivo",
            "exclusiva", "produto", "produtos", "itens", "item", "selecao", "desconto", "ate", "cupom", "codigo",
            "oferece", "concede", "por", "ganhar", "desbloqueie", "desfrute", "proporciona", "utilize", "receber",
            "escolha", "encontre", "descubra", "conheca", "acesse", "renove", "aproveitar", "+"}
# ...e, se sobrar frase de campanha ("Os melhores itens do site", "A chance de", "Marcas em alta"), não é produto
_RE_ANTES_GENERICO = re.compile(r"\b(?:melhores|site|marcas?|alta|chance|momento|chegou|especial|super|mega|black|friday|"
                                r"esquenta|hora|imperdive\w*|exclusiv\w*|prime|economi\w*|descont\w*|online|todos?|tudo|"
                                r"precinho|login|cpf|regulamento|confira|corra|novidades?|lancamentos?|promocional|"
                                r"hoje)\b")
_MAX_PALAVRAS_PRODUTO = 8


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
    duvidoso: bool = False   # desconto em R$ acima do plausível (no anúncio, o preço do produto no lugar do desconto)
    ate: bool = False        # "até 60% OFF": o máximo da vitrine, não o valor certo do cupom
    marcas: list[str] = field(default_factory=list)   # "só no app", "Prime", "1ª compra", "WhatsApp"

    @property
    def legivel(self) -> bool:
        return self.desconto is not None or self.so_frete

    @property
    def restrito(self) -> bool:
        """Vale só numa lista, categoria, produto, no frete ou para um público (ou o valor não é certo)."""
        return bool(self.selecao or self.so_frete or self.duvidoso or self.ate or self.desconto is None
                    or (self.escopo and self.escopo != "todo site") or any(m != "só no app" for m in self.marcas))

    @property
    def peso(self) -> float:
        """Para ordenar (maior desconto primeiro): R$ fixo vale ele; % vale o teto ou, sem teto, o % de R$ 1.000. O
        "até X" de vitrine vale metade."""
        if self.desconto is None or self.duvidoso:
            return 0.5 if self.so_frete else 0.0
        tipo, v = self.desconto
        p = v if tipo == "R$" else (self.teto if self.teto else v * 10)
        return p / 2 if self.ate else p

    @property
    def informacao(self) -> int:
        """Quanto o anúncio diz (para escolher entre duplicados): o desconto e a compra mínima pesam mais."""
        return 2 * (self.desconto is not None and not self.duvidoso) + 2 * (self.minimo is not None) + \
            (self.teto is not None) + bool(self.escopo)


_ESCOPO_MAX = 36   # caracteres do escopo na linha (o resto vira "…")


def _encurta(texto: str) -> str:
    texto = texto.strip(" .,-").lower()
    if len(texto) > _ESCOPO_MAX:
        texto = texto[:_ESCOPO_MAX].rsplit(" ", 1)[0] + "…"
    return texto


def _escopo_depois(titulo: str, fim_desconto: int) -> str:
    """O que o texto diz sobre onde o cupom vale, depois do desconto: "Som Vídeo Eletro", "em Eletrônicos" ->
    "eletrônicos", "em Gift Cards na Nuuvem com cupom + PIX" -> "gift cards". '' se não sobra nada útil."""
    orig = titulo[fim_desconto:]
    norm = _norm1(orig)
    # apaga (com espaços, mantendo as posições) o que não é escopo
    chars = list(orig)
    for m in [*_RE_RESTO_FORA.finditer(norm), *_RE_LOJA_FRASE.finditer(norm)]:
        for i in range(m.start(), m.end()):
            chars[i] = " "
    resto = "".join(chars)
    # corta em pontuação que fecha a frase/abre outra condição ("+ frete grátis", mas não o "+" do "Galaxy S24+")
    resto = re.split(r"[|(:;!?]|\s[-–]\s|\s\+|,(?!\d)|\.\s", resto)[0]
    # o nome da loja e a palavra "selecionados" (a marca "itens selecionados" já diz isso) não são escopo
    palavras = [p for p in resto.split() if re.search(r"\w", p) and not _RE_PALAVRA_FORA.fullmatch(_norm1(p).strip(".,!"))]
    while palavras and _norm1(palavras[0]).strip(".,") in _CONECTIVOS:
        palavras.pop(0)
    while palavras and _norm1(palavras[-1]).strip(".,") in _CONECTIVOS:
        palavras.pop()
    if not palavras or all(_norm1(p).strip(".,") in _NEUTRAS for p in palavras) \
            or not re.search(r"[^\W\d_]{3}", " ".join(palavras)) \
            or _RE_ESCOPO_GENERICO.search(_norm1(" ".join(palavras))):
        return ""
    return _encurta(" ".join(palavras))


def _produto_antes(texto: str, ini_desconto: int) -> str:
    """O produto escrito ANTES do desconto, quando depois dele não há nada: "Adquira o Meta Quest 3 512GB com R$500 de
    desconto" -> "meta quest 3 512gb"; "Faça um upgrade com o Intel Core i5-12600K e 15% OFF" -> "intel core i5-12600k";
    "produtos Netshoes TÊNIS MIZUNO WAVE PROPHECY COM R$200 OFF" -> "tênis mizuno wave prophecy". Frase de campanha ("Os
    melhores itens do site com", "A chance de", "Marcas em alta com até") -> ''."""
    antes = texto[:ini_desconto]
    chars = list(antes)
    for m in _RE_LOJA_FRASE.finditer(_norm1(antes)):
        for i in range(m.start(), m.end()):
            chars[i] = " "
    pedacos = re.split(r"[|:;!?()\[\]]|\s[-–]\s|,(?!\d)|\.\s", "".join(chars))
    palavras = [p for p in (pedacos[-1] if pedacos else "").split()
                if re.search(r"\w", p) and not _RE_PALAVRA_FORA.fullmatch(_norm1(p).strip(".,!"))]
    while palavras and _norm1(palavras[0]).strip(".,!") in _CHAMADA:
        palavras.pop(0)
    while palavras and _norm1(palavras[-1]).strip(".,!") in _CHAMADA | _CONECTIVOS | {"r$"}:
        palavras.pop()
    if not palavras or len(palavras) > _MAX_PALAVRAS_PRODUTO:
        return ""
    junto = " ".join(palavras)
    n = _norm1(junto)
    if not re.search(r"[^\W\d_]{3}", junto) or _RE_ESCOPO_GENERICO.search(n) or _RE_ANTES_GENERICO.search(n) \
            or "r$" in n or all(_norm1(p).strip(".,") in _NEUTRAS for p in palavras):   # "LEVE 2 POR R$6,99 CADA"
        return ""
    return _encurta(junto)


@dataclass
class _Desconto:
    tipo: str                  # '%' | 'R$'
    valor: float
    minimo: Optional[float]    # "R$ 490 em R$ 3200": o mínimo vem junto
    ate: bool                  # "até 60%": máximo da vitrine
    ini: int
    fim: int


def _ate_antes(txt: str, pos: int) -> bool:
    return bool(_RE_ATE_ANTES.search(txt[max(0, pos - 12):pos]))


def _descontos(txt: str) -> list[_Desconto]:
    """Os descontos do texto (normalizado), na ordem de preferência: os em %, os em R$ com "OFF"/"de desconto" e os
    "R$ X em R$ Y" do Pelando, cada grupo na ordem do texto. O "100%" do nome do produto fica de fora."""
    out: list[_Desconto] = []
    for m in _RE_PCT.finditer(txt):
        x = _valor(m.group(1))
        if not 0 < x <= 100 or (x >= 100 and not _RE_PCT_DESCONTO_DEPOIS.match(txt, m.end())):
            continue
        out.append(_Desconto("%", x, None, _ate_antes(txt, m.start()), m.start(), m.end()))
    for m in _RE_REAIS.finditer(txt):
        x = _primeiro(m)
        if x and x > 0:
            ate = _ate_antes(txt, m.start()) or bool(re.search(r"\bate\s+r\$", m.group(0)))
            out.append(_Desconto("R$", x, None, ate, m.start(), m.end()))
    for m in _RE_REAIS_EM.finditer(txt):
        x = _primeiro(m)
        if x and x > 0:
            out.append(_Desconto("R$", x, _valor(m.group(2)), _ate_antes(txt, m.start()), m.start(), m.end()))
    return out


def valor_do_cupom(titulo: str, regra: str = "") -> Valor:
    """Desconto, compra mínima, teto, escopo e marcas do cupom, lidos do título (e da regra quando o título não diz).

    O desconto: o primeiro do título que não é "até X" de vitrine; senão o da regra ("Marcas em alta com até 60% de
    desconto" + "10% DE DESCONTO NOS PRODUTOS SELECIONADOS" -> 10%); senão o "até X" (mostrado "até 60% OFF")."""
    from .regras import _conserta_mojibake

    titulo = _conserta_mojibake(titulo or "")
    regra = _conserta_mojibake(regra or "")
    t, r = _norm1(titulo), _norm1(regra)
    r_util = "" if _RE_AVISO_GENERICO.search(r) else r   # o aviso genérico do Pelando no ML não é a regra do cupom
    v = Valor()
    ds_t, ds_r = _descontos(t), _descontos(r)
    certo_t = next((d for d in ds_t if not d.ate), None)
    certo_r = next((d for d in ds_r if not d.ate), None)
    no_titulo = certo_t or (ds_t[0] if ds_t else None)          # onde o título fala do desconto (para o escopo)
    escolha = certo_t or certo_r or no_titulo or (ds_r[0] if ds_r else None)
    if escolha is not None:
        v.desconto, v.minimo, v.ate = (escolha.tipo, escolha.valor), escolha.minimo, escolha.ate
        if v.minimo is None and escolha.tipo == "R$":
            # "oferece R$ 20 em R$ 149": o mesmo valor também casou como "R$ X em R$ Y", que traz o mínimo
            v.minimo = next((d.minimo for d in ds_t + ds_r if d.minimo and abs(d.valor - escolha.valor) < 0.01), None)
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
    if v.desconto and v.desconto[0] == "%" and v.teto is None and escolha is not None:
        # "15% OFF no Pix até R$ 200": o "até R$" depois do % (o "compras de até R$ 1000" sai logo abaixo)
        v.teto = _primeiro(_RE_ATE_REAIS.search(t if any(d is escolha for d in ds_t) else r, escolha.fim))
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
    # escopo: "todo site"; senão o que segue o desconto no título, o produto antes dele, ou o mesmo na regra (Promobit:
    # "R$100 OFF ASICS DYNABLAST 6", "TÊNIS MIZUNO WAVE PROPHECY COM R$200 OFF")
    if _RE_SITE_TODO.search(t):
        v.escopo = "todo site"
    else:
        if no_titulo is not None:
            v.escopo = _escopo_depois(titulo, no_titulo.fim) or _produto_antes(titulo, no_titulo.ini)
        # a regra só no formato do Promobit ("produtos <Loja> ..."); a do Pelando é comentário de usuário
        if not v.escopo and r_util.startswith("produtos ") and ds_r:
            d = certo_r or ds_r[0]
            v.escopo = _escopo_depois(regra, d.fim) or _produto_antes(regra, d.ini)
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
    if _RE_RESGATOU.search(texto):
        v.marcas.append(MARCA_RESGATOU)
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
        partes.append(("até " if v.ate else "") + (f"{_fmt_pct(x)} OFF" if tipo == "%" else f"{fmt_reais(x)} OFF"))
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
    """"até 18/11/2026", "Validade: até 18.11", "válida até o fim do mês" (o mês da publicação) no título/regra (a maior
    data, fim do dia). Sem data -> None."""
    texto = _norm1(f"{reg.get('titulo') or ''} {reg.get('regra') or ''}")
    pub = _data(reg.get("publicado"))
    base = pub.date() if pub else agora().date()
    datas = []
    if _RE_FIM_DO_MES.search(texto):
        prox = date(base.year + (base.month == 12), base.month % 12 + 1, 1)
        datas.append(prox - timedelta(days=1))
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


def validade_padrao(validade: Optional[datetime], publicado: Any) -> bool:
    """A validade do anúncio parece data-padrão de anúncio antigo (publicado há mais de VALIDADE_PADRAO_IDADE dias, com
    validade em 31/12 ou a mais de VALIDADE_PADRAO_SPAN dias da publicação: JBL25, publicado em 09/2025 e "válido" até
    09/2027)? Aí ela não prova que o cupom ainda vale."""
    pub = _data(publicado)
    if validade is None or pub is None or (agora() - pub).days <= VALIDADE_PADRAO_IDADE:
        return False
    v = validade.astimezone(TZ_BR)
    return (v.month, v.day) == (12, 31) or (v - pub).days > VALIDADE_PADRAO_SPAN


def validade_declarada(reg: dict) -> Optional[datetime]:
    """A validade que conta: a do anúncio (menos a data-padrão de anúncio antigo) ou, sem ela, a escrita no texto."""
    validade = _data(reg.get("validade"))
    if validade_padrao(validade, reg.get("publicado")):
        validade = None
    return validade or validade_no_texto(reg)


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
        return None   # sem publicação não dá para saber se os 4 dígitos são data (MAGALU0911 do anúncio)
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
    telegram = str(reg.get("fonte") or "") == "telegram"
    if telegram:
        # cupom citado nos canais do Telegram (monitor/cupons_telegram.py): um post mais novo que todas as citações
        # ativas disse que esgotou; a seção do post diz quando começa ("Válidos de 10/11 até 12/11")
        if esgotado_depois(reg, [reg]):
            return "esgotado"
        ini = _data((reg.get("extra") or {}).get("inicio"))
        if ini is not None and ini.date() > agora_.date():
            return f"começa {ini:%d/%m}"
    validade = validade_declarada(reg)
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
    if str(reg.get("fonte") or "") == "pelando":
        # o Pelando só mostra (e o coletor só lê) cupom com status ativo, e o registro é da última leitura: vale uma janela
        # maior. O "há 3 dias" dele é arredondado para baixo (3,0 dias antes da leitura): conta o dia inteiro
        limite = max(dias, config.CUPONS_ATIVOS_DIAS_PELANDO)
        return "" if d < limite + 1 else f"publicado há {d:.0f} dias"
    if telegram:
        # janela própria: a citação mais recente do código nos canais (cada post novo renova)
        dias = config.CUPONS_ATIVOS_DIAS_TELEGRAM
    return "" if d <= dias else f"publicado há {d:.0f} dias"


def esgotado_depois(reg: dict, ativos: Iterable[dict]) -> bool:
    """O registro diz (extra['esgotado_em'], cupom do Telegram) que o código esgotou DEPOIS da publicação de todos os
    `ativos` (o próprio registro, ou os anúncios ativos do mesmo código em qualquer fonte)? Anúncio sem data conta
    como mais velho."""
    esg = _data((reg.get("extra") or {}).get("esgotado_em")) if isinstance(reg.get("extra"), dict) else None
    if esg is None:
        return False
    for r in ativos:
        pub = _data(r.get("publicado"))
        if pub is not None and pub > esg:
            return False
    return True


def _como_dict(c: Any) -> Optional[dict]:
    if isinstance(c, dict):
        return c
    to = getattr(c, "to_dict", None)
    return to() if callable(to) else None


def cupons_ativos(regs: Iterable[Any], expirados: Optional[set[str]] = None,
                  dias: Optional[float] = None) -> dict[str, list[dict]]:
    """{loja: [cupons ativos]}; cada cupom é o registro (dict) com '_valor' (Valor) e '_texto' (o valor pronto, sem
    HTML). Ordem na loja: os do anúncio monitorado (especifico), os gerais e os restritos (lista, categoria, produto,
    frete, público), cada grupo com o maior desconto primeiro. `expirados`: None lê o testador."""
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
        # um post do Telegram disse que o código esgotou depois de todos os anúncios ativos dele (de qualquer fonte)
        if any(esgotado_depois(r, ativos) for r in grupo if r.get("fonte") == "telegram"):
            continue
        melhor = _o_melhor(ativos)
        # o valor do anúncio que diz mais, mesmo que ele não conte como ativo (o mesmo código no Pelando, publicado há
        # mais dias, com "R$ 400 OFF acima de R$ 2.500", e no Promobit, com validade e outro valor no título)
        mais = _o_melhor(grupo)
        if mais is not melhor and mais["_valor"].informacao > melhor["_valor"].informacao:
            melhor = {**melhor, "_valor": mais["_valor"]}
        melhor["_outro_valor"] = _outro_valor(melhor["_valor"], grupo)
        melhores[chave] = melhor
    por_loja: dict[str, list[dict]] = {}
    for reg in melhores.values():
        reg["_texto"] = texto_do_valor(reg["_valor"], reg.get("titulo") or "")
        if reg.get("_outro_valor"):
            reg["_texto"] += f" · outro anúncio diz {reg['_outro_valor']}"
        por_loja.setdefault(reg["loja"], []).append(reg)
    for lista in por_loja.values():
        lista.sort(key=lambda r: (not r.get("especifico"), r["_valor"].restrito, -r["_valor"].peso,
                                  r["_valor"].minimo or 0, r["codigo"].upper()))
    return por_loja


def _outro_valor(v: Valor, grupo: list[dict]) -> str:
    """'R$ 670 OFF' quando outro anúncio do mesmo código, tão completo quanto o escolhido, diz outro desconto do mesmo
    tipo (AFFNOV22 no Pelando: "R$620 off em R$4200" e "R$ 670 acima de R$ 4200"); '' se todos concordam. Anúncio menos
    completo (o título genérico do Promobit) não entra."""
    if not v.desconto or v.duvidoso:
        return ""
    tipo, x = v.desconto
    for r in grupo:
        o = r["_valor"]
        if o.desconto and not o.duvidoso and o.desconto[0] == tipo and o.informacao >= v.informacao \
                and abs(o.desconto[1] - x) > 0.01 * x:
            return f"{_fmt_pct(o.desconto[1])} OFF" if tipo == "%" else f"{fmt_reais(o.desconto[1])} OFF"
    return ""


def _o_melhor(regs: list[dict]) -> dict:
    melhor = regs[0]
    for r in regs[1:]:
        if _melhor_registro(r, melhor):
            melhor = r
    return melhor


def _melhor_registro(a: dict, b: dict) -> bool:
    """O registro `a` diz mais que `b`? Mais informação (desconto, mínimo, teto, escopo, validade); empate, o mais
    novo."""
    ia = a["_valor"].informacao + (validade_declarada(a) is not None)
    ib = b["_valor"].informacao + (validade_declarada(b) is not None)
    if ia != ib:
        return ia > ib
    return str(a.get("publicado") or "") > str(b.get("publicado") or "")


def ordem_das_lojas(lojas: Iterable[str]) -> list[str]:
    """As lojas que o monitor mais usa primeiro (ORDEM_LOJAS), depois as outras em ordem alfabética."""
    pos = {l: i for i, l in enumerate(ORDEM_LOJAS)}
    return sorted(lojas, key=lambda l: (pos.get(l, len(pos)), sem_acentos(l).lower()))


def _texto_da_linha(reg: dict) -> str:
    """O que vem depois do código: o valor, o anúncio (cupom da página do produto) e o vencimento (até 31 dias; "vence
    hoje", "vence amanhã")."""
    texto = reg.get("_texto") or texto_do_valor(reg.get("_valor") or Valor(), reg.get("titulo") or "")
    if reg.get("especifico"):
        modelo = reg.get("modelo")
        texto += f" · só no anúncio do {rotulo_modelo(str(modelo))}" if modelo else " · só no anúncio"
    validade = validade_declarada(reg)
    if validade is not None:
        faltam = (validade.astimezone(TZ_BR).date() - agora().date()).days
        if faltam <= 0:
            texto += " · vence hoje"
        elif faltam == 1:
            texto += " · vence amanhã"
        elif faltam <= 31:
            texto += f" · vence {validade.astimezone(TZ_BR):%d/%m}"
    return texto


def _bloco(loja: str, regs: list[dict]) -> list[str]:
    """O título da loja (com quantos códigos ela tem) e uma linha por valor: códigos diferentes com o MESMO valor
    (AEMEGA8, AFFNOV08 e Pelando8: R$ 580 OFF acima de R$ 3.700) ficam na mesma linha, cada um no seu <code>, até
    MAX_CODIGOS_POR_LINHA (o seguinte abre outra linha). No máximo config.CUPONS_ATIVOS_MAX_POR_LOJA linhas (0 = todas);
    o resto vira "… e mais N códigos"."""
    grupos: list[tuple[str, list[dict]]] = []
    onde: dict[str, int] = {}
    for r in regs:
        texto = _texto_da_linha(r)
        # escopo cortado ("…") pode esconder produtos diferentes com o mesmo começo: não junta
        agrupa = bool(r.get("codigo")) and not r.get("especifico") and "…" not in texto
        i = onde.get(texto) if agrupa else None
        if i is not None and len(grupos[i][1]) < MAX_CODIGOS_POR_LINHA:
            grupos[i][1].append(r)
            continue
        if agrupa:
            onde[texto] = len(grupos)
        grupos.append((texto, [r]))
    maximo = config.CUPONS_ATIVOS_MAX_POR_LOJA
    mostra = grupos[:maximo] if maximo > 0 else grupos
    escondidos = sum(len(rs) for _t, rs in grupos[len(mostra):])
    linhas = [f"🛒 <b>{html.escape(loja.upper(), quote=False)}</b> ({len(regs)})"]
    for texto, rs in mostra:
        if rs[0].get("codigo"):
            ini = "• " + " ou ".join(f"<code>{html.escape(r['codigo'], quote=False)}</code>" for r in rs)
        else:
            ini = "• <i>sem código (automático)</i>"
        linhas.append(f"{ini} — {html.escape(texto, quote=False)}" + (" ⭐" if rs[0].get("especifico") else ""))
    if escondidos:
        linhas.append(f"<i>… e mais {escondidos} código{'' if escondidos == 1 else 's'} de lista, categoria ou "
                      "menor desconto</i>")
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
        # loja grande demais: corta entre linhas, repetindo o título com "(cont.)" (o título nunca fica sozinho; a linha
        # tem no máximo MAX_CODIGOS_POR_LINHA códigos, então sempre cabe)
        titulo = linhas[0]
        atual = titulo
        for ln in linhas[1:]:
            if len(atual) + 1 + len(ln) > cabe and atual != titulo:
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


def cupons_conhecidos(estado: Any, cupons: Iterable[Any]) -> list[dict]:
    """Todos os cupons que a rodada conhece, como registros (dict), para a lista de cupons ativos e o melhor cupom do
    AliExpress: os desta rodada, os da última leitura (por fonte e loja) deste modo que não vieram agora (a página de
    uma loja que falhou nesta rodada não tira a loja da lista) e os do outro modo (latest e última leitura do state
    dele). Os do Telegram entram sempre que estão dentro da janela (Estado.cupons_da_ultima_leitura): o post que saiu da
    1ª página do canal entre uma rodada e outra continua valendo."""
    regs = [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in cupons]
    lidas_agora = {(r.get("fonte"), loja_canonica(str(r.get("loja") or ""))) for r in regs}
    regs += [r for r in estado.cupons_da_ultima_leitura()
             if r.get("fonte") in config.FONTES_CUPOM_SO_LISTA
             or (r.get("fonte"), loja_canonica(str(r.get("loja") or ""))) not in lidas_agora]
    regs += estado.cupons_de_outros_modos()
    return regs


# ---- melhor cupom de plataforma para um anúncio (pedido de 08/11/2026: PS5 do AliExpress) ----
# marcas que tiram o cupom da conta: público restrito (1ª compra, assinante, WhatsApp)
_MARCAS_FORA_DA_CONTA = {"Prime/assinante", "1ª compra", "WhatsApp"}
# desconto fixo sem compra mínima conhecida entra na conta só até esta fração do preço do item
DESCONTO_SEM_MINIMO_MAX = 0.15


def opcoes_de_cupom(preco_item: float, ativos_da_loja: Iterable[dict]) -> list[dict]:
    """Os cupons ativos da loja (cupons_ativos(...)[loja]) que valem num item de `preco_item` (o preço do item, sem o
    frete: o cupom é sobre o item), do maior desconto para o menor; os "só para quem resgatou" vão para o fim. Fica de
    fora: sem desconto legível, valor duvidoso, "até X%" de vitrine, só frete, lista/seleção, categoria/produto, 1ª
    compra, assinante e WhatsApp ("só no app" fica: o código é digitado no app), compra mínima acima do preço do item
    e teto da compra abaixo dele. % sai do preço com o teto. Um código por pedido: a lista é de alternativas.
    Cada opção: {'codigo', 'desconto', 'minimo', 'texto', 'fonte', 'resgatou', 'validade'}."""
    melhores: dict[str, dict] = {}
    for r in ativos_da_loja:
        v: Valor = r.get("_valor") or valor_do_cupom(r.get("titulo") or "", r.get("regra") or "")
        cod = str(r.get("codigo") or "").strip().upper()
        if not cod or r.get("especifico") or v.desconto is None or v.duvidoso or v.ate or v.so_frete or v.selecao:
            continue
        if v.escopo and v.escopo != "todo site":
            continue
        if any(m in _MARCAS_FORA_DA_CONTA for m in v.marcas):
            continue
        if v.minimo and v.minimo > preco_item + 0.005:
            continue
        if v.teto_compra and preco_item > v.teto_compra + 0.005:
            continue
        tipo, x = v.desconto
        desconto = x if tipo == "R$" else preco_item * x / 100
        if tipo == "%" and v.teto:
            desconto = min(desconto, v.teto)
        if not 0 < desconto < preco_item:
            continue
        if tipo == "R$" and not v.minimo and desconto > DESCONTO_SEM_MINIMO_MAX * preco_item:
            continue   # "R$ 785 OFF" sem a compra mínima: na dúvida não entra na conta (todo cupom grande tem mínimo)
        validade = validade_declarada(r)
        op = {"codigo": cod, "desconto": round(desconto, 2), "minimo": v.minimo, "texto": r.get("_texto") or
              texto_do_valor(v, r.get("titulo") or ""), "fonte": r.get("fonte"), "resgatou": MARCA_RESGATOU in v.marcas,
              "validade": validade.date().isoformat() if validade else None}
        if cod not in melhores or op["desconto"] > melhores[cod]["desconto"]:
            melhores[cod] = op
    return sorted(melhores.values(), key=lambda o: (o["resgatou"], -o["desconto"], o["minimo"] or 0, o["codigo"]))


def regra_do_cupom(op: dict) -> str:
    """'R$ 785 OFF acima de R$ 4.200' (o produtos.preco_com_cupom_do_anuncio confere a compra mínima nesse texto)."""
    return f"{fmt_reais(op['desconto'])} OFF" + (f" acima de {fmt_reais(op['minimo'])}" if op.get("minimo") else "")


def aplica_melhor_cupom(ofertas: Iterable[Any], regs: Iterable[Any], loja: str = "AliExpress",
                        expirados: Optional[set[str]] = None) -> int:
    """Grava em cada oferta de loja da `loja` (produto que não é TV) o preço com o melhor cupom ativo da loja (o maior
    desconto com compra mínima <= preço do item), para o alerta, o 🎯 e o painel (produtos.preco_com_cupom_do_anuncio):
    extra['preco_com_cupom'] = item - desconto + frete (quando o frete é conhecido), 'cupom_preco' (o código),
    'cupom_regra', 'cupom_origem' = 'lista', 'cupom_desconto', 'cupom_validade' e 'cupons_alternativos' (os 3
    seguintes, para quando o melhor esgotar). Só calcula: quem digita o código no app é o usuário (1 por pedido).
    Devolve quantas ofertas ganharam o preço com cupom."""
    from . import produtos
    from .models import modelo_de

    alvo = [o for o in ofertas if getattr(o, "tipo", "") == "loja" and loja_canonica(getattr(o, "loja", "")) == loja
            and getattr(o, "ativo", True) and (o.preco or o.melhor_preco) and not produtos.eh_tv(modelo_de(o))]
    if not alvo:
        return 0
    ativos = cupons_ativos(regs, expirados).get(loja, [])
    n = 0
    for o in alvo:
        preco_item = float(o.preco or o.melhor_preco)
        ops = opcoes_de_cupom(preco_item, ativos)
        if not ops:
            continue
        frete = o.extra.get("frete")
        frete = float(frete) if isinstance(frete, (int, float)) and frete >= 0 else 0.0

        def total(op: dict) -> float:
            return round(preco_item - op["desconto"] + frete, 2)

        b = ops[0]
        o.extra.update({
            "preco_com_cupom": total(b), "cupom_preco": b["codigo"], "cupom_regra": regra_do_cupom(b),
            "cupom_origem": "lista", "cupom_desconto": b["desconto"],
            "cupons_alternativos": [{"codigo": a["codigo"], "desconto": a["desconto"], "preco": total(a),
                                     "resgatou": a["resgatou"]} for a in ops[1:4]]})
        if b.get("validade"):
            o.extra["cupom_validade"] = b["validade"]
        else:
            o.extra.pop("cupom_validade", None)
        o.cupom = b["codigo"]
        n += 1
    return n


def texto_do_melhor_cupom(o: Any) -> str:
    """A linha do alerta com o melhor cupom da lista (aplica_melhor_cupom): "🎟️ Com o cupom AFFNOV11 (melhor cupom
    AliExpress ativo; 1 por pedido, digite no app): R$ 3.736,63 (item R$ 4.500 − R$ 785 + frete R$ 21,63) · se
    esgotado: AFFNOV09 → R$ 3.771,63". '' sem o cálculo."""
    extra = (o.get("extra") if isinstance(o, dict) else getattr(o, "extra", None)) or {}
    if extra.get("cupom_origem") != "lista" or not extra.get("preco_com_cupom") or not extra.get("cupom_preco"):
        return ""
    loja = loja_canonica(str((o.get("loja") if isinstance(o, dict) else getattr(o, "loja", "")) or ""))
    preco = (o.get("preco") if isinstance(o, dict) else getattr(o, "preco", None))
    conta = ""
    if preco and extra.get("cupom_desconto"):
        conta = f" (item {fmt_reais(float(preco))} − {fmt_reais(float(extra['cupom_desconto']))}"
        frete = extra.get("frete")
        if isinstance(frete, (int, float)) and frete > 0:
            conta += f" + frete {fmt_reais(float(frete))}"
        elif frete == 0:
            conta += " + frete grátis"
        conta += ")"
    txt = (f"🎟️ Com o cupom {extra['cupom_preco']} (melhor cupom {loja} ativo; 1 por pedido, digite no app): "
           f"{fmt_reais(float(extra['preco_com_cupom']))}{conta}")
    alts = [a for a in extra.get("cupons_alternativos") or [] if isinstance(a, dict) and a.get("codigo")]
    if alts:
        txt += " · se esgotado: " + ", ".join(f"{a['codigo']} → {fmt_reais(float(a['preco']))}" for a in alts[:2])
    return txt
