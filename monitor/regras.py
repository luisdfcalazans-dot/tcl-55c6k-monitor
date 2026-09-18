"""Decide o que vira alerta. Cada alerta é uma mensagem HTML pronta para o Telegram."""

from __future__ import annotations

import html
import re
from typing import Optional

from . import config
from .estado import Estado
from .models import Cupom, Oferta
from .util import dias_desde, fmt_preco, loja_canonica, parse_preco, sem_acentos

_RE_ATE = re.compile(r"(?:compras?\s+)?(?:at[ée]|m[áa]ximo(?: de)?)\s*R\$\s?([\d.]+)", re.I)
_RE_ACIMA = re.compile(r"(?:acima de|a partir de|m[íi]nimo(?: de)?|compras?\s+(?:de|a partir de))\s*R\$\s?([\d.]+)", re.I)
_CATEGORIAS_FORA = [
    "moda", "roupa", "beleza", "perfum", "maquiagem", "supermercado", "mercado ", "bebida", "cerveja", "vinho", "livro",
    "brinquedo", "pet ", "petshop", "games", "celular", "smartphone", "iphone", "notebook", "moveis", "cama",
    "mesa e banho", "esporte", "treino", "bike", "calcado", "tenis", "infantil", "papelaria", "farmacia", "saude",
    "cuidados pessoais", "automotivo", "ferramenta", "jardim", "primeira compra", "novos clientes", "entrega", "frete",
    "app ", "aplicativo", "selecionados", "marca ", "cozinha", "eletroportateis", "geladeira", "fogao", "lavadora",
    "ar-condicionado", "ar condicionado", "informatica", "audio", "fone", "relogio", "oculos", "bolsa", "joia",
]
_CATEGORIAS_DENTRO = [
    "tv", "televis", "eletronic", "tecnolog", "site todo", "loja toda", "todo o site", "qualquer", "suas compras",
    "em compras", "no site", "todos os produtos", "primeira compra no site",
]
# Marcas e produtos que não são a TV: se aparecem no título/regra (palavra inteira) ou dentro do código, o cupom não serve
_MARCAS_OUTRAS = [
    "dyson", "jbl", "asus", "aoc", "ps5", "playstation", "xbox", "nintendo", "motorola", "moto", "oppo", "xiaomi",
    "galaxy", "iphone", "apple", "tablet", "lenovo", "edifier", "britania", "dinoxx", "haiflex", "beauty", "decor",
    "decoracao", "conta nova", "contas novas", "novos usuarios", "novo usuario", "whatsapp", "zap", "cashback",
    "edge", "signature", "gta", "gamer", "shark", "robo", "nivea", "livro", "livros", "leia", "audio", "selecao",
    "pet", "cama", "notebook", "monitor", "ssd", "placa de video", "processador", "mouse", "teclado", "headset",
    "cadeira", "fone", "caixa de som", "smartwatch", "relogio", "perfume", "cerveja", "vinho", "suplemento", "whey",
    "fralda", "bebe", "brinquedo", "pneu", "prime day", "pra casa", "para casa",
]
_CODIGO_OUTRAS = [m for m in _MARCAS_OUTRAS if " " not in m and len(m) >= 3]
_RE_EM_X = re.compile(r"\boff\s+em\s+(.{3,60})$")
_RE_EM_TUDO = re.compile(r"\bem tudo\b(?!\s+(?:pra|para)\b)")


def _num(s: str) -> Optional[float]:
    try:
        return float(s.replace(".", ""))
    except ValueError:
        return None


def cupom_compativel(c: Cupom, preco_loja: Optional[float]) -> tuple[bool, str]:
    """Verifica se a regra do cupom cabe na TV. Devolve (ok, motivo)."""
    if c.especifico:
        return True, "cupom do produto"
    texto = sem_acentos(f"{c.titulo} {c.regra}").lower()
    titulo = sem_acentos(c.titulo).lower().strip()
    codigo = sem_acentos(c.codigo).lower()
    for w in _MARCAS_OUTRAS:
        if re.search(r"\b" + re.escape(w) + r"\b", texto):
            return False, f"marca/produto: {w}"
    for w in _CODIGO_OUTRAS:
        if w in codigo:
            return False, f"código de outra marca: {w}"
    dentro = any(d in texto for d in _CATEGORIAS_DENTRO) or bool(_RE_EM_TUDO.search(texto))
    # "10% OFF em Cervejas": o que vem depois de "em" tem de ser o site todo, TV ou eletrônicos
    m = _RE_EM_X.search(titulo)
    if m:
        alvo = m.group(1)
        if not any(d in alvo for d in _CATEGORIAS_DENTRO):
            return False, f"categoria: {alvo[:30]}"
    for cat in _CATEGORIAS_FORA:
        if cat in texto and not dentro:
            return False, f"categoria: {cat.strip()}"
    p = preco_loja or config.ALVO_PARCELADO
    m = _RE_ATE.search(texto)
    if m:
        lim = _num(m.group(1))
        if lim and lim < p * 0.5:  # "até R$ 300" não serve para uma TV de R$ 3 mil
            return False, f"só até R$ {lim:.0f}"
    m = _RE_ACIMA.search(texto)
    if m:
        lim = _num(m.group(1))
        if lim and lim > p:
            return False, f"só acima de R$ {lim:.0f}"
    return True, ""


def _esc(s: Optional[str]) -> str:
    return html.escape(s or "", quote=False)


def _linha_preco(o: Oferta) -> str:
    partes = []
    if o.preco:
        partes.append(f"<b>{fmt_preco(o.preco)}</b>")
    if o.preco_pix and (not o.preco or abs(o.preco_pix - o.preco) > 0.5):
        partes.append(f"Pix {fmt_preco(o.preco_pix)}")
    if o.parcelado:
        partes.append(_esc(o.parcelado))
    if o.cupom:
        partes.append(f"cupom <code>{_esc(o.cupom)}</code>")
    return " · ".join(partes) if partes else "preço não informado"


def _msg_oferta(etiquetas: list[str], o: Oferta, anterior: Optional[float] = None) -> str:
    cab = " ".join(etiquetas)
    quem = o.loja + (f" (vendido por {o.vendedor})" if o.vendedor and o.vendedor != o.loja else "")
    linhas = [f"{cab} — <b>{_esc(quem)}</b>", _esc(o.titulo[:140]), _linha_preco(o)]
    if anterior:
        linhas.append(f"antes: {fmt_preco(anterior)}")
    if o.tipo == "post":
        linhas.append(f"via {_esc(o.fonte)}" + (f" · {_esc(o.publicado[:16].replace('T', ' '))}" if o.publicado else ""))
    linhas.append(o.url)
    return "\n".join(linhas)


def gerar_alertas(estado: Estado, ofertas: list[Oferta], cupons: list[Cupom]) -> tuple[list[str], dict[str, float]]:
    """Devolve (mensagens, {chave_oferta: preco_alertado})."""
    msgs: list[str] = []
    alertados: dict[str, float] = {}
    minimo_antes = estado.minimo()
    preco_minimo_antes = float(minimo_antes["preco"]) if minimo_antes else None

    lojas = [o for o in ofertas if o.tipo == "loja"]
    posts = [o for o in ofertas if o.tipo == "post"]

    # ---- preços de loja ----
    for o in lojas:
        p = o.melhor_preco
        if not p or not o.ativo:
            continue
        prev = estado.oferta_anterior(o.chave)
        etiquetas: list[str] = []
        anterior = None
        novo_minimo = preco_minimo_antes is not None and p < preco_minimo_antes
        if novo_minimo:
            etiquetas.append("🏆 MENOR PREÇO já visto")
        if prev is None:
            if not estado.bootstrap and (p <= config.ALVO_PARCELADO or (preco_minimo_antes and p <= preco_minimo_antes * 1.03)):
                etiquetas.append("🆕 Nova oferta")
        else:
            anterior = prev.get("ultimo_preco")
            if anterior and p < float(anterior) * (1 - config.QUEDA_MINIMA_PCT / 100):
                etiquetas.append("🔻 Queda de preço")
                anterior = float(anterior)
            else:
                anterior = None
        abaixo_alvo = (o.preco_pix and o.preco_pix <= config.ALVO_PIX) or p <= config.ALVO_PIX or \
            (o.preco and o.preco <= config.ALVO_PARCELADO and o.parcelado)
        if abaixo_alvo and not estado.bootstrap:
            ja = prev.get("preco_alertado") if prev else None
            if ja is None or p < float(ja) - 0.5:
                etiquetas.append("🎯 Abaixo do alvo")
        if etiquetas:
            msgs.append(_msg_oferta(etiquetas, o, anterior))
            alertados[o.chave] = p
        if novo_minimo:
            preco_minimo_antes = p

    # ---- postagens em sites de promoção e canais ----
    for o in posts:
        if estado.oferta_anterior(o.chave) is not None:
            continue
        if not o.ativo:
            continue
        d = dias_desde(o.publicado)
        if d is not None and d > 3:
            continue
        if estado.bootstrap:
            continue
        et = ["📣 Promoção postada"]
        if o.melhor_preco and o.melhor_preco <= config.ALVO_PIX:
            et.append("🎯")
        msgs.append(_msg_oferta(et, o))

    # ---- cupons ----
    preco_por_loja: dict[str, float] = {}
    for o in lojas:
        if o.melhor_preco and o.ativo:
            lc = loja_canonica(o.loja)
            preco_por_loja[lc] = min(preco_por_loja.get(lc, 1e9), o.melhor_preco)
    lojas_com_tv = set(preco_por_loja) | {"Amazon", "Magazine Luiza", "Mercado Livre", "KaBuM!", "Casas Bahia", "Fast Shop"}
    novos: list[str] = []
    codigos_vistos: set[str] = set()
    for c in cupons:
        if estado.cupom_anterior(c.chave) is not None or estado.bootstrap:
            continue
        lc = loja_canonica(c.loja)
        if lc not in lojas_com_tv and not c.especifico:
            continue
        ok, _motivo = cupom_compativel(c, preco_por_loja.get(lc))
        if not ok:
            continue
        marca = f"{lc}|{c.codigo.upper()}"
        if marca in codigos_vistos:
            continue  # o mesmo cupom no Promobit e no Pelando
        codigos_vistos.add(marca)
        pl = preco_por_loja.get(lc)
        linha = f"• <b>{_esc(lc)}</b> <code>{_esc(c.codigo)}</code> — {_esc(c.titulo[:90])}"
        if c.validade:
            linha += f" (até {_esc(c.validade[:10])})"
        if pl:
            linha += f" · TV lá: {fmt_preco(pl)}"
        if c.especifico:
            linha = "⭐ " + linha + " — cupom do produto"
        linha += f"\n  {c.url}"
        novos.append(linha)
    if novos:
        cab = "🎟️ <b>Novos cupons aplicáveis à TV</b>" if len(novos) > 1 else "🎟️ <b>Novo cupom aplicável à TV</b>"
        corpo = "\n".join(novos[:12])
        if len(novos) > 12:
            corpo += f"\n… e mais {len(novos) - 12} (veja o painel)"
        msgs.append(cab + "\n" + corpo)

    return msgs, alertados


_RE_PARCELA_TXT = re.compile(r"(\d{1,2})x\s*(?:de\s*)?R\$\s?([\d.]+(?:,\d{2})?)", re.I)


def sanear(ofertas: list[Oferta]) -> tuple[list[Oferta], list[str]]:
    """Tira preços que claramente não são desta TV antes de virarem alerta.

    Nasceu de um caso real: a página esgotada da Casas Bahia fez o coletor pegar o preço de uma
    Hisense do carrossel de recomendados (R$ 2.189) como se fosse a 55C6K.
    Duas checagens: parcelamento que não fecha com o preço, e preço fora da faixa das outras lojas.
    """
    from statistics import median

    avisos: list[str] = []
    # 1) parcelado incoerente com o preço -> o parcelado veio de outro produto
    for o in ofertas:
        if not o.parcelado or not o.melhor_preco:
            continue
        m = _RE_PARCELA_TXT.search(o.parcelado)
        if not m:
            continue
        total = int(m.group(1)) * (parse_preco(m.group(2)) or 0)
        if total and abs(total - o.melhor_preco) > max(80.0, o.melhor_preco * 0.2):
            avisos.append(f"{o.loja}: parcelado '{o.parcelado}' não fecha com {fmt_preco(o.melhor_preco)}")
            o.extra["parcelado_descartado"] = o.parcelado
            o.parcelado = None

    # 2) preço muito fora da faixa das demais lojas
    precos = [o.melhor_preco for o in ofertas if o.tipo == "loja" and o.ativo and o.melhor_preco]
    if len(precos) >= 4:
        meio = median(precos)
        piso, teto = meio * 0.55, meio * 2.2
        for o in ofertas:
            p = o.melhor_preco
            if o.tipo != "loja" or not o.ativo or not p or piso <= p <= teto:
                continue
            avisos.append(f"{o.loja}: {fmt_preco(p)} fora da faixa (mediana {fmt_preco(meio)}) — descartado")
            o.ativo = False
            o.extra["descartado"] = f"fora da faixa (mediana {meio:.2f})"
    return ofertas, avisos


def cupons_aplicaveis(ofertas: list[Oferta], cupons: list[Cupom]) -> list[Cupom]:
    """Só cupons de lojas que vendem a TV e cuja regra cabe no preço dela (para o painel e o resumo)."""
    preco_por_loja: dict[str, float] = {}
    for o in ofertas:
        if o.tipo == "loja" and o.melhor_preco and o.ativo:
            lc = loja_canonica(o.loja)
            preco_por_loja[lc] = min(preco_por_loja.get(lc, 1e9), o.melhor_preco)
    lojas_com_tv = set(preco_por_loja) | {"Amazon", "Magazine Luiza", "Mercado Livre", "KaBuM!", "Casas Bahia", "Fast Shop"}
    out: list[Cupom] = []
    vistos: set[str] = set()
    for c in cupons:
        lc = loja_canonica(c.loja)
        if lc not in lojas_com_tv and not c.especifico:
            continue
        if not cupom_compativel(c, preco_por_loja.get(lc))[0]:
            continue
        marca = f"{lc}|{c.codigo.upper()}"
        if marca in vistos:
            continue
        vistos.add(marca)
        out.append(c)
    return out


def resumo_diario(estado: Estado, ofertas: list[Oferta], cupons: list[Cupom]) -> str:
    lojas = sorted(
        [o for o in ofertas if o.tipo == "loja" and o.melhor_preco and o.ativo],
        key=lambda o: o.melhor_preco or 0,
    )
    linhas = ["☀️ <b>Resumo diário — TCL 55C6K</b>"]
    if lojas:
        for o in lojas[:10]:
            quem = o.loja + (f"/{o.vendedor}" if o.vendedor and o.vendedor != o.loja else "")
            extra = f" · {o.parcelado}" if o.parcelado else ""
            linhas.append(f"• {_esc(quem)}: <b>{fmt_preco(o.melhor_preco)}</b>{_esc(extra)}")
    else:
        linhas.append("• nenhum preço de loja coletado")
    m = estado.minimo()
    if m:
        linhas.append(f"Menor já visto: {fmt_preco(float(m['preco']))} ({_esc(m['loja'])}, {m['quando'][:10]})")
    linhas.append(f"Alvo: Pix {fmt_preco(config.ALVO_PIX)} · parcelado {fmt_preco(config.ALVO_PARCELADO)}")
    if cupons:
        cods = ", ".join(sorted({f"{loja_canonica(c.loja)} {c.codigo}" for c in cupons}))[:400]
        linhas.append(f"Cupons ativos: {_esc(cods)}")
    return "\n".join(linhas)


def mensagem_bootstrap(ofertas: list[Oferta], cupons: list[Cupom], modo: str) -> str:
    lojas = sorted([o for o in ofertas if o.tipo == "loja" and o.melhor_preco], key=lambda o: o.melhor_preco or 0)
    posts = [o for o in ofertas if o.tipo == "post"]
    linhas = [f"✅ <b>Monitor da TCL 55C6K iniciado</b> (modo {modo})"]
    for o in lojas[:8]:
        linhas.append(f"• {_esc(o.loja)}: <b>{fmt_preco(o.melhor_preco)}</b>" + (f" · {_esc(o.parcelado)}" if o.parcelado else ""))
    linhas.append(f"{len(posts)} postagens antigas registradas, {len(cupons)} cupons ativos. A partir de agora só chegam novidades.")
    return "\n".join(linhas)


def mensagem_fonte_quebrada(nome: str, falhas: int, erro: str) -> str:
    return f"⚠️ Fonte <b>{_esc(nome)}</b> falhou {falhas} vezes seguidas.\n<code>{_esc(erro[:200])}</code>"
