"""Diferencial do grupo estado-alertas: o código da main (8e21e6d) x o deste branch, no mesmo corpus.

Uso:  python tests/diff_estado_alertas.py [--detalhe] [--saida arquivo.txt]

Não é coletado pelo pytest (o nome não começa com test_). Só lê o git (cat-file/show) e os arquivos de correção da
auditoria; nunca escreve em docs/data (a reprodução roda em pastas temporárias).

Corpus
  (a) real: todas as versões de docs/data/state_*.json e latest_*.json no histórico do git (cupons: título/regra;
      ofertas de loja e posts: título, preços);
  (b) sintético: as entradas das correções das rodadas 1 a 4 (scratchpad/correcoes/estado-alertas*.json) e as linhas
      da tabela de ouro (tests/test_tabela_ouro_estado_alertas.py) e dos testes de cupom.

Comparações
  C1  cupom_compativel(cupom, preço da TV na loja) em cada cupom do corpus;
  C2  reprodução em cadeia das rodadas reais (cloud e pc intercaladas pela hora): cada código roda a sequência do
      seu run.py (sanear -> gerar_alertas -> cupons_aplicaveis -> persistência) com o seu próprio estado; compara os
      alertas (cupons, preços, posts), os cupons do painel e o mínimo;
  C3  sanear em cada versão das ofertas de loja.

Toda diferença tem de ter uma explicação (uma das classes EXPLICACOES, que dizem qual correção intencional a causa)
ou vira "SEM EXPLICAÇÃO" (bug a corrigir). O resumo no fim dá o tamanho do corpus e as contagens.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
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


# ============================================================ código da main num pacote temporário

def _git(*args: str, binario: bool = False):
    r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True)
    r.check_returncode()
    return r.stdout if binario else r.stdout.decode("utf-8")


def carrega_main(pasta: Path):
    """Copia monitor/ da main para <pasta>/monitor_main e importa (os imports do pacote são relativos)."""
    for arq in _git("ls-tree", "-r", "--name-only", MAIN_SHA, "monitor").split():
        dst = pasta / arq.replace("monitor/", "monitor_main/", 1)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(_git("show", f"{MAIN_SHA}:{arq}", binario=True))
    sys.path.insert(0, str(pasta))
    return {n: importlib.import_module(f"monitor_main.{n}") for n in ("config", "util", "models", "estado", "regras")}


def carrega_branch():
    return {n: importlib.import_module(f"monitor.{n}") for n in ("config", "util", "models", "estado", "regras")}


# ============================================================ corpus real: histórico de docs/data

def versoes_dos_dados() -> list[tuple[str, str, str, dict]]:
    """[(sha, data do commit, arquivo, json)] de todas as versões dos state/latest, do mais antigo ao mais novo."""
    linhas = [ln.split() for ln in _git("log", "--reverse", "--format=%H %cI", "--", *ARQS_DADOS).splitlines() if ln]
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


def compara_compat(mm, mb, corpus: list[dict]) -> list[dict]:
    difs = []
    for d in corpus:
        lc = mb["util"].loja_canonica(d["loja"])
        preco = d.get("preco") if d.get("preco") is not None else PRECO_LOJA.get(lc)
        a = mm["regras"].cupom_compativel(_cupom(mm, d), preco)
        b = mb["regras"].cupom_compativel(_cupom(mb, d), preco)
        if a[0] != b[0]:
            difs.append({"cupom": d, "preco": preco, "main": a, "branch": b})
    return difs
