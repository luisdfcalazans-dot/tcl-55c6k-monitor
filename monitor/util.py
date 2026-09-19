from __future__ import annotations

import html as html_mod
import json
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import requests

from . import config

try:
    from zoneinfo import ZoneInfo

    TZ_BR = ZoneInfo("America/Sao_Paulo")
except Exception:  # Windows sem o pacote tzdata: usa -03:00 fixo
    TZ_BR = timezone(timedelta(hours=-3), name="BRT")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
HEADERS_HTML = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}
HEADERS_JSON = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

_sessao = requests.Session()


def agora() -> datetime:
    return datetime.now(TZ_BR)


def agora_iso() -> str:
    return agora().isoformat(timespec="seconds")


def hoje() -> str:
    return agora().date().isoformat()


def http_get(url: str, headers: Optional[dict] = None, timeout: int = 30, tentativas: int = 2) -> requests.Response:
    """GET com cabeçalhos de navegador e uma repetição em caso de falha de rede."""
    ultimo_erro: Exception | None = None
    for i in range(tentativas):
        try:
            r = _sessao.get(url, headers=headers or HEADERS_HTML, timeout=timeout)
            if r.status_code >= 500 and i + 1 < tentativas:
                time.sleep(2)
                continue
            return r
        except requests.RequestException as e:  # rede, timeout
            ultimo_erro = e
            time.sleep(2)
    assert ultimo_erro is not None
    raise ultimo_erro


def get_html(url: str, **kw) -> str:
    r = http_get(url, headers=HEADERS_HTML, **kw)
    r.raise_for_status()
    # sem charset no cabeçalho o requests assume latin-1 e os acentos viram "Ã¡"; todos os sites daqui são UTF-8
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "latin-1", "latin1"):
        r.encoding = "utf-8"
    return r.text


def get_json(url: str, headers: Optional[dict] = None, **kw) -> Any:
    h = dict(HEADERS_JSON)
    if headers:
        h.update(headers)
    r = http_get(url, headers=h, **kw)
    r.raise_for_status()
    return r.json()


# ---------- parsing ----------

_RE_NEXT_DATA = re.compile(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>\s*(.+?)\s*</script>', re.S)
_RE_JSONLD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.+?)</script>', re.S)


def next_data(html: str) -> Optional[dict]:
    m = _RE_NEXT_DATA.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def jsonld(html: str) -> list[Any]:
    out: list[Any] = []
    for m in _RE_JSONLD.finditer(html):
        try:
            out.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
    return out


def jsonld_produtos(html: str) -> list[dict]:
    """Devolve todos os nós schema.org Product (inclusive dentro de @graph e ItemList)."""
    prods: list[dict] = []

    def visita(n: Any) -> None:
        if isinstance(n, list):
            for x in n:
                visita(x)
        elif isinstance(n, dict):
            t = n.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                prods.append(n)
            for k in ("@graph", "itemListElement", "item", "mainEntity"):
                if k in n:
                    visita(n[k])

    visita(jsonld(html))
    return prods


# Valor em reais com ponto de milhar (3.599,00) ou sem (3599,00 / 3599.99). O (?!\d) exige o fim do número:
# sem ele a primeira alternativa casava só "359" de "R$ 3599" e o valor real sumia.
_NUM_BRL_SRC = r"\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:[.,]\d{2})?"
_NUM_BRL = rf"({_NUM_BRL_SRC})(?!\d)"
_RE_PRECO = re.compile(r"R\$\s?" + _NUM_BRL)


def parse_preco(texto: Any) -> Optional[float]:
    """Converte 'R$ 3.082,61', '3.082,61', '3082.61', 2799 em float."""
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto) if texto > 0 else None
    s = str(texto).strip()
    if not s:
        return None
    s = s.replace("R$", "").replace("\xa0", "").strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):    # 2.799 (milhar em pt-BR; preço nunca tem 3 decimais)
        v = float(s.replace(".", ""))
        return v if v > 0 else None
    if re.fullmatch(r"\d+(\.\d{1,2})?", s):      # 3082.61 ou 2799
        v = float(s)
        return v if v > 0 else None
    if re.fullmatch(r"\d{1,3}(\.\d{3})*,\d{1,2}", s) or re.fullmatch(r"\d+,\d{1,2}", s):
        v = float(s.replace(".", "").replace(",", "."))
        return v if v > 0 else None
    return None


def precos_no_texto(texto: str) -> list[float]:
    """Todos os valores 'R$ ...' de um texto, em ordem."""
    out = []
    for m in _RE_PRECO.finditer(texto or ""):
        v = parse_preco(m.group(1))
        if v:
            out.append(v)
    return out


# ---------- postagem livre (Telegram): preço da TV ----------
#
# Cada valor "R$ ..." de uma postagem é classificado pelo que está em volta dele (na mesma linha; a linha de cima
# só entra quando a frase dela termina em "de", ":" ou ">" e o valor abre a linha de baixo):
#   preco     candidato: cartão, Pix, "com cupom", "Preço mínimo: R$ X", "Preço final com o desconto: R$ X", o
#             valor DEPOIS de uma seta e "a partir de R$ X" sem cupom/desconto na mesma frase
#   fraco     só vale se não houver candidato: "a partir de R$ X" no meio da frase e "mín./mínimo: R$ X" sem
#             cupom nem Pix, e "R$ X mais barato (que...)" (diferença quando há outro preço; o preço quando é o
#             único). "R$ X (mais barato do ano!)", "R$ X mais barato no Pix", "No Pix sai a partir de R$ X", "ou a
#             partir de R$ X no Pix", "Histórico mínimo: R$ X no Pix" e "Com o cupom X, a partir de R$ Y" são o preço.
#   antigo    "De R$ X", "era/estava/antes R$ X", o valor ANTES de uma seta seguida de outro valor, ou de "por R$ Y"
#   condicao  mínimo do cupom: "acima (de)", "superior a", "compras de", "compras +", "comprando/levando/gastar",
#             "valor/pedido/compra mínimo" (também "mín:"), "+R$", "R$ X ou mais/pra cima", "> R$" depois de uma
#             palavra (no começo da linha ">" é marcador), o fim de uma faixa cujo começo é condição ("Compras de R$ 800
#             a R$ 1.999"), "a partir de"/"mín." numa frase de cupom/desconto (também depois de "(" "|" " - " quando o
#             trecho de antes, na mesma linha, anuncia o cupom: "Cupom TV300 (a partir de R$ 2.500)", ou numa linha
#             de ingresso 🎟️ com OFF/%/desconto); e, na frase que anuncia o desconto do cupom ("R$ 300 OFF ...",
#             "Cupom de R$ 300 ..."), o valor DEPOIS do desconto que não está marcado como preço (por, Pix, à vista,
#             final, com cupom, ou o rótulo ':' logo antes: "R$ 300 OFF no app: R$ 2.899" é o preço final): é um termo
#             do cupom, não o preço da TV
#   teto      "máximo de", "desconto máximo", "limitado a", "limite de"
#   desconto  "R$ X OFF", "R$ X de desconto", "economize", "desconto de", "cupom de", "cashback", "de volta" e o
#             rótulo "Desconto: R$ X" ("com o desconto: R$ X", "após o desconto: R$ X", "Pix c/ desconto: R$ X"
#             são o preço final)
#   parcela   "10x de R$ X", "10x R$ X", "parcelas de", "R$ X/mês"
# O preço da TV é o menor candidato >= piso (abaixo de R$ 1.500 nenhum valor é o preço desta TV); sem candidato,
# o menor "fraco" >= piso.

PISO_PRECO_TV = 1500.0  # abaixo disso nenhum valor é o preço da 55C6K (peça, acessório, parcela, desconto)
_RE_VALOR_POST = re.compile(r"R\$\s*" + _NUM_BRL)  # aceita "R$  3.599" (espaço duplo, comum nos canais)
_SETA = r"(?:-+>|=+>|>>|➡️|➡|→|⏩|⇒|➔|➜|⟶)"
_RE_SETA_ANTES = re.compile(r"(?:" + _SETA + r"|(?<![<>!=])=)\s*$")  # "= R$ 2.899" também é o resultado
# a seta só separa o preço antigo do novo quando outro valor vem logo depois ("R$ 2.799 ➡️ https://..." é o preço)
_RE_SETA_DEPOIS = re.compile(r"^\s*" + _SETA + r"[^a-z0-9\n]*(?:(?:por|para|pra)\s*:?\s*)?r\$")
_RE_DEPOIS = [
    ("desconto", re.compile(r"^\s*\)?\s*(?:off\b|de\s+desconto|de\s+economia|de\s+cashback|em\s+cashback|"
                            r"de\s+volta|a\s+menos\b|de\s+diferenca)")),
    ("condicao", re.compile(r"^(?:\s*(?:em\s+(?:compras|pedidos|produtos)|nas\s+compras|ou\s+mais\b(?!\s+barat)|"
                            r"ou\s+acima\b|(?:pra|para)\s+cima\b|em\s+diante\b)|\+(?=\s|$|[)\].,;:!]))")),
    ("parcela", re.compile(r"^\s*(?:x\s*\d|/\s*mes|por\s+mes\b|mensais)")),
    ("antigo", re.compile(r"^\s*[),;]?\s*(?:por|para|pra)\s*:?\s*r\$")),
    # "mais barato (que ...)" é diferença; "mais barato do ano/de sempre/no Pix/à vista" é o preço
    ("fraco", re.compile(r"^\s*(?:de\s+|\(\s*)?mais\s+barat[oa]s?(?!\s+(?:d[oa]s?\s+(?:ano|mes|historia|brasil|site|"
                         r"momento|dia|semana|mercado|internet)\b|de\s+(?:sempre|todos)\b|ja\s+vist|"
                         r"(?:no|via|pelo)\s+(?:pix|app|boleto)\b|a\s+vista\b))")),
]
_RE_ANTES = [
    ("parcela", re.compile(r"(?:\b\d{1,2}\s*(?:x|vezes)\s*(?:(?:sem|s/)\s*juros\s*)?(?:de\s*)?|"
                           r"\bparcelas?\s+(?:de\s*)?)[:\-]?\s*$")),
    ("teto", re.compile(r"(?:\bmaxim[oa]|\bmax\.?|\blimitad[oa]\s+a|\blimite|\bteto)(?:\s+de)?\s*[:\-]?\s*$")),
    # "Desconto: R$ X" só como rótulo (começo da linha/frase, "valor do desconto:"); "com o desconto:",
    # "após o desconto:", "c/ desconto:", "5% desconto:" vêm antes do preço final
    ("desconto", re.compile(r"(?:\beconomi\w*|\bdesconto\s+de|(?:^|[^a-z0-9\s/%])\s*(?:(?:valor|total)\s+(?:do|de)\s+)?"
                            r"desconto\s*:|\bcashback|\bcupom\s+de|\boff\s+de|\bganhe|"
                            r"\bvolta\s+de)(?:\s+de)?\s*[:\-]?\s*$")),
    ("condicao", re.compile(
        # "acima de R$ X" e "acima R$ X" (sem "de": "R$ 250 acima R$2500", "Compras acima R$4000"); "compras +R$ X"
        r"(?:\bacima(?:\s+d[eoa]s?)?|\b(?:superior|superiores|maior|maiores)\s+(?:a|ao|que|de)|"
        r"\b(?:compras?|pedidos?|carrinhos?)\s*\+|"
        r"\b(?:compras?|pedidos?|carrinhos?|produtos?|gastos?)\s+(?:(?:a\s+partir|acima|minim[oa]s?)\s+)?de|"
        r"\b(?:gastando|gaste|gastar|comprando|levando)(?:\s+(?:a\s+partir\s+de|acima\s+de|mais\s+de|de|"
        r"ao\s+menos|pelo\s+menos))?|"
        r"\b(?:compre|comprar)\s+(?:a\s+partir\s+de|acima\s+de|mais\s+de|ao\s+menos|pelo\s+menos)|"
        r"\b(?:valor|pedido|compra|carrinho|gasto)s?\s+min(?:im[oa]s?)?\b\.?(?:\s+(?:de|do|da|no|na|para)\b)?"
        r"(?:\s+(?:pedido|compra|carrinho|valor|gasto)s?\b)?|"
        r"\bmin(?:im[oa]s?)?\b\.?\s+(?:de|do|da|no|na|para)\s+(?:pedido|compra|carrinho|valor|gasto)s?\b|"
        r"≥"
        r")\s*[:\-]?\s*\+?\s*$")),
    ("antigo", re.compile(r"(?:(?:^|[^a-z0-9\s])\s*de|\bera|\bestava|\bcustava|\bantes|\bantigo|\bsaia\s+por|"
                          r"\b(?:caiu|baixou|saiu|desceu)\s+de)\s*[:\-]?\s*$")),
]
# "💳 10x sem juros: R$ 2.990": rótulo com dois-pontos (sem "de") e 4 parcelas ou mais; um valor >= piso aí é o
# total, porque a parcela seria absurda para esta TV
_RE_TOTAL_PARCELADO = re.compile(r"\b(?:[4-9]|1\d|2[0-4])\s*(?:x|vezes)\s*(?:(?:sem|s/)\s*juros\s*)?:\s*$")
# "> R$ 2.500" / ">= R$ 2.500" depois de uma palavra é o mínimo do cupom ("R$ 300 OFF > R$ 2.500"); fora de seta
# ("->", "=>", ">>") e não no começo da linha, onde ">" é marcador de lista ("> R$ 2.899 no Pix")
_RE_MAIOR = re.compile(r"(?<![-=>])>=?\s*$")
# "a partir de R$ X" e "mín./mínimo: R$ X" soltos: mínimo de cupom quando a mesma frase ("mín.": a mesma linha)
# fala de cupom/desconto antes ("Cupom TV300 (mín. R$ 2.500)", "R$ 250 OFF a partir de R$ 2.500", "Cupom TV300,
# a partir de R$ 2.500"); o preço quando a frase fala do produto ("TCL 55C6K a partir de R$ 2.899", "Com frete
# grátis, a partir de R$ 2.899", "A partir de R$ 3.349,00" do Canaltech); "fraco" no meio de outra frase
# ("📉 Mínimo: R$ 2.899")
_RE_A_PARTIR_DE = re.compile(r"(?:\ba\s+partir\s+de|(?<!preco\s)(?<!precos\s)\bmin(?:im[oa]s?)?\b\.?(?:\s+de)?)"
                             r"\s*[:\-]?\s*$")
_RE_CONTEXTO_CUPOM = re.compile(r"cupo(?:m|ns)\s*:?\s*[a-z]*\d|\boff\b|descont|valid|compra|pedido|cashback|economi|%|"
                                r"\bgast|carrinho|levando|(?:\bem|\bpara|\bnos|\bde)\s+(?:qualquer\s+|todos\s+os\s+)?"
                                r"produtos?\b")
# cupom com código ou com o valor do desconto: a frase é do cupom mesmo depois de uma vírgula
# ("Cupom 10% OFF, a partir de R$ 2.500"). Só "X% OFF" sem cupom é promoção da loja: "Com 5% OFF no Pix, a partir
# de R$ 2.899", "Até 10% OFF, a partir de R$ 2.899" descrevem o preço
_RE_CUPOM_FORTE = re.compile(r"cupo(?:m|ns)\s*:?\s*[a-z]*\d|cupo(?:m|ns)\s+de\s+(?:r\$\s*)?\d|"
                             r"r\$\s*\d[\d.,]*\s*\)?\s*(?:off\b|de\s+desconto)")
_RE_SEP_FRASE = re.compile(r"[|•·;/(]|\s[-—–]\s")
_RE_MODELO_NA_FRASE = re.compile(r"c6k(?![a-z0-9])")
# linha de cupom pelo emoji de ingresso ("🎟️ 10% OFF, a partir de R$ 2.500"): com OFF/%/desconto antes, o "a partir
# de" é o mínimo do cupom, mesmo sem a palavra "cupom"
_RE_LINHA_INGRESSO = re.compile("^[^\\w\\n]*[\U0001F39F\U0001F3AB]")
# "Com o cupom X, a partir de R$ Y": o preço com o cupom aplicado (não o mínimo dele)
_RE_COM_O_CUPOM = re.compile(r"\b(?:com|c/|usando|aplicando)\s+(?:o\s+|os\s+)?cupo(?:m|ns)\b")
# o preço no Pix / à vista continua candidato mesmo com "a partir de"/"mínimo" na frase ("No Pix sai a partir de",
# "ou a partir de R$ X no Pix", "Histórico mínimo: R$ X no Pix")
_RE_PIX_NA_FRASE = re.compile(r"\bpix\b|\ba\s+vista\b")
# faixa de valores: "Compras de R$ 800 a R$ 1.999" (o 2º valor tem o tipo do 1º quando o 1º é condição)
_RE_FAIXA_ANTES = re.compile(r"r\$\s*(\d[\d.,]*)(\s*(?:a|ate|-|–)\s*)$")
# frase que anuncia o desconto do cupom: "R$ 300 OFF", "R$ 300 de desconto", "cupom de R$ 300", "economize R$ 300"
_RE_DESCONTO_DO_CUPOM = re.compile(r"\bcupo(?:m|ns)\s+de\s+r\$\s*\d[\d.,]*(?:\s*(?:off\b|de\s+desconto))?|"
                                   r"r\$\s*\d[\d.,]*\s*\)?\s*(?:off\b|de\s+desconto)|"
                                   r"\b(?:ganhe|economize)\s+(?:ate\s+)?r\$\s*\d[\d.,]*")
# o texto entre o desconto e o valor fala da própria TV (não da compra): o valor é o preço dela
_RE_A_PROPRIA_TV = re.compile(r"\b(?:tvs?|smart|tcl|c6k|55c6k|televis\w*)\b")
# ... ou fala da compra (mínimo do cupom mesmo com ':' antes do valor)
_RE_TERMO_DE_COMPRA = re.compile(r"\bcompra|\bpedido|\bgast|\bacima|\bminim|\bmin\b|\bvalid|\bsuperior|\bpartir")
_RE_SEP_CLAUSULA = re.compile(r"[|•·;()\[\]/,]|\s[-—–]\s|[.!?](?=\s|$)")
# marcas de que o valor é o preço resultante (não um termo do cupom)
_RE_MARCA_PRECO_ANTES = re.compile(
    r"(?:\bpor|\bsai(?:\s+(?:a|por))?|\bfica(?:\s+(?:por|em|a))?|\bpagando|\bpague|\bpaga|\bfinal|\btotal|\bpix|"
    r"\ba\s+vista|\bpreco|\b(?:com|apos|depois\s+d[oa])\s+(?:o\s+|a\s+)?(?:cupom|desconto)\b.*|"
    r"\bc/\s*(?:cupom|desconto)\b.*)\s*[:\-]?\s*$")
_RE_MARCA_PRECO_DEPOIS = re.compile(r"^\s*[(\[]?\s*(?:(?:no|via|pelo|com|em)\s+)?(?:pix|a\s+vista|boleto)\b|"
                                    r"^\s*com\s+(?:o\s+)?(?:cupom|desconto)\b")
# a linha de cima continua na de baixo quando termina numa preposição/dois-pontos ("... acima de" / "R$ 2.500")
_RE_FRASE_ABERTA = re.compile(r"(?:\bde|:|>|\bacima|\bpartir|\bminim[oa]|\bmin\.)\s*$")


def _contexto(texto: str, ini: int, fim: int) -> tuple[str, str]:
    """(antes, depois) do valor texto[ini:fim], sem acentos e em minúsculas, dentro da linha."""
    ini_linha = texto.rfind("\n", 0, ini) + 1
    fim_linha = texto.find("\n", fim)
    fim_linha = len(texto) if fim_linha < 0 else fim_linha
    antes = sem_acentos(texto[ini_linha:ini]).lower()
    if ini_linha > 0 and not re.search(r"[a-z0-9]", antes):
        anterior = sem_acentos(texto[texto.rfind("\n", 0, ini_linha - 1) + 1: ini_linha - 1]).lower()
        if _RE_FRASE_ABERTA.search(anterior):
            antes = anterior + "\n" + antes
    return antes, sem_acentos(texto[fim:fim_linha]).lower()


def _a_partir_de(antes: str, m: re.Match, depois: str = "") -> str:
    """Tipo de "a partir de R$ X" / "mín. R$ X" (m: o marcador no fim de antes)."""
    pre = antes[:m.start()]
    ini_linha = pre.rfind("\n") + 1
    duro = max((s.end() for s in _RE_SEP_FRASE.finditer(pre)), default=0)
    virgula = pre.rfind(",") + 1
    modelo = max((s.end() for s in _RE_MODELO_NA_FRASE.finditer(pre)), default=0)
    ini = max(duro, virgula, modelo)
    frase = pre[ini:]
    if _RE_CONTEXTO_CUPOM.search(frase):
        return "condicao"
    if not m.group().lstrip().startswith("a") and _RE_CONTEXTO_CUPOM.search(pre[ini_linha:]):
        return "condicao"  # "mín." numa linha de cupom: "🎟️ R$ 250 OFF (mín R$ 2.500)"
    # a cláusula (até o último separador forte: "(", "|", " - "...) com "com o cupom" é o preço com o cupom
    clausula = pre[max(duro, modelo, ini_linha):]
    if not _RE_COM_O_CUPOM.search(clausula):
        # o trecho da linha até o marcador (depois do modelo) anuncia o cupom: "Cupom TV300 (a partir de R$ 2.500)",
        # "Cupom TV300 | a partir de", "Cupom TV300, a partir de", "Cupom de R$ 300 a partir de R$ 2.500 no Pix",
        # "R$ 300 OFF na AliExpress (a partir de R$ 2.200)"; ou é linha de ingresso com OFF/%/desconto ("🎟️ 10% OFF,
        # a partir de R$ 2.500")
        trecho = pre[max(ini_linha, modelo):]
        if _RE_CUPOM_FORTE.search(trecho) or (
                _RE_LINHA_INGRESSO.search(pre[ini_linha:]) and _RE_CONTEXTO_CUPOM.search(trecho)):
            return "condicao"
    if _RE_PIX_NA_FRASE.search(clausula) or _RE_MARCA_PRECO_DEPOIS.search(depois):
        return "preco"  # "No Pix sai a partir de R$ X", "ou a partir de R$ X no Pix", "mínimo: R$ X no Pix"
    abre_frase = not re.search(r"[a-z0-9]", frase)
    return "preco" if abre_frase and m.group().lstrip().startswith("a") else "fraco"


def _termo_do_cupom(antes: str, depois: str) -> bool:
    """True se o valor vem depois do desconto do cupom, na mesma frase, sem marca de preço ("R$ 300 OFF para
    compras superiores a R$ 2.500", "R$ 300 OFF comprando R$ 2.500 ou mais"). "R$ 300 OFF: R$ 3.299" (nada entre
    o desconto e o valor), "..., sai por R$ 3.299", "R$ 3.299 no Pix" e o valor que se refere à própria TV
    ("R$ 300 OFF nesta TV de R$ 3.599") continuam sendo preço."""
    ini = max((s.end() for s in _RE_SEP_CLAUSULA.finditer(antes)), default=0)
    frase = antes[ini:]
    descontos = list(_RE_DESCONTO_DO_CUPOM.finditer(frase))
    if not descontos:
        return False
    entre = frase[descontos[-1].end():]
    if not re.search(r"[a-z0-9]", entre) or _RE_A_PROPRIA_TV.search(entre):
        return False
    if entre.rstrip().endswith(":") and not _RE_TERMO_DE_COMPRA.search(entre):
        # rótulo do preço final: "R$ 300 OFF no app: R$ 2.899", "Cupom de R$ 300 aplicado no carrinho: R$ 2.899"
        # (não "R$ 300 OFF válido para compras: R$ 2.500", que é o mínimo)
        return False
    return not (_RE_MARCA_PRECO_ANTES.search(frase) or _RE_MARCA_PRECO_DEPOIS.search(depois))


def classifica_valor(antes: str, depois: str, valor: Optional[float] = None) -> str:
    """Tipo de um valor da postagem pelo contexto (ver o comentário acima)."""
    if _RE_SETA_DEPOIS.search(depois):
        return "antigo"
    for tipo, r in _RE_DEPOIS:
        if r.search(depois):
            return tipo
    if _RE_SETA_ANTES.search(antes):
        return "preco"
    m = _RE_A_PARTIR_DE.search(antes)
    if m:
        return _a_partir_de(antes, m, depois)
    m = _RE_FAIXA_ANTES.search(antes)
    if m and classifica_valor(antes[:m.start()], m.group(2)) == "condicao":
        return "condicao"  # "Compras de R$ 800 a R$ 1.999": o fim da faixa também é condição do cupom
    for tipo, r in _RE_ANTES:
        if r.search(antes):
            if tipo == "parcela" and valor is not None and valor >= PISO_PRECO_TV and _RE_TOTAL_PARCELADO.search(antes):
                return "preco"
            return tipo
    m = _RE_MAIOR.search(antes)
    if m and re.search(r"[a-z0-9]", antes[antes.rfind("\n", 0, m.start()) + 1:m.start()]):
        return "condicao"  # só com palavra antes do ">" na MESMA linha
    if _termo_do_cupom(antes, depois):
        return "condicao"
    return "preco"


def valores_postagem(texto: str) -> list[tuple[float, str]]:
    """(valor, tipo) de cada "R$ ..." do texto, na ordem."""
    texto = texto or ""
    out = []
    for m in _RE_VALOR_POST.finditer(texto):
        v = parse_preco(m.group(1))
        if v:
            out.append((v, classifica_valor(*_contexto(texto, m.start(), m.end()), valor=v)))
    return out


def preco_postagem(texto: str, piso: float = 1000) -> Optional[float]:
    """Preço da TV numa postagem livre: o menor candidato >= piso; sem candidato, o menor valor "fraco" >= piso.
    Recebe só o trecho da 55C6K (filtro.bloco_55c6k), sem os valores de outros produtos."""
    vals = valores_postagem(texto)
    for tipo in ("preco", "fraco"):
        cand = [v for v, t in vals if t == tipo and v >= piso]
        if cand:
            return min(cand)
    return None


_RE_LINHA_DE_CUPOM = re.compile(r"cupo|codigo|\bcod\.|\boff\b|descont|frete|cashback|economi|volta", re.I)


def so_preco_abaixo_do_piso(texto: str, piso: float) -> bool:
    """True se o trecho não tem preço >= piso e anuncia um preço entre R$ 100 e o piso numa linha que não é de
    cupom/desconto/frete ("Tela de 55\" (modelo 55C6K) / R$ 1.499"): é peça/acessório, não a TV."""
    if preco_postagem(texto, piso) is not None:
        return False
    for linha in (texto or "").splitlines():
        if _RE_LINHA_DE_CUPOM.search(sem_acentos(linha)):
            continue
        if any(t == "preco" and 100 <= v < piso for v, t in valores_postagem(linha)):
            return True
    return False


def fmt_preco(v: Optional[float]) -> str:
    if v is None:
        return "—"
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def limpa_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


def sem_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def loja_canonica(nome: str) -> str:
    n = sem_acentos((nome or "").strip().lower())
    n = re.sub(r"\s+", " ", n)
    if n in config.LOJAS_CANONICAS:
        return config.LOJAS_CANONICAS[n]
    for k, v in config.LOJAS_CANONICAS.items():
        if k in n:
            return v
    return (nome or "").strip() or "?"


_RE_REL = re.compile(r"(\d+)\s*(min|minuto|h|hora|dia|semana|mes|mês|ano)", re.I)


def tempo_relativo_para_iso(texto: str) -> Optional[str]:
    """'23 dias', 'há 2 h', 'ontem', 'agora' -> ISO aproximado."""
    t = sem_acentos((texto or "").lower())
    base = agora()
    if not t:
        return None
    if "agora" in t or "momento" in t:
        return base.isoformat(timespec="seconds")
    if "ontem" in t:
        return (base - timedelta(days=1)).isoformat(timespec="seconds")
    if "hoje" in t:
        return base.isoformat(timespec="seconds")
    m = _RE_REL.search(t)
    if not m:
        return None
    n = int(m.group(1))
    u = m.group(2)
    if u.startswith("min"):
        d = timedelta(minutes=n)
    elif u.startswith("h"):
        d = timedelta(hours=n)
    elif u.startswith("dia"):
        d = timedelta(days=n)
    elif u.startswith("sem"):
        d = timedelta(weeks=n)
    elif u.startswith("me"):
        d = timedelta(days=30 * n)
    else:
        d = timedelta(days=365 * n)
    return (base - d).isoformat(timespec="seconds")


def iso_normaliza(s: Optional[str]) -> Optional[str]:
    """Aceita '2026-09-13T14:03:25-0300' ou ISO com Z e devolve ISO com dois-pontos no fuso."""
    if not s:
        return None
    s = s.strip()
    m = re.fullmatch(r"(.+T\d\d:\d\d:\d\d)([+-]\d\d)(\d\d)", s)
    if m:
        s = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_BR).isoformat(timespec="seconds")
    except ValueError:
        return s


def dias_desde(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_BR)
        return (agora() - dt).total_seconds() / 86400
    except ValueError:
        return None


# "10x de R$ 399,90 sem juros", "10x sem juros de R$ 399,90", "10x R$ 399,90 (s/ juros)"
_RE_PARCELA = re.compile(
    r"(?:em\s+at[ée]\s+)?(?P<n>\d{1,2})\s*x(?:[^\S\n]*(?P<sj1>(?:sem|s/)[^\S\n]*juros)[^\S\n]*|\s*)(?:de\s*)?"
    rf"R\$\s?(?P<v>{_NUM_BRL_SRC})(?!\d)(?P<sj2>[^\S\n]*(?:[-–—,][^\S\n]*|no[^\S\n]+cart[aã]o"
    r"(?:[^\S\n]+de[^\S\n]+cr[eé]dito)?[^\S\n]*)?\(?[^\S\n]*(?:sem|s/)[^\S\n]*juros)?",
    re.I,
)


def parcelado_no_texto(texto: str) -> Optional[str]:
    """Parcelamento 'Nx R$ V sem juros' do texto, olhando SÓ a primeira parcela citada.

    Se a primeira parcela não diz 'sem juros' (é 'com juros' ou não tem rótulo), devolve None. Nunca pula
    para uma parcela mais adiante: as fontes passam a página inteira (Amazon) e, na Casas Bahia, a próxima
    'sem juros' depois de '11x de R$ 399,83 com juros' era a de uma TV patrocinada (6x R$ 569,43).
    """
    m = _RE_PARCELA.search(texto or "")
    if not m or not (m.group("sj1") or m.group("sj2")) or int(m.group("n")) < 2:
        return None
    return f"{m.group('n')}x R$ {m.group('v')} sem juros"


# ---------- código de cupom ----------
# Código: palavra de 4 a 20 letras/dígitos ASCII (hífen no meio vale: "TCL-300") depois de "cupom", "código",
# "cód." (pulando palavras comuns, pontuação e emoji).
#   - com dígito: pode vir mais adiante na mesma linha ("CUPOM EXTRA NO APP: TCL300", "Cupom de R$ 200 OFF: TCL200");
#     em maiúsculas, em minúsculas começando por letra ("tcl300") ou misturado logo depois do marcador ou de ':'
#     ("Cupom: Magalu10", "Use o cupom BlackFriday10");
#   - só letras: em maiúsculas e logo depois de ':' ("Use o cupom: APROVEITANOML", "Cupom exclusivo: SOLTAODESCONTO"),
#     ou logo depois do marcador com um sinal explícito de código: verbo antes ("Use o cupom SOLTAODESCONTO"), aspas
#     ('CUPOM "LEVOUBARATO"'), traço ("CUPOM - LEVOUBARATO") ou o marcador "código"/"cód." ("Código LEVOUBARATO").
#     Sem sinal, a palavra seguinte a "cupom" é da manchete, não o código ("🚨 CUPOM VALENDO 🚨", "Cupom SHOPEE
#     liberado", "Cupom DESBLOQUEADO", "CUPOM LEVOUBARATO").
# Entre vários, vale o 1º com dígito. Nunca uma palavra do português ("CUPOM LIBERADO", "CUPOM DISPONÍVEL") nem um
# código de modelo de TV (55C6K).
_RE_MARCADOR_CUPOM = re.compile(r"(?<![a-z])(?:cupo(?:m|ns)|c[oó]digos?|c[oó]d\.?)(?![a-z])", re.I)
_RE_CODIGO = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
# código de modelo de TV (55C6K, 43S5K, 65QM8K, 50QNED70); "50OFF100" é cupom
_RE_MODELO_TV = re.compile(r"\d{2,3}(?!OFF)[A-Z]{1,5}\d{1,3}[A-Z]{0,3}")
# verbo (ou "com o") logo antes do marcador: "Use o cupom X", "Aplique o cupom X", "Com o cupom X"
_RE_VERBO_CUPOM = re.compile(r"\b(?:use|usem|usar|usando|utilize|utilizem|utilizar|aplique|apliquem|aplicar|aplicando|"
                             r"insira|inserir|digite|digitar|coloque|colocar|resgate|resgatar|ative|ativar|com|c/)\s+"
                             r"(?:(?:o|os|a|as|seu|esse|este|nosso)\s+)?$")
_BORDA_TOKEN = "\"“”'‘’`:;,.!?()[]{}*_~-–—#>«»|/"
_NAO_E_CUPOM = {
    # artigos, preposições e palavras que aparecem depois de "cupom" nas postagens
    "DE", "DO", "DA", "DOS", "DAS", "NA", "NO", "NAS", "NOS", "EM", "COM", "SEM", "PARA", "PRA", "POR", "OU", "E",
    "O", "A", "OS", "AS", "UM", "UMA", "SEU", "SUA", "NOSSO", "NOSSA", "ESSE", "ESSA", "ESTE", "ESTA", "AI", "LA",
    "EXCLUSIVO", "EXCLUSIVA", "VALIDO", "VALIDA", "DESCONTO", "DESCONTOS", "DISPONIVEL", "DISPONIVEIS", "ATIVADO",
    "ATIVADA", "ATIVO", "ATIVA", "APLICADO", "APLICADA", "AUTOMATICO", "AUTOMATICA", "PRIMEIRA", "MERCADO", "LINK",
    "LOJA", "SITE", "APLICAR", "RESGATE", "RESGATAR", "NOVO", "NOVA", "NOVOS", "NOVAS", "ABAIXO", "ACIMA", "AQUI",
    "PAGINA", "ESPECIAL", "SELECIONADO", "SELECIONADOS", "LIBERADO", "LIBERADA", "LIBERADOS", "EXTRA", "SURPRESA",
    "ESGOTADO", "ESGOTADA", "VOLTOU", "RELAMPAGO", "APP", "PIX", "HOJE", "AGORA", "OFF", "PAGO", "CARTAO",
    "PROMOCIONAL", "PROMO", "PROMOCAO", "GRATIS", "FRETE", "BONUS", "VALE", "DUPLO", "SECRETO", "ATUALIZADO",
    "NOVAMENTE", "PARCEIRO", "TODOS", "TODAS", "QUALQUER", "PRODUTO", "PRODUTOS", "CUPOM", "CUPONS", "CODIGO",
    "USE", "USAR", "USEM", "APLIQUE", "INSIRA", "DIGITE", "COPIE", "PRIME", "MEMBROS", "SMART", "NAO", "MAIS",
    "ATE", "FINAL", "VALOR", "MINIMO", "DIRETO", "CARRINHO", "CHECKOUT", "OFERTA", "OFERTAS", "PRECO", "LIMITADO",
    "LIMITADA", "ESTOQUE", "MOEDAS", "HDR10", "HDMI", "QLED", "OLED", "MINI", "LEVE",
    # palavras de manchete depois de "CUPOM" (verificador da rodada 4)
    "VALENDO", "FUNCIONANDO", "QUENTE", "ACABOU", "OFICIAL", "RENOVADO", "ABERTO", "BOMBA", "INSANO", "ENCONTRADO",
    "REATIVADO", "ACUMULATIVO", "DESCRICAO", "APROVEITE", "APROVEITEM", "CORRE", "CORRAM", "CORRA",
}


_ASPAS = "\"“”'‘’`«"
_TRACOS = "-–—"


def _tokens(linha: str) -> list[tuple[str, bool, bool, bool]]:
    """Palavras da linha, sem pontuação em volta: (palavra, é a 1ª da linha, vem logo depois de ':', tem marcador
    explícito de código: ':' antes, entre aspas ou depois de um traço)."""
    out = []
    primeiro, apos_dois_pontos, apos_traco = True, False, False
    for bruto in linha.split():
        tok = bruto.strip(_BORDA_TOKEN)
        # código colado numa palavra comum em minúsculas: "BRAE2ou BRFSAFF02", "cupom RISE15de Desconto"
        m = re.fullmatch(r"([A-Z0-9]{4,20})([a-z]{1,4})", tok)
        if m and m.group(2).upper() in _NAO_E_CUPOM:
            tok = m.group(1)
        if tok and re.search(r"\w", tok):
            dois_pontos = apos_dois_pontos or bruto.startswith(":")
            marcado = dois_pontos or apos_traco or bruto[0] in _ASPAS + _TRACOS
            out.append((tok, primeiro, dois_pontos, marcado))
            primeiro, apos_dois_pontos, apos_traco = False, False, False
        elif bruto.strip(_ASPAS + _TRACOS) == "":
            apos_traco = True  # "CUPOM - LEVOUBARATO", 'CUPOM " LEVOUBARATO "'
        if bruto.endswith(":"):
            apos_dois_pontos = True
    return out


def _eh_codigo(tok: str) -> bool:
    """4-20 letras/dígitos ASCII (hífen só no meio), com letra; nunca código de modelo de TV (55C6K)."""
    return bool(4 <= len(tok) <= 20 and _RE_CODIGO.fullmatch(tok) and re.search(r"[A-Za-z]", tok)
                and not _RE_MODELO_TV.fullmatch(tok.upper()))


def _caixa_de_codigo(tok: str, logo_depois: bool) -> bool:
    """Caixa de um código: maiúsculas; minúsculas começando por letra ("tcl300", não "23h59"); misturada só com
    dígito e logo depois do marcador ou de ':' ("Magalu10"), nunca colada numa palavra ("BRAE2ou")."""
    if tok.isupper():
        return True
    if tok.islower():
        return tok[0].isalpha()
    return logo_depois and tok[0].isalpha() and bool(re.search(r"\d", tok))


def cupom_no_texto(texto: str) -> Optional[str]:
    """Código de cupom de um texto ('use o cupom TECNOBLOG250'), ou None."""
    texto = texto or ""
    candidatos: list[tuple[int, str]] = []  # (prioridade, código): 0 com dígito, 1 só letras
    for m in _RE_MARCADOR_CUPOM.finditer(texto):
        ini_linha = texto.rfind("\n", 0, m.start()) + 1
        fim_linha = texto.find("\n", m.end())
        resto = texto[m.end(): len(texto) if fim_linha < 0 else fim_linha]
        verbo = bool(_RE_VERBO_CUPOM.search(sem_acentos(texto[ini_linha:m.start()]).lower()))
        manchete = m.group().isupper()  # "CUPOM" em maiúsculas: a palavra seguinte pode ser da manchete
        codigo = not m.group().lower().startswith("cupo")  # "Código X" / "Cód. X": o marcador já diz que é código
        toks = _tokens(resto)
        antes = len(candidatos)
        for tok, primeiro, apos_dois_pontos, marcado in toks:
            if sem_acentos(tok).upper() in _NAO_E_CUPOM or not _eh_codigo(tok):
                continue
            logo_depois = primeiro or apos_dois_pontos
            if not _caixa_de_codigo(tok, logo_depois):
                continue
            if re.search(r"\d", tok):
                candidatos.append((0, tok.upper()))
            elif tok.isupper() and (apos_dois_pontos or (primeiro and (verbo or marcado or codigo))):
                # só letras: logo depois de ':' ou logo depois do marcador com um sinal explícito de código (verbo
                # antes, aspas, traço, "código"). "Cupom SHOPEE liberado", "CUPOM VALENDO" não são código; nunca a
                # palavra seguinte a uma palavra comum ("CUPOM PRIMEIRA COMPRA")
                candidatos.append((1, tok))
        if len(candidatos) == antes and fim_linha >= 0:
            # nada na linha do marcador: o código pode abrir a linha de baixo ("Use o cupom abaixo 👇" / "TCL300").
            # Só com dígito, ou só letras quando a linha do marcador termina em ':' ("Cupom:" / "LEVOUBARATO") ou
            # é só o rótulo ("🎟️ Cupom" / "DESCONTAO"; não "🔥 CUPOM 🔥" / "APROVEITE", manchete em maiúsculas)
            prox = _tokens(texto[fim_linha + 1:].split("\n", 1)[0])[:1]
            for tok, _, _, _ in prox:
                if _eh_codigo(tok) and _caixa_de_codigo(tok, True) and sem_acentos(tok).upper() not in _NAO_E_CUPOM:
                    if re.search(r"\d", tok):
                        candidatos.append((0, tok.upper()))
                    elif tok.isupper() and (resto.rstrip().endswith(":")
                                            or (not re.search(r"[A-Za-z0-9]", resto) and not manchete)):
                        candidatos.append((1, tok))
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: c[0])[1]
