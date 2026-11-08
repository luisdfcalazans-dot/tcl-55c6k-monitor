"""Cupons citados nos posts dos canais do Telegram (pedido de 08/11/2026: "faça a varredura também nos cupons que
aparecem nas mensagens dos grupos do telegram").

Cobre: os padrões reais das prévias (linha "valor + mínimo + código(s)", código na linha de baixo, código antes do
valor, percentual com limite, "Cupom: X" do post de produto, cabeçalho de seção com loja e validade, esgotado,
"quem resgatou"), a lista negra, a loja (prefixo da plataforma, cabeçalho, hashtag, link), a consolidação (espelhos,
valores diferentes, ids estáveis, esgotado depois), o HTML da prévia (fixtures com mensagens reais de 08/11/2026), a
fonte (cupons junto com as ofertas, que não mudam), a lista diária (janela de 2 dias, DDMM, começo futuro, veto por
esgotado, registro mais completo entre Promobit e Telegram, teto de linhas por loja) e o run.py (vai para a lista e
nunca para o "Novo cupom aplicável"). Nada vai à rede e nada lê ou grava o docs/data do repositório.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from monitor import config, cupons_telegram as ct, lista_cupons as lc
from monitor.estado import Estado
from monitor.models import Cupom
from monitor.sources import telegram_public
from monitor.util import TZ_BR, agora, agora_iso, hoje

FX = Path(__file__).parent / "fixtures"
PUB = "2026-11-08T12:00:00-03:00"
ALI = "https://s.click.aliexpress.com/e/_c3KAhHcb"
MELI = "https://meli.la/2susU5E"


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    monkeypatch.setattr(config, "CUPONS_ATIVOS_DIAS", 3.0)
    monkeypatch.setattr(config, "CUPONS_ATIVOS_DIAS_TELEGRAM", 2.0)
    monkeypatch.setattr(config, "CUPONS_ATIVOS_MAX_POR_LOJA", 0)
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", None)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    return tmp_path


def _cits(texto, links=(), canal="canal", post="canal/1", codes=(), riscados=(), publicado=PUB):
    return ct.citacoes_do_post(texto, list(links), canal, post, publicado, list(codes), list(riscados))


def _trios(cits):
    return [(c.loja, c.codigo, c.titulo) for c in cits]


def _iso(**delta) -> str:
    return (agora() - timedelta(**delta)).isoformat(timespec="seconds")


def _congela(monkeypatch, quando: datetime) -> None:
    from monitor import util

    monkeypatch.setattr(util, "agora", lambda: quando)
    monkeypatch.setattr(lc, "agora", lambda: quando)


# ---------------------------------------------------------------------------------------------------------------------
# 1) linha "valor + mínimo + código(s)"
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("linha, esperado", [
    ("🏷 R$ 785 OFF em R$ 4200: AFFNOV11", [("AFFNOV11", "R$ 785 OFF acima de R$ 4.200")]),
    ("🏷 R$ 670 OFF em R$ 4.200: AFFNOV22", [("AFFNOV22", "R$ 670 OFF acima de R$ 4.200")]),
    ("🏷 R$ 16 OFF em R$ 80: AFFNOV01 ou AEMEGA1",
     [("AFFNOV01", "R$ 16 OFF acima de R$ 80"), ("AEMEGA1", "R$ 16 OFF acima de R$ 80")]),
    ("🎟R$800 OFF em R$4000: IFP1ZYZM", [("IFP1ZYZM", "R$ 800 OFF acima de R$ 4.000")]),        # sem espaço (Linguiça)
    ("R$40 off em pedidos acima de R$250: LINGUICA40", [("LINGUICA40", "R$ 40 OFF acima de R$ 250")]),
    ("🛍️ R$ 125 OFF a partir de R$ 740: AFFNOV04", [("AFFNOV04", "R$ 125 OFF acima de R$ 740")]),
    ("🏷 R$ 650 OFF em R$ 3.800: AESUPER5", [("AESUPER5", "R$ 650 OFF acima de R$ 3.800")]),
    ("🎟️ R$ 670 OFF em R$ 4.200 - Cupom: AFFNOV22", [("AFFNOV22", "R$ 670 OFF acima de R$ 4.200")]),
    ("🔹R$ 16 off acima de R$ 80: ISKANDAR1 |IFPQWR8M | AEMEGA1",                               # Iskandar, com "|"
     [("ISKANDAR1", "R$ 16 OFF acima de R$ 80"), ("IFPQWR8M", "R$ 16 OFF acima de R$ 80"),
      ("AEMEGA1", "R$ 16 OFF acima de R$ 80")]),
    ("🏷️ R$16 OFF em R$80: peperaio1 / AEMEGA1",                                                # minúsculas (Peperaio)
     [("PEPERAIO1", "R$ 16 OFF acima de R$ 80"), ("AEMEGA1", "R$ 16 OFF acima de R$ 80")]),
])
def test_linha_valor_minimo_e_codigos(linha, esperado):
    cits = _cits("🚨 Cupons novos AliExpress\n" + linha + "\nResgate aqui:\n" + ALI, [ALI])
    assert [(c.codigo, c.titulo) for c in cits] == esperado
    assert {c.loja for c in cits} == {"AliExpress"} and {c.tipo for c in cits} == {"lista"}
    assert all(c.chave_valor.startswith("R") for c in cits)


def test_codigos_da_plataforma_dizem_a_loja_sem_link_nem_cabecalho():
    # o ISKANDAR1 vai junto com os códigos do AliExpress da mesma linha
    cits = _cits("🔹R$ 16 off acima de R$ 80: ISKANDAR1 |IFPQWR8M | AEMEGA1")
    assert {(c.loja, c.codigo) for c in cits} == {("AliExpress", "ISKANDAR1"), ("AliExpress", "IFPQWR8M"),
                                                  ("AliExpress", "AEMEGA1")}
    assert ct.loja_do_codigo("AFFNOV9") == ct.loja_do_codigo("AESUPER5") == ct.loja_do_codigo("IFPTS24X") == "AliExpress"
    assert ct.loja_do_codigo("LINGUICA40") is None and ct.loja_do_codigo("BORTODEZ") is None


# ---------------------------------------------------------------------------------------------------------------------
# 2) código na linha de baixo; 3) código antes do valor; 4) percentuais
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("texto, links, esperado", [
    # chinacuponsbr: o código embaixo, às vezes dois
    ("CUPONS ALIEXPRESS\nR$785 de desconto em R$4200\nAFFNOV11\nR$800 de desconto em R$4000\nIFPR2XGX IFPE6TPU", [],
     [("AliExpress", "AFFNOV11", "R$ 785 OFF acima de R$ 4.200"), ("AliExpress", "IFPR2XGX", "R$ 800 OFF acima de R$ 4.000"),
      ("AliExpress", "IFPE6TPU", "R$ 800 OFF acima de R$ 4.000")]),
    # Peperaio: "🎟️ Cupom:" embaixo
    ("💸 R$ 670 OFF acima de R$ 4200\n🎟️ Cupom: AFFNOV22", [ALI], [("AliExpress", "AFFNOV22", "R$ 670 OFF acima de R$ 4.200")]),
    # nerdofertas (Shopee): centavos
    ("🏷 R$ 10,00 OFF em R$ 40,00\n🏷 Cupom: FF5E8II49K", ["https://s.shopee.com.br/60T0V28onj"],
     [("Shopee", "FF5E8II49K", "R$ 10 OFF acima de R$ 40")]),
    # pobregram: % com limite e o código só de letras depois de "CUPOM:"
    ("➡️ 25% OFF em R$79, limitado a R$80 OFF\n🎟 CUPOM: COMPRAHOJE", [MELI],
     [("Mercado Livre", "COMPRAHOJE", "25% OFF acima de R$ 79, limite de R$ 80")]),
    # OfertasDoDia/hardmob: o código antes do valor (cupom.cc é genérico: a loja vem do prefixo)
    ("Cupons AliExpress\nAFFNOV04 R$ 125 OFF acima de R$ 740\nAFFNOV22 R$ 670 OFF acima de R$ 4.200 🆕",
     ["https://cupom.cc/abc"],
     [("AliExpress", "AFFNOV04", "R$ 125 OFF acima de R$ 740"), ("AliExpress", "AFFNOV22", "R$ 670 OFF acima de R$ 4.200")]),
    # Iskandar no ML, em 3 linhas
    ("📝 TAMOSJUNTO 👉 10% OFF\nTecnologia\nCompra mínima: R$149 | Desconto máx: R$200", [MELI],
     [("Mercado Livre", "TAMOSJUNTO", "10% OFF acima de R$ 149, limite de R$ 200")]),
])
def test_codigo_embaixo_ou_antes_do_valor(texto, links, esperado):
    assert _trios(_cits(texto, links)) == esperado


@pytest.mark.parametrize("linha, titulo", [
    ("🏷 10% OFF em R$149, Limite de R$ 200 OFF: TAMOSJUNTO", "10% OFF acima de R$ 149, limite de R$ 200"),
    ("🏷 10% OFF acima de R$ 79, limite R$ 30 OFF: BORTODEZ", "10% OFF acima de R$ 79, limite de R$ 30"),
    ("✨ 10% OFF a partir de R$ 79, Limite de R$ 30: BORTODEZ", "10% OFF acima de R$ 79, limite de R$ 30"),
    ("🏷 30% OFF, limite R$ 500 OFF: COMBINACUPOM", "30% OFF, limite de R$ 500"),
    ("🏷 25%  OFF , Limite de R$ 500  OFF :  MUITOBARATO", "25% OFF, limite de R$ 500"),     # Xavier (busca)
])
def test_percentual_com_limite_mercado_livre(linha, titulo):
    [c] = _cits("🚨 Cupons Mercado Livre\n" + linha + "\nResgate aqui:\n" + MELI, [MELI])
    assert (c.loja, c.titulo) == ("Mercado Livre", titulo)
    # a lista lê desconto, mínimo e teto do título canônico
    v = lc.valor_do_cupom(c.titulo)
    assert v.desconto[0] == "%" and v.teto is not None


def test_chave_do_valor_ignora_o_limite_do_desconto_fixo():
    [a] = _cits("🛍️ R$ 10 OFF a partir de R$ 99, Limite de R$ 10: TODOSITE0811", [MELI])
    [b] = _cits("🏷 R$ 10 OFF em R$ 99: TODOSITE0811", [MELI])
    assert a.chave_valor == b.chave_valor == "R10-99" and a.titulo == b.titulo == "R$ 10 OFF acima de R$ 99"
    assert ct.chave_do_valor("%", 15, 500, 100) == "P15-500-100" and ct.chave_do_valor("R$", None, None, None) == "post"


def test_titulo_canonico_e_lido_pela_lista():
    assert lc.texto_do_valor(lc.valor_do_cupom("R$ 785 OFF acima de R$ 4.200")) == "R$ 785 OFF · mín. R$ 4.200"
    assert lc.texto_do_valor(lc.valor_do_cupom("10% OFF acima de R$ 149, limite de R$ 200")) == \
        "10% OFF · mín. R$ 149 · até R$ 200"
    assert lc.texto_do_valor(lc.valor_do_cupom("R$ 580 OFF acima de R$ 3.700")) == "R$ 580 OFF · mín. R$ 3.700"


# ---------------------------------------------------------------------------------------------------------------------
# 5) post de produto
# ---------------------------------------------------------------------------------------------------------------------
def test_post_de_produto_xavier_do_ps5_tira_as_moedas():
    texto = ("🚨 PlayStation 5 Edição Digital 825GB 1 Controle Branco Sony\n💵 R$ 3.690\nOu em até 12x\n"
             f"🎟 Cupom: AFFNOV11 + 740 moedas no app\n{ALI}\n(Anúncio)")
    [c] = _cits(texto, [ALI], codes=["AFFNOV11"])
    assert (c.loja, c.codigo, c.tipo, c.chave_valor) == ("AliExpress", "AFFNOV11", "produto", "post")
    assert c.titulo == "cupom citado no post de PlayStation 5 Edição Digital 825GB por R$ 3.690"


def test_post_de_produto_com_chamada_antes_do_nome():
    # Linguiça, 08/11 16:31: a 1ª linha é a chamada; o produto vem embaixo (o PS5 do AliExpress)
    texto = (f"Pronto para libertar das amarras da sociedade!\nPlaystation 5 Digital Edition 825Gb\n{ALI}\n"
             "R$3.760,76 com cupom AFFNOV09\n*Estoque no Brasil, sem taxas adicionais!")
    [c] = _cits(texto, [ALI, "https://linktr.ee/exemplo"])
    assert (c.loja, c.codigo) == ("AliExpress", "AFFNOV09")
    assert c.titulo == "cupom citado no post de Playstation 5 Digital Edition 825Gb por R$ 3.760,76"


@pytest.mark.parametrize("linha, codigos", [
    ("🏷 Cupom: AFFNOV11 ou AFFNOV09 + 740 Moedas no app", ["AFFNOV11", "AFFNOV09"]),        # nerdofertas
    ("📝 Cupom: AFFNOV11 ou AFFNOV09 + 750 moedas no APP", ["AFFNOV11", "AFFNOV09"]),        # Iskandar
    ("🏷️ Use cupom: AFFNOV11 ou AFFNOV09 + Moedas no App", ["AFFNOV11", "AFFNOV09"]),       # tecnoart
    ("💵 R$ 3.837,02 com cupom: AFFNOV22", ["AFFNOV22"]),
    ("R$3.760,76 com cupom AFFNOV09", ["AFFNOV09"]),                                          # Linguiça, sem ":"
    ("🎯 Usem o cupom: AFFNOV11", ["AFFNOV11"]),                                               # promotop
    # cupom de UMA loja dentro do AliExpress junto com o da plataforma: só o da plataforma
    ("🎟 Cupom: LIBRETX5X3DD + AEMEGA6", ["AEMEGA6"]),
    ("🎟 Cupom: AFFNOV11 + Cupom da loja", ["AFFNOV11"]),
])
def test_post_de_produto_aliexpress(linha, codigos):
    cits = _cits(f"🚨 Console PlayStation 5 Slim Digital\n💰 R$ 3.679 em 12x SEM JUROS\n{linha}\n{ALI}", [ALI])
    assert [c.codigo for c in cits] == codigos
    assert {c.loja for c in cits} == {"AliExpress"}


def test_post_de_produto_com_o_codigo_na_linha_de_baixo():
    texto = "🚀 Ghost of Yotei Complete Edition PS5 Físico\n💹 R$ 228,55 com cupom:\nJOGOS0811\n👇 Link do produto:\n" + MELI
    [c] = _cits(texto, [MELI, "https://linktr.ee/exemplo"])
    assert (c.loja, c.codigo) == ("Mercado Livre", "JOGOS0811")
    assert c.titulo == "cupom citado no post de Ghost of Yotei Complete Edition PS5 por R$ 228,55"   # até 6 palavras
    # só letras logo depois de "com cupom:" (o código vem embaixo)
    [c] = _cits("📦 Kit Essencial\n💸 R$ 389,00 com cupom:\nPROMODEZ\n" + MELI, [MELI])
    assert c.codigo == "PROMODEZ"
    # "TAMOSJUNTO + CUPOM DE R$ 200 OFF DA LOJA": o código do começo da linha
    [c] = _cits("⚡ Smart Tv\n🤑 R$ 1.979,00 no PIX com cupom:\nTAMOSJUNTO + CUPOM DE R$ 200 OFF DA LOJA\n" + MELI, [MELI])
    assert c.codigo == "TAMOSJUNTO"


# ---------------------------------------------------------------------------------------------------------------------
# lista negra
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("texto", [
    "🚨 Cupons novos AliExpress\nResgate aqui:\n" + ALI,
    "🎟️ Resgate o cupom de R$ 20 OFF no anúncio\n" + MELI,
    "🚨 Cupons Mercado Livre\n🏷 R$ 100 OFF em R$ 300\nResgate aqui:\n" + MELI,       # sem código
    "Use o cupom PIX no app\n" + MELI,
    "Cupom: APP\n" + MELI,
    "🎟 Cupom: OFF\n" + MELI,
    "CUPOM LINK abaixo\n" + MELI,
    "🔥 CUPOM VALENDO 🔥\nAPROVEITE\n" + MELI,
    "Cupons QUENTINHOS para hoje\n" + MELI,
    "Smart TV TCL 55C6K com cupom 55C6K\n" + MELI,                                     # código de modelo
    "PS5 825GB com cupom: 825GB\n" + MELI,                                              # medida
    "Cupom: MOEDAS\n" + ALI,
])
def test_lista_negra_nao_vira_codigo(texto):
    assert _cits(texto, [MELI, ALI]) == []


def test_so_o_codigo_antes_da_palavra_comum():
    [c] = _cits("🚨 Kit 3 Camisetas\n💵 R$ 62,94\n🎟 Cupom: COMBINACUPOM + cupom de 10% OFF da loja no anúncio\n" + MELI,
                [MELI], codes=["COMBINACUPOM"])
    assert c.codigo == "COMBINACUPOM"
    # só letras e sem ":" nem <code>: não é código ("Cupom SHOPEE liberado")
    assert _cits("Cupom SHOPEE liberado hoje\nhttps://s.shopee.com.br/x", ["https://s.shopee.com.br/x"]) == []


# ---------------------------------------------------------------------------------------------------------------------
# 6) validade, esgotado, "quem resgatou"
# ---------------------------------------------------------------------------------------------------------------------
def test_secoes_com_validade_e_a_validade_do_evento():
    texto = ("🔥 Promo 11.11 do AliExpress\nVendas Oficiais: 01.11.2026 às 00h01 até 18.11.2026 às 23h59\n"
             "CUPONS ESPECIAIS (Válidos de 10/11 até 12/11)\n🎟 R$600 OFF em R$3000: IFPTRZAQ\n"
             "🎟 R$800 OFF em R$4000: IFP1ZYZM\nCUPONS REGULARES\n🎟 R$750 OFF em R$4500: AFFNOV09\n" + ALI)
    cits = {c.codigo: c for c in _cits(texto, [ALI])}
    assert (cits["IFP1ZYZM"].inicio, cits["IFP1ZYZM"].validade) == ("2026-11-10", "2026-11-12")
    assert cits["IFP1ZYZM"].regra.startswith("CUPONS ESPECIAIS")
    # "CUPONS REGULARES" volta para a data do evento
    assert (cits["AFFNOV09"].inicio, cits["AFFNOV09"].validade) == ("2026-11-01", "2026-11-18")


@pytest.mark.parametrize("cabecalho, esperado", [
    ("CUPONS ALIEXPRESS(11/11 À 12/11)", ("2026-11-11", "2026-11-12")),
    ("🚨Especiais: Ativa dia 10.11 vai até 12.11", ("2026-11-10", "2026-11-12")),
    ("⏳ Vale até 18/11 ou enquanto durarem os cupons", (None, "2026-11-18")),
])
def test_faixas_de_data_dos_cabecalhos(cabecalho, esperado):
    [c] = _cits(f"{cabecalho}\n🏷 R$ 800 OFF em R$ 4000: IFP1ZYZM", [ALI])
    assert (c.inicio, c.validade) == esperado


def test_data_no_rodape_vale_para_o_post_todo():
    cits = _cits("🚨 Cupons novos AliExpress\n🏷 R$ 785 OFF em R$ 4200: AFFNOV11\n🏷 R$ 670 OFF em R$ 4.200: AFFNOV22\n"
                 "⏰ Vai até 18.11.2026", [ALI])
    assert {c.validade for c in cits} == {"2026-11-18"}


def test_esgotado_no_texto_riscado_e_aviso_solto():
    [c] = _cits("O cupom IFP43VOM esgotou")
    assert (c.loja, c.codigo, c.esgotado) == ("AliExpress", "IFP43VOM", True)
    assert c.titulo == "cupom citado como esgotado no Telegram"
    # código riscado (<s>)
    cits = {c.codigo: c for c in _cits("🏷 R$ 785 OFF em R$ 4200: AFFNOV11\n🏷 R$ 670 OFF em R$ 4.200: AFFNOV22",
                                       riscados=["AFFNOV11"])}
    assert cits["AFFNOV11"].esgotado and not cits["AFFNOV22"].esgotado
    # o promotop edita o post original
    [c] = _cits("❌Cupom Esgotado❌\n🚨 Console PS5 Digital\n💵 R$ 3.690\n🎯 Usem o cupom: AFFNOV11\n" + ALI, [ALI])
    assert c.esgotado
    # sem loja conhecida (nem link, nem prefixo da plataforma), o aviso fica de fora
    assert _cits("Cupom AMAIOR50 esgotado!") == []


def test_quem_resgatou_vira_restricao():
    [c] = _cits("🏷 R$ 785 OFF em R$ 4200: AFFNOV11\nCupom funcionando para quem resgatou no inicio da promoção", [ALI])
    assert c.resgatou
    [cup] = ct.consolida([c])
    assert "só para quem resgatou" in cup.regra
    assert lc.MARCA_RESGATOU in lc.valor_do_cupom(cup.titulo, cup.regra).marcas


def test_novos_compradores_vira_1a_compra():
    [c] = _cits("Cupons NOVOS Compradores\n🔹R$ 25 off acima de R$ 30: IFPNEW01", [ALI])
    assert "1ª compra" in lc.valor_do_cupom(c.titulo, c.regra).marcas


# ---------------------------------------------------------------------------------------------------------------------
# loja
# ---------------------------------------------------------------------------------------------------------------------
def test_loja_pelo_cabecalho_hashtag_e_link():
    assert _trios(_cits("#Kabum\n🏷 R$ 50 OFF acima de R$ 500: KABUM50OFF"))[0][0] == "KaBuM!"
    assert _trios(_cits("🚨 Cupons renovados Shopee\n🏷 R$ 10,00 OFF em R$ 40,00: I65FDHJK1E", ["https://cupom.cc/x"]))[0][0] \
        == "Shopee"
    assert _trios(_cits("🏷 R$ 20 OFF acima de R$ 100: MELI20OFF", [MELI]))[0][0] == "Mercado Livre"
    # link genérico e código que não é da plataforma: sem loja, fora
    assert _cits("🏷 R$ 20 OFF acima de R$ 100: GENERICO20", ["https://cutt.ly/abc"]) == []
    # links de lojas diferentes no mesmo post: o link não decide
    assert ct.loja_dos_links([MELI, ALI]) is None


def test_magalu_store_com_link_do_aliexpress_e_aliexpress():
    texto = f"PS5 Digital vendido pela Magalu Store\n💵 R$ 3.851\n🎟 Cupom: AFFNOV22\n{ALI}"
    assert telegram_public.loja_no_texto(texto, [ALI]) == "AliExpress"
    assert _cits(texto, [ALI])[0].loja == "AliExpress"
    # sem link de marketplace, o texto continua decidindo (como antes)
    assert telegram_public.loja_no_texto("Cupom Magalu: INFLU100", ["https://encurtou.com/x"]) == "Magazine Luiza"


# ---------------------------------------------------------------------------------------------------------------------
# consolidação
# ---------------------------------------------------------------------------------------------------------------------
def test_espelhos_viram_um_cupom_e_ids_estaveis():
    texto = "Cupons AliExpress\nAFFNOV22 R$ 670 OFF acima de R$ 4.200 🆕"
    cits = _cits(texto, canal="hardmob_promo", post="hardmob_promo/10", publicado="2026-11-08T10:00:00-03:00") + \
        _cits(texto, canal="ofertasdodia", post="ofertasdodia/20", publicado="2026-11-08T10:01:00-03:00") + \
        _cits("🏷 R$ 670 OFF em R$ 4.200: AFFNOV22", canal="xaviertechpromo", post="xaviertechpromo/30",
              publicado="2026-11-08T09:00:00-03:00")
    [c] = ct.consolida(cits)
    assert (c.fonte, c.loja, c.codigo, c.id) == ("telegram", "AliExpress", "AFFNOV22", "AliExpress|AFFNOV22|R670-4200")
    assert c.chave == "telegram:AliExpress|AFFNOV22|R670-4200"
    assert c.url == "https://t.me/ofertasdodia/20" and c.publicado == "2026-11-08T10:01:00-03:00"   # a mais recente
    assert c.extra["canais"] == ["hardmob_promo", "ofertasdodia", "xaviertechpromo"]
    assert c.extra["n_grupos"] == 2   # hardmob e OfertasDoDia são espelhos
    # a mesma citação lida duas vezes (1ª página e busca) conta uma
    assert len(ct.consolida(cits + cits)) == 1


def test_valores_diferentes_do_mesmo_codigo_ficam_separados():
    cits = _cits("🏷 R$ 650 OFF em R$ 3.800: AESUPER2", post="a/1") + _cits("🏷 R$ 540 OFF em R$ 2.700: AESUPER2", post="b/2")
    ids = sorted(c.id for c in ct.consolida(cits))
    assert ids == ["AliExpress|AESUPER2|R540-2700", "AliExpress|AESUPER2|R650-3800"]
    # na lista: uma linha, com o outro valor junto
    regs = [dict(c.to_dict(), publicado=_iso(hours=1)) for c in ct.consolida(cits)]
    [r] = lc.cupons_ativos(regs, set())["AliExpress"]
    assert "outro anúncio diz" in r["_texto"]


def test_esgotado_depois_da_ultima_citacao_ativa():
    ativa = _cits("🏷 R$ 785 OFF em R$ 4200: AFFNOV11", post="x/1", publicado="2026-11-08T09:00:00-03:00")
    esgotou = _cits("O cupom AFFNOV11 esgotou", post="i/2", publicado="2026-11-08T11:00:00-03:00")
    [c] = ct.consolida(ativa + esgotou)
    assert c.extra["esgotado_em"] == "2026-11-08T11:00:00-03:00" and c.titulo == "R$ 785 OFF acima de R$ 4.200"
    # voltou: uma citação ativa mais nova que o "esgotou"
    voltou = _cits("🏷 R$ 785 OFF em R$ 4200: AFFNOV11", post="x/3", publicado="2026-11-08T12:00:00-03:00")
    [c] = ct.consolida(ativa + esgotou + voltou)
    assert "esgotado_em" not in c.extra
    # só o aviso: um registro inativo (serve para tirar o código das outras fontes)
    [c] = ct.consolida(esgotou)
    assert c.extra["esgotado_em"] and lc.motivo_inativo(c.to_dict(), set()) == "esgotado"


# ---------------------------------------------------------------------------------------------------------------------
# HTML da prévia (mensagens reais de 08/11/2026)
# ---------------------------------------------------------------------------------------------------------------------
def _fx(nome: str) -> str:
    return (FX / nome).read_text(encoding="utf-8")


def test_previa_real_do_xavier():
    html = _fx("telegram_cupons_xaviertechpromo_2026-11-08.html")
    cits = telegram_public.citacoes_do_html(html, "xaviertechpromo")
    por = {(c.codigo, c.chave_valor): c for c in cits}
    assert por[("AFFNOV11", "R785-4200")].titulo == "R$ 785 OFF acima de R$ 4.200"
    assert por[("AFFNOV09", "R750-4500")].loja == "AliExpress"
    assert por[("AFFNOV22", "R670-4200")].regra == "Cupons novos AliExpress"
    assert por[("AEMEGA8", "R580-3700")].post == "xaviertechpromo/383712"
    assert por[("AFFNOV11", "R785-4200")].publicado == "2026-11-08T12:34:49-03:00"     # <time> UTC -> Brasília
    # lista do ML com códigos datados e a da Shopee
    assert por[("ELETRO0811", "P15-500-100")].titulo == "15% OFF acima de R$ 500, limite de R$ 100"
    assert por[("I65FDHJK1E", "R10-40")].loja == "Shopee"
    # post de produto com 4 códigos (os 3 da plataforma e um alternativo)
    assert {c.codigo for c in cits if c.post == "xaviertechpromo/384115"} == {"ISKANDAR4", "AFFNOV04", "AEMEGA4", "M1RC35BR"}
    assert {(c.loja, c.codigo) for c in cits if c.post == "xaviertechpromo/384105"} == {("Mercado Livre", "JOGOS0811")}
    # post sem cupom (Amazon) não vira nada
    assert not [c for c in cits if c.post == "xaviertechpromo/384104"]
    # as ofertas de produto da mesma página não mudam com a extração de cupom
    assert telegram_public.parse_canal(html, "xaviertechpromo") == \
        telegram_public.parse_canal_e_cupons(html, "xaviertechpromo")[0]


def test_previa_real_do_linguica():
    cits = telegram_public.citacoes_do_html(_fx("telegram_cupons_linguicapromocoes_2026-11-08.html"), "linguicapromocoes")
    por = {c.codigo: c for c in cits}
    assert (por["IFP1ZYZM"].titulo, por["IFP1ZYZM"].inicio, por["IFP1ZYZM"].validade) == \
        ("R$ 800 OFF acima de R$ 4.000", "2026-11-10", "2026-11-12")
    assert (por["AFFNOV09"].validade, por["AFFNOV09"].regra) == ("2026-11-18", "CUPONS REGULARES")
    assert por["LINGUICA580"].loja == "AliExpress" and por["LINGUICA580"].titulo == "R$ 580 OFF acima de R$ 3.700"
    assert por["TAMOSJUNTO"].loja == "Mercado Livre" and por["TAMOSJUNTO"].tipo == "produto"
    assert por["JOGOS0811"].titulo.startswith("cupom citado no post de Ghost of Yotei")
    assert por["MODABELEZA0811"].titulo == "20% OFF acima de R$ 89, limite de R$ 30"
    # "Produtos mais vendidos (clique em mostrar mais)" é a vitrine do canal, não restrição do cupom
    assert "selecionados" not in por["TODOSITE0811"].regra


def _post_html(texto_html: str, data: str = "2026-11-08T15:00:00+00:00", post: str = "canal/7") -> str:
    return (f'<div class="tgme_widget_message" data-post="{post}"><div class="tgme_widget_message_text">{texto_html}'
            f'</div><time datetime="{data}"></time></div>')


def test_html_sintetico_com_code_riscado_e_hora_utc():
    html = _post_html('<i class="emoji"><b>🏷</b></i> R$ 785 OFF em R$ 4200: <s><code>AFFNOV11</code></s><br/>'
                      '<i class="emoji"><b>🏷</b></i> R$ 25 OFF em R$ 199: <code>BORTODEZ</code><br/>'
                      f'<a href="{ALI}">{ALI}</a>')
    cits = {c.codigo: c for c in telegram_public.citacoes_do_html(html, "canal")}
    assert cits["AFFNOV11"].esgotado            # riscado
    assert cits["BORTODEZ"].loja == "AliExpress"  # só letras, mas dentro de <code>
    assert cits["BORTODEZ"].publicado == "2026-11-08T12:00:00-03:00"


def test_fonte_devolve_cupons_e_as_ofertas_nao_mudam(monkeypatch):
    xavier = _fx("telegram_cupons_xaviertechpromo_2026-11-08.html")
    linguica = _fx("telegram_cupons_linguicapromocoes_2026-11-08.html")
    monkeypatch.setattr(config, "TELEGRAM_CANAIS_PUBLICOS", ["xaviertechpromo", "linguicapromocoes"])
    monkeypatch.setattr(config, "TELEGRAM_CANAIS_BUSCA", [])
    monkeypatch.setattr(config, "TELEGRAM_CANAIS_CUPONS", ["chinacuponsbr"])
    monkeypatch.setattr(config, "TELEGRAM_BUSCA_CUPONS_CANAIS", ["xaviertechpromo", "IskandarSouza"])
    pedidas: list[str] = []

    def site(url, **k):
        pedidas.append(url)
        if "chinacuponsbr" in url:
            raise ConnectionError("fora do ar")   # página extra falhando não derruba nada
        return linguica if "linguica" in url else xavier

    monkeypatch.setattr(telegram_public, "get_html", site)
    ofertas, cupons = telegram_public.TelegramPublico().coletar()
    # 1ª página de cada canal, o canal só de cupom e a busca por "OFF" só no canal de listas que está sendo lido
    assert pedidas == ["https://t.me/s/xaviertechpromo", "https://t.me/s/linguicapromocoes", "https://t.me/s/chinacuponsbr",
                       "https://t.me/s/xaviertechpromo?q=OFF"]
    assert ofertas == telegram_public.parse_canal(xavier, "xaviertechpromo") + \
        telegram_public.parse_canal(linguica, "linguicapromocoes")
    por = {c.id: c for c in cupons}
    assert all(c.fonte == "telegram" for c in cupons)
    c = por["AliExpress|AFFNOV09|R750-4500"]
    assert set(c.extra["canais"]) == {"xaviertechpromo", "linguicapromocoes"} and c.validade == "2026-11-18"
    assert por["AliExpress|IFP1ZYZM|R800-4000"].extra["inicio"] == "2026-11-10"


# ---------------------------------------------------------------------------------------------------------------------
# lista diária
# ---------------------------------------------------------------------------------------------------------------------
def _tg(codigo, titulo, loja="AliExpress", publicado=None, **kw):
    return {"fonte": "telegram", "loja": loja, "codigo": codigo, "titulo": titulo, "url": "https://t.me/canal/1",
            "id": f"{loja}|{codigo}|x", "regra": kw.pop("regra", ""), "validade": kw.pop("validade", None),
            "publicado": publicado or _iso(hours=2), "extra": kw.pop("extra", {}), **kw}


def test_janela_do_telegram_dois_dias():
    assert lc.motivo_inativo(_tg("AFFNOV22", "R$ 670 OFF acima de R$ 4.200", publicado=_iso(days=1, hours=20)), set()) == ""
    assert lc.motivo_inativo(_tg("AFFNOV22", "R$ 670 OFF acima de R$ 4.200", publicado=_iso(days=2, hours=6)), set()) \
        .startswith("publicado há")
    # o Promobit continua com a janela dele (3 dias)
    promobit = dict(_tg("AFFNOV22", "R$ 670 OFF", publicado=_iso(days=2, hours=6)), fonte="promobit")
    assert lc.motivo_inativo(promobit, set()) == ""
    # com validade, vale até ela
    assert lc.motivo_inativo(_tg("AFFNOV09", "R$ 750 OFF acima de R$ 4.500", publicado=_iso(days=5),
                                 validade=(agora() + timedelta(days=3)).date().isoformat()), set()) == ""


def test_codigo_datado_do_telegram_so_no_dia():
    hoje_ = f"{agora():%d%m}"
    ontem = f"{agora() - timedelta(days=1):%d%m}"
    assert lc.motivo_inativo(_tg(f"JOGOS{hoje_}", "15% OFF acima de R$ 200, limite de R$ 80", loja="Mercado Livre"),
                             set()) == ""
    assert lc.motivo_inativo(_tg(f"JOGOS{ontem}", "15% OFF acima de R$ 200, limite de R$ 80", loja="Mercado Livre",
                                 publicado=_iso(hours=20)), set()).startswith("código de")


def test_comeca_no_futuro_e_esgotado(monkeypatch):
    _congela(monkeypatch, datetime(2026, 11, 8, 15, 0, tzinfo=TZ_BR))
    especial = _tg("IFP1ZYZM", "R$ 800 OFF acima de R$ 4.000", publicado="2026-11-08T14:30:48-03:00",
                   validade="2026-11-12", extra={"inicio": "2026-11-10"})
    assert lc.motivo_inativo(especial, set()) == "começa 10/11"
    _congela(monkeypatch, datetime(2026, 11, 10, 9, 0, tzinfo=TZ_BR))
    assert lc.motivo_inativo(especial, set()) == ""
    _congela(monkeypatch, datetime(2026, 11, 13, 9, 0, tzinfo=TZ_BR))
    assert lc.motivo_inativo(especial, set()) == "vencido"
    esg = _tg("AFFNOV11", "R$ 785 OFF acima de R$ 4.200", publicado="2026-11-12T10:00:00-03:00",
              extra={"esgotado_em": "2026-11-12T11:00:00-03:00"})
    assert lc.motivo_inativo(esg, set()) == "esgotado"


def test_promobit_e_telegram_viram_uma_linha_com_o_mais_completo():
    promobit = {"fonte": "promobit", "loja": "AliExpress", "codigo": "AFFNOV11", "titulo": "Cupom AliExpress R$ 785 OFF",
                "url": "https://exemplo/c", "id": "p1", "publicado": _iso(hours=5)}
    tg = _tg("affnov11", "R$ 785 OFF acima de R$ 4.200")
    [r] = lc.cupons_ativos([promobit, tg], set())["AliExpress"]
    assert r["_texto"] == "R$ 785 OFF · mín. R$ 4.200" and r["fonte"] == "telegram"
    out = "\n".join(lc.mensagens_cupons_ativos([promobit, tg], set()))
    assert out.upper().count("AFFNOV11") == 1


def test_esgotado_no_telegram_tira_o_codigo_das_outras_fontes():
    promobit = {"fonte": "promobit", "loja": "AliExpress", "codigo": "AFFNOV11", "titulo": "R$ 785 OFF acima de R$ 4.200",
                "url": "https://exemplo/c", "id": "p1", "publicado": _iso(hours=5)}
    aviso = _tg("AFFNOV11", "cupom citado como esgotado no Telegram", publicado=_iso(hours=1),
                extra={"esgotado_em": _iso(hours=1)})
    assert "AliExpress" not in lc.cupons_ativos([promobit, aviso], set())
    # anúncio ativo publicado depois do "esgotou": fica
    novo = dict(promobit, id="p2", publicado=_iso(minutes=10))
    assert lc.cupons_ativos([promobit, novo, aviso], set())["AliExpress"]


def test_lista_respeita_o_teto_de_linhas_por_loja(monkeypatch):
    monkeypatch.setattr(config, "CUPONS_ATIVOS_MAX_POR_LOJA", 10)
    cits = telegram_public.citacoes_do_html(_fx("telegram_cupons_xaviertechpromo_2026-11-08.html"), "xaviertechpromo")
    regs = [dict(c.to_dict(), publicado=_iso(hours=1)) for c in ct.consolida(cits)]
    txt = "\n".join(lc.mensagens_cupons_ativos(regs, set()))
    bloco = txt.split("🛒 <b>ALIEXPRESS</b>", 1)[1].split("\n\n", 1)[0]
    linhas = [l for l in bloco.splitlines() if l.startswith("• ")]
    assert len(linhas) == 10 and "… e mais" in bloco
    assert linhas[0].startswith("• <code>AFFNOV11</code> — R$ 785 OFF · mín. R$ 4.200")


def test_cupons_do_telegram_ficam_fora_dos_vistos_e_dentro_da_janela_da_leitura(dados):
    e = Estado("cloud")
    e.dados["cupons"] = {
        "telegram:a": dict(_tg("AFFNOV11", "R$ 785 OFF acima de R$ 4.200"), ultima_vez=_iso(hours=20)),
        "telegram:b": dict(_tg("AFFNOV22", "R$ 670 OFF acima de R$ 4.200"), ultima_vez=_iso(minutes=5)),
        "telegram:c": dict(_tg("AFFNOV01", "R$ 16 OFF acima de R$ 80"), ultima_vez=_iso(days=3)),
        "promobit:x": {"fonte": "promobit", "loja": "AliExpress", "codigo": "VELHO", "titulo": "R$ 5 OFF",
                       "ultima_vez": _iso(hours=20)},
        "promobit:y": {"fonte": "promobit", "loja": "AliExpress", "codigo": "NOVO", "titulo": "R$ 5 OFF",
                       "ultima_vez": _iso(minutes=5)},
    }
    codigos = {r["codigo"] for r in e.cupons_da_ultima_leitura()}
    # o Telegram fica com tudo o que viu na janela (o post de madrugada saiu da 1ª página); o Promobit, só a última leitura
    assert codigos == {"AFFNOV11", "AFFNOV22", "NOVO"}
    assert {r["fonte"] for r in e.cupons_vistos()} == {"promobit"}
    e.dados["cupons"]["telegram:d"] = dict(_tg("AFFNOV02", "x"), ultima_vez=_iso(days=16))
    assert e.poda_cupons_so_lista() == 1 and "telegram:d" not in e.dados["cupons"]
    assert "promobit:x" in e.dados["cupons"]


# ---------------------------------------------------------------------------------------------------------------------
# run.py: vai para a lista e nunca para o "Novo cupom aplicável"
# ---------------------------------------------------------------------------------------------------------------------
def test_run_telegram_na_lista_e_fora_do_alerta_de_cupom_novo(dados, monkeypatch, capsys):
    import run
    from monitor import regras, sources

    (dados / "state_cloud.json").write_text(json.dumps({
        "ofertas": {}, "cupons": {}, "minimo": None, "saude": {}, "ultimo_resumo": hoje(),
        "criado_em": "2026-09-13T15:22:00-03:00", "cupons_alertados": {}}), encoding="utf-8")
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    tg = Cupom("telegram", "AliExpress", "AFFNOV22", "R$ 670 OFF acima de R$ 4.200", "https://t.me/canal/1",
               "AliExpress|AFFNOV22|R670-4200", publicado=agora_iso(), extra={"canais": ["canal"]})
    promobit = Cupom("promobit", "Mercado Livre", "RODADA15", "15% OFF acima de R$500 limitado à R$100",
                     "https://exemplo/c", "r15", publicado=agora_iso())

    class Fake(sources.Fonte):
        nome = "fake"

        def coletar(self):
            return [], [tg, promobit]

    vistos: list = []
    original = regras.gerar_alertas

    def espia(estado, ofertas, cupons, vigia=False):
        vistos.extend(cupons)
        return original(estado, ofertas, cupons, vigia=vigia)

    monkeypatch.setattr(regras, "gerar_alertas", espia)
    monkeypatch.setattr(sources, "por_modo", lambda m: [Fake()])
    monkeypatch.setattr(run, "carrega_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run.py", "--mode", "cloud", "--no-notify", "--cupons"])
    assert run.main() == 0
    out = capsys.readouterr().out
    assert [c.fonte for c in vistos] == ["promobit"], "o cupom do Telegram não vai para o alerta de cupom novo"
    assert "<code>AFFNOV22</code> — R$ 670 OFF · mín. R$ 4.200" in out
    st = json.loads((dados / "state_cloud.json").read_text(encoding="utf-8"))
    assert st["cupons"]["telegram:AliExpress|AFFNOV22|R670-4200"]["extra"] == {"canais": ["canal"]}
    lt = json.loads((dados / "latest_cloud.json").read_text(encoding="utf-8"))
    assert all(c.get("fonte") != "telegram" for c in lt.get("cupons") or [])
