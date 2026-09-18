"""Tabela de ouro do grupo estado-alertas (rodada 3).

Um caso por exemplo concreto: a evidência dos achados F2, F3, F4, F5 e F9, todas as regressões das rodadas 1 e 2
(REG-1, REG-2, DESCONTOEMCASA) e os casos que os verificadores disseram que têm de continuar funcionando.
Cada linha é entrada -> saída esperada (aceita/recusa, preço, parcelado, alerta sai ou não). Quando uma expectativa
antiga e uma nova conflitam, vale a do verificador mais recente; o comentário da linha diz por quê.

Textos de cupom: reais, dos state_*.json de 13 a 18/09/2026 (o id do anúncio vai no nome da linha quando ajuda).
Nada aqui lê ou escreve docs/data. Os snapshots reais das páginas só são lidos; sem eles a linha é pulada.
"""

import csv
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from monitor import config
from monitor.estado import Estado, lojas_diretas
from monitor.models import Cupom, Oferta
from monitor.regras import cupom_compativel, cupons_aplicaveis, gerar_alertas, mensagem_bootstrap, resumo_diario, sanear
from monitor.util import agora

SNAP = Path(r"C:\Users\luisd\AppData\Local\Temp\claude\C--Users-luisd-OneDrive--rea-de-Trabalho-promos"
            r"\8294b9c9-bb7f-4112-99fd-4c7e3e9f239b\scratchpad\snapshots")
URL_CB = "https://www.casasbahia.com.br/x/p/55069456"
ML, MAGALU, AMAZON, KABUM, ALI = "Mercado Livre", "Magazine Luiza", "Amazon", "KaBuM!", "AliExpress"
# preços reais da TV em 18/09 (Pix): ML 3.491,03 (snapshot), Magalu 3.561,55, Amazon 3.279, KaBuM 3.159, Ali 3.749
P_ML, P_MAGALU, P_AMAZON, P_KABUM, P_ALI = 3491.03, 3561.55, 3279.0, 3159.0, 3749.0


@pytest.fixture(autouse=True)
def dados_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    return tmp_path


# ============================================================ 1) cupom_compativel: texto do cupom -> serve para a TV?
# (id da linha, loja, código, título, regra, preço da TV na loja, esperado)

COMPAT = [
    # ---- F3: cupons do site todo que servem para a TV (evidência do achado; têm de continuar aceitos) ----
    ("F3-INFLU300-economize-ate-300-acima-de-3000", MAGALU, "INFLU300",
     "Os melhores itens do site com R$ 300 OFF aplicando cupom Magalu",
     "produtos Magazine Luiza Economize até R$ 300 ao usar o código promocional no carrinho de compras (acima de R$ 3000).",
     P_MAGALU, True),
    ("F3-RODEIO220-economize-ate-220-acima-de-2000", MAGALU, "RODEIO220",
     "Cupom de desconto Magazine Luiza oferece R$ 220 OFF em suas compras",
     "produtos Magazine Luiza Economize até R$ 220 ao usar o código promocional em compras acima de R$ 2.000 no "
     "carrinho de compras.", P_MAGALU, True),
    ("F3-INFLU25-25pct-off-ate-800", MAGALU, "INFLU25", "Use cupom Magalu e tenha desconto de 25% OFF até R$ 800",
     "produtos Magazine Luiza Economize até 25% OFF até R$ 800 ao usar o código promocional no carrinho de compras.",
     P_MAGALU, True),
    ("F3-ESQUENTA320-pelando-OFF-em-compras-acima-de-3000", MAGALU, "ESQUENTA320",
     "Magalu: Ganhe R$320 OFF em compras acima de R$3.000", "R$320 partir de R$3.000 (válido para itens elegíveis )",
     P_MAGALU, True),
    ("F3-ESQUENTA320-promobit-69223", MAGALU, "ESQUENTA320",
     "Os melhores itens do site com R$320 OFF aplicando cupom Magazine Luiza",
     "produtos Magazine Luiza Economize até R$320 ao usar o código promocional no carrinho de compras (a partir de R$3.000).",
     P_MAGALU, True),
    ("F3-R$320-OFF-em-compras-acima-de-R$3.000", MAGALU, "X", "R$ 320 OFF em compras acima de R$ 3.000", "", P_MAGALU, True),
    ("F3-desconto-maximo-de-R$500-e-teto-do-desconto", MAGALU, "X",
     "Cupom Magalu com desconto máximo de R$500 em suas compras", "", P_MAGALU, True),
    # "mercado " do nome da loja não é a categoria supermercado
    ("F3-PEGANOMELI-OFF-no-Mercado-Livre", ML, "PEGANOMELI",
     "CAÇA AO DESCONTO: 22% OFF no Mercado Livre (acima de R$1) com cupom",
     "produtos Mercado Livre Desconto de até 22% em compra a partir de R$1, com desconto máximo de R$500.", P_ML, True),
    ("F3-DESCONTOBOM-OFF-no-Mercado-Livre", ML, "DESCONTOBOM",
     "FESTA DE PREÇOS: 25% OFF no Mercado Livre (acima de R$1) com cupom",
     "produtos Mercado Livre Desconto de até 25% em compra a partir de R$1, excluído o valor do frete, com desconto "
     "máximo de R$500 válido para itens elegíveis.", P_ML, True),
    ("F3-ALLSITE-em-Todo-Site", ML, "ALLSITE", "Cupom Mercado Livre - R$50 off em Compras Acima de R$499 em Todo Site",
     "Cupom Diz Todo Site, confiram", P_ML, True),
    ("F3-ACHEIOFF-em-geral", ML, "ACHEIOFF",
     "CAÇA AO DESCONTO: 25% OFF em geral no Mercado Livre (acima de R$1) com cupom", "", P_ML, True),
    ("F3-NOVA1-em-compras-acima-de-1600-na-AliExpress", ALI, "NOVA1",
     "COMPRE MAIS: R$ 240 OFF em compras acima de R$ 1.600 na AliExpress (com cupom)", "produtos Aliexpress", P_ALI, True),
    ("F3-NATORCIDA-em-compras-na-Amazon", AMAZON, "NATORCIDA", "A chance de economizar 30% OFF em compras na Amazon",
     "produtos Amazon", P_AMAZON, True),
    # ---- continuam fora (tests/test_parsers.py e rodada 1) ----
    ("F3-compras-ate-R$600-continua-fora", MAGALU, "DESCONTA15",
     "O momento chegou: Aplique cupom Magazine Luiza e ganhe 15% OFF",
     "produtos Magazine Luiza Aplique o código promocional no carrinho de compras em compras até R$600.", P_MAGALU, False),
    ("F3-acima-de-R$4.200-continua-fora", MAGALU, "X", "Magalu: R$ 400 OFF em compras acima de R$ 4.200", "",
     P_MAGALU, False),
    ("F3-supermercado-continua-fora", MAGALU, "X", "Cupom Magalu 10% OFF em Mercado", "", P_MAGALU, False),
    ("F3-FULL1209-entregas-FULL-continua-fora", ML, "FULL1209",
     "Cupom Mercado Livre oferece 10% OFF, máximo R$ 20, em R$ 89 em Entregas FULL", "pedido mínimo R$ 89", P_ML, False),
    ("F3-tudo-pra-casa-continua-fora", ML, "CASA1309",
     "Cupom Mercado Livre - R$100 OFF em Compras Acima de R$899 em Tudo Pra Casa", "Em Itens Selecionados", P_ML, False),
    # ---- REG-1 (rodada 1): o mesmo código escrito de jeitos diferentes ----
    ("REG1-MELIACHAPROMO-pelando-em-Selecionados-recusado", ML, "MELIACHAPROMO",
     "Cupom Mercado Livre - 10% OFF Acima de R$99 limitado à R$300 em Selecionados", "Em Itens Selecionados", P_ML, False),
    ("REG1-MELIACHAPROMO-promobit-69374-aceito", ML, "MELIACHAPROMO",
     "A chance de economizar 10% em compras na Mercado Livre",
     "produtos Mercado Livre Economize até 10% ao usar o código promocional no carrinho de compras (compra mínima R$99).",
     P_ML, True),
    ("REG1-MELIACHAPROMO-promobit-69469-itens-elegiveis-aceito", ML, "MELIACHAPROMO",
     "Cupom de desconto Mercado Livre oferece 10,00% OFF em suas compras",
     "produtos Mercado Livre Desconto de até 10% em compra a partir de R$99, excluído o valor do frete, com desconto "
     "máximo de R$300 válido para itens elegíveis.", P_ML, True),
    ("F9-PROMOMELI-pelando-em-Tecnologia-aceito", ML, "PROMOMELI",
     "Cupom Mercado Livre - 10% acima de R$149 limitado à R$200 em Tecnologia", "Em itens Selecionados", P_ML, True),
    ("F9-PROMOMELI-promobit-69433-aceito", ML, "PROMOMELI", "A chance de economizar 10% em compras no Mercado Livre",
     "produtos Mercado Livre -", P_ML, True),
    # ---- regressão da rodada 2: cupom só de uma categoria virou compatível ao tirar o nome da loja ----
    ("R2-DESCONTOEMCASA-pelando-30a59912-na-categoria-Casa", ML, "DESCONTOEMCASA",
     "Cupom Mercado Livre oferece 20% OFF, máximo R$ 60, em R$ 79 em Casa", "pedido mínimo R$ 79 na categoria Casa",
     P_ML, False),
    # ---- regra geral pedida na rodada 3: cupom de uma categoria só serve se a categoria for TV/eletrônicos/
    # tecnologia ou o site todo. Textos reais do corpus de 13-18/09 ----
    ("R3-na-categoria-X-so-na-regra", ML, "X", "Cupom Mercado Livre oferece 20% OFF",
     "pedido mínimo R$ 79 na categoria Casa", P_ML, False),
    ("R3-na-categoria-Eletronicos-serve", ML, "X", "Cupom Mercado Livre oferece 10% OFF",
     "pedido mínimo R$ 149 na categoria Eletrônicos", P_ML, True),
    ("R3-em-Casa-DESCONTOJA-promobit-69522", ML, "DESCONTOJA",
     "NOVO ESPAÇO: 15% OFF em Casa no Mercado Livre (acima de R$50) com cupom", "produtos Mercado Livre", P_ML, False),
    ("R3-em-Casa-e-Decor-DESCONTOEMCASA-promobit-69554", ML, "DESCONTOEMCASA",
     "ESTILO NOVO: 20% OFF em Casa e Decor no Mercado Livre (acima de R$79) com cupom", "produtos Mercado Livre",
     P_ML, False),
    ("R3-em-Acessorios-MLDEBOA-promobit-69600", ML, "MLDEBOA",
     "ACELERE AGORA: 20% OFF em Acessórios no Mercado Livre (acima de R$79) com cupom", "produtos Mercado Livre",
     P_ML, False),
    ("R3-de-Desconto-em-Perifericos-FERICOS20", KABUM, "FERICOS20", "20% de Desconto em Periféricos",
     "produtos KaBuM! 20% OFF em Periféricos", P_KABUM, False),
    ("R3-em-produtos-de-beleza-GANHEAQUI", AMAZON, "GANHEAQUI", "Desconto Amazon: economize 10% em produtos de beleza",
     "produtos Amazon PARA PRODUTOS SELECIONADOS, TESTE O CUPOM NO CARRINHO", P_AMAZON, False),
    ("R3-produtos-participantes-IMPRIMEJUNTO", KABUM, "IMPRIMEJUNTO",
     "12% de Desconto em produtos participantes da promoção Imprime Junto",
     "produtos KaBuM! 12% OFF em produtos participantes da promoção Imprime Junto", P_KABUM, False),
    # a TV é TCL, mas "produtos TCL participantes" é uma seleção sem dizer se a 55C6K entra: sem alerta falso
    ("R3-produtos-TCL-participantes-TCL10OFF", KABUM, "TCL10OFF", "10% de Desconto em produtos TCL participantes da promoção",
     "produtos KaBuM! 10% OFF em produtos TCL participantes da promoção", P_KABUM, False),
    ("R3-itens-selecionados-com-suas-compras-TECH20", KABUM, "TECH20",
     "Desfrute de 20% OFF em suas compras com o cupom KaBum!",
     "produtos KaBuM! APLICÁVEL A ITENS SELECIONADOS (VERIFIQUE A DISPONIBILIDADE NO LINK)", P_KABUM, False),
    ("R3-produtos-selecionados-da-campanha-PDF04", ALI, "PDF04", "Aproveite R$55 OFF em suas compras com cupom AliExpress",
     "produtos Aliexpress O VOUCHER ATENDE AOS PRODUTOS SELECIONADOS DA CAMPANHA!", P_ALI, False),
    ("R3-em-itens-selecionados-MELITUDOBOM-pelando", ML, "MELITUDOBOM",
     "20% OFF acima R$ 19, limite de R$ 100 em itens selecionados com cupom mercado livre",
     "Excelente cupom - limite de R$ 100", P_ML, False),
    ("R3-produtos-do-link-DESCONTONAREDA-pelando", ML, "DESCONTONAREDA", "18% OFF acima de R$ 79, limite R$ 60 OFF",
     "18% OFF acima de R$ 79, limite R$ 60 OFF válido para produtos do link", P_ML, False),
    ("R3-lista-de-itens-PROMOOFF15", AMAZON, "PROMOOFF15", "Cupom de 15% OFF com desconto máximo de R$ 60 OFF",
     "Lista de itens...", P_AMAZON, False),
    # anúncio cortado ("... de Desconto em" e nada mais): a categoria sumiu; o ENTER15 era de informática
    ("R3-titulo-cortado-em-ENTER15-promobit-69106", KABUM, "ENTER15", "15% de Desconto em", "produtos KaBuM! 15% OFF em",
     P_KABUM, False),
    ("R3-titulo-cortado-em-CONEC50OFF-promobit-69107", KABUM, "CONEC50OFF", "R$50,00 de Desconto em",
     "produtos KaBuM! R$50,00 OFF em", P_KABUM, False),
    # cupom de outro produto (outra TV, um kit), não de uma categoria
    ("R3-outra-Smart-TV-TCL15OFF-P7L", KABUM, "TCL15OFF", "15% de Desconto na Smart TV TCL 50 QLED 4K P7L com Google TV e VRR",
     "produtos KaBuM! 15% OFF na Smart TV TCL 50 QLED 4K P7L com Google TV e VRR", P_KABUM, False),
    ("R3-kit-de-outro-produto-10OFFNOKIT", KABUM, "10OFFNOKIT",
     "Kit Streamer HyperX QuadCast + Cloud Stinger 2 Preto com 10% de Desconto usando o cupom",
     "produtos KaBuM! Kit Streamer HyperX QuadCast + Cloud Stinger 2 Preto com 10% OFF usando o cupom", P_KABUM, False),
    # "em R$ 30" deixou de ser lido como categoria (é o valor mínimo); o "1ª compra" continua recusando este
    ("R3-so-1a-compra-CUPOMNOAPP-pelando", AMAZON, "CUPOMNOAPP", "(1ª Compra / APP) Cupom Amazon oferece R$ 10 OFF em R$ 30",
     "pedido mínimo R$ 30, válido para 1ª compra", P_AMAZON, False),
    # antes aceito; "nas 4 primeiras compras" é cupom de cliente novo (sem alerta falso)
    ("R3-so-primeiras-compras-SEGUNDANOW", AMAZON, "SEGUNDANOW", "A chance de economizar 50% em compras na Amazon",
     "produtos Amazon Aproveite descontos de até 50% ao inserir o cupom na finalização da compra (nas 4 primeiras "
     "compras).", P_AMAZON, False),
    # não pode recusar demais: "em R$ 149" é o valor mínimo, não uma categoria (Shopee, preço genérico)
    ("R3-em-R$-149-e-valor-minimo-COELHONOJAPAOAF", "Shopee", "COELHONOJAPAOAF", "Cupom Shopee oferece R$ 20 OFF em R$ 149",
     "Clique no link do post aqui no pelando para ir direto à página de resgate", 3500.0, True),
    # sintéticos: "participantes" só é seleção quando são produtos/itens; Smart TV de 55" pode ser a própria TV
    ("R3-cartoes-participantes-nao-e-selecao-de-produtos", MAGALU, "X", "Cupom Magalu R$ 200 OFF em suas compras",
     "Válido para pagamento com cartões participantes", P_MAGALU, True),
    ("R3-Smart-TV-de-55-nao-e-outra-TV", MAGALU, "X", "R$ 300 OFF na Smart TV TCL 55 polegadas", "", P_MAGALU, True),
    # ---- exceções da regra geral: a categoria é TV, eletrônicos, tecnologia ou o site todo (têm de ficar aceitos) ----
    ("R3-em-TVs-e-Celulares-selecionados-TVSCOMPRITTAS", ML, "TVSCOMPRITTAS",
     "Cupom Mercado Livre - 15% off  Acima de R$899  limitado à R$150 em TVs e Celulares", "Em itens Selecionados",
     P_ML, True),
    ("R3-em-Tvs-Selecionas-TV100", AMAZON, "TV100", "Cupom de R$ 100 OFF em Tvs Selecionas na Amazon",
     "Algumas tvs com R$ 100 OFF", P_AMAZON, True),
    ("R3-produtos-de-tecnologia-selecionados-ADAMANTIUM", KABUM, "ADAMANTIUM",
     "Garanta 25% de desconto em suas compras com o cupom KaBum!",
     "produtos KaBuM! ATÉ 25% OFF EM PRODUTOS DE TECNOLOGIA SELECIONADOS", P_KABUM, True),
    ("R3-eletronicos-itens-selecionados-ULTRA15", KABUM, "ULTRA15", "Use o cupom KaBum! e economize 15% em suas compras",
     "produtos KaBuM! 15% DE DESCONTO EM ELETRÔNICOS, VÁLIDO PARA ITENS SELECIONADOS", P_KABUM, True),
    ("R3-em-Eletronicos-OFERTAS-promobit-69567", ML, "OFERTAS",
     "Tech em alta: 10% OFF em Eletrônicos no Mercado Livre (acima de R$149) com cupom", "produtos Mercado Livre",
     P_ML, True),
    ("R3-todas-as-categorias-CARRINHOCHEIOJA", ML, "CARRINHOCHEIOJA",
     "TODAS AS CATEGORIAS: 30% OFF no Mercado Livre (acima de R$1) com cupom",
     "produtos Mercado Livre Desconto de até 30% em compra a partir de R$1, excluído o valor do frete, com desconto "
     "máximo de R$500 válido para itens elegíveis.", P_ML, True),
    ("R3-em-seus-pedidos-aplicando-cupom-MLDEBOA-promobit-69475", ML, "MLDEBOA",
     "Economize 20% em seus pedidos aplicando cupom Mercado Livre", "produtos Mercado Livre -", P_ML, True),
    ("R3-em-compras-na-Mercado-Livre-CACIFE12-promobit-69707", ML, "CACIFE12",
     "A chance de economizar 12% em compras na Mercado Livre",
     "produtos Mercado Livre Economize até 12% ao usar o código promocional no carrinho de compras (compra mínima R$55).",
     P_ML, True),
    # "itens elegíveis no link" é o texto padrão do ML para cupom do site todo (não é "produtos do link")
    ("R3-itens-elegiveis-no-link-PEGAMELI-promobit-69415", ML, "PEGAMELI", "Cupom Mercado Livre concede desconto de 22%",
     "produtos Mercado Livre Desconto de até 22% em compra a partir de R$1, excluído o valor do frete, com desconto "
     "máximo de R$500 válido para itens elegíveis no link: https: https://l", P_ML, True),
    ("R3-em-TVs-test_parsers", MAGALU, "Z", "Cupom de desconto Magalu oferece 10% OFF em TVs", "", 3091.0, True),
    ("R3-em-eletronicos-test_parsers", MAGALU, "Z", "Cupom Amazon 10% OFF em eletrônicos", "", 3091.0, True),
    ("R3-Economize-R$30-em-seus-pedidos-MELIUZ", MAGALU, "MELIUZ",
     "Economize R$30 em seus pedidos aplicando cupom Magazine Luiza",
     "produtos Magazine Luiza Economize até R$30 ao usar o código promocional no carrinho de compras (acima de R$250).",
     P_MAGALU, True),
]


def _cupom(loja, codigo, titulo, regra="", fonte="promobit", cid=None, especifico=False):
    return Cupom(fonte=fonte, loja=loja, codigo=codigo, titulo=titulo, url="u", id=cid or f"{codigo}-{titulo[:12]}",
                 regra=regra, especifico=especifico)


@pytest.mark.parametrize("linha", COMPAT, ids=[l[0] for l in COMPAT])
def test_ouro_cupom_compativel(linha):
    _id, loja, codigo, titulo, regra, preco, esperado = linha
    ok, motivo = cupom_compativel(_cupom(loja, codigo, titulo, regra), preco)
    assert ok is esperado, motivo


# ============================================================ 2) cenários: estado + rodada -> alertas/mínimo/histórico

def _grava_state(pasta, modo, minimo=None, ofertas=None, cupons=None):
    """State já existente (não é partida), no formato do repositório antes da rodada 2 (sem 'cupons_alertados')."""
    dados = {"ofertas": ofertas or {}, "cupons": cupons or {}, "minimo": minimo, "saude": {},
             "ultimo_resumo": None, "criado_em": "2026-09-13T15:22:00-03:00"}
    (pasta / f"state_{modo}.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def _minimo(preco, loja=AMAZON):
    return {"preco": preco, "loja": loja, "quando": "2026-09-14T21:08:06-03:00", "url": "u", "titulo": "TCL 55C6K"}


def _reg_oferta(fonte, oid, loja, ultimo):
    return {"fonte": fonte, "id": oid, "tipo": "loja", "loja": loja, "ativo": True, "ultimo_preco": ultimo,
            "menor_preco": ultimo, "preco_alertado": None, "primeira_vez": "2026-09-13T15:22:00-03:00"}


def _rodada(modo, ofertas, cupons=()):
    """A mesma sequência do run.py: sanear -> alertas -> registra/mínimo -> cupons -> histórico -> salva."""
    est = Estado(modo)
    ofertas, _av = sanear(ofertas)
    msgs, alertados = gerar_alertas(est, ofertas, list(cupons))
    diretas = lojas_diretas(ofertas)
    for o in ofertas:
        est.registra_oferta(o, alertados.get(o.chave))
        est.atualiza_minimo(o, diretas)
    for c in cupons:
        est.registra_cupom(c)
    est.anexa_historico([o for o in ofertas if o.tipo == "loja" and o.ativo and o.melhor_preco])
    est.salva()
    return est, msgs


def _ofertas_pc_1709(amazon=4034.5, cb=2189.3):
    """Preços reais do modo pc em 17/09 21:37: a CB trouxe o preço de uma Hisense do carrossel."""
    out = [Oferta("amazon", "loja", AMAZON, "TCL 55C6K", "u", "B0F7JZMVKF", preco=amazon),
           Oferta("mercadolivre", "loja", ML, "TCL 55C6K", "u", "MLB48808732", preco=4169.0),
           Oferta("aliexpress", "loja", ALI, "TCL 55C6K", "u", "1005009459962683", preco=4199.0)]
    if cb:
        out.append(Oferta("casasbahia", "loja", "Casas Bahia", "TCL 55C6K", URL_CB, "55069456", preco=cb,
                          parcelado="6x R$ 795,32 sem juros"))
    return out


def _cab(msgs):
    return [m.split("\n")[0] for m in msgs]


def _codigos(msgs):
    return [c for m in msgs for c in re.findall(r"<code>([^<]+)</code>", m)]


def _ha(dias):
    return (agora() - timedelta(days=dias)).isoformat(timespec="seconds")


def _reg(fonte, cid, loja, codigo, titulo, regra="", especifico=False, primeira=5.0, ultima=None):
    """Registro de cupom como o run.py grava em state['cupons'] (primeira/ultima: dias atrás)."""
    return {"fonte": fonte, "id": cid, "loja": loja, "codigo": codigo, "titulo": titulo, "url": "u", "regra": regra,
            "validade": None, "publicado": None, "especifico": especifico, "chave": f"{fonte}:{cid}",
            "primeira_vez": _ha(primeira), "ultima_vez": _ha(primeira if ultima is None else ultima)}


def _de_reg(reg, **kw):
    campos = {k: reg[k] for k in ("fonte", "loja", "codigo", "titulo", "url", "id", "regra", "especifico")}
    campos.update(kw)
    return Cupom(**campos)


def _por_chave(*regs):
    return {r["chave"]: r for r in regs}


PEL_MELIACHAPROMO = _reg("pelando", "01627720-85c6-4e77-ab35-5e49b007e8e2", ML, "MELIACHAPROMO",
                         "Cupom Mercado Livre - 10% OFF Acima de R$99 limitado à R$300 em Selecionados",
                         "Em Itens Selecionados", primeira=5.1, ultima=3.9)
PROMOBIT_69374 = _reg("promobit", "69374", ML, "MELIACHAPROMO", "A chance de economizar 10% em compras na Mercado Livre",
                      "produtos Mercado Livre Economize até 10% ao usar o código promocional no carrinho de compras "
                      "(compra mínima R$99).", primeira=5.0)
PROMOBIT_69469 = _reg("promobit", "69469", ML, "MELIACHAPROMO",
                      "Cupom de desconto Mercado Livre oferece 10,00% OFF em suas compras",
                      "produtos Mercado Livre Desconto de até 10% em compra a partir de R$99, excluído o valor do "
                      "frete, com desconto máximo de R$300 válido para itens elegíveis.", primeira=5.0)
PEL_PROMOMELI = _reg("pelando", "f07c1dba-68a1-4030-93bb-954eb65a5ae0", ML, "PROMOMELI",
                     "Cupom Mercado Livre - 10% acima de R$149 limitado à R$200 em Tecnologia", "Em itens Selecionados",
                     primeira=5.1)
PROMOBIT_69433 = _reg("promobit", "69433", ML, "PROMOMELI", "A chance de economizar 10% em compras no Mercado Livre",
                      "produtos Mercado Livre -", primeira=5.0)
PEL_ESQUENTA320 = _reg("pelando", "a44fdd07-3363-4c9e-a5ff-088bffddb12a", MAGALU, "ESQUENTA320",
                       "Magalu: Ganhe R$320 OFF em compras acima de R$3.000",
                       "R$320 partir de R$3.000 (válido para itens elegíveis )", primeira=5.1, ultima=3.9)
PROMOBIT_69223 = _reg("promobit", "69223", MAGALU, "ESQUENTA320",
                      "Os melhores itens do site com R$320 OFF aplicando cupom Magazine Luiza",
                      "produtos Magazine Luiza Economize até R$320 ao usar o código promocional no carrinho de compras "
                      "(a partir de R$3.000).", primeira=5.0, ultima=0.3)
LU250 = [_reg("magalu", f"LU250-2026-09-{d}", MAGALU, "LU250", "R$ 250,00 OFF com cupom: LU250",
              "R$ 250,00 OFF com cupom: LU250", especifico=True, primeira=p, ultima=u)
         for d, p, u in (("14", 5.1, 5.0), ("18", 3.9, 2.1), ("16", 2.0, 2.0))]
# DESCONTOEMCASA: o Pelando (modo pc) e o Promobit (modo cloud) em 15-18/09
PEL_DESCONTOEMCASA = _reg("pelando", "30a59912-4c06-43a7-893e-f6d8d25128c6", ML, "DESCONTOEMCASA",
                          "Cupom Mercado Livre oferece 20% OFF, máximo R$ 60, em R$ 79 em Casa",
                          "pedido mínimo R$ 79 na categoria Casa", primeira=3.0, ultima=0.1)
PROMOBIT_69554 = _reg("promobit", "69554", ML, "DESCONTOEMCASA",
                      "ESTILO NOVO: 20% OFF em Casa e Decor no Mercado Livre (acima de R$79) com cupom",
                      "produtos Mercado Livre", primeira=3.0, ultima=0.5)
PROMOBIT_69713 = _reg("promobit", "69713", ML, "DESCONTOEMCASA",
                      "CORRE PRO MELI: 20% OFF no Mercado Livre (acima de R$ 79) com cupom", "produtos Mercado Livre",
                      primeira=0.1)
PROMOBIT_69522 = _reg("promobit", "69522", ML, "DESCONTOJA",
                      "NOVO ESPAÇO: 15% OFF em Casa no Mercado Livre (acima de R$50) com cupom", "produtos Mercado Livre",
                      primeira=2.0, ultima=1.0)
PROMOBIT_69703 = _reg("promobit", "69703", ML, "DESCONTOJA",
                      "OFERTA SURPRESA: 15% OFF em Produtos no Mercado Livre (acima de R$50) com cupom",
                      "produtos Mercado Livre Desconto de até 15% em compra a partir de R$50, excluído o valor do frete, "
                      "com desconto máximo de R$200 válido para itens elegíveis.", primeira=0.5)
PROMOBIT_69600 = _reg("promobit", "69600", ML, "MLDEBOA",
                      "ACELERE AGORA: 20% OFF em Acessórios no Mercado Livre (acima de R$79) com cupom",
                      "produtos Mercado Livre", primeira=1.5, ultima=1.0)
PROMOBIT_69475 = _reg("promobit", "69475", ML, "MLDEBOA", "Economize 20% em seus pedidos aplicando cupom Mercado Livre",
                      "produtos Mercado Livre -", primeira=0.5)


def _esquenta_do_produto(cid="ESQUENTA320-2026-09-25"):
    return Cupom(fonte="magalu", loja=MAGALU, codigo="ESQUENTA320", titulo="R$ 320,00 OFF com cupom: ESQUENTA320",
                 url="https://www.magazineluiza.com.br/x/p/240162800/", id=cid,
                 regra="R$ 320,00 OFF com cupom: ESQUENTA320", validade="2026-09-25T23:59:00-03:00", especifico=True)


def _ml_oferta():
    """Oferta selecionada do ML no snapshot de 18/09 (preço 3.599, Pix 3.491,03)."""
    return Oferta("mercadolivre", "loja", ML, "TCL 55C6K", "u", "MLB5417889802", preco=3599.0, preco_pix=3491.03,
                  vendedor=ML)


# ---- F2 ----

def c_f2_descarte_nao_vira_minimo(d, mp):
    _grava_state(d, "pc", minimo=_minimo(3199.0))
    est, _ = _rodada("pc", _ofertas_pc_1709())
    cb = est.oferta_anterior("casasbahia:55069456")
    return est.minimo()["preco"], cb["ativo"], cb.get("ultimo_preco"), cb.get("menor_preco")


def c_f2_queda_real_leva_trofeu(d, mp):
    _grava_state(d, "pc", minimo=_minimo(3199.0))
    _rodada("pc", _ofertas_pc_1709())
    est, msgs = _rodada("pc", _ofertas_pc_1709(amazon=3100.0, cb=None))
    amazon = [c for c in _cab(msgs) if "Amazon" in c]
    return len(amazon), "🏆 MENOR PREÇO já visto" in amazon[0], "🔻 Queda de preço" in amazon[0], est.minimo()["preco"]


def c_f2_inativa_rodada_isolada(d, mp):
    _grava_state(d, "pc")
    est, msgs = _rodada("pc", [Oferta("amazon", "loja", AMAZON, "TCL 55C6K", "u", "B0F7JZMVKF", preco=2500.0,
                                      ativo=False)])
    return est.minimo(), msgs


def c_f2_registra_inativa_mantem_preco(d, mp):
    _grava_state(d, "pc", ofertas={"casasbahia:55069456": _reg_oferta("casasbahia", "55069456", "Casas Bahia", 3599.09)})
    est = Estado("pc")
    est.registra_oferta(Oferta("casasbahia", "loja", "Casas Bahia", "t", URL_CB, "55069456", preco=2189.3, ativo=False))
    reg = est.oferta_anterior("casasbahia:55069456")
    return reg["ultimo_preco"], reg["menor_preco"], reg["ativo"]


def c_f2_bootstrap_so_ativas(d, mp):
    msg = mensagem_bootstrap([Oferta("casasbahia", "loja", "Casas Bahia", "t", URL_CB, "1", preco=2189.3, ativo=False),
                              Oferta("amazon", "loja", AMAZON, "t", "u", "2", preco=3279.0)], [], "pc")
    return "Amazon" in msg, "Casas Bahia" in msg, "2.189,30" in msg


# ---- F4 ----

def c_f4_historico_sem_descartada(d, mp):
    _grava_state(d, "pc", minimo=_minimo(3199.0))
    _rodada("pc", _ofertas_pc_1709())
    linhas = list(csv.DictReader((d / "historico_pc.csv").open(encoding="utf-8")))
    return sorted((r["loja"], r["preco"]) for r in linhas)


def c_f4_anexa_historico_filtra(d, mp):
    Estado("pc").anexa_historico([
        Oferta("amazon", "loja", AMAZON, "t", "u", "1", preco=4034.5),
        Oferta("casasbahia", "loja", "Casas Bahia", "t", URL_CB, "2", preco=2189.3, ativo=False),
        Oferta("aliexpress", "loja", ALI, "t", "u", "3")])
    return [(r["loja"], r["preco"]) for r in csv.DictReader((d / "historico_pc.csv").open(encoding="utf-8"))]


# ---- F5 ----

def _pc_com_amazon(d, cloud=True):
    if cloud:
        _grava_state(d, "cloud", minimo=_minimo(2991.6, MAGALU))
    _grava_state(d, "pc", minimo=_minimo(3199.0),
                 ofertas={"amazon:B0F7JZMVKF": _reg_oferta("amazon", "B0F7JZMVKF", AMAZON, 3279.0)})
    return Estado("pc")


def _amazon(preco):
    return Oferta("amazon", "loja", AMAZON, "TCL 55C6K", "u", "B0F7JZMVKF", preco=preco, vendedor="Magalu.")


def c_f5_3150_sem_trofeu(d, mp):
    msgs, _ = gerar_alertas(_pc_com_amazon(d), [_amazon(3150.0)], [])
    return "🔻 Queda de preço" in _cab(msgs)[0], any("🏆" in c for c in _cab(msgs))


def c_f5_2950_com_trofeu(d, mp):
    msgs, _ = gerar_alertas(_pc_com_amazon(d), [_amazon(2950.0)], [])
    return any("🏆 MENOR PREÇO já visto" in c for c in _cab(msgs))


def c_f5_sem_outro_modo_usa_o_proprio(d, mp):
    msgs, _ = gerar_alertas(_pc_com_amazon(d, cloud=False), [_amazon(3150.0)], [])
    return any("🏆" in c for c in _cab(msgs))


def c_f5_resumo_menor_dos_dois_modos(d, mp):
    _grava_state(d, "pc", minimo=_minimo(3199.0))
    _grava_state(d, "cloud", minimo=_minimo(2991.6, MAGALU))
    esperado = "Menor já visto: R$ 2.991,60 (Magazine Luiza"
    return esperado in resumo_diario(Estado("cloud"), [], []), esperado in resumo_diario(Estado("pc"), [], [])


# ---- F9 ----

def c_f9_lu250_nova_data(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(*LU250))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_de_reg(LU250[2], id="LU250-2026-09-20")])
    return msgs


def c_f9_promomeli_outro_post(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(PEL_PROMOMELI, PROMOBIT_69433))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_de_reg(PROMOBIT_69433, id="69999")])
    return msgs


def c_f9_mensagem_cortada_nao_conta(d, mp):
    """Rodada 2: a mensagem de cupons cortada pelo limite (MAX_ALERTAS) não conta como alertada."""
    import run

    _grava_state(d, "cloud", cupons=_por_chave(*LU250))
    est = Estado("cloud")
    msgs, _ = gerar_alertas(est, [], [_de_reg(PROMOBIT_69374)])
    run.limita_alertas(["⚠️ aviso"] * 15 + msgs, est, 15)
    est.salva()
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_de_reg(PROMOBIT_69469)])
    return _codigos(msgs)


def c_f9_partida_anuncia_aplicaveis(d, mp):
    """Rodada 2: na partida os cupons aplicáveis ficam como anunciados; o que a partida recusou ainda alerta."""
    amazon = Oferta("amazon", "loja", AMAZON, "TCL 55C6K", "u", "B0F7JZMVKF", preco=3279.0)
    est, msgs1 = _rodada("cloud", [amazon], [_de_reg(PEL_PROMOMELI), _de_reg(PEL_MELIACHAPROMO)])
    origens = [a["origem"] for a in est.dados["cupons_alertados"].get("Mercado Livre|PROMOMELI", [])]
    _est, msgs2 = _rodada("cloud", [amazon], [_de_reg(PROMOBIT_69433), _de_reg(PROMOBIT_69374)])
    return msgs1, origens, _codigos(msgs2)


# ---- REG-1 e REG-2 (rodada 1) ----

def c_reg1_so_visto_no_pelando_alerta(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(PEL_MELIACHAPROMO))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_de_reg(PROMOBIT_69374)])
    return _cab(msgs), _codigos(msgs)


def c_reg1_repost_mesmo_desconto_nao_repete(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(PEL_MELIACHAPROMO))
    _rodada("cloud", [], [_de_reg(PROMOBIT_69374)])
    _est, msgs = _rodada("cloud", [], [_de_reg(PROMOBIT_69469)])
    return msgs


def c_reg1_desconto_mudou_alerta(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(PEL_MELIACHAPROMO))
    _rodada("cloud", [], [_de_reg(PROMOBIT_69374)])
    _est, msgs = _rodada("cloud", [], [_de_reg(PROMOBIT_69374, id="69999",
                                               titulo="A chance de economizar 15% em compras na Mercado Livre")])
    return _codigos(msgs)


def c_reg1_sequencia_real_13_09(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(PEL_MELIACHAPROMO, PEL_PROMOMELI))
    _est, m1 = _rodada("cloud", [], [_de_reg(PROMOBIT_69374), _de_reg(PROMOBIT_69469), _de_reg(PROMOBIT_69433)])
    _est, m2 = _rodada("cloud", [], [_de_reg(PROMOBIT_69374, id="69504")])
    return _codigos(m1), m2


def c_reg2_pagina_do_produto_alerta(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(PEL_ESQUENTA320, PROMOBIT_69223))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_esquenta_do_produto()])
    return _codigos(msgs), "⭐" in msgs[0], "cupom do produto" in msgs[0]


def c_reg2_site_depois_produto(d, mp):
    _grava_state(d, "cloud")
    _e, m1 = _rodada("cloud", [], [_de_reg(PROMOBIT_69223)])
    _e, m2 = _rodada("cloud", [], [_esquenta_do_produto()])
    _e, m3 = _rodada("cloud", [], [_esquenta_do_produto("ESQUENTA320-2026-09-30"), _de_reg(PROMOBIT_69223, id="69998")])
    return _codigos(m1), "⭐" in m2[0], m3


def c_reg2_recusado_pela_regra_da_epoca_alerta(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(PEL_ESQUENTA320, PROMOBIT_69223))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_de_reg(PROMOBIT_69223, id="69998")])
    return _codigos(msgs)


# ---- F3 no painel ----

def c_f3_cupons_aplicaveis_magalu(d, mp):
    magalu = Oferta("magalu", "loja", MAGALU, "TCL 55C6K", "u", "240162800-magazineluiza", preco=3749.0,
                    preco_pix=3561.55)
    cs = [_cupom(*l[1:5]) for l in COMPAT if l[2] in ("INFLU300", "RODEIO220", "INFLU25")]
    return [c.codigo for c in cupons_aplicaveis([magalu], cs)]


# ---- regressão da rodada 2: DESCONTOEMCASA ----

def c_r2_descontoemcasa_fora_do_painel(d, mp):
    return [c.codigo for c in cupons_aplicaveis([_ml_oferta()], [_de_reg(PEL_DESCONTOEMCASA)])]


def c_r2_descontoemcasa_novo_id_pelando_pc(d, mp):
    _grava_state(d, "pc", cupons=_por_chave(PEL_DESCONTOEMCASA))
    msgs, _ = gerar_alertas(Estado("pc"), [_ml_oferta()], [_de_reg(PEL_DESCONTOEMCASA, id="novo-id-do-pelando")])
    return [m for m in msgs if "🎟️" in m]


class _FonteFake:
    nome = "pelando.cupons"
    modo = "pc"
    alerta_falha = True

    def coletar(self):
        return [_ml_oferta()], [_de_reg(PEL_DESCONTOEMCASA, id="novo-id-do-pelando")]


def c_r2_descontoemcasa_run_main_pc(d, mp):
    """O verificador rodou run.main() no modo pc: saía '🎟️ Novo cupom aplicável à TV • Mercado Livre DESCONTOEMCASA'."""
    import io

    import run
    from monitor import sources

    _grava_state(d, "pc", minimo=_minimo(3199.0), cupons=_por_chave(PEL_DESCONTOEMCASA),
                 ofertas={"mercadolivre:MLB5417889802": _reg_oferta("mercadolivre", "MLB5417889802", ML, 3491.03)})
    mp.setattr(run, "carrega_env", lambda: None)  # nunca lê .env
    mp.setattr(sources, "por_modo", lambda modo: [_FonteFake()])
    mp.setattr(run.time, "sleep", lambda s: None)
    mp.setattr(sys, "argv", ["run.py", "--mode", "pc", "--no-notify"])
    saida = io.StringIO()
    mp.setattr(sys, "stdout", saida)
    assert run.main() == 0
    latest = json.loads((d / "latest_pc.json").read_text(encoding="utf-8"))
    alertas = [b for b in saida.getvalue().split("[alerta]") if "🎟️" in b]
    return alertas, [c["codigo"] for c in latest["cupons"]]


# ---- rodada 3: o código que um anúncio diz ser de uma categoria não vira alerta por outro anúncio genérico ----

def c_r3_descontoemcasa_promobit_generico(d, mp):
    """Cloud: o Promobit 69554 diz 'em Casa e Decor'; o 69713 do mesmo código tem título genérico."""
    _grava_state(d, "cloud", cupons=_por_chave(PROMOBIT_69554))
    est = Estado("cloud")
    novo = _de_reg(PROMOBIT_69713)
    msgs, _ = gerar_alertas(est, [_ml_oferta()], [novo])
    return msgs, [c.codigo for c in cupons_aplicaveis([_ml_oferta()], [novo], est)]


def c_r3_descontoemcasa_mesma_rodada(d, mp):
    _grava_state(d, "cloud")
    cs = [_de_reg(PROMOBIT_69713), _de_reg(PROMOBIT_69554)]
    msgs, _ = gerar_alertas(Estado("cloud"), [_ml_oferta()], cs)
    return msgs, [c.codigo for c in cupons_aplicaveis([_ml_oferta()], cs)]


def c_r3_descontoja_promobit_generico(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(PROMOBIT_69522))
    msgs, _ = gerar_alertas(Estado("cloud"), [_ml_oferta()], [_de_reg(PROMOBIT_69703)])
    return msgs


def c_r3_mldeboa_promobit_generico(d, mp):
    _grava_state(d, "cloud", cupons=_por_chave(PROMOBIT_69600))
    msgs, _ = gerar_alertas(Estado("cloud"), [_ml_oferta()], [_de_reg(PROMOBIT_69475)])
    return msgs


def c_r3_mldeboa_sem_o_post_da_categoria_alerta(d, mp):
    """Sem nenhum anúncio dizendo a categoria, o texto genérico serve (é o caso do MELIACHAPROMO da REG-1)."""
    _grava_state(d, "cloud")
    msgs, _ = gerar_alertas(Estado("cloud"), [_ml_oferta()], [_de_reg(PROMOBIT_69475)])
    return _codigos(msgs)


def _codigo_generico_depois_de(d, anterior, novo):
    _grava_state(d, "cloud", cupons=_por_chave(anterior))
    msgs, _ = gerar_alertas(Estado("cloud"), [_ml_oferta()], [_de_reg(novo)])
    return _codigos(msgs)


def c_r3_cacife12(d, mp):
    pel = _reg("pelando", "d9cd1559-d020-4e68-bc7a-22750d770d19", ML, "CACIFE12",
               "Cupom Mercado Livre - 12% off  Acima de R$55 limitado à R$100 em Selecionados Cacife",
               "Em Itens Selecionados", primeira=2.0)
    pb = _reg("promobit", "69707", ML, "CACIFE12", "A chance de economizar 12% em compras na Mercado Livre",
              "produtos Mercado Livre Economize até 12% ao usar o código promocional no carrinho de compras "
              "(compra mínima R$55).", primeira=0.5)
    return _codigo_generico_depois_de(d, pel, pb)


def c_r3_compraml_slogan_nao_barra(d, mp):
    slogan = _reg("promobit", "69600x", ML, "COMPRAML",
                  "MERCADO EM ALTA: 22% OFF em ofertas no Mercado Livre (acima de R$1) com cupom", "produtos Mercado Livre",
                  primeira=2.0)
    generico = _reg("promobit", "69601x", ML, "COMPRAML",
                    "Faça compras com cupom de desconto Mercado Livre e economize 22,00%", "produtos Mercado Livre",
                    primeira=0.5)
    return _codigo_generico_depois_de(d, slogan, generico)


def c_r3_vipaqui_selecionados_com_valor_nao_barra(d, mp):
    pel = _reg("pelando", "vipaqui-pelando", ML, "VIPAQUI",
               "Cupom 25% OFF no Mercado Livre em selecionados acima R$1 - Limite R$500",
               "Aplique o cupom na página de cupons ao invés de tentar diretamente em um produto ou no carrinho de compras",
               primeira=2.0)
    pb = _reg("promobit", "vipaqui-promobit", ML, "VIPAQUI", "Compre com código promocional Mercado Livre e economize 25,00%",
              "produtos Mercado Livre", primeira=0.5)
    return _codigo_generico_depois_de(d, pel, pb)


def c_r3_saindobarrato_selecao_nao_barra(d, mp):
    selecao = _reg("promobit", "sb-1", ML, "SAINDOBARRATO",
                   "DESCONTOS IMPERDÍVEIS: Cupom 30% OFF na Seleção Mercado Livre (Compra mínima R$1)",
                   "produtos Mercado Livre", primeira=2.0)
    generico = _reg("promobit", "sb-2", ML, "SAINDOBARRATO", "Use cupom Mercado Livre e tenha desconto de 30%",
                    "produtos Mercado Livre", primeira=0.5)
    return _codigo_generico_depois_de(d, selecao, generico)


def c_r3_categoria_vista_ha_mais_de_30_dias_nao_conta(d, mp):
    velho = dict(PROMOBIT_69600, primeira_vez=_ha(60), ultima_vez=_ha(45))
    _grava_state(d, "cloud", cupons=_por_chave(velho))
    msgs, _ = gerar_alertas(Estado("cloud"), [_ml_oferta()], [_de_reg(PROMOBIT_69475)])
    return _codigos(msgs)


def c_r3_pagina_do_produto_nao_e_barrada(d, mp):
    """Cupom da página da TV (especifico) vale para a TV mesmo que um anúncio do código fale de outra categoria."""
    outro = _reg("promobit", "70001", MAGALU, "ESQUENTA320", "20% OFF em Moda na Magalu", "produtos Magazine Luiza",
                 primeira=1.0)
    _grava_state(d, "cloud", cupons=_por_chave(outro))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_esquenta_do_produto()])
    return _codigos(msgs)


CENARIOS = [
    # F2: o sanear descarta a CB 2.189,30; o mínimo continua 3.199 e a CB não grava último/menor preço
    ("F2-descarte-do-sanear-nao-vira-minimo", c_f2_descarte_nao_vira_minimo, (3199.0, False, None, None)),
    # F2: a queda real da Amazon para 3.100 (abaixo de 3.199) leva o troféu junto com a queda
    ("F2-Amazon-3100-leva-trofeu-e-queda", c_f2_queda_real_leva_trofeu, (1, True, True, 3100.0)),
    ("F2-inativa-2500-em-rodada-isolada-nao-vira-minimo", c_f2_inativa_rodada_isolada, (None, [])),
    ("F2-registra-oferta-inativa-mantem-3599.09", c_f2_registra_inativa_mantem_preco, (3599.09, 3599.09, False)),
    ("F2-mensagem-de-partida-so-lista-ativas", c_f2_bootstrap_so_ativas, (True, False, False)),
    ("F4-historico-sem-a-CB-descartada", c_f4_historico_sem_descartada,
     [(ALI, "4199.0"), (AMAZON, "4034.5"), (ML, "4169.0")]),
    ("F4-anexa-historico-tira-inativa-e-sem-preco", c_f4_anexa_historico_filtra, [(AMAZON, "4034.5")]),
    # F5: pc 3.199, cloud 2.991,60 (legítimo: Magalu/Fast Shop Pix). Amazon a 3.150: queda sem troféu
    ("F5-pc-3150-contra-cloud-2991.60-sem-trofeu", c_f5_3150_sem_trofeu, (True, False)),
    ("F5-pc-2950-com-trofeu", c_f5_2950_com_trofeu, True),
    ("F5-sem-arquivo-do-outro-modo-usa-o-proprio", c_f5_sem_outro_modo_usa_o_proprio, True),
    ("F5-resumo-diario-mostra-o-menor-dos-dois-modos", c_f5_resumo_menor_dos_dois_modos, (True, True)),
    ("F9-LU250-com-nova-data-no-id-nao-realerta", c_f9_lu250_nova_data, []),
    ("F9-PROMOMELI-em-outro-post-nao-realerta", c_f9_promomeli_outro_post, []),
    ("F9-mensagem-cortada-pelo-limite-nao-conta-como-alertada", c_f9_mensagem_cortada_nao_conta, ["MELIACHAPROMO"]),
    ("F9-partida-anuncia-aplicaveis-e-recusado-alerta-depois", c_f9_partida_anuncia_aplicaveis,
     ([], ["partida"], ["MELIACHAPROMO"])),
    ("REG1-so-visto-e-recusado-no-Pelando-ainda-alerta", c_reg1_so_visto_no_pelando_alerta,
     (["🎟️ <b>Novo cupom aplicável à TV</b>"], ["MELIACHAPROMO"])),
    ("REG1-depois-de-alertado-repost-com-10pct-nao-repete", c_reg1_repost_mesmo_desconto_nao_repete, []),
    ("REG1-depois-de-alertado-15pct-alerta", c_reg1_desconto_mudou_alerta, ["MELIACHAPROMO"]),
    ("REG1-sequencia-real-de-13-09", c_reg1_sequencia_real_13_09, (["MELIACHAPROMO"], [])),
    ("REG2-ESQUENTA320-da-pagina-do-produto-alerta-com-estrela", c_reg2_pagina_do_produto_alerta,
     (["ESQUENTA320"], True, True)),
    ("REG2-site-alertado-depois-produto-alerta-depois-silencio", c_reg2_site_depois_produto, (["ESQUENTA320"], True, [])),
    ("REG2-visto-mas-recusado-pela-regra-da-epoca-alerta", c_reg2_recusado_pela_regra_da_epoca_alerta, ["ESQUENTA320"]),
    ("F3-cupons_aplicaveis-Magalu-3749-Pix-3561.55", c_f3_cupons_aplicaveis_magalu, ["INFLU300", "RODEIO220", "INFLU25"]),
    ("R2-DESCONTOEMCASA-fora-de-cupons_aplicaveis", c_r2_descontoemcasa_fora_do_painel, []),
    ("R2-DESCONTOEMCASA-novo-id-do-Pelando-no-pc-nao-alerta", c_r2_descontoemcasa_novo_id_pelando_pc, []),
    ("R2-DESCONTOEMCASA-run.main-pc-sem-alerta-e-fora-do-latest", c_r2_descontoemcasa_run_main_pc, ([], [])),
    ("R3-DESCONTOEMCASA-promobit-69713-generico-com-69554-Casa-no-estado", c_r3_descontoemcasa_promobit_generico,
     ([], [])),
    ("R3-DESCONTOEMCASA-69713-e-69554-na-mesma-rodada", c_r3_descontoemcasa_mesma_rodada, ([], [])),
    ("R3-DESCONTOJA-promobit-69703-generico-com-69522-Casa-no-estado", c_r3_descontoja_promobit_generico, []),
    ("R3-MLDEBOA-promobit-69475-generico-com-69600-Acessorios-no-estado", c_r3_mldeboa_promobit_generico, []),
    ("R3-MLDEBOA-69475-sem-anuncio-da-categoria-alerta", c_r3_mldeboa_sem_o_post_da_categoria_alerta, ["MLDEBOA"]),
    # "Selecionados Cacife" nomeia a seleção (como "Selecionados Garnier/Moda/Full"): entre não perder um cupom que
    # talvez sirva e não mandar alerta falso, fica sem alerta (as ofertas reais chegam pelos preços e posts)
    ("R3-CACIFE12-promobit-69707-com-Selecionados-Cacife-no-estado", c_r3_cacife12, []),
    # REG-1 continua valendo: seleção vaga, slogan e condição de valor em outro anúncio não barram o código
    ("R3-COMPRAML-slogan-MERCADO-EM-ALTA-nao-barra-o-codigo", c_r3_compraml_slogan_nao_barra, ["COMPRAML"]),
    ("R3-VIPAQUI-em-selecionados-acima-R$1-Limite-R$500-nao-barra", c_r3_vipaqui_selecionados_com_valor_nao_barra,
     ["VIPAQUI"]),
    ("R3-SAINDOBARRATO-Selecao-Mercado-Livre-nao-barra", c_r3_saindobarrato_selecao_nao_barra, ["SAINDOBARRATO"]),
    ("R3-categoria-vista-ha-mais-de-30-dias-nao-barra", c_r3_categoria_vista_ha_mais_de_30_dias_nao_conta, ["MLDEBOA"]),
    ("R3-cupom-da-pagina-do-produto-nao-e-barrado", c_r3_pagina_do_produto_nao_e_barrada, ["ESQUENTA320"]),
]


@pytest.mark.parametrize("linha", CENARIOS, ids=[l[0] for l in CENARIOS])
def test_ouro_cenario(linha, dados_tmp, monkeypatch):
    _id, cenario, esperado = linha
    assert cenario(dados_tmp, monkeypatch) == esperado


# ============================================================ 3) snapshots reais das páginas (18/09/2026)

def _snap(nome: str) -> str:
    arq = SNAP / nome
    if not arq.exists():
        pytest.skip(f"snapshot {nome} não está nesta máquina")
    return arq.read_text(encoding="utf-8")


def _cb_do_snapshot(mp):
    from monitor.sources import playwright_sources as ps

    html, texto = _snap("casasbahia_produto.html"), _snap("casasbahia_produto.txt")
    mp.setattr(ps, "_abrir", lambda *a, **k: (html, texto, []))
    ofertas, cupons = ps.CasasBahia().coletar()
    assert len(ofertas) == 1 and cupons == []
    return ofertas[0]


def _ml_do_snapshot(d, mp):
    from monitor.sources import playwright_sources as ps

    html, texto = _snap("mercadolivre_produto.html"), _snap("mercadolivre_produto.txt")
    mp.setattr(ps, "MARCA_BLOQUEIO_ML", d / "ml_bloqueado_em")  # nunca mexe em logs/
    mp.setattr(ps, "_abrir", lambda *a, **k: (html, texto, []))
    ofertas, cupons = ps.MercadoLivre().coletar()
    assert cupons == []
    sel = ps._ml_oferta_selecionada(html).get("item_id")
    return ofertas, [o for o in ofertas if o.id == sel][0]


def _amazon_do_snapshot(disponibilidade=None):
    from monitor.sources import amazon

    html = _snap("amazon_produto.html")
    if disponibilidade:
        assert " Em estoque " in html
        html = html.replace(" Em estoque ", f" {disponibilidade} ", 1)
    return amazon.parse_produto(html)


def s_cb(d, mp):
    o = _cb_do_snapshot(mp)
    return o.preco, o.preco_pix, o.parcelado, o.vendedor, o.ativo


def s_ml(d, mp):
    _todas, o = _ml_do_snapshot(d, mp)
    return o.id, o.preco, o.preco_pix, o.melhor_preco, o.vendedor, o.ativo


def s_amazon_indisponivel(d, mp):
    """F2: com '#availability' = 'Temporariamente indisponível.' o parser devolve preço com ativo=False."""
    o = _amazon_do_snapshot("Temporariamente indisponível.")
    est = Estado("pc")  # sem state: o primeiro preço ativo viraria o mínimo
    return o.preco, o.ativo, est.atualiza_minimo(o), est.minimo()


def s_sanear_mantem_precos_reais(d, mp):
    """Os preços reais de 18/09 não podem ser descartados nem perder o parcelado."""
    cb = _cb_do_snapshot(mp)
    ml_todas, _sel = _ml_do_snapshot(d, mp)
    amz = _amazon_do_snapshot()
    ofertas, avisos = sanear([cb, amz] + ml_todas)
    return avisos, [o.ativo for o in ofertas], cb.parcelado, amz.parcelado


def s_rodada_real_minimo(d, mp):
    """Rodada pc com as páginas reais: o novo menor preço é o Pix do ML (3.491,03) e leva o troféu."""
    _grava_state(d, "pc", minimo=_minimo(3599.09, "Casas Bahia"))
    cb = _cb_do_snapshot(mp)
    ml_todas, _sel = _ml_do_snapshot(d, mp)
    est, msgs = _rodada("pc", [cb, _amazon_do_snapshot()] + ml_todas)
    trofeu = [c for c in _cab(msgs) if "🏆" in c]
    return est.minimo()["preco"], est.minimo()["loja"], len(trofeu), ML in trofeu[0]


def s_descontoemcasa_contra_o_preco_real(d, mp):
    _todas, o = _ml_do_snapshot(d, mp)
    return cupom_compativel(_de_reg(PEL_DESCONTOEMCASA), o.melhor_preco)[0]


SNAPSHOTS = [
    ("SNAP-CasasBahia-preco-3998.99-pix-3599.09-10x-399.90", s_cb,
     (3998.99, 3599.09, "10x R$ 399,90 sem juros (cartão Casas Bahia)", "Casas Bahia", True)),
    ("SNAP-MercadoLivre-selecionada-preco-3599-pix-3491.03", s_ml,
     ("MLB5417889802", 3599.0, 3491.03, 3491.03, ML, True)),
    ("SNAP-F2-Amazon-indisponivel-com-preco-nao-vira-minimo", s_amazon_indisponivel, (3749.0, False, False, None)),
    ("SNAP-sanear-mantem-os-precos-reais", s_sanear_mantem_precos_reais,
     ([], [True, True, True, True], "10x R$ 399,90 sem juros (cartão Casas Bahia)", "12x R$ 312,49 sem juros")),
    ("SNAP-rodada-pc-real-minimo-3491.03-do-ML-com-trofeu", s_rodada_real_minimo, (3491.03, ML, 1, True)),
    ("SNAP-R2-DESCONTOEMCASA-contra-o-Pix-real-do-ML", s_descontoemcasa_contra_o_preco_real, False),
]


@pytest.mark.parametrize("linha", SNAPSHOTS, ids=[l[0] for l in SNAPSHOTS])
def test_ouro_snapshot(linha, dados_tmp, monkeypatch):
    _id, cenario, esperado = linha
    assert cenario(dados_tmp, monkeypatch) == esperado
