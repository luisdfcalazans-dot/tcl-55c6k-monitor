"""Prazo de entrega do GTA 6 (Code in Box e pacotes com o jogo) lido nas lojas, com o CEP de entrega do usuário.

O CEP vem SÓ de config.cep_entrega() (variável de ambiente CEP_ENTREGA: .env do PC, secret do GitHub). Ele nunca vai
para log, mensagem, teste, docs/data nem anotações: as funções daqui recebem o CEP e devolvem só a data. Sem a
variável, vale o CEP de referência (centro de São Paulo) e a oferta sai com extra['cep_referencia'] = True (prazo
aproximado).

Gravado na oferta (monitor/produtos.entrega lê): extra['entrega_prevista'] (data ISO), extra['entrega_ate_lancamento']
(chega até 18/11, a tempo de jogar à meia-noite de 19/11) e extra['cep_referencia'].
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

from .. import config, produtos
from ..util import agora, sem_acentos

# feriados nacionais que caem em dia útil até o começo de 2027 (prazo em "dias úteis" das lojas VTEX). 20/11 (Consciência
# Negra, Lei 14.759/2023) é sexta, logo depois do lançamento: quem não recebe até 19/11 recebe a partir de 21-23/11
FERIADOS = frozenset({
    "2026-10-12", "2026-11-02", "2026-11-15", "2026-11-20", "2026-12-25", "2027-01-01",
})

_MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10,
          "nov": 11, "dez": 12}
_RE_DIA_MES = re.compile(r"\b(\d{1,2})\s+de\s+(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*\.?(?:\s+de\s+(\d{4}))?")
_RE_DATA_BR = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_RE_ESTIMATIVA = re.compile(r"^\s*(\d{1,3})\s*(bd|d|h)\s*$", re.I)


def precisa(pid: Any) -> bool:
    """O produto traz o GTA 6 Code in Box (o jogo ou um pacote com ele): a entrega importa."""
    p = produtos.produto(pid)
    return bool(p and p.gta_fisico)


def cep() -> tuple[str, bool]:
    """(CEP só com dígitos, é o de referência?). O CEP do usuário não pode ser impresso."""
    return config.cep_entrega()


def hoje() -> date:
    return agora().date()


def e_dia_util(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in FERIADOS


def soma_dias_uteis(inicio: date, n: int) -> date:
    """`n` dias úteis depois de `inicio` (sábado, domingo e feriado nacional não contam)."""
    d = inicio
    while n > 0:
        d += timedelta(days=1)
        if e_dia_util(d):
            n -= 1
    return d


def dias_uteis_entre(inicio: date, fim: date) -> int:
    """Quantos dias úteis há depois de `inicio` até `fim` (inclusive): o inverso de soma_dias_uteis."""
    n, d = 0, inicio
    while d < fim:
        d += timedelta(days=1)
        if e_dia_util(d):
            n += 1
    return n


def inicio_pre_venda(envio: Any = None) -> date:
    """Primeiro dia em que a caixa do GTA 6 pode sair da loja: 12/11 (a Rockstar libera as caixas para o
    pré-carregamento) ou a data de envio que a loja informa ("envio a partir de 16/11"), a que for mais tarde."""
    d = date.fromisoformat(produtos.INICIO_ENVIO_GTA6)
    try:
        return max(d, date.fromisoformat(str(envio)[:10])) if envio else d
    except ValueError:
        return d


def ajusta_pre_venda(data_iso: Any, base: Optional[date] = None,
                     inicio: Optional[date] = None) -> tuple[Optional[str], bool]:
    """(data, ajustou?) da entrega de um GTA 6 físico na pré-venda. Antes de 12/11 (ou da data de envio informada) a
    caixa não existe: uma data anterior é o prazo da loja contado a partir de HOJE (estimativa da VTEX, cartão da
    Amazon, carrinho). O trânsito (dias úteis de `base`/hoje até ela, pelo menos 1) passa a contar do início do envio.
    Revisão de 03/10: "5bd" na Americanas virava "previsão 09/10 — chega a tempo"; o certo é 19/11 (no dia)."""
    if not data_iso:
        return None, False
    try:
        d = date.fromisoformat(str(data_iso)[:10])
    except ValueError:
        return None, False
    ini = inicio or inicio_pre_venda()
    h = base or hoje()
    if d >= ini or h >= ini:
        return d.isoformat(), False
    if d >= date.fromisoformat(produtos.INICIO_ENVIO_GTA6):
        # depois de 12/11, mas antes do envio que a própria loja informou: chega, no mínimo, 1 dia útil depois dele
        return soma_dias_uteis(ini, 1).isoformat(), True
    return soma_dias_uteis(ini, max(1, dias_uteis_entre(h, d))).isoformat(), True


def data_da_estimativa(estimativa: Any, base: Optional[date] = None) -> Optional[str]:
    """Prazo da VTEX ("39bd" = 39 dias úteis, "5d" = 5 dias corridos, "12h") em data ISO a partir de `base` (hoje)."""
    m = _RE_ESTIMATIVA.match(str(estimativa or ""))
    if not m:
        return None
    n, unid = int(m.group(1)), m.group(2).lower()
    b = base or hoje()
    if unid == "bd":
        return soma_dias_uteis(b, n).isoformat()
    if unid == "d":
        return (b + timedelta(days=n)).isoformat()
    return (b + timedelta(days=max(1, (n + 23) // 24))).isoformat()


def _ano_provavel(mes: int, dia: int, base: date) -> int:
    """Data sem ano ("16 de Novembro", "30/11"): o ano em que ela ainda está por vir (até ~2 meses para trás é o ano
    corrente: a página pode mostrar uma data que já passou por pouco)."""
    try:
        d = date(base.year, mes, dia)
    except ValueError:
        return base.year
    return base.year + 1 if (base - d).days > 60 else base.year


def data_por_extenso(texto: Any, base: Optional[date] = None) -> Optional[str]:
    """Primeira data em português do texto ("Segunda-feira, 16 de Novembro", "seg., 16 de nov.", "Chega dia 30 de
    novembro", "até 17/11/2026", "17/11/26") em ISO. None quando não há data."""
    t = sem_acentos(str(texto or "")).lower()
    b = base or hoje()
    m = _RE_DIA_MES.search(t)
    if m:
        dia, mes = int(m.group(1)), _MESES[m.group(2)]
        ano = int(m.group(3)) if m.group(3) else _ano_provavel(mes, dia, b)
        try:
            return date(ano, mes, dia).isoformat()
        except ValueError:
            return None
    m = _RE_DATA_BR.search(t)
    if m:
        dia, mes = int(m.group(1)), int(m.group(2))
        if not (1 <= mes <= 12 and 1 <= dia <= 31):
            return None
        ano = m.group(3)
        a = (2000 + int(ano) if len(ano) == 2 else int(ano)) if ano else _ano_provavel(mes, dia, b)
        try:
            return date(a, mes, dia).isoformat()
        except ValueError:
            return None
    return None


def chega_a_tempo(data_iso: Optional[str]) -> Optional[bool]:
    """A data chega até 18/11 (a tempo de jogar à meia-noite de 19/11)?"""
    if not data_iso:
        return None
    return data_iso[:10] <= produtos.ENTREGA_LIMITE_GTA6


def marca(o: Any, data_iso: Optional[str], referencia: bool, origem: str = "") -> None:
    """Grava o prazo na oferta (só no que traz o GTA 6 físico). `data_iso` None não apaga nada. Data antes de as
    caixas existirem (12/11, ou o envio que a loja informa) é reprojetada a partir delas (ajusta_pre_venda)."""
    if not data_iso or not precisa(getattr(o, "modelo", None)):
        return
    data, ajustou = ajusta_pre_venda(data_iso, inicio=inicio_pre_venda(o.extra.get("envio_a_partir")))
    if not data:
        return
    o.extra["entrega_prevista"] = data
    o.extra["entrega_ate_lancamento"] = chega_a_tempo(data)
    o.extra["cep_referencia"] = bool(referencia)
    if ajustou:
        origem = (origem + " " if origem else "") + "(prazo contado a partir de 12/11, quando saem as caixas)"
    if origem:
        o.extra["entrega_origem"] = origem


def marca_envio_tardio(o: Any, referencia: bool = False) -> None:
    """A loja diz que só envia a partir do lançamento ("ENVIO A PARTIR DE 19 DE NOVEMBRO"): chega depois, qualquer que
    seja o CEP (por isso, por padrão, não é prazo de CEP de referência)."""
    if not precisa(getattr(o, "modelo", None)):
        return
    o.extra["entrega_ate_lancamento"] = False
    o.extra["cep_referencia"] = bool(referencia)
    o.extra["entrega_origem"] = "texto do anúncio"


# "ENVIO A PARTIR DE 19 DE NOVEMBRO" (Carrefour), "SERA ENVIADO A PARTIR DO DIA:  20/11/2026" (parceiro na KaBuM)
_RE_ENVIO_A_PARTIR = re.compile(r"(?:envio|envios|enviad[oa]|despach\w*|entrega\w*)\s+(?:somente\s+|so\s+|apenas\s+)?"
                                r"a\s+partir\s+(?:de|do dia|da data)\s*:?\s*([^.\n<]{3,30})")


def envio_a_partir(texto: Any, base: Optional[date] = None) -> Optional[str]:
    """A data de "envio a partir de 19 de novembro" / "enviado a partir do dia 20/11/2026" do texto, ou None."""
    t = sem_acentos(str(texto or "")).lower()
    m = _RE_ENVIO_A_PARTIR.search(t)
    return data_por_extenso(m.group(1), base) if m else None


# CEP -> UF (faixas dos Correios). Só para escolher o estado nas consultas de preço que pedem a UF (Netshoes).
_FAIXAS_UF = (
    (1000, 19999, "SP"), (20000, 28999, "RJ"), (29000, 29999, "ES"), (30000, 39999, "MG"), (40000, 48999, "BA"),
    (49000, 49999, "SE"), (50000, 56999, "PE"), (57000, 57999, "AL"), (58000, 58999, "PB"), (59000, 59999, "RN"),
    (60000, 63999, "CE"), (64000, 64999, "PI"), (65000, 65999, "MA"), (66000, 68899, "PA"), (68900, 68999, "AP"),
    (69000, 69299, "AM"), (69300, 69399, "RR"), (69400, 69899, "AM"), (69900, 69999, "AC"), (70000, 72799, "DF"),
    (72800, 72999, "GO"), (73000, 73699, "DF"), (73700, 76799, "GO"), (76800, 76999, "RO"), (77000, 77999, "TO"),
    (78000, 78899, "MT"), (79000, 79999, "MS"), (80000, 87999, "PR"), (88000, 89999, "SC"), (90000, 99999, "RS"),
)


def uf_do_cep(cep_: Any) -> str:
    d = re.sub(r"\D", "", str(cep_ or ""))
    if len(d) != 8:
        return "SP"
    p = int(d[:5])
    return next((uf for a, b, uf in _FAIXAS_UF if a <= p <= b), "SP")
