"""Estado, histórico e alertas: casos reais de 13-18/09/2026 (F2-F5, F9, REG-1, REG-2) e o agregador (Zoom).

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
    _compativel_regra_antiga, _desconto, cupom_compativel, cupons_aplicaveis, gerar_alertas, mensagem_bootstrap,
    resumo_diario, sanear,
)
from monitor.util import agora

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
    """Mesma sequência do run.py: sanear -> alertas -> registra/mínimo -> cupons -> histórico -> salva."""
    est = Estado(modo)
    ofertas, _av = sanear(ofertas)
    est.migra_chaves_de_oferta(ofertas)
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


# ---------------- F9: cupom repetido com outro id (e as regressões REG-1 e REG-2 da rodada 1) ----------------
# Só é repetição o código (loja + código) já ALERTADO com o mesmo desconto. Textos reais do state_cloud de 13-18/09;
# as datas ficam relativas a agora para o prazo de 30 dias não vencer com o tempo.

def _ha(dias):
    return (agora() - timedelta(days=dias)).isoformat(timespec="seconds")


def _reg(fonte, cid, loja, codigo, titulo, regra="", especifico=False, primeira=5.0, ultima=None):
    """Registro de cupom como o run.py grava em state['cupons'] (primeira/ultima: dias atrás)."""
    return {"fonte": fonte, "id": cid, "loja": loja, "codigo": codigo, "titulo": titulo, "url": "u", "regra": regra,
            "validade": None, "publicado": None, "especifico": especifico, "chave": f"{fonte}:{cid}",
            "primeira_vez": _ha(primeira), "ultima_vez": _ha(primeira if ultima is None else ultima)}


def _cupom(reg, **kw):
    campos = {k: reg[k] for k in ("fonte", "loja", "codigo", "titulo", "url", "id", "regra", "especifico")}
    campos.update(kw)
    return Cupom(**campos)


def _por_chave(*regs):
    return {r["chave"]: r for r in regs}


# pelando 13/09 15:23 (rodada de partida): recusado pelas duas regras ("em Selecionados")
PEL_MELIACHAPROMO = _reg("pelando", "01627720-85c6-4e77-ab35-5e49b007e8e2", "Mercado Livre", "MELIACHAPROMO",
                         "Cupom Mercado Livre - 10% OFF Acima de R$99 limitado à R$300 em Selecionados",
                         "Em Itens Selecionados", primeira=5.1, ultima=3.9)
PROMOBIT_69374 = _reg("promobit", "69374", "Mercado Livre", "MELIACHAPROMO",
                      "A chance de economizar 10% em compras na Mercado Livre",
                      "produtos Mercado Livre Economize até 10% ao usar o código promocional no carrinho de compras "
                      "(compra mínima R$99).", primeira=5.0)
PROMOBIT_69469 = _reg("promobit", "69469", "Mercado Livre", "MELIACHAPROMO",
                      "Cupom de desconto Mercado Livre oferece 10,00% OFF em suas compras",
                      "produtos Mercado Livre Desconto de até 10% em compra a partir de R$99, excluído o valor do "
                      "frete, com desconto máximo de R$300 válido para itens elegíveis.", primeira=5.0)
PEL_PROMOMELI = _reg("pelando", "f07c1dba-68a1-4030-93bb-954eb65a5ae0", "Mercado Livre", "PROMOMELI",
                     "Cupom Mercado Livre - 10% acima de R$149 limitado à R$200 em Tecnologia", "Em itens Selecionados",
                     primeira=5.1)
PROMOBIT_69433 = _reg("promobit", "69433", "Mercado Livre", "PROMOMELI",
                      "A chance de economizar 10% em compras no Mercado Livre", "produtos Mercado Livre -", primeira=5.0)
# ESQUENTA320: a regra antiga recusava os dois ("Economize até R$320", "OFF em compras acima de"): nunca alertou
PEL_ESQUENTA320 = _reg("pelando", "a44fdd07-3363-4c9e-a5ff-088bffddb12a", "Magazine Luiza", "ESQUENTA320",
                       "Magalu: Ganhe R$320 OFF em compras acima de R$3.000",
                       "R$320 partir de R$3.000 (válido para itens elegíveis )", primeira=5.1, ultima=3.9)
PROMOBIT_69223 = _reg("promobit", "69223", "Magazine Luiza", "ESQUENTA320",
                      "Os melhores itens do site com R$320 OFF aplicando cupom Magazine Luiza",
                      "produtos Magazine Luiza Economize até R$320 ao usar o código promocional no carrinho de compras "
                      "(a partir de R$3.000).", primeira=5.0, ultima=0.3)
LU250 = [_reg("magalu", f"LU250-2026-09-{d}", "Magazine Luiza", "LU250", "R$ 250,00 OFF com cupom: LU250",
              "R$ 250,00 OFF com cupom: LU250", especifico=True, primeira=p, ultima=u)
         for d, p, u in (("14", 5.1, 5.0), ("18", 3.9, 2.1), ("16", 2.0, 2.0))]


def _esquenta_do_produto(cid="ESQUENTA320-2026-09-25"):
    return Cupom(fonte="magalu", loja="Magazine Luiza", codigo="ESQUENTA320", titulo="R$ 320,00 OFF com cupom: ESQUENTA320",
                 url="https://www.magazineluiza.com.br/x/p/240162800/", id=cid,
                 regra="R$ 320,00 OFF com cupom: ESQUENTA320", validade="2026-09-25T23:59:00-03:00", especifico=True)


def _codigos(msgs):
    import re
    return [c for m in msgs for c in re.findall(r"<code>([^<]+)</code>", m)]


def test_reg1_codigo_so_visto_como_incompativel_ainda_alerta(dados_tmp):
    """REG-1: com só o registro do Pelando ('em Selecionados', recusado) no estado, o Promobit 69374 (compatível)
    tem de alertar. A rodada 1 silenciava porque o código tinha sido VISTO nos últimos 30 dias."""
    assert cupom_compativel(_cupom(PEL_MELIACHAPROMO), 3491.03)[0] is False
    grava_state(dados_tmp, "cloud", cupons=_por_chave(PEL_MELIACHAPROMO))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_cupom(PROMOBIT_69374)])
    assert len(msgs) == 1 and "🎟️" in msgs[0] and _codigos(msgs) == ["MELIACHAPROMO"], msgs


def test_reg1_depois_de_alertado_o_mesmo_codigo_so_repete_se_o_desconto_mudar(dados_tmp):
    grava_state(dados_tmp, "cloud", cupons=_por_chave(PEL_MELIACHAPROMO))
    _est, msgs = rodada("cloud", [], [_cupom(PROMOBIT_69374)])
    assert _codigos(msgs) == ["MELIACHAPROMO"]
    salvo = json.loads((dados_tmp / "state_cloud.json").read_text(encoding="utf-8"))
    alertas = salvo["cupons_alertados"]["Mercado Livre|MELIACHAPROMO"]
    assert [(a["chave"], a["origem"]) for a in alertas] == [("promobit:69374", "alerta")]
    # outra rodada: o mesmo código com outro id e o mesmo desconto (10%, agora com o teto de R$300) não repete
    _est, msgs = rodada("cloud", [], [_cupom(PROMOBIT_69469)])
    assert msgs == []
    # desconto mudou (15%): é novidade
    _est, msgs = rodada("cloud", [], [_cupom(PROMOBIT_69374, id="69999",
                                             titulo="A chance de economizar 15% em compras na Mercado Livre")])
    assert _codigos(msgs) == ["MELIACHAPROMO"]


def test_reg2_cupom_da_pagina_do_produto_alerta_mesmo_com_o_codigo_visto_no_site(dados_tmp):
    """REG-2: registros reais do ESQUENTA320 (Pelando e Promobit) no estado + o cupom na página da TV na Magalu."""
    grava_state(dados_tmp, "cloud", cupons=_por_chave(PEL_ESQUENTA320, PROMOBIT_69223))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_esquenta_do_produto()])
    assert len(msgs) == 1 and _codigos(msgs) == ["ESQUENTA320"], msgs
    assert "⭐" in msgs[0] and "cupom do produto" in msgs[0]


def test_cupom_do_produto_e_novidade_mesmo_com_o_codigo_ja_alertado_como_cupom_do_site(dados_tmp):
    grava_state(dados_tmp, "cloud")
    _est, msgs = rodada("cloud", [], [_cupom(PROMOBIT_69223)])  # alertado como cupom do site
    assert _codigos(msgs) == ["ESQUENTA320"] and "⭐" not in msgs[0]
    _est, msgs = rodada("cloud", [], [_esquenta_do_produto()])
    assert _codigos(msgs) == ["ESQUENTA320"] and "⭐" in msgs[0], "vale para esta TV: é informação nova"
    # agora sim é repetição: a tag do produto com outra data no id, e o cupom do site num novo post
    _est, msgs = rodada("cloud", [], [_esquenta_do_produto("ESQUENTA320-2026-09-30"),
                                      _cupom(PROMOBIT_69223, id="69998")])
    assert msgs == []


def test_codigo_visto_mas_recusado_pela_regra_da_epoca_alerta_quando_volta(dados_tmp):
    """O ESQUENTA320 foi visto no Pelando e no Promobit, mas a regra antiga recusava os dois: nunca virou alerta."""
    grava_state(dados_tmp, "cloud", cupons=_por_chave(PEL_ESQUENTA320, PROMOBIT_69223))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_cupom(PROMOBIT_69223, id="69998")])
    assert _codigos(msgs) == ["ESQUENTA320"]


def test_estado_antigo_cupom_da_magalu_com_nova_data_no_id_nao_realerta(dados_tmp):
    """F9 (rodada 1, mantido): LU250 com três chaves no state_cloud; a quarta data não é novidade."""
    grava_state(dados_tmp, "cloud", cupons=_por_chave(*LU250))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_cupom(LU250[2], id="LU250-2026-09-20")])
    assert msgs == []


def test_estado_antigo_mesmo_codigo_em_outro_post_nao_realerta(dados_tmp):
    """F9 (rodada 1, mantido): o PROMOMELI já tinha sido alertado pelo Promobit 69433."""
    grava_state(dados_tmp, "cloud", cupons=_por_chave(PEL_PROMOMELI, PROMOBIT_69433))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_cupom(PROMOBIT_69433, id="69999")])
    assert msgs == []


def test_estado_antigo_desconto_diferente_alerta(dados_tmp):
    grava_state(dados_tmp, "cloud", cupons=_por_chave(*LU250))
    novo = _cupom(LU250[2], id="LU250-2026-09-25", titulo="R$ 300,00 OFF com cupom: LU250",
                  regra="R$ 300,00 OFF com cupom: LU250")
    msgs, _ = gerar_alertas(Estado("cloud"), [], [novo])
    assert _codigos(msgs) == ["LU250"]


def test_sequencia_real_de_13_09(dados_tmp):
    """13/09: partida às 15:23 com os posts do Pelando; às 15:29 o Promobit traz MELIACHAPROMO (2 posts) e
    PROMOMELI. O MELIACHAPROMO alerta uma vez (era 'em Selecionados' no Pelando); o PROMOMELI já tinha sido
    anunciado na partida com os mesmos 10%. Depois, um repost do MELIACHAPROMO não repete."""
    grava_state(dados_tmp, "cloud", cupons=_por_chave(PEL_MELIACHAPROMO, PEL_PROMOMELI))
    _est, msgs = rodada("cloud", [], [_cupom(PROMOBIT_69374), _cupom(PROMOBIT_69469), _cupom(PROMOBIT_69433)])
    assert _codigos(msgs) == ["MELIACHAPROMO"]
    _est, msgs = rodada("cloud", [], [_cupom(PROMOBIT_69374, id="69504")])
    assert msgs == []


def test_partida_anuncia_os_cupons_aplicaveis(dados_tmp):
    """Na partida nada vira alerta de cupom, mas os aplicáveis ficam como anunciados: o mesmo código com outro id
    não é novidade depois. O que a partida recusou continua podendo alertar."""
    amazon = Oferta("amazon", "loja", "Amazon", "TCL 55C6K", "u", "B0F7JZMVKF", preco=3279.0)
    est, msgs = rodada("cloud", [amazon], [_cupom(PEL_PROMOMELI), _cupom(PEL_MELIACHAPROMO)])
    assert est.bootstrap and msgs == []
    assert [a["origem"] for a in est.dados["cupons_alertados"]["Mercado Livre|PROMOMELI"]] == ["partida"]
    assert "Mercado Livre|MELIACHAPROMO" not in est.dados["cupons_alertados"]
    _est, msgs = rodada("cloud", [amazon], [_cupom(PROMOBIT_69433), _cupom(PROMOBIT_69374)])
    assert _codigos(msgs) == ["MELIACHAPROMO"]


def test_estado_antigo_e_migrado_uma_vez(dados_tmp):
    grava_state(dados_tmp, "cloud", cupons=_por_chave(PEL_ESQUENTA320, PROMOBIT_69223, PEL_PROMOMELI,
                                                      PROMOBIT_69433, *LU250))
    est = Estado("cloud")
    gerar_alertas(est, [], [])
    alertados = est.dados["cupons_alertados"]
    assert "Magazine Luiza|ESQUENTA320" not in alertados, "a regra antiga recusava: nunca alertou"
    assert {a["chave"] for a in alertados["Mercado Livre|PROMOMELI"]} == {PEL_PROMOMELI["chave"], "promobit:69433"}
    assert len(alertados["Magazine Luiza|LU250"]) == 3
    assert all(a["origem"] == "legado" for v in alertados.values() for a in v)
    est.salva()
    # depois da migração, cupom só visto (registrado sem alerta) não conta como alertado
    est = Estado("cloud")
    est.registra_cupom(_cupom(PROMOBIT_69374))
    est.salva()
    est = Estado("cloud")
    assert not est.alertas_de_cupom("Mercado Livre|MELIACHAPROMO")
    msgs, _ = gerar_alertas(est, [], [_cupom(PROMOBIT_69469)])
    assert _codigos(msgs) == ["MELIACHAPROMO"]


def test_cupom_alertado_ha_muito_tempo_alerta_de_novo(dados_tmp):
    velho = _reg("magalu", "LU250-2026-07-01", "Magazine Luiza", "LU250", "R$ 250,00 OFF com cupom: LU250",
                 "R$ 250,00 OFF com cupom: LU250", especifico=True, primeira=60, ultima=60)
    grava_state(dados_tmp, "cloud", cupons=_por_chave(velho))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_cupom(velho, id="LU250-2026-09-20")])
    assert _codigos(msgs) == ["LU250"]
    outro = Cupom(fonte="magalu", loja="Magazine Luiza", codigo="LU300", titulo="R$ 300,00 OFF com cupom: LU300",
                  url="u", id="LU300-2026-09-20", especifico=True)
    msgs, _ = gerar_alertas(Estado("cloud"), [], [outro])
    assert _codigos(msgs) == ["LU300"]


def test_cupom_alertado_ha_tempo_mas_ainda_no_ar_nao_repete(dados_tmp):
    ainda = _reg("magalu", "LU250-2026-07-01", "Magazine Luiza", "LU250", "R$ 250,00 OFF com cupom: LU250",
                 "R$ 250,00 OFF com cupom: LU250", especifico=True, primeira=45, ultima=0.1)
    grava_state(dados_tmp, "cloud", cupons=_por_chave(ainda))
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_cupom(ainda, id="LU250-2026-09-20")])
    assert msgs == []


def test_sem_desconto_legivel_compara_o_titulo(dados_tmp):
    grava_state(dados_tmp, "cloud")
    base = Cupom(fonte="promobit", loja="KaBuM!", codigo="KABUMSITE", titulo="Cupom especial KaBuM! no site todo",
                 url="u", id="1")
    _est, msgs = rodada("cloud", [], [base])
    assert _codigos(msgs) == ["KABUMSITE"]
    _est, msgs = rodada("cloud", [], [Cupom(**{**base.__dict__, "id": "2"})])
    assert msgs == []
    _est, msgs = rodada("cloud", [], [Cupom(**{**base.__dict__, "id": "3",
                                                "titulo": "Cupom KaBuM! vale no site todo, inclusive TVs"})])
    assert _codigos(msgs) == ["KABUMSITE"]


def test_so_os_cupons_que_foram_na_mensagem_ficam_como_alertados(dados_tmp):
    grava_state(dados_tmp, "cloud")
    cs = [Cupom(fonte="promobit", loja="Magazine Luiza", codigo=f"TV{i:02d}", titulo=f"R$ {100 + i} OFF em suas compras",
                url="u", id=str(i)) for i in range(13)]
    est, msgs = rodada("cloud", [], cs)
    assert len(_codigos(msgs)) == 12 and "e mais 1" in msgs[0]
    assert sorted(est.dados["cupons_alertados"]) == sorted(f"Magazine Luiza|TV{i:02d}" for i in range(12))


def test_mensagem_de_cupons_que_nao_sai_nao_conta_como_alertada(dados_tmp):
    """run.py corta as mensagens no limite da rodada: se a de cupons fica de fora, nada nela foi alertado."""
    import run

    grava_state(dados_tmp, "cloud", cupons=_por_chave(*LU250))
    est = Estado("cloud")
    msgs, _ = gerar_alertas(est, [], [_cupom(PROMOBIT_69374)])
    assert est.alertas_de_cupom("Mercado Livre|MELIACHAPROMO")
    assert run.limita_alertas(["⚠️ aviso"] + msgs, est, 15) == ["⚠️ aviso"] + msgs  # dentro do limite: nada muda
    assert est.alertas_de_cupom("Mercado Livre|MELIACHAPROMO")
    saida = run.limita_alertas(["⚠️ aviso"] * 15 + msgs, est, 15)
    assert len(saida) == 16 and "e mais 1 alertas" in saida[-1]
    assert not est.alertas_de_cupom("Mercado Livre|MELIACHAPROMO")
    assert len(est.alertas_de_cupom("Magazine Luiza|LU250")) == 3, "o que veio do estado antigo continua"
    est.salva()
    msgs, _ = gerar_alertas(Estado("cloud"), [], [_cupom(PROMOBIT_69469)])  # o mesmo código num novo post
    assert _codigos(msgs) == ["MELIACHAPROMO"]


@pytest.mark.parametrize("titulo,regra,esperado", [
    ("Cupom de desconto Mercado Livre oferece 10,00% OFF em suas compras", "", (("%", 10.0), None)),
    ("A chance de economizar 10% em compras na Mercado Livre", "", (("%", 10.0), None)),
    ("R$ 250,00 OFF com cupom: LU250", "", (("R$", 250.0), None)),
    ("Cupom Mercado Livre - 25% OFF em Compras Acima de R$1 limitado à R$500", "", (("%", 25.0), 500.0)),
    ("A chance de economizar R$ 100 em compras na Magazine Luiza", "", (("R$", 100.0), None)),
    ("Magalu: Ganhe R$320 OFF em compras acima de R$3.000", "", (("R$", 320.0), None)),
    ("Use cupom Magalu e tenha desconto de 25% OFF até R$ 800", "", (("%", 25.0), 800.0)),
    ("Cupom Magalu", "Economize até R$ 1.000 ao usar o código", (("R$", 1000.0), None)),
    ("Garanta desconto no site aplicando o cupom KaBuM!", "", (None, None)),
])
def test_desconto_lido_do_titulo_e_da_regra(titulo, regra, esperado):
    assert _desconto(titulo, regra) == esperado


def test_regra_antiga_reproduz_o_que_o_codigo_da_epoca_alertava():
    """Estados antigos não registravam os alertas de cupom: a migração usa a regra da época (recusava os de F3)."""
    for cupom, preco in SERVEM[:5]:  # INFLU300, RODEIO220, INFLU25, ESQUENTA320 x2
        assert _compativel_regra_antiga(cupom, preco) is False, cupom.codigo
    for reg in (PROMOBIT_69374, PROMOBIT_69433, PEL_PROMOMELI, LU250[0]):
        assert _compativel_regra_antiga(_cupom(reg), 3491.03) is True, reg["chave"]
    assert _compativel_regra_antiga(_cupom(PEL_MELIACHAPROMO), 3491.03) is False


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



# ---------------- rodada 4: regras gerais de cupom (variações de cada princípio, não só os exemplos) ----------------
# Cada linha: (loja, título, regra, serve). Preço da TV: o de 18/09 na loja. Ver o comentário no topo de regras.py.
_PRECO = {"Magazine Luiza": 3561.55, "Mercado Livre": 3491.03, "Amazon": 3279.0, "KaBuM!": 3159.0,
          "Casas Bahia": 3599.09}
_MG, _ML, _AMZ, _KB, _CB = "Magazine Luiza", "Mercado Livre", "Amazon", "KaBuM!", "Casas Bahia"
PRINCIPIOS = [
    # (a) exclusão não é o escopo; só a exclusão da própria TV (ou de eletrônicos/TCL) tira a TV
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto Celulares e Games.", True),
    (_MG, "Cupom Magalu R$ 200 OFF em compras acima de R$ 1.500", "Não se aplica a produtos de Mercado e Farmácia", True),
    (_MG, "Cupom Magalu R$ 200 OFF", "Válido em todo o site, menos Supermercado", True),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exclui iPhone, Apple e Samsung Galaxy", True),
    (_ML, "15% OFF em todo o site (limite R$ 150)", "Não cumulativo. Exceto Supermercado, Farmácia e Pet.", True),
    (_AMZ, "Cupom Amazon 10% OFF em Eletrônicos", "Não válido em livros e eBooks Kindle", True),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto TVs", False),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto eletrônicos e TVs", False),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto TVs Samsung e LG", True),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Não válido para TVs de 32 polegadas", True),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Não válido para TVs de 50 a 65 polegadas", False),
    (_AMZ, "Cupom Amazon R$ 100 OFF", "Não válido para primeira compra", True),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto eletrônicos vendidos por terceiros", True),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto TVs acima de R$ 5.000", True),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto acessórios para TV", True),
    # cliente novo "inclusive"/"também" não é cupom só de cliente novo; kit como palavra solta não é o produto
    (_MG, "Cupom Magalu R$ 100 OFF em qualquer compra, inclusive na 1ª compra", "", True),
    (_MG, "Cupom Magalu R$ 100 OFF para clientes antigos e novos clientes", "", True),
    (_MG, "Cupom Magalu R$ 100 OFF para novos clientes", "", False),
    (_MG, "Cupom Magalu R$ 100 OFF acima de R$ 1.000", "Válido para kit e unidades avulsas em compras no site", True),
    (_MG, "Cupom Magalu R$ 50 OFF para você renovar a casa", "", True),
    (_MG, "Kit Smart TV 55 polegadas + Soundbar com R$ 300 OFF", "", True),
    (_MG, "Kit 55C6K + Soundbar com R$ 300 OFF", "", True),
    (_AMZ, "Cupom Amazon R$ 100 OFF em compras acima de R$ 2.000",
     "Válido em compras realizadas até 30/09 em produtos vendidos e entregues pela Amazon", True),
    (_KB, "Cupom KaBuM! R$ 200 OFF em compras acima de R$ 2.500", "Cupom válido em produtos em estoque", True),
    (_MG, "Cupom 10% OFF na categoria Informática e TVs", "", True),
    (_MG, "Cupom 10% OFF", "Categoria: Casa", False),
    (_MG, "Cupom R$ 100 OFF em compras acima de R$ 1.000 na categoria TV e Vídeo", "", True),
    (_MG, "Cupom de 10% para Moda", "", False),
    # (b) todos os alvos; alvo neutro não é categoria; alvo fora do desconto não é o escopo
    (_MG, "Cupom Magalu R$ 300 OFF em TVs e Celulares", "", True),
    (_MG, "10% OFF em Celulares e TVs selecionados", "", True),
    (_MG, "10% OFF em Games e TVs", "", True),
    (_KB, "Cupom KaBuM! 10% OFF em Eletrônicos em oferta", "", True),
    (_KB, "Cupom KaBuM! 10% OFF em TVs na Black Friday", "", True),
    (_MG, "Cupom Magalu R$ 300 OFF para pagamento no boleto", "", True),
    (_MG, "Cupom Magalu R$ 300 OFF em compras no aplicativo", "Válido somente no app", True),
    (_MG, "Cupom Magalu R$ 300 OFF em compras acima de R$ 3.000", "Válido em uma única compra por CPF.", True),
    (_MG, "Economize R$ 300 em uma única compra acima de R$ 3.000", "", True),
    (_MG, "Cupom Magalu R$ 300 OFF em compras acima de R$ 3.000", "Receba em casa com frete grátis", True),
    (_MG, "Cupom Magalu R$ 300 OFF em compras acima de R$ 3.000", "Válido em pedidos feitos até 30/09", True),
    (_MG, "Cupom Magalu R$ 300 OFF em compras acima de R$ 3.000", "Cupom selecionado para você!", True),
    (_ML, "Cupom Mercado Livre 10% OFF em compras realizadas pelo app", "", True),
    (_ML, "Cupom 10% OFF em itens vendidos e entregues pelo Mercado Livre", "", True),
    (_ML, "10% OFF pagando com Mercado Pago", "", True),
    (_ML, "Cupom Mercado Livre 10% OFF em compras acima de R$ 99", "Uso único. Válido em todo o Brasil.", True),
    (_MG, "R$ 100 OFF em Moda", "", False),
    (_MG, "R$ 50 OFF em Acessórios para TV", "", False),
    (_MG, "R$ 50 OFF em Suportes de TV", "", False),
    (_ML, "Cupom Mercado Livre 20% OFF", "Válido na categoria Beleza e Cuidado Pessoal", False),
    (_MG, "10% OFF em Instrumentos Musicais", "", False),
    (_KB, "Casa inteligente: 15% OFF em produtos para sua casa tech!", "produtos KaBuM!", False),
    (_MG, "Cupom Magalu R$ 300 OFF", "Válido para itens selecionados", False),
    (_ML, "Cupom Mercado Livre 10% OFF em Selecionados", "", False),
    # (c) tamanhos
    (_AMZ, "Cupom R$ 250 OFF em Smart TVs 55 a 85 polegadas", "", True),
    (_AMZ, "Cupom R$ 250 OFF em Smart TVs de 43 a 65 polegadas", "", True),
    (_AMZ, "Cupom R$ 250 OFF em Smart TVs a partir de 50 polegadas", "", True),
    (_AMZ, "Cupom R$ 250 OFF em Smart TVs 50 polegadas ou mais", "", True),
    (_AMZ, "Cupom R$ 250 OFF em Smart TVs acima de 50 polegadas", "", True),
    (_AMZ, "Cupom R$ 300 OFF em TVs, inclusive na Smart TV TCL 50 P7L", "", True),
    (_AMZ, "Cupom R$ 250 OFF em Smart TVs até 50 polegadas", "", False),
    (_AMZ, "Cupom R$ 250 OFF na Smart TV TCL 65 C7K", "", False),
    (_AMZ, "Cupom R$ 250 OFF na Smart TV TCL 55C6K", "", True),
    (_AMZ, "Cupom R$ 250 OFF em TVs TCL 50P7K, 55C6K e 65C7K", "", True),
    (_AMZ, "Cupom R$ 250 OFF na Smart TV TCL 65C6K", "", False),
    (_AMZ, "Cupom 10% OFF em TVs TCL 50P7K e 65C7K", "", False),
    (_MG, "R$ 50 OFF em Controle Remoto para Smart TV", "", False),
    (_MG, "R$ 300 OFF na compra da sua Smart TV", "", True),
    (_MG, "Cupom de R$ 300 para TVs", "", True),
    # (d) frete e app
    (_CB, "Cupom Casas Bahia Frete Grátis em compras acima de R$ 99", "", False),
    (_CB, "Cupom Casas Bahia R$ 30 OFF no frete", "", False),
    (_MG, "Cupom Magalu R$ 200 OFF + entrega grátis", "", True),
    (_MG, "Cupom Magalu R$ 200 OFF", "Válido no APP", True),
    (_MG, "Cupom de 10% no app Magalu", "", True),
    # compra mínima depois de "OFF em"
    (_MG, "Cupom Magalu R$ 350 OFF em R$ 3500", "", True),
    (_MG, "Cupom Magalu R$ 350 OFF em R$ 5000", "", False),
    # ---- 2ª passada da rodada 4 ----
    # teto: da COMPRA/do ITEM (como a main) salvo quando o valor é o próprio desconto (F3)
    (_MG, "Cupom Magalu 10% OFF em compras até R$ 2.500", "", False),
    (_MG, "Cupom Magalu R$ 200 OFF", "Válido para compras até R$ 5.000", True),
    (_MG, "Economize até R$ 150 em compras acima de R$ 1.000", "", True),
    (_AMZ, "Ganhe 15% de desconto (até R$ 200) na Amazon", "", True),
    (_KB, "Cupom KaBuM! 15% OFF - máximo de R$ 100", "", True),
    (_MG, "Cupom Magalu R$ 30 OFF em compras até R$ 300", "", False),
    (_CB, "Cupom Casas Bahia 20% OFF, desconto até R$ 50", "", True),
    (_MG, "Até R$ 1.500 OFF em TVs com cupom Magalu", "", True),
    (_AMZ, "Cupom Amazon 10% OFF em produtos até R$ 3.000", "", False),
    # (c) tamanhos com polegada, sem vírgula, com 4K no meio; "12x"/"20%" não são tamanho
    (_AMZ, 'Cupom Amazon R$ 300 OFF em Smart TV 4K 55"', "", True),
    (_AMZ, "Cupom Amazon R$ 300 OFF na Smart TV 50 4K UHD", "", False),
    (_MG, "Cupom Magalu R$ 300 OFF em TVs 4K de 50 a 85 polegadas", "", True),
    (_MG, "Cupom Magalu R$ 300 OFF em Smart TVs de 50 polegadas, 55 polegadas e 65 polegadas", "", True),
    (_MG, "Cupom Magalu 10% OFF Smart TVs 12x sem juros", "", True),
    (_MG, "Cupom Magalu Smart TV com 20% OFF", "", True),
    (_MG, "Cupom Magalu R$ 300 OFF em Smart TVs 50+ polegadas", "", True),
    (_MG, "Cupom Magalu R$ 300 OFF em TVs de 65 e 75 polegadas", "", False),
    (_MG, "Cupom Magalu R$ 300 OFF em TVs", "Não válido para TVs de 32 e 43 polegadas", True),
    # qualificador de venda/pagamento não é categoria; condição do produto e vendedor terceiro são
    (_MG, "Cupom Magalu 10% OFF em compras parceladas", "", True),
    (_AMZ, "Cupom Amazon 10% OFF em produtos Seminovos", "", False),
    (_AMZ, "Cupom Amazon R$ 50 OFF em produtos vendidos por terceiros", "", False),
    # cliente novo
    (_ML, "Cupom Mercado Livre R$ 50 OFF", "Válido para novos e antigos clientes", True),
    (_MG, "Cupom Magalu R$ 300 OFF em compras acima de R$ 3.000", "Não é necessário ser cliente novo", True),
    (_MG, "Cupom Magalu R$ 300 OFF", "Para compras pela primeira vez no app", False),
    (_MG, "Cupom Magalu R$ 300 OFF para membros novos do Clube", "", True),
    # (a) a exclusão acaba na vírgula que abre outra condição; "com exceção de" é exclusão
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto Celulares, Games e Informática", True),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto TVs, em compras acima de R$ 1.000", False),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Válido em compras acima de R$ 1.000, com exceção de iPhone e Apple",
     True),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto Celulares, compra mínima de R$ 5.000", False),
    (_MG, "Cupom Magalu R$ 200 OFF em todo o site", "Exceto Celulares, e TVs acima de R$ 5.000", True),
    (_ML, "Cupom Mercado Livre 20% OFF", "Desconto de 20% com teto de até R$ 100", True),
    (_MG, "Cupom Magalu 10% OFF", "Válido para produtos novos e usados", True),
    (_MG, "Cupom Magalu 10% OFF para compras de até R$ 1.999", "", False),
    (_MG, "Cupom Magalu R$ 300 OFF", "Não é exclusivo para novos clientes", True),
]


@pytest.mark.parametrize("loja,titulo,regra,serve", PRINCIPIOS,
                         ids=[f"{t[:45]}|{r[:25]}" for _l, t, r, _s in PRINCIPIOS])
def test_regras_gerais_de_cupom(loja, titulo, regra, serve):
    ok, motivo = cupom_compativel(_c(loja, "SONDA", titulo, regra), _PRECO[loja])
    assert ok is serve, motivo


# ---------------- ZOOM: agregador x fonte direta em qualquer modo ----------------

def test_agregador_reconhecido_por_fonte_e_url_sem_extra():
    """As linhas do Zoom gravadas hoje não têm extra.agregador (o painel também olha fonte e URL)."""
    from monitor.estado import e_agregador

    assert e_agregador(Oferta("zoom", "loja", "Amazon", "t", "https://www.zoom.com.br/tv/x", "1", preco=1.0))
    assert e_agregador({"fonte": "buscape", "loja": "Amazon"})
    assert e_agregador({"preco": 3082.61, "loja": "Webcontinental", "url": "https://www.zoom.com.br/tv/x"})
    assert not e_agregador(Oferta("amazon", "loja", "Amazon", "t", "https://www.amazon.com.br/dp/B0F7JZMVKF", "2"))


def test_lojas_diretas_de_qualquer_modo_e_idade(dados_tmp):
    """Rodada atual + state deste modo + state/latest do outro modo; agregador nunca conta como direto."""
    grava_state(dados_tmp, "cloud", ofertas={
        "vtex:Web-1": {"fonte": "vtex", "tipo": "loja", "loja": "Webcontinental", "ativo": False},
        "zoom:9": {"fonte": "zoom", "tipo": "loja", "loja": "Ponto", "ativo": True}})
    grava_state(dados_tmp, "pc", ofertas={"casasbahia:1": {"fonte": "casasbahia", "tipo": "loja", "loja": "Casas Bahia"}})
    (dados_tmp / "latest_pc.json").write_text(json.dumps({"ofertas_loja": [
        {"fonte": "amazon", "tipo": "loja", "loja": "Amazon", "ativo": False, "melhor_preco": 3749.0}]}),
        encoding="utf-8")
    est = Estado("cloud")
    rodada_atual = [Oferta("kabum", "loja", "KaBuM!", "t", "u", "911482", preco=4184.88), _zoom("Ponto", 3000.0, "9")]
    assert est.lojas_diretas_conhecidas(rodada_atual) == {"KaBuM!", "Webcontinental", "Casas Bahia", "Amazon"}


def test_resumo_so_troca_a_linha_do_agregador_coberto(dados_tmp):
    """Loja do outro modo sem linha de agregador aqui não entra no resumo; a do agregador coberto vira a direta."""
    grava_state(dados_tmp, "cloud")
    (dados_tmp / "latest_pc.json").write_text(json.dumps({"atualizado": "2026-09-18T17:43:57-03:00", "ofertas_loja": [
        {"fonte": "amazon", "tipo": "loja", "loja": "Amazon", "vendedor": "Magalu.", "ativo": True, "preco": 3749.0,
         "melhor_preco": 3749.0, "url": "https://www.amazon.com.br/dp/B0F7JZMVKF"},
        {"fonte": "casasbahia", "tipo": "loja", "loja": "Casas Bahia", "ativo": True, "melhor_preco": 3599.09}]}),
        encoding="utf-8")
    txt = resumo_diario(Estado("cloud"), [_zoom("Amazon", 3279.0, "1489104908"),
                                          Oferta("kabum", "loja", "KaBuM!", "t", "u", "911482", preco=4184.88)], [])
    lojas = [ln for ln in txt.split("\n") if ln.startswith("• ")]
    assert lojas == ["• Amazon/Magalu.: <b>R$ 3.749,00</b> · visto 18/09 17:43 (PC)", "• KaBuM!: <b>R$ 4.184,88</b>"]


def test_agregador_coberto_por_oferta_direta_inativa_do_outro_modo_some_sem_substituta(dados_tmp):
    grava_state(dados_tmp, "cloud")
    (dados_tmp / "latest_pc.json").write_text(json.dumps({"atualizado": "2026-09-18T17:43:57-03:00", "ofertas_loja": [
        {"fonte": "amazon", "tipo": "loja", "loja": "Amazon", "ativo": False, "melhor_preco": 3749.0}]}),
        encoding="utf-8")
    txt = resumo_diario(Estado("cloud"), [_zoom("Amazon", 3279.0, "1489104908")], [])
    assert "Amazon" not in txt and "nenhum preço de loja coletado" in txt


# ---------------- B5 (19/09): a chave da oferta mudou de formato; o histórico vai junto ----------------

URL_AMZ = "https://www.amazon.com.br/dp/B0F7JZMVKF"
URL_ML = "https://www.mercadolivre.com.br/smart-tv-tcl-55c6k/p/MLB48808732"


def _reg_b5(fonte, oid, loja, url, vendedor, ultimo, menor=None, alertado=None, ativo=True):
    return {"fonte": fonte, "id": oid, "tipo": "loja", "loja": loja, "url": url, "vendedor": vendedor,
            "ativo": ativo, "ultimo_preco": ultimo, "menor_preco": menor if menor is not None else ultimo,
            "preco_alertado": alertado, "primeira_vez": "2026-09-13T15:22:00-03:00",
            "ultima_vez": "2026-09-19T12:59:00-03:00"}


def _estado_de_antes(pasta, modo="pc"):
    """State como está no repositório em 19/09: a chave da Amazon ainda é só o ASIN."""
    grava_state(pasta, modo, minimo=minimo(3199.0), ofertas={
        "amazon:B0F7JZMVKF": _reg_b5("amazon", "B0F7JZMVKF", "Amazon", URL_AMZ, "Magalu.", 3374.10,
                                  menor=3199.0, alertado=3374.10),
        "casasbahia:55069456": _reg_b5("casasbahia", "55069456", "Casas Bahia", URL_CB, "Casas Bahia", 3599.09),
    })


def _amazon_nova(preco):
    o = Oferta("amazon", "loja", "Amazon", "TCL 55C6K", f"{URL_AMZ}?smid=ACUNARZFR75ET",
               "B0F7JZMVKF-ACUNARZFR75ET", preco_pix=preco, vendedor="Magalu.")
    o.extra.update({"anuncio": "B0F7JZMVKF", "asin": "B0F7JZMVKF", "vendedor_id": "ACUNARZFR75ET"})
    return o


def test_chave_nova_herda_o_historico_da_antiga(dados_tmp):
    _estado_de_antes(dados_tmp)
    est, _ = rodada("pc", [_amazon_nova(3374.10)])
    novo = est.dados["ofertas"]["amazon:B0F7JZMVKF-ACUNARZFR75ET"]
    assert (novo["menor_preco"], novo["preco_alertado"]) == (3199.0, 3374.10)
    assert novo["primeira_vez"] == "2026-09-13T15:22:00-03:00"
    velho = est.dados["ofertas"]["amazon:B0F7JZMVKF"]
    assert velho["migrado_para"] == "amazon:B0F7JZMVKF-ACUNARZFR75ET" and velho["ativo"] is False


def test_primeira_rodada_depois_da_juncao_ainda_manda_a_queda(dados_tmp):
    # 3.374,10 -> 3.100,00 é queda de 8%: sem a migração a chave nova não teria com o que comparar
    _estado_de_antes(dados_tmp)
    _est, msgs = rodada("pc", [_amazon_nova(3100.0)])
    assert any("🔻" in m for m in msgs), "a queda de preço continua sendo alertada"


def test_alvo_nao_repete_no_mesmo_preco_depois_da_juncao(dados_tmp):
    # preco_alertado 3.374,10 veio junto: o mesmo preço não gera 🎯 de novo
    grava_state(dados_tmp, "pc", minimo=minimo(3199.0), ofertas={
        "amazon:B0F7JZMVKF": _reg_b5("amazon", "B0F7JZMVKF", "Amazon", URL_AMZ, "Magalu.", 2800.0,
                                  menor=2800.0, alertado=2800.0)})
    _est, msgs = rodada("pc", [_amazon_nova(2800.0)])
    assert not any("🎯" in m for m in msgs), "o alvo já foi avisado neste preço"
    _est2, msgs2 = rodada("pc", [_amazon_nova(2700.0)])
    assert any("🎯" in m for m in msgs2), "preço melhor ainda avisa"


def test_migracao_roda_uma_vez_e_nao_rouba_de_quem_esta_em_uso(dados_tmp):
    _estado_de_antes(dados_tmp)
    est, _ = rodada("pc", [_amazon_nova(3374.10)])
    # a chave antiga continua no estado, marcada; numa 2ª rodada nada mais é migrado
    mapa = Estado("pc").migra_chaves_de_oferta([_amazon_nova(3374.10)])
    assert mapa == {}
    assert est.dados["ofertas"]["casasbahia:55069456"].get("migrado_para") is None


def test_duas_ofertas_novas_do_mesmo_vendedor_e_url_nao_migram(dados_tmp):
    # identidade disputada: migrar daria a UMA delas um "ultimo_preco" que não é dela (🔻 inventado)
    grava_state(dados_tmp, "pc", ofertas={
        "mercadolivre:MLB48808732": _reg_b5("mercadolivre", "MLB48808732", "Mercado Livre", URL_ML, "Magalu", 3491.03)})
    a = Oferta("mercadolivre", "loja", "Mercado Livre", "TCL 55C6K", URL_ML, "MLB1111111111",
               preco_pix=3491.03, vendedor="Magalu")
    b = Oferta("mercadolivre", "loja", "Mercado Livre", "TCL 55C6K", URL_ML, "MLB2222222222",
               preco_pix=3300.0, vendedor="Magalu")
    est = Estado("pc")
    assert est.migra_chaves_de_oferta([a, b]) == {}
    assert est.dados["ofertas"]["mercadolivre:MLB48808732"].get("migrado_para") is None


def test_vendedor_diferente_nao_herda_o_historico(dados_tmp):
    _estado_de_antes(dados_tmp)
    outro = _amazon_nova(3100.0)
    outro.vendedor, outro.id = "Lojas Colombo S/A", "B0F7JZMVKF-A30OZFNW1RCCSM"
    outro.url = f"{URL_AMZ}?smid=A30OZFNW1RCCSM"
    est = Estado("pc")
    assert est.migra_chaves_de_oferta([outro]) == {}
