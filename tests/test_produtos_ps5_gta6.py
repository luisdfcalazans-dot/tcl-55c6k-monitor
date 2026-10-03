"""PS5 e GTA 6 monitorados junto com as TVs (pedido do usuário em 03/10/2026).

Cobre o catálogo (monitor/produtos.py: ids, metas aprovadas, termos, EANs, ids por loja), o classificador com títulos
reais da pesquisa de 03/10 (versões do PS5, pacotes com o GTA, kits e edições especiais, Code in Box, digital, Ultimate,
upgrade, gift card, leitor, e o que nunca vira o produto: usado, KSA/International, acessório, outro jogo, PS4/VR2/Portal/
Xbox, PS Plus), a mensagem livre com vários produtos, as metas por oferta (entrega do GTA até 18/11, kit = base + extra,
gift card em loja oficial, custo efetivo do digital), os alertas por produto (partida por seção, meta e distância,
"chega a tempo?"), o modo vigia só nas TVs, os cupons por família, o estado/latest por produto, a confiança por produto,
as fontes de postagens e o painel. Nenhum teste acessa a rede.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from monitor import config, confianca, produtos
from monitor.estado import Estado, chave_minimo
from monitor.models import Cupom, Oferta, modelo_de, rotulo_modelo
from monitor.regras import (
    cupom_compativel, cupons_aplicaveis, gerar_alertas, mensagem_bootstrap, resumo_diario, sanear,
)
from monitor.sources import promobit, telegram_public
from monitor.util import agora_iso, preco_postagem


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    """docs/data num diretório temporário e os alvos padrão das TVs (nada lê nem grava o repositório)."""
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    for k, v in (("ALVO_PIX", 2900.0), ("ALVO_PARCELADO", 3000.0), ("ALVO_PIX_65", 3300.0),
                 ("ALVO_PARCELADO_65", 3500.0)):
        monkeypatch.setattr(config, k, v)
    return tmp_path


# ------------------------------------------------------------------------------------------------
# catálogo
# ------------------------------------------------------------------------------------------------

def test_catalogo_tem_os_ids_do_contrato_e_as_tvs_de_sempre():
    for pid in ("55C6K", "65C6K", "PS5_DIGITAL", "PS5_DISCO", "PS5_PRO", "PS5_DIGITAL_GTA6", "PS5_DISCO_GTA6", "PS5_KIT",
                "GTA6_CODE_IN_BOX", "GTA6_DIGITAL", "GTA6_ULTIMATE", "GTA6_UPGRADE", "GIFT_CARD_PSN", "LEITOR_PS5"):
        assert pid in produtos.IDS, pid
    assert produtos.TVS == ("55C6K", "65C6K") and produtos.IDS[:2] == produtos.TVS
    assert {produtos.familia(p) for p in produtos.IDS} == {"TV", "PS5", "GTA6", "ACESSORIO"}
    assert produtos.secao("LEITOR_PS5") == "PS5" and produtos.secao("GIFT_CARD_PSN") == "GTA6"
    assert rotulo_modelo("55C6K") == "TCL 55C6K" and rotulo_modelo("PS5_PRO") == "PS5 Pro"


def test_metas_aprovadas_pelo_usuario():
    esperado = {"PS5_DIGITAL": (3550, 3700), "PS5_DISCO": (3950, 4150), "PS5_PRO": (5950, 6100),
                "PS5_DIGITAL_GTA6": (4000, 4150), "PS5_DISCO_GTA6": (4300, 4450), "GTA6_CODE_IN_BOX": (345, 370),
                "GTA6_DIGITAL": (365, 365), "GTA6_ULTIMATE": (450, 450), "GTA6_UPGRADE": (85, 85),
                "LEITOR_PS5": (300, 320)}
    for pid, (pix, parc) in esperado.items():
        assert (config.alvo_pix(pid), config.alvo_parcelado(pid)) == (pix, parc), pid
    p = produtos.produto("GTA6_CODE_IN_BOX")
    assert (p.alvo_pix_tardio, p.alvo_parcelado_tardio) == (300, 320)
    assert config.alvo_pix("PS5_KIT") is None and config.alvo_pix("GIFT_CARD_PSN") is None
    # as TVs continuam como antes, e o latest leva só elas em 'alvos'
    assert config.alvos() == {"55C6K": {"pix": 2900.0, "parcelado": 3000.0}, "65C6K": {"pix": 3300.0, "parcelado": 3500.0}}
    assert set(config.alvos_produtos()) == set(produtos.IDS)


def test_constantes_das_tvs_saem_do_catalogo_com_os_valores_de_sempre():
    assert config.BUSCAS == ["55c6k", "tcl 55c6k", "tcl c6k 55"]
    assert config.BUSCAS_65 == ["65c6k", "tcl 65c6k", "tcl c6k 65"]
    assert config.EAN_POR_MODELO == {"7899968301747": "55C6K", "7899968301754": "65C6K"}
    assert config.MAGALU_TERMOS == ["tcl 55c6k", "tcl 65c6k", "55c6k", "tcl c6k 55", "smart tv tcl 55 mini led"]
    assert config.ASINS_AMAZON == {m: produtos.produto(m).ids_loja["Amazon"][0] for m in produtos.TVS}


def test_ean_e_id_da_loja():
    assert produtos.produto_por_ean("0711719021490") == "PS5_DIGITAL"
    assert produtos.produto_por_ean("711719023876") == "PS5_DIGITAL"     # sem o zero (Americanas, Mais Correios)
    assert produtos.produto_por_ean("0711719022022") == "PS5_DISCO"
    assert produtos.produto_por_ean("710425676338") == "GTA6_CODE_IN_BOX"
    assert produtos.produto_por_ean("7899968301754") == "65C6K"
    assert produtos.produto_por_ean("123") is None
    assert produtos.produto_por_id_loja("Amazon", "B0H6KT2RWH") == "GTA6_CODE_IN_BOX"
    assert produtos.produto_por_id_loja("KaBuM!", "636960") == "PS5_PRO"
    assert produtos.produto_por_id_loja("Netshoes", "d32-286w-014") == "PS5_DIGITAL"
    assert produtos.produto_por_id_loja("PlayStation Store", "EP1004-PPSA01547_00-GTAVIULTIMATE001") == "GTA6_ULTIMATE"
    assert produtos.produto_por_id_loja("Amazon", "636960") is None      # id de outra loja
    assert produtos.ids_da_loja("Amazon", ["PS5"])["B0H6LVH152"] == "PS5_DIGITAL_GTA6"


def test_termos_por_fonte_sem_repeticao():
    t = produtos.termos("promobit")
    assert len(t) == len({x.lower() for x in t})
    assert t[:2] == ["55c6k", "65c6k"]
    for x in ("playstation 5", "ps5 pro", "gta vi", "gta 6", "grand theft auto vi", "gift card playstation"):
        assert x in t
    assert produtos.termos("pelando", ["TV"]) == ["55c6k", "65c6k", "tcl 55c6k", "tcl 65c6k"]


def test_cep_de_entrega_so_da_variavel_de_ambiente(monkeypatch):
    monkeypatch.delenv("CEP_ENTREGA", raising=False)
    assert config.cep_entrega() == (config.CEP_REFERENCIA, True)
    monkeypatch.setenv("CEP_ENTREGA", "12345-678")
    assert config.cep_entrega() == ("12345678", False)
    monkeypatch.setenv("CEP_ENTREGA", "1234")
    assert config.cep_entrega()[1] is True


# ------------------------------------------------------------------------------------------------
# classificador: títulos reais da pesquisa de 03/10
# ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("titulo,esperado", [
    ("Console Sony PlayStation 5 SSD 825GB Controle sem fio DualSense 2 Jogos Digitais Edição Digital Branco", "PS5_DIGITAL"),
    ("PlayStation 5 Digital 825GB 1 Controle Branco", "PS5_DIGITAL"),
    ("Sony PlayStation 5 Edição Digital 825GB 1 Controle", "PS5_DIGITAL"),
    ("PS5 Slim Digital - Pacote Astro Bot e GT7", "PS5_DIGITAL"),
    ("Console PS5 Slim 1TB Branco Sony", "PS5_DISCO"),
    ("Pix Playstation 5 Slim Disk 1TB", "PS5_DISCO"),
    ("Console Playstation 5 Slim 1TB Disk CFI-2114", "PS5_DISCO"),
    ("Console Sony PlayStation 5 com Leitor de Discos SSD 1TB Controle sem fio DualSense 2 Jogos Branco", "PS5_DISCO"),
    ("Console PlayStation 5 Pro Sony SSD 2TB com Controle sem fio DualSense", "PS5_PRO"),
    ("18x s/j Console Playstation 5 Pro 2TB Sony Bivolt", "PS5_PRO"),
    ("Bundle GTA VI + PS5 Slim Digital 825 GB + Astro Bot + GT7", "PS5_DIGITAL_GTA6"),
    ("GTA VI + PS5 Slim Disk + Astro Bot + Gran Turismo 7", "PS5_DISCO_GTA6"),
    ("Jogo Grand Theft Auto VI (GTA 6) PS5 - Code in Box Pré-venda - Lançamento 19/11", "GTA6_CODE_IN_BOX"),
    ("Grand Theft Auto VI - PlayStation 5", "GTA6_CODE_IN_BOX"),
    ("Jogo Grand Theft Auto GTA VI, PS5 - TT000272PS5", "GTA6_CODE_IN_BOX"),
    ("Jogo Grand Theft Auto VI Mídia Física PS5", "GTA6_CODE_IN_BOX"),
    ("GTA VI Ultimate Edition", "GTA6_ULTIMATE"),
    ("Grand Theft Auto VI: Ultimate Edition Upgrade", "GTA6_UPGRADE"),
    ("Gift Card PlayStation R$300 Vale-Presente para Jogos e Assinaturas", "GIFT_CARD_PSN"),
    ("Sony PlayStation Store Gift Card R$ 100 Digital", "GIFT_CARD_PSN"),
    ("Cartão PSN R$ 150", "GIFT_CARD_PSN"),
    ("Leitor Disco Playstation 5 Slim/PS5 Pro Sony Branco", "LEITOR_PS5"),
    ("Smart TV 55 TCL 4K UHD MiniLED 55C6K 120Hz", "55C6K"),
    ("Smart TV TCL 65C6K 65 4K Mini LED Android TV", "65C6K"),
])
def test_classifica_titulos_reais(titulo, esperado):
    c = produtos.classifica(titulo)
    assert c.produto == esperado, c


@pytest.mark.parametrize("titulo,motivo", [
    ("PlayStation 5 Slim Digital Edition Console Blue Controller Bundle KSA Version", "versão estrangeira"),
    ("Console PS5 Slim Digital International Version", "versão estrangeira"),
    ("Playstation 5 Slim Digital Amazon Quase Novo", "estado"),
    ("Console PS5 Slim Digital usado", "estado"),
    ("Console PlayStation 5 Slim 30º Aniversário", "edição de colecionador"),
    ("Controle DualSense Edição Limitada GTA VI", "acessório"),
    ("Headset Pulse 3D PS5", "acessório"),
    ("SSD Samsung 990 Pro 2TB com dissipador PS5", "acessório"),
    ("Suporte vertical PS5 Slim", "acessório"),
    ("Jogo EA Sports FC 26 PS5", "outro jogo"),
    ("Jogo GTA V PS5", "outro jogo"),
    ("Grand Theft Auto: The Trilogy", "outro jogo"),
    ("Console Xbox Series X + GTA 6", "outro aparelho"),
    ("PlayStation Portal", "outro aparelho"),
    ("PlayStation Plus Essential 12 meses", "assinatura"),
    ("GTA VI + DualSense Techno Red", "kit de jogo e acessório"),
    ("Camiseta GTA VI Vice City", "produto temático"),
    ("Marvel's Spider-Man 2 - PlayStation 5", "sem console"),
])
def test_nunca_vira_o_produto(titulo, motivo):
    c = produtos.classifica(titulo)
    assert c.produto is None and c.motivo.startswith(motivo), c


@pytest.mark.parametrize("titulo,base,valor", [
    ("Console PlayStation 5 Digital Edição Limitada Wolverine", "PS5_DIGITAL", 200.0),
    ("Console PS5 Slim Digital 1TB + 2 Controles", "PS5_DIGITAL", 300.0),
    ("Kit PS5 Digital com R$ 500 em créditos PS Store", "PS5_DIGITAL", 400.0),
    ("Console Playstation 5 Pro Branco de 2TB + Controle sem fio DualSense Branco", "PS5_PRO", 300.0),
    ("Console PlayStation 5 Slim Edição Digital + Leitor de Disco", "PS5_DIGITAL", 300.0),
    ("Console PS5 Slim Digital + EA Sports FC 26", "PS5_DIGITAL", 200.0),
])
def test_kit_e_edicao_especial_levam_o_console_base_e_o_valor_do_extra(titulo, base, valor):
    c = produtos.classifica(titulo)
    assert c.produto == "PS5_KIT" and c.detalhes["base"] == base and c.detalhes["valor_extra"] == valor, c


def test_versao_nao_identificada_fica_com_a_meta_da_digital():
    c = produtos.classifica("PlayStation 5")
    assert c.produto == "PS5_DIGITAL" and c.detalhes.get("versao_incerta") is True


def test_gift_card_tem_o_valor_de_face():
    assert produtos.classifica("Gift Card PlayStation R$300 Vale-Presente").detalhes["valor_face"] == 300.0
    assert produtos.classifica("Cartão PSN R$ 150").detalhes["valor_face"] == 150.0
    assert produtos.classifica("Gift Card PlayStation Network 360 BRL").detalhes["valor_face"] == 360.0  # Pelando


@pytest.mark.parametrize("titulo", [
    "ACHADOS MAGALU! PS5 Slim R$ 4.875, Galaxy S24 Ultra R$ 5.099 e Lavadora Electrolux R$ 1.549",
    "SUPER OFERTAS SHOPEE com Até 70% OFF! Smart TV, GTA 6, Playstation 5 e Muito Mais!",
])
def test_resumo_de_varias_ofertas_nao_e_um_produto(titulo):
    """Casos reais do Promobit (29/09 e 26/09): o "preço" da postagem não é de um produto (R$ 234,28 / R$ 202,90)."""
    c = produtos.classifica(titulo)
    assert c.produto is None and c.motivo == "resumo de várias ofertas", c


def test_postagem_com_preco_fora_da_faixa_sai_da_rodada():
    """Caso real (Promobit, 28/09): "R$22 OFF em Gift Card PlayStation na Shopee | Mín: R$300" com preço R$ 0,01."""
    cupom = Oferta("promobit", "post", "Shopee", "Seus jogos no PS: R$22 OFF em Gift Card PlayStation na Shopee",
                   "u", "x", preco=0.01, modelo="GIFT_CARD_PSN")
    ok = Oferta("promobit", "post", "Nuuvem", "Gift Card PlayStation R$ 300", "u", "y", preco=242.74,
                modelo="GIFT_CARD_PSN")
    ofertas, avisos = sanear([cupom, ok])
    assert ofertas == [ok] and "postagem ignorada" in avisos[0]


def test_gta_na_ps_store_e_digital():
    assert produtos.classifica("Grand Theft Auto VI", loja="PlayStation Store").produto == "GTA6_DIGITAL"
    assert produtos.classifica("Grand Theft Auto VI").produto == "GTA6_CODE_IN_BOX"


def test_ean_e_id_valem_mais_que_o_titulo_mas_o_estado_ainda_recusa():
    # título genérico do marketplace, mas o EAN diz qual é
    assert produtos.classifica("Console Sony Bundle Branco", ean="0711719022022").produto == "PS5_DISCO"
    assert produtos.classifica("Produto 1051619", loja="KaBuM!", id_loja="1051619").produto == "GTA6_CODE_IN_BOX"
    c = produtos.classifica("Console Sony recondicionado", ean="0711719022022")
    assert c.produto is None and c.motivo.startswith("estado")
    # o id da KaBuM da edição Wolverine diz que é kit: a base e o extra saem do título
    k = produtos.classifica("Console PlayStation 5 Digital Wolverine", loja="KaBuM!", id_loja="1065184")
    assert k.produto == "PS5_KIT" and k.detalhes["base"] == "PS5_DIGITAL" and k.detalhes["valor_extra"] == 200.0
    assert produtos.CARRINHO == ("55C6K", "65C6K", "PS5_DIGITAL", "PS5_DISCO", "PS5_PRO", "GTA6_CODE_IN_BOX")


# ------------------------------------------------------------------------------------------------
# mensagem livre (Telegram): um bloco por produto
# ------------------------------------------------------------------------------------------------

def _preco(t: produtos.Trecho, pid: str) -> float | None:
    return preco_postagem(t.trecho, produtos.piso(pid))


def test_mensagem_com_varios_produtos_separa_os_precos():
    texto = ("🔥 CUPOMLIBERADO na Netshoes\n🎮 PS5 Digital com 2 jogos — R$ 3.599 em 10x\n"
             "🎮 PS5 Slim com leitor + 2 jogos — R$ 3.999,99\n🎮 PS5 Pro 2TB — R$ 6.009\n🎮 GTA 6 Code in Box — R$ 341")
    achados = produtos.extrai_produtos(texto)
    assert {p: _preco(t, p) for p, t in achados.items()} == {
        "PS5_DIGITAL": 3599.0, "PS5_DISCO": 3999.99, "PS5_PRO": 6009.0, "GTA6_CODE_IN_BOX": 341.0}
    assert "CUPOMLIBERADO" in achados["PS5_PRO"].preambulo


def test_preco_antes_do_nome():
    texto = "💰 R$ 341\nJogo GTA 6 PS5 Code in Box\n💰 R$ 3.599\nConsole PS5 Slim Digital\nhttps://x"
    achados = produtos.extrai_produtos(texto)
    assert _preco(achados["GTA6_CODE_IN_BOX"], "GTA6_CODE_IN_BOX") == 341.0
    assert _preco(achados["PS5_DIGITAL"], "PS5_DIGITAL") == 3599.0


def test_tv_e_ps5_na_mesma_mensagem():
    texto = "Smart TV TCL 55C6K por R$ 3.299\n📺 ótima TV\n🎮 Console PS5 Slim Digital por R$ 3.499\nhttps://x"
    achados = produtos.extrai_produtos(texto)
    assert set(achados) == {"55C6K", "PS5_DIGITAL"}
    assert _preco(achados["PS5_DIGITAL"], "PS5_DIGITAL") == 3499.0


@pytest.mark.parametrize("texto,esperado", [
    ("Console PS5 Slim Digital\n+ 2 controles DualSense\nR$ 4.099 no Pix", {"PS5_KIT"}),
    ("Console PS5 Slim Digital usado em ótimo estado\nR$ 2.800", set()),
    ("Controle DualSense Edição GTA VI\nR$ 599", set()),
    ("🎮 GTA 6 PS5 Code in Box — R$ 345\n🕹️ Controle DualSense Branco — R$ 399", {"GTA6_CODE_IN_BOX"}),
    ("Console PlayStation 5 Slim Digital 825GB\nCompatível com jogos de PS4 e PS5\nR$ 3.499 no Pix", {"PS5_DIGITAL"}),
    ("Console PS5 Digital por R$ 599", set()),   # preço abaixo do piso do console: não é o console
])
def test_mensagem_livre_casos(texto, esperado):
    assert set(produtos.extrai_produtos(texto)) == esperado


def test_mensagem_de_gift_card_traz_o_valor_de_face():
    achados = produtos.extrai_produtos("Gift Card PlayStation R$ 300\n💰 R$ 242,74\n📍 Eneba")
    assert achados["GIFT_CARD_PSN"].detalhes["valor_face"] == 300.0
    assert _preco(achados["GIFT_CARD_PSN"], "GIFT_CARD_PSN") == 242.74


# ------------------------------------------------------------------------------------------------
# metas por oferta e entrega do GTA 6
# ------------------------------------------------------------------------------------------------

def _gta(loja="Amazon", vendedor=None, preco=339.0, tipo="loja", extra=None, oid="g1"):
    return Oferta("x", tipo, loja, "Jogo GTA 6 PS5 Code in Box", f"https://x/{oid}", oid, preco=preco,
                  vendedor=vendedor, extra=extra or {}, modelo="GTA6_CODE_IN_BOX", publicado=agora_iso())


@pytest.mark.parametrize("extra,classe,pix", [
    ({"entrega_prevista": "2026-11-16"}, "a_tempo", 345.0),
    ({"entrega_prevista": "2026-11-18"}, "a_tempo", 345.0),
    ({"entrega_prevista": "2026-11-19"}, "no_dia", 300.0),
    ({"entrega_prevista": "2026-11-30"}, "depois", 300.0),
    ({"entrega_ate_lancamento": True}, "a_tempo", 345.0),
    ({"entrega_ate_lancamento": False}, "depois", 300.0),
])
def test_meta_do_code_in_box_depende_da_entrega(extra, classe, pix):
    o = _gta(loja="Magazine Luiza", extra=extra)
    assert produtos.entrega(o).classe == classe
    assert produtos.alvos_da_oferta(o, hoje="2026-10-03").pix == pix


def test_entrega_estimada_pela_loja_quando_a_fonte_nao_diz():
    assert produtos.entrega(_gta("Amazon")).classe == "a_tempo"
    assert produtos.entrega(_gta("Amazon")).cep_referencia is True       # estimativa: prazo aproximado
    assert produtos.entrega(_gta("Netshoes")).classe == "depois"
    assert produtos.entrega(_gta("KaBuM!", vendedor="MERCADOONLINESP")).classe == "depois"
    e = produtos.entrega(_gta("Magazine Luiza"))
    assert e.classe == "desconhecida" and "confira" in e.texto
    a = produtos.alvos_da_oferta(_gta("Magazine Luiza"), hoje="2026-10-03")
    assert a.pix == 345.0 and a.nota == "prazo desconhecido"
    # depois do lançamento, a meta é a de quem chega depois
    assert produtos.alvos_da_oferta(_gta("Amazon"), hoje="2026-11-20").pix == 300.0
    # o pacote com o GTA também mostra a entrega; o console sozinho, não
    pac = Oferta("x", "loja", "Amazon", "Pacote", "u", "p", preco=4602.0, modelo="PS5_DIGITAL_GTA6")
    assert produtos.entrega(pac).classe == "a_tempo"
    assert produtos.entrega(Oferta("x", "loja", "Amazon", "PS5", "u", "q", preco=3800.0, modelo="PS5_DIGITAL")) is None


def test_meta_do_kit_e_do_gift_card():
    kit = Oferta("x", "post", "KaBuM!", "Console PS5 Slim Digital + 2 Controles", "u", "k", preco=3800.0,
                 modelo="PS5_KIT")
    assert produtos.alvos_da_oferta(kit) == (3850.0, 4000.0, "meta do PS5 Slim Digital + R$ 300 do extra")
    oficial = Oferta("x", "post", "Nuuvem", "Gift Card PlayStation R$ 300", "u", "g", preco=242.74,
                     modelo="GIFT_CARD_PSN")
    assert produtos.alvos_da_oferta(oficial).pix == 255.0
    eneba = Oferta("x", "post", "Eneba", "Gift Card PlayStation R$ 300", "u", "e", preco=242.74, modelo="GIFT_CARD_PSN")
    assert produtos.alvos_da_oferta(eneba).pix is None
    ml = Oferta("x", "post", "Mercado Livre", "Sony PlayStation Store Gift Card R$ 100", "u", "m", preco=85.0,
                modelo="GIFT_CARD_PSN", extra={"texto": "na loja oficial PlayStation"})
    assert produtos.alvos_da_oferta(ml).pix == 85.0


def test_custo_efetivo_do_digital_com_gift_card():
    gift = Oferta("x", "post", "Nuuvem", "Gift Card PlayStation R$ 300", "u", "g", preco=242.74,
                  modelo="GIFT_CARD_PSN", publicado=agora_iso())
    ps = Oferta("psstore", "loja", "PlayStation Store", "Grand Theft Auto VI", "u", "s", preco=449.90,
                modelo="GTA6_DIGITAL")
    d, _o = produtos.desconto_gift_card([gift, ps])
    assert round(d, 3) == round(1 - 242.74 / 300, 3)
    assert produtos.preco_comparavel(ps, d) == round(449.90 * (1 - d), 2) <= 365
    assert produtos.custo_digital_com_gift(d)["GTA6_DIGITAL"] <= 365
    # gift card de loja não oficial não conta
    eneba = Oferta("x", "post", "Eneba", "Gift Card PlayStation R$ 300", "u", "e", preco=200.0, modelo="GIFT_CARD_PSN")
    assert produtos.desconto_gift_card([eneba, ps]) is None


def test_custo_final_do_gta_compara_todas_as_formas():
    linhas = produtos.custo_final_gta([
        _gta("Netshoes", preco=341.0, tipo="post", oid="n"), _gta("Amazon", preco=418.40, oid="a"),
        Oferta("x", "post", "Nuuvem", "Gift Card PlayStation R$ 300", "u", "g", preco=242.74, modelo="GIFT_CARD_PSN",
               publicado=agora_iso()),
    ])
    assert linhas[0]["loja"] == "Netshoes" and linhas[0]["entrega"] == "depois"
    digital = [l for l in linhas if l["produto"] == "GTA6_DIGITAL"]
    assert digital and digital[0]["custo_final"] < 365 and digital[0]["entrega"] == "digital"
    assert [l["custo_final"] for l in linhas] == sorted(l["custo_final"] for l in linhas)


# ------------------------------------------------------------------------------------------------
# alertas por produto
# ------------------------------------------------------------------------------------------------

def _state(pasta, **extra):
    d = {"ofertas": {}, "cupons": {}, "minimo": None, "saude": {}, "ultimo_resumo": None,
         "criado_em": "2026-09-13T15:22:00-03:00", "modelos_iniciados": ["55C6K", "65C6K"]}
    d.update(extra)
    (pasta / "state_cloud.json").write_text(json.dumps(d), encoding="utf-8")


def _rodada(ofertas, cupons=(), vigia=False):
    est = Estado("cloud")
    ofertas, _ = sanear(ofertas)
    msgs, alertados = gerar_alertas(est, ofertas, list(cupons), vigia=vigia)
    diretas = est.lojas_diretas_conhecidas(ofertas)
    novos = [m for m in produtos.NAO_TVS if est.bootstrap_modelo(m) and any(modelo_de(o) == m for o in ofertas)]
    if novos:
        msgs.append(mensagem_bootstrap(ofertas, [], "cloud", diretas, novos))
    produtos.anota(ofertas)
    for o in ofertas:
        est.registra_oferta(o, alertados.get(o.chave))
        est.atualiza_minimo(o, diretas)
    est.marca_modelos_iniciados({modelo_de(o) for o in ofertas})
    est.anexa_historico([o for o in ofertas if o.tipo == "loja" and o.ativo and o.melhor_preco])
    est.escreve_latest(ofertas, [])
    est.salva()
    return est, msgs


def _post(pid, titulo, preco, loja, oid, extra=None):
    return Oferta("promobit", "post", loja, titulo, f"https://p/{oid}", oid, preco=preco, publicado=agora_iso(),
                  modelo=pid, extra=extra or {})


def test_partida_por_secao_e_depois_toda_postagem_alerta_com_meta_e_distancia(dados):
    _state(dados)
    antigo = _post("PS5_DIGITAL", "PS5 Slim Digital 825GB", 3889.0, "Amazon", "p1")
    est, msgs = _rodada([antigo])
    assert len(msgs) == 1 and msgs[0].startswith("✅ <b>Monitor de PS5 iniciado</b>")
    assert "1 postagens antigas registradas" in msgs[0]
    # rodada seguinte: a postagem antiga não repete; a nova sai, com o produto e a distância até a meta. O kit é de um
    # produto que ainda não tinha aparecido, mas a seção do PS5 já começou: é novidade
    novo = _post("PS5_DIGITAL", "PS5 Slim Digital 825GB", 3499.0, "Netshoes", "p2")
    kit = _post("PS5_KIT", "Console PS5 Slim Digital + 2 Controles", 4200.0, "KaBuM!", "p3")
    est, msgs = _rodada([antigo, novo, kit])
    cabs = [m.split("\n")[0] for m in msgs]
    assert cabs == ["📣 Promoção postada 🎯 · PS5 Slim Digital — <b>Netshoes</b>",
                    "📣 Promoção postada · PS5 edição especial / kit — <b>KaBuM!</b>"]
    assert "🎯 Meta: Pix R$ 3.550,00 · parcelado R$ 3.700,00 — R$ 51,00 abaixo da meta ✅" in msgs[0]
    assert "R$ 350,00 acima da meta" in msgs[1] and "meta do PS5 Slim Digital + R$ 300 do extra" in msgs[1]


def test_alerta_do_gta_diz_a_entrega_e_se_chega_a_tempo(dados):
    _state(dados, modelos_iniciados=["55C6K", "65C6K", "GTA6_CODE_IN_BOX"])
    est, msgs = _rodada([_post("GTA6_CODE_IN_BOX", "Jogo GTA 6 PS5 Code in Box", 341.0, "Netshoes", "n"),
                         _post("GTA6_CODE_IN_BOX", "Jogo GTA 6 PS5 Code in Box", 339.0, "Amazon", "a")])
    net, amz = msgs
    assert net.startswith("📣 Promoção postada · GTA 6 PS5 Code in Box")       # 341 > 300 (chega depois)
    assert "chega DEPOIS do lançamento" in net and "Meta: Pix R$ 300,00" in net
    assert amz.startswith("📣 Promoção postada 🎯 · GTA 6 PS5 Code in Box")    # 339 <= 345 (chega a tempo)
    assert "chega a tempo ✅" in amz and "previsão 16/11" in amz


def test_preco_so_de_assinante_nao_ganha_alvo(dados):
    """O usuário só tem Nubank/NuPay (03/10): o preço "Prime" do post sai, sem 🎯 e com o aviso."""
    _state(dados, modelos_iniciados=["55C6K", "65C6K", "PS5_DIGITAL"])
    est, msgs = _rodada([_post("PS5_DIGITAL", "[Prime] PS5 Slim Digital 825GB", 3400.0, "Amazon", "pr")])
    (m,) = msgs
    assert m.startswith("📣 Promoção postada · PS5 Slim Digital") and "exclusivo de assinatura (prime)" in m


def test_gift_card_de_loja_oficial_ganha_alvo_e_mostra_o_custo_do_gta_digital(dados):
    _state(dados, modelos_iniciados=["55C6K", "65C6K", "GTA6_CODE_IN_BOX"])
    est, msgs = _rodada([
        _post("GIFT_CARD_PSN", "Gift Card PlayStation R$ 300", 242.74, "Nuuvem", "g1"),
        _post("GIFT_CARD_PSN", "Gift Card PlayStation R$ 300", 230.0, "Eneba", "g2")])
    nuuvem, eneba = msgs
    assert nuuvem.startswith("📣 Promoção postada 🎯 · Gift card PlayStation")
    assert "GTA 6 digital sairia por R$ 364,03" in nuuvem
    assert not eneba.startswith("📣 Promoção postada 🎯") and "loja não oficial" in eneba


def test_digital_da_ps_store_alerta_pelo_custo_efetivo(dados):
    _state(dados, modelos_iniciados=["55C6K", "65C6K", "GTA6_DIGITAL"])
    ps = Oferta("psstore", "loja", "PlayStation Store", "Grand Theft Auto VI", "https://ps/s", "s", preco=449.90,
                vendedor="PlayStation Store", modelo="GTA6_DIGITAL")
    gift = _post("GIFT_CARD_PSN", "Gift Card PlayStation R$ 300", 242.74, "Nuuvem", "g1")
    est, msgs = _rodada([ps, gift])
    loja = [m for m in msgs if "PlayStation Store</b>" in m.split("\n")[0]]
    assert loja and "🎯 Abaixo do alvo" in loja[0] and "custo efetivo R$ 364,03" in loja[0]


def test_modo_vigia_vale_so_para_as_tvs(dados, monkeypatch, capsys):
    """run.py em modo vigia: a 55C6K não alerta, a 65C6K só abaixo do limite; o PS5 e o GTA 6 seguem normais."""
    import run
    from monitor import sources

    _state(dados, modelos_iniciados=["55C6K", "65C6K", "PS5_DIGITAL", "GTA6_CODE_IN_BOX"])
    monkeypatch.setattr(config, "VIGIA_ATE", "2999-12-31")
    monkeypatch.setattr(config, "ALVO_PIX_65", 3300.0)
    agora = agora_iso()

    class Fake(sources.Fonte):
        nome = "fake"

        def coletar(self):
            return [
                Oferta("promobit", "post", "Magazine Luiza", "Smart TV TCL 55C6K", "u55", "t55", preco=2500.0,
                       publicado=agora, modelo="55C6K"),
                Oferta("promobit", "post", "Amazon", "Smart TV TCL 65C6K", "u65", "t65", preco=3600.0, publicado=agora,
                       modelo="65C6K"),
                Oferta("promobit", "post", "Netshoes", "PS5 Slim Digital", "ups", "ps", preco=3499.0, publicado=agora,
                       modelo="PS5_DIGITAL"),
                Oferta("promobit", "post", "Amazon", "Jogo GTA 6 PS5", "ugta", "gta", preco=339.0, publicado=agora,
                       modelo="GTA6_CODE_IN_BOX"),
            ], []

    monkeypatch.setattr(sources, "por_modo", lambda modo: [Fake()])
    monkeypatch.setattr(run, "carrega_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run.py", "--mode", "cloud", "--no-notify"])
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    try:
        run.main()
    finally:
        config.ALVO_PIX_65 = 3300.0   # o modo vigia troca o alvo da 65" no módulo
        config.ALVO_PARCELADO_65 = 3500.0
    out = capsys.readouterr().out
    alertas = [b for b in out.split("[alerta]\n")[1:]]
    cabs = [a.split("\n")[0] for a in alertas]
    assert any("PS5 Slim Digital" in c and "🎯" in c for c in cabs), cabs
    assert any("GTA 6 PS5 Code in Box" in c for c in cabs), cabs
    assert not any("TCL 55C6K" in c or "TCL 65C6K" in c for c in cabs), cabs   # 65C6K acima de R$ 3.427
    assert "[vigia]" in out


def test_resumo_do_ps5_e_do_gta(dados):
    _state(dados, modelos_iniciados=["55C6K", "65C6K", "PS5_DIGITAL", "GTA6_CODE_IN_BOX"])
    of = [Oferta("netshoes", "loja", "Netshoes", "PlayStation 5 Edição Digital", "https://n/1", "D32", preco=4549.0,
                 preco_pix=4094.10, vendedor="Magalu Oficial", modelo="PS5_DIGITAL", extra={"vendedor_id": "29198"}),
          Oferta("kabum", "loja", "KaBuM!", "Jogo GTA VI PS5", "https://k/1", "1051619", preco=449.9, preco_pix=418.41,
                 vendedor="KaBuM!", modelo="GTA6_CODE_IN_BOX")]
    est, _ = _rodada(of)
    r = resumo_diario(est, of, [])
    assert r.startswith("☀️ <b>Resumo diário — TCL 55C6K</b>")
    assert "🎮 <b>PS5</b>" in r and "R$ 4.094,10 (Netshoes/Magalu Oficial) · meta R$ 3.550,00" in r
    assert "🎮 <b>GTA 6</b>" in r and "chega a tempo" in r
    rv = resumo_diario(est, of, [], vigia=True)
    assert "TCL 55C6K" not in rv and "🎮 <b>PS5</b>" in rv


# ------------------------------------------------------------------------------------------------
# cupons por família
# ------------------------------------------------------------------------------------------------

def _cupom(loja, codigo, titulo, regra=""):
    return Cupom("promobit", loja, codigo, titulo, "https://c", codigo, regra=regra)


@pytest.mark.parametrize("cupom,produto,ok", [
    (_cupom("KaBuM!", "PS5200", "PS5 com R$ 200 de desconto"), "PS5_DIGITAL", True),
    (_cupom("KaBuM!", "PS5200", "PS5 com R$ 200 de desconto"), "55C6K", False),
    (_cupom("KaBuM!", "PS5200", "PS5 com R$ 200 de desconto"), "GTA6_CODE_IN_BOX", False),
    (_cupom("Magazine Luiza", "GTA60", "R$ 60 OFF no GTA VI"), "GTA6_CODE_IN_BOX", True),
    (_cupom("Magazine Luiza", "GTA60", "R$ 60 OFF no GTA VI"), "PS5_DIGITAL", False),
    (_cupom("Magazine Luiza", "GTA60", "R$ 60 OFF no GTA VI"), "PS5_DIGITAL_GTA6", True),
    (_cupom("Magazine Luiza", "TVS300", "Cupom Magalu R$ 300 OFF em TVs"), "PS5_DIGITAL", False),
    (_cupom("Magazine Luiza", "TVS300", "Cupom Magalu R$ 300 OFF em TVs"), "55C6K", True),
    (_cupom("Magazine Luiza", "SITE200", "Cupom Magalu R$ 200 OFF em todo o site", "Exceto Celulares e Games."),
     "PS5_DIGITAL", False),
    (_cupom("Magazine Luiza", "SITE200", "Cupom Magalu R$ 200 OFF em todo o site", "Exceto Celulares e Games."),
     "55C6K", True),
    (_cupom("Netshoes", "GAMES10", "10% OFF em Games na Netshoes"), "PS5_DIGITAL", True),
    (_cupom("Netshoes", "GAMES10", "10% OFF em Games na Netshoes"), "GIFT_CARD_PSN", False),
    (_cupom("Nuuvem", "GIFT5", "5% OFF em gift cards PlayStation"), "GIFT_CARD_PSN", True),
    (_cupom("Amazon", "MODA20", "20% OFF em Moda"), "PS5_DIGITAL", False),
    (_cupom("KaBuM!", "XBOX50", "R$ 50 OFF em Xbox"), "GTA6_CODE_IN_BOX", False),
    (_cupom("KaBuM!", "NOVO10", "10% OFF para novos clientes"), "PS5_PRO", False),
    (_cupom("KaBuM!", "MIL", "R$ 100 OFF em compras acima de R$ 1.000"), "GTA6_CODE_IN_BOX", False),
    (_cupom("KaBuM!", "MIL", "R$ 100 OFF em compras acima de R$ 1.000"), "PS5_PRO", True),
    # casos reais das listas de cupons de 03/10 (Promobit)
    (_cupom("Netshoes", "CAMISETA", "Aproveite para economizar R$10 com cupom Netshoes"), "PS5_DIGITAL", False),
    (_cupom("Netshoes", "UNDER15", "Faça compras com cupom de desconto Netshoes e economize 15%"), "PS5_DIGITAL", False),
    (_cupom("Netshoes", "PLAY150", "Ganhe R$150 de desconto Netshoes em suas compras",
            "PLAYSTATION 5 SLIM COM R$150 OFF"), "PS5_DIGITAL", True),
    (_cupom("KaBuM!", "STAR10OFF", "10% de Desconto no Starlink Mini Internet via Satélite"), "PS5_PRO", False),
    (_cupom("KaBuM!", "MIRA20", "Headshot garantido: 20% OFF em Mouses Gamer selecionados!"), "PS5_PRO", False),
    (_cupom("KaBuM!", "ULTRA15", "Use o cupom KaBum! e economize 15% em suas compras",
            "15% DE DESCONTO EM ELETRÔNICOS"), "PS5_PRO", True),
    (_cupom("Amazon", "PRIMEGAME5", "Use cupom Amazon e tenha desconto de 5% + 7%"), "GTA6_CODE_IN_BOX", False),
    (_cupom("Nuuvem", "PALAMIGO", "GARANTIDO! 8% OFF no jogo Palworld com cupom"), "GTA6_DIGITAL", False),
    (_cupom("Amazon", "JOGUE10", "Economize 10% na compra de jogos de tabuleiro"), "GTA6_CODE_IN_BOX", False),
    (_cupom("Magazine Luiza", "JOGOS30", "R$ 30 OFF em jogos"), "GTA6_CODE_IN_BOX", True),
    (_cupom("Magazine Luiza", "JOGOS30", "R$ 30 OFF em jogos"), "PS5_DIGITAL", False),
    (_cupom("Magazine Luiza", "FASHION10", "A chance de economizar 10% em compras na Magazine Luiza"), "PS5_DIGITAL", False),
    (_cupom("Nuuvem", "PS5NUU", "Garanta 5% OFF em Gift Cards Playstation com cupom Nuuvem"), "GIFT_CARD_PSN", True),
])
def test_cupom_por_familia(cupom, produto, ok):
    assert cupom_compativel(cupom, None, produto)[0] is ok, cupom_compativel(cupom, None, produto)


def test_mensagem_de_cupom_diz_para_quais_produtos_e_mantem_a_da_tv(dados):
    _state(dados, modelos_iniciados=["55C6K", "65C6K", "PS5_DIGITAL"])
    ps5 = _post("PS5_DIGITAL", "PS5 Slim Digital", 3999.0, "KaBuM!", "x")
    est = Estado("cloud")
    msgs, _ = gerar_alertas(est, [ps5], [_cupom("KaBuM!", "PS5200", "PS5 com R$ 200 de desconto"),
                                          _cupom("Magazine Luiza", "TVS300", "Cupom Magalu R$ 300 OFF em TVs")])
    cupons = [m for m in msgs if m.startswith("🎟️")][0]
    assert cupons.startswith("🎟️ <b>Novos cupons aplicáveis</b> (TVs, PS5)")
    assert "PS5200</code> — PS5 com R$ 200 de desconto · serve para: PS5 Digital" in cupons
    assert "TVS300</code> — Cupom Magalu R$ 300 OFF em TVs\n" in cupons
    assert {c.codigo for c in cupons_aplicaveis([ps5], [_cupom("KaBuM!", "PS5200", "PS5 com R$ 200 de desconto")],
                                                 est)} == {"PS5200"}


def test_cupom_so_dos_produtos_em_partida_nao_vira_alerta(dados):
    """Na partida do PS5 num state que já existia, os cupons que só servem a ele são anunciados na mensagem de início
    (como na partida geral), não numa enxurrada de 🎟️."""
    _state(dados)
    ps5 = _post("PS5_DIGITAL", "PS5 Slim Digital", 3999.0, "KaBuM!", "x")
    est = Estado("cloud")
    msgs, _ = gerar_alertas(est, [ps5], [_cupom("KaBuM!", "PS5200", "PS5 com R$ 200 de desconto")])
    assert not [m for m in msgs if m.startswith("🎟️")]
    assert est.alertas_de_cupom("KaBuM!|PS5200")[0]["origem"] == "partida"


def test_modo_vigia_tira_as_tvs_dos_cupons(dados):
    _state(dados, modelos_iniciados=["55C6K", "65C6K", "PS5_DIGITAL"])
    ps5 = _post("PS5_DIGITAL", "PS5 Slim Digital", 3999.0, "KaBuM!", "x")
    msgs, _ = gerar_alertas(Estado("cloud"), [ps5], [_cupom("Magazine Luiza", "TVS300", "R$ 300 OFF em TVs"),
                                                     _cupom("KaBuM!", "PS5200", "PS5 com R$ 200 de desconto")],
                            vigia=True)
    cupons = [m for m in msgs if m.startswith("🎟️")]
    assert len(cupons) == 1 and "PS5200" in cupons[0] and "TVS300" not in cupons[0]


# ------------------------------------------------------------------------------------------------
# estado, histórico e latest por produto
# ------------------------------------------------------------------------------------------------

def test_minimo_historico_e_latest_por_produto(dados):
    _state(dados, modelos_iniciados=["55C6K", "65C6K", "PS5_DIGITAL"])
    of = [Oferta("netshoes", "loja", "Netshoes", "PlayStation 5 Edição Digital", "https://n/1", "D32", preco=4549.0,
                 preco_pix=4094.10, vendedor="Magalu Oficial", modelo="PS5_DIGITAL", extra={"vendedor_id": "29198"}),
          Oferta("kabum", "loja", "KaBuM!", "Console PS5 Digital Wolverine", "https://k/1", "1065184", preco=5099.0,
                 preco_pix=4742.07, vendedor="KaBuM!", modelo="PS5_KIT")]
    est, _ = _rodada(of)
    assert est.minimo("PS5_DIGITAL")["preco"] == 4094.10 and est.minimo("PS5_DIGITAL")["modelo"] == "PS5_DIGITAL"
    assert est.minimo("PS5_KIT") is None              # kit mistura edições: sem "menor já visto"
    lt = json.loads((dados / "latest_cloud.json").read_text(encoding="utf-8"))
    assert lt["minimo_PS5_DIGITAL"]["preco"] == 4094.10 and "minimo_PS5_KIT" not in lt
    assert lt["produtos"]["PS5_DIGITAL"]["nome"] == "PS5 Slim Digital" and lt["produtos"]["55C6K"]["familia"] == "TV"
    assert "gta6_custo_final" in lt
    kit = next(o for o in lt["ofertas_loja"] if o["modelo"] == "PS5_KIT")
    assert kit["extra"]["alvo"]["pix"] == 3750.0 and kit["extra"]["produto"]["base"] == "PS5_DIGITAL"
    linhas = (dados / "historico_cloud.csv").read_text(encoding="utf-8").splitlines()
    assert linhas[0].endswith(",modelo") and any(l.endswith(",PS5_DIGITAL") for l in linhas[1:])
    assert est.dados["modelos_iniciados"] == ["55C6K", "65C6K", "PS5_DIGITAL", "PS5_KIT"]


def test_registro_antigo_sem_modelo_continua_da_55(dados):
    assert modelo_de({}) == "55C6K" and modelo_de({"modelo": "xyz"}) == "55C6K"
    assert modelo_de({"modelo": "gta6_code_in_box"}) == "GTA6_CODE_IN_BOX"
    assert chave_minimo("PS5_PRO") == "minimo_PS5_PRO" and chave_minimo("55C6K") == "minimo"


def test_sanear_descarta_preco_fora_da_faixa_do_produto():
    jogo_como_console = Oferta("x", "loja", "Amazon", "PS5 (jogo)", "u", "1", preco=399.0, modelo="PS5_DIGITAL")
    console_como_jogo = Oferta("x", "loja", "Amazon", "GTA", "u", "2", preco=3999.0, modelo="GTA6_CODE_IN_BOX")
    ok = Oferta("x", "loja", "Amazon", "PS5", "u", "3", preco=3999.0, modelo="PS5_DIGITAL")
    _of, avisos = sanear([jogo_como_console, console_como_jogo, ok])
    assert not jogo_como_console.ativo and not console_como_jogo.ativo and ok.ativo and len(avisos) == 2


# ------------------------------------------------------------------------------------------------
# confiança por produto
# ------------------------------------------------------------------------------------------------

def test_referencia_de_preco_e_do_mesmo_produto(dados):
    _state(dados)
    est = Estado("cloud")
    confiavel = Oferta("netshoes", "loja", "Netshoes", "PS5 Digital", "https://n/1", "D32", preco=4549.0,
                       preco_pix=4094.10, vendedor="Magalu Oficial", modelo="PS5_DIGITAL",
                       extra={"vendedor_id": "29198"})
    golpe = Oferta("magalu", "loja", "Magazine Luiza", "PS5 Digital", "https://m/p/abc/?seller_id=lojax",
                   "abc-lojax", preco=2900.0, vendedor="Loja X", modelo="PS5_DIGITAL",
                   extra={"vendedor_id": "lojax", "ficha": {"anatel": "09573-24-00953", "avaliacoes": 3}})
    pro = Oferta("kabum", "loja", "KaBuM!", "PS5 Pro", "https://k/1", "636960", preco=7299.0, vendedor="KaBuM!",
                 modelo="PS5_PRO")
    gta = Oferta("kabum", "loja", "KaBuM!", "GTA VI", "https://k/2", "1051619", preco=449.9, preco_pix=418.41,
                 vendedor="Loja Nova", modelo="GTA6_CODE_IN_BOX", extra={"vendedor_id": "999"})
    confianca.avaliar(est, [confiavel, golpe, pro, gta], rede=False)
    assert confianca.veredito_de(confiavel) == confianca.CONFIAVEL
    assert confianca.veredito_de(golpe) == confianca.SUSPEITO       # 2.900 é 29% abaixo dos 4.094,10 confiáveis
    assert any("menor que o da loja confiável mais barata" in s for s in golpe.extra["confianca"]["sinais"])
    # a homologação da TV não vale para o PS5 (sem o sinal de Anatel)
    assert not any("Anatel" in s for s in golpe.extra["confianca"]["sinais"])
    # o GTA não é comparado com o preço do PS5
    assert confianca.veredito_de(gta) == confianca.SEM_RISCO
    assert confianca.chave_referencia(Oferta("x", "post", "N", "Gift Card PlayStation R$ 300", "u", "g",
                                             modelo="GIFT_CARD_PSN")) == "GIFT_CARD_PSN|300.0"


def test_catalogo_do_vendedor_sem_games_e_sinal_de_identidade():
    o = Oferta("magalu", "loja", "Magazine Luiza", "PS5 Digital", "u", "a-x", preco=3000.0, vendedor="X",
               modelo="PS5_DIGITAL", extra={"vendedor_id": "x"})
    cat = {"total": 2667, "tv": 9, "eletronicos": 40, "games": 2, "eletronicos_games": 50, "principais": ["Brinquedos"]}
    sinais, _ = confianca.sinais_da_oferta(o, confianca.Referencias(), cat)
    assert [s.codigo for s in sinais] == ["catalogo_sem_games"] and "catalogo_sem_games" in confianca.SINAIS_DE_IDENTIDADE
    # catálogo antigo (sem a contagem de games): sem sinal
    sinais, _ = confianca.sinais_da_oferta(o, confianca.Referencias(), {"total": 2667, "tv": 9, "eletronicos": 40})
    assert not sinais


def test_listas_de_confianca_tem_os_vendedores_do_ps5():
    ns = Oferta("netshoes", "loja", "Netshoes", "PS5", "u", "1", vendedor="Magalu Oficial", modelo="PS5_DIGITAL",
                extra={"vendedor_id": "29198"})
    ml = Oferta("mercadolivre", "loja", "Mercado Livre", "PS5", "u", "2", vendedor="PlayStation", modelo="PS5_DIGITAL",
                extra={"vendedor_id": "1047493289"})
    assert confianca.classifica_por_lista(ns, ())[0] == confianca.CONFIAVEL
    assert confianca.classifica_por_lista(ml, ())[0] == confianca.CONFIAVEL


# ------------------------------------------------------------------------------------------------
# fontes de postagens
# ------------------------------------------------------------------------------------------------

def test_promobit_classifica_por_produto():
    item = {"offer_id": 3078009, "offer_title": "Console Playstation 5 Pro Sony SSD 2TB", "offer_slug": "ps5-pro",
            "store_name": "Netshoes", "offer_price": 5999.99, "offer_status_name": "APPROVED"}
    o = promobit._oferta_de_item(item, True)
    assert (o.modelo, o.loja, o.preco) == ("PS5_PRO", "Netshoes", 5999.99)
    item2 = dict(item, offer_title="Gift Card PlayStation R$ 300", offer_price=242.74, offer_id=1)
    g = promobit._oferta_de_item(item2, True)
    assert g.modelo == "GIFT_CARD_PSN" and g.extra["produto"]["valor_face"] == 300.0
    assert promobit._oferta_de_item(dict(item, offer_title="Controle DualSense Branco"), True) is None


def _html_canal(*msgs: str) -> str:
    corpo = "".join(
        f'<div class="tgme_widget_message" data-post="pelandobr/{i}"><div class="tgme_widget_message_text">'
        f'{m.replace(chr(10), "<br>")}</div><time datetime="{agora_iso()}"></time></div>' for i, m in enumerate(msgs, 1))
    return f"<html><body>{corpo}</body></html>"


def test_telegram_um_post_por_produto_com_a_loja_do_pelandobr():
    html = _html_canal(
        "Console PlayStation 5 Pro Sony SSD 2TB com Controle sem fio DualSense\n💰 R$ 6009,35\n📍 Netshoes\npelando.promo/a",
        "🎮 PS5 Slim Digital — R$ 3.599\n🎮 GTA 6 Code in Box — R$ 341\nNa Netshoes",
        "Smart TV 65” TCL 4K QD-Mini LED Google TV 65C6K\n💰 R$ 3527,00\n📍 Mais Correios\npelando.promo/b")
    ofs = {o.id: o for o in telegram_public.parse_canal(html, "pelandobr")}
    assert ofs["pelandobr/1#PS5_PRO"].preco == 6009.35 and ofs["pelandobr/1#PS5_PRO"].loja == "Netshoes"
    assert ofs["pelandobr/2#PS5_DIGITAL"].preco == 3599.0 and ofs["pelandobr/2#GTA6_CODE_IN_BOX"].preco == 341.0
    # o post da TV comprada (01/10): a loja agora sai certa
    assert ofs["pelandobr/3#65C6K"].loja == "Mais Correios" and ofs["pelandobr/3#65C6K"].preco == 3527.0


# ------------------------------------------------------------------------------------------------
# painel: uma seção por família
# ------------------------------------------------------------------------------------------------

def test_painel_mostra_as_secoes_do_ps5_e_do_gta(tmp_path):
    import test_painel as tp

    if not tp.NODE:
        pytest.skip("node não encontrado no PATH")
    harness = tp.HARNESS.replace(
        "process.stdout.write(JSON.stringify(saida));",
        "saida.secoes = {ps5: el('secao-PS5').innerHTML, gta: el('secao-GTA6').innerHTML};\n"
        "  process.stdout.write(JSON.stringify(saida));")
    cat = produtos.para_painel()
    ps5 = tp.oferta("netshoes", "Netshoes", 4549.0, 4094.10, vendedor="Magalu Oficial",
                    parcelado="10x R$ 454,90 sem juros", oid="D32")
    ps5.update(modelo="PS5_DIGITAL", titulo="PlayStation 5 Edição Digital")
    gta = tp.oferta("kabum", "KaBuM!", 449.9, 418.41, vendedor="KaBuM!", oid="1051619")
    gta.update(modelo="GTA6_CODE_IN_BOX", titulo="GTA VI", extra={"entrega": {"classe": "a_tempo", "data": "2026-11-17",
               "texto": "📦 Entrega: previsão 17/11 — chega a tempo ✅"}, "alvo": {"pix": 345.0, "nota": ""}})
    cloud = tp.latest("cloud", tp.CLOUD_AT, [*tp.ofertas_cloud_hoje(), ps5, gta], tp.MIN_MAGALU)
    cloud["produtos"] = cat
    cloud["gta6_custo_final"] = [{"produto": "GTA6_CODE_IN_BOX", "forma": "GTA 6 PS5 Code in Box", "loja": "KaBuM!",
                                  "tipo": "loja", "url": "https://k", "preco": 418.41, "custo_final": 418.41,
                                  "entrega": "a_tempo", "entrega_texto": "chega a tempo", "meta": 345.0}]
    cloud["posts"] = [{"fonte": "promobit", "tipo": "post", "loja": "Netshoes", "titulo": "PS5 Slim Digital",
                       "url": "https://p/1", "id": "1", "chave": "promobit:1", "preco": 3599.0, "melhor_preco": 3599.0,
                       "publicado": "2026-09-18T10:00:00-03:00", "modelo": "PS5_DIGITAL"}]
    dados = tmp_path / "dados.json"
    dados.write_text(json.dumps({"agora": tp.AGORA, "formatar": [], "arquivos": {
        "data/latest_cloud.json": cloud, "data/latest_pc.json": tp.latest("pc", tp.PC_AT, tp.ofertas_pc_hoje(),
                                                                         tp.MIN_AMAZON),
        "data/historico_cloud.csv": tp.CSV_CLOUD, "data/historico_pc.csv": tp.CSV_PC}}, ensure_ascii=False),
        encoding="utf-8")
    h = tmp_path / "h.js"
    h.write_text(harness, encoding="utf-8")
    p = subprocess.run([tp.NODE, str(h), str(tp.INDEX), str(dados)], capture_output=True, text=True, encoding="utf-8",
                       timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["erro"] is None, out["erro"]
    # as TVs continuam como antes (o PS5 e o GTA não entram na tabela nem no destaque da 55")
    assert out["melhor"] == tp.brl(3561.55) and "Netshoes" not in out["tabela"]
    s = out["secoes"]
    assert "<h2>PS5</h2>" in s["ps5"] and "PS5 Slim Digital" in s["ps5"] and tp.brl(4094.10) in s["ps5"]
    assert tp.brl(3550.0) in s["ps5"] and (tp.brl(4094.10 - 3550.0) + " acima") in s["ps5"]
    assert "<h2>GTA 6</h2>" in s["gta"] and "Todas as formas pelo custo final" in s["gta"]
    assert "chega até 18/11" in s["gta"] and "chega a tempo" in s["gta"]
    assert out["graficos"]["chart-PS5_DIGITAL"]["alvo"] == 3550.0
    assert 'class="chip mp">PS5 Digital</span>' in out["l-posts"]
