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


_RE_PRECO = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)")


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


_RE_PARCELA = re.compile(
    r"(?:em\s+at[ée]\s+)?(\d{1,2})\s*x\s*(?:de\s*)?R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)(\s*sem juros)?", re.I
)


def parcelado_no_texto(texto: str) -> Optional[str]:
    m = _RE_PARCELA.search(texto or "")
    if not m:
        return None
    sj = " sem juros" if m.group(3) else ""
    return f"{m.group(1)}x R$ {m.group(2)}{sj}"


_RE_CUPOM = re.compile(r"cupom\s*[:\-]?\s*[\"“']?([A-Z0-9][A-Z0-9\-]{3,24})[\"”']?", re.I)


def cupom_no_texto(texto: str) -> Optional[str]:
    """Extrai um código de cupom de um texto ('use o cupom TECNOBLOG250')."""
    for m in _RE_CUPOM.finditer(texto or ""):
        cod = m.group(1)
        if cod.upper() in {"DE", "NA", "NO", "PARA", "EXCLUSIVO", "EXCLUSIVA", "VALIDO", "VÁLIDO", "DESCONTO"}:
            continue
        if any(ch.isdigit() for ch in cod) or cod.isupper():
            return cod.upper()
    return None
