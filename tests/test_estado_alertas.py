"""Estado, histórico e alertas: casos reais de 17-18/09/2026 (F2, F3, F4, F5, F9) e a convenção do agregador (Zoom).

Cada teste usa um diretório de dados temporário; nada aqui lê ou escreve docs/data.
"""

import csv
import json
from datetime import timedelta

import pytest

from monitor import config
from monitor.estado import Estado
from monitor.models import Cupom, Oferta
from monitor.regras import (
    cupom_compativel, cupons_aplicaveis, gerar_alertas, mensagem_bootstrap, resumo_diario, sanear,
)
from monitor.util import agora, agora_iso

URL_CB = "https://www.casasbahia.com.br/x/p/55069456"


@pytest.fixture(autouse=True)
def dados_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    return tmp_path


def grava_state(pasta, modo, minimo=None, ofertas=None, cupons=None):
    """State já existente (não é bootstrap), como o que está no repositório."""
    dados = {"ofertas": ofertas or {}, "cupons": cupons or {}, "minimo": minimo, "saude": {},
             "ultimo_resumo": None, "criado_em": "2026-09-13T15:22:00-03:00"}
    (pasta / f"state_{modo}.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def minimo(preco, loja="Amazon"):
    return {"preco": preco, "loja": loja, "quando": "2026-09-14T21:08:06-03:00", "url": "u", "titulo": "TCL 55C6K"}


def reg_oferta(fonte, oid, loja, ultimo):
    return {"fonte": fonte, "id": oid, "tipo": "loja", "loja": loja, "ativo": True, "ultimo_preco": ultimo,
            "menor_preco": ultimo, "preco_alertado": None, "primeira_vez": "2026-09-13T15:22:00-03:00"}


def rodada(modo, ofertas, cupons=()):
    """Mesma sequência do run.py: sanear -> alertas -> registra/mínimo -> histórico -> salva."""
    from monitor.estado import lojas_diretas

    est = Estado(modo)
    ofertas, _av = sanear(ofertas)
    msgs, alertados = gerar_alertas(est, ofertas, list(cupons))
    diretas = lojas_diretas(ofertas)
    for o in ofertas:
        est.registra_oferta(o, alertados.get(o.chave))
        est.atualiza_minimo(o, diretas)
    est.anexa_historico([o for o in ofertas if o.tipo == "loja" and o.ativo and o.melhor_preco])
    est.salva()
    return est, msgs


def ofertas_pc_1709(amazon=4034.5, cb=2189.3):
    """Preços reais do modo pc em 17/09 21:37: a CB trouxe o preço de uma Hisense do carrossel."""
    out = [
        Oferta("amazon", "loja", "Amazon", "TCL 55C6K", "u", "B0F7JZMVKF", preco=amazon),
        Oferta("mercadolivre", "loja", "Mercado Livre", "TCL 55C6K", "u", "MLB48808732", preco=4169.0),
        Oferta("aliexpress", "loja", "AliExpress", "TCL 55C6K", "u", "1005009459962683", preco=4199.0),
    ]
    if cb:
        out.append(Oferta("casasbahia", "loja", "Casas Bahia", "TCL 55C6K", URL_CB, "55069456", preco=cb,
                          parcelado="6x R$ 795,32 sem juros"))
    return out


def cab(msgs):
    return [m.split("\n")[0] for m in msgs]


# ---------------- F2: oferta inativa/descartada não vira "menor já visto" ----------------

def test_atualiza_minimo_ignora_oferta_inativa(dados_tmp):
    """Amazon 'Temporariamente indisponível': o parser devolve preço com ativo=False."""
    grava_state(dados_tmp, "pc", minimo=minimo(3199.0))
    est = Estado("pc")
    esgotada = Oferta("amazon", "loja", "Amazon", "TCL 55C6K", "u", "B0F7JZMVKF", preco=2500.0, ativo=False)
    assert est.atualiza_minimo(esgotada) is False
    assert est.minimo()["preco"] == 3199.0


def test_descarte_do_sanear_nao_polui_minimo_nem_esconde_o_trofeu(dados_tmp):
    grava_state(dados_tmp, "pc", minimo=minimo(3199.0))
    est, _ = rodada("pc", ofertas_pc_1709())
    assert est.minimo()["preco"] == 3199.0, "o preço da Hisense (CB 2.189,30) virou 'menor já visto'"
    cb = est.oferta_anterior("casasbahia:55069456")
    assert cb["ativo"] is False
    assert cb.get("ultimo_preco") is None and cb.get("menor_preco") is None

    # rodada seguinte: a Amazon cai de verdade para 3.100, abaixo do mínimo real de 3.199
    est, msgs = rodada("pc", ofertas_pc_1709(amazon=3100.0, cb=None))
    assert any("🏆 MENOR PREÇO já visto" in c and "Amazon" in c for c in cab(msgs)), cab(msgs)
    assert est.minimo()["preco"] == 3100.0


def test_registra_oferta_inativa_mantem_ultimo_preco_ativo(dados_tmp):
    grava_state(dados_tmp, "pc", ofertas={"casasbahia:55069456": reg_oferta("casasbahia", "55069456", "Casas Bahia", 3599.09)})
    est = Estado("pc")
    est.registra_oferta(Oferta("casasbahia", "loja", "Casas Bahia", "t", URL_CB, "55069456", preco=2189.3, ativo=False))
    reg = est.oferta_anterior("casasbahia:55069456")
    assert reg["ultimo_preco"] == 3599.09 and reg["menor_preco"] == 3599.09 and reg["ativo"] is False


def test_mensagem_bootstrap_so_lista_ofertas_ativas():
    ofs = [Oferta("casasbahia", "loja", "Casas Bahia", "t", URL_CB, "1", preco=2189.3, ativo=False),
           Oferta("amazon", "loja", "Amazon", "t", "u", "2", preco=3279.0)]
    msg = mensagem_bootstrap(ofs, [], "pc")
    assert "Amazon" in msg and "Casas Bahia" not in msg and "2.189,30" not in msg


# ---------------- F4: histórico só com preços ativos ----------------

def test_historico_nao_grava_oferta_descartada(dados_tmp):
    est = Estado("pc")
    est.anexa_historico([
        Oferta("amazon", "loja", "Amazon", "t", "u", "1", preco=4034.5),
        Oferta("casasbahia", "loja", "Casas Bahia", "t", URL_CB, "2", preco=2189.3, ativo=False),
        Oferta("aliexpress", "loja", "AliExpress", "t", "u", "3"),  # sem preço
    ])
    linhas = list(csv.DictReader((dados_tmp / "historico_pc.csv").open(encoding="utf-8")))
    assert [(r["loja"], r["preco"]) for r in linhas] == [("Amazon", "4034.5")]


def test_rodada_com_descarte_nao_vai_para_o_grafico(dados_tmp):
    rodada("pc", ofertas_pc_1709())
    linhas = list(csv.DictReader((dados_tmp / "historico_pc.csv").open(encoding="utf-8")))
    assert "Casas Bahia" not in {r["loja"] for r in linhas}
    assert {r["loja"] for r in linhas} == {"Amazon", "Mercado Livre", "AliExpress"}


# ---------------- F5: "menor já visto" considera os dois modos ----------------

def _estado_pc_com_amazon(dados_tmp):
    grava_state(dados_tmp, "pc", minimo=minimo(3199.0),
                ofertas={"amazon:B0F7JZMVKF": reg_oferta("amazon", "B0F7JZMVKF", "Amazon", 3279.0)})
    return Estado("pc")


def test_trofeu_compara_com_minimo_do_outro_modo(dados_tmp):
    grava_state(dados_tmp, "cloud", minimo=minimo(2991.6, "Magazine Luiza"))
    est = _estado_pc_com_amazon(dados_tmp)
    msgs, _ = gerar_alertas(est, [Oferta("amazon", "loja", "Amazon", "TCL 55C6K", "u", "B0F7JZMVKF", preco=3150.0)], [])
    assert cab(msgs) and "🔻 Queda de preço" in cab(msgs)[0]
    assert not any("🏆" in c for c in cab(msgs)), "3.150 não é menor que os 2.991,60 do modo cloud"

    msgs, _ = gerar_alertas(est, [Oferta("amazon", "loja", "Amazon", "TCL 55C6K", "u", "B0F7JZMVKF", preco=2950.0)], [])
    assert any("🏆 MENOR PREÇO já visto" in c for c in cab(msgs))


def test_trofeu_sem_arquivo_do_outro_modo_usa_o_proprio(dados_tmp):
    est = _estado_pc_com_amazon(dados_tmp)
    msgs, _ = gerar_alertas(est, [Oferta("amazon", "loja", "Amazon", "TCL 55C6K", "u", "B0F7JZMVKF", preco=3150.0)], [])
    assert any("🏆" in c for c in cab(msgs))


def test_trofeu_tolera_arquivo_do_outro_modo_quebrado(dados_tmp):
    (dados_tmp / "state_cloud.json").write_text("{quebrado", encoding="utf-8")
    (dados_tmp / "latest_cloud.json").write_text(json.dumps({"minimo": minimo(2991.6, "Magazine Luiza")}), encoding="utf-8")
    est = _estado_pc_com_amazon(dados_tmp)
    msgs, _ = gerar_alertas(est, [Oferta("amazon", "loja", "Amazon", "TCL 55C6K", "u", "B0F7JZMVKF", preco=3150.0)], [])
    assert not any("🏆" in c for c in cab(msgs)), "deveria cair no latest_cloud.json"


def test_resumo_diario_mostra_o_menor_dos_dois_modos(dados_tmp):
    grava_state(dados_tmp, "pc", minimo=minimo(3199.0))
    grava_state(dados_tmp, "cloud", minimo=minimo(2991.6, "Magazine Luiza"))
    txt = resumo_diario(Estado("cloud"), [], [])
    assert "Menor já visto: R$ 2.991,60 (Magazine Luiza" in txt
    txt = resumo_diario(Estado("pc"), [], [])
    assert "Menor já visto: R$ 2.991,60 (Magazine Luiza" in txt


# ---------------- F9: cupom repetido com outro id não alerta de novo ----------------

def _reg_cupom(fonte, cid, loja, codigo, ultima_vez):
    return {"fonte": fonte, "id": cid, "loja": loja, "codigo": codigo, "titulo": f"R$ 250,00 OFF com cupom: {codigo}",
            "url": "u", "regra": "", "validade": None, "publicado": None, "especifico": fonte == "magalu",
            "chave": f"{fonte}:{cid}", "primeira_vez": "2026-09-13T15:23:17-03:00", "ultima_vez": ultima_vez}


def _lu250(cid):
    return Cupom(fonte="magalu", loja="Magazine Luiza", codigo="LU250", titulo="R$ 250,00 OFF com cupom: LU250",
                 url="https://x", id=cid, regra="R$ 250,00 OFF com cupom: LU250",
                 validade="2026-09-20T23:59:00-03:00", especifico=True)


def test_cupom_da_magalu_com_nova_data_no_id_nao_realerta(dados_tmp):
    grava_state(dados_tmp, "cloud", cupons={
        "magalu:LU250-2026-09-18": _reg_cupom("magalu", "LU250-2026-09-18", "Magazine Luiza", "LU250", agora_iso())})
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_lu250("LU250-2026-09-20")])
    assert msgs == []


def test_mesmo_codigo_em_outro_site_de_promocao_nao_realerta(dados_tmp):
    grava_state(dados_tmp, "cloud", cupons={
        "pelando:abc": _reg_cupom("pelando", "abc", "mercado-livre", "PROMOMELI", agora_iso())})
    novo = Cupom(fonte="promobit", loja="Mercado Livre", codigo="promomeli", url="u", id="69433",
                 titulo="Cupom de desconto Mercado Livre oferece 10% OFF em suas compras")
    msgs, _ = gerar_alertas(Estado("cloud"), [], [novo])
    assert msgs == []


def test_cupom_novo_ou_que_voltou_depois_de_muito_tempo_alerta(dados_tmp):
    antigo = (agora() - timedelta(days=60)).isoformat(timespec="seconds")
    grava_state(dados_tmp, "cloud", cupons={
        "magalu:LU250-2026-07-01": _reg_cupom("magalu", "LU250-2026-07-01", "Magazine Luiza", "LU250", antigo)})
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_lu250("LU250-2026-09-20")])
    assert len(msgs) == 1 and "LU250" in msgs[0]
    outro = Cupom(fonte="magalu", loja="Magazine Luiza", codigo="LU300", titulo="R$ 300,00 OFF com cupom: LU300",
                  url="u", id="LU300-2026-09-20", especifico=True)
    msgs, _ = gerar_alertas(Estado("cloud"), [], [outro])
    assert len(msgs) == 1 and "LU300" in msgs[0]


# ---------------- F3: cupons do site todo que servem para a TV ----------------

def _c(loja, codigo, titulo, regra=""):
    return Cupom(fonte="promobit", loja=loja, codigo=codigo, titulo=titulo, url="", id=codigo + titulo[:10], regra=regra)


SERVEM = [  # textos reais do state_cloud de 18/09 (preço da TV na loja: Magalu Pix 3.561,55; ML Pix 3.491,03)
    (_c("Magazine Luiza", "INFLU300", "Os melhores itens do site com R$ 300 OFF aplicando cupom Magalu",
        "produtos Magazine Luiza Economize até R$ 300 ao usar o código promocional no carrinho de compras (acima de R$ 3000)."), 3561.55),
    (_c("Magazine Luiza", "RODEIO220", "Cupom de desconto Magazine Luiza oferece R$ 220 OFF em suas compras",
        "produtos Magazine Luiza Economize até R$ 220 ao usar o código promocional em compras acima de R$ 2.000 no carrinho de compras."), 3561.55),
    (_c("Magazine Luiza", "INFLU25", "Use cupom Magalu e tenha desconto de 25% OFF até R$ 800",
        "produtos Magazine Luiza Economize até 25% OFF até R$ 800 ao usar o código promocional no carrinho de compras."), 3561.55),
    (_c("Magazine Luiza", "ESQUENTA320", "Magalu: Ganhe R$320 OFF em compras acima de R$3.000",
        "R$320 partir de R$3.000 (válido para itens elegíveis )"), 3561.55),
    (_c("Magazine Luiza", "ESQUENTA320", "Os melhores itens do site com R$320 OFF aplicando cupom Magazine Luiza",
        "produtos Magazine Luiza Economize até R$320 ao usar o código promocional no carrinho de compras (a partir de R$3.000)."), 3561.55),
    (_c("Magazine Luiza", "X", "R$ 320 OFF em compras acima de R$ 3.000"), 3561.55),
    (_c("Magazine Luiza", "X", "Cupom Magalu com desconto máximo de R$500 em suas compras"), 3561.55),
    (_c("Mercado Livre", "DESCONTOBOM", "FESTA DE PREÇOS: 25% OFF no Mercado Livre (acima de R$1) com cupom",
        "produtos Mercado Livre Desconto de até 25% em compra a partir de R$1, excluído o valor do frete, "
        "com desconto máximo de R$500 válido para itens elegíveis."), 3491.03),
    (_c("Mercado Livre", "PEGANOMELI", "CAÇA AO DESCONTO: 22% OFF no Mercado Livre (acima de R$1) com cupom",
        "produtos Mercado Livre Desconto de até 22% em compra a partir de R$1, com desconto máximo de R$500."), 3491.03),
    (_c("Mercado Livre", "ACHEIOFF", "CAÇA AO DESCONTO: 25% OFF em geral no Mercado Livre (acima de R$1) com cupom"), 3491.03),
    (_c("Mercado Livre", "ALLSITE", "Cupom Mercado Livre - R$50 off em Compras Acima de R$499 em Todo Site",
        "Cupom Diz Todo Site, confiram"), 3491.03),
    (_c("AliExpress", "NOVA1", "COMPRE MAIS: R$ 240 OFF em compras acima de R$ 1.600 na AliExpress (com cupom)",
        "produtos Aliexpress"), 3749.0),
    (_c("Amazon", "NATORCIDA", "A chance de economizar 30% OFF em compras na Amazon", "produtos Amazon"), 3279.0),
]

NAO_SERVEM = [
    (_c("Magazine Luiza", "DESCONTA15", "O momento chegou: Aplique cupom Magazine Luiza e ganhe 15% OFF",
        "produtos Magazine Luiza Aplique o código promocional no carrinho de compras em compras até R$600."), 3561.55),
    (_c("Magazine Luiza", "X", "Cupom Magalu 10% OFF", "Válido para compra máxima de R$ 500."), 3561.55),
    (_c("Magazine Luiza", "X", "Magalu: R$ 400 OFF em compras acima de R$ 4.200"), 3561.55),
    (_c("Magazine Luiza", "X", "Cupom Magalu 10% OFF em Mercado"), 3561.55),
    (_c("Mercado Livre", "AGORAVAI", "Cupom Mercado Livre - 25% OFF em Compras Acima de R$1 limitado à R$500 em Selecionados",
        "Em itens Selecionados"), 3491.03),
    (_c("Mercado Livre", "20LIMPEZAOFF", "Cupom Mercado Livre - 20% off em Compras Acima de R$99 limitado à R$30",
        "Em itens Selecionados limpeza e higiene"), 3491.03),
    (_c("Mercado Livre", "ISDIN15", "Economize 15% em seus pedidos aplicando cupom Mercado Livre",
        "produtos Mercado Livre Economize até 15% ao usar o código promocional no carrinho de compras (mínimo R$5)."), 3491.03),
    (_c("Mercado Livre", "ISDIN15", "Cupom Mercado Livre - 15% off em Compras Acima de R$5 limitado à R$150 em Itens Isdin"), 3491.03),
    (_c("Mercado Livre", "FULL1209", "Cupom Mercado Livre oferece 10% OFF, máximo R$ 20, em R$ 89 em Entregas FULL",
        "pedido mínimo R$ 89"), 3491.03),
    (_c("Magazine Luiza", "RELAX5", "Cupom de desconto Magalu oferece 5% OFF em compras Relax Medic"), 3561.55),
    (_c("Fast Shop", "3CORACOES", "Saboreie mais: 5% OFF em produtos 3 Corações na Fastshop"), 3296.81),
]


@pytest.mark.parametrize("cupom,preco", SERVEM, ids=[c.codigo + ":" + c.titulo[:30] for c, _ in SERVEM])
def test_cupom_do_site_todo_serve_para_a_tv(cupom, preco):
    ok, motivo = cupom_compativel(cupom, preco)
    assert ok, motivo


@pytest.mark.parametrize("cupom,preco", NAO_SERVEM, ids=[c.codigo + ":" + c.titulo[:30] for c, _ in NAO_SERVEM])
def test_cupom_que_nao_serve_continua_fora(cupom, preco):
    assert cupom_compativel(cupom, preco)[0] is False


def test_cupons_aplicaveis_mostra_os_cupons_da_magalu_no_painel():
    magalu = Oferta("magalu", "loja", "Magazine Luiza", "TCL 55C6K", "u", "240162800-magazineluiza",
                    preco=3749.0, preco_pix=3561.55)
    cs = [c for c, _ in SERVEM[:4]]
    assert [c.codigo for c in cupons_aplicaveis([magalu], cs)] == ["INFLU300", "RODEIO220", "INFLU25", "ESQUENTA320"]


# ---------------- convenção: Zoom/Buscapé é agregador ----------------

def _zoom(loja, preco, oid):
    return Oferta("zoom", "loja", loja, "TCL 55C6K", "https://www.zoom.com.br/x", oid, preco=preco,
                  extra={"agregador": True})


def test_agregador_nao_alerta_nem_define_minimo_quando_a_loja_tem_fonte_direta(dados_tmp):
    grava_state(dados_tmp, "cloud", minimo=minimo(3159.0, "KaBuM!"), ofertas={
        "zoom:1561988278": reg_oferta("zoom", "1561988278", "Magazine Luiza", 3937.15),
        "magalu:240162800-magazineluiza": reg_oferta("magalu", "240162800-magazineluiza", "Magazine Luiza", 3561.55)})
    ofs = [_zoom("Magazine Luiza", 2800.0, "1561988278"),
           Oferta("magalu", "loja", "Magazine Luiza", "TCL 55C6K", "u", "240162800-magazineluiza",
                  preco=3749.0, preco_pix=3561.55)]
    est, msgs = rodada("cloud", ofs)
    assert msgs == [], cab(msgs)
    assert est.minimo()["preco"] == 3159.0


def test_agregador_de_loja_sem_fonte_direta_ainda_conta(dados_tmp):
    grava_state(dados_tmp, "cloud", minimo=minimo(3159.0, "KaBuM!"), ofertas={
        "zoom:1489104908": reg_oferta("zoom", "1489104908", "Amazon", 3279.0)})
    est, msgs = rodada("cloud", [_zoom("Amazon", 2950.0, "1489104908"),
                                 Oferta("kabum", "loja", "KaBuM!", "TCL 55C6K", "u", "911482", preco=3159.0)])
    assert any("🏆 MENOR PREÇO já visto" in c and "Amazon" in c for c in cab(msgs)), cab(msgs)
    assert est.minimo()["preco"] == 2950.0


def test_atualiza_minimo_sem_saber_das_fontes_diretas_ignora_agregador(dados_tmp):
    grava_state(dados_tmp, "cloud", minimo=minimo(3159.0, "KaBuM!"))
    est = Estado("cloud")
    assert est.atualiza_minimo(_zoom("Amazon", 2000.0, "z")) is False
    assert est.minimo()["preco"] == 3159.0
