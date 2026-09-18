"""Diferencial do grupo estado-alertas: o código da main (8e21e6d) x o deste branch, no mesmo corpus.

Uso:  python tests/diff_estado_alertas.py [--detalhe] [--saida arquivo.txt] [--so C1,C2,C3]

Não é coletado pelo pytest (o nome não começa com test_). Só lê o git (log/cat-file/show) e os arquivos de correção
da auditoria; nunca escreve em docs/data (as reproduções rodam em pastas temporárias).

Corpus
  (a) real: todas as versões de docs/data/state_*.json e latest_*.json no histórico do git: os cupons (título/regra de
      cada anúncio), as ofertas de loja e os posts de cada rodada;
  (b) sintético: as entradas das correções das rodadas 1 a 4 (scratchpad/correcoes/estado-alertas*.json), as linhas
      da tabela de ouro (tests/test_tabela_ouro_estado_alertas.py) e as dos testes de cupom (test_estado_alertas,
      test_parsers).

Comparações
  C1  cupom_compativel(cupom, preço da TV na loja) em cada variante de cupom do corpus;
  C2  cenários das correções (sequências de rodadas com estado), rodados nos dois códigos pela mesma sequência do
      run.py de cada um;
  C3  cada rodada real (um latest_<modo>.json com 'atualizado' novo, no histórico deste branch e da main), reproduzida
      nos dois códigos a partir dos MESMOS arquivos reais de antes dela (state/latest dos dois modos) e com o relógio
      na hora da rodada: ofertas de loja do latest, cupons e posts do state com ultima_vez da rodada. Compara os alertas
      de preço, de post e de cupom, os cupons do painel, o mínimo gravado, as linhas do resumo diário e da partida.

Toda diferença recebe uma explicação (a correção intencional que a causa) ou vira "SEM EXPLICAÇÃO", que é bug. O
resumo no fim dá o tamanho do corpus e as contagens; com --detalhe lista cada diferença.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))
MAIN_SHA = "8e21e6d"
CORRECOES = Path(r"C:\Users\luisd\AppData\Local\Temp\claude\C--Users-luisd-OneDrive--rea-de-Trabalho-promos"
                 r"\8294b9c9-bb7f-4112-99fd-4c7e3e9f239b\scratchpad\correcoes")
ARQS_DADOS = ["docs/data/state_cloud.json", "docs/data/state_pc.json", "docs/data/latest_cloud.json",
              "docs/data/latest_pc.json"]
# preço da TV (Pix) por loja em 18/09, o que gerar_alertas usa como preco_loja; loja sem preço -> None (alvo parcelado)
PRECO_LOJA = {"Mercado Livre": 3491.03, "Magazine Luiza": 3561.55, "Amazon": 3279.0, "KaBuM!": 3159.0,
              "AliExpress": 3749.0, "Casas Bahia": 3599.09, "Fast Shop": 3296.81}
MODS = ("config", "util", "models", "estado", "regras")


# ============================================================ código da main num pacote temporário

def _git(*args: str, binario: bool = False):
    r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True)
    r.check_returncode()
    return r.stdout if binario else r.stdout.decode("utf-8")


def carrega_main(pasta: Path) -> dict:
    """Copia monitor/ da main para <pasta>/monitor_main e importa (os imports do pacote são relativos)."""
    for arq in _git("ls-tree", "-r", "--name-only", MAIN_SHA, "monitor").split():
        dst = pasta / arq.replace("monitor/", "monitor_main/", 1)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(_git("show", f"{MAIN_SHA}:{arq}", binario=True))
    sys.path.insert(0, str(pasta))
    return {n: importlib.import_module(f"monitor_main.{n}") for n in MODS}


def carrega_branch() -> dict:
    return {n: importlib.import_module(f"monitor.{n}") for n in MODS}


# ============================================================ corpus real: histórico de docs/data

def versoes_dos_dados() -> list[tuple[str, str, str, dict]]:
    """[(sha, data do commit, arquivo, json)] de todas as versões dos state/latest, do mais antigo ao mais novo, no
    histórico deste branch e no da main (que continua recebendo as coletas)."""
    revs = ["HEAD"] + (["main"] if subprocess.run(["git", "rev-parse", "--verify", "-q", "main"], cwd=RAIZ,
                                                   capture_output=True).returncode == 0 else [])
    linhas = [ln.split() for ln in _git("log", "--reverse", "--date-order", "--format=%H %cI", *revs, "--",
                                         *ARQS_DADOS).splitlines() if ln]
    pedidos = [(sha, quando, arq) for sha, quando in linhas for arq in ARQS_DADOS]
    p = subprocess.run(["git", "cat-file", "--batch"], cwd=RAIZ, capture_output=True,
                       input="".join(f"{s}:{a}\n" for s, _q, a in pedidos).encode())
    out, i, res = p.stdout, 0, []
    for sha, quando, arq in pedidos:
        nl = out.index(b"\n", i)
        cab = out[i:nl].decode()
        i = nl + 1
        if cab.endswith("missing"):
            continue
        tam = int(cab.split()[2])
        corpo = out[i:i + tam]
        i += tam + 1
        try:
            res.append((sha, quando, arq, json.loads(corpo.decode("utf-8"))))
        except (UnicodeDecodeError, ValueError):
            continue
    return res


def cupons_reais(versoes) -> list[dict]:
    """Uma entrada por variante de texto (fonte, loja, código, título, regra, especifico)."""
    vistos: dict[tuple, dict] = {}
    for _sha, _q, _arq, d in versoes:
        lista = d.get("cupons")
        for c in (lista.values() if isinstance(lista, dict) else lista or []):
            if not isinstance(c, dict):
                continue
            k = (c.get("fonte") or "", c.get("loja") or "", c.get("codigo") or "", c.get("titulo") or "",
                 c.get("regra") or "", bool(c.get("especifico")))
            vistos.setdefault(k, {"fonte": k[0], "loja": k[1], "codigo": k[2], "titulo": k[3], "regra": k[4],
                                  "especifico": k[5], "origem": "git"})
    return list(vistos.values())


# ============================================================ corpus sintético

def _s(loja, codigo, titulo, regra="", origem="", especifico=False, preco=None):
    return {"fonte": "sintetico", "loja": loja, "codigo": codigo, "titulo": titulo, "regra": regra,
            "especifico": especifico, "origem": origem, "preco": preco}


ML, MAGALU, AMAZON, KABUM, CB = "Mercado Livre", "Magazine Luiza", "Amazon", "KaBuM!", "Casas Bahia"
# entradas escritas nos arquivos de correção (rodadas 1 a 4) que não são cópia de um cupom real do git
SINTETICOS_CORRECOES = [
    # rodada 1 (estado-alertas.json, F3): "R$ 320 OFF em compras acima de R$ 3.000", "desconto máximo de R$500"
    _s(MAGALU, "X", "R$ 320 OFF em compras acima de R$ 3.000", origem="rodada1-F3"),
    _s(MAGALU, "X", "Cupom Magalu com desconto máximo de R$500 em suas compras", origem="rodada1-F3"),
    _s(MAGALU, "X", "Cupom Magalu 10% OFF", "Válido para compras até R$ 300", origem="rodada1-F3-teto-da-compra"),
    # rodada 2 (REG-1/REG-2) e 3 (DESCONTOEMCASA): textos reais (já no corpus do git); o 15% é sintético
    _s(ML, "MELIACHAPROMO", "A chance de economizar 15% em compras na Mercado Livre",
       "produtos Mercado Livre Economize até 10% ao usar o código promocional no carrinho de compras (compra mínima R$99).",
       origem="rodada2-REG1-15pct"),
    _s(MAGALU, "ESQUENTA320", "R$ 320,00 OFF com cupom: ESQUENTA320", "R$ 320,00 OFF com cupom: ESQUENTA320",
       origem="rodada2-REG2-produto", especifico=True),
    # rodada 4: regressões e não resolvidos da rodada 3
    _s(MAGALU, "TVMAGALU300", "Cupom Magalu R$ 300 OFF em TVs acima de R$ 3.000", "Não válido para a categoria Celulares.",
       origem="rodada4-exclusao"),
    _s(MAGALU, "TVMAGALU300", "Cupom de desconto Magazine Luiza oferece R$ 300 OFF em TVs", "",
       origem="rodada4-exclusao-promobit"),
    _s(ML, "MELI15TUDO", "Cupom Mercado Livre 15% OFF em todo o site (limite R$ 150)",
       "Válido em todo o site, exceto na categoria Supermercado. Compra mínima R$ 199.", origem="rodada4-exclusao"),
    _s(KABUM, "TVKABUM10", "Cupom KaBuM! 10% OFF em TVs em promoção", "produtos KaBuM! 10% OFF em TVs em promoção",
       origem="rodada4-varios-em"),
    _s(MAGALU, "SMARTTV250", "Cupom Magalu R$ 250 OFF em Smart TVs em oferta", "", origem="rodada4-varios-em"),
    _s(MAGALU, "PIX300", "Cupom Magalu de R$ 300 para pagamento em Pix", "Válido em compras acima de R$ 3.000",
       origem="rodada4-varios-em"),
    _s(AMAZON, "TCLTV250", "Cupom Amazon R$ 250 OFF em Smart TV TCL 50, 55 e 65 polegadas",
       "Válido para TVs vendidas pela Amazon.", origem="rodada4-tamanhos"),
    _s(CB, "CBFRETE200", "Cupom Casas Bahia: R$ 200 OFF + Frete Grátis em compras acima de R$ 1.999",
       "Aplique o cupom no carrinho. Limitado a 1 uso por CPF.", origem="rodada4-frete"),
    _s(MAGALU, "APPMAGALU350", "Cupom Magalu com R$ 350 OFF para usar no app",
       "produtos Magazine Luiza Use o código no app em compras acima de R$ 3.000.", origem="rodada4-app"),
    _s(ML, "DESCONTOJA", "Cupom Mercado Livre 15% OFF acima de R$ 50 (limi R$ 200 OFF)",
       "Cupom Mercado Livre 15% OFF acima de R$ 50 (limi R$ 200 OFF)", origem="rodada4-descontoja-pc"),
]


def sinteticos_dos_testes() -> list[dict]:
    """Linhas de cupom da tabela de ouro e dos testes de cupom (test_estado_alertas, test_parsers)."""
    out = []
    import test_tabela_ouro_estado_alertas as ouro

    for linha in ouro.COMPAT:
        _id, loja, codigo, titulo, regra, preco, _esp = linha[:7]
        out.append(_s(loja, codigo, titulo, regra, origem=f"ouro:{_id}", preco=preco))
    for linha in getattr(ouro, "COMPAT_OU_PRECO_CERTO", []):
        _id, loja, codigo, titulo, regra, preco = linha[:6]
        out.append(_s(loja, codigo, titulo, regra, origem=f"ouro:{_id}", preco=preco))
    import test_estado_alertas as tea

    for nome in ("SERVEM", "NAO_SERVEM"):
        for c, preco in getattr(tea, nome):
            out.append(_s(c.loja, c.codigo, c.titulo, c.regra, origem=f"test_estado_alertas:{nome}", preco=preco))
    for loja, titulo, regra, _serve in getattr(tea, "PRINCIPIOS", []):
        out.append(_s(loja, "SONDA", titulo, regra, origem="test_estado_alertas:PRINCIPIOS", preco=tea._PRECO[loja]))
    # test_parsers.test_cupom_compativel (as listas estão dentro do teste; copiadas aqui)
    for t in ["Cupom de desconto Magalu oferece 20% OFF em Cervejas",
              "Cupom de desconto Magalu oferece 5% OFF em entrega FULL",
              "Cupom de desconto Magalu oferece 10% OFF em Cuidados Pessoais",
              "Cupom de desconto Magalu oferece 10% OFF em itens de treino",
              "Cupom de desconto Magalu oferece 10% OFF em Bikes", "Cupom Magalu 15% OFF em compras de até R$ 1000",
              "Cupom de descontoMagalu oferece 5% OFF em suas compras DYSON", "PS5 com R$100 de Desconto",
              "DESCONTO IMPERDÍVEL: R$ 1200 OFF no OPPO Find X9 Pro na FastShop",
              "30% Off limitado a R$30 para contas novas", "Cupom Magazine - R$ 50 em R$120 no Zap",
              "Cupom Mercado Livre - R$100 OFF em Compras Acima de R$899 em Tudo Pra Casa",
              "Produtos Beauty Coreanos com 20% OFF na Amazon",
              "Cupom de desconto Magalu oferece R$100 OFF em suas compras",
              "Cupom de desconto Magalu oferece 10% OFF em suas compras", "Cupom Magalu R$ 100 acima de R$ 1000",
              "Cupom de desconto Magalu oferece 10% OFF em TVs", "Cupom Amazon 10% OFF em eletrônicos"]:
        out.append(_s(MAGALU, "Z", t, origem="test_parsers", preco=3091.0))
    out.append(_s(MAGALU, "A", "Cupom Magalu 10% OFF", "Válido para compras até R$300.", origem="test_parsers",
                  preco=3700.0))
    out.append(_s(MAGALU, "B", "Cupom Magalu R$ 100 acima de R$ 1000", origem="test_parsers", preco=3700.0))
    out.append(_s(AMAZON, "C", "10% OFF em moda", origem="test_parsers", preco=3200.0))
    out.append(_s(KABUM, "JBL25", "25% de Desconto em produtos", origem="test_parsers", preco=3159.0))
    out.append(_s(AMAZON, "NIVEA20", "Aplique cupom Amazon e ganhe 20% OFF", origem="test_parsers", preco=3278.0))
    return out


# ============================================================ C1: cupom_compativel

def _cupom(mods, d: dict, cid: str = "x"):
    lc = mods["util"].loja_canonica(d["loja"])
    return mods["models"].Cupom(fonte=d["fonte"], loja=lc, codigo=d["codigo"], titulo=d["titulo"], url="", id=cid,
                                regra=d["regra"], especifico=d["especifico"])


def explica_compat(a: tuple, b: tuple, d: dict) -> tuple[str, str]:
    """(classe, por quê) de uma diferença de cupom_compativel: a = main, b = branch. Classe '' = sem explicação."""
    ma, mb = a[1], b[1]
    if b[0]:  # o branch aceita o que a main recusava
        if ma.startswith(("só até R$", "só acima de R$")) and re.search(
                r"\b(?:exceto|excluindo|n[ãa]o\s+(?:é\s+)?v[áa]lid|n[ãa]o\s+vale|n[ãa]o\s+se\s+aplica)[^.;]*R\$",
                f"{d['titulo']} {d['regra']}", re.I):
            return "R4a-valor-na-exclusao", "o valor estava numa exclusão ('exceto TVs acima de R$ 5.000'): não é o " \
                                            "mínimo/teto da compra (R4 a)"
        if ma.startswith("só até R$"):
            return "F3-teto-do-desconto", "'até R$'/'máximo R$' é teto do DESCONTO, não da compra (F3)"
        if ma == "categoria: mercado":
            return "F3-nome-da-loja", "o 'mercado' era o nome da loja Mercado Livre (F3) ou Mercado Pago"
        if ma.startswith("categoria: ") and re.search(r"\b(?:compras|pedidos)\b.*\b(?:acima|partir)", ma):
            return "F3-valor-minimo", "'OFF em compras acima de R$ X' é valor mínimo, não categoria (F3)"
        if ma.startswith("categoria: ") and re.search(r"\b(?:frete|app|aplicativo|entrega)\b", ma):
            return "R4d-frete-app", "frete, entrega e app não são categorias (R4 d)"
        if ma.startswith(("categoria: ", "marca/produto: ")):
            return "R4ab-escopo", "a palavra que a main lia como categoria/marca é exclusão, loja, pagamento ou alvo neutro; " \
                                  "o alvo declarado é TV/site todo/compras (R4 a/b)"
        return "", ""
    # o branch recusa o que a main aceitava
    if mb.startswith("exclui: "):
        return "R4a-exclui-a-tv", "a exclusão tira a própria TV ('exceto TVs/eletrônicos/TCL')"
    if mb.startswith("outro produto: "):
        return "R3-outro-produto", "cupom de outra TV (outro tamanho) ou de um kit"
    if mb.startswith("só para novos clientes"):
        return "R3-cliente-novo", "cupom só para cliente novo / 1ª compra"
    if mb == "só frete":
        return "R4d-so-frete", "cupom só de frete: não é desconto no preço da TV"
    if mb.startswith("categoria: "):
        return "R3-categoria-declarada", "o alvo declarado do desconto é uma categoria que não é TV"
    if mb.startswith("restrito: anúncio cortado"):
        return "R3-anuncio-cortado", "título cortado em 'em': a categoria sumiu"
    if mb.startswith("restrito: "):
        return "R3-selecao", "vale só para uma seleção de itens sem dizer que é TV/tecnologia"
    if mb.startswith("só até R$") and re.search(r"compra\s+m[áa]xima", f"{d['titulo']} {d['regra']}", re.I):
        return "F3-teto-da-compra", "'compra máxima de R$ X' é teto da COMPRA (a main só lia 'máximo', no masculino)"
    if mb.startswith("só acima de R$") and re.search(r"\b(?:off|desconto)\s+em\s+r\$", f"{d['titulo']} {d['regra']}",
                                                     re.I):
        return "R4-minimo-em-R$", "'R$ 350 OFF em R$ 3500': o valor depois de 'OFF em' é a compra mínima"
    if mb.startswith("marca/produto: ") and _conserta_so_mojibake(d):
        return "mojibake", "o texto antigo tinha mojibake (UTF-8 lido como cp1252); consertado ele diz outra marca/produto"
    return "", ""


def _conserta_so_mojibake(d: dict) -> bool:
    return bool(re.search("[ÂÃ][\u0080-\u00bf\u0152-\u2122]", f"{d['titulo']} {d['regra']}"))


def compara_compat(mm, mb, corpus: list[dict]) -> list[dict]:
    difs = []
    for d in corpus:
        lc = mb["util"].loja_canonica(d["loja"])
        preco = d.get("preco") if d.get("preco") is not None else PRECO_LOJA.get(lc)
        a = mm["regras"].cupom_compativel(_cupom(mm, d), preco)
        b = mb["regras"].cupom_compativel(_cupom(mb, d), preco)
        if a[0] != b[0]:
            classe, porque = explica_compat(a, b, d)
            difs.append({"cupom": d, "preco": preco, "main": a, "branch": b, "classe": classe, "porque": porque})
    return difs


# ============================================================ uma rodada: a sequência do run.py de cada código

def _oferta(mods, d: dict):
    campos = set(mods["models"].Oferta.__dataclass_fields__)
    kw = {k: v for k, v in d.items() if k in campos}
    kw["extra"] = dict(kw.get("extra") or {})
    # desfaz o que o sanear da rodada original gravou (o sanear roda de novo aqui)
    if kw["extra"].pop("descartado", None) is not None:
        kw["ativo"] = True
    pd = kw["extra"].pop("parcelado_descartado", None)
    if pd:
        kw["parcelado"] = pd
    return mods["models"].Oferta(**kw)


def _cupom_de(mods, d: dict):
    campos = set(mods["models"].Cupom.__dataclass_fields__)
    kw = {k: v for k, v in d.items() if k in campos}
    kw["loja"] = mods["util"].loja_canonica(kw.get("loja") or "")
    kw.setdefault("url", "")
    return mods["models"].Cupom(**kw)


_RUN = None


def _limita_do_branch():
    global _RUN
    if _RUN is None:
        _RUN = importlib.import_module("run")
    return _RUN.limita_alertas


def rodada(mods: dict, e_branch: bool, pasta: Path, modo: str, ofertas: list[dict], cupons: list[dict],
           quando: datetime) -> dict:
    """sanear -> gerar_alertas -> cupons_aplicaveis -> partida/resumo -> limite -> persistência, como no run.py de cada
    código (sem fontes, sem Telegram). O resumo é calculado em toda rodada para comparar (o run.py manda 1x por dia)."""
    cfg, util, reg, est_mod = mods["config"], mods["util"], mods["regras"], mods["estado"]
    cfg.DIR_DADOS = pasta
    util.agora = lambda q=quando: q
    unicas: dict = {}
    for d in ofertas:
        o = _oferta(mods, d)
        unicas.setdefault(o.chave, o)
    ofs = list(unicas.values())
    unicos: dict = {}
    for d in cupons:
        c = _cupom_de(mods, d)
        unicos.setdefault(c.chave, c)
    cs = list(unicos.values())
    ofs, _av = reg.sanear(ofs)
    estado = est_mod.Estado(modo)
    if e_branch:
        diretas = estado.lojas_diretas_conhecidas(ofs)
        minimo_antes = estado.minimo_geral(diretas)
    else:
        diretas, minimo_antes = None, estado.minimo()
    boot = estado.bootstrap
    msgs, alertados = reg.gerar_alertas(estado, ofs, cs)
    aplic = reg.cupons_aplicaveis(ofs, cs, estado) if e_branch else reg.cupons_aplicaveis(ofs, cs)
    partida = None
    if boot and (ofs or cs):
        partida = reg.mensagem_bootstrap(ofs, aplic, modo, diretas) if e_branch else \
            reg.mensagem_bootstrap(ofs, aplic, modo)
        msgs = [partida]
    resumo = None if boot else reg.resumo_diario(estado, ofs, aplic)
    if e_branch:
        _limita_do_branch()(list(msgs), estado, cfg.MAX_ALERTAS_POR_EXECUCAO)
    for o in ofs:
        estado.registra_oferta(o, alertados.get(o.chave))
        if e_branch:
            estado.atualiza_minimo(o, diretas)
        else:
            estado.atualiza_minimo(o)
    for c in cs:
        estado.registra_cupom(c)
    estado.marca_inativas({o.chave for o in ofs}, {o.fonte for o in ofs} | {c.fonte for c in cs})
    estado.anexa_historico([o for o in ofs if o.tipo == "loja" and (not e_branch or (o.ativo and o.melhor_preco))])
    estado.escreve_latest(ofs, aplic)
    estado.salva()
    return {"msgs": msgs, "alertados": alertados, "aplic": aplic, "resumo": resumo, "partida": partida, "ofertas": ofs,
            "cupons": cs, "minimo_antes": minimo_antes, "minimo": estado.minimo(), "estado": estado,
            "diretas": diretas, "bootstrap": boot}


# ---- o que se compara de uma rodada ----
_RE_CODE = re.compile(r"<code>([^<]+)</code>")


def _quem(o) -> str:
    return o.loja + (f" (vendido por {o.vendedor})" if o.vendedor and o.vendedor != o.loja else "")


def saidas(r: dict) -> dict:
    """{tipo: {chave: valor}} normalizado para comparar main x branch."""
    import html as _html

    precos, posts, cupons = {}, set(), []
    por_url_quem = {(o.url, _quem(o)): o.chave for o in r["ofertas"]}
    for m in r["msgs"]:
        linhas = m.split("\n")
        if m.startswith("🎟️"):
            cupons += _RE_CODE.findall(m)
        elif m.startswith("📣"):
            posts.add(m)
        elif m.startswith("✅"):
            continue
        else:
            mm = re.match(r"(.*) — <b>(.*)</b>$", linhas[0])
            chave = por_url_quem.get((linhas[-1], _html.unescape(mm.group(2)))) if mm else None
            precos[chave or linhas[0]] = mm.group(1) if mm else linhas[0]
    resumo = r["resumo"] or ""
    return {
        "preço": precos,
        "post": {p: True for p in posts},
        "cupom": {c: True for c in cupons},
        "painel": {c.codigo.upper(): True for c in r["aplic"]},
        "mínimo": {"mínimo": (round(float(r["minimo"]["preco"]), 2), r["minimo"]["loja"]) if r["minimo"] else None},
        "resumo": {ln: True for ln in resumo.split("\n") if ln.startswith("• ") or ln.startswith("Menor já visto")},
        "partida": {ln: True for ln in (r["partida"] or "").split("\n") if ln.startswith("• ")},
    }


def difere(a: dict, b: dict) -> list[tuple[str, str, object, object]]:
    """[(tipo, chave, main, branch)]"""
    out = []
    sa, sb = saidas(a), saidas(b)
    for tipo in sa:
        for k in sorted(set(sa[tipo]) | set(sb[tipo]), key=str):
            va, vb = sa[tipo].get(k), sb[tipo].get(k)
            if va != vb:
                out.append((tipo, k, va, vb))
    return out


# ---- explicação de cada diferença de rodada ----

def _preco_main(r_main, lc, mm):
    ps = [o.melhor_preco for o in r_main["ofertas"]
          if o.tipo == "loja" and o.melhor_preco and o.ativo and mm["util"].loja_canonica(o.loja) == lc]
    return min(ps) if ps else None


def _preco_branch(r_br, lc, mb):
    reg = mb["regras"]
    est = r_br["estado"]
    return reg._precos_da_tv(r_br["ofertas"], r_br["diretas"],
                             reg._substitutas(est, r_br["ofertas"], r_br["diretas"]))[0].get(lc)


def explica_rodada(dif, r_main, r_br, mm, mb, cupons_vistos_antes) -> tuple[str, str]:
    tipo, chave, va, vb = dif
    regb = mb["regras"]
    if tipo in ("cupom", "painel"):
        cod = str(chave).upper()
        cs = [c for c in r_br["cupons"] if (c.codigo or "").upper() == cod]
        for c in cs:
            lc = mb["util"].loja_canonica(c.loja)
            pa, pb = _preco_main(r_main, lc, mm), _preco_branch(r_br, lc, mb)
            cm = next(x for x in r_main["cupons"] if x.chave == c.chave)
            a = mm["regras"].cupom_compativel(cm, pa)
            b = regb.cupom_compativel(c, pb)
            if a[0] != b[0]:
                if pa != pb and regb.cupom_compativel(c, pa)[0] == a[0]:
                    return "ZOOM-preco-da-tv", f"{c.loja}: preço da TV {pa} (agregador) x {pb} (direto): a regra de valor muda"
                d = {"titulo": c.titulo, "regra": c.regra}
                classe, porque = explica_compat(a, b, d)
                if classe:
                    return classe, f"{c.chave}: main {a} branch {b} — {porque}"
        if va and not vb:  # a main alerta/mostra, o branch não, e o cupom é compatível nos dois
            restr = regb.restricao_do_codigo(r_br["cupons"], cupons_vistos_antes)
            lc = mb["util"].loja_canonica(cs[0].loja) if cs else ""
            if f"{lc}|{cod}" in restr:
                return "R3-R4e-codigo-de-categoria", ("outro anúncio do mesmo código (nesta rodada ou visto em 30 dias, "
                                                      "em qualquer modo) declara uma categoria que não é TV")
            if tipo == "cupom" and not r_br["bootstrap"]:
                marca = f"{lc}|{cod}"
                if any(regb._ja_alertado(r_br["estado"], marca, c) for c in cs):
                    return "F9-ja-alertado", "o mesmo loja+código já foi alertado (ou anunciado na partida) com o mesmo desconto"
        if tipo == "cupom" and (len(saidas(r_main)["cupom"]) >= 12 or len(saidas(r_br)["cupom"]) >= 12):
            return "limite-12-linhas", "mais de 12 cupons novos: as 12 linhas da mensagem saem noutra ordem (produto primeiro)"
        return "", ""
    if tipo == "preço":
        o = next((x for x in r_br["ofertas"] if x.chave == chave), None)
        if o is not None and mb["estado"].e_agregador(o) and not mb["estado"].conta_como_preco(o, r_br["diretas"]):
            return "ZOOM-agregador-coberto", f"{o.loja} do agregador: a loja tem fonte direta ({'nesta rodada' if mb['util'].loja_canonica(o.loja) in mb['estado'].lojas_diretas(r_br['ofertas']) else 'no state ou no outro modo'})"
        ma, mb_ = r_main["minimo_antes"], r_br["minimo_antes"]
        pa = float(ma["preco"]) if ma else None
        pb = float(mb_["preco"]) if mb_ else None
        # só as etiquetas que dependem do mínimo de referência (🏆 e 🆕, que usa mínimo × 1,03) mudam
        if pa != pb and _sem_etiquetas_de_minimo(va) == _sem_etiquetas_de_minimo(vb):
            return "F5-ZOOM-minimo-de-referencia", (f"'menor já visto' de referência: main {pa} (só o do modo) x branch {pb} "
                                                    "(o menor dos dois modos, sem mínimo de agregador coberto)")
        return "", ""
    if tipo == "mínimo":
        mn, mbr = va, vb
        ofs = r_main["ofertas"]
        if mn:
            fonte = [o for o in ofs if o.tipo == "loja" and o.melhor_preco and abs(o.melhor_preco - mn[0]) < 0.01]
            if fonte and all(not o.ativo for o in fonte):
                return "F2-minimo-de-oferta-inativa", f"a main gravou {mn} de uma oferta inativa/descartada"
            if fonte and all(mb["estado"].e_agregador(o) for o in fonte):
                return "ZOOM-minimo-de-agregador", f"a main gravou {mn} do agregador de uma loja com fonte direta"
        pre = r_main["minimo_antes"]
        if pre and mb["estado"].e_agregador(pre):
            return "ZOOM-minimo-antigo-do-agregador", f"o mínimo gravado antes ({pre['preco']} {pre['loja']}) veio do Zoom"
        return "", ""
    if tipo in ("resumo", "partida"):
        linha = str(chave)
        if linha.startswith("Menor já visto"):
            return "F5-ZOOM-menor-ja-visto", "o resumo usa o menor dos dois modos, sem mínimo de agregador coberto (F5/ZOOM)"
        if " · visto " in linha:
            return "ZOOM-oferta-direta-do-outro-modo", "no lugar da linha do agregador, a oferta direta do outro modo"
        agreg = [o for o in r_main["ofertas"] if mb["estado"].e_agregador(o)
                 and linha.startswith(f"• {o.loja}") and mb["util"].fmt_preco(o.melhor_preco) in linha]
        if va and agreg:
            return "ZOOM-agregador-coberto", "linha do agregador de loja com fonte direta"
        inat = [o for o in r_main["ofertas"] if not o.ativo and o.melhor_preco and mb["util"].fmt_preco(o.melhor_preco) in linha]
        if tipo == "partida" and va and inat:
            return "F2-partida-so-ativas", "a mensagem de partida só lista ofertas ativas"
        # o resumo mostra 10 lojas e a partida 8: sem as linhas do agregador coberto, outras ofertas diretas entram
        limite, texto_main = (10, r_main["resumo"]) if tipo == "resumo" else (8, r_main["partida"])
        n_main = len([ln for ln in (texto_main or "").split("\n") if ln.startswith("• ")])
        tem_agregador = any(mb["estado"].e_agregador(o) and not mb["estado"].conta_como_preco(o, r_br["diretas"])
                            for o in r_main["ofertas"])
        if vb and not va and n_main >= limite and tem_agregador and " · visto " not in linha:
            return f"ZOOM-top{limite}", f"sem as linhas do agregador, outras ofertas diretas entram nas {limite} da mensagem"
        return "", ""
    return "", ""


def _sem_etiquetas_de_minimo(v) -> str:
    return re.sub(r"🏆 MENOR PREÇO já visto|🆕 Nova oferta", "", str(v or "")).strip()


# ============================================================ C3: rodadas reais (cada uma a partir do state real)

def rodadas_reais(versoes) -> list[dict]:
    """Cada rodada real (um latest_<modo>.json com 'atualizado' novo), com o que ela coletou e os arquivos de antes.

    Ofertas de loja: latest_<modo>.ofertas_loja. Cupons e posts: registros do state_<modo> do mesmo commit com
    ultima_vez até 15 min antes da rodada. Pré-estado: a versão anterior dos 4 arquivos (a mesma para os dois códigos)."""
    por_sha: dict[str, dict] = defaultdict(dict)
    ordem: list[str] = []
    for sha, _q, arq, d in versoes:
        if sha not in por_sha:
            ordem.append(sha)
        por_sha[sha][arq.split("/")[-1].replace(".json", "")] = d
    antes: dict[str, dict] = {}
    visto: dict[str, str] = {}
    out = []
    for sha in ordem:
        arqs = por_sha[sha]
        for modo in ("cloud", "pc"):
            lt, st = arqs.get(f"latest_{modo}"), arqs.get(f"state_{modo}")
            t = (lt or {}).get("atualizado")
            if not t or not st or t == visto.get(modo) or not isinstance(lt.get("ofertas_loja"), list):
                continue
            visto[modo] = t
            fim = datetime.fromisoformat(t)

            def recente(reg):
                try:
                    dt = datetime.fromisoformat(reg.get("ultima_vez") or "")
                except ValueError:
                    return False
                return 0 <= (fim - dt).total_seconds() <= 900

            cupons = [r for r in (st.get("cupons") or {}).values() if isinstance(r, dict) and recente(r)]
            posts = [r for r in (st.get("ofertas") or {}).values()
                     if isinstance(r, dict) and r.get("tipo") == "post" and recente(r)]
            out.append({"sha": sha, "modo": modo, "quando": fim, "ofertas": list(lt["ofertas_loja"]) + posts,
                        "cupons": cupons, "antes": dict(antes)})
        antes = dict(arqs)
    return out


def _grava_pre(pasta: Path, arquivos: dict):
    for f in pasta.glob("*"):
        f.unlink()
    for nome, d in arquivos.items():
        if d is not None and nome.startswith(("state_", "latest_")):
            (pasta / f"{nome}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def compara_rodadas_reais(mm, mb, versoes, tmp: Path) -> tuple[list[dict], int]:
    difs = []
    runs = rodadas_reais(versoes)
    pa, pb = tmp / "c3_main", tmp / "c3_branch"
    pa.mkdir()
    pb.mkdir()
    for run in runs:
        _grava_pre(pa, run["antes"])
        _grava_pre(pb, run["antes"])
        ra = rodada(mm, False, pa, run["modo"], run["ofertas"], run["cupons"], run["quando"])
        # o que o branch sabia antes da rodada (restricao_do_codigo): state deste modo e do outro, 30 dias
        mb["config"].DIR_DADOS = pb
        _grava_pre(pb, run["antes"])
        mb["util"].agora = lambda q=run["quando"]: q
        vistos_antes = mb["estado"].Estado(run["modo"]).cupons_vistos()
        rb = rodada(mb, True, pb, run["modo"], run["ofertas"], run["cupons"], run["quando"])
        for dif in difere(ra, rb):
            classe, porque = explica_rodada(dif, ra, rb, mm, mb, vistos_antes)
            difs.append({"rodada": f"{run['modo']} {run['quando'].isoformat()[:16]} ({run['sha'][:7]})", "dif": dif,
                         "classe": classe, "porque": porque})
    return difs, len(runs)


# ============================================================ C2: cenários das correções (rodadas encadeadas)

def _reg_cupom(fonte, cid, loja, codigo, titulo, regra="", especifico=False, primeira="2026-09-13T15:23:00-03:00",
               ultima=None):
    return {"fonte": fonte, "id": cid, "loja": loja, "codigo": codigo, "titulo": titulo, "url": "u", "regra": regra,
            "validade": None, "publicado": None, "especifico": especifico, "chave": f"{fonte}:{cid}",
            "primeira_vez": primeira, "ultima_vez": ultima or primeira}


def _state(minimo=None, ofertas=None, cupons=()):
    return {"ofertas": ofertas or {}, "cupons": {c["chave"]: c for c in cupons}, "minimo": minimo, "saude": {},
            "ultimo_resumo": None, "criado_em": "2026-09-13T15:22:00-03:00"}


def _min(preco, loja="Amazon", url="u"):
    return {"preco": preco, "loja": loja, "quando": "2026-09-14T21:08:06-03:00", "url": url, "titulo": "TCL 55C6K"}


def _of(fonte, loja, oid, preco=None, pix=None, ativo=True, parcelado=None, vendedor=None, url="u", extra=None):
    return {"fonte": fonte, "tipo": "loja", "loja": loja, "titulo": "TCL 55C6K", "url": url, "id": oid, "preco": preco,
            "preco_pix": pix, "parcelado": parcelado, "ativo": ativo, "vendedor": vendedor, "extra": extra or {}}


def _reg_of(fonte, loja, oid, ultimo):
    return {f"{fonte}:{oid}": {"fonte": fonte, "id": oid, "tipo": "loja", "loja": loja, "ativo": True,
                               "ultimo_preco": ultimo, "menor_preco": ultimo, "preco_alertado": None,
                               "primeira_vez": "2026-09-13T15:22:00-03:00"}}


def _c(fonte, cid, loja, codigo, titulo, regra="", especifico=False):
    return {"fonte": fonte, "id": cid, "loja": loja, "codigo": codigo, "titulo": titulo, "url": "u", "regra": regra,
            "especifico": especifico}


AGORA_C2 = datetime.fromisoformat("2026-09-18T17:50:00-03:00")
PEL_MELIACHA = _reg_cupom("pelando", "01627720", ML, "MELIACHAPROMO",
                          "Cupom Mercado Livre - 10% OFF Acima de R$99 limitado à R$300 em Selecionados",
                          "Em Itens Selecionados")
PB_69374 = _c("promobit", "69374", ML, "MELIACHAPROMO", "A chance de economizar 10% em compras na Mercado Livre",
              "produtos Mercado Livre Economize até 10% ao usar o código promocional no carrinho de compras (compra "
              "mínima R$99).")
PB_69469 = _c("promobit", "69469", ML, "MELIACHAPROMO", "Cupom de desconto Mercado Livre oferece 10,00% OFF em suas compras",
              "produtos Mercado Livre Desconto de até 10% em compra a partir de R$99, excluído o valor do frete, com "
              "desconto máximo de R$300 válido para itens elegíveis.")
LU250 = [_reg_cupom("magalu", f"LU250-2026-09-{d}", MAGALU, "LU250", "R$ 250,00 OFF com cupom: LU250",
                    "R$ 250,00 OFF com cupom: LU250", especifico=True) for d in ("14", "18", "16")]
PEL_ESQ = _reg_cupom("pelando", "a44fdd07", MAGALU, "ESQUENTA320", "Magalu: Ganhe R$320 OFF em compras acima de R$3.000",
                     "R$320 partir de R$3.000 (válido para itens elegíveis )")
PB_69223 = _reg_cupom("promobit", "69223", MAGALU, "ESQUENTA320",
                      "Os melhores itens do site com R$320 OFF aplicando cupom Magazine Luiza",
                      "produtos Magazine Luiza Economize até R$320 ao usar o código promocional no carrinho de compras "
                      "(a partir de R$3.000).")
ESQ_PRODUTO = _c("magalu", "ESQUENTA320-2026-09-25", MAGALU, "ESQUENTA320", "R$ 320,00 OFF com cupom: ESQUENTA320",
                 "R$ 320,00 OFF com cupom: ESQUENTA320", especifico=True)
PEL_CASA = _reg_cupom("pelando", "30a59912", ML, "DESCONTOEMCASA",
                      "Cupom Mercado Livre oferece 20% OFF, máximo R$ 60, em R$ 79 em Casa",
                      "pedido mínimo R$ 79 na categoria Casa", ultima="2026-09-18T16:37:00-03:00")
PB_69522 = _reg_cupom("promobit", "69522", ML, "DESCONTOJA",
                      "NOVO ESPAÇO: 15% OFF em Casa no Mercado Livre (acima de R$50) com cupom", "produtos Mercado Livre",
                      primeira="2026-09-15T11:29:00-03:00", ultima="2026-09-17T17:01:00-03:00")
ML_OF = _of("mercadolivre", ML, "MLB5417889802", preco=3599.0, pix=3491.03, vendedor=ML)
MAGALU_OF = _of("magalu", MAGALU, "240162800-magazineluiza", preco=3749.0, pix=3561.55, vendedor="Magalu")
PC_1709 = [_of("amazon", AMAZON, "B0F7JZMVKF", preco=4034.5), _of("mercadolivre", ML, "MLB48808732", preco=4169.0),
           _of("aliexpress", "AliExpress", "1005009459962683", preco=4199.0),
           _of("casasbahia", CB, "55069456", preco=2189.3, parcelado="6x R$ 795,32 sem juros")]
PELANDO_TVMAGALU = _reg_cupom("pelando", "tvmagalu300-pelando", MAGALU, "TVMAGALU300",
                              "Cupom Magalu R$ 300 OFF em TVs acima de R$ 3.000", "Não válido para a categoria Celulares.",
                              primeira="2026-09-17T12:00:00-03:00")
DESCONTOJA_PC = _c("pelando", "novo-post-descontoja", ML, "DESCONTOJA",
                   "Cupom Mercado Livre 15% OFF acima de R$ 50 (limi R$ 200 OFF)",
                   "Cupom Mercado Livre 15% OFF acima de R$ 50 (limi R$ 200 OFF)")
ZOOM_URL = "https://www.zoom.com.br/tv/smart-tv-mini-led-55-tcl-4k-55c6k?highlightedItemId=1489104908"


def _real(nome):
    """Arquivos reais da main (recorte em tests/fixtures/dados_8e21e6d.json)."""
    d = json.loads((RAIZ / "tests" / "fixtures" / "dados_8e21e6d.json").read_text(encoding="utf-8"))
    return d[nome]


# (id, achado que a diferença corrige ou None se o resultado tem de ser igual, arquivos iniciais, rodadas)
# rodada: (modo, ofertas, cupons)
def cenarios() -> list[tuple]:
    reais = {n: _real(n) for n in ("state_cloud", "state_pc", "latest_cloud", "latest_pc")}
    cloud_ofs = reais["latest_cloud"]["ofertas_loja"]
    return [
        ("F2-CB-descartada-e-Amazon-3100", "F2", {"state_pc": _state(_min(3199.0))},
         [("pc", PC_1709, []), ("pc", PC_1709[:3] + [], []),
          ("pc", [dict(PC_1709[0], preco=3100.0)] + PC_1709[1:3], [])]),
        ("F5-pc-3150-e-2950-contra-cloud-2991.60", "F5",
         {"state_cloud": _state(_min(2991.6, MAGALU)),
          "state_pc": _state(_min(3199.0), _reg_of("amazon", AMAZON, "B0F7JZMVKF", 3279.0))},
         [("pc", [_of("amazon", AMAZON, "B0F7JZMVKF", preco=3150.0, vendedor="Magalu.")], []),
          ("pc", [_of("amazon", AMAZON, "B0F7JZMVKF", preco=2950.0, vendedor="Magalu.")], [])]),
        ("F9-LU250-nova-data", "F9", {"state_cloud": _state(cupons=LU250)},
         [("cloud", [], [dict(LU250[2], id="LU250-2026-09-20")])]),
        ("REG1-MELIACHAPROMO", "REG-1", {"state_cloud": _state(cupons=[PEL_MELIACHA])},
         [("cloud", [], [PB_69374]), ("cloud", [], [PB_69469]),
          ("cloud", [], [dict(PB_69374, id="69999", titulo="A chance de economizar 15% em compras na Mercado Livre")])]),
        ("REG2-ESQUENTA320-do-produto", "REG-2", {"state_cloud": _state(cupons=[PEL_ESQ, PB_69223])},
         [("cloud", [], [ESQ_PRODUTO])]),
        ("R2-DESCONTOEMCASA-pelando-novo-id-pc", "R2-DESCONTOEMCASA", {"state_pc": _state(cupons=[PEL_CASA])},
         [("pc", [ML_OF], [dict(PEL_CASA, id="novo-id-do-pelando")])]),
        ("R3-DESCONTOJA-promobit-generico-cloud", "R3", {"state_cloud": _state(cupons=[PB_69522])},
         [("cloud", [ML_OF], [_c("promobit", "69703", ML, "DESCONTOJA",
                                 "OFERTA SURPRESA: 15% OFF em Produtos no Mercado Livre (acima de R$50) com cupom",
                                 "produtos Mercado Livre")])]),
        ("R4-TVMAGALU300-pelando-e-promobit", None,
         {"state_cloud": dict(_state(cupons=[PELANDO_TVMAGALU]), cupons_alertados={})},
         [("cloud", [MAGALU_OF], [_c("promobit", "tvmagalu300-promobit", MAGALU, "TVMAGALU300",
                                     "Cupom de desconto Magazine Luiza oferece R$ 300 OFF em TVs")])]),
        ("R4-exemplos-da-rodada-3", "F3",  # a main aceita todos; a diferença é só F3 (APPMAGALU350 "acima de R$ 3.000")
         {"state_cloud": _state()},
         [("cloud", [MAGALU_OF, ML_OF, _of("kabum", KABUM, "911482", preco=3159.0),
                     _of("amazon", AMAZON, "B0F7JZMVKF", preco=3279.0), _of("casasbahia", CB, "55069456", preco=3599.09)],
           [_c("promobit", d["codigo"] + str(i), d["loja"], d["codigo"], d["titulo"], d["regra"])
            for i, d in enumerate(SINTETICOS_CORRECOES) if d["origem"].startswith("rodada4")
            and d["codigo"] != "DESCONTOJA"])]),
        ("R4-DESCONTOJA-pc-com-os-state-reais", "R4e-DESCONTOJA",
         {n: reais[n] for n in ("state_cloud", "state_pc", "latest_cloud", "latest_pc")},
         [("pc", [ML_OF], [DESCONTOJA_PC])]),
        ("ZOOM-rodada-do-cloud-real", "ZOOM",
         {n: reais[n] for n in ("state_cloud", "state_pc", "latest_cloud", "latest_pc")},
         [("cloud", cloud_ofs, [])]),
        ("ZOOM-Amazon-2800-no-Zoom", "ZOOM",
         {n: reais[n] for n in ("state_cloud", "state_pc", "latest_cloud", "latest_pc")},
         [("cloud", [o for o in cloud_ofs if not (o["fonte"] == "zoom" and o["loja"] == AMAZON)]
           + [_of("zoom", AMAZON, "1489104908", preco=2800.0, url=ZOOM_URL)], [])]),
        ("ZOOM-so-o-agregador-conhece-a-loja", None,
         {n: reais[n] for n in ("state_cloud", "latest_cloud")},
         [("cloud", [o for o in cloud_ofs if not (o["fonte"] == "zoom" and o["loja"] == AMAZON)]
           + [_of("zoom", AMAZON, "1489104908", preco=2800.0, url=ZOOM_URL)], [])]),
    ]


def compara_cenarios(mm, mb, tmp: Path) -> tuple[list[dict], int]:
    difs = []
    todos = cenarios()
    for nome, achado, iniciais, rodadas in todos:
        pa, pb = tmp / f"c2_{nome}_main", tmp / f"c2_{nome}_branch"
        pa.mkdir()
        pb.mkdir()
        _grava_pre(pa, iniciais)
        _grava_pre(pb, iniciais)
        for i, (modo, ofs, cs) in enumerate(rodadas):
            mb["config"].DIR_DADOS = pb
            mb["util"].agora = lambda: AGORA_C2
            vistos = mb["estado"].Estado(modo).cupons_vistos()
            ra = rodada(mm, False, pa, modo, ofs, cs, AGORA_C2)
            rb = rodada(mb, True, pb, modo, ofs, cs, AGORA_C2)
            for dif in difere(ra, rb):
                classe, porque = explica_rodada(dif, ra, rb, mm, mb, vistos)
                if not classe and achado:
                    classe, porque = f"cenário {achado}", f"é a correção do achado {achado}"
                difs.append({"rodada": f"{nome} #{i + 1}", "dif": dif, "classe": classe, "porque": porque})
    return difs, len(todos)


def _relata(p, titulo, difs, detalhe):
    sem = [x for x in difs if not x["classe"]]
    p(f"   diferenças: {len(difs)}  explicadas: {len(difs) - len(sem)}  SEM EXPLICAÇÃO: {len(sem)}")
    for classe, n in sorted(Counter(x["classe"] or "SEM EXPLICAÇÃO" for x in difs).items()):
        p(f"     {n:4d}  {classe}")
    if detalhe or sem:
        for x in sorted(difs, key=lambda x: (x["classe"], x["rodada"])):
            tipo, chave, va, vb = x["dif"]
            p(f"   [{x['classe'] or 'SEM EXPLICAÇÃO'}] {x['rodada']} {tipo}: {str(chave)[:110]}")
            p(f"       main {str(va)[:120]} | branch {str(vb)[:120]}")
            if x["porque"]:
                p(f"       por quê: {x['porque'][:200]}")
    return len(sem)


# ============================================================ saída

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detalhe", action="store_true")
    ap.add_argument("--saida", default="")
    ap.add_argument("--so", default="C1,C2,C3")
    args = ap.parse_args()
    partes = set(args.so.split(","))
    out: list[str] = []

    def p(s=""):
        out.append(s)

    with tempfile.TemporaryDirectory() as tmp:
        mm = carrega_main(Path(tmp))
        mb = carrega_branch()
        versoes = versoes_dos_dados()
        resumo = []
        if "C1" in partes:
            reais = cupons_reais(versoes)
            sint = SINTETICOS_CORRECOES + sinteticos_dos_testes()
            corpus = reais + sint
            difs = compara_compat(mm, mb, corpus)
            sem = [x for x in difs if not x["classe"]]
            p(f"== C1 cupom_compativel: {len(corpus)} entradas ({len(reais)} variantes reais do git, {len(sint)} sintéticas)")
            p(f"   diferenças: {len(difs)}  explicadas: {len(difs) - len(sem)}  SEM EXPLICAÇÃO: {len(sem)}")
            for classe, n in sorted(Counter(x["classe"] or "SEM EXPLICAÇÃO" for x in difs).items()):
                p(f"     {n:4d}  {classe}")
            if args.detalhe or sem:
                for x in sorted(difs, key=lambda x: (x["classe"], x["cupom"]["codigo"])):
                    c = x["cupom"]
                    p(f"   [{x['classe'] or 'SEM EXPLICAÇÃO'}] {c['loja']} {c['codigo']} ({c['origem']}) preço {x['preco']}")
                    p(f"       título: {c['titulo'][:150]}")
                    if c["regra"]:
                        p(f"       regra:  {c['regra'][:150]}")
                    p(f"       main {x['main']}  branch {x['branch']}")
            resumo.append(("C1", len(corpus), len(difs), len(sem)))
        if "C2" in partes:
            difs, n = compara_cenarios(mm, mb, Path(tmp))
            p(f"== C2 cenários das correções (rodadas 1-4): {n} cenários")
            resumo.append(("C2", n, len(difs), _relata(p, "C2", difs, args.detalhe)))
        if "C3" in partes:
            difs, n = compara_rodadas_reais(mm, mb, versoes, Path(tmp))
            p(f"== C3 rodadas reais do histórico de docs/data: {n} rodadas (cloud e pc), cada uma a partir do state real")
            resumo.append(("C3", n, len(difs), _relata(p, "C3", difs, args.detalhe)))
        p("== RESUMO (parte, entradas, diferenças, sem explicação)")
        for r in resumo:
            p(f"   {r[0]}: {r[1]} entradas, {r[2]} diferenças, {r[2] - r[3]} explicadas, {r[3]} sem explicação")
    texto = "\n".join(out)
    if args.saida:
        Path(args.saida).write_text(texto, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    print(texto)
    return 1 if any(r[3] for r in resumo) else 0


if __name__ == "__main__":
    sys.exit(main())
