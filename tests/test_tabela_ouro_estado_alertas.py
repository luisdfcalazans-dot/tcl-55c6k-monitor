"""Tabela de ouro do grupo estado-alertas (rodadas 3 e 4).

Um caso por exemplo concreto: a evidência dos achados F2, F3, F4, F5 e F9, todas as regressões das rodadas 1, 2 e 3
(REG-1, REG-2, DESCONTOEMCASA; TVMAGALU300, MELI15TUDO, TVKABUM10, SMARTTV250, PIX300, TCLTV250, CBFRETE200,
APPMAGALU350, DESCONTOJA no pc), o item ZOOM e os casos que os verificadores disseram que têm de continuar funcionando.
Linhas "R4b-*" (2ª passada da rodada 4): as entradas exatas com que o verificador mostrou o branch pior que a main
(lista de tamanhos com polegada, teto do item/da compra, "Renovados"/"Recondicionados", cliente novo no app) e as
rodadas E1-E8 dele com os arquivos reais.
Linhas "R5-*" (passada final, lista fechada E1-E5 do veredito final da rodada 4): número que não é tamanho depois de
"Smart TV(s)", cupom progressivo (menor mínimo), cliente novo só com as palavras explícitas, exclusão de OUTRAS TVs, e
cupom de loja oficial/marca/outra loja; com as entradas exatas do veredito e as rodadas com os arquivos reais.
Cada linha é entrada -> saída esperada (aceita/recusa, preço, parcelado, alerta sai ou não). Quando uma expectativa
antiga e uma nova conflitam, vale a do verificador mais recente; o comentário da linha diz por quê.

Textos de cupom: reais, dos state_*.json de 13 a 18/09/2026 (o id do anúncio vai no nome da linha quando ajuda), ou
os exemplos exatos dos arquivos de correção. Nada aqui lê ou escreve docs/data: os dados reais da main (8e21e6d) vêm
do recorte tests/fixtures/dados_8e21e6d.json. Os snapshots reais das páginas só são lidos; sem eles a linha é pulada.
"""

import csv
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from monitor import config, util
from monitor.estado import Estado, e_agregador
from monitor.models import Cupom, Oferta
from monitor.regras import (
    cupom_compativel, cupons_aplicaveis, gerar_alertas, mensagem_bootstrap, restricao_do_codigo, resumo_diario, sanear,
)
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
    # ---- rodada 4: regressões da rodada 3 (exemplos exatos do arquivo de correção; a main aceita e alerta todos) ----
    # (a) exclusão não é o escopo: "Não válido para a categoria Celulares" / "exceto na categoria Supermercado"
    ("R4-TVMAGALU300-nao-valido-para-Celulares", MAGALU, "TVMAGALU300",
     "Cupom Magalu R$ 300 OFF em TVs acima de R$ 3.000", "Não válido para a categoria Celulares.", P_MAGALU, True),
    ("R4-TVMAGALU300-promobit-limpo", MAGALU, "TVMAGALU300",
     "Cupom de desconto Magazine Luiza oferece R$ 300 OFF em TVs", "", P_MAGALU, True),
    ("R4-MELI15TUDO-site-todo-exceto-Supermercado", ML, "MELI15TUDO",
     "Cupom Mercado Livre 15% OFF em todo o site (limite R$ 150)",
     "Válido em todo o site, exceto na categoria Supermercado. Compra mínima R$ 199.", P_ML, True),
    # (b) todos os alvos contam; "promoção", "oferta" e "Pix" são neutros
    ("R4-TVKABUM10-TVs-em-promocao", KABUM, "TVKABUM10", "Cupom KaBuM! 10% OFF em TVs em promoção",
     "produtos KaBuM! 10% OFF em TVs em promoção", P_KABUM, True),
    ("R4-SMARTTV250-Smart-TVs-em-oferta", MAGALU, "SMARTTV250", "Cupom Magalu R$ 250 OFF em Smart TVs em oferta", "",
     P_MAGALU, True),
    ("R4-PIX300-pagamento-em-Pix", MAGALU, "PIX300", "Cupom Magalu de R$ 300 para pagamento em Pix",
     "Válido em compras acima de R$ 3.000", P_MAGALU, True),
    # (c) lista de tamanhos com o 55
    ("R4-TCLTV250-Smart-TV-TCL-50-55-e-65", AMAZON, "TCLTV250",
     "Cupom Amazon R$ 250 OFF em Smart TV TCL 50, 55 e 65 polegadas", "Válido para TVs vendidas pela Amazon.", P_AMAZON,
     True),
    # (d) frete e app não são categorias
    ("R4-CBFRETE200-OFF-mais-frete-gratis", "Casas Bahia", "CBFRETE200",
     "Cupom Casas Bahia: R$ 200 OFF + Frete Grátis em compras acima de R$ 1.999",
     "Aplique o cupom no carrinho. Limitado a 1 uso por CPF.", 3599.09, True),
    ("R4-APPMAGALU350-usar-no-app", MAGALU, "APPMAGALU350", "Cupom Magalu com R$ 350 OFF para usar no app",
     "produtos Magazine Luiza Use o código no app em compras acima de R$ 3.000.", P_MAGALU, True),
    # o anúncio do Pelando do DESCONTOJA é genérico: sozinho ele serve; quem o barra é o outro modo (ver cenários R4)
    ("R4-DESCONTOJA-pelando-generico-sozinho-serve", ML, "DESCONTOJA",
     "Cupom Mercado Livre 15% OFF acima de R$ 50 (limi R$ 200 OFF)",
     "Cupom Mercado Livre 15% OFF acima de R$ 50 (limi R$ 200 OFF)", P_ML, True),
    # ---- rodada 4, 2ª passada: o verificador achou entradas em que a 1ª passada ficava PIOR que a main ----
    # R3-3 não resolvido / regressão 1: a mesma lista de tamanhos escrita com polegada (", '', pol.) ou sem vírgula.
    # A main aceita e alerta todas; a 55" está na lista ou na faixa
    ("R4b-TCLTV250-50-55-65-com-aspas-regra-vazia", AMAZON, "TCLTV250",
     'Cupom Amazon R$ 250 OFF em Smart TV TCL 50", 55" e 65"', "", P_AMAZON, True),
    ("R4b-TCLTV250-50-55-65-com-aspas-e-regra", AMAZON, "TCLTV250",
     'Cupom Amazon R$ 250 OFF em Smart TV TCL 50", 55" e 65"', "Válido para TVs vendidas pela Amazon.", P_AMAZON, True),
    ("R4b-TVGRANDE300-Smart-TVs-de-50-a-65-com-aspas", MAGALU, "TVGRANDE300",
     'Cupom Magalu R$ 300 OFF em Smart TVs de 50" a 65"', "", P_MAGALU, True),
    ("R4b-Smart-TVs-43-a-55-com-aspas", KABUM, "X", 'Cupom 10% OFF em Smart TVs 43" a 55"', "", P_KABUM, True),
    ("R4b-Smart-TVs-50-ou-55-com-aspas", "Casas Bahia", "X", 'Cupom Casas Bahia R$ 200 OFF em Smart TVs 50" ou 55"', "",
     3599.09, True),
    ("R4b-Smart-TVs-50-a-65-com-aspas-simples-dobradas", MAGALU, "X", "Cupom Magalu R$ 300 OFF em Smart TVs 50'' a 65''",
     "", P_MAGALU, True),
    ("R4b-Smart-TV-TCL-50-55-65-com-barras", AMAZON, "X", 'Cupom Amazon R$ 250 OFF em Smart TV TCL 50" / 55" / 65"', "",
     P_AMAZON, True),
    ("R4b-Smart-TVs-50-pol-a-65-pol", MAGALU, "X", "Cupom Magalu R$ 300 OFF em Smart TVs 50 pol. a 65 pol.", "", P_MAGALU,
     True),
    ("R4b-Smart-TV-TCL-50-55-e-65-sem-virgula", AMAZON, "X",
     "Cupom Amazon R$ 250 OFF em Smart TV TCL 50 55 e 65 polegadas", "", P_AMAZON, True),
    ("R4b-Smart-TV-TCL-50-e-55-C6K", AMAZON, "X", 'Cupom Amazon R$ 250 OFF em Smart TV TCL 50" e 55" C6K', "", P_AMAZON,
     True),
    # os mesmos formatos sem o 55 continuam fora (outra TV); "TVs de 43 polegadas" era aceito pela main (pré-existente)
    ("R4b-Smart-TVs-de-32-e-43-com-aspas-fora", KABUM, "X", 'Cupom KaBuM! R$ 100 OFF em Smart TVs de 32" e 43"', "",
     P_KABUM, False),
    ("R4b-Smart-TVs-65-ou-maiores-fora", AMAZON, "X", 'Cupom Amazon R$ 400 OFF em Smart TVs 65" ou maiores', "", P_AMAZON,
     False),
    ("R4b-TVs-de-43-polegadas-fora", MAGALU, "X", "Cupom Magalu R$ 100 OFF em TVs de 43 polegadas", "", P_MAGALU, False),
    ("R4b-Smart-TVs-10pct-OFF-nao-e-tamanho", MAGALU, "X", "Cupom Magalu Smart TVs 10% OFF", "", P_MAGALU, True),
    # regressão 2: teto do ITEM/da compra (a main recusa 'só até R$ X'; a 1ª passada aceitava = alerta falso)
    ("R4b-ATE500-produtos-ate-R$500-KaBuM", KABUM, "ATE500", "Use o cupom KaBum! e economize 10% em suas compras",
     "produtos KaBuM! VÁLIDO PARA PRODUTOS ATÉ R$ 500", P_KABUM, False),
    ("R4b-TUDO99-itens-ate-R$99-AliExpress", ALI, "TUDO99", "Cupom AliExpress R$ 10 OFF em itens até R$ 99",
     "Válido para itens da seção Tudo até R$ 99", P_ALI, False),
    ("R4b-FAIXA30-compras-de-R$200-ate-R$499", MAGALU, "FAIXA30",
     "Cupom Magalu - R$ 30 OFF em compras de R$ 200 até R$ 499", "Válido para produtos vendidos e entregues pelo Magalu",
     P_MAGALU, False),
    ("R4b-itens-de-ate-R$99-na-regra", ALI, "TUDO99", "Os melhores itens do site com R$ 10 OFF aplicando cupom AliExpress",
     "produtos Aliexpress Válido para itens de até R$ 99.", P_ALI, False),
    ("R4b-produtos-de-ate-R$150-vendidos-pela-Magalu", MAGALU, "PRECINHO",
     "Cupom de desconto Magalu oferece 15% OFF em suas compras",
     "produtos Magazine Luiza Válido para produtos de até R$ 150 vendidos pela Magalu.", P_MAGALU, False),
    ("R4b-pedidos-de-no-maximo-R$300", MAGALU, "MAX300", "Cupom Magalu 10% OFF (limite R$ 30)",
     "Válido para pedidos de no máximo R$ 300.", P_MAGALU, False),
    ("R4b-itens-com-preco-de-ate-R$100", AMAZON, "PEQ20", "Desconto Amazon: economize 20% em suas compras",
     "produtos Amazon Válido somente para itens com preço de até R$ 100.", P_AMAZON, False),
    ("R4b-carrinhos-de-ate-R$300", "Casas Bahia", "CB20", "Cupom Casas Bahia R$ 20 OFF",
     "Válido para carrinhos de até R$ 300.", 3599.09, False),
    ("R4b-produtos-com-valor-ate-R$200", AMAZON, "VALE", "Cupom Amazon 15% OFF em produtos com valor até R$ 200", "",
     P_AMAZON, False),
    # pré-existente (main e 1ª passada aceitavam): o teto é o preço da própria TV
    ("R4b-TVs-ate-R$2.000-fora", MAGALU, "X", "Cupom Magalu R$ 100 OFF em TVs até R$ 2.000", "", P_MAGALU, False),
    ("R4b-TVs-de-ate-R$5.000-serve", KABUM, "X", "Cupom KaBuM! R$ 200 OFF em TVs de até R$ 5.000", "", P_KABUM, True),
    # o teto do DESCONTO continua não barrando (F3)
    ("R4b-desconto-de-ate-12pct-com-desconto-maximo-de-R$400", ML, "X",
     "TELA GRANDE: 12% OFF em TVs no Mercado Livre (acima de R$ 1.500) com cupom",
     "produtos Mercado Livre Desconto de até 12% em compra a partir de R$1.500, com desconto máximo de R$400 válido "
     "para itens elegíveis.", P_ML, True),
    ("R4b-10pct-OFF-parenteses-maximo-R$50", MAGALU, "X", "Cupom Magalu 10% OFF (máximo R$ 50) em todo o site", "",
     P_MAGALU, True),
    ("R4b-ate-R$300-de-desconto-em-compras-acima-de-R$3.000", MAGALU, "X",
     "Cupom Magalu: até R$ 300 de desconto em compras acima de R$ 3.000", "", P_MAGALU, True),
    # a exclusão acaba na vírgula que abre outra condição: a compra mínima depois dela vale
    ("R4b-exceto-Celulares-virgula-compras-acima-de-R$5.000-fora", MAGALU, "X", "Cupom Magalu R$ 300 OFF em todo o site",
     "Exceto Celulares, em compras acima de R$ 5.000", P_MAGALU, False),
    ("R4b-exceto-Supermercado-Farmacia-e-Pet-lista-continua", ML, "X", "Cupom Mercado Livre 15% OFF em todo o site",
     "Exceto Supermercado, Farmácia e Pet. Compra mínima R$ 199.", P_ML, True),
    # regressão 3: particípio que diz O QUE é o produto é categoria (a main recusa); venda/entrega não é
    ("R4b-RENOVA20-produtos-Renovados", AMAZON, "RENOVA20", "Cupom Amazon 20% OFF em produtos Renovados",
     "Válido para produtos Amazon Renovados vendidos pela Amazon", P_AMAZON, False),
    ("R4b-RENOVEJA-Recondicionados", ML, "RENOVEJA",
     "RENOVE JÁ: 15% OFF em Recondicionados no Mercado Livre (acima de R$ 99) com cupom", "produtos Mercado Livre", P_ML,
     False),
    ("R4b-Produtos-Usados", AMAZON, "USADOS15", "Cupom Amazon 15% OFF em Produtos Usados",
     "Válido para produtos vendidos pela Amazon", P_AMAZON, False),
    ("R4b-Congelados-e-Resfriados", ML, "CONGEL10", "Cupom Mercado Livre 10% OFF em Congelados e Resfriados", "", P_ML,
     False),
    ("R4b-Itens-Importados", AMAZON, "IMPORT", "Cupom Amazon 10% OFF em Itens Importados", "", P_AMAZON, False),
    ("R4b-Mais-Vendidos-e-selecao", ML, "MAISVEND",
     "OFERTA TOP: 15% OFF em Mais Vendidos no Mercado Livre (acima de R$ 99) com cupom", "produtos Mercado Livre", P_ML,
     False),
    ("R4b-vendidos-pela-loja-parceira-Lojas-Colombo", MAGALU, "LOJA10",
     "Cupom Magalu 10% OFF em produtos vendidos pela loja parceira Lojas Colombo", "", P_MAGALU, False),
    ("R4b-vendidos-e-entregues-pela-propria-loja-serve", AMAZON, "VENDAMZ",
     "Cupom Amazon R$ 100 OFF em produtos vendidos e entregues pela Amazon", "Compra mínima R$ 1.000", P_AMAZON, True),
    # regressão 4: cliente novo escrito de outros jeitos (a main recusava pelo 'app'; app não é categoria)
    ("R4b-BEMVINDO20-clientes-novos-no-app", MAGALU, "BEMVINDO20", "Cupom Magalu R$ 20 OFF para clientes novos no app",
     "Válido para compras acima de R$ 100", P_MAGALU, False),
    ("R4b-quem-ainda-nao-comprou-no-app", AMAZON, "NOVOAPP", "Cupom Amazon R$ 20 OFF para quem ainda não comprou no app",
     "", P_AMAZON, False),
    ("R4b-novos-cadastros-no-app", "Casas Bahia", "APPNOVO", "Cupom Casas Bahia 10% OFF no app para novos cadastros", "",
     3599.09, False),
    ("R4b-quem-nunca-comprou", ML, "NUNCA30", "Cupom Mercado Livre R$ 30 OFF para quem nunca comprou",
     "Compra mínima R$ 60", P_ML, False),
    ("R4b-clientes-novos-e-antigos-serve", MAGALU, "X", "Cupom Magalu R$ 300 OFF para clientes novos e antigos",
     "Válido em compras acima de R$ 3.000", P_MAGALU, True),
    # ---- rodada 5 (passada final): a lista fechada E1-E5, com as entradas exatas do veredito final ----
    # E1: número depois de "Smart TV(s)" que não é tamanho (data, hora, limite de uso, quantidade de cupons) não é
    # "outro tamanho"; tamanho precisa de polegada, código de modelo, especificação de TV logo depois (4K, QLED) ou
    # lista explícita. Título e regra são lidos separados (a data da regra não vira tamanho da TV do título). A main
    # aceita todas
    ("R5-E1-TVML400-valido-ate-30-09-e-500-cupons-na-regra", ML, "TVML400",
     "Cupom Mercado Livre - 10% OFF Acima de R$ 1.999 limitado à R$ 400 em Smart TVs",
     "Válido até 30/09 ou enquanto durarem os 500 cupons", P_ML, True),
    ("R5-E1-limitado-a-10-usos-por-CPF", ML, "X",
     "Cupom Mercado Livre - 10% OFF Acima de R$1.999 limitado à R$300 em Smart TVs", "Limitado a 10 usos por CPF", P_ML,
     True),
    ("R5-E1-acaba-em-30-minutos", ML, "X", "Cupom Mercado Livre - 10% OFF Acima de R$1.999 limitado à R$300 em Smart TVs",
     "Acaba em 30 minutos", P_ML, True),
    ("R5-E1-valido-ate-23-09", ML, "X", "Cupom Mercado Livre - 10% OFF Acima de R$1.999 limitado à R$300 em Smart TVs",
     "Válido até 23/09", P_ML, True),
    ("R5-E1-so-50-cupons", ML, "X", "Cupom Mercado Livre - 10% OFF Acima de R$1.999 limitado à R$300 em Smart TVs",
     "Só 50 cupons", P_ML, True),
    ("R5-E1-Smart-TVs-ate-30-09-no-titulo", MAGALU, "X", "Cupom Magalu R$ 300 OFF em Smart TVs até 30/09", "", P_MAGALU,
     True),
    ("R5-E1-Smart-TVs-hoje-ate-as-23-59", MAGALU, "X", "Cupom Magalu R$ 300 OFF em Smart TVs hoje até às 23:59", "",
     P_MAGALU, True),
    ("R5-E1-Smart-TVs-valido-ate-dia-25", KABUM, "X", "Cupom KaBuM! 10% OFF em Smart TVs válido até dia 25", "", P_KABUM,
     True),
    ("R5-E1-Smart-TVs-em-ate-10-vezes", "Casas Bahia", "X",
     "Cupom Casas Bahia R$ 200 OFF em Smart TVs em até 10 vezes sem juros", "", 3599.09, True),
    ("R5-E1-Smart-TVs-para-os-primeiros-50-clientes", MAGALU, "X",
     "Cupom Magalu R$ 300 OFF em Smart TVs para os primeiros 50 clientes", "", P_MAGALU, True),
    ("R5-E1-dias-19-e-20-de-setembro-na-regra", MAGALU, "X", "Cupom Magalu R$ 300 OFF em Smart TVs",
     "Válido nos dias 19 e 20 de setembro", P_MAGALU, True),
    # continuam tamanho: lista explícita sem polegada, e o número seguido de especificação de TV
    ("R5-E1-Smart-TVs-32-e-43-lista-sem-polegada-fora", MAGALU, "X", "Cupom Magalu R$ 300 OFF em Smart TVs 32 e 43", "",
     P_MAGALU, False),
    ("R5-E1-Smart-TVs-de-50-a-65-faixa-sem-polegada-serve", MAGALU, "X", "Cupom Magalu R$ 300 OFF em Smart TVs de 50 a 65",
     "", P_MAGALU, True),
    ("R5-E1-Smart-TV-65-QLED-fora", MAGALU, "X", "Cupom Magalu R$ 300 OFF na Smart TV 65 QLED", "", P_MAGALU, False),
    # E2: cupom progressivo (em faixas) serve se o preço da TV alcança QUALQUER faixa: vale o menor mínimo; o mínimo
    # de uma faixa de cima nunca recusa. A main aceita todos
    ("R5-E2-ESCADA500-progressivo-Magalu", MAGALU, "ESCADA500",
     "Cupom Magalu progressivo: R$ 100 OFF acima de R$ 1.000, R$ 300 OFF acima de R$ 3.000 e R$ 500 OFF acima de "
     "R$ 5.000", "", P_MAGALU, True),
    ("R5-E2-Casas-Bahia-150-300-600", "Casas Bahia", "X",
     "Cupom Casas Bahia: R$ 150 OFF acima de R$ 1.500 | R$ 300 OFF acima de R$ 3.000 | R$ 600 OFF acima de R$ 6.000",
     "Válido para TVs e Eletrônicos", 3599.09, True),
    ("R5-E2-progressivos-Magalu-150-e-400", MAGALU, "X",
     "Cupons progressivos Magalu - R$ 150 OFF acima de R$ 1.500 / R$ 400 OFF acima de R$ 4.000", "", P_MAGALU, True),
    ("R5-E2-ML-10pct-TVs-acima-2000-e-15pct-acima-5000", ML, "X",
     "Cupom Mercado Livre - 10% OFF em TVs (acima de R$ 2.000); 15% OFF acima de R$ 5.000", "", P_ML, True),
    ("R5-E2-descricao-do-Pelando-cita-o-MAGALU500", MAGALU, "TVMAGALU300", "Cupom Magalu R$ 300 OFF em TVs acima de R$ 3.000",
     "Pra quem vai gastar mais, o MAGALU500 dá R$ 500 OFF acima de R$ 5.000", P_MAGALU, True),
    # o CLIENTE real da Fast Shop (promobit:69092 e 69083, em faixas de R$ 800, R$ 2.000 e R$ 4.000): como na main,
    # serve com a TV a R$ 3.296,81 e também a R$ 1.500 (a faixa de R$ 800)
    ("R5-E2-CLIENTE-69092-Fast-Shop-3296.81", "Fast Shop", "CLIENTE",
     "O momento chegou: Aplique cupom Fastshop e ganhe 12% OFF",
     "produtos Fast Shop Compras de R$800 a R$1999 | 8% OFF | Limitado a R$160\nCompras de R$ 2000 a R$3999 | 10% OFF | "
     "Limitado a R$220\nCompras acima R$4000 | 12% OFF | Limitado a R$500", 3296.81, True),
    ("R5-E2-CLIENTE-69092-Fast-Shop-1500", "Fast Shop", "CLIENTE",
     "O momento chegou: Aplique cupom Fastshop e ganhe 12% OFF",
     "produtos Fast Shop Compras de R$800 a R$1999 | 8% OFF | Limitado a R$160\nCompras de R$ 2000 a R$3999 | 10% OFF | "
     "Limitado a R$220\nCompras acima R$4000 | 12% OFF | Limitado a R$500", 1500.0, True),
    ("R5-E2-CLIENTE-69083-Fast-Shop-1500", "Fast Shop", "CLIENTE",
     "Compras de R$800 a R$1999 | 8% de Desconto | Limitado a R$160\nCompras de R$ 2000 a R$3999 | 10% de Desconto | "
     "Limitado a R$220\nCompras acima R$4000 | 12% de Desconto | Limitado a R$500",
     "produtos Fast Shop Compras de R$800 a R$1999 | 8% OFF | Limitado a R$160\nCompras de R$ 2000 a R$3999 | 10% OFF | "
     "Limitado a R$220\nCompras acima R$4000 | 12% OFF | Limitado a R$500", 1500.0, True),
    # a faixa de baixo com teto ("de R$ 800 até R$ 1.999") não recusa quando há faixa de cima
    ("R5-E2-faixas-com-ate-a-TV-cabe-na-faixa-de-cima", "Fast Shop", "X", "Cupom Fast Shop progressivo",
     "Compras de R$ 800 até R$ 1.999: 8% OFF | Compras de R$ 2.000 até R$ 3.999: 10% OFF | Acima de R$ 4.000: 12% OFF",
     3296.81, True),
    # uma faixa só continua recusando: mínimo acima do preço, teto abaixo; e o preço no vão entre duas faixas também
    ("R5-E2-uma-faixa-so-acima-de-R$5.000-fora", MAGALU, "X", "Cupom Magalu R$ 500 OFF acima de R$ 5.000", "", P_MAGALU,
     False),
    ("R5-E2-TV-no-vao-entre-as-faixas-fora", "Fast Shop", "X", "Cupom Fast Shop progressivo",
     "Compras de R$ 800 até R$ 1.999: 8% OFF | Acima de R$ 5.000: 12% OFF", 3296.81, False),
    # E3: cliente novo só com as palavras explícitas da restrição (a main aceita todas estas; a regra do Pelando é
    # texto livre de quem postou)
    ("R5-E3-quem-ainda-nao-usou-corre", MAGALU, "TVMAGALU300", "Cupom Magalu R$ 300 OFF em TVs acima de R$ 3.000",
     "Quem ainda não usou, corre que acaba hoje!", P_MAGALU, True),
    ("R5-E3-liberado-pela-primeira-vez", MAGALU, "TVMAGALU300", "Cupom Magalu R$ 300 OFF em TVs acima de R$ 3.000",
     "Cupom liberado pela primeira vez para TVs, aproveitem", P_MAGALU, True),
    ("R5-E3-quem-nunca-usou-cupom-no-ML", ML, "X",
     "Cupom Mercado Livre - 10% OFF Acima de R$ 1.999 limitado à R$ 400 em TVs",
     "Quem nunca usou cupom no ML, vale a pena testar no carrinho", P_ML, True),
    ("R5-E3-novos-compradores-e-quem-ja-comprou", AMAZON, "X", "Cupom Amazon R$ 200 OFF em Smart TVs",
     "Válido para novos compradores e quem já comprou na Amazon", P_AMAZON, True),
    # as palavras explícitas continuam recusando
    ("R5-E3-novos-usuarios-fora", AMAZON, "X", "Cupom Amazon R$ 200 OFF em Smart TVs", "Válido para novos usuários",
     P_AMAZON, False),
    ("R5-E3-primeiro-pedido-fora", ML, "X", "Cupom Mercado Livre R$ 300 OFF em TVs", "Válido no primeiro pedido", P_ML,
     False),
    ("R5-E3-quem-ainda-nao-comprou-fora", MAGALU, "X", "Cupom Magalu R$ 300 OFF em TVs",
     "Só para quem ainda não comprou no site", P_MAGALU, False),
    ("R5-E3-1a-compra-fora", MAGALU, "X", "Cupom Magalu R$ 300 OFF em TVs (1ª compra)", "", P_MAGALU, False),
    # E4: exclusão de OUTRAS TVs (outro tamanho/modelo, mesmo da TCL) não tira a 55C6K. A main aceita todas
    ("R5-E4-TCLAMZ200-exceto-a-TCL-32S5400A", AMAZON, "TCLAMZ200", "Cupom Amazon R$ 200 OFF em Smart TVs TCL",
     "Válido para Smart TVs TCL vendidas pela Amazon, exceto a TCL 32S5400A", P_AMAZON, True),
    ("R5-E4-exceto-modelos-TCL-de-32-e-43-polegadas", KABUM, "X", "Cupom KaBuM! 8% OFF em TVs TCL",
     "produtos KaBuM! 8% OFF em TVs TCL (exceto modelos TCL de 32 e 43 polegadas)", P_KABUM, True),
    ("R5-E4-nao-valido-para-TVs-TCL-32-e-43-aspas", MAGALU, "X", "Cupom Magalu R$ 300 OFF em Smart TVs",
     'Não válido para TVs TCL 32" e 43"', P_MAGALU, True),
    ("R5-E4-TVS300-exceto-TVs-32-43-e-50-polegadas", MAGALU, "TVS300", "Cupom Magalu R$ 300 OFF em TVs",
     "Exceto TVs 32, 43 e 50 polegadas", P_MAGALU, True),
    # a exclusão que cobre a 55" / 55C6K / C6K / a TCL ou as TVs sem qualificador continua tirando a TV
    ("R5-E4-exceto-a-TCL-55C6K-fora", AMAZON, "X", "Cupom Amazon R$ 200 OFF em Smart TVs",
     "Exceto a TCL 55C6K", P_AMAZON, False),
    ("R5-E4-exceto-a-linha-C6K-fora", AMAZON, "X", "Cupom Amazon R$ 200 OFF em Smart TVs TCL", "Exceto a linha C6K",
     P_AMAZON, False),
    ("R5-E4-exceto-produtos-TCL-fora", MAGALU, "X", "Cupom Magalu R$ 200 OFF em todo o site", "Exceto produtos TCL",
     P_MAGALU, False),
    ("R5-E4-exceto-TVs-TCL-de-50-a-65-fora", MAGALU, "X", "Cupom Magalu R$ 200 OFF em todo o site",
     "Exceto TVs TCL de 50 a 65 polegadas", P_MAGALU, False),
    ("R5-E4-exceto-TVs-32-43-55-fora", MAGALU, "X", "Cupom Magalu R$ 300 OFF em TVs", "Exceto TVs 32, 43 e 55 polegadas",
     P_MAGALU, False),
    # E5: cupom de marca / loja oficial / outra loja não serve, salvo se a marca é TCL
    ("R5-E5-LGOFICIAL15-Loja-Oficial-LG", ML, "LGOFICIAL15",
     "Cupom Mercado Livre 15% OFF em compras acima de R$ 200 na Loja Oficial LG",
     "Válido apenas para produtos da loja oficial", P_ML, False),
    ("R5-E5-PHILCO12-em-Loja-Oficial-Philco", ML, "PHILCO12",
     "Cupom Mercado Livre - 12% OFF Acima de R$ 99 limitado à R$ 60 em Loja Oficial Philco", "", P_ML, False),
    ("R5-E5-ELECTROLUX15-CASA-NOVA-Promobit", ML, "ELECTROLUX15",
     "CASA NOVA: 15% OFF na Loja Oficial Electrolux no Mercado Livre (acima de R$ 299) com cupom",
     "produtos Mercado Livre", P_ML, False),
    ("R5-E5-Loja-Oficial-Brastemp", ML, "X",
     "Cupom Mercado Livre 10% OFF em compras acima de R$ 99 na Loja Oficial Brastemp", "", P_ML, False),
    ("R5-E5-Magalu-na-Netshoes", MAGALU, "X", "Cupom Magalu 10% OFF em compras acima de R$ 199 na Netshoes", "",
     P_MAGALU, False),
    ("R5-E5-Magalu-na-Loja-Oficial-Electrolux", MAGALU, "X", "Cupom Magalu 10% OFF na Loja Oficial Electrolux", "",
     P_MAGALU, False),
    ("R5-E5-Amazon-na-loja-Samsung", AMAZON, "X", "Cupom Amazon 15% OFF na loja Samsung", "", P_AMAZON, False),
    ("R5-E5-Fast-Shop-Smart-TVs-Samsung", "Fast Shop", "X", "Cupom Fast Shop 10% OFF em Smart TVs Samsung", "", 3296.81,
     False),
    ("R5-E5-ML-10pct-OFF-em-TCL-serve", ML, "X", "Cupom Mercado Livre 10% OFF em TCL", "", P_ML, True),
    ("R5-E5-Loja-Oficial-TCL-serve", ML, "X", "Cupom Mercado Livre 10% OFF na Loja Oficial TCL", "", P_ML, True),
    ("R5-E5-TVs-TCL-serve", MAGALU, "X", "Cupom Magalu R$ 300 OFF em TVs TCL", "", P_MAGALU, True),
    ("R5-E5-TVs-Samsung-LG-e-TCL-serve", MAGALU, "X", "Cupom Magalu R$ 300 OFF em Smart TVs Samsung, LG e TCL", "",
     P_MAGALU, True),
    # conferência da passada final: "loja oficial" sem nome de marca (ou com nome de varejista) não recusa; no ML a
    # própria 55C6K é vendida pela "Loja oficial Magalu" (vendedor visto em latest_pc)
    ("R5-E5-Loja-Oficial-Magalu-no-ML-serve", ML, "X", "Cupom Mercado Livre 15% OFF na Loja Oficial Magalu", "", P_ML,
     True),
    ("R5-E5-em-lojas-oficiais-serve", ML, "X", "Cupom Mercado Livre 10% OFF em lojas oficiais acima de R$ 1.999", "",
     P_ML, True),
    ("R5-E5-Lojas-Oficiais-na-regra-serve", ML, "X", "Cupom Mercado Livre 12% OFF acima de R$ 1.999 em Lojas Oficiais",
     "Válido apenas para produtos de lojas oficiais", P_ML, True),
    ("R5-E5-vendidos-pela-Loja-Oficial-serve", MAGALU, "X", "Cupom Magalu R$ 200 OFF",
     "Válido para produtos vendidos pela Loja Oficial", P_MAGALU, True),
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

def _grava_state(pasta, modo, minimo=None, ofertas=None, cupons=None, alertados=None):
    """State já existente (não é partida), no formato do repositório antes da rodada 2 (sem 'cupons_alertados').
    alertados: grava 'cupons_alertados' (state de depois da rodada 2: os cupons vistos que não estão ali não foram
    alertados)."""
    dados = {"ofertas": ofertas or {}, "cupons": cupons or {}, "minimo": minimo, "saude": {},
             "ultimo_resumo": None, "criado_em": "2026-09-13T15:22:00-03:00"}
    if alertados is not None:
        dados["cupons_alertados"] = alertados
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
    diretas = est.lojas_diretas_conhecidas(ofertas)
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


# ---- rodada 4: regressões da rodada 3 (textos exatos do arquivo de correção) ----

def _magalu_oferta():
    """Magalu 1P em 18/09: R$ 3.749, Pix 3.561,55."""
    return Oferta("magalu", "loja", MAGALU, "TCL 55C6K", "u", "240162800-magazineluiza", preco=3749.0,
                  preco_pix=3561.55, vendedor="Magalu")


PEL_TVMAGALU300 = _reg("pelando", "tvmagalu300-pelando", MAGALU, "TVMAGALU300",
                       "Cupom Magalu R$ 300 OFF em TVs acima de R$ 3.000", "Não válido para a categoria Celulares.",
                       primeira=1.0)
PROMOBIT_TVMAGALU300 = _reg("promobit", "tvmagalu300-promobit", MAGALU, "TVMAGALU300",
                            "Cupom de desconto Magazine Luiza oferece R$ 300 OFF em TVs", "", primeira=0.1)


def c_r4_tvmagalu300_alerta_e_painel(d, mp):
    """A main alerta '🎟️ Novo cupom aplicável à TV • Magazine Luiza TVMAGALU300 … · TV lá: R$ 3.561,55'."""
    _grava_state(d, "cloud")
    est = Estado("cloud")
    c = _de_reg(PEL_TVMAGALU300)
    msgs, _ = gerar_alertas(est, [_magalu_oferta()], [c])
    return (_codigos(msgs), "TV lá: R$ 3.561,55" in msgs[0] if msgs else None,
            [x.codigo for x in cupons_aplicaveis([_magalu_oferta()], [c], est)])


def c_r4_tvmagalu300_pelando_no_estado_nao_silencia_o_promobit(d, mp):
    """Amplificação da rodada 3: com o anúncio do Pelando ('Não válido para a categoria Celulares') no state, o post
    limpo do Promobit do mesmo código era barrado por restricao_do_codigo. A main alerta. (State de depois da rodada 2:
    o anúncio do Pelando foi visto e recusado, não alertado.)"""
    _grava_state(d, "cloud", cupons=_por_chave(PEL_TVMAGALU300), alertados={})
    est = Estado("cloud")
    novo = _de_reg(PROMOBIT_TVMAGALU300)
    msgs, _ = gerar_alertas(est, [_magalu_oferta()], [novo])
    return (sorted(restricao_do_codigo([novo], est.cupons_vistos())), _codigos(msgs),
            [x.codigo for x in cupons_aplicaveis([_magalu_oferta()], [novo], est)])


def c_r4_tvmagalu300_ja_alertado_nao_repete(d, mp):
    """F9: se o anúncio do Pelando já virou alerta (aqui, pelo estado antigo: a regra da época o aceitava), o post do
    Promobit com o mesmo desconto (R$ 300) é repetição."""
    _grava_state(d, "cloud", cupons=_por_chave(PEL_TVMAGALU300))
    msgs, _ = gerar_alertas(Estado("cloud"), [_magalu_oferta()], [_de_reg(PROMOBIT_TVMAGALU300)])
    return msgs


def c_r4_meli15tudo_alerta(d, mp):
    _grava_state(d, "cloud")
    c = Cupom(fonte="pelando", loja=ML, codigo="MELI15TUDO", url="u", id="meli15tudo",
              titulo="Cupom Mercado Livre 15% OFF em todo o site (limite R$ 150)",
              regra="Válido em todo o site, exceto na categoria Supermercado. Compra mínima R$ 199.")
    msgs, _ = gerar_alertas(Estado("cloud"), [_ml_oferta()], [c])
    return _codigos(msgs)


# anúncios com outro "em" depois do alvo de TV: nem recusam, nem barram o código em outros anúncios
R4_VARIOS_EM = [
    _reg("promobit", "tvkabum10", KABUM, "TVKABUM10", "Cupom KaBuM! 10% OFF em TVs em promoção",
         "produtos KaBuM! 10% OFF em TVs em promoção", primeira=1.0),
    _reg("promobit", "smarttv250", MAGALU, "SMARTTV250", "Cupom Magalu R$ 250 OFF em Smart TVs em oferta", "",
         primeira=1.0),
    _reg("promobit", "pix300", MAGALU, "PIX300", "Cupom Magalu de R$ 300 para pagamento em Pix",
         "Válido em compras acima de R$ 3.000", primeira=1.0),
]


def c_r4_varios_em_alertam(d, mp):
    _grava_state(d, "cloud")
    ofs = [_magalu_oferta(), Oferta("kabum", "loja", KABUM, "TCL 55C6K", "u", "911482", preco=3159.0)]
    msgs, _ = gerar_alertas(Estado("cloud"), ofs, [_de_reg(r) for r in R4_VARIOS_EM])
    return sorted(_codigos(msgs))


def c_r4_varios_em_nao_barram_outro_post(d, mp):
    """Com esses anúncios no state, um post genérico do mesmo código (id novo) ainda alerta (a main alerta)."""
    _grava_state(d, "cloud", cupons=_por_chave(*R4_VARIOS_EM))
    est = Estado("cloud")
    genericos = [_de_reg(r, id=r["id"] + "-2", titulo=f"Economize com o cupom {r['codigo']} em suas compras",
                         regra="") for r in R4_VARIOS_EM]
    ofs = [_magalu_oferta(), Oferta("kabum", "loja", KABUM, "TCL 55C6K", "u", "911482", preco=3159.0)]
    restritos = restricao_do_codigo(genericos, est.cupons_vistos())
    # os anúncios do state já foram vistos (não alertados): o genérico é a primeira vez que o código alerta
    msgs, _ = gerar_alertas(est, ofs, genericos)
    return sorted(restritos), sorted(_codigos(msgs))


def c_r4_tcltv250_alerta(d, mp):
    _grava_state(d, "pc")
    c = Cupom(fonte="promobit", loja=AMAZON, codigo="TCLTV250", url="u", id="tcltv250",
              titulo="Cupom Amazon R$ 250 OFF em Smart TV TCL 50, 55 e 65 polegadas",
              regra="Válido para TVs vendidas pela Amazon.")
    msgs, _ = gerar_alertas(Estado("pc"), [Oferta("amazon", "loja", AMAZON, "TCL 55C6K", "u", "B0F7JZMVKF",
                                                   preco=3279.0)], [c])
    return _codigos(msgs)


def c_r4_frete_e_app_alertam(d, mp):
    _grava_state(d, "pc")
    cb = Cupom(fonte="promobit", loja="Casas Bahia", codigo="CBFRETE200", url="u", id="cbfrete200",
               titulo="Cupom Casas Bahia: R$ 200 OFF + Frete Grátis em compras acima de R$ 1.999",
               regra="Aplique o cupom no carrinho. Limitado a 1 uso por CPF.")
    app = Cupom(fonte="promobit", loja=MAGALU, codigo="APPMAGALU350", url="u", id="appmagalu350",
                titulo="Cupom Magalu com R$ 350 OFF para usar no app",
                regra="produtos Magazine Luiza Use o código no app em compras acima de R$ 3.000.")
    ofs = [Oferta("casasbahia", "loja", "Casas Bahia", "TCL 55C6K", URL_CB, "55069456", preco=3998.99,
                  preco_pix=3599.09), _magalu_oferta()]
    msgs, _ = gerar_alertas(Estado("pc"), ofs, [cb, app])
    return sorted(_codigos(msgs))


# ---- rodada 4: DESCONTOJA no pc com os state reais da main (o cloud sabe que o código é só "em Casa") ----
FIXTURE_8E21 = Path(__file__).parent / "fixtures" / "dados_8e21e6d.json"
AGORA_8E21 = "2026-09-18T17:50:00-03:00"  # logo depois da coleta das 17:43


def _dados_reais(d, mp, arquivos=("state_cloud", "state_pc", "latest_cloud", "latest_pc"), hora=AGORA_8E21):
    """Grava no diretório de dados temporário os arquivos reais da main e para o relógio na hora deles."""
    from datetime import datetime

    reais = json.loads(FIXTURE_8E21.read_text(encoding="utf-8"))
    for nome in arquivos:
        (d / f"{nome}.json").write_text(json.dumps(reais[nome], ensure_ascii=False), encoding="utf-8")
    quando = datetime.fromisoformat(hora)
    mp.setattr(util, "agora", lambda: quando)
    return reais


def _descontoja_do_pelando():
    t = "Cupom Mercado Livre 15% OFF acima de R$ 50 (limi R$ 200 OFF)"
    return Cupom(fonte="pelando", loja=ML, codigo="DESCONTOJA", titulo=t, url="u", id="novo-post-descontoja", regra=t)


def c_r4_descontoja_pc_gerar_alertas(d, mp):
    """A main: (False, 'categoria: mercado'), sem alerta. A rodada 3 alertava e punha no latest_pc.cupons."""
    _dados_reais(d, mp)
    est = Estado("pc")
    c = _descontoja_do_pelando()
    msgs, _ = gerar_alertas(est, [_ml_oferta()], [c])
    return ("Mercado Livre|DESCONTOJA" in restricao_do_codigo([c], est.cupons_vistos()),
            [m for m in msgs if "🎟️" in m], [x.codigo for x in cupons_aplicaveis([_ml_oferta()], [c], est)])


class _FonteDescontoja:
    nome = "pelando.cupons"
    modo = "pc"
    alerta_falha = True

    def coletar(self):
        return [_ml_oferta()], [_descontoja_do_pelando()]


def c_r4_descontoja_pc_run_main(d, mp):
    """A mesma rodada pelo run.main() no modo pc (fonte trocada, sem .env, sem Telegram)."""
    import io

    import run
    from monitor import sources

    _dados_reais(d, mp)
    mp.setattr(run, "carrega_env", lambda: None)
    mp.setattr(sources, "por_modo", lambda modo: [_FonteDescontoja()])
    mp.setattr(run.time, "sleep", lambda s: None)
    mp.setattr(sys, "argv", ["run.py", "--mode", "pc", "--no-notify"])
    saida = io.StringIO()
    mp.setattr(sys, "stdout", saida)
    assert run.main() == 0
    latest = json.loads((d / "latest_pc.json").read_text(encoding="utf-8"))
    return [b for b in saida.getvalue().split("[alerta]") if "🎟️" in b], [c["codigo"] for c in latest["cupons"]]


def c_r4_descontoja_sem_o_arquivo_do_cloud(d, mp):
    """Sem o state do cloud (arquivo ausente) o pc não quebra e, sem saber do 'em Casa', o anúncio genérico serve."""
    _dados_reais(d, mp, arquivos=("state_pc", "latest_pc"))
    msgs, _ = gerar_alertas(Estado("pc"), [_ml_oferta()], [_descontoja_do_pelando()])
    return _codigos(msgs)


def c_r4_descontoja_casa_ha_mais_de_30_dias(d, mp):
    """A janela de 30 dias continua: 'em Casa' visto no cloud há mais de 30 dias não barra."""
    _dados_reais(d, mp, hora="2026-10-25T12:00:00-03:00")
    msgs, _ = gerar_alertas(Estado("pc"), [_ml_oferta()], [_descontoja_do_pelando()])
    return _codigos(msgs)


# ---- ZOOM: agregador de loja que tem fonte direta (em qualquer modo) não é preço ----

def _ofertas_do_latest(reais, modo):
    campos = set(Oferta.__dataclass_fields__)
    return [Oferta(**{k: v for k, v in o.items() if k in campos}) for o in reais[f"latest_{modo}"]["ofertas_loja"]]


def c_zoom_resumo_cloud_real(d, mp):
    """O resumo do cloud de 18/09 listou 'Amazon: R$ 3.279' (Zoom parado desde 14/09) como a loja mais barata. A
    Amazon real (ASIN B0F7JZMVKF, o mesmo do Zoom) estava a R$ 3.749 no pc."""
    reais = _dados_reais(d, mp)
    txt = resumo_diario(Estado("cloud"), _ofertas_do_latest(reais, "cloud"), [])
    lojas = [ln for ln in txt.split("\n") if ln.startswith("• ")]
    return ("3.279" in txt, lojas[0],
            "• Amazon/Magalu.: <b>R$ 3.749,00</b> · 12x R$ 312,49 sem juros · visto 18/09 17:43 (PC)" in lojas,
            [ln for ln in lojas if ln.startswith("• KaBuM!")], "Menor já visto: R$ 2.991,60 (Magazine Luiza" in txt)


def c_zoom_resumo_sem_o_pc(d, mp):
    """Loja que só o agregador conhece (nenhuma fonte direta em nenhum modo) continua com a linha dele."""
    reais = _dados_reais(d, mp, arquivos=("state_cloud", "latest_cloud"))
    txt = resumo_diario(Estado("cloud"), _ofertas_do_latest(reais, "cloud"), [])
    return "• Amazon: <b>R$ 3.279,00</b>" in txt, " · visto " in txt


def _zoom_amazon(preco):
    return Oferta("zoom", "loja", AMAZON, "Smart TV TCL 55C6K", "https://www.zoom.com.br/tv/x?highlightedItemId=1489104908",
                  "1489104908", preco=preco)


def c_zoom_amazon_2800_no_cloud(d, mp):
    """O Zoom (sem extra.agregador, como o parser grava hoje) mostra a Amazon a R$ 2.800: com o pc vendo a Amazon
    direto, não sai 🎯/🏆/🔻 nem vira mínimo; sem nenhum arquivo do pc, sai como hoje."""
    reais = _dados_reais(d, mp)
    ofs = [o for o in _ofertas_do_latest(reais, "cloud") if not (o.fonte == "zoom" and o.loja == AMAZON)]
    est, msgs = _rodada("cloud", ofs + [_zoom_amazon(2800.0)])
    com_pc = ([m.split("\n")[0] for m in msgs if "Amazon" in m.split("\n")[0]], est.minimo()["preco"])
    for f in ("state_cloud", "state_pc", "latest_pc", "historico_cloud"):
        (d / f"{f}.json").unlink(missing_ok=True)
    (d / "historico_cloud.csv").unlink(missing_ok=True)
    _dados_reais(d, mp, arquivos=("state_cloud", "latest_cloud"))
    est, msgs = _rodada("cloud", ofs + [_zoom_amazon(2800.0)])
    sem_pc = [m.split("\n")[0] for m in msgs if "Amazon" in m.split("\n")[0]]
    return com_pc, len(sem_pc), all(e in sem_pc[0] for e in ("🏆", "🔻", "🎯")), est.minimo()["preco"]


def c_zoom_partida_e_cupom(d, mp):
    """Mensagem de partida sem a linha do agregador coberto; cupom da Amazon no cloud mostra o preço direto do pc."""
    reais = _dados_reais(d, mp)
    ofs = _ofertas_do_latest(reais, "cloud")
    est = Estado("cloud")
    partida = mensagem_bootstrap(ofs, [], "cloud", est.lojas_diretas_conhecidas(ofs))
    c = Cupom(fonte="promobit", loja=AMAZON, codigo="AMZ100", url="u", id="amz100",
              titulo="Cupom Amazon R$ 100 OFF em Eletrônicos acima de R$ 3.500")
    msgs, _ = gerar_alertas(est, ofs, [c])
    return "3.279" in partida, [ln for ln in msgs[0].split("\n") if "AMZ100" in ln][0].endswith("TV lá: R$ 3.749,00")


def c_zoom_minimo_antigo_do_agregador(d, mp):
    """Real (5 versões do state_cloud de 13/09): mínimo 3.082,61 'Webcontinental' com URL do Zoom, e a Webcontinental
    tem fonte direta (vtex). Esse mínimo não vale; fica o menor dos registros que contam."""
    reais = _dados_reais(d, mp, arquivos=("state_pc", "latest_pc"))
    st = dict(reais["state_cloud"], minimo={"preco": 3082.61, "loja": "Webcontinental",
                                            "quando": "2026-09-13T15:23:00-03:00",
                                            "url": "https://www.zoom.com.br/tv/smart-tv-mini-led-55-tcl-4k-55c6k",
                                            "titulo": "Smart TV TCL 55C6K"})
    (d / "state_cloud.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    m = Estado("cloud").minimo_geral()
    return m["preco"], m["loja"]


def c_zoom_linhas_reais_sao_agregador(d, mp):
    """As linhas do Zoom gravadas hoje não trazem extra.agregador: fonte/URL bastam (o mesmo critério do painel)."""
    reais = json.loads(FIXTURE_8E21.read_text(encoding="utf-8"))
    return sorted({(o["loja"], e_agregador(o)) for o in reais["latest_cloud"]["ofertas_loja"] if o["fonte"] == "zoom"})


# ---- rodada 4, 2ª passada: as rodadas do verificador (E1-E8), com os arquivos reais da main ----

def _rodada_real_com_cupom(d, mp, modo, cupom):
    """Uma rodada de `modo` com as ofertas reais do latest dele e um cupom novo: (linhas 🎟️ do cupom, painel)."""
    reais = _dados_reais(d, mp)
    ofs = _ofertas_do_latest(reais, modo)
    est = Estado(modo)
    ofs, _av = sanear(ofs)
    msgs, _ = gerar_alertas(est, ofs, [cupom])
    linhas = [ln for m in msgs if m.startswith("🎟️") for ln in m.split("\n") if cupom.codigo in ln]
    return linhas, [c.codigo for c in cupons_aplicaveis(ofs, [cupom], est)]


def _cp(fonte, loja, codigo, titulo, regra, cid):
    return Cupom(fonte=fonte, loja=loja, codigo=codigo, titulo=titulo, url="u", id=cid, regra=regra)


def c_r4b_e1_ate500_cloud(d, mp):
    return _rodada_real_com_cupom(d, mp, "cloud", _cp(
        "promobit", KABUM, "ATE500", "Use o cupom KaBum! e economize 10% em suas compras",
        "produtos KaBuM! VÁLIDO PARA PRODUTOS ATÉ R$ 500", "70123"))


def c_r4b_e2_tudo99_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", _cp(
        "pelando", ALI, "TUDO99", "Cupom AliExpress R$ 10 OFF em itens até R$ 99",
        "Válido para itens da seção Tudo até R$ 99", "pel-tudo99"))


def c_r4b_e3_renova20_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", _cp(
        "pelando", AMAZON, "RENOVA20", "Cupom Amazon 20% OFF em produtos Renovados",
        "Válido para produtos Amazon Renovados vendidos pela Amazon", "pel-renova"))


def c_r4b_e4_renoveja_cloud(d, mp):
    return _rodada_real_com_cupom(d, mp, "cloud", _cp(
        "promobit", ML, "RENOVEJA", "RENOVE JÁ: 15% OFF em Recondicionados no Mercado Livre (acima de R$ 99) com cupom",
        "produtos Mercado Livre", "70124"))


def c_r4b_e5_faixa30_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", _cp(
        "pelando", MAGALU, "FAIXA30", "Cupom Magalu - R$ 30 OFF em compras de R$ 200 até R$ 499",
        "Válido para produtos vendidos e entregues pelo Magalu", "pel-faixa30"))


def c_r4b_e6_tcltv250_pc(d, mp):
    """A main manda '🎟️ Novo cupom aplicável à TV • Amazon TCLTV250 — ... · TV lá: R$ 3.749,00' e põe no painel."""
    linhas, painel = _rodada_real_com_cupom(d, mp, "pc", _cp(
        "pelando", AMAZON, "TCLTV250", 'Cupom Amazon R$ 250 OFF em Smart TV TCL 50", 55" e 65"', "", "pel-tcltv250"))
    return len(linhas), linhas[0].endswith("TV lá: R$ 3.749,00") if linhas else None, painel


def c_r4b_e7_tvgrande300_cloud(d, mp):
    """A main alerta com 'TV lá: R$ 3.561,55' e põe no painel."""
    linhas, painel = _rodada_real_com_cupom(d, mp, "cloud", _cp(
        "promobit", MAGALU, "TVGRANDE300", 'Cupom Magalu R$ 300 OFF em Smart TVs de 50" a 65"', "", "70300"))
    return len(linhas), linhas[0].endswith("TV lá: R$ 3.561,55") if linhas else None, painel


def c_r4b_e8_bemvindo20_cloud(d, mp):
    return _rodada_real_com_cupom(d, mp, "cloud", _cp(
        "promobit", MAGALU, "BEMVINDO20", "Cupom Magalu R$ 20 OFF para clientes novos no app",
        "Válido para compras acima de R$ 100", "70301"))


# ---- rodada 5 (passada final): rodadas com os arquivos reais da main, lista fechada E1-E5 ----
# O esperado é a saída da main 8e21e6d nestas mesmas rodadas (linha 🎟️ exata e painel), ou nada quando a main e o
# certo são não alertar (E5)
R5_TVML400 = _cp("pelando", ML, "TVML400", "Cupom Mercado Livre - 10% OFF Acima de R$ 1.999 limitado à R$ 400 em Smart TVs",
                 "Válido até 30/09 ou enquanto durarem os 500 cupons", "pel-tvml400")
R5_ESCADA500 = _cp("promobit", MAGALU, "ESCADA500", "Cupom Magalu progressivo: R$ 100 OFF acima de R$ 1.000, R$ 300 OFF "
                   "acima de R$ 3.000 e R$ 500 OFF acima de R$ 5.000", "", "70500")
R5_TCLAMZ200 = _cp("pelando", AMAZON, "TCLAMZ200", "Cupom Amazon R$ 200 OFF em Smart TVs TCL",
                   "Válido para Smart TVs TCL vendidas pela Amazon, exceto a TCL 32S5400A", "pel-tclamz200")
R5_TVS300 = _cp("promobit", MAGALU, "TVS300", "Cupom Magalu R$ 300 OFF em TVs", "Exceto TVs 32, 43 e 50 polegadas", "70501")
R5_LGOFICIAL15 = _cp("pelando", ML, "LGOFICIAL15",
                     "Cupom Mercado Livre 15% OFF em compras acima de R$ 200 na Loja Oficial LG",
                     "Válido apenas para produtos da loja oficial", "pel-lgoficial15")


def c_r5_e1_tvml400_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", R5_TVML400)


def c_r5_e1_smart_tvs_ate_30_09_cloud(d, mp):
    return _rodada_real_com_cupom(d, mp, "cloud", _cp(
        "promobit", MAGALU, "SMART300", "Cupom Magalu R$ 300 OFF em Smart TVs até 30/09", "", "70502"))


def c_r5_e1_smart_tvs_ate_23_59_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", _cp(
        "pelando", MAGALU, "SMART300", "Cupom Magalu R$ 300 OFF em Smart TVs hoje até às 23:59", "", "pel-smart300"))


def c_r5_e2_escada500_cloud(d, mp):
    return _rodada_real_com_cupom(d, mp, "cloud", R5_ESCADA500)


def c_r5_e2_cb_faixas_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", _cp(
        "pelando", "Casas Bahia", "CBFAIXAS",
        "Cupom Casas Bahia: R$ 150 OFF acima de R$ 1.500 | R$ 300 OFF acima de R$ 3.000 | R$ 600 OFF acima de R$ 6.000",
        "Válido para TVs e Eletrônicos", "pel-cbfaixas"))


def c_r5_e3_quem_ainda_nao_usou_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", _cp(
        "pelando", MAGALU, "TVMAGALU300", "Cupom Magalu R$ 300 OFF em TVs acima de R$ 3.000",
        "Quem ainda não usou, corre que acaba hoje!", "pel-tvmagalu300-usou"))


def c_r5_e4_tclamz200_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", R5_TCLAMZ200)


def c_r5_e4_tvs300_cloud(d, mp):
    return _rodada_real_com_cupom(d, mp, "cloud", R5_TVS300)


def c_r5_e4_exclusao_de_outras_tvs_nao_barra_o_codigo(d, mp):
    """Via restricao_do_codigo, esses anúncios (no state, 30 dias, qualquer modo) não barram o código em outro post."""
    _dados_reais(d, mp)
    est = Estado("cloud")
    genericos = [_cp("promobit", c.loja, c.codigo, f"Economize com o cupom {c.codigo} em suas compras", "", c.id + "-2")
                 for c in (R5_TCLAMZ200, R5_TVS300)]
    vistos = est.cupons_vistos() + [{"fonte": c.fonte, "id": c.id, "loja": c.loja, "codigo": c.codigo,
                                     "titulo": c.titulo, "regra": c.regra} for c in (R5_TCLAMZ200, R5_TVS300)]
    codigos = {"Amazon|TCLAMZ200", "Magazine Luiza|TVS300"}
    return sorted(codigos & restricao_do_codigo([R5_TCLAMZ200, R5_TVS300] + genericos, vistos))


def c_r5_e5_lgoficial15_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", R5_LGOFICIAL15)


def c_r5_e5_philco12_pc(d, mp):
    return _rodada_real_com_cupom(d, mp, "pc", _cp(
        "pelando", ML, "PHILCO12", "Cupom Mercado Livre - 12% OFF Acima de R$ 99 limitado à R$ 60 em Loja Oficial Philco",
        "", "pel-philco12"))


def c_r5_e5_electrolux15_cloud(d, mp):
    return _rodada_real_com_cupom(d, mp, "cloud", _cp(
        "promobit", ML, "ELECTROLUX15",
        "CASA NOVA: 15% OFF na Loja Oficial Electrolux no Mercado Livre (acima de R$ 299) com cupom",
        "produtos Mercado Livre", "70503"))


def c_r5_e5_loja_de_marca_barra_o_codigo(d, mp):
    """O código de um anúncio de loja de marca é daquela loja: um post genérico do mesmo código (id novo) não alerta."""
    _dados_reais(d, mp)
    vistos = Estado("pc").cupons_vistos() + [{"fonte": "pelando", "id": R5_LGOFICIAL15.id, "loja": ML,
                                              "codigo": "LGOFICIAL15", "titulo": R5_LGOFICIAL15.titulo,
                                              "regra": R5_LGOFICIAL15.regra}]
    generico = _cp("promobit", ML, "LGOFICIAL15", "Cupom Mercado Livre 15% OFF", "produtos Mercado Livre", "70504")
    return sorted({"Mercado Livre|LGOFICIAL15"} & restricao_do_codigo([generico], vistos))


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
    # ---- rodada 4: regressões da rodada 3 ----
    ("R4-TVMAGALU300-alerta-com-TV-la-e-vai-ao-painel", c_r4_tvmagalu300_alerta_e_painel,
     (["TVMAGALU300"], True, ["TVMAGALU300"])),
    ("R4-TVMAGALU300-Pelando-no-state-nao-silencia-o-Promobit", c_r4_tvmagalu300_pelando_no_estado_nao_silencia_o_promobit,
     ([], ["TVMAGALU300"], ["TVMAGALU300"])),
    ("R4-TVMAGALU300-ja-alertado-no-Pelando-nao-repete-no-Promobit", c_r4_tvmagalu300_ja_alertado_nao_repete, []),
    ("R4-MELI15TUDO-alerta", c_r4_meli15tudo_alerta, ["MELI15TUDO"]),
    ("R4-TVKABUM10-SMARTTV250-PIX300-alertam", c_r4_varios_em_alertam, ["PIX300", "SMARTTV250", "TVKABUM10"]),
    ("R4-TVKABUM10-SMARTTV250-PIX300-nao-barram-outro-post", c_r4_varios_em_nao_barram_outro_post,
     ([], ["PIX300", "SMARTTV250", "TVKABUM10"])),
    ("R4-TCLTV250-alerta", c_r4_tcltv250_alerta, ["TCLTV250"]),
    ("R4-CBFRETE200-e-APPMAGALU350-alertam", c_r4_frete_e_app_alertam, ["APPMAGALU350", "CBFRETE200"]),
    # (e) o que o cloud sabe do código (DESCONTOJA só "em Casa", promobit:69522) vale no pc: sem alerta e fora do painel
    ("R4-DESCONTOJA-pc-com-os-state-reais-nao-alerta", c_r4_descontoja_pc_gerar_alertas, (True, [], [])),
    ("R4-DESCONTOJA-pc-run.main-sem-alerta-e-fora-do-latest", c_r4_descontoja_pc_run_main, ([], [])),
    ("R4-DESCONTOJA-pc-sem-o-arquivo-do-cloud-nao-quebra", c_r4_descontoja_sem_o_arquivo_do_cloud, ["DESCONTOJA"]),
    ("R4-DESCONTOJA-Casa-visto-ha-mais-de-30-dias-nao-barra", c_r4_descontoja_casa_ha_mais_de_30_dias, ["DESCONTOJA"]),
    # ---- ZOOM (18/09): dados reais da main ----
    # (tem 3.279?, primeira loja do resumo, Amazon direta do pc com quando, linhas da KaBuM!, menor já visto)
    ("ZOOM-resumo-do-cloud-sem-a-Amazon-parada-do-Zoom", c_zoom_resumo_cloud_real,
     (False, "• Magazine Luiza/Magalu: <b>R$ 3.561,55</b> · 10x R$ 374,90 sem juros", True,
      ["• KaBuM!: <b>R$ 4.184,88</b> · 10x de R$ 418,48 sem juros"], True)),
    ("ZOOM-loja-que-so-o-agregador-conhece-continua", c_zoom_resumo_sem_o_pc, (True, False)),
    # com o pc: nenhum alerta da Amazon do Zoom e o mínimo fica 2.991,60; sem o pc: 🏆🔻🎯 e mínimo 2.800 (como hoje)
    ("ZOOM-Amazon-2800-no-Zoom-nao-alerta-quando-o-pc-ve-a-Amazon", c_zoom_amazon_2800_no_cloud,
     (([], 2991.6), 1, True, 2800.0)),
    ("ZOOM-partida-e-TV-la-do-cupom-com-o-preco-direto", c_zoom_partida_e_cupom, (False, True)),
    ("ZOOM-minimo-antigo-vindo-do-Zoom-nao-vale", c_zoom_minimo_antigo_do_agregador, (2991.6, MAGALU)),
    ("ZOOM-linhas-reais-do-Zoom-sao-agregador", c_zoom_linhas_reais_sao_agregador,
     [(AMAZON, True), (KABUM, True), (MAGALU, True)]),
    # ---- rodada 4, 2ª passada: rodadas do verificador com os arquivos reais (a main é a referência) ----
    # sem alerta e fora do painel, como na main (teto do item/compra, produto renovado, cliente novo)
    ("R4b-E1-ATE500-cloud-produtos-ate-R$500-sem-alerta", c_r4b_e1_ate500_cloud, ([], [])),
    ("R4b-E2-TUDO99-pc-itens-ate-R$99-sem-alerta", c_r4b_e2_tudo99_pc, ([], [])),
    ("R4b-E3-RENOVA20-pc-Renovados-sem-alerta", c_r4b_e3_renova20_pc, ([], [])),
    ("R4b-E4-RENOVEJA-cloud-Recondicionados-sem-alerta", c_r4b_e4_renoveja_cloud, ([], [])),
    ("R4b-E5-FAIXA30-pc-compras-de-200-ate-499-sem-alerta", c_r4b_e5_faixa30_pc, ([], [])),
    ("R4b-E8-BEMVINDO20-cloud-clientes-novos-no-app-sem-alerta", c_r4b_e8_bemvindo20_cloud, ([], [])),
    # alerta com o preço da TV e no painel, como na main (a lista de tamanhos inclui a 55")
    ("R4b-E6-TCLTV250-pc-50-55-65-com-aspas-alerta", c_r4b_e6_tcltv250_pc, (1, True, ["TCLTV250"])),
    ("R4b-E7-TVGRANDE300-cloud-50-a-65-com-aspas-alerta", c_r4b_e7_tvgrande300_cloud, (1, True, ["TVGRANDE300"])),
    # ---- rodada 5 (passada final): a mesma linha 🎟️ e o mesmo painel da main ----
    ("R5-E1-TVML400-pc-alerta-como-a-main", c_r5_e1_tvml400_pc,
     (["• <b>Mercado Livre</b> <code>TVML400</code> — Cupom Mercado Livre - 10% OFF Acima de R$ 1.999 limitado à "
       "R$ 400 em Smart TVs · TV lá: R$ 3.491,03"], ["TVML400"])),
    ("R5-E1-Smart-TVs-ate-30-09-cloud-alerta-como-a-main", c_r5_e1_smart_tvs_ate_30_09_cloud,
     (["• <b>Magazine Luiza</b> <code>SMART300</code> — Cupom Magalu R$ 300 OFF em Smart TVs até 30/09 · TV lá: "
       "R$ 3.561,55"], ["SMART300"])),
    ("R5-E1-Smart-TVs-hoje-ate-as-23-59-pc-alerta-como-a-main", c_r5_e1_smart_tvs_ate_23_59_pc,
     (["• <b>Magazine Luiza</b> <code>SMART300</code> — Cupom Magalu R$ 300 OFF em Smart TVs hoje até às 23:59"],
      ["SMART300"])),
    ("R5-E2-ESCADA500-cloud-alerta-como-a-main", c_r5_e2_escada500_cloud,
     (["• <b>Magazine Luiza</b> <code>ESCADA500</code> — Cupom Magalu progressivo: R$ 100 OFF acima de R$ 1.000, "
       "R$ 300 OFF acima de R$ 3.000 e R$  · TV lá: R$ 3.561,55"], ["ESCADA500"])),
    ("R5-E2-Casas-Bahia-150-300-600-pc-alerta-como-a-main", c_r5_e2_cb_faixas_pc,
     (["• <b>Casas Bahia</b> <code>CBFAIXAS</code> — Cupom Casas Bahia: R$ 150 OFF acima de R$ 1.500 | R$ 300 OFF "
       "acima de R$ 3.000 | R$ 600 OF · TV lá: R$ 3.599,09"], ["CBFAIXAS"])),
    ("R5-E3-TVMAGALU300-quem-ainda-nao-usou-pc-alerta-como-a-main", c_r5_e3_quem_ainda_nao_usou_pc,
     (["• <b>Magazine Luiza</b> <code>TVMAGALU300</code> — Cupom Magalu R$ 300 OFF em TVs acima de R$ 3.000"],
      ["TVMAGALU300"])),
    ("R5-E4-TCLAMZ200-pc-alerta-como-a-main", c_r5_e4_tclamz200_pc,
     (["• <b>Amazon</b> <code>TCLAMZ200</code> — Cupom Amazon R$ 200 OFF em Smart TVs TCL · TV lá: R$ 3.749,00"],
      ["TCLAMZ200"])),
    ("R5-E4-TVS300-cloud-alerta-como-a-main", c_r5_e4_tvs300_cloud,
     (["• <b>Magazine Luiza</b> <code>TVS300</code> — Cupom Magalu R$ 300 OFF em TVs · TV lá: R$ 3.561,55"],
      ["TVS300"])),
    ("R5-E4-exclusao-de-outras-TVs-nao-barra-o-codigo", c_r5_e4_exclusao_de_outras_tvs_nao_barra_o_codigo, []),
    # E5: sem alerta e fora do painel, como na main
    ("R5-E5-LGOFICIAL15-pc-sem-alerta", c_r5_e5_lgoficial15_pc, ([], [])),
    ("R5-E5-PHILCO12-pc-sem-alerta", c_r5_e5_philco12_pc, ([], [])),
    ("R5-E5-ELECTROLUX15-cloud-sem-alerta", c_r5_e5_electrolux15_cloud, ([], [])),
    ("R5-E5-loja-de-marca-barra-o-codigo-no-post-generico", c_r5_e5_loja_de_marca_barra_o_codigo,
     ["Mercado Livre|LGOFICIAL15"]),
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
