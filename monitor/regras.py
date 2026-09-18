"""Decide o que vira alerta. Cada alerta é uma mensagem HTML pronta para o Telegram."""

from __future__ import annotations

import html
import re
from typing import Optional

from . import config
from .estado import Estado, conta_como_preco, lojas_diretas, marca_cupom
from .models import Cupom, Oferta
from .util import dias_desde, fmt_preco, loja_canonica, parse_preco, sem_acentos

# "até R$ X" só limita o valor da COMPRA quando vem ligado a ela: "compras até R$ 600", "válido para compras até
# R$300", "pedidos de até R$ 1000", "compra máxima de R$ 500". Já "Economize até R$ 300", "25% OFF até R$ 800" e
# "desconto máximo de R$ 500" são tetos do DESCONTO, que não impedem o cupom de servir para a TV.
_RE_ATE = re.compile(
    r"(?:compras?|pedidos?)\s+(?:de\s+)?at[ée]\s*R\$\s?([\d.]+)|compra\s+m[áa]xima(?:\s+de)?\s*R\$\s?([\d.]+)", re.I)
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
    "tv", "televis", "eletronic", "tecnolog", "site todo", "loja toda", "todo o site", "todo site", "qualquer", "suas compras",
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
    # cosméticos que aparecem em cupons do Mercado Livre com título genérico (ISDIN15, MANTECORP14...)
    "isdin", "mantecorp", "avene", "garnier", "loreal", "maybelline",
]
_CODIGO_OUTRAS = [m for m in _MARCAS_OUTRAS if " " not in m and len(m) >= 3]
_RE_EM_X = re.compile(r"\boff\s+em\s+(.{3,60})$")
_RE_EM_TUDO = re.compile(r"\bem tudo\b(?!\s+(?:pra|para)\b)")
# nome da loja no texto não é categoria ("Mercado Livre" não é o "mercado" das compras de supermercado)
_RE_LOJA_NO_TEXTO = re.compile(
    r"\b(?:(?:na|no|da|do)\s+)?(?:mercado\s*livre|magazine\s+luiza|magalu|amazon|aliexpress|kabum|shopee|"
    r"fast\s*shop|casas\s+bahia)\b")
# "OFF em compras acima de R$ 3.000" / "a partir de" / "de até": é o valor da compra, não uma categoria
_RE_ALVO_COMPRAS = re.compile(
    r"^(?:suas\s+|nas\s+)?(?:compras|pedidos)\s+(?:acima\s+(?:de\s+)?|a\s+partir\s+de|(?:de\s+)?ate|de)\s*r\$\s?[\d.,]+"
    r"(.*)$")
_RE_COMPRAS_MINIMO = re.compile(r"\bem\s+(?:compras|pedidos)\s+(?:acima\s+de|a\s+partir\s+de)\s*r\$\s?[\d.,]+")
_RE_FRETE_EXCLUIDO = re.compile(r"\b(?:excluido|exceto|excluindo|sem contar)\s+(?:o\s+)?(?:valor\s+d[oe]\s+)?frete\b")
# depois de tirar a loja, o valor mínimo e "(acima de R$1) com cupom", estes alvos valem para o site todo
_ALVOS_GERAIS = {"", "compras", "pedidos", "geral", "tudo", "ofertas", "ofertas gerais", "produtos", "todo site",
                 "seus pedidos", "suas compras", "toda a loja", "toda loja"}

# ---- cupom que vale só para uma parte da loja (rodada 3) ----
# Serve para a TV só quando a parte é TV, eletrônicos ou tecnologia, ou quando o texto diz o site todo.
_RE_TV_TECH = re.compile(r"\btvs?\b|televis|eletronic|tecnolog")
_RE_SITE_TODO = re.compile(r"site todo|todo o site|todo site|loja toda|toda a loja|todas as categorias|todos os produtos")
# "pedido mínimo R$ 79 na categoria Casa"
_RE_NA_CATEGORIA = re.compile(r"\bcategoria[:\s]+(?:de\s+)?([a-z][^.;,()|]{2,40})")
# seleção sem dizer qual: "itens selecionados", "produtos participantes", "produtos do link", "lista de itens".
# É vago: o Pelando escreve "em Selecionados" em quase todo cupom do Mercado Livre, inclusive nos que o Promobit
# mostra valendo para o site todo (REG-1: MELIACHAPROMO). Recusa o anúncio, mas não o código (ver restricao_do_codigo).
_RE_SELECAO = re.compile(r"\bselecionad\w*|\bselecionas\b|\b(?:produtos|itens)\b[^.;|]{0,40}?\bparticipantes?\b"
                         r"|\b(?:produtos|itens) do link\b|\blista de itens\b")
_RE_PALAVRAS_DE_SELECAO = re.compile(
    r"\b(?:itens|produtos|categorias?|selecionad\w*|selecionas|participantes?|da promocao|do link)\b")
# cupom de outro produto: um kit, ou uma TV de outro tamanho ("na Smart TV TCL 50 QLED 4K P7L")
_RE_OUTRO_PRODUTO = re.compile(r"\bkit\b|\bsmart\s*tv\s+(?:[a-z]+\s+){0,2}(?!55\b)\d{2}\b")
# "acima R$1", "limite R$500", "sem mínimo": condição de valor, não categoria
_RE_CONDICAO_VALOR = re.compile(
    r"\b(?:acima|a partir|limite|limitad[oa]|minimo|maximo|sem)\b(?:\s+(?:de|a|do)\b)?\s*(?:r\$\s?[\d.,]+)?|r\$\s?[\d.,]+")
# só para quem nunca comprou: "(1ª Compra / APP)", "nas 4 primeiras compras", "novos clientes", "contas novas"
_RE_SO_NOVOS = re.compile(r"\b(?:1a|1o|primeir[oa]s?)\s+(?:compras?|pedidos?)\b"
                          r"|\bnov[oa]s\s+(?:clientes|usuarios|contas)\b|\bcontas?\s+novas?\b")
# "... com cupom Mercado Livre", "usando o cupom X aproveite...": o resto do título não é categoria
_RE_COM_CUPOM_FIM = re.compile(r"\b(?:com|usando|aplicando)\s+(?:o\s+)?(?:cupom|voucher|codigo)\b.*$")


def _alvo_do_titulo(titulo: str) -> Optional[str]:
    """O que vem depois do ÚLTIMO 'em' do título (sem a loja, parênteses e 'com cupom'): '20% OFF em Casa no Mercado
    Livre (acima de R$79) com cupom' -> 'casa'; '20% OFF, máximo R$ 60, em R$ 79 em Casa' -> 'casa'.
    None: o título não diz "em <algo>" ('em R$ 79' e 'em até 10x' não contam). '': o anúncio acaba em "em" (cortado)."""
    t = _RE_LOJA_NO_TEXTO.sub(" ", titulo)
    t = re.sub(r"\([^)]*\)?", " ", t)
    t = _RE_COM_CUPOM_FIM.sub(" ", t)
    t = re.sub(r"[\s!.,:;|-]+$", "", t)
    ems = [m for m in re.finditer(r"\bem\b\s*", t) if not re.match(r"r\$|\d|ate\s+\d", t[m.end():])]
    return t[ems[-1].end():] if ems else None


def _alvo_categoria(alvo: str) -> str:
    """'compras acima de r$ 740 na aliexpress com cupom' -> ''; '... limitado a r$500 em selecionados' -> 'selecionados'."""
    m = _RE_ALVO_COMPRAS.match(alvo)
    if m:
        em = re.search(r"\bem\s+(.{3,60})$", m.group(1))
        alvo = em.group(1) if em else ""
    alvo = _RE_LOJA_NO_TEXTO.sub(" ", alvo)
    alvo = re.sub(r"\([^)]*\)?|\bcom cupom\b", " ", alvo)
    return re.sub(r"[\s!.,:;-]+", " ", alvo).strip()


def _num(s: str) -> Optional[float]:
    try:
        return float(s.replace(".", ""))
    except ValueError:
        return None


def _motivo_marca(texto: str, codigo: str) -> str:
    """'marca/produto: x' quando o cupom é de outra marca ou produto; '' quando não."""
    for w in _MARCAS_OUTRAS:
        if re.search(r"\b" + re.escape(w) + r"\b", texto):
            return f"marca/produto: {w}"
    for w in _CODIGO_OUTRAS:
        if w in codigo:
            return f"código de outra marca: {w}"
    return ""


def _texto_cat(texto: str) -> str:
    """Texto para as categorias: sem o nome da loja, sem "em compras acima de R$ X" (valor mínimo, não "site todo")
    e sem "excluído o valor do frete" (regra do desconto, não cupom de frete)."""
    return _RE_FRETE_EXCLUIDO.sub(" ", _RE_COMPRAS_MINIMO.sub(" ", _RE_LOJA_NO_TEXTO.sub(" ", texto)))


def _parte_da_loja(titulo: str, texto_cat: str) -> tuple[str, str]:
    """A parte da loja a que o anúncio diz que o cupom se limita, quando não é TV/eletrônicos/tecnologia nem o site
    todo: ('categoria', 'casa') para "20% OFF em Casa" ou "na categoria Casa"; ('restrito', 'selecionados') para uma
    seleção sem dizer qual ("em Selecionados", "em itens selecionados acima R$1 - Limite R$500") ou anúncio cortado
    ("15% de Desconto em"); ('', '') quando o anúncio não limita (ou limita a TV/tecnologia/site todo)."""
    m = _RE_NA_CATEGORIA.search(texto_cat)
    if m:
        cat = m.group(1).strip()
        if cat not in _ALVOS_GERAIS and not (_RE_TV_TECH.search(cat) or _RE_SITE_TODO.search(cat)):
            return "categoria", cat[:30]
    # o que vem depois do último "em" do título: "10% OFF em Cervejas", "20% de Desconto em Periféricos",
    # "... em R$ 79 em Casa"
    alvo = _alvo_do_titulo(titulo)
    if alvo == "":
        return "restrito", "anúncio cortado (sem a categoria)"
    if alvo is not None:
        alvo = _alvo_categoria(alvo)
        if alvo not in _ALVOS_GERAIS and not any(d in alvo for d in _CATEGORIAS_DENTRO):
            resto = _RE_PALAVRAS_DE_SELECAO.sub(" ", _RE_CONDICAO_VALOR.sub(" ", alvo))
            if not re.sub(r"[\W_]+", "", resto):
                return "restrito", alvo[:30]  # "em Selecionados acima R$1 - Limite R$500": seleção vaga
            return "categoria", alvo[:30]
    return "", ""


def cupom_compativel(c: Cupom, preco_loja: Optional[float]) -> tuple[bool, str]:
    """Verifica se a regra do cupom cabe na TV. Devolve (ok, motivo)."""
    if c.especifico:
        return True, "cupom do produto"
    texto = sem_acentos(f"{c.titulo} {c.regra}").lower()
    titulo = sem_acentos(c.titulo).lower().strip()
    marca = _motivo_marca(texto, sem_acentos(c.codigo).lower())
    if marca:
        return False, marca
    m = _RE_OUTRO_PRODUTO.search(texto)
    if m and "c6k" not in texto:
        return False, f"outro produto: {m.group(0)}"
    m = _RE_SO_NOVOS.search(texto)
    if m:
        return False, f"só para novos clientes: {m.group(0)}"
    texto_cat = _texto_cat(texto)
    # cupom de uma parte da loja: só serve se a parte for TV, eletrônicos, tecnologia ou o site todo
    tipo, parte = _parte_da_loja(titulo, texto_cat)
    if tipo:
        return False, f"{tipo}: {parte}"
    dentro = any(d in texto_cat for d in _CATEGORIAS_DENTRO) or bool(_RE_EM_TUDO.search(texto_cat))
    for cat in _CATEGORIAS_FORA:
        if cat == "selecionados":
            continue  # seleção vaga: vale a regra de baixo
        if cat in texto_cat and not dentro:
            return False, f"categoria: {cat.strip()}"
    # "APLICÁVEL A ITENS SELECIONADOS", "válido para produtos do link": só se a seleção for de TV/tecnologia
    m = _RE_SELECAO.search(texto_cat)
    if m and not (_RE_TV_TECH.search(texto_cat) or _RE_SITE_TODO.search(texto_cat) or _RE_EM_TUDO.search(texto_cat)):
        return False, f"restrito: {m.group(0)}"
    p = preco_loja or config.ALVO_PARCELADO
    m = _RE_ATE.search(texto)
    if m:
        lim = _num(m.group(1) or m.group(2))
        if lim and lim < p * 0.5:  # "compras até R$ 300" não serve para uma TV de R$ 3 mil
            return False, f"só até R$ {lim:.0f}"
    m = _RE_ACIMA.search(texto)
    if m:
        lim = _num(m.group(1))
        if lim and lim > p:
            return False, f"só acima de R$ {lim:.0f}"
    return True, ""


# ---- cupom já alertado ----
# Lojas que vendem a TV mesmo quando a rodada não trouxe preço delas (cupom dessas lojas pode virar alerta)
_LOJAS_COM_TV = {"Amazon", "Magazine Luiza", "Mercado Livre", "KaBuM!", "Casas Bahia", "Fast Shop"}

# Regra de compatibilidade do código anterior a 18/09/2026. Serve SÓ para ler estados antigos, que não registravam
# quais cupons viraram alerta: o código da época alertava justamente os cupons novos que esta regra aceitava, e ela
# recusava muitos que servem para a TV ("Economize até R$ 300", "OFF em compras acima de R$ 3.000", o "mercado" do
# nome da loja). A lista de marcas é a atual: um cupom de marca que ela recusa não vira alerta de qualquer jeito.
_RE_ATE_ANTIGO = re.compile(r"(?:compras?\s+)?(?:at[ée]|m[áa]ximo(?: de)?)\s*R\$\s?([\d.]+)", re.I)
_DENTRO_ANTIGO = [d for d in _CATEGORIAS_DENTRO if d != "todo site"]


def _compativel_regra_antiga(c: Cupom, preco_loja: Optional[float]) -> bool:
    if c.especifico:
        return True
    texto = sem_acentos(f"{c.titulo} {c.regra}").lower()
    titulo = sem_acentos(c.titulo).lower().strip()
    if _motivo_marca(texto, sem_acentos(c.codigo).lower()):
        return False
    dentro = any(d in texto for d in _DENTRO_ANTIGO) or bool(_RE_EM_TUDO.search(texto))
    m = _RE_EM_X.search(titulo)
    if m and not any(d in m.group(1) for d in _DENTRO_ANTIGO):
        return False
    if not dentro and any(cat in texto for cat in _CATEGORIAS_FORA):
        return False
    p = preco_loja or config.ALVO_PARCELADO
    m = _RE_ATE_ANTIGO.search(texto)
    if m and (lim := _num(m.group(1))) and lim < p * 0.5:
        return False
    m = _RE_ACIMA.search(texto)
    if m and (lim := _num(m.group(1))) and lim > p:
        return False
    return True


def _cupom_do_registro(reg: dict) -> Cupom:
    return Cupom(fonte=reg.get("fonte") or "", loja=loja_canonica(reg.get("loja") or ""), codigo=reg.get("codigo") or "",
                 titulo=reg.get("titulo") or "", url="", id=str(reg.get("id") or ""), regra=reg.get("regra") or "",
                 especifico=bool(reg.get("especifico")))


def _alertado_no_codigo_antigo(reg: dict, preco_por_loja: dict[str, float]) -> bool:
    """Registro de cupom de um estado antigo: o código da época alertou (ou anunciou na partida) este cupom?"""
    c = _cupom_do_registro(reg)
    lc = c.loja
    if lc not in _LOJAS_COM_TV and lc not in preco_por_loja and not c.especifico:
        return False
    return _compativel_regra_antiga(c, preco_por_loja.get(lc))


def restricao_do_codigo(cupons: list[Cupom], registros=()) -> set[str]:
    """'loja|CÓDIGO' que algum anúncio (desta rodada, ou dos `registros` vistos nos últimos 30 dias) declara ser de
    uma categoria que não é TV/eletrônicos/tecnologia nem o site todo ("20% OFF em Casa e Decor", "na categoria Casa").

    O mesmo código aparece em anúncios diferentes, e o Promobit alterna títulos genéricos ("20% OFF no Mercado
    Livre", "Economize 20% em seus pedidos") com o que diz a categoria: o cupom é o mesmo, então o anúncio genérico
    também não serve. Só conta a categoria declarada: a seleção vaga ("em Selecionados", que o Pelando põe em quase
    todo cupom do ML, REG-1) e as listas de palavras (que pegam slogans como "MERCADO EM ALTA") não barram o código."""
    out: set[str] = set()
    for c in list(cupons) + [_cupom_do_registro(r) for r in registros]:
        if c.especifico or not (c.codigo or "").strip():
            continue
        titulo = sem_acentos(c.titulo).lower().strip()
        tipo, _parte = _parte_da_loja(titulo, _texto_cat(sem_acentos(f"{c.titulo} {c.regra}").lower()))
        if tipo == "categoria":
            out.add(marca_cupom(c.loja, c.codigo))
    return out


_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_RE_DESC_PCT = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,2})?)\s*%")
_RE_DESC_REAIS = re.compile(
    r"r\$\s?" + _NUM + r"\s*(?:off|de desconto|de volta)\b"
    r"|(?:economiz\w*|ganhe|desconto de|oferece|concede)\s+(?:ate\s+)?r\$\s?" + _NUM)
_RE_DESC_TETO = re.compile(
    r"(?:limitad[oa]|limite)\s+(?:a\s+|de\s+)?r\$\s?" + _NUM + r"|maximo(?:\s+de)?\s+r\$\s?" + _NUM
    + r"|%\s*(?:off\s+)?ate\s+r\$\s?" + _NUM)


def _valor(s: str) -> float:
    s = s.replace(".", "").replace(",", ".") if "," in s or re.search(r"\.\d{3}\b", s) else s
    return float(s)


def _desconto(titulo: str, regra: str) -> tuple[Optional[tuple[str, float]], Optional[float]]:
    """(desconto principal, teto): (('%', 10.0), 500.0) para '10% OFF limitado a R$ 500'; ('R$', 250.0) para
    'R$ 250,00 OFF'. Procura no título e, se ele não diz o desconto, na regra. Nada legível -> (None, None)."""
    principal = None
    for txt in (sem_acentos(titulo or "").lower(), sem_acentos(regra or "").lower()):
        m = _RE_DESC_PCT.search(txt)
        if m:
            principal = ("%", _valor(m.group(1)))
            break
        m = _RE_DESC_REAIS.search(txt)
        if m:
            principal = ("R$", _valor(m.group(1) or m.group(2)))
            break
    m = _RE_DESC_TETO.search(sem_acentos(f"{titulo or ''} {regra or ''}").lower())
    teto = _valor(next(g for g in m.groups() if g)) if m else None
    return principal, teto


def _norm_titulo(s: str) -> str:
    return re.sub(r"[^a-z0-9%$]+", " ", sem_acentos(s or "").lower()).strip()


def _mesmo_cupom(c: Cupom, alerta: dict) -> bool:
    """O cupom repete o que já foi alertado? Compara o desconto (e o teto, quando os dois dizem); quando um dos dois
    não traz desconto legível, compara o título. Fontes escrevem o mesmo cupom de jeitos diferentes, o desconto não."""
    p1, t1 = _desconto(c.titulo, c.regra)
    p2, t2 = _desconto(alerta.get("titulo") or "", alerta.get("regra") or "")
    if p1 is None or p2 is None:
        return _norm_titulo(c.titulo) == _norm_titulo(alerta.get("titulo") or "")
    return p1 == p2 and (t1 is None or t2 is None or t1 == t2)


def _ja_alertado(estado: Estado, marca: str, c: Cupom) -> bool:
    """Só é repetição o cupom (loja + código) que já foi ALERTADO (ou anunciado na partida) com o mesmo
    desconto/título. Ter sido só visto, ou visto e recusado, não conta. Cupom da página do produto (especifico) só
    repete outro cupom da página do produto: "vale para esta TV" é novidade mesmo que o código já tenha sido
    alertado como cupom do site."""
    for alerta in estado.alertas_de_cupom(marca):
        if c.especifico and not alerta.get("especifico"):
            continue
        if _mesmo_cupom(c, alerta):
            return True
    return False


_CAB_CUPONS = "🎟️ <b>Nov"


def e_mensagem_de_cupons(m: str) -> bool:
    """A mensagem de cupons de gerar_alertas (se ela não for enviada, os cupons dela não contam como alertados)."""
    return m.startswith(_CAB_CUPONS)


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
    """Devolve (mensagens, {chave_oferta: preco_alertado}).

    Os cupons alertados ficam registrados no estado (em memória; o run.py salva no fim da rodada): quando o mesmo
    código volta com outro id, só deixa de ser novidade se já foi alertado com o mesmo desconto.
    """
    msgs: list[str] = []
    alertados: dict[str, float] = {}
    # o "menor já visto" é o dos dois modos (o painel mostra o menor entre cloud e pc)
    minimo_antes = estado.minimo_geral()
    preco_minimo_antes = float(minimo_antes["preco"]) if minimo_antes else None

    lojas = [o for o in ofertas if o.tipo == "loja"]
    posts = [o for o in ofertas if o.tipo == "post"]
    diretas = lojas_diretas(ofertas)

    # ---- preços de loja ----
    for o in lojas:
        p = o.melhor_preco
        # inativa, sem preço, ou agregador (Zoom) de loja que tem fonte direta nesta rodada: não gera alerta de preço
        if not p or not conta_como_preco(o, diretas):
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
    lojas_com_tv = set(preco_por_loja) | _LOJAS_COM_TV
    # estado antigo não registrava os alertas de cupom: reconstrói (uma vez) o que o código da época alertou
    estado.migra_alertas_de_cupom(lambda reg: _alertado_no_codigo_antigo(reg, preco_por_loja))
    # códigos que outro anúncio declara serem de outra categoria (ex.: DESCONTOEMCASA "em Casa e Decor")
    restritos = restricao_do_codigo(cupons, estado.cupons_vistos())
    novos: list[tuple[Cupom, str]] = []
    codigos_vistos: set[str] = set()
    # cupom da página do produto primeiro: se o mesmo código vier também como cupom do site, fica a linha do produto
    for c in sorted(cupons, key=lambda c: not c.especifico):
        if estado.cupom_anterior(c.chave) is not None:
            continue
        lc = loja_canonica(c.loja)
        if lc not in lojas_com_tv and not c.especifico:
            continue
        ok, _motivo = cupom_compativel(c, preco_por_loja.get(lc))
        if not ok:
            continue
        marca = marca_cupom(lc, c.codigo)
        if marca in restritos and not c.especifico:
            continue
        if marca in codigos_vistos:
            continue  # o mesmo cupom no Promobit e no Pelando nesta rodada
        # o mesmo código volta com outro id (a Magalu põe a data no id; Pelando e Promobit têm ids próprios):
        # só é repetição se já foi ALERTADO com o mesmo desconto
        if _ja_alertado(estado, marca, c):
            continue
        codigos_vistos.add(marca)
        if estado.bootstrap:
            # partida: a mensagem de início anuncia os cupons aplicáveis e avisa que só chegam novidades depois
            estado.registra_alerta_cupom(c, origem="partida")
            continue
        pl = preco_por_loja.get(lc)
        linha = f"• <b>{_esc(lc)}</b> <code>{_esc(c.codigo)}</code> — {_esc(c.titulo[:90])}"
        if c.validade:
            linha += f" (até {_esc(c.validade[:10])})"
        if pl:
            linha += f" · TV lá: {fmt_preco(pl)}"
        if c.especifico:
            linha = "⭐ " + linha + " — cupom do produto"
        linha += f"\n  {c.url}"
        novos.append((c, linha))
    if novos:
        cab = "🎟️ <b>Novos cupons aplicáveis à TV</b>" if len(novos) > 1 else "🎟️ <b>Novo cupom aplicável à TV</b>"
        corpo = "\n".join(linha for _c, linha in novos[:12])
        if len(novos) > 12:
            corpo += f"\n… e mais {len(novos) - 12} (veja o painel)"
        msgs.append(cab + "\n" + corpo)
        # registra o que foi alertado de fato (as linhas que foram na mensagem), para não repetir depois
        for c, _linha in novos[:12]:
            estado.registra_alerta_cupom(c)

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


def cupons_aplicaveis(ofertas: list[Oferta], cupons: list[Cupom], estado: Optional[Estado] = None) -> list[Cupom]:
    """Só cupons de lojas que vendem a TV e cuja regra cabe no preço dela (para o painel e o resumo).
    Com o estado, um código que outro anúncio já visto diz ser de outra categoria também fica fora."""
    preco_por_loja: dict[str, float] = {}
    for o in ofertas:
        if o.tipo == "loja" and o.melhor_preco and o.ativo:
            lc = loja_canonica(o.loja)
            preco_por_loja[lc] = min(preco_por_loja.get(lc, 1e9), o.melhor_preco)
    lojas_com_tv = set(preco_por_loja) | _LOJAS_COM_TV
    restritos = restricao_do_codigo(cupons, estado.cupons_vistos() if estado else [])
    out: list[Cupom] = []
    vistos: set[str] = set()
    for c in cupons:
        lc = loja_canonica(c.loja)
        if lc not in lojas_com_tv and not c.especifico:
            continue
        if not cupom_compativel(c, preco_por_loja.get(lc))[0]:
            continue
        marca = marca_cupom(lc, c.codigo)
        if marca in restritos and not c.especifico:
            continue
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
    m = estado.minimo_geral()
    if m:
        linhas.append(f"Menor já visto: {fmt_preco(float(m['preco']))} ({_esc(m['loja'])}, {m['quando'][:10]})")
    linhas.append(f"Alvo: Pix {fmt_preco(config.ALVO_PIX)} · parcelado {fmt_preco(config.ALVO_PARCELADO)}")
    if cupons:
        cods = ", ".join(sorted({f"{loja_canonica(c.loja)} {c.codigo}" for c in cupons}))[:400]
        linhas.append(f"Cupons ativos: {_esc(cods)}")
    return "\n".join(linhas)


def mensagem_bootstrap(ofertas: list[Oferta], cupons: list[Cupom], modo: str) -> str:
    lojas = sorted([o for o in ofertas if o.tipo == "loja" and o.melhor_preco and o.ativo], key=lambda o: o.melhor_preco or 0)
    posts = [o for o in ofertas if o.tipo == "post"]
    linhas = [f"✅ <b>Monitor da TCL 55C6K iniciado</b> (modo {modo})"]
    for o in lojas[:8]:
        linhas.append(f"• {_esc(o.loja)}: <b>{fmt_preco(o.melhor_preco)}</b>" + (f" · {_esc(o.parcelado)}" if o.parcelado else ""))
    linhas.append(f"{len(posts)} postagens antigas registradas, {len(cupons)} cupons ativos. A partir de agora só chegam novidades.")
    return "\n".join(linhas)


def mensagem_fonte_quebrada(nome: str, falhas: int, erro: str) -> str:
    return f"⚠️ Fonte <b>{_esc(nome)}</b> falhou {falhas} vezes seguidas.\n<code>{_esc(erro[:200])}</code>"
