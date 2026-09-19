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

Toda diferença recebe uma explicação (a correção intencional que a causa) ou vira "SEM EXPLICAÇÃO", que é bug. A
explicação de cupom (C1, e os cupons de C2/C3) só vale com PROVA lida no próprio texto do cupom por regex próprias
deste arquivo (explica_compat): teto do desconto x teto da compra, a palavra só dentro de uma exclusão, alvo com
palavras neutras, texto de cliente novo, lista de tamanhos que cobre a 55"... O motivo da main sozinho não explica: foi
assim que as regressões achadas pelo verificador na 1ª passada da rodada 4 passaram como "explicadas". O corpus
sintético inclui as sondas do verificador (scratchpad/vr4) e sondas próprias de cada regra nova. O resumo no fim dá o
tamanho do corpus e as contagens; com --detalhe lista cada diferença.
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


# sondas do verificador da rodada 4 (scratchpad/vr4/sonda_*.py: textos novos e realistas que ele usou para achar
# casos piores que a main)
SONDAS_DO_VERIFICADOR = [
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 250 OFF em Smart TV TCL 50", 55" e 65"', 'Válido para TVs vendidas pela Amazon.'),  # sonda_pol.py
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 250 OFF em Smart TV TCL 50", 55" e 65"', ''),  # sonda_pol.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TVs de 50" a 65"', ''),  # sonda_pol.py
    ('KaBuM!', 'SONDA', 'Cupom 10% OFF em Smart TVs 43" a 55"', ''),  # sonda_pol.py
    ('Casas Bahia', 'SONDA', 'Cupom Casas Bahia R$ 200 OFF em Smart TVs 50" ou 55"', ''),  # sonda_pol.py
    ('Magazine Luiza', 'SONDA', "Cupom Magalu R$ 300 OFF em Smart TVs 50'' a 65''", ''),  # sonda_pol.py
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 250 OFF em Smart TV TCL 50 55 e 65 polegadas', ''),  # sonda_pol.py
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 250 OFF em Smart TV TCL 50" / 55" / 65"', ''),  # sonda_pol.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TVs 50 pol. a 65 pol.', ''),  # sonda_pol.py
    ('KaBuM!', 'SONDA', 'Cupom KaBuM! R$ 200 OFF em Smart TVs TCL 50P7K e 55C6K', ''),  # sonda_pol.py
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 250 OFF em Smart TV TCL 50" e 55" C6K', ''),  # sonda_pol.py
    ('AliExpress', 'TUDO99', 'Os melhores itens do site com R$ 10 OFF aplicando cupom AliExpress', 'produtos Aliexpress Válido para itens de até R$ 99.'),  # sonda_a2.py
    ('Magazine Luiza', 'PRECINHO', 'Cupom de desconto Magalu oferece 15% OFF em suas compras', 'produtos Magazine Luiza Válido para produtos de até R$ 150 vendidos pela Magalu.'),  # sonda_a2.py
    ('Magazine Luiza', 'FAIXA30', 'Cupom de desconto Magalu de R$30 OFF em suas compras', 'produtos Magazine Luiza Válido em compras de R$ 200 até R$ 499.'),  # sonda_a2.py
    ('Magazine Luiza', 'MAX300', 'Cupom Magalu 10% OFF (limite R$ 30)', 'Válido para pedidos de no máximo R$ 300.'),  # sonda_a2.py
    ('Amazon', 'PEQ20', 'Desconto Amazon: economize 20% em suas compras', 'produtos Amazon Válido somente para itens com preço de até R$ 100.'),  # sonda_a2.py
    ('KaBuM!', 'ATE500', 'Use o cupom KaBum! e economize 10% em suas compras', 'produtos KaBuM! VÁLIDO PARA PRODUTOS ATÉ R$ 500'),  # sonda_a2.py
    ('Casas Bahia', 'CB20', 'Cupom Casas Bahia R$ 20 OFF', 'Válido para carrinhos de até R$ 300.'),  # sonda_a2.py
    ('Mercado Livre', 'ML10', 'Cupom Mercado Livre 10% OFF em compras até R$ 500', ''),  # sonda_a2.py
    ('Magazine Luiza', 'M50', 'Cupom Magalu R$ 50 OFF em pedidos até R$ 400', ''),  # sonda_a2.py
    ('Amazon', 'VALE', 'Cupom Amazon 15% OFF em produtos com valor até R$ 200', ''),  # sonda_a2.py
    ('Mercado Livre', 'RECOND10', 'Cupom Mercado Livre - 10% OFF em Produtos Recondicionados', 'Em itens Selecionados'),  # sonda_a3.py
    ('Amazon', 'USADOS15', 'Cupom Amazon 15% OFF em Produtos Usados', 'Válido para produtos vendidos pela Amazon'),  # sonda_a3.py
    ('KaBuM!', 'REEMB15', '15% de Desconto em produtos reembalados', 'produtos KaBuM! 15% OFF em produtos reembalados'),  # sonda_a3.py
    ('Mercado Livre', 'CONGEL10', 'Cupom Mercado Livre 10% OFF em Congelados e Resfriados', ''),  # sonda_a3.py
    ('Amazon', 'IMPORT', 'Cupom Amazon 10% OFF em Itens Importados', ''),  # sonda_a3.py
    ('Magazine Luiza', 'PERSO', 'Cupom Magalu 20% OFF em Produtos Personalizados', ''),  # sonda_a3.py
    ('Mercado Livre', 'OFDIA', 'Cupom Mercado Livre 10% OFF em Ofertas do Dia', ''),  # sonda_a3.py
    ('Amazon', 'VENDAMZ', 'Cupom Amazon R$ 100 OFF em produtos vendidos e entregues pela Amazon', 'Compra mínima R$ 1.000'),  # sonda_a3.py
    ('Magazine Luiza', 'ELETRO10', 'Cupom Magalu 10% OFF em Eletro', ''),  # sonda_a3.py
    ('Casas Bahia', 'MOVELETRO', 'Cupom Casas Bahia R$ 100 OFF em Móveis e Eletro', ''),  # sonda_a3.py
    ('Mercado Livre', 'MAISVEND', 'OFERTA TOP: 15% OFF em Mais Vendidos no Mercado Livre (acima de R$ 99) com cupom', 'produtos Mercado Livre'),  # sonda_a3.py
    ('Amazon', 'RENEW', 'Cupom Amazon 20% OFF em produtos Renovados', ''),  # sonda_a3.py
    ('Mercado Livre', 'OPENBOX', 'Cupom Mercado Livre 12% OFF em produtos Open Box', ''),  # sonda_a3.py
    ('KaBuM!', 'OPENB10', '10% de Desconto em produtos Open Box', 'produtos KaBuM! 10% OFF em produtos Open Box'),  # sonda_a3.py
    ('Magazine Luiza', 'LANC', 'Cupom Magalu 10% OFF em Lançamentos', ''),  # sonda_a3.py
    ('Mercado Livre', 'EMBAL', 'Cupom Mercado Livre 20% OFF em Itens Embalados a Vácuo', ''),  # sonda_a3.py
    ('Amazon', 'DIGITAL', 'Cupom Amazon 30% OFF em Produtos Digitais', ''),  # sonda_a3.py
    ('Mercado Livre', 'SEMINOVO', 'Cupom Mercado Livre 10% OFF em Celulares Seminovos', ''),  # sonda_a3.py
    ('Amazon', 'NOVOAPP', 'Cupom Amazon R$ 20 OFF para quem ainda não comprou no app', ''),  # sonda_a4.py
    ('Mercado Livre', 'NUNCA30', 'Cupom Mercado Livre R$ 30 OFF para quem nunca comprou', 'Compra mínima R$ 60'),  # sonda_a4.py
    ('Magazine Luiza', 'BEMVINDO', 'Cupom Magalu R$ 20 OFF para clientes novos no app', 'Válido para compras acima de R$ 100'),  # sonda_a4.py
    ('Casas Bahia', 'APPNOVO', 'Cupom Casas Bahia 10% OFF no app para novos cadastros', ''),  # sonda_a4.py
    ('Amazon', 'PRIMEIRA', 'Cupom Amazon R$ 25 OFF no primeiro pedido pelo app', ''),  # sonda_a4.py
    ('Magazine Luiza', 'SELTCL', 'Cupom Magalu - 10% OFF em Selecionados TCL', 'Em itens Selecionados'),  # sonda_a4.py
    ('Mercado Livre', 'TCLDAYS', 'Cupom Mercado Livre - 10% OFF Acima de R$1.500 limitado à R$400 em Selecionados TCL', 'Em itens Selecionados'),  # sonda_a4.py
    ('Magazine Luiza', 'TV300', 'Cupom Magalu R$ 300 OFF em TVs a partir de 55 polegadas', 'Válido em compras acima de R$ 2.999'),  # sonda_a4.py
    ('KaBuM!', 'TV43', 'Cupom KaBuM! R$ 100 OFF em Smart TVs de 32 e 43 polegadas', ''),  # sonda_a4.py
    ('Amazon', 'VALEPRESENTE', 'Cupom Amazon R$ 50 OFF na compra de Vale-Presente', ''),  # sonda_a4.py
    ('Magazine Luiza', 'CARTAOLUIZA', 'Cupom Magalu R$ 200 OFF pagando com Cartão Luiza em compras acima de R$ 2.000', ''),  # sonda_a4.py
    ('Mercado Livre', 'MELIPLUS', 'Cupom Mercado Livre 10% OFF para assinantes Meli+ (limite R$ 100)', ''),  # sonda_a4.py
    ('Amazon', 'ALEXA', 'Cupom Amazon R$ 100 OFF em dispositivos Echo e Fire TV', ''),  # sonda_a4.py
    ('Magazine Luiza', 'SEGURO', 'Cupom Magalu 20% OFF em Garantia Estendida', ''),  # sonda_a4.py
    ('Casas Bahia', 'TVCB', 'Cupom Casas Bahia R$ 250 OFF em TVs Mini LED', 'Válido para compras acima de R$ 3.000. Exceto marketplace.'),  # sonda_a4.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 100 OFF em TVs de 43 polegadas', ''),  # sonda_pre.py
    ('Fast Shop', 'SONDA', 'Cupom Fast Shop 10% OFF em Smart TVs Samsung', ''),  # sonda_pre.py
    ('KaBuM!', 'SONDA', 'Cupom KaBuM! 10% OFF em TVs e Monitores Gamer', ''),  # sonda_pre.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 10% OFF em TV e Áudio', ''),  # sonda_pre.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 100 OFF em TVs até R$ 2.000', ''),  # sonda_pre.py
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 10% OFF em Cama, Mesa e Banho e Smart TVs', ''),  # sonda_pre.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 400 OFF em Smart TVs 55", 65" e 75"', ''),  # sonda_tv.py
    ('Amazon', 'SONDA', 'Cupom Amazon: R$ 300 OFF em TVs TCL C6K (50" a 98")', ''),  # sonda_tv.py
    ('KaBuM!', 'SONDA', 'Cupom KaBuM! 12% OFF em Smart TVs TCL de 55 polegadas ou mais', 'produtos KaBuM! 12% OFF em Smart TVs TCL'),  # sonda_tv.py
    ('Amazon', 'SONDA', 'R$ 500 OFF na Smart TV TCL 55" C6K Mini LED', ''),  # sonda_tv.py
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 200 OFF na Smart TV TCL 55C6K e na 65C6K', ''),  # sonda_tv.py
    ('Casas Bahia', 'SONDA', 'Cupom Casas Bahia 10% OFF em TVs a partir de R$ 2.000 (exceto 32 e 43 polegadas)', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 250 OFF em Smart TV acima de R$ 3.000 no Pix', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em TVs 4K e 8K', ''),  # sonda_tv.py
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 15% OFF em TVs Mini LED (limite R$ 500)', ''),  # sonda_tv.py
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre - 8% OFF Acima de R$ 2.000 limitado à R$ 300 em Eletrônicos, Áudio e Vídeo', 'Em itens Selecionados'),  # sonda_tv.py
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 150 OFF em Smart TVs Google TV', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom de R$ 200 OFF em TVs QLED e Mini LED da TCL', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu: R$ 300 OFF em Eletrônicos (Smart TVs, Notebooks e Celulares)', ''),  # sonda_tv.py
    ('KaBuM!', 'SONDA', 'Cupom 10% OFF em Smart TVs 43" a 55"', ''),  # sonda_tv.py
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 300 OFF em Smart TVs 55" vendidas pela Amazon', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu - R$ 300 OFF em TVs Selecionadas Acima de R$ 2.999', 'Em itens Selecionados'),  # sonda_tv.py
    ('Casas Bahia', 'SONDA', 'Cupom Casas Bahia R$ 200 OFF em Smart TVs no app (1 uso por CPF)', ''),  # sonda_tv.py
    ('Fast Shop', 'SONDA', 'Cupom Fast Shop 5% OFF em TVs e Home Theaters', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em TVs, exceto TVs de 32" e 43"', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu - 10% OFF em TVs e Eletroportáteis (Exceto Linha Branca)', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF na Semana da TV', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom de desconto Magazine Luiza oferece R$ 300 OFF em TVs', 'produtos Magazine Luiza Válido para compras a partir de R$ 3.000 em TVs de 50 polegadas ou mais'),  # sonda_tv.py
    ('Amazon', 'SONDA', 'Smart TV TCL 55C6K por R$ 3.299 com cupom', ''),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TVs de 55 a 65 polegadas, exceto Samsung', ''),  # sonda_tv.py
    ('KaBuM!', 'SONDA', 'Cupom 10% OFF em Smart TVs 50" ou maiores', ''),  # sonda_tv.py
    ('Mercado Livre', 'SONDA', 'TELA GRANDE: 12% OFF em TVs no Mercado Livre (acima de R$ 1.500) com cupom', 'produtos Mercado Livre Desconto de até 12% em compra a partir de R$1.500, com desconto máximo de R$400 válido para itens elegíveis.'),  # sonda_tv.py
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre - 10% OFF Acima de R$1.999 limitado à R$300 em Smart TVs', 'Em Smart Tvs Selecionadas'),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu - R$ 250 OFF em Tv, Som e Vídeo', ''),  # sonda_tv.py
    ('Amazon', 'SONDA', 'Cupom Amazon 10% OFF em TV e Home Theater (limite R$ 200)', 'Válido para produtos vendidos e entregues pela Amazon. Não válido para Fire TV e Echo.'),  # sonda_tv.py
    ('Casas Bahia', 'SONDA', 'Cupom Casas Bahia R$ 300 OFF em Televisores acima de R$ 2.999', 'Não cumulativo com outras promoções. Não válido para produtos de marketplace.'),  # sonda_tv.py
    ('KaBuM!', 'SONDA', 'R$300,00 de Desconto em Smart TVs', 'produtos KaBuM! R$300,00 OFF em Smart TVs'),  # sonda_tv.py
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 8% OFF em Eletrônicos no Pix', 'Válido em compras acima de R$ 1.000, exceto celulares'),  # sonda_tv.py
    ('AliExpress', 'ATE99', 'Cupom AliExpress R$ 10 OFF em itens até R$ 99', 'Válido para itens da seção Tudo até R$ 99'),  # sonda_a.py
    ('Magazine Luiza', 'MAGA15', 'Cupom Magalu 15% OFF em produtos de até R$ 150', ''),  # sonda_a.py
    ('Magazine Luiza', 'FAIXA30', 'Cupom Magalu R$ 30 OFF em compras de R$ 200 até R$ 499', ''),  # sonda_a.py
    ('Mercado Livre', 'MAX300', 'Cupom Mercado Livre 10% OFF (limite R$ 30)', 'Válido para pedidos de no máximo R$ 300.'),  # sonda_a.py
    ('Amazon', 'ACHADOS', 'Cupom Amazon 10% OFF em itens de até R$ 200 vendidos pela Amazon', ''),  # sonda_a.py
    ('KaBuM!', 'TVS5', 'Cupom KaBuM! 5% OFF em Smart TVs de 50" a 65"', 'produtos KaBuM! 5% OFF em Smart TVs'),  # sonda_a.py
    ('Magazine Luiza', 'TV55MAIS', 'Cupom Magalu R$ 300 OFF em Smart TVs 55" ou mais', ''),  # sonda_a.py
    ('Casas Bahia', 'TV4K150', 'Cupom Casas Bahia R$ 150 OFF em TVs 4K acima de R$ 2.500', ''),  # sonda_a.py
    ('Mercado Livre', 'AVTV12', 'Cupom Mercado Livre - 12% OFF Acima de R$199 limitado à R$120 em TVs, Áudio e Vídeo', 'Em itens Selecionados'),  # sonda_a.py
    ('Mercado Livre', 'NOVOML25', 'Cupom Mercado Livre R$ 25 OFF para quem nunca comprou no app (acima de R$ 50)', 'Válido somente para a primeira compra no app'),  # sonda_a.py
    ('Amazon', 'BEMVINDO20', 'Cupom Amazon R$ 20 OFF para clientes novos no app', ''),  # sonda_a.py
    ('Magazine Luiza', 'SITE10', 'Cupom Magazine Luiza oferece 10% OFF em todo o site', 'produtos Magazine Luiza Não válido para produtos de Mercado, Eletroportáteis e Smart TVs.'),  # sonda_a.py
    ('Amazon', 'TV65', 'Cupom Amazon R$ 400 OFF em Smart TVs 65" ou maiores', ''),  # sonda_a.py
    ('Amazon', 'FIRETV', 'Cupom Amazon R$ 50 OFF em Fire TV Stick', ''),  # sonda_a.py
    ('Magazine Luiza', 'ELETRO200', 'Cupom Magalu - R$ 200 OFF em compras acima de R$ 2.000 em Eletroportáteis, TVs, Celulares e mais', ''),  # sonda_a.py
    ('Magazine Luiza', 'MAGALU300', 'Cupom Magalu - R$ 300 OFF em compras acima de R$ 3.000 (Exceto Celulares, Games e Informática)', 'Válido para produtos vendidos e entregues por Magalu.'),  # sonda_a.py
    ('Casas Bahia', 'TVCB8', 'Cupom Casas Bahia 8% OFF em Smart TVs, exceto TVs Samsung e LG', ''),  # sonda_a.py
    ('Casas Bahia', 'ELE8', 'Cupom Casas Bahia 8% OFF em Eletrônicos, exceto Smart TVs abaixo de 50"', ''),  # sonda_a.py
    ('Magazine Luiza', 'PIX5', 'Cupom Magalu 5% OFF extra no pagamento via Pix', 'Válido para compras acima de R$ 1.000'),  # sonda_a.py
    ('Magazine Luiza', 'CARTAO150', 'Cupom Magalu R$ 150 OFF para Cartão Magalu', 'Válido em compras acima de R$ 1.500 pagas com Cartão Luiza'),  # sonda_a.py
    ('Mercado Livre', 'TECH15', 'LIQUIDA TECH: 15% OFF em Tecnologia no Mercado Livre (acima de R$ 199) com cupom', 'produtos Mercado Livre'),  # sonda_a.py
    ('Magazine Luiza', 'TCLAPP250', 'Cupom de R$ 250 OFF na TV TCL 55C6K pelo app da Magalu', ''),  # sonda_a.py
    ('Magazine Luiza', 'SEMANA10', 'Cupom Magalu 10% OFF na Semana do Cliente', 'Limitado a R$ 200 de desconto.'),  # sonda_a.py
    ('Mercado Livre', 'FULL100', 'Cupom Mercado Livre: R$ 100 OFF em compras acima de R$ 1.000 em produtos com Frete Full', ''),  # sonda_a.py
    ('Magazine Luiza', 'CAMA15', 'Cupom Magalu 15% OFF em Cama, Mesa e Banho', ''),  # sonda_a.py
    ('Mercado Livre', 'SUPER20', 'Cupom Mercado Livre 20% OFF em Supermercado (acima de R$ 99)', ''),  # sonda_a.py
    ('Amazon', 'PRIME30', 'Cupom Amazon R$ 30 OFF para membros Prime em compras acima de R$ 150', ''),  # sonda_a.py
    ('KaBuM!', 'HARDWARE8', '8% de Desconto em Hardware', 'produtos KaBuM! 8% OFF em Hardware'),  # sonda_a.py
    ('KaBuM!', 'GAMER10', '10% de Desconto em Cadeiras e Mesas Gamer', 'produtos KaBuM! 10% OFF'),  # sonda_a.py
    ('Magazine Luiza', 'TVAUDIO', 'Cupom Magalu 10% OFF em TV e Áudio', ''),  # sonda_a.py
    ('Fast Shop', 'FAST300', 'Cupom Fast Shop R$ 300 OFF em compras acima de R$ 3.000', 'Não válido para produtos Apple.'),  # sonda_a.py
    ('Amazon', 'SMARTTV10', 'Cupom Amazon 10% OFF em Smart TVs (limite R$ 300)', 'Válido em Smart TVs vendidas e entregues pela Amazon. Não cumulativo.'),  # sonda_a.py
    ('Mercado Livre', 'DIADOSPAIS', 'Cupom Mercado Livre - 15% OFF acima de R$ 299 limitado a R$ 200 em Presentes para o Dia dos Pais', 'Em itens Selecionados'),  # sonda_a.py
    ('Casas Bahia', 'CBAPP', 'Cupom Casas Bahia R$ 100 OFF no App em compras acima de R$ 1.000', 'Exclusivo para compras no app.'),  # sonda_a.py
    ('Magazine Luiza', 'LOJA10', 'Cupom Magalu 10% OFF em produtos vendidos pela loja parceira Lojas Colombo', ''),  # sonda_a.py
    ('Mercado Livre', 'ELETRODOM', 'Cupom Mercado Livre 10% OFF em Eletrodomésticos (acima de R$ 500)', ''),  # sonda_a.py
    ('Mercado Livre', 'CELTV', 'Cupom Mercado Livre - 10% OFF em Celulares e Smartphones', 'Não válido para TVs'),  # sonda_a.py
    ('Magazine Luiza', 'VIDEO10', 'Cupom Magalu 10% OFF em TV e Vídeo', 'Compra mínima R$ 1.000'),  # sonda_a.py
    ('Amazon', 'OUTLET', 'Cupom Amazon 15% OFF em produtos do Outlet', 'Até R$ 100 de desconto'),  # sonda_a.py
    ('Mercado Livre', 'MELI3MIL', 'Cupom Mercado Livre R$ 300 OFF em compras de R$ 3.000 ou mais', 'Limitado a 1 uso por conta.'),  # sonda_a.py
    ('Magazine Luiza', 'TV100X', 'Cupom Magalu R$ 100 OFF em TVs até R$ 2.000', ''),  # sonda_a.py
    ('KaBuM!', 'TVKABUM', 'Cupom KaBuM! R$ 200 OFF em TVs de até R$ 5.000', ''),  # sonda_a.py
    ('Casas Bahia', 'ENTREGA50', 'Cupom Casas Bahia R$ 50 OFF na entrega de compras acima de R$ 1.000', ''),  # sonda_a.py
    ('Amazon', 'EBOOK', 'Cupom Amazon 20% OFF em eBooks Kindle', ''),  # sonda_a.py
    ('Magazine Luiza', 'INFO10', 'Cupom Magalu 10% OFF em Informática e Games', ''),  # sonda_a.py
]
# sondas próprias da 2ª passada da rodada 4: variações de cada regra nova (teto, tamanhos, qualificador, cliente novo,
# fim da exclusão), para achar casos em que o branch fica pior que a main
SONDAS_PROPRIAS = [
    ("Magazine Luiza", "SONDA", "Cupom Magalu 10% OFF em compras até R$ 2.500", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 200 OFF", "Válido para compras até R$ 5.000"),
    ("Magazine Luiza", "SONDA", "Economize até R$ 150 em compras acima de R$ 1.000", ""),
    ("Magazine Luiza", "SONDA", "Cupom de até R$ 300 OFF em compras acima de R$ 2.000", ""),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre: desconto de 10% limitado até R$ 100", ""),
    ("Amazon", "SONDA", "Ganhe 15% de desconto (até R$ 200) na Amazon", ""),
    ("KaBuM!", "SONDA", "Cupom KaBuM! 15% OFF - máximo de R$ 100", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 30 OFF em compras até R$ 300", ""),
    ("Casas Bahia", "SONDA", "Cupom Casas Bahia 20% OFF, desconto até R$ 50", ""),
    ("Amazon", "SONDA", "Cupom Amazon: 10% de volta em até R$ 100", ""),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre com cashback de até R$ 50", ""),
    ("Casas Bahia", "SONDA", "Frete grátis para compras até R$ 99", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu 10% OFF", "Válido para produtos a partir de R$ 100 até R$ 5.000"),
    ("Magazine Luiza", "SONDA", "Cupom Magalu 10% OFF", "Valor máximo do desconto: R$ 300"),
    ("Magazine Luiza", "SONDA", "Cupom Magalu 10% OFF", "Desconto máximo: R$ 300"),
    ("Magazine Luiza", "SONDA", "Até R$ 1.500 OFF em TVs com cupom Magalu", ""),
    ("Amazon", "SONDA", "Cupom Amazon 10% OFF em produtos até R$ 3.000", ""),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre 10% OFF em compras de até R$ 2.000", "Desconto máximo de R$ 200"),
    ("Amazon", "SONDA", 'Cupom Amazon R$ 300 OFF em Smart TV 4K 55"', ""),
    ("Amazon", "SONDA", 'Cupom Amazon R$ 300 OFF em Smart TVs 32" até 55"', ""),
    ("Amazon", "SONDA", "Cupom Amazon R$ 300 OFF na Smart TV 50 4K UHD", ""),
    ("Amazon", "SONDA", "Cupom Amazon R$ 300 OFF na Smart TV 55 4K", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em TVs 4K de 50 a 85 polegadas", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em Smart TVs 43 polegadas e 55 polegadas", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em Smart TV até 55", ""),
    ("Magazine Luiza", "SONDA", 'Cupom Magalu R$ 300 OFF na Smart TV 58"', ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF na Smart TV 2024 50 polegadas", ""),
    ("Magazine Luiza", "SONDA", "Cupom 10% OFF em Smart TVs de 32 a 50 polegadas", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em Smart TVs de 50 polegadas, 55 polegadas e 65 polegadas", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em Smart TV 55 ou 65 polegadas", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em Smart TV 50”", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu 10% OFF Smart TVs 12x sem juros", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu Smart TV com 20% OFF", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em Smart TVs 50+ polegadas", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em TVs de 55 polegadas", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em TVs de 65 e 75 polegadas", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em TVs", "Válido para TVs de 50 polegadas ou mais"),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF em TVs", "Não válido para TVs de 32 e 43 polegadas"),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre 10% OFF em produtos anunciados", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu 10% OFF em compras parceladas", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu 10% OFF em compras pagas com Pix", ""),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre 10% OFF em itens com frete grátis", ""),
    ("Amazon", "SONDA", "Cupom Amazon 10% OFF em produtos Seminovos", ""),
    ("KaBuM!", "SONDA", "10% de Desconto em produtos Open Box", "produtos KaBuM! 10% OFF em produtos Open Box"),
    ("Magazine Luiza", "SONDA", "Cupom Magalu 10% OFF em produtos de Vitrine", ""),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre R$ 20 OFF para quem nunca comprou no Mercado Livre", ""),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre R$ 50 OFF", "Válido para novos e antigos clientes"),
    ("Magazine Luiza", "SONDA", "Cupom de boas-vindas Magalu R$ 20 OFF", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 20 OFF exclusivo para novos clientes do app", ""),
    ("Amazon", "SONDA", "Cupom Amazon R$ 20 OFF na primeira compra no app", ""),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre 15% OFF", "Válido para clientes novos ou que não compram há 6 meses"),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 200 OFF em todo o site", "Exceto Celulares, Games e Informática"),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 200 OFF em todo o site", "Exceto TVs, em compras acima de R$ 1.000"),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre 10% OFF em todo o site",
     "Não válido para Supermercado, com desconto máximo de R$ 100"),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 200 OFF em todo o site", "Exceto Celulares, válido em compras acima de R$ 5.000"),
    ("Mercado Livre", "SONDA", "Cupom Mercado Livre R$ 100 OFF em produtos Full", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF para membros novos do Clube", ""),
    ("Magazine Luiza", "SONDA", "Cupom Magalu R$ 300 OFF", "Para compras pela primeira vez no app"),
    ("Amazon", "SONDA", "Cupom Amazon R$ 50 OFF em produtos vendidos por terceiros", ""),
    ("Amazon", "SONDA", "Cupom Amazon R$ 50 OFF", "Válido para produtos vendidos e entregues pela Amazon"),
]

SONDAS_PROPRIAS += [  # 2ª leva (scratchpad/r4ea/sonda_r4b.py)
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 10% OFF para compras de até R$ 1.999', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 10% OFF', 'Desconto máximo de R$ 1.999'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 5% OFF (desconto limitado a R$ 200)', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 5% OFF', 'O desconto é de até R$ 200 por CPF'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 5% OFF', 'Válido para pedidos com valor total de até R$ 5.000'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 5% OFF', 'Válido para pedidos com valor total de até R$ 1.000'),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 20% OFF até R$ 100', ''),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre R$ 20 OFF até R$ 100', ''),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 20% OFF', 'Desconto de 20% com teto de até R$ 100'),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 20% de desconto', 'Limite de desconto de até R$ 100'),
    ('Amazon', 'SONDA', 'Cupom Amazon: economize 10%', 'Válido em itens de até R$ 3.500'),
    ('Amazon', 'SONDA', 'Cupom Amazon: economize 10%', 'Aplicável em compras de R$ 100 a R$ 3.000'),
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 50 OFF', 'Cupom válido até 30/09 ou até R$ 10.000 em descontos'),
    ('KaBuM!', 'SONDA', 'Cupom KaBuM! 5% OFF', 'Válido em produtos até R$ 1.000 e acima de R$ 2.000'),
    ('KaBuM!', 'SONDA', 'Cupom KaBuM! 5% OFF no Pix até R$ 500', ''),
    ('Casas Bahia', 'SONDA', 'Cupom Casas Bahia 10% OFF', 'Válido para compras no valor máximo de R$ 800'),
    ('Casas Bahia', 'SONDA', 'Cupom Casas Bahia R$ 100 de cashback em compras até R$ 1.000', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu: R$ 300 de volta até R$ 3.000 em compras', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TV de 55 a 98 polegadas', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TVs até 43 polegadas', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TVs de 32 até 50 polegadas', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TVs de 65 a 85 polegadas', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TV QLED 4K 50”', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TV QLED 55” 4K', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TV TCL 43S5K e 55C6K', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em Smart TV TCL 43S5K', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em TV TCL 65C6K', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em TVs a partir de 43 polegadas', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em TVs acima de 60 polegadas', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em TVs grandes (55" ou mais)', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF em TVs grandes (65" ou mais)', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF na TV 55 polegadas', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF na TV 32 polegadas', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 150 OFF em TVs', 'Válido para Smart TVs 43" e 50"'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 150 OFF em TVs 50" ou menos', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 150 OFF em TVs 60" ou menos', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 150 OFF em Smart TV 55 polegadas 120Hz', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 150 OFF em Smart TV 40 anos Magalu', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu Smart TV: 10 dias de ofertas', ''),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 10% OFF em produtos selecionados vendidos pelo Mercado Livre', ''),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 10% OFF em produtos disponíveis', ''),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 10% OFF em produtos Full enviados pelo Mercado Livre', ''),
    ('Amazon', 'SONDA', 'Cupom Amazon 10% OFF em produtos internacionais', ''),
    ('Amazon', 'SONDA', 'Cupom Amazon 10% OFF em itens elegíveis', ''),
    ('Amazon', 'SONDA', 'Cupom Amazon 10% OFF em produtos Amazon Renew', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 10% OFF em produtos de mostruário', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 10% OFF', 'Válido para produtos novos e usados'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 10% OFF em pedidos realizados no app', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 10% OFF em compras feitas pelo site', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 10% OFF em produtos vendidos e entregues por Magalu', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu 10% OFF em produtos vendidos pelo Magalu e parceiros', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF', 'Válido para clientes novos e antigos'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF', 'Válido para todos os clientes, novos ou não'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF', 'Não é exclusivo para novos clientes'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 300 OFF', 'Válido para a primeira compra com o cartão Magalu'),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre R$ 30 OFF na sua primeira compra no Mercado Pago', ''),
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 20 OFF para quem ainda não assinou o Prime', ''),
    ('Amazon', 'SONDA', 'Cupom Amazon R$ 20 OFF para quem nunca usou o app', ''),
    ('Casas Bahia', 'SONDA', 'Cupom Casas Bahia R$ 50 OFF para novas contas do app', ''),
    ('Casas Bahia', 'SONDA', 'Cupom Casas Bahia R$ 50 OFF para novo usuário', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 50 OFF: primeira vez no app?', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 50 OFF na nova loja do app', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 50 OFF em novos produtos', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 50 OFF com o novo app', ''),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em todo o site', 'Exceto Celulares, com desconto máximo de R$ 200'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em todo o site', 'Exceto Celulares, TVs e Games'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em todo o site', 'Exceto Celulares, e TVs acima de R$ 5.000'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em todo o site', 'Exceto Celulares, 1 uso por CPF'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em todo o site', 'Exceto Celulares, para compras acima de R$ 5.000'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em todo o site', 'Exceto Celulares, compra mínima de R$ 5.000'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em todo o site', 'Exceto Celulares, Notebooks, com exceção de iPhone'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em todo o site', 'Exceto Celulares, cupons, vale-presente'),
    ('Magazine Luiza', 'SONDA', 'Cupom Magalu R$ 200 OFF em todo o site', 'Não válido para Apple, em compras até R$ 1.000'),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 10% OFF', 'Válido em todo o site, exceto Supermercado, desconto de até R$ 100'),
    ('Mercado Livre', 'SONDA', 'Cupom Mercado Livre 10% OFF', 'Exceto itens de Supermercado, em compras acima de R$ 99 na categoria Casa'),
]

def sinteticos_das_sondas() -> list[dict]:
    out = [_s(l, c, t, r, origem="sonda-verificador-r4") for l, c, t, r in SONDAS_DO_VERIFICADOR]
    out += [_s(l, c, t, r, origem="sonda-propria-r4b") for l, c, t, r in SONDAS_PROPRIAS]
    return out


# ============================================================ C1: cupom_compativel

def _cupom(mods, d: dict, cid: str = "x"):
    lc = mods["util"].loja_canonica(d["loja"])
    return mods["models"].Cupom(fonte=d["fonte"], loja=lc, codigo=d["codigo"], titulo=d["titulo"], url="", id=cid,
                                regra=d["regra"], especifico=d["especifico"])


# ---- explicação de uma diferença de cupom_compativel ----
# Cada classe só vale com PROVA no próprio texto do cupom, lida aqui de um jeito independente do código do branch
# (regex próprias, mais simples). O motivo da main sozinho não explica nada: foi assim que as regressões da rodada 4
# (teto do item lido como teto do desconto, "Renovados", cliente novo no app, lista de tamanhos com ") passaram como
# "explicadas". Diferença sem prova = SEM EXPLICAÇÃO = bug.

def _desfaz_mojibake(s: str) -> str:
    """'vÃ¡lido' -> 'válido' (texto UTF-8 que uma coleta antiga leu como cp1252)."""
    def um(m: re.Match) -> str:
        for cod in ("cp1252", "latin-1"):
            try:
                return m.group(0).encode(cod).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        return m.group(0)

    return re.sub("[ÂÃ][-¿Œ-™]", um, s or "")


def _n(s: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", _desfaz_mojibake(s))
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    t = t.replace("ª", "a").replace("º", "o")
    return re.sub(r"\s+", " ", t)


# exclusão até o fim da frase ("." de número não fecha a frase)
_X_EXCL = re.compile(r"(?:\b(?:exceto|excluindo|exclui|excluid[oa]s?|nao\s+(?:e\s+|sao\s+)?valid[oa]s?|nao\s+vale|"
                     r"nao\s+se\s+aplica|nao\s+inclui|nao\s+contempla|com\s+excecao\s+de)|(?:,\s*|\b(?:tudo|site|loja)\s+)(?:menos|fora))\b"
                     r"(?:(?!,\s*(?:em|na|no|para|com|acima|a partir|valid|limit|pedido|compra|minim|maxim|ate|cupom|"
                     r"desconto|r\$|\d))[^.;|!?()]|\.(?=\d))*")
_X_TV = re.compile(r"\btvs?\b|televis|eletronic|\beletro\b|tecnolog|audio\s*(?:e|&|,)\s*video|todo o site|site todo|"
                   r"todo site|loja toda|toda a loja|todas as categorias|\bem geral\b|\bem tudo\b|todos os produtos")
_X_NAO_TV = re.compile(r"\b(?:fire|google|android|apple|roku)\s+tv\b|\btv\s+(?:box|stick)\b|"
                       r"\b(?:acessorios?|suportes?|controles?(?:\s+remotos?)?|cabos?|antenas?)\s+(?:para|pra|de)\s+"
                       r"(?:sua\s+)?(?:smart\s*)?tvs?\b")
_X_NOVO = re.compile(r"\bnov[oa]s?\s+(?:client|usuari|conta|cadastr|comprador)|\b(?:client|usuari|conta|cadastr)\w*\s+"
                     r"nov[oa]|\bnunca\s+(?:comprou|compraram)|\bnao\s+comprou|\b(?:1a|1o|primeir[oa]s?)\s+(?:compra|"
                     r"pedido)|primeira\s+vez")
_X_NOVO_TAMBEM = re.compile(r"\binclusive\b|\btambem\b|\bantig|todos os clientes|qualquer cliente|"
                            r"\bnao\s+(?:e\s+)?(?:necessario|precis|exclusiv|somente|apenas)")
_X_TETO = re.compile(r"\b(?:ate|(?:no\s+)?maxim[oa](?:\s+d[eoa])?)\s*(?:de\s+)?r\$\s?(\d[\d.]*)")
_X_PALAVRA_DE_DESCONTO = re.compile(r"economi|ganh|descont|cupo|voucher|cashback|limit|frete|entrega|gratis|volta|"
                                    r"bonus|credito|abatiment|reembols|%")
_X_ENCHIMENTO = {"de", "do", "da", "no", "na", "o", "a", "um", "uma", "valor", "total", "maximo", "maxima", "limite",
                 "e", ",", "(", ":", "-", "off"}
# palavras que não são categoria num alvo "OFF em X" do título (lista própria do diferencial)
_X_NEUTRAS = set("""o a os as de da do das dos e em no na nos nas um uma sua suas seu seus todo toda todos todas cada
qualquer mais compra compras pedido pedidos produto produtos item itens carrinho site loja lojas app aplicativo pix boleto
cartao cartoes credito debito pagamento promocao promocoes oferta ofertas frete gratis geral acima partir minimo minima
valor vendido vendidos vendida vendidas entregue entregues realizada realizadas realizado realizados feito feitos feita
feitas elegivel elegiveis disponivel disponiveis pelo pela por com ate r mercado livre magalu magazine luiza amazon kabum
aliexpress shopee fast shop casas bahia seus seu gerais cupom cupons desconto descontos off anunciado
anunciados anunciada anunciadas parcelada parceladas parcelado parcelados paga pagas pago pagos""".split())


def _fora_das_exclusoes(t: str) -> str:
    return _X_EXCL.sub(" ", t)


def _tem_tv(t: str) -> bool:
    return bool(_X_TV.search(_X_NAO_TV.sub(" ", _fora_das_exclusoes(t))))


def _so_nas_exclusoes(t: str, palavra: str) -> bool:
    """A palavra aparece no texto, e só dentro de exclusões."""
    rx = re.compile(r"\b" + re.escape(palavra.strip()))
    return bool(rx.search(t)) and not rx.search(_fora_das_exclusoes(t))


def _teto_e_do_desconto(t: str, m: re.Match) -> bool:
    """Prova independente de que 'até/máximo R$ X' é o teto do DESCONTO: a palavra antes (pulando enchimento) é de
    desconto, ou o valor vem seguido de OFF / de desconto / de volta."""
    if re.match(r"\s*(?:off\b|(?:de|em)\s+(?:descont|volta|cashback))", t[m.end():]):
        return True
    antes = re.split(r"[;|!?]|\.(?!\d)", t[max(0, m.start() - 80):m.start()])[-1]
    toks = re.findall(r"%|[a-z$]+|[\d.,]+|[,(:-]", antes)
    while toks and toks[-1] in _X_ENCHIMENTO:
        if toks[-1] == "off":
            # "% OFF até" é teto do desconto; "R$ 20 OFF até" (desconto fixo) não
            return len(toks) >= 2 and toks[-2] == "%"
        toks.pop()
    return bool(toks) and bool(_X_PALAVRA_DE_DESCONTO.search(toks[-1]))


def _tetos_independentes(t: str) -> list[tuple[float, bool]]:
    """[(valor, é teto do desconto)] de cada 'até/máximo R$ X' fora das exclusões."""
    t = _fora_das_exclusoes(t)
    out = []
    for m in _X_TETO.finditer(t):
        try:
            v = float(m.group(1).rstrip(".,").replace(".", ""))
        except ValueError:
            continue
        out.append((v, _teto_e_do_desconto(t, m)))
    return out


def _tamanhos_incluem_55(t: str) -> bool:
    """Prova independente de que o texto cobre a 55": o número 55 (ou um modelo 55xxx), uma faixa que passa por 55
    ou 'a partir de/acima de/ou mais' com um número <= 55."""
    t = _fora_das_exclusoes(t)
    if re.search(r"(?<![\d.,])55(?!\d)", t):
        return True
    limpo = re.sub(r"\"|''|'|”|″|\bpol(?:egadas?)?\.?", " ", t)
    for a, b in re.findall(r"(?<![\d.,])(\d{2})\s*(?:\ba\b|\bate\b|-|–)\s*(\d{2})(?!\d)", limpo):
        if int(a) <= 55 <= int(b):
            return True
    for n in re.findall(r"(?:acima\s+de|a\s+partir\s+de|partir\s+de|maiores?\s+que)\s+(\d{2})(?!\d)", limpo):
        if int(n) <= 55:
            return True
    for n in re.findall(r"(?<![\d.,])(\d{2})(?!\d)\s*(?:\+|ou\s+mais|ou\s+maior|ou\s+superior|ou\s+acima)", limpo):
        if int(n) <= 55:
            return True
    return False


def explica_compat(a: tuple, b: tuple, d: dict) -> tuple[str, str]:
    """(classe, por quê) de uma diferença de cupom_compativel: a = main, b = branch. Classe '' = sem explicação."""
    ma, mb = a[1], b[1]
    t = _n(f"{d['titulo']} | {d['regra']}")
    tit = _n(d["titulo"])
    if b[0]:  # o branch aceita o que a main recusava
        if _X_NOVO.search(_fora_das_exclusoes(t)) and not _X_NOVO_TAMBEM.search(t):
            return "", ""  # texto de cliente novo: aceitar é alerta falso
        if ma.startswith("só até R$"):
            v = float(ma.split("R$")[1])
            tetos = [x for x in _tetos_independentes(t) if abs(x[0] - v) < 1]
            if tetos and all(desc for _v, desc in tetos):
                return "F3-teto-do-desconto", "'até/máximo R$' logo depois de desconto/% ou seguido de OFF: teto do DESCONTO (F3)"
            valor = re.compile(r"r\$\s?" + re.escape(f"{v:,.0f}".replace(",", ".")) + r"(?!\d)|r\$\s?"
                               + re.escape(f"{v:.0f}") + r"(?!\d)")
            if not tetos and any(re.search(r"\b(?:ate|maxim)", x.group(0)) and valor.search(x.group(0))
                                 for x in _X_EXCL.finditer(t)):
                return "R4a-valor-na-exclusao", "o 'até R$' estava numa exclusão (R4 a)"
            return "", ""
        if ma.startswith("só acima de R$"):
            v = float(ma.split("R$")[1])
            num = r"(?:" + re.escape(f"{v:,.0f}".replace(",", ".")) + "|" + re.escape(f"{v:.0f}") + r")(?![\d])"
            minimo = r"(?:acima de|a partir de|minim[oa](?: de)?|compras?\s+(?:de|a partir de))\s*r\$\s?" + num
            if not re.search(minimo, _fora_das_exclusoes(t)) and any(re.search(minimo, x.group(0))
                                                                      for x in _X_EXCL.finditer(t)):
                return "R4a-valor-na-exclusao", "o 'acima de R$' estava numa exclusão ('exceto TVs acima de R$ 5.000'), " \
                                                "não é compra mínima (R4 a)"
            return "", ""
        if ma.startswith("marca/produto: "):
            w = ma.split(": ", 1)[1]
            if _so_nas_exclusoes(t, w):
                return "R4a-exclusao", f"'{w}' só aparece numa exclusão (R4 a)"
            if w == "audio" and re.search(r"audio\s*(?:e|&|,)\s*video", t) and not re.search(
                    r"\baudio\b(?!\s*(?:e|&|,)\s*video)", t):
                return "R4b-audio-e-video", "'Áudio e Vídeo' é a categoria das TVs (R4 b)"
            return "", ""
        if ma.startswith("categoria: "):
            alvo = ma.split(": ", 1)[1].strip()
            if alvo == "mercado":
                sem_loja = re.sub(r"mercado\s*(?:livre|pago)", " ", t)
                if "mercado " not in sem_loja + " ":
                    return "F3-nome-da-loja", "o 'mercado' era o nome da loja Mercado Livre (ou Mercado Pago) (F3)"
                if _so_nas_exclusoes(t, "mercado"):
                    return "R4a-exclusao", "'mercado' só aparece numa exclusão (R4 a)"
                if _tem_tv(t):
                    return "R4b-alvo-tv", "um alvo é TV/eletrônicos/tecnologia/site todo (R4 b)"
                return "", ""
            if alvo in ("novos clientes", "primeira compra") and _X_NOVO_TAMBEM.search(t):
                return "R4-cliente-novo-tambem", "vale também para quem já é cliente ('inclusive', 'antigos e novos')"
            if alvo in ("app", "aplicativo", "frete", "entrega"):
                if _tem_tv(t) or not _X_NOVO.search(t):
                    return "R4d-frete-app", "frete, entrega e app não são categorias, e o texto não é de cliente novo (R4 d)"
                return "", ""
            if _so_nas_exclusoes(t, alvo.split()[0]):
                return "R4a-exclusao", f"'{alvo}' só aparece numa exclusão (R4 a)"
            if _tem_tv(t):
                return "R4b-alvo-tv", "um alvo (em qualquer lugar do texto) é TV/eletrônicos/tecnologia/site todo (R4 b)"
            if re.match(r"(?:compras?|pedidos?)\b.*\b(?:acima|partir|minim|r\$)", alvo):
                return "F3-valor-minimo", "'OFF em compras acima de R$ X' é valor mínimo, não categoria (F3)"
            # o alvo inteiro do título (a main corta o motivo em 30 caracteres), sem valores
            m_alvo = re.search(r"\boff\s+em\s+(.{3,60})$", tit.strip())
            alvo = m_alvo.group(1) if m_alvo and m_alvo.group(1).startswith(alvo[:20]) else alvo
            sem_valor = re.sub(r"r\$\s?[\d.,]+\+?|\d+", " ", alvo)
            palavras = [w for w in re.findall(r"[a-z]+", sem_valor) if w not in _X_NEUTRAS]
            if not palavras:
                return "R4b-alvo-neutro", f"o alvo '{alvo}' só tem palavras neutras (compras, app, Pix, vendidos pela " \
                                          "loja...) (R4 b)"
            return "", ""
        return "", ""
    # o branch recusa o que a main aceitava
    if mb.startswith("exclui: "):
        if any(_X_TV.search(_X_NAO_TV.sub(" ", x.group(0))) for x in _X_EXCL.finditer(t)):
            return "R4a-exclui-a-tv", "a exclusão tira a própria TV ('exceto TVs/eletrônicos/TCL')"
        return "", ""
    if mb.startswith("outro produto: kit"):
        if "kit" in tit and not _tem_tv(t):
            return "R3-kit", "anúncio de um kit sem TV"
        return "", ""
    if mb.startswith("outro produto: "):
        if not _tamanhos_incluem_55(t) and not re.search(r"\binclusive\b|\btodas?\s+as\s+(?:smart\s*)?tvs\b", t):
            return "R3-outro-tamanho", "TV de outro tamanho/modelo e nada no texto cobre a 55\""
        return "", ""
    if mb.startswith("só para novos clientes"):
        if _X_NOVO.search(_fora_das_exclusoes(t)):
            return "R3-cliente-novo", "cupom só para cliente novo / 1ª compra"
        return "", ""
    if mb == "só frete":
        resto = re.sub(r"r\$\s?[\d.,]+\s*(?:off\s+)?(?:n[oa]|d[oa]|em)\s+fretes?|fretes?\s+gratis|"
                       r"(?:acima de|a partir de|minim[oa](?: de)?|compras?\s+(?:de|acima de))\s*r\$\s?[\d.,]+", " ", t)
        if "frete" in t and not re.search(r"r\$\s?\d|\d\s*%", resto):
            return "R4d-so-frete", "cupom só de frete: não é desconto no preço da TV"
        return "", ""
    if mb.startswith(("categoria: ", "restrito: ")):
        if _tem_tv(t):
            return "", ""  # o texto diz TV/site todo fora das exclusões: recusar por categoria é cupom perdido
        if mb.startswith("restrito: anúncio cortado"):
            return "R3-anuncio-cortado", "título cortado em 'em': a categoria sumiu"
        if mb.startswith("restrito: "):
            return "R3-selecao", "vale só para uma seleção de itens sem dizer que é TV/tecnologia"
        return "R3-categoria-declarada", "o alvo declarado do desconto é uma categoria que não é TV (e nada diz TV)"
    if mb.startswith("só até R$"):
        v = float(mb.split("R$")[1])
        tetos = [x for x in _tetos_independentes(t) if abs(x[0] - v) < 1]
        if tetos and not any(desc for _v, desc in tetos):
            return "F3-teto-da-compra", "teto da COMPRA/do item menor que o preço da TV (a main só recusava abaixo de " \
                                        "metade do preço, ou não lia 'compra máxima')"
        return "", ""
    if mb.startswith("só acima de R$"):
        v = float(mb.split("R$")[1])
        num = r"(?:" + re.escape(f"{v:,.0f}".replace(",", ".")) + "|" + re.escape(f"{v:.0f}") + r")(?![\d])"
        fora = _fora_das_exclusoes(t)
        if re.search(r"\b(?:off|desconto)\s+em\s+r\$\s?" + num, fora):
            return "R4-minimo-em-R$", "'R$ 350 OFF em R$ 3500': o valor depois de 'OFF em' é a compra mínima"
        if re.search(r"(?:acima de|a partir de|minim[oa](?: de)?|compras?\s+(?:de|a partir de))\s*r\$\s?" + num, fora):
            return "R4-compra-minima", "compra mínima acima do preço da TV que a main não lia ('compra mínima de R$ X', " \
                                       "ou um segundo mínimo no texto)"
        return "", ""
    if mb.startswith("marca/produto: ") and _conserta_so_mojibake(d):
        return "mojibake", "o texto antigo tinha mojibake (UTF-8 lido como cp1252); consertado ele diz outra marca/produto"
    return "", ""


def _conserta_so_mojibake(d: dict) -> bool:
    return bool(re.search("[ÂÃ][-¿Œ-™]", f"{d['titulo']} {d['regra']}"))


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
            sint = SINTETICOS_CORRECOES + sinteticos_dos_testes() + sinteticos_das_sondas()
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
