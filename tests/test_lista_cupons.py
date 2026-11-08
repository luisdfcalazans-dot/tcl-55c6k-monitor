"""Lista diária "🎟️ Cupons ativos" no Telegram e o canal novo do Telegram (pedidos de 08/11/2026).

Cobre: o valor do desconto lido dos títulos reais (Pelando e Promobit), a regra de "ativo" (validade, publicado há até
CUPONS_ATIVOS_DIAS dias, código datado DDMM só no dia, código que dá para digitar, testador), a deduplicação entre os
modos, a leitura do outro modo (latest e última leitura do state), o formato (ordem das lojas, linha em branco entre
lojas, <code>, escape de HTML), a divisão em mensagens, e o run.py (uma vez por dia junto com o resumo, forçada com
--resumo/--cupons, nunca no modo pc sem pedido). Nada vai à rede e nada lê ou grava o docs/data do repositório.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from monitor import config, lista_cupons as lc
from monitor.estado import Estado
from monitor.models import Cupom
from monitor.regras import e_mensagem_de_cupons
from monitor.util import agora, agora_iso, hoje

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    """docs/data num diretório temporário; o testador começa vazio; 3 dias para cupom sem validade (o padrão)."""
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    monkeypatch.setattr(config, "CUPONS_ATIVOS_DIAS", 3.0)
    monkeypatch.setattr(config, "CUPONS_ATIVOS_MAX_POR_LOJA", 0)
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", None)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    return tmp_path


def _iso(**delta) -> str:
    return (agora() - timedelta(**delta)).isoformat(timespec="seconds")


def _ddmm(dias_atras: int = 0) -> str:
    return f"{agora() - timedelta(days=dias_atras):%d%m}"


def _cupom(codigo, titulo, loja="Mercado Livre", fonte="pelando", regra="", validade=None, publicado=None, **kw):
    return {"fonte": fonte, "loja": loja, "codigo": codigo, "titulo": titulo, "url": "https://exemplo/cupons",
            "id": f"{fonte}-{codigo}-{titulo[:10]}", "regra": regra, "validade": validade,
            "publicado": publicado if publicado is not None else _iso(hours=2), **kw}


# ---------------------------------------------------------------------------------------------------------------------
# valor do desconto
# ---------------------------------------------------------------------------------------------------------------------
AVISO_ML = ("🚨 Fiquem atentos: A maioria dos cupons do Mercado Livre agora se aplica apenas a itens selecionados. "
            "📌 Dica: Na hora de adicionar o cupom, clique em \"Conferir lista\" para ver todos os produtos "
            "participantes.")


@pytest.mark.parametrize("titulo, regra, esperado", [
    ("Cupom Mercado Livre - R$10 OFF acima de R$99 em Todo Site", "Cupom Diz Todo Site, confiram",
     "R$ 10 OFF · mín. R$ 99 · todo site"),
    ("Cupom Mercado Livre - 15% OFF acima de R$500 limitado à R$100 Som Vídeo Eletro", AVISO_ML,
     "15% OFF · mín. R$ 500 · até R$ 100 · som vídeo eletro"),
    ("R$400 OFF", "", "R$ 400 OFF"),
    ("12% OFF acima de R$ 149 (até R$ 200) em Eletrônicos", "", "12% OFF · mín. R$ 149 · até R$ 200 · eletrônicos"),
    ("R$ 500 de desconto em compras a partir de R$ 3.700", "produtos Aliexpress", "R$ 500 OFF · mín. R$ 3.700"),
    # Pelando sem "OFF"
    ("Cupom Aliexpress R$ 490 em R$ 3200", "Cupom válido em várias coisas", "R$ 490 OFF · mín. R$ 3.200"),
    ("Cupom Aliexpress R$ 785 acima de R$ R$ 4200", "", "R$ 785 OFF · mín. R$ 4.200"),
    ("A chance de economizar R$50 em compras na Magazine Luiza", "produtos Magazine Luiza", "R$ 50 OFF"),
    # Promobit: o mínimo e o teto estão na regra
    ("Cupom de desconto Mercado Livre oferece 30% OFF em suas compras",
     "produtos Mercado Livre Compra mínima de R$29. Limite de desconto: R$500", "30% OFF · mín. R$ 29 · até R$ 500"),
    # "compras de até R$ 1000" é o teto da COMPRA, não do desconto
    ("Cupom Magazine Luiza R$ 10% OFF em  compras de até R$ 1000", "", "10% OFF · compras até R$ 1.000"),
    ("Cupom Shopee oferece 10% OFF, máximo R$ 50, em R$ 59 em ITENS SELECIONADOS", "",
     "10% OFF · mín. R$ 59 · até R$ 50 · itens selecionados"),
    ("Cupom Mercado Livre 12% OFF acima de R$ 79 (Limitado a R$ 60 OFF) em Moda", "",
     "12% OFF · mín. R$ 79 · até R$ 60 · moda"),
    ("HORA DO GAME: 5% OFF em Gift Cards na Nuuvem com cupom + PIX", "produtos Nuuvem", "5% OFF · gift cards"),
    ("R$ 350.00 OFF com cupom: LU350", "R$ 350.00 OFF com cupom: LU350", "R$ 350 OFF"),
    ("Frete grátis em compras acima de R$ 99", "", "frete grátis · mín. R$ 99"),
    # o título gerado pelo site diz "todo o site"; a regra diz que é uma lista
    ("Desconto de 15% em todo o site da Netshoes", "produtos Netshoes VÁLIDO PARA PRODUTOS SELECIONADOS NO LINK",
     "15% OFF · itens selecionados"),
    # o aviso genérico do Pelando no ML não transforma todo cupom em "itens selecionados"
    ("Cupom Mercado Livre - R$40 OFF acima de R$399 Todo Site", AVISO_ML, "R$ 40 OFF · mín. R$ 399 · todo site"),
    ("Ganhe R$15 OFF em suas compras aplicando o cupom AliExpress", "", "R$ 15 OFF"),
    # frase do site não é escopo; a categoria depois de "desconto em" é
    ("Use o cupom e ganhe 15% de desconto no seu carrinho", "", "15% OFF"),
    ("Ganhe 20% de desconto em botas Acero", "", "20% OFF · botas acero"),
    ("Garanta 5% OFF em sua primeira compra na KaBuM!", "", "5% OFF · 1ª compra"),
    # o título do anúncio no Promobit às vezes traz o preço do produto no lugar do desconto
    ("O momento chegou: Aplique cupom Fast Shop e ganhe R$ 5.229.90 OFF", "produtos Fast Shop",
     "valor a conferir (o anúncio diz R$ 5.229,90 OFF)"),
])
def test_valor_do_cupom_com_titulos_reais(titulo, regra, esperado):
    assert lc.texto_do_valor(lc.valor_do_cupom(titulo, regra), titulo) == esperado


def test_valor_desconto_minimo_e_teto_separados():
    v = lc.valor_do_cupom("Cupom Mercado Livre - 15% OFF acima de R$500 limitado à R$100 Som Vídeo Eletro")
    assert (v.desconto, v.minimo, v.teto, v.escopo) == (("%", 15.0), 500.0, 100.0, "som vídeo eletro")
    v = lc.valor_do_cupom("R$400 OFF")
    assert (v.desconto, v.minimo, v.teto) == (("R$", 400.0), None, None)
    v = lc.valor_do_cupom("12% OFF acima de R$ 149 (até R$ 200) em Eletrônicos")
    assert (v.desconto, v.minimo, v.teto) == (("%", 12.0), 149.0, 200.0)


def test_valor_marcas_de_app_assinante_e_titulo_ilegivel():
    t = lc.texto_do_valor(lc.valor_do_cupom("[APP/PRIME] 20% OFF em Brinquedos e Jogos"))
    assert t.startswith("20% OFF · brinquedos e jogos") and "só no app" in t and "Prime/assinante" in t
    # sem desconto legível: o título resumido (até ~70 caracteres)
    assert lc.texto_do_valor(lc.valor_do_cupom("Cupom especial da loja"), "Cupom especial da loja") == \
        "Cupom especial da loja"
    longo = "Cupom secreto que vale em muita coisa da loja inteira mas ninguém sabe dizer quanto vale de verdade"
    t = lc.texto_do_valor(lc.valor_do_cupom(longo), longo)
    assert t.endswith("…") and len(t) <= 71


def test_fmt_reais_sem_centavos_quando_inteiro():
    assert lc.fmt_reais(1200) == "R$ 1.200"
    assert lc.fmt_reais(99.9) == "R$ 99,90"
    assert lc.fmt_reais(10) == "R$ 10"


# ---------------------------------------------------------------------------------------------------------------------
# regra de "ativo"
# ---------------------------------------------------------------------------------------------------------------------
def test_codigo_datado_de_ontem_fora_e_de_hoje_dentro():
    ontem = _cupom(f"TODOSITE{_ddmm(1)}", "Cupom Mercado Livre - R$40 OFF acima de R$399 Todo Site",
                   publicado=_iso(hours=20))
    hoje_ = _cupom(f"TODOSITE{_ddmm(0)}", "Cupom Mercado Livre - R$10 OFF acima de R$99 em Todo Site")
    minusculo = _cupom(f"eletro{_ddmm(0)}", "Cupom Mercado Livre - 15% OFF acima de R$500 limitado à R$100")
    no_meio = _cupom(f"SITE{_ddmm(1)}TODO", "Cupom Mercado Livrer R$220 OFF acima de R$1499 Todo Site",
                     publicado=_iso(hours=20))
    assert lc.motivo_inativo(ontem).startswith("código de")
    assert lc.motivo_inativo(no_meio).startswith("código de"), "no ML o DDMM pode estar no meio do código"
    assert lc.motivo_inativo(hoje_) == "" and lc.motivo_inativo(minusculo) == ""
    ativos = lc.cupons_ativos([ontem, hoje_, minusculo, no_meio], expirados=set())
    assert {c["codigo"] for c in ativos["Mercado Livre"]} == {f"TODOSITE{_ddmm(0)}", f"eletro{_ddmm(0)}"}


def test_codigo_datado_fora_do_ml_so_com_a_data_perto_da_publicacao():
    # como o PS0707 da Hype (publicado em 07/07 com o código "do dia"), mas com validade explícita no futuro: ela vale
    hype = _cupom(f"PS{_ddmm(5)}", "DESBLOQUEIE O PLAY: 7% OFF em Giftcard Playstation (acima de R$150)", loja="Hype",
                  fonte="promobit", publicado=_iso(days=5),
                  validade=(agora() + timedelta(days=20)).isoformat(timespec="seconds"))
    assert lc.motivo_inativo(hype) == ""
    # sem validade, o código que termina na data da publicação é datado (de outro dia: fora)
    assert lc.data_no_codigo("NATAL2512", "Americanas", "2026-12-25T10:00:00-03:00") == (25, 12)
    assert lc.data_no_codigo("TECH1500", "KaBuM!", None) is None, "15/00 não é data"
    assert lc.data_no_codigo("CUPOM0711", "KaBuM!", "2026-03-01T10:00:00-03:00") is None, "longe da publicação"
    assert lc.data_no_codigo("ALLSITE04011", "Mercado Livre") is None, "5 dígitos não é DDMM"


def test_validade_vencida_fora_e_validade_futura_dentro():
    vencido = _cupom("VENCEU10", "10% OFF em tudo", loja="KaBuM!", fonte="promobit",
                     validade=_iso(hours=1), publicado=_iso(hours=3))
    valido = _cupom("VALE10", "10% OFF em tudo", loja="KaBuM!", fonte="promobit",
                    validade=(agora() + timedelta(days=3)).isoformat(timespec="seconds"), publicado=_iso(days=40))
    so_data = _cupom("DIAINTEIRO", "10% OFF em tudo", loja="KaBuM!", fonte="promobit", validade=hoje(),
                     publicado=_iso(days=40))
    assert lc.motivo_inativo(vencido) == "vencido"
    assert lc.motivo_inativo(valido) == "", "com validade, a data de publicação não importa"
    assert lc.motivo_inativo(so_data) == "", "validade só com a data vale até o fim do dia"


def test_validade_escrita_no_texto():
    reg = _cupom("AEMEGA7", "Cupom Aliexpress R$ 400 OFF acima de R$ 2.500", loja="AliExpress",
                 regra="Esquenta: 29.10.2026 às 00h01 até 31.10.2026 às 23h59\n"
                       f"Vendas Oficiais: 01.11.2026 às 00h01 até {agora() + timedelta(days=5):%d.%m.%Y} às 23h59",
                 publicado=_iso(days=7))
    assert lc.motivo_inativo(reg) == "", "vale a maior data do texto, não a do esquenta"
    velho = dict(reg, regra="Validade: até 31/10/2025.", codigo="VELHO1")
    assert lc.motivo_inativo(velho) == "vencido"


def test_publicado_ha_5_dias_fora_e_ha_2_dentro(monkeypatch):
    # fonte sem sinal de status (o Promobit sem validade): a janela de CUPONS_ATIVOS_DIAS
    velho = _cupom("VELHO10", "Cupom Mercado Livre - 10% OFF acima de R$79 limitado à R$40", fonte="promobit",
                   publicado=_iso(days=5))
    novo = _cupom("NOVO10", "Cupom Mercado Livre - 10% OFF acima de R$79 limitado à R$40", fonte="promobit",
                  publicado=_iso(days=2))
    assert lc.motivo_inativo(velho).startswith("publicado há")
    assert lc.motivo_inativo(novo) == ""
    monkeypatch.setattr(config, "CUPONS_ATIVOS_DIAS", 7.0)
    assert lc.motivo_inativo(velho) == "", "CUPONS_ATIVOS_DIAS muda a janela sem mexer no código"


def test_so_codigo_que_da_para_digitar():
    for cod in ("Resgate no link", "Direto no link", "MTQxNDc5NTg5OQ==", "PRIME10DO10*", "-", ""):
        assert lc.motivo_inativo(_cupom(cod, "Cupom Shopee oferece até R$160 OFF", loja="Shopee")) == "sem código", cod
    auto = _cupom("", "Desconto automático de 10% no carrinho em eletrônicos", loja="Americanas")
    assert lc.motivo_inativo(auto) == ""
    m = lc.mensagens_cupons_ativos([auto], expirados=set())[0]
    assert "sem código (automático)" in m and "10% OFF" in m


def test_cupom_do_anuncio_sem_data_fica_e_cupom_do_site_sem_data_sai():
    anuncio = _cupom("LU350", "R$ 350.00 OFF com cupom: LU350", loja="Magazine Luiza", fonte="magalu",
                     publicado="", especifico=True, modelo="PS5_DIGITAL")
    site = _cupom("SEMDATA", "R$ 30 OFF", loja="Magazine Luiza", publicado="")
    assert lc.motivo_inativo(anuncio) == "" and lc.motivo_inativo(site) == "sem data"
    m = lc.mensagens_cupons_ativos([anuncio], expirados=set())[0]
    assert "<code>LU350</code> — R$ 350 OFF · só no anúncio do PS5 Slim Digital ⭐" in m


def _testador(dados, cupons_ml: dict, cupons_magalu: dict | None = None):
    arq = {"mercadolivre": {"cupons": cupons_ml}, "magalu": {"cupons": cupons_magalu or {}}}
    (dados / "cupons_carrinho.json").write_text(json.dumps(arq, ensure_ascii=False), encoding="utf-8")


def test_testador_tira_codigo_expirado_mas_nao_o_que_so_nao_serve_no_produto(dados):
    _testador(dados, {
        "ACABOU": {"testado_em": _iso(hours=5), "aceito": False, "mensagem": "O cupom não está mais disponível."},
        "NAOSERVE": {"testado_em": _iso(hours=5), "aceito": False, "mensagem": "Este cupom não se aplica a você."},
        "ANTIGO": {"testado_em": _iso(days=3), "aceito": False, "mensagem": "O cupom não está mais disponível."},
        "VOLTOU@MLB1": {"testado_em": _iso(hours=5), "aceito": False, "mensagem": "O cupom não está mais disponível."},
        "VOLTOU@MLB2": {"testado_em": _iso(hours=2), "aceito": True, "mensagem": ""},
    }, {"LU400@123-magazineluiza": {"testado_em": _iso(hours=1), "aceito": False, "mensagem":
                                    "Este cupom não foi aplicado. Pode ter algum erro de digitação ou não estar mais "
                                    "ativo."},
        "LU50@123-magazineluiza": {"testado_em": _iso(hours=1), "aceito": False,
                                   "mensagem": "Este cupom LU50 não se aplica para este pedido."}})
    exp = lc.expirados_no_testador()
    assert exp == {"Mercado Livre|ACABOU", "Magazine Luiza|LU400"}
    regs = [_cupom("acabou", "R$ 10 OFF"), _cupom("NAOSERVE", "R$ 10 OFF"), _cupom("ANTIGO", "R$ 10 OFF"),
            _cupom("VOLTOU", "R$ 10 OFF"), _cupom("LU400", "R$ 400 OFF", loja="Magazine Luiza"),
            _cupom("LU50", "R$ 50 OFF", loja="Magazine Luiza")]
    ativos = lc.cupons_ativos(regs)   # sem `expirados`: lê o testador
    codigos = {c["codigo"] for lista in ativos.values() for c in lista}
    assert codigos == {"NAOSERVE", "ANTIGO", "VOLTOU", "LU50"}


def test_testador_ausente_ou_quebrado_nao_tira_nada(dados):
    assert lc.expirados_no_testador() == set()
    (dados / "cupons_carrinho.json").write_text("{quebrado", encoding="utf-8")
    assert lc.expirados_no_testador() == set()


def test_cupom_de_tv_fora_com_as_tvs_desligadas(monkeypatch):
    monkeypatch.setattr(config, "TVS_DESLIGADAS", True)
    tv = _cupom("TV100", "R$ 100 OFF", loja="Magazine Luiza", especifico=True, modelo="55C6K")
    assert lc.cupons_ativos([tv], expirados=set()) == {}


# ---------------------------------------------------------------------------------------------------------------------
# deduplicação (entre fontes e modos)
# ---------------------------------------------------------------------------------------------------------------------
def test_dedupe_sem_diferenca_de_maiusculas_fica_o_registro_mais_completo():
    promobit = _cupom("affnov07", "A chance de economizar R$ 2.569 em compras na Aliexpress", loja="aliexpress",
                      fonte="promobit", publicado=_iso(hours=1))
    pelando = _cupom("AFFNOV07", "Cupom Aliexpress R$ 400 OFF acima de R$ 2.500", loja="AliExpress",
                     publicado=_iso(hours=10), _modo="pc")
    ativos = lc.cupons_ativos([promobit, pelando], expirados=set())
    assert list(ativos) == ["AliExpress"] and len(ativos["AliExpress"]) == 1
    assert ativos["AliExpress"][0]["_texto"] == "R$ 400 OFF · mín. R$ 2.500"
    # Cupom (objeto) e registro (dict) do mesmo código: um só
    obj = Cupom("pelando", "Mercado Livre", "BUDBLACK", "Cupom Mercado Livre - 10% OFF acima de R$1 limitado a R$999",
                "https://x", "1", publicado=_iso(hours=3))
    reg = _cupom("budblack", "Cupom Mercado Livre - 10% OFF acima de R$1 limitado a R$999", _modo="pc")
    assert len(lc.cupons_ativos([obj, reg], expirados=set())["Mercado Livre"]) == 1


def test_dedupe_usa_o_valor_do_anuncio_mais_completo_mesmo_fora_da_janela():
    """Como o AFFNOV22 em 08/11: o Promobit diz que vale até 10/11, mas o título do anúncio traz outro valor; o Pelando
    tem o valor certo num anúncio fora da janela dele. Entra pelo Promobit, com o valor do Pelando."""
    vence = agora() + timedelta(days=2)
    promobit = _cupom("AFFNOV22", "A chance de economizar R$ 4.369 em compras na Aliexpress", loja="AliExpress",
                      fonte="promobit", validade=vence.isoformat(timespec="seconds"), publicado=_iso(days=6))
    pelando = _cupom("AFFNOV22", "Cupom R$620 off em R$4200 aliexpress", loja="AliExpress", publicado=_iso(days=20))
    assert lc.motivo_inativo(pelando).startswith("publicado há")
    m = lc.mensagens_cupons_ativos([promobit, pelando], expirados=set())[0]
    assert f"<code>AFFNOV22</code> — R$ 620 OFF · mín. R$ 4.200 · vence {vence:%d/%m}" in m
    # sem nenhum anúncio ativo, o código não entra
    assert lc.cupons_ativos([pelando], expirados=set()) == {}


def test_maximo_de_cupons_por_loja(monkeypatch):
    monkeypatch.setattr(config, "CUPONS_ATIVOS_MAX_POR_LOJA", 2)
    regs = [_cupom(f"KAB{i}0", f"{i * 5}% OFF", loja="KaBuM!", fonte="promobit") for i in range(1, 6)]
    m = lc.mensagens_cupons_ativos(regs, expirados=set())[0]
    assert "🛒 <b>KABUM!</b> (5)" in m
    assert "<code>KAB50</code>" in m and "<code>KAB40</code>" in m and "<code>KAB30</code>" not in m
    assert "<i>… e mais 3 códigos de lista, categoria ou menor desconto</i>" in m


# ---------------------------------------------------------------------------------------------------------------------
# outro modo: latest e última leitura do state
# ---------------------------------------------------------------------------------------------------------------------
def _grava(dados, nome, conteudo):
    (dados / nome).write_text(conteudo if isinstance(conteudo, str) else json.dumps(conteudo, ensure_ascii=False),
                              encoding="utf-8")


def test_cupons_do_outro_modo_latest_e_ultima_leitura_do_state(dados):
    agora_, antes = _iso(minutes=5), _iso(minutes=35)
    cupons = {
        "pelando:1": dict(_cupom("NOVO1", "R$ 10 OFF"), ultima_vez=agora_),
        "pelando:2": dict(_cupom("NOVO2", "R$ 20 OFF"), ultima_vez=_iso(minutes=8)),
        "pelando:3": dict(_cupom("ANTES3", "R$ 30 OFF"), ultima_vez=antes),   # leitura anterior: não está mais lá
        "magalu:4": dict(_cupom("VELHO4", "R$ 40 OFF", fonte="magalu"), ultima_vez=_iso(hours=40)),   # > 36 h
    }
    _grava(dados, "state_pc.json", {"ofertas": {}, "cupons": cupons})
    _grava(dados, "latest_pc.json", {"atualizado": agora_, "cupons": [_cupom("DOLATEST", "R$ 50 OFF")]})
    regs = Estado("cloud").cupons_de_outros_modos()
    assert sorted(r["codigo"] for r in regs) == ["DOLATEST", "NOVO1", "NOVO2"]
    assert all(r["_modo"] == "pc" for r in regs)


def test_cupons_do_outro_modo_latest_velho_e_arquivos_quebrados(dados):
    _grava(dados, "latest_pc.json", {"atualizado": _iso(hours=50), "cupons": [_cupom("VELHO", "R$ 5 OFF")]})
    _grava(dados, "state_pc.json", "{quebrado")
    assert Estado("cloud").cupons_de_outros_modos() == []
    _grava(dados, "latest_pc.json", "[]")
    assert Estado("cloud").cupons_de_outros_modos() == []


def test_ultima_leitura_deste_modo(dados):
    est = Estado("cloud")
    est.dados["cupons"] = {"promobit:1": dict(_cupom("A1", "R$ 1 OFF", fonte="promobit"), ultima_vez=_iso(minutes=1)),
                           "promobit:2": dict(_cupom("B2", "R$ 2 OFF", fonte="promobit"), ultima_vez=_iso(hours=3))}
    assert [r["codigo"] for r in est.cupons_da_ultima_leitura()] == ["A1"]


# ---------------------------------------------------------------------------------------------------------------------
# formato
# ---------------------------------------------------------------------------------------------------------------------
def _varias_lojas():
    return [
        _cupom("ZATT10", "10% OFF", loja="Zattini", fonte="promobit"),
        _cupom("BOTI15", "15% OFF", loja="Boticário", fonte="promobit"),
        _cupom("NET15", "15% OFF", loja="Netshoes", fonte="promobit"),
        _cupom("ALI50", "Cupom Aliexpress R$ 50 OFF acima de R$ 290", loja="AliExpress"),
        _cupom("MAGA30", "R$ 30 OFF", loja="Magazine Luiza"),
        _cupom("AMZ20", "20% OFF em itens selecionados", loja="Amazon"),
        _cupom("PEQUENO", "Cupom Mercado Livre - R$10 OFF acima de R$99 em Todo Site"),
        _cupom("GRANDE", "Cupom Mercado Livre - 25% OFF acima de R$1 limitado à R$500"),
        _cupom("MEDIO", "Cupom Mercado Livre - R$40 OFF acima de R$399 Todo Site"),
        _cupom("KAB5", "5% OFF", loja="KaBuM!", fonte="promobit"),
    ]


def test_formato_ordem_das_lojas_linha_em_branco_e_maior_desconto_primeiro():
    quando = agora().replace(day=8, month=11, hour=9, minute=31)
    msgs = lc.mensagens_cupons_ativos(_varias_lojas(), expirados=set(), quando=quando)
    assert len(msgs) == 1
    m = msgs[0]
    linhas = m.split("\n")
    assert linhas[0] == "🎟️ <b>Cupons ativos</b> · 08/11 09:31"
    assert linhas[1] == "<i>10 cupons em 8 lojas · toque no código para copiar</i>"
    lojas = re.findall(r"🛒 <b>([^<]+)</b> \((\d+)\)", m)
    assert [l for l, _n in lojas] == ["MERCADO LIVRE", "AMAZON", "MAGAZINE LUIZA", "KABUM!", "ALIEXPRESS", "NETSHOES",
                                      "BOTICÁRIO", "ZATTINI"]
    assert lojas[0][1] == "3"
    # uma linha em branco antes de cada loja
    for i, ln in enumerate(linhas):
        if ln.startswith("🛒"):
            assert linhas[i - 1] == "", ln
    # no ML, o maior desconto primeiro (25% até R$ 500 > R$ 40 > R$ 10)
    ml = m.split("🛒 <b>MERCADO LIVRE</b> (3)\n", 1)[1].split("\n\n", 1)[0].split("\n")
    assert [re.search(r"<code>(\w+)</code>", ln).group(1) for ln in ml] == ["GRANDE", "MEDIO", "PEQUENO"]
    assert "• <code>PEQUENO</code> — R$ 10 OFF · mín. R$ 99 · todo site" in ml
    assert m.endswith(lc.RODAPE)
    assert not e_mensagem_de_cupons(m), "a lista não é a mensagem de 'Novo cupom' (não mexe nos alertados)"


def test_formato_escapa_html():
    regs = [_cupom("SEGURO1", "Cupom <b>secreto</b> & especial", loja="Loja <X> & Cia", fonte="promobit")]
    m = lc.mensagens_cupons_ativos(regs, expirados=set())[0]
    assert "🛒 <b>LOJA &lt;X&gt; &amp; CIA</b> (1)" in m
    assert "• <code>SEGURO1</code> — Cupom &lt;b&gt;secreto&lt;/b&gt; &amp; especial" in m
    assert "<b>secreto</b>" not in m


def test_formato_codigos_com_o_mesmo_valor_na_mesma_linha():
    regs = [_cupom(c, "Cupom Aliexpress R$ 580 OFF acima de R$ 3.700", loja="AliExpress")
            for c in ("AEMEGA8", "AFFNOV08", "Pelando8")]
    m = lc.mensagens_cupons_ativos(regs, expirados=set())[0]
    assert "🛒 <b>ALIEXPRESS</b> (3)" in m
    assert re.search(r"• (<code>\w+</code> ou ){2}<code>\w+</code> — R\$ 580 OFF · mín\. R\$ 3\.700", m)


def test_sem_cupom_ativo_manda_aviso():
    msgs = lc.mensagens_cupons_ativos([_cupom("VELHO", "R$ 5 OFF", publicado=_iso(days=30))], expirados=set())
    assert len(msgs) == 1
    assert msgs[0].startswith("🎟️ <b>Cupons ativos</b> · ") and msgs[0].endswith("Nenhum cupom ativo encontrado hoje.")


def test_divisao_em_mensagens_sem_cortar_loja_pequena():
    regs = []
    for i in range(240):   # uma loja enorme (corta entre linhas, com "(cont.)")
        regs.append(_cupom(f"ML{i:03d}X", f"Cupom Mercado Livre - {i % 30 + 1}% OFF acima de R${i + 10} limitado à "
                                          f"R${i + 5} Categoria {i}"))
    for j in range(60):    # várias lojas pequenas
        regs.append(_cupom(f"LJ{j:03d}Y", f"R$ {j + 1} OFF acima de R$ {j + 100}", loja=f"Loja {j // 5:02d}",
                           fonte="promobit"))
    msgs = lc.mensagens_cupons_ativos(regs, expirados=set())
    n = len(msgs)
    assert n >= 3
    assert all(len(m) <= lc.LIMITE_MENSAGEM for m in msgs)
    assert msgs[0].startswith("🎟️ <b>Cupons ativos</b> · ") and msgs[0].split("\n")[0].endswith(f"(1/{n})")
    for i, m in enumerate(msgs[1:], 2):
        assert m.startswith(f"🎟️ <b>Cupons ativos</b> ({i}/{n})")
    tudo = "\n".join(msgs)
    for r in regs:
        assert tudo.count(f"<code>{r['codigo']}</code>") == 1, r["codigo"]
    assert "🛒 <b>MERCADO LIVRE</b> (cont.)" in tudo
    # loja pequena nunca é cortada: o título e todos os códigos dela na mesma mensagem
    for k in range(12):
        loja = f"LOJA {k:02d}"
        com_ela = [m for m in msgs if f"🛒 <b>{loja}</b>" in m]
        assert len(com_ela) == 1
        assert all(f"<code>LJ{j:03d}Y</code>" in com_ela[0] for j in range(k * 5, k * 5 + 5))
    assert msgs[-1].endswith(lc.RODAPE)
    assert not any(e_mensagem_de_cupons(m) for m in msgs)


# ---------------------------------------------------------------------------------------------------------------------
# config: canal novo e hora da lista
# ---------------------------------------------------------------------------------------------------------------------
def test_canal_linguicapromocoes_monitorado_e_sem_duplicados():
    canais = [c.lower() for c in config.TELEGRAM_CANAIS_PUBLICOS]
    assert "linguicapromocoes" in canais
    assert len(canais) == len(set(canais))


def test_hora_da_lista_segue_o_resumo_quando_nao_definida(monkeypatch):
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", None)
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", 7)
    assert config.hora_lista_cupons() == 7
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", -1)
    assert config.hora_lista_cupons() == -1


def test_workflow_tem_o_input_cupons():
    yml = (RAIZ / ".github" / "workflows" / "monitor.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s+cupons:\n\s+description: .+\n\s+type: boolean", yml, re.M)
    assert "CUPONS: ${{ github.event.inputs.cupons }}" in yml
    assert '[ "$CUPONS" = "true" ] && extra="$extra --cupons"' in yml


# ---------------------------------------------------------------------------------------------------------------------
# run.py: uma vez por dia, forçada, nunca no pc sem pedido
# ---------------------------------------------------------------------------------------------------------------------
def _state_inicial(dados, modo="cloud", **extra):
    d = {"ofertas": {}, "cupons": {}, "minimo": None, "saude": {}, "ultimo_resumo": hoje(),
         "criado_em": "2026-09-13T15:22:00-03:00", "cupons_alertados": {}, **extra}
    _grava(dados, f"state_{modo}.json", d)


def _roda(monkeypatch, capsys, cupons=(), modo="cloud", argv_extra=(), notificar=True):
    import run
    from monitor import sources

    class Fake(sources.Fonte):
        nome = "fake"

        def coletar(self):
            return [], list(cupons)

    monkeypatch.setattr(sources, "por_modo", lambda m: [Fake()])
    monkeypatch.setattr(run, "carrega_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run.py", "--mode", modo, *(("--no-notify",) if notificar else ()), *argv_extra])
    assert run.main() == 0
    return capsys.readouterr().out


def _cupom_da_rodada(codigo="RODADA15", titulo="Cupom Mercado Livre - 15% OFF acima de R$500 limitado à R$100"):
    return Cupom("fake", "Mercado Livre", codigo, titulo, "https://exemplo/c", codigo, publicado=agora_iso())


def _ultima_lista(dados, modo="cloud"):
    return json.loads((dados / f"state_{modo}.json").read_text(encoding="utf-8")).get("ultima_lista_cupons")


def test_run_manda_a_lista_uma_vez_por_dia_fora_do_limite_de_alertas(dados, monkeypatch, capsys):
    _state_inicial(dados)
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", 0)        # já passou da hora
    monkeypatch.setattr(config, "MAX_ALERTAS_POR_EXECUCAO", 0)  # o limite dos alertas não corta a lista
    # o outro modo também entra
    _grava(dados, "latest_pc.json", {"atualizado": agora_iso(), "cupons": [
        _cupom(f"eletro{_ddmm(0)}", "Cupom Mercado Livre - 15% OFF acima de R$500 limitado à R$100 Som Vídeo Eletro")]})
    out = _roda(monkeypatch, capsys, [_cupom_da_rodada()])
    assert "[lista de cupons]\n🎟️ <b>Cupons ativos</b>" in out
    assert "<code>RODADA15</code> — 15% OFF · mín. R$ 500 · até R$ 100" in out
    assert f"<code>eletro{_ddmm(0)}</code>" in out
    assert _ultima_lista(dados) == hoje()
    # a segunda rodada do dia não manda de novo
    out = _roda(monkeypatch, capsys, [_cupom_da_rodada()])
    assert "[lista de cupons]" not in out


def test_run_nao_manda_a_lista_no_pc_nem_desligada(dados, monkeypatch, capsys):
    _state_inicial(dados, "pc")
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", 0)
    out = _roda(monkeypatch, capsys, [_cupom_da_rodada()], modo="pc")
    assert "[lista de cupons]" not in out and _ultima_lista(dados, "pc") is None
    _state_inicial(dados)
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", -1)
    out = _roda(monkeypatch, capsys, [_cupom_da_rodada()])
    assert "[lista de cupons]" not in out


@pytest.mark.parametrize("flag", ["--resumo", "--cupons"])
def test_run_forca_a_lista_com_resumo_ou_cupons(dados, monkeypatch, capsys, flag):
    _state_inicial(dados, "pc", ultima_lista_cupons=hoje())   # já mandou hoje e está no pc: só sai forçada
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", -1)
    out = _roda(monkeypatch, capsys, [_cupom_da_rodada()], modo="pc", argv_extra=(flag,))
    assert "[lista de cupons]" in out and "<code>RODADA15</code>" in out


def test_run_sem_cupom_ativo_manda_o_aviso(dados, monkeypatch, capsys):
    _state_inicial(dados)
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    out = _roda(monkeypatch, capsys, [], argv_extra=("--cupons",))
    assert "Nenhum cupom ativo encontrado hoje." in out


def test_run_falha_no_telegram_tenta_de_novo_na_proxima_rodada(dados, monkeypatch, capsys):
    from monitor import notificar

    _state_inicial(dados)
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", 0)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123456:teste")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "1")
    enviadas: list[tuple[str, bool]] = []
    resposta = {"ok": False}
    monkeypatch.setattr(notificar, "enviar", lambda m, silencioso=False: enviadas.append((m, silencioso))
                        or resposta["ok"])
    _roda(monkeypatch, capsys, [_cupom_da_rodada()], notificar=False)
    assert any(m.startswith("🎟️ <b>Cupons ativos</b>") for m, _s in enviadas)
    assert _ultima_lista(dados) is None, "não chegou: a próxima rodada manda de novo"
    resposta["ok"] = True
    enviadas.clear()
    _roda(monkeypatch, capsys, [_cupom_da_rodada()], notificar=False)
    lista = [(m, s) for m, s in enviadas if m.startswith("🎟️ <b>Cupons ativos</b>")]
    assert lista and lista[0][1] is False, "a primeira parte da lista toca"
    assert _ultima_lista(dados) == hoje()


# =====================================================================================================================
# correções da verificação (08/11/2026)
# =====================================================================================================================
# ---- valor: "até X" de vitrine, "100%" do produto, teto depois de outra palavra, frete e parcelamento --------------
@pytest.mark.parametrize("titulo, regra, esperado", [
    # o "até 60%" do título é a vitrine; a regra diz o valor do cupom (SLIME10 na Nuuvem)
    ("Marcas em alta com até 60% de desconto", "produtos Nuuvem 10% DE DESCONTO NOS PRODUTOS SELECIONADOS, APROVEITE!",
     "10% OFF · itens selecionados"),
    # sem valor certo em lugar nenhum: mostra que é o máximo (QUERO45 na Netshoes, 6DO6 na Americanas)
    ("Até 60% OFF em produtos Alpha Co com desconto na Netshoes",
     "produtos Netshoes PARA PRODUTOS ALPHA CO SELECIONADOS, EM COMPRAS ACIMA DE R$0,01. APLIQUE O CUPOM E GANHE ATÉ 60% OFF",
     "até 60% OFF · alpha co · itens selecionados"),
    ("Garanta até R$100 de desconto na Americanas com este cupom",
     "produtos Americanas CONFIRA O REGULAMENTO DA PROMOÇÃO NO SITE", "até R$ 100 OFF"),
    ("Cupom de desconto Shopee oferece até R$160 OFF em suas compras", "produtos Shopee", "até R$ 160 OFF"),
    # o valor certo vem antes do "até" de vitrine no mesmo título
    ("Ofertas de Data Dupla com até R$100 OFF no cupom Americanas",
     "produtos Americanas DESCONTO DE R$20 OFF EM COMPRAS ACIMA DE R$200", "R$ 20 OFF · mín. R$ 200"),
    # "100%" do nome do produto não é desconto
    ("Whey Protein 100% Pure 900g com R$ 30 OFF", "", "R$ 30 OFF · whey protein 100% pure 900g"),
    ("Camiseta 100% algodão com 10% OFF", "", "10% OFF · camiseta 100% algodão"),
    ("Tudo com 100% OFF no frete", "", "100% OFF"),
    # teto escrito depois de outra palavra; frete grátis com limite
    ("15% OFF no Pix até R$ 200", "", "15% OFF · até R$ 200"),
    ("Compras com cupom Americanas e frete grátis garantido",
     "produtos Americanas FRETE GRÁTIS ATÉ R$15 EM PEDIDOS ACIMA DE R$100", "frete grátis · mín. R$ 100 · até R$ 15"),
    ("10% OFF em compras de até R$ 1000", "", "10% OFF · compras até R$ 1.000"),
    # frete e parcelamento não são escopo
    ("Cupom R$ 15 OFF no frete", "", "R$ 15 OFF no frete"),
    ("R$ 20 OFF acima de R$ 99 + frete grátis", "", "R$ 20 OFF · mín. R$ 99"),
    ("Cupom 12% OFF em até 10x sem juros", "", "12% OFF"),
    ("Cupom de R$ 30 para compras acima de R$ 199", "", "R$ 30 OFF · mín. R$ 199"),
    ("R$ 30 para compras acima de R$ 199", "", "R$ 30 OFF · mín. R$ 199"),
])
def test_valor_vitrine_produto_teto_e_frete(titulo, regra, esperado):
    assert lc.texto_do_valor(lc.valor_do_cupom(titulo, regra), titulo) == esperado


def test_valor_ate_de_vitrine_pesa_menos_e_e_restrito():
    certo = lc.valor_do_cupom("60% OFF em tudo")
    vitrine = lc.valor_do_cupom("Até 60% OFF em tudo")
    assert vitrine.ate and not certo.ate
    assert vitrine.peso == certo.peso / 2
    assert vitrine.restrito and not certo.restrito


# ---- escopo: o produto antes do desconto e a regra do Promobit -----------------------------------------------------
@pytest.mark.parametrize("titulo, regra, esperado", [
    ("Adquira o Meta Quest 3 512GB com R$500 de desconto",
     "produtos KaBuM! GANHE R$500 OFF NO ÓCULOS DE REALIDADE VIRTUAL META QUEST 3 512GB BRANCO. FAÇA LOGIN",
     "R$ 500 OFF · meta quest 3 512gb"),
    ("Smartphone Galaxy A17 256GB com R$300 de desconto",
     "produtos KaBuM! SMARTPHONE SAMSUNG GALAXY A17 256GB COM R$300 OFF", "R$ 300 OFF · smartphone galaxy a17 256gb"),
    ("Split Midea 18.000 BTUs com R$300 de desconto", "", "R$ 300 OFF · split midea 18.000 btus"),
    ("Faça um upgrade com o Intel Core i5-12600K e 15% OFF", "", "15% OFF · intel core i5-12600k"),
    ("Turbine seu setup com o processador AMD Ryzen 7 5700 e 15% de desconto", "",
     "15% OFF · processador amd ryzen 7 5700"),
    ("Phantom Blade Zero Deluxe com 10% OFF no cupom Hype Games", "", "10% OFF · phantom blade zero deluxe"),
    ("Galaxy S24+ com 10% OFF", "", "10% OFF · galaxy s24+"),
    # nome longo: corta com "…"
    ("Aspirador de água e pó Philco PAS34 1400W com 20% OFF", "", "20% OFF · aspirador de água e pó philco pas34…"),
    # frase de campanha antes do desconto não é produto
    ("Os melhores itens do site com R$ 200 OFF aplicando cupom KaBuM!", "produtos KaBuM!", "R$ 200 OFF"),
    ("A chance de economizar R$ 120 em compras na KaBuM!", "produtos KaBuM!", "R$ 120 OFF"),
    ("Compre com código promocional Kabum e economize 10%", "produtos KaBuM!", "10% OFF"),
    ("O momento chegou: Aplique cupom Fast Shop e ganhe 10% OFF", "produtos Fast Shop", "10% OFF"),
    # o título não diz onde vale; a regra do Promobit diz o produto (depois ou antes do desconto)
    ("A Netshoes oferece R$100 OFF para os seus pedidos", "produtos Netshoes R$100 OFF ASICS DYNABLAST 6",
     "R$ 100 OFF · asics dynablast 6"),
    ("Economia de R$200 com o cupom de desconto Netshoes",
     "produtos Netshoes TÊNIS MIZUNO WAVE PROPHECY COM R$200 OFF NO CUPOM", "R$ 200 OFF · tênis mizuno wave prophecy"),
    ("Aplique o cupom KaBum! e receba 20% OFF em suas compras",
     "produtos KaBuM! CUPOM EXCLUSIVO PARA NOTEBOOK LENOVO. VÁLIDO PARA O PRODUTO NOTEBOOK LENOVO IDEAPAD SLIM 3 COM 20% "
     "DE DESCONTO", "20% OFF · notebook lenovo ideapad slim 3"),
    # preço na regra ("LEVE 2 POR R$6,99 CADA + 20%") não é produto
    ("Americanas com 20% OFF em suas compras", "produtos Americanas LEVE 2 POR R$6,99 CADA + 20% DE DESCONTO COM CUPOM",
     "20% OFF"),
    # a regra do Pelando é comentário de usuário: não vira escopo
    ("Wella Professionals Oil Reflections: Kit por R$123,11 com cupom",
     "R$ 100 OFF no KIT Wella Professionals Oil Reflections", "R$ 100 OFF"),
    # "participantes da campanha": o que vem antes fica; vira seleção
    ("10% de Desconto em Notebooks e Monitores participantes da campanha", "produtos KaBuM!",
     "10% OFF · notebooks e monitores · itens selecionados"),
    ("20% OFF em produtos participantes da campanha", "produtos KaBuM!", "20% OFF · itens selecionados"),
    # nome de loja com duas palavras sai inteiro; o "shop" do "Pet Shop" fica
    ("Cupom Mercado Livre oferece R$ 20 em R$ 149 em Pet Shop", "", "R$ 20 OFF · mín. R$ 149 · pet shop"),
    ("Cupom Shopee - R$25 OFF acima de R$129 Todas as Lojas", "", "R$ 25 OFF · mín. R$ 129 · todo site"),
    ("Cupom Mercado Livre 10% OFF acima de R$ 149 (Limitado a R$ 100 OFF) em itens selecionados",
     "Cupom Mercado Libre 10% OFF acima de R$ 79 (Limitado a R$ 100 OFF) em itens selecionados",
     "10% OFF · mín. R$ 149 · até R$ 100 · itens selecionados"),
])
def test_escopo_produto_antes_do_desconto_e_na_regra(titulo, regra, esperado):
    assert lc.texto_do_valor(lc.valor_do_cupom(titulo, regra), titulo) == esperado


def test_cupons_de_produtos_diferentes_nao_juntam_na_mesma_linha():
    vence = (agora() + timedelta(days=4)).isoformat(timespec="seconds")
    regs = [_cupom("ARNOVO10", "Split Midea 18.000 BTUs com R$300 de desconto", loja="KaBuM!", fonte="promobit",
                   validade=vence),
            _cupom("MAGA300", "Smartphone Galaxy A17 256GB com R$300 de desconto", loja="KaBuM!", fonte="promobit",
                   validade=vence),
            _cupom("PHANTOMPS", "Phantom Blade Zero Deluxe com 10% OFF no cupom Hype Games", loja="Hype",
                   fonte="promobit", validade=vence),
            _cupom("ZELDAOOT", "Zelda Ocarina of Time com 10% OFF usando o cupom Hype Games", loja="Hype",
                   fonte="promobit", validade=vence)]
    m = lc.mensagens_cupons_ativos(regs, expirados=set())[0]
    assert " ou " not in m
    assert "• <code>VR500</code>" not in m and "• <code>MAGA300</code> — R$ 300 OFF · smartphone galaxy a17 256gb" in m
    assert "• <code>ZELDAOOT</code> — 10% OFF · zelda ocarina of time" in m


def test_ordem_na_loja_anuncio_depois_gerais_depois_restritos():
    regs = [_cupom("VR500", "Adquira o Meta Quest 3 512GB com R$500 de desconto", loja="KaBuM!", fonte="promobit"),
            _cupom("LISTA30", "30% OFF em itens selecionados", loja="KaBuM!", fonte="promobit"),
            _cupom("GERAL10", "10% OFF", loja="KaBuM!", fonte="promobit"),
            _cupom("SITE5", "R$ 5 OFF em todo o site", loja="KaBuM!", fonte="promobit"),
            _cupom("ANUNCIO", "R$ 20 OFF", loja="KaBuM!", fonte="kabum", publicado="", especifico=True,
                   modelo="PS5_DIGITAL")]
    ativos = lc.cupons_ativos(regs, expirados=set())
    assert [c["codigo"] for c in ativos["KaBuM!"]] == ["ANUNCIO", "GERAL10", "SITE5", "VR500", "LISTA30"]


def test_maximo_de_linhas_por_loja_conta_os_codigos_escondidos(monkeypatch):
    monkeypatch.setattr(config, "CUPONS_ATIVOS_MAX_POR_LOJA", 1)
    regs = [_cupom(c, "Cupom Aliexpress R$ 580 OFF acima de R$ 3.700", loja="AliExpress") for c in ("A1X", "B2X")]
    regs += [_cupom("C3X", "Cupom Aliexpress R$ 50 OFF acima de R$ 290", loja="AliExpress"),
             _cupom("D4X", "Cupom Aliexpress R$ 16 OFF acima de R$ 80", loja="AliExpress")]
    m = lc.mensagens_cupons_ativos(regs, expirados=set())[0]
    assert "🛒 <b>ALIEXPRESS</b> (4)" in m
    assert "• <code>A1X</code> ou <code>B2X</code> — R$ 580 OFF · mín. R$ 3.700" in m
    assert "<i>… e mais 2 códigos de lista, categoria ou menor desconto</i>" in m
    monkeypatch.setattr(config, "CUPONS_ATIVOS_MAX_POR_LOJA", 3)
    m = lc.mensagens_cupons_ativos(regs, expirados=set())[0]
    assert "… e mais" not in m


def test_padrao_de_linhas_por_loja_e_10_e_janela_do_pelando_14():
    """Os padrões (sem a variável no ambiente), lidos do código para não recarregar o config no meio da suíte."""
    fonte = (RAIZ / "monitor" / "config.py").read_text(encoding="utf-8")
    assert '_env("CUPONS_ATIVOS_MAX_POR_LOJA", "10")' in fonte
    assert '_env("CUPONS_ATIVOS_DIAS_PELANDO", "14")' in fonte
    yml = (RAIZ / ".github" / "workflows" / "monitor.yml").read_text(encoding="utf-8")
    assert "CUPONS_ATIVOS_DIAS_PELANDO: ${{ vars.CUPONS_ATIVOS_DIAS_PELANDO }}" in yml


# ---- "ativo": janela do Pelando, validade-padrão, "fim do mês", datas que não são data --------------------------------
def test_pelando_vale_ate_14_dias_e_conta_o_dia_inteiro(monkeypatch):
    titulo = "Cupom Amazon - 20% OFF em Cozinha"
    assert lc.motivo_inativo(_cupom("COZINHA20", titulo, loja="Amazon", publicado=_iso(days=10))) == ""
    # "há 14 dias" é 14,0 dias antes da leitura: ainda vale umas horas depois
    assert lc.motivo_inativo(_cupom("COZ14", titulo, loja="Amazon", publicado=_iso(days=14, hours=3))) == ""
    assert lc.motivo_inativo(_cupom("COZ16", titulo, loja="Amazon", publicado=_iso(days=16))).startswith("publicado há")
    # o Promobit sem validade continua com os 3 dias
    assert lc.motivo_inativo(_cupom("PB4", titulo, loja="Amazon", fonte="promobit", publicado=_iso(days=4))) != ""
    monkeypatch.setattr(config, "CUPONS_ATIVOS_DIAS_PELANDO", 5.0)
    assert lc.motivo_inativo(_cupom("COZINHA20", titulo, loja="Amazon", publicado=_iso(days=10))) != ""
    # o código datado e o testador valem também no Pelando
    assert lc.motivo_inativo(_cupom(f"TODOSITE{_ddmm(2)}", "R$ 10 OFF", publicado=_iso(days=2))).startswith("código de")
    assert lc.motivo_inativo(_cupom("ACABOU", titulo, publicado=_iso(days=1)), {"Mercado Livre|ACABOU"}) != ""


def test_validade_padrao_de_anuncio_antigo_nao_conta():
    # JBL25: publicado há mais de um ano, "válido" por mais dois
    jbl = _cupom("JBL25", "25% de Desconto em produtos JBL", loja="KaBuM!", fonte="promobit",
                 publicado=_iso(days=415), validade=(agora() + timedelta(days=320)).isoformat(timespec="seconds"))
    assert lc.motivo_inativo(jbl).startswith("publicado há")
    # 31/12 em anúncio de meses atrás: data-padrão
    fim_do_ano = f"{agora().year}-12-31T23:59:59-03:00"
    velho = _cupom("NUU10", "10% OFF", loja="Nuuvem", fonte="promobit", publicado=_iso(days=100), validade=fim_do_ano)
    novo = _cupom("NUU11", "10% OFF", loja="Nuuvem", fonte="promobit", publicado=_iso(days=10), validade=fim_do_ano)
    assert lc.motivo_inativo(velho).startswith("publicado há")
    assert lc.motivo_inativo(novo) == "", "anúncio novo com validade em 31/12: vale"
    # validade perto da publicação, mesmo em anúncio antigo: vale
    perto = _cupom("OBA20", "Economize R$20", loja="Americanas", fonte="promobit", publicado=_iso(days=136),
                   validade=(agora() + timedelta(days=5)).isoformat(timespec="seconds"))
    if (agora() + timedelta(days=5)).strftime("%d/%m") != "31/12":
        assert lc.motivo_inativo(perto) == ""
    assert lc.validade_padrao(lc._data(jbl["validade"]), jbl["publicado"])
    assert not lc.validade_padrao(None, jbl["publicado"]) and not lc.validade_padrao(lc._data(fim_do_ano), None)


def test_validade_ate_o_fim_do_mes_e_parcelas_nao_sao_data():
    reg = {"titulo": "25% de Desconto em produtos JBL. Oferta válida até o fim do mês",
           "publicado": "2025-09-19T10:00:09-03:00"}
    assert lc.validade_no_texto(reg).date().isoformat() == "2025-09-30"
    dez = {"titulo": "Válido até o final do mês", "publicado": "2026-12-05T10:00:00-03:00"}
    assert lc.validade_no_texto(dez).date().isoformat() == "2026-12-31"
    assert lc.validade_no_texto({"titulo": "parcele em até 10/12 vezes", "publicado": agora_iso()}) is None
    assert lc.validade_no_texto({"titulo": "em até 10/12x sem juros", "publicado": agora_iso()}) is None
    assert lc.validade_no_texto({"titulo": "válido até 10/12", "publicado": agora_iso()}) is not None


def test_codigo_com_4_digitos_sem_publicacao_fora_do_ml_nao_e_datado():
    anuncio = {"codigo": "MAGALU0911", "loja": "Magazine Luiza", "especifico": True, "titulo": "10% OFF"}
    assert lc.data_no_codigo("MAGALU0911", "Magazine Luiza") is None
    assert lc.motivo_inativo(anuncio, set()) == ""
    # no Mercado Livre continua datado em qualquer lugar do código
    assert lc.data_no_codigo("SITE0911TODO", "Mercado Livre") == (9, 11)


# ---- duplicados com valores diferentes, vencimento -----------------------------------------------------------------
def test_anuncios_igualmente_completos_com_valores_diferentes_mostram_o_outro():
    a = _cupom("AFFNOV22", "Cupom R$620 off em R$4200 aliexpress", loja="AliExpress", publicado=_iso(days=5))
    b = _cupom("AFFNOV22", "Cupom Aliexpress R$ 670 acima de R$ 4200", loja="AliExpress", publicado=_iso(days=5))
    # o título genérico do Promobit (menos completo) não conta como divergência
    c = _cupom("AFFNOV22", "Os melhores itens do site com R$ 1.014 OFF aplicando cupom", loja="AliExpress",
               fonte="promobit", publicado=_iso(days=5))
    m = lc.mensagens_cupons_ativos([a, b, c], expirados=set())[0]
    assert "<code>AFFNOV22</code> — R$ 620 OFF · mín. R$ 4.200 · outro anúncio diz R$ 670 OFF" in m
    m = lc.mensagens_cupons_ativos([a, c], expirados=set())[0]
    assert "<code>AFFNOV22</code> — R$ 620 OFF · mín. R$ 4.200" in m and "outro anúncio" not in m


def test_vence_hoje_e_amanha():
    fim = agora().replace(hour=23, minute=59, second=59, microsecond=0)
    hoje_ = _cupom("HOJE10", "10% OFF", loja="KaBuM!", fonte="promobit", validade=fim.isoformat())
    amanha = _cupom("AMANHA10", "10% OFF", loja="KaBuM!", fonte="promobit",
                    validade=(fim + timedelta(days=1)).isoformat())
    longe = _cupom("LONGE10", "10% OFF", loja="KaBuM!", fonte="promobit",
                   validade=(fim + timedelta(days=5)).isoformat())
    m = lc.mensagens_cupons_ativos([hoje_, amanha, longe], expirados=set())[0]
    assert "<code>HOJE10</code> — 10% OFF · vence hoje" in m
    assert "<code>AMANHA10</code> — 10% OFF · vence amanhã" in m
    assert f"<code>LONGE10</code> — 10% OFF · vence {fim + timedelta(days=5):%d/%m}" in m


# ---- divisão: linha longa e primeira parte sem cupom ---------------------------------------------------------------
def test_muitos_codigos_com_o_mesmo_valor_nao_estouram_a_mensagem():
    regs = [_cupom(f"COD{i:025d}", "R$ 10 OFF acima de R$ 50", loja="Shopee") for i in range(120)]
    msgs = lc.mensagens_cupons_ativos(regs, expirados=set())
    assert all(len(m) <= lc.LIMITE_MENSAGEM for m in msgs)
    for m in msgs:
        for ln in m.split("\n"):
            assert ln.count("<code>") <= lc.MAX_CODIGOS_POR_LINHA
    assert "<code>" in msgs[0], "a primeira parte não sai só com o cabeçalho"
    tudo = "\n".join(msgs)
    assert all(tudo.count(f"<code>{r['codigo']}</code>") == 1 for r in regs)


# ---- última leitura por fonte e loja --------------------------------------------------------------------------------
def test_ultima_leitura_por_loja_nao_some_quando_uma_pagina_falha(dados):
    est = Estado("cloud")
    est.dados["cupons"] = {
        # a página da KaBuM! falhou na última leitura do Promobit: a leitura anterior dela vale
        "promobit:1": dict(_cupom("KAB10", "10% OFF", loja="KaBuM!", fonte="promobit"), ultima_vez=_iso(hours=2)),
        "promobit:2": dict(_cupom("NET10", "10% OFF", loja="Netshoes", fonte="promobit"), ultima_vez=_iso(minutes=5)),
        "promobit:3": dict(_cupom("NETVELHO", "5% OFF", loja="Netshoes", fonte="promobit"), ultima_vez=_iso(hours=2)),
    }
    assert sorted(r["codigo"] for r in est.cupons_da_ultima_leitura()) == ["KAB10", "NET10"]


def test_run_completa_por_loja_a_leitura_que_falhou(dados, monkeypatch, capsys):
    cupons = {
        "promobit:1": dict(_cupom("KABANTES", "10% OFF", loja="KaBuM!", fonte="promobit"), ultima_vez=_iso(hours=1)),
        "promobit:2": dict(_cupom("NETANTES", "10% OFF", loja="Netshoes", fonte="promobit"), ultima_vez=_iso(hours=1)),
    }
    _state_inicial(dados, cupons=cupons)
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    agora_netshoes = Cupom("promobit", "Netshoes", "NETAGORA", "15% OFF", "https://exemplo/c", "n1", publicado=agora_iso())
    out = _roda(monkeypatch, capsys, [agora_netshoes], argv_extra=("--cupons",))
    assert "<code>NETAGORA</code>" in out and "<code>KABANTES</code>" in out
    assert "<code>NETANTES</code>" not in out, "a Netshoes foi lida agora: a leitura anterior dela não conta"


# ---- run.py: lista que chegou só em parte ---------------------------------------------------------------------------
def _envio_por_partes(monkeypatch, falhas: dict[str, int]):
    """notificar.enviar falso: a mensagem que começa com uma chave de `falhas` falha tantas vezes."""
    from monitor import lista_cupons, notificar

    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123456:teste")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(lista_cupons, "mensagens_cupons_ativos", lambda regs: ["PARTE1", "PARTE2"])
    enviadas: list[str] = []

    def enviar(m, silencioso=False):
        if m.startswith("PARTE"):
            enviadas.append(m)
        if falhas.get(m, 0) > 0:
            falhas[m] -= 1
            return False
        return True

    monkeypatch.setattr(notificar, "enviar", enviar)
    return enviadas


def test_run_parte_que_falhou_ganha_nova_tentativa_na_hora(dados, monkeypatch, capsys):
    _state_inicial(dados)
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", 0)
    enviadas = _envio_por_partes(monkeypatch, {"PARTE2": 1})
    _roda(monkeypatch, capsys, [_cupom_da_rodada()], notificar=False)
    assert enviadas == ["PARTE1", "PARTE2", "PARTE2"]
    assert _ultima_lista(dados) == hoje()


def test_run_lista_que_chegou_em_parte_repete_uma_vez_so(dados, monkeypatch, capsys):
    _state_inicial(dados)
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    monkeypatch.setattr(config, "HORA_LISTA_CUPONS", 0)
    enviadas = _envio_por_partes(monkeypatch, {"PARTE2": 99})
    _roda(monkeypatch, capsys, [_cupom_da_rodada()], notificar=False)
    assert _ultima_lista(dados) is None, "chegou só a 1ª parte: a próxima rodada manda de novo"
    enviadas.clear()
    _roda(monkeypatch, capsys, [_cupom_da_rodada()], notificar=False)
    assert enviadas[:2] == ["PARTE1", "PARTE2"]
    assert _ultima_lista(dados) == hoje(), "na 2ª vez em parte, desiste até amanhã"
    enviadas.clear()
    _roda(monkeypatch, capsys, [_cupom_da_rodada()], notificar=False)
    assert enviadas == []


# ---- canal novo: links encurtados do Mercado Livre e da Amazon ------------------------------------------------------
def _post_canal(link: str, titulo: str = "Gta Vi - Playstation 5 Versão Standard Nacional Br") -> str:
    return (
        '<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="linguicapromocoes/101">'
        '<div class="tgme_widget_message_text js-message_text" dir="auto">'
        f'<i class="emoji"><b>⏰</b></i> {titulo}<br/><br/>'
        '<i class="emoji"><b>💹</b></i> R$ 378,40 com cupom:<br/><code>40ALLSITE</code><br/><br/>'
        f'<i class="emoji"><b>✨</b></i> Link do produto:<br/><a href="{link}">{link}</a><br/><br/>'
        'anúncio<br/>Entre no meu grupo de ofertas<br/><a href="https://linktr.ee/exemplo">https://linktr.ee/exemplo</a>'
        '</div><div class="tgme_widget_message_footer"><a class="tgme_widget_message_date">'
        f'<time datetime="{agora_iso()}"></time></a></div></div></div>')


@pytest.mark.parametrize("link, loja", [("https://meli.la/1AbCdEf", "Mercado Livre"),
                                        ("https://amzn.to/3XyZabc", "Amazon")])
def test_canal_linguica_link_encurtado_diz_a_loja(link, loja):
    from monitor.sources import telegram_public

    ofs = telegram_public.parse_canal(_post_canal(link), "linguicapromocoes")
    assert ofs, "a postagem do GTA 6 vira oferta"
    assert {o.loja for o in ofs} == {loja}
    assert all(o.cupom == "40ALLSITE" for o in ofs)
    assert telegram_public.loja_no_texto("Oferta", ["https://meli.la/xyz"]) == "Mercado Livre"
