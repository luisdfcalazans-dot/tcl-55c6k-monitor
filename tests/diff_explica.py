"""Explicações conferidas das diferenças main x branch do diferencial (tests/diff_extracao_nuvem.py).

Cada função olha a entrada e as duas saídas e só devolve um motivo quando a diferença é exatamente a correção
intencional (achado N-Fx, regressão R-x ou princípio a/b/c/d da rodada 4). Qualquer outra diferença volta None
e aparece como "SEM EXPLICAÇÃO" (bug a corrigir).
"""

from __future__ import annotations

import re

from monitor.util import _NAO_E_CUPOM, sem_acentos

# negativos/acessórios que a branch acrescentou ao filtro de título (N-F1 e princípio d)
_NOVOS_NEGATIVOS = ("placa", "peca", "t-con", "cabo flat", "barra de led", "par de pes", "avulso", "backlight",
                    "sucata", "reembalad", "mostruario", "recertificad", "remanufaturad", "avaria",
                    "fonte de alimenta", "controles remotos", "alto-falante")
_OUTROS_MODELOS = ("c655", "c6ks", "c7k", "c8k", "c9k", "p7k", "p8k", "q6k", "q7k", "x955", "s5k", "p755")
_NEG_DESCRICAO = ("suporte", "controle remoto", "base", "pedestal", "capa", "cabo hdmi", "pelicula")


# ---------------------------------------------------------------- normalização da saída

def normaliza_saida(it: dict, s):
    if not isinstance(s, dict) and not isinstance(s, list):
        return s
    if it["tipo"] == "titulo":
        return s["aceita"]  # o motivo é só depuração; vale o veredito
    if it["tipo"] == "post":
        return [(o["preco"], o["parcelado"], o["cupom"], o["alvo"]) for o in s["ofertas"]]
    return s


# ---------------------------------------------------------------- títulos

def _titulo(texto: str, a: dict, b: dict) -> str | None:
    t = sem_acentos(texto).lower()
    if a["aceita"] and not b["aceita"]:
        m = b["motivo"]
        if m.startswith("negativo: ") and m[10:] in _NOVOS_NEGATIVOS:
            return f"N-F1/princípio d (peça ou estado do produto): {m}"
        if m.startswith("acessório: "):
            return f"N-F1/princípio d (acessório pelo 1º substantivo ou começo do título): {m}"
        if m == "vários tamanhos":
            return "N-F1 (anúncio de vários tamanhos cita outro <tam>C6K além da 55C6K)"
    if b["aceita"] and not a["aceita"]:
        m = a["motivo"]
        if m == "negativo: suporte" and re.search(r"\bsuporte\s+(?:a|ao|aos|as|para|de|do|com)?\s*(?:hdr|dolby|4k|hdmi|"
                                                  r"wi-?fi|bluetooth|comandos?\s+de\s+voz|voz|multiplos)", t):
            return "N-F6 ('suporte a <recurso>' é recurso da TV, não o acessório)"
        if m == "negativo: controle remoto" and re.search(r"(?:com|c/)\s+controles?\s+remotos?|controles?\s+remotos?\s+"
                                                          r"(?:com|por|de|via)\s+(?:comando\s+de\s+)?voz", t):
            return "R1-REG5b ('com controle remoto'/'controle remoto por voz' é recurso da TV)"
    return None


# ---------------------------------------------------------------- texto (cupom, preços, parcelado)

def _precos(texto: str, pm: list, pb: list) -> str | None:
    if len(pm) != len(pb):
        return None
    for m, n in zip(pm, pb):
        if m == n:
            continue
        # N-F2: "R$ 3599" virava 359 (a 1ª alternativa do regex casava só 3 dígitos)
        if not (n >= 1000 and m == float(str(int(n))[:3])):
            return None
    return "N-F2 (valor sem ponto de milhar: 'R$ 3599' era lido como 359)"


def _parcelado(texto: str, pm: str | None, pb: str | None) -> str | None:
    t = sem_acentos(texto).lower()
    if pb is None and pm is not None and ("sem juros" not in pm or pm.startswith("1x")):
        return "R1-REG2 (só a 1ª parcela e só quando diz 'sem juros'; 1x não é parcelamento)"
    if pb is not None and pm is None and re.search(r"x\s*(?:sem|s/)\s*juros\s*de|\(\s*s/\s*juros", t):
        return "R1-REG2 (formatos '10x sem juros de R$' e '(s/ juros)')"
    if pb is not None and pm is not None and pb == pm + " sem juros" and "s/ juros" in t:
        return "R1-REG2 (formato '(s/ juros)')"
    if pb is not None and pm is not None:
        vm, vb = pm.split("R$ ")[-1].split(" ")[0], pb.split("R$ ")[-1].split(" ")[0]
        if vb.startswith(vm) and len(vb) > len(vm) and "." not in vb.split(",")[0]:
            return "N-F2 (parcela sem ponto de milhar)"
    return None


def _cupom(texto: str, cm: str | None, cb: str | None) -> str | None:
    if cm is not None and sem_acentos(cm).upper() in _NAO_E_CUPOM | {"DISPON"}:
        if cb is None or re.search(re.escape(cb), texto, re.I):
            return f"N-F10/princípio c ('{cm}' é palavra comum, não código)"
    if cm and re.search(re.escape(cm), texto) is None and re.search(re.escape(cm), texto, re.I) and (
            cb is None or cm.startswith(cb) or re.search(r"\b" + re.escape(cb) + r"\b", texto)):
        # "BRAE2ou" (código colado em "ou") virava o código BRAE2OU; a branch separa BRAE2
        return f"princípio c (código colado numa palavra: '{cm}' está escrito misturado no texto; branch {cb})"
    # o código aparece como palavra (ou colado numa palavra comum em minúsculas: "BRAE2ou")
    if cb is not None and (re.search(r"\b" + re.escape(cb) + r"\b", texto, re.I)
                           or re.search(r"\b" + re.escape(cb) + r"(?=[a-z]{1,4}\b)", texto)):
        marcador = re.search(r"(?:cupo(?:m|ns)|c[oó]digos?|c[oó]d\.?)[^\n]*" + re.escape(cb), texto, re.I)
        if marcador and cm is None:
            return f"princípio c (código '{cb}' depois de 'cupom'/'código', pulando palavras comuns)"
        if marcador and cm is not None and re.search(r"\d", cb) and not re.search(r"\d", cm):
            return f"princípio c (entre vários códigos, o com dígito: '{cb}' em vez de '{cm}')"
    return None


def _texto(it: dict, a: dict, b: dict) -> str | None:
    texto = it["texto"]
    motivos = []
    for campo, f in (("precos", _precos), ("parcelado", _parcelado), ("cupom", _cupom)):
        if a[campo] != b[campo]:
            m = f(texto, a[campo], b[campo])
            if not m:
                return None
            motivos.append(m)
    return "; ".join(motivos) or None


# ---------------------------------------------------------------- postagens

def _tipos(valores: list, v: float) -> set:
    return {t for x, t in valores if abs(x - v) < 0.005}


# Conferência INDEPENDENTE do classificador da branch (util.valores_postagem): o valor da main só conta como
# "não é o preço" se o texto tiver, colada nele, uma das frases do princípio b.
_NAO_PRECO_ANTES = re.compile(
    r"(?:(?:^|[^\w\s])\s*de|\bera|\bantes|\b(?:caiu|baixou|saiu)\s+de|acima\s+de|(?:compras?|pedidos?)\s+"
    r"(?:(?:a\s+partir|acima|minim[oa])\s+)?de|(?:valor|pedido|compra)\s+minim[oa](?:\s+do\s+pedido)?|min\.|"
    r"(?<![-=>])>|gastando|maxim[oa](?:\s+de)?|limitad[oa]\s+a|economi\w*|desconto\s+de|cashback|"
    r"\d{1,2}\s*x\s*(?:de)?)\s*:?\s*$")
_NAO_PRECO_DEPOIS = re.compile(r"^\s*\)?\s*(?:off\b|de\s+desconto|em\s+compras|a\s+menos|(?:-+>|=>|>>|➡|→|⏩)|"
                               r"por\s+r\$)")
_A_PARTIR_CUPOM = re.compile(r"(?:off|cupom|desconto|valid|compras|pedidos|produto)[^|/(]*a\s+partir\s+de\s*$")


def _nao_e_preco(texto: str, v: float) -> bool:
    """True se toda ocorrência do valor v no texto tem, colada, uma frase de não-preço do princípio b."""
    achou = False
    for m in re.finditer(r"R\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:[.,]\d{2})?)(?!\d)", texto):
        bruto = m.group(1)
        num = float(bruto.replace(".", "").replace(",", ".")) if "," in bruto or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", bruto) \
            else float(bruto)
        if abs(num - v) > 0.005:
            continue
        achou = True
        ini = texto.rfind("\n", 0, m.start()) + 1
        antes = sem_acentos(texto[ini:m.start()]).lower()
        if not re.search(r"[a-z0-9]", antes) and ini > 0:
            antes = sem_acentos(texto[texto.rfind("\n", 0, ini - 1) + 1: ini - 1]).lower() + " " + antes
        fim = texto.find("\n", m.end())
        depois = sem_acentos(texto[m.end(): len(texto) if fim < 0 else fim]).lower()
        if not (_NAO_PRECO_ANTES.search(antes) or _NAO_PRECO_DEPOIS.search(depois) or _A_PARTIR_CUPOM.search(antes)):
            return False
    return achou


# conferência independente de "a postagem cita outro produto": código de modelo com tamanho (43S5K, 65P7K),
# modelo TCL sem tamanho (P7K, S5K), TV de outro tamanho (43", 65 polegadas) ou TV de outra marca
_OUTRO_PRODUTO = re.compile(
    r"(?<![a-z0-9])(?:32|40|43|50|58|65|70|75|85|98|100|115)\s?[a-z]{1,5}\d{1,3}[a-z]{0,3}(?![a-z0-9])|"
    r"(?<![a-z0-9])(?:c|p|q|qm|s|x)\d(?:k|l|ks)(?![a-z0-9])|"
    r"(?<![\d.,$])(?:32|40|43|50|58|65|70|75|85|98|100|115)\s*(?:\"|pol)|"
    r"\btvs?\s+(?:tcl\s+)?(?:32|40|43|50|58|65|70|75|85|98|100|115)\b|"
    r"\btvs?\s+(?:\w+\s+){0,3}(?:samsung|lg|philips|aoc|philco|hisense)\b")


def _cita_outro_produto(texto: str) -> bool:
    t = re.sub(r"(?<![a-z0-9])55\s?c6k|(?<![a-z0-9])c6k", " ", sem_acentos(texto).lower())
    return bool(_OUTRO_PRODUTO.search(t))


def _preco(texto: str, om: dict, ob: dict, db: dict) -> str | None:
    pm, pb = om["preco"], ob["preco"]
    valores = db.get("valores") or []
    no_trecho = [x for x, _ in db.get("valores_trecho") or []]
    if pm is not None:
        tipos = _tipos(valores, pm)
        if tipos and not tipos & {"preco", "fraco"} and _nao_e_preco(texto, pm):
            return f"N-F3/princípio b (o valor da main, {pm:.2f}, é {'/'.join(sorted(tipos))}, não o preço)"
        if pm < 1500 and (pb is None or pb >= 1500):
            return f"princípio b (valor abaixo de R$ 1.500 não é o preço desta TV: {pm:.2f})"
        if tipos and not any(abs(x - pm) < 0.005 for x in no_trecho) and _cita_outro_produto(texto):
            return f"princípio a (segmentação: {pm:.2f} é de outro produto ou de uma linha de comparação)"
        if "fraco" in tipos and pb is not None and "preco" in _tipos(valores, pb):
            return "princípio b ('mais barato'/'a partir de' só valem quando não há outro candidato)"
        if not tipos:
            return None
    else:
        if re.search(r"R\$\s?\d{4,}(?![\d.])|R\$\s{2,}\d", texto):
            return "N-F2 (valor sem ponto de milhar ou 'R$  ' com espaço duplo)"
    return None


def _post(it: dict, a: dict, b: dict) -> str | None:
    from tests.diff_extracao_nuvem import _texto_da_postagem
    texto = _texto_da_postagem(it["html"])
    om, ob = a["ofertas"], b["ofertas"]
    dm, db = a["diag"], b["diag"]
    if om and not ob:
        rej = db.get("rejeicao") or ""
        if rej.startswith("estado/combo: "):
            return f"R2-REG1/N-F1 (estado do produto ou combo em qualquer linha: {rej[14:]})"
        if rej == "sem título da 55C6K" and db.get("motivos_c6k") and all(db["motivos_c6k"]):
            return f"N-F1/princípio d (a linha da 55C6K não passa no filtro de título: {db['motivos_c6k'][0]})"
        pm = om[0]["preco"]
        if rej == "outro produto sem preço da 55C6K" and _cita_outro_produto(texto):
            return f"princípio a (outro produto na postagem e o bloco da 55C6K sem preço; main dava {pm})"
        if rej == "abaixo do piso" and (pm is None or pm < 1500):
            return "princípio b (o único preço anunciado fica abaixo de R$ 1.500: peça/acessório, não a TV)"
        return None
    if ob and not om:
        m = dm.get("motivo_msg") or ""
        if (m == "outro tamanho" or (m.startswith("negativo: ") and m[10:] in _OUTROS_MODELOS)) and \
                _cita_outro_produto(texto):
            return f"princípio a (segmentação: a main descartava a postagem inteira por citar outro produto: {m})"
        if m.startswith("negativo: ") and m[10:] in _NEG_DESCRICAO:
            return f"N-F6 (o filtro de título roda só na linha-título; a main descartava por '{m[10:]}' no corpo)"
        return None
    if len(om) != 1 or len(ob) != 1:
        return None
    om, ob = om[0], ob[0]
    motivos = []
    if om["preco"] != ob["preco"]:
        m = _preco(texto, om, ob, db)
        if not m:
            return None
        motivos.append(m)
    if om["cupom"] != ob["cupom"]:
        m = _cupom(db.get("trecho") or texto, om["cupom"], ob["cupom"])
        if not m and om["cupom"] and ob["cupom"] is None and om["cupom"] not in (db.get("trecho") or ""):
            m = f"princípio a (o cupom '{om['cupom']}' está no bloco de outro produto)"
        if not m:
            return None
        motivos.append(m)
    if om["parcelado"] != ob["parcelado"]:
        m = _parcelado(texto, om["parcelado"], ob["parcelado"])
        if not m:
            return None
        motivos.append(m)
    if om["alvo"] != ob["alvo"] and om["preco"] == ob["preco"]:
        return None
    return "; ".join(motivos) or None


# ---------------------------------------------------------------- fontes

def _fonte(it: dict, a, b) -> str | None:
    if not isinstance(a, list) or not isinstance(b, list):
        return None
    ma, mb = {o["id"]: o for o in a}, {o["id"]: o for o in b}
    motivos = set()
    parser = it["parser"]
    for oid in ma.keys() | mb.keys():
        x, y = ma.get(oid), mb.get(oid)
        if x == y:
            continue
        if x is None or y is None:
            return None
        campos = {k for k in x if x[k] != y[k]}
        if parser == "vtex" and campos == {"preco_pix"} and x["preco_pix"] is None:
            motivos.add("N-F4 (Pix da VTEX lido das parcelas 1x Pix)")
        elif parser == "zoom" and campos <= {"agregador", "preco", "preco_pix", "parcelado"} and y["agregador"]:
            motivos.add("N-F5/N-F7 (Zoom marcado como agregador; cartão, Pix e parcelas do estado da página)")
        elif parser == "kabum" and campos == {"vendedor"} and x["vendedor"] is None:
            motivos.add("N-F8 (vendedor do marketplace da KaBuM!)")
        else:
            return None
    return "; ".join(sorted(motivos)) or None


def explica(it: dict, a, b) -> str | None:
    """Motivo de uma diferença intencional (a = main, b = branch), ou None se não há explicação."""
    if it["origem"].startswith("ouro:"):
        return f"linha da tabela de ouro: {it['origem'][5:]}"
    if isinstance(a, str) or isinstance(b, str):
        return None  # exceção num dos lados
    if it["tipo"] == "titulo":
        return _titulo(it["texto"], a, b)
    if it["tipo"] == "texto":
        return _texto(it, a, b)
    if it["tipo"] == "post":
        return _post(it, a, b)
    return _fonte(it, a, b)
