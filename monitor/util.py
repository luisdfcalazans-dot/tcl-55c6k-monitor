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
#   preco     candidato: cartão, Pix, "com cupom", "Preço mínimo: R$ X", o valor DEPOIS de uma seta e "A partir
#             de R$ X" abrindo a linha/frase sem contexto de cupom (formato do Canaltech)
#   fraco     só vale se não houver candidato: "a partir de R$ X" no meio da frase e "mín./mínimo: R$ X", sem
#             contexto de cupom, e "R$ X mais barato..." (diferença quando há outro preço; o preço quando é o único)
#   antigo    "De R$ X", "era/estava/antes R$ X", o valor ANTES de uma seta (->, =>, >>, ➡️, →, ⏩) ou de "por R$ Y"
#   condicao  mínimo do cupom: "acima de", "a partir de"/"mín." num contexto de cupom/desconto, "compras de",
#             "valor/pedido mínimo", "compra mínima", "> R$" / ">= R$" (fora de seta), "gastando", "em compras"
#   teto      "máximo de", "desconto máximo", "limitado a", "limite de"
#   desconto  "R$ X OFF", "R$ X de desconto", "economize", "desconto de", "cupom de", "cashback", "de volta"
#   parcela   "10x de R$ X", "10x R$ X", "parcelas de", "R$ X/mês"
# O preço da TV é o menor candidato >= piso (abaixo de R$ 1.500 nenhum valor é o preço desta TV); sem candidato,
# o menor "fraco" >= piso.

PISO_PRECO_TV = 1500.0  # abaixo disso nenhum valor é o preço da 55C6K (peça, acessório, parcela, desconto)
_RE_VALOR_POST = re.compile(r"R\$\s*" + _NUM_BRL)  # aceita "R$  3.599" (espaço duplo, comum nos canais)
_SETA = r"(?:-+>|=+>|>>|➡️|➡|→|⏩|⇒|➔|➜|⟶)"
_RE_SETA_ANTES = re.compile(_SETA + r"\s*$")
_RE_SETA_DEPOIS = re.compile(r"^\s*" + _SETA)
_RE_DEPOIS = [
    ("desconto", re.compile(r"^\s*\)?\s*(?:off\b|de\s+desconto|de\s+economia|de\s+cashback|em\s+cashback|"
                            r"de\s+volta|a\s+menos\b)")),
    ("condicao", re.compile(r"^\s*(?:em\s+(?:compras|pedidos|produtos)|nas\s+compras|ou\s+mais\s+em\s+compras)")),
    ("parcela", re.compile(r"^\s*(?:x\s*\d|/\s*mes|por\s+mes\b|mensais)")),
    ("antigo", re.compile(r"^\s*[),;]?\s*(?:por|para|pra)\s*:?\s*r\$")),
    ("fraco", re.compile(r"^\s*(?:de\s+|\(\s*)?mais\s+barat")),
]
_RE_ANTES = [
    ("parcela", re.compile(r"(?:\b\d{1,2}\s*(?:x|vezes)\s*(?:(?:sem|s/)\s*juros\s*)?(?:de\s*)?|"
                           r"\bparcelas?\s+(?:de\s*)?)[:\-]?\s*$")),
    ("teto", re.compile(r"(?:\bmaxim[oa]|\bmax\.?|\blimitad[oa]\s+a|\blimite|\bteto)(?:\s+de)?\s*[:\-]?\s*$")),
    ("desconto", re.compile(r"(?:\beconomi\w*|\bdesconto\s+de|(?<!com\s)(?<!%\sde\s)\bdesconto\s*:|\bcashback|"
                            r"\bcupom\s+de|\boff\s+de|\bganhe|"
                            r"\bvolta\s+de)(?:\s+de)?\s*[:\-]?\s*$")),
    ("condicao", re.compile(
        r"(?:\bacima\s+de|"
        r"\b(?:compras?|pedidos?|carrinho|produtos?|gastos?)\s+(?:(?:a\s+partir|acima|minim[oa]s?)\s+)?de|"
        r"\b(?:gastando|gaste|gastar)(?:\s+(?:a\s+partir\s+de|acima\s+de|mais\s+de|de))?|"
        r"\b(?:comprando|compre)\s+(?:a\s+partir\s+de|acima\s+de|mais\s+de)|"
        r"\b(?:valor|pedido|compra|carrinho|gasto)s?\s+minim[oa]s?(?:\s+(?:de|do|da|no|na|para)\b)?"
        r"(?:\s+(?:pedido|compra|carrinho|valor|gasto)s?\b)?|"
        r"\bminim[oa]s?\s+(?:de|do|da|no|na|para)\s+(?:pedido|compra|carrinho|valor|gasto)s?\b|"
        r"(?<![-=>])>=?|≥"
        r")\s*[:\-]?\s*$")),
    ("antigo", re.compile(r"(?:(?:^|[^a-z0-9\s])\s*de|\bera|\bestava|\bcustava|\bantes|\bantigo|\bsaia\s+por|"
                          r"\b(?:caiu|baixou|saiu|desceu)\s+de)\s*[:\-]?\s*$")),
]
# "a partir de R$ X" e "mín./mínimo: R$ X" soltos: mínimo de cupom quando a mesma frase fala de cupom/desconto
# antes ("Cupom TV300 (mín. R$ 2.500)", "R$ 250 OFF a partir de R$ 2.500"); senão, preço "fraco" ("A partir de
# R$ 3.349,00" do Canaltech, "com cupom a partir de R$ 2.899", "📉 Mínimo: R$ 2.899")
_RE_A_PARTIR_DE = re.compile(r"(?:\ba\s+partir\s+de|(?<!preco\s)(?<!precos\s)\bmin(?:\.|im[oa]s?\b))\s*[:\-]?\s*$")
_RE_CONTEXTO_CUPOM = re.compile(r"cupo(?:m|ns)\s*:?\s*[a-z]*\d|\boff\b|descont|valid|compra|pedido|produto|frete|"
                                r"cashback|economi|%|\bgast|carrinho")
_RE_SEP_FRASE = re.compile(r"[|•·;/(]")
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
            antes = anterior + " " + antes
    return antes, sem_acentos(texto[fim:fim_linha]).lower()


def classifica_valor(antes: str, depois: str) -> str:
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
        frase = _RE_SEP_FRASE.split(antes)[-1]
        if _RE_CONTEXTO_CUPOM.search(frase):
            return "condicao"
        # "A partir de R$ 3.349,00" abrindo a linha (ou a frase, depois de "|" ou "/"): o preço do Canaltech
        abre_frase = not re.search(r"[a-z0-9]", _RE_SEP_FRASE.split(antes[:m.start()])[-1])
        return "preco" if abre_frase and m.group().lstrip().startswith("a") else "fraco"
    for tipo, r in _RE_ANTES:
        if r.search(antes):
            return tipo
    return "preco"


def valores_postagem(texto: str) -> list[tuple[float, str]]:
    """(valor, tipo) de cada "R$ ..." do texto, na ordem."""
    texto = texto or ""
    out = []
    for m in _RE_VALOR_POST.finditer(texto):
        v = parse_preco(m.group(1))
        if v:
            out.append((v, classifica_valor(*_contexto(texto, m.start(), m.end()))))
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
    rf"R\$\s?(?P<v>{_NUM_BRL_SRC})(?!\d)(?P<sj2>[^\S\n]*\(?[^\S\n]*(?:sem|s/)[^\S\n]*juros)?",
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
# Código: palavra de 4 a 20 letras/dígitos ASCII depois de "cupom", "código", "cód." (pulando palavras comuns,
# pontuação e emoji). Só letras: tem de estar em maiúsculas e ser a 1ª palavra depois do marcador. Com dígito:
# pode vir mais adiante na mesma linha ("CUPOM EXTRA NO APP: TCL300", "Cupom de R$ 200 OFF: TCL200"). Entre
# vários, vale o 1º com dígito. Nunca uma palavra do português ("CUPOM LIBERADO", "CUPOM DISPONÍVEL") nem um
# código de modelo de TV (55C6K).
_RE_MARCADOR_CUPOM = re.compile(r"(?<![a-z])(?:cupo(?:m|ns)|c[oó]digos?|c[oó]d\.?)(?![a-z])", re.I)
_RE_CODIGO = re.compile(r"[A-Za-z0-9]{4,20}")
_RE_MODELO_TV = re.compile(r"\d{2,3}[A-Z]{1,5}\d{1,3}[A-Z]{0,3}")
_BORDA_TOKEN = "\"“”'‘’:;,.!?()[]{}*_~-–—#>«»|/"
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
}


def _tokens(linha: str) -> list[tuple[str, bool]]:
    """Palavras da linha, sem pontuação em volta, e se cada uma abre a frase (1ª da linha ou depois de ':')."""
    out = []
    abre = True
    for bruto in linha.split():
        tok = bruto.strip(_BORDA_TOKEN)
        # código colado numa palavra comum em minúsculas: "BRAE2ou BRFSAFF02", "cupom RISE15de Desconto"
        m = re.fullmatch(r"([A-Z0-9]{4,20})([a-z]{1,4})", tok)
        if m and m.group(2).upper() in _NAO_E_CUPOM:
            tok = m.group(1)
        if tok and re.search(r"\w", tok):
            out.append((tok, abre))
            abre = False
        if bruto.endswith(":"):
            abre = True
    return out


def _eh_codigo(tok: str) -> bool:
    """4-20 letras/dígitos ASCII, com letra; em maiúsculas, ou em minúsculas começando por letra ("tv300", não
    "23h59"); nunca misturado ("BRAE2ou") nem código de modelo de TV (55C6K)."""
    return bool(_RE_CODIGO.fullmatch(tok) and re.search(r"[A-Za-z]", tok)
                and (tok.isupper() or (tok.islower() and tok[0].isalpha()))
                and not _RE_MODELO_TV.fullmatch(tok.upper()))


def cupom_no_texto(texto: str) -> Optional[str]:
    """Código de cupom de um texto ('use o cupom TECNOBLOG250'), ou None."""
    texto = texto or ""
    candidatos: list[tuple[int, str]] = []  # (prioridade, código): 0 com dígito, 1 só letras
    for m in _RE_MARCADOR_CUPOM.finditer(texto):
        fim_linha = texto.find("\n", m.end())
        resto = texto[m.end(): len(texto) if fim_linha < 0 else fim_linha]
        toks = _tokens(resto)
        antes = len(candidatos)
        for tok, abre in toks:
            if sem_acentos(tok).upper() in _NAO_E_CUPOM:
                continue
            valido = _eh_codigo(tok)
            if valido and re.search(r"\d", tok):
                candidatos.append((0, tok.upper()))
            elif valido and abre and tok.isupper():
                # só letras: logo depois do marcador ou de ':' ("Cupom exclusivo: SOLTAODESCONTO"); nunca a
                # palavra seguinte a uma palavra comum ("CUPOM PRIMEIRA COMPRA")
                candidatos.append((1, tok))
        if len(candidatos) == antes and fim_linha >= 0:
            # nada na linha do marcador: o código pode abrir a linha de baixo ("Use o cupom abaixo 👇" / "TCL300").
            # Só com dígito, ou só letras quando a linha do marcador termina em ':' ("Cupom:" / "LEVOUBARATO")
            prox = _tokens(texto[fim_linha + 1:].split("\n", 1)[0])[:1]
            for tok, _ in prox:
                if _eh_codigo(tok) and sem_acentos(tok).upper() not in _NAO_E_CUPOM:
                    if re.search(r"\d", tok):
                        candidatos.append((0, tok.upper()))
                    elif tok.isupper() and resto.rstrip().endswith(":"):
                        candidatos.append((1, tok))
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: c[0])[1]
