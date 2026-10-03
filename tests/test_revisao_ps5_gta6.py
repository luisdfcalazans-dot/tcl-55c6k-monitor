"""Correções da revisão do PS5/GTA 6 (03/10/2026).

1. (alta) Carrinho: o leitor de disco avulso da pessoa nunca é lido como console ("Unidade de Disco para Consoles PS5
   Digital Edition", nome oficial da Sony; "Leitor de Disco Ultra HD Blu-ray Console PS5 Slim"). Antes ele virava um
   principal restaurável e saía da sacola em silêncio.
2. (média) Entrega do GTA 6 na pré-venda: o prazo conta a partir de 12/11 (quando as caixas existem). Uma estimativa
   curta da VTEX ("5bd"), uma data lida no carrinho ou no cartão da Amazon antes de 12/11 não pode virar "chega a tempo".
3. (média) Gift card da PlayStation só paga compra na PS Store: chave/código de outra loja (Eneba, revendedor do ML) não
   ganha o custo efetivo com gift card.
4. (média) "+ Controle Sem Fio DualSense" (singular, sem número, sem "extra") é o controle que já vem no console: não
   vira kit (+R$ 300 na meta).
5. (baixas) Classificador (mousepad, Grade A, 30 Anos, conta compartilhada, garantia estendida, brinde); cupom do leitor
   no console; "Games e Consoles" no GTA; limite de alertas sem prioridade e posts repetidos em vários canais; cupom do
   anúncio do Magalu com código de um cupom e desconto de outro, vencido ou com compra mínima.

Nada acessa a rede nem abre navegador.
"""

from __future__ import annotations

import json
import sys
from datetime import date

import pytest

from monitor import config, confianca, produtos
from monitor.carrinho import CarrinhoOcupado, Magalu, MercadoLivre, modelo_da_linha, produto_do_titulo
from monitor.estado import Estado
from monitor.models import Cupom, Oferta
from monitor.regras import cupom_compativel, gerar_alertas
from monitor.sources import entrega, magalu, vtex
from monitor.util import agora_iso
from test_carrinho import MAGALU_1P
from test_testador_anuncios import FIXO, amb, tc  # noqa: F401 - ambiente do testador (dados, relógio, sessão)
from test_testador_produtos import (  # noqa: F401
    IDS_ML, K_GTA, ML_PS5, O_GTA, URL_PS5, CarrinhoProdutos, SacolaProdutos, _alvo, _latest, _sacola,
)


class _Hoje(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 3)


@pytest.fixture
def hoje_03_10(monkeypatch):
    monkeypatch.setattr(entrega, "hoje", lambda: date(2026, 10, 3))
    monkeypatch.setattr(produtos, "date", _Hoje)


def _estado(tmp_path, monkeypatch, modo="cloud"):
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    d = {"ofertas": {}, "cupons": {}, "minimo": None, "saude": {}, "ultimo_resumo": None,
         "criado_em": "2026-09-13T15:22:00-03:00", "modelos_iniciados": list(produtos.IDS)}
    (tmp_path / f"state_{modo}.json").write_text(json.dumps(d), encoding="utf-8")
    return Estado(modo)


# ------------------------------------------------------------------------------------------------
# 1. (alta) leitor de disco avulso nunca é o console (classificador e carrinho)
# ------------------------------------------------------------------------------------------------

LEITORES = [
    "Unidade de Disco para Consoles PS5 Digital Edition - Sony",     # nome oficial da Sony
    "Leitor de Disco Ultra HD Blu-ray Console PS5 Slim",
    "Unidade de Disco para Console PS5 Digital Edition",
    "Leitor de Disco Sony para Console PS5 Slim e PS5 Pro, Branco",
    "Drive de Disco para Console PlayStation 5 Pro",
    "Sony - Leitor de Disco Console PS5 Slim",
    "Leitor de Disco Blu-ray Consoles PlayStation 5 Digital Edition",
    "Leitor Disco Playstation 5 Slim/PS5 Pro Sony Branco",
]


@pytest.mark.parametrize("titulo", LEITORES)
def test_leitor_avulso_e_o_leitor_mesmo_com_console_no_titulo(titulo):
    assert produtos.classifica(titulo).produto == "LEITOR_PS5"


@pytest.mark.parametrize("titulo,esperado", [
    ("Console PS5 Slim Leitor de Disco 1TB Branco", "PS5_DISCO"),
    ("Console PlayStation 5 Slim com Leitor de Disco", "PS5_DISCO"),
    ("Console Sony PlayStation 5 com Leitor de Discos SSD 1TB Controle sem fio DualSense 2 Jogos Branco", "PS5_DISCO"),
    ("Console Sony Playstation 5 Standard 825gb E Leitor De Blue Ray", "PS5_DISCO"),
    ("Console PS5 Slim Digital + Leitor de Disco Sony", "PS5_KIT"),
    ("Console PlayStation 5 Slim Edição Digital + Leitor de Disco", "PS5_KIT"),
    ("Capa para Consoles PS5 Slim", None),
])
def test_console_com_leitor_continua_console(titulo, esperado):
    assert produtos.classifica(titulo).produto == esperado


@pytest.mark.parametrize("titulo", LEITORES)
def test_leitor_no_carrinho_nunca_e_um_principal(titulo):
    assert modelo_da_linha(titulo) is None and produto_do_titulo(titulo) is None
    assert produto_do_titulo(titulo + "\nVendido por Sony\nR$ 549\nExcluir") is None


@pytest.mark.parametrize("titulo", [
    "Console PS5 Slim Digital - Capa Protetora",
    "Console PlayStation 5 Slim Suporte Vertical com Cooler",
    "Console PS5 Pro Skin Adesivo Personalizado",
    "PlayStation 5 Slim Digital Base Carregadora para 2 Controles",
])
def test_peca_citada_na_linha_do_carrinho_nunca_e_um_principal(titulo):
    assert produto_do_titulo(titulo) is None and modelo_da_linha(titulo) is None


def test_titulos_do_robo_continuam_reconhecidos_no_carrinho():
    for t, p in (("PlayStation 5 Edição Digital 825GB 1 Controle Branco Sony", "PS5_DIGITAL"),
                 ("Console PlayStation 5 Slim com Leitor de Disco 1TB", "PS5_DISCO"),
                 ("Console Sony PlayStation 5, Com Leitor de Discos, SSD 1TB, Controle Sem Fio DualSense", "PS5_DISCO"),
                 ("Console PS5 Digital 825GB com Controle DualSense Branco - Sony", "PS5_DIGITAL"),
                 ("Jogo Grand Theft Auto VI (GTA 6) PS5 - Code in Box Pré-venda - Lançamento 19/11", "GTA6_CODE_IN_BOX")):
        assert produto_do_titulo(t) == p, t


@pytest.mark.parametrize("titulo", LEITORES[:2])
def test_magalu_nao_tira_o_leitor_da_pessoa(titulo):
    m = Magalu()
    m.comecar_rodada()
    p = SacolaProdutos([{"id": "leitor9", "quantity": 1, "name": titulo, "seller": MAGALU_1P}])
    alvo = _alvo(URL_PS5, "PS5_DIGITAL", restauraveis=("PS5_DIGITAL", "PS5_DISCO", "GTA6_CODE_IN_BOX"))
    with pytest.raises(CarrinhoOcupado):
        m.garantir_item(p, URL_PS5, alvo)
    assert _sacola(p) == [("leitor9", 1)] and p.cliques == [] and m.removidos == []


@pytest.mark.parametrize("titulo", LEITORES[:2])
def test_ml_linha_do_leitor_nao_e_produto_do_carrinho(titulo):
    linhas = [{"links": ["https://produto.mercadolivre.com.br/MLB-7777777777-x"], "texto": titulo + "\nExcluir"}]
    (c,) = MercadoLivre.classificar_linhas(linhas, ML_PS5, "", (), "PS5_DIGITAL", dict(IDS_ML))
    assert (c["tv"], c["modelo"]) == (False, None)


# ------------------------------------------------------------------------------------------------
# 2. (média) entrega do GTA 6 na pré-venda conta a partir de 12/11
# ------------------------------------------------------------------------------------------------

class _Resp:
    def __init__(self, d):
        self.d = d

    def json(self):
        return self.d

    def raise_for_status(self):
        pass


def _gta_vtex(monkeypatch, estimativa="5bd", descricao="Pré-venda. Lançamento 19/11/2026"):
    gta = {"productId": "9", "productName": "Jogo Grand Theft Auto VI PS5 Code in Box", "link": "https://x/p",
           "description": descricao,
           "items": [{"itemId": "1", "ean": "0710425676338", "sellers": [{"sellerId": "1", "sellerName": "AMERICANAS SA",
                      "commertialOffer": {"Price": 449.9, "AvailableQuantity": 5, "Installments": []}}]}]}
    monkeypatch.setattr(vtex, "get_json", lambda url, **k: [gta])
    sim = {"logisticsInfo": [{"itemIndex": 0, "slas": [{"id": "NORMAL", "shippingEstimate": estimativa,
                                                       "deliveryChannel": "delivery"}]}]}
    monkeypatch.setattr(vtex.requests, "post", lambda *a, **k: _Resp(sim))
    (o,), _ = vtex.VtexEan("americanas").coletar()
    return o


def test_vtex_pre_venda_conta_o_prazo_a_partir_de_12_11(monkeypatch, hoje_03_10):
    monkeypatch.delenv("CEP_ENTREGA", raising=False)
    o = _gta_vtex(monkeypatch)
    # 12/11 (quinta) + 5 dias úteis: 13, 16, 17, 18 e 19/11
    assert o.extra["entrega_prevista"] == "2026-11-19" and o.extra["entrega_ate_lancamento"] is False
    e = produtos.entrega(o)
    assert e.classe == "no_dia" and "chega a tempo" not in e.texto
    assert produtos.alvos_da_oferta(o, "2026-10-03")[:2] == (300.0, 320.0)


def test_vtex_pre_venda_com_envio_informado_conta_a_partir_do_envio(monkeypatch, hoje_03_10):
    monkeypatch.delenv("CEP_ENTREGA", raising=False)
    o = _gta_vtex(monkeypatch, "2bd", "Envios a partir de 16/11/2026")
    assert o.extra["entrega_prevista"] == "2026-11-18" and produtos.entrega(o).classe == "a_tempo"


def test_simula_prazo_sem_inicio_continua_contando_de_hoje(monkeypatch, hoje_03_10):
    sim = {"logisticsInfo": [{"slas": [{"shippingEstimate": "5bd", "deliveryChannel": "delivery"}]}]}
    monkeypatch.setattr(vtex.requests, "post", lambda *a, **k: _Resp(sim))
    assert vtex.simula_prazo("https://x", "1", "1", "01310100") == "2026-10-09"
    assert vtex.simula_prazo("https://x", "1", "1", "01310100", inicio=date(2026, 11, 12)) == "2026-11-19"


@pytest.mark.parametrize("lida,esperada,ajustou", [
    ("2026-10-09", "2026-11-19", True),    # 5 dias úteis depois de hoje (sábado 03/10): 5 depois de 12/11
    ("2026-10-05", "2026-11-13", True),    # 1 dia útil
    ("2026-11-16", "2026-11-16", False),   # depois de 12/11: a data da loja vale como está
    (None, None, False),
])
def test_ajusta_pre_venda(lida, esperada, ajustou, hoje_03_10):
    assert entrega.ajusta_pre_venda(lida) == (esperada, ajustou)


def test_marca_reprojeta_data_antes_de_12_11(hoje_03_10):
    gta = Oferta("x", "loja", "Amazon", "GTA 6", "u", "1", preco=400, modelo="GTA6_CODE_IN_BOX")
    entrega.marca(gta, "2026-10-09", False, "página da Amazon")
    assert gta.extra["entrega_prevista"] == "2026-11-19" and gta.extra["entrega_ate_lancamento"] is False
    assert "12/11" in gta.extra["entrega_origem"]
    e = produtos.entrega(gta)
    assert e.classe == "no_dia" and "previsão 19/11 (contado a partir de 12/11)" in e.texto


def test_data_antes_de_12_11_gravada_sem_ajuste_nao_chega_a_tempo(hoje_03_10):
    o = {"modelo": "GTA6_CODE_IN_BOX", "loja": "Americanas", "extra": {"entrega_prevista": "2026-10-09"}}
    e = produtos.entrega(o)
    assert e.classe == "desconhecida" and "chega a tempo" not in e.texto and "12/11" in e.texto
    assert produtos.alvos_da_oferta(o, "2026-10-03").nota == "prazo desconhecido"


def test_entrega_lida_no_carrinho_antes_de_12_11_e_reprojetada(amb):
    # relógio do testador: sábado 19/09; o carrinho diz 25/09 (5 dias úteis): 5 dias úteis depois de 12/11 = 19/11
    _latest(amb, [O_GTA], cupons=[])
    loja = CarrinhoProdutos(amb.pasta, aceita={(K_GTA, "GTA60"): 60.0}, entregas={K_GTA: "2026-09-25"})
    aceitos, _ = amb.rodar(loja, None)
    (r,) = [x for x in aceitos if x.codigo == "GTA60"]
    assert (r.extra["alvo_pix"], r.extra["alvo_parcelado"]) == (300.0, 320.0)
    msg = tc.msg_melhor([("Magazine Luiza", r)])
    assert "previsão 19/11" in msg and "chega a tempo" not in msg


# ------------------------------------------------------------------------------------------------
# 3. (média) gift card da PlayStation só paga a PS Store
# ------------------------------------------------------------------------------------------------

def _gift(pub):
    return Oferta(fonte="promobit", tipo="post", loja="Mercado Livre",
                  titulo="Gift Card PlayStation R$ 100 - Loja oficial PlayStation", url="https://www.promobit.com.br/g/",
                  id="g1", preco=81.0, modelo="GIFT_CARD_PSN", cupom="LOJASOFICIAIS",
                  extra={"produto": {"valor_face": 100.0}}, publicado=pub)


def _ps_store():
    return Oferta(fonte="psstore", tipo="loja", loja="PlayStation Store", titulo="Grand Theft Auto VI",
                  url="https://store.playstation.com/pt-br/product/EP1004-PPSA01547_00-GTAVISTANDARD001",
                  id="EP1004-PPSA01547_00-GTAVISTANDARD001", preco=449.90, vendedor="PlayStation Store",
                  modelo="GTA6_DIGITAL")


def _chave_eneba(pub, preco=420.0):
    return Oferta(fonte="promobit", tipo="post", loja="Eneba", titulo="GTA VI Edição Standard PS5 Digital - chave",
                  url="https://www.promobit.com.br/oferta/k/", id="k1", preco=preco, modelo="GTA6_DIGITAL", publicado=pub)


def test_gift_card_nao_desconta_chave_de_outra_loja():
    pub = agora_iso()
    gift = produtos.desconto_gift_card([_gift(pub)])
    assert gift and round(gift[0], 2) == 0.19
    chave = _chave_eneba(pub)
    assert produtos.preco_comparavel(chave, gift[0]) == 420.0
    linhas = produtos.linhas_da_oferta(chave, gift)
    assert not any("custo efetivo" in l for l in linhas)
    assert any("R$ 55,00 acima da meta" in l for l in linhas), linhas
    # a PS Store continua com o custo efetivo
    assert produtos.preco_comparavel(_ps_store(), gift[0]) == 364.42


def test_alerta_da_chave_da_eneba_sem_meta_falsa(tmp_path, monkeypatch):
    e = _estado(tmp_path, monkeypatch)
    pub = agora_iso()
    ofertas = [_ps_store(), _gift(pub), _chave_eneba(pub)]
    confianca.avaliar(e, ofertas, rede=False)
    msgs, _ = gerar_alertas(e, ofertas, [])
    (eneba,) = [x for x in msgs if "Eneba" in x]
    assert "🎯" not in eneba.split("\n")[0] and "custo efetivo" not in eneba
    (ps,) = [x for x in msgs if "PlayStation Store" in x.split("\n")[0]]
    assert "🎯" in ps.split("\n")[0] and "custo efetivo R$ 364,42" in ps


def test_custo_final_do_gta_nao_desconta_a_chave():
    pub = agora_iso()
    linhas = produtos.custo_final_gta([_ps_store(), _gift(pub), _chave_eneba(pub)])
    por_loja = {l["loja"]: l for l in linhas if l["produto"] == "GTA6_DIGITAL"}
    assert por_loja["Eneba"]["custo_final"] == 420.0 and por_loja["PlayStation Store"]["custo_final"] == 364.42
    assert "PS Store" not in por_loja["Eneba"]["forma"] and "Eneba" in por_loja["Eneba"]["forma"]
    assert linhas[0]["loja"] == "PlayStation Store"


# ------------------------------------------------------------------------------------------------
# 4. (média) o controle que acompanha o console não é extra de kit
# ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("titulo,esperado", [
    ("Console PlayStation 5 Slim Digital 825GB + Controle Sem Fio Dualsense Branco", "PS5_DIGITAL"),  # Shopee 27/09
    ("Console PlayStation 5 Pro Branco De 2TB + Controle Sem Fio Dualsense Branco", "PS5_PRO"),      # Inpower 25/09
    ("Console PS5 Slim Digital 825GB + Controle", "PS5_DIGITAL"),
    ("PlayStation 5 Slim Disk 1TB + Controle DualSense", "PS5_DISCO"),
    ("Console PS5 Slim Digital + GTA 6 + Controle DualSense", "PS5_DIGITAL_GTA6"),
    # o que é a mais continua kit
    ("Console PlayStation 5 Slim Digital 825GB + Controle DualSense Extra", "PS5_KIT"),
    ("Kit PS5 Slim Digital + 2 Controles DualSense", "PS5_KIT"),
    ("Console PlayStation 5 Slim Digital com 2 Controles", "PS5_KIT"),
    ("Console PS5 Slim Digital - Kit com Controle Extra", "PS5_KIT"),
    ("Console PS5 Slim Digital + Controle Adicional DualSense", "PS5_KIT"),
    ("Console PS5 Slim Digital + Controle DualSense Edge", "PS5_KIT"),
    ("Console PS5 Slim Digital + Mais Um Controle", "PS5_KIT"),
    # rodada seca de 03/10 depois da correção (KaBuM/EFACINI e @pelandobr): sobra de texto não é um "outro jogo"
    ("Console Playstation 5 Slim Digital SSD 825gb 4k Uhd 120hz Ray Tracing + Controle Dualsense E 2 Jogos, Bivolt, "
     "Branco", "PS5_DIGITAL"),
    ("Console PlayStation 5 com Leitor de Discos e SSD 1TB + Jogo ASTRO BOT + Gran Turismo 7 - PS5", "PS5_DISCO"),
    ("Console PS5 Slim Digital + Jogo EA FC 26", "PS5_KIT"),
])
def test_controle_que_acompanha_nao_e_extra(titulo, esperado):
    c = produtos.classifica(titulo)
    assert c.produto == esperado, c


def test_vale_da_loja_no_kit_conta_como_credito():
    # KaBuM: "+ Gift Card KaBuM: 500 Reais" é crédito (80% do valor de face), não um "outro jogo" de R$ 200
    c = produtos.classifica("Console Sony PlayStation 5 Com Leitor de Discos SSD 1TB Controle Sem Fio DualSense + 2 Jogos "
                            "+ Gift Card KaBuM: 500 Reais")
    assert c.produto == "PS5_KIT" and c.detalhes["base"] == "PS5_DISCO"
    assert [e["tipo"] for e in c.detalhes["extras"]] == ["credito"] and c.detalhes["valor_extra"] == 400.0


@pytest.mark.parametrize("titulo,preco", [
    ("Console PlayStation 5 Slim Digital 825GB + Controle Sem Fio Dualsense Branco", 3799.0),
    ("Console PlayStation 5 Pro Branco De 2TB + Controle Sem Fio Dualsense Branco", 6200.0),
])
def test_alerta_do_console_com_o_controle_que_acompanha_usa_a_meta_do_console(tmp_path, monkeypatch, titulo, preco):
    e = _estado(tmp_path, monkeypatch)
    c = produtos.classifica(titulo, "Shopee")
    post = Oferta(fonte="promobit", tipo="post", loja="Shopee", titulo=titulo, url="https://p/x", id="x", preco=preco,
                  modelo=c.produto, extra={"produto": c.detalhes}, publicado=agora_iso())
    (msg,) = gerar_alertas(e, [post], [])[0]
    assert "🎯" not in msg.split("\n")[0] and "acima da meta" in msg


# ------------------------------------------------------------------------------------------------
# 5. (baixas) classificador, cupons, limite de alertas, cupom do anúncio do Magalu
# ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("titulo,esperado", [
    ("Mousepad Gamer Grande GTA VI 90x40", None),
    ("Mouse Pad Gamer GTA 6 Vice City", None),
    ("Console PS5 Slim Digital - Grade A", None),
    ("Console Playstation 5 Slim Digital 825GB Edição Limitada 30 Anos", None),
    ("GTA 6 PS5 Conta Secundária", None),
    ("GTA 6 PS5 Mídia Digital Primária", None),
    ("GTA VI PS5 Digital - Conta Compartilhada", None),
    ("Garantia Estendida - Console PS5", None),
    ("Seguro Roubo e Furto Console PlayStation 5 Slim", None),
    ("Notebook Gamer + GTA VI de brinde", None),
    ("Ganhe GTA VI na compra de Placa de Vídeo RTX", None),
    # o que é o produto continua
    ("GTA VI PS5 Pré-venda Mídia Física Brinde Mapa", "GTA6_CODE_IN_BOX"),
    ("Jogo GTA 6 PS5 Code in Box Pré-venda Lançamento 19/11", "GTA6_CODE_IN_BOX"),
    ("GTA VI Edição Standard PS5 Digital", "GTA6_DIGITAL"),
    ("Console PS5 Slim Digital 825GB (Nacional)", "PS5_DIGITAL"),
    ("Console PlayStation 5 Slim Edição Digital Fortnite Cobalt Star", "PS5_KIT"),
])
def test_classificador_casos_da_revisao(titulo, esperado):
    assert produtos.classifica(titulo).produto == esperado


def test_classificador_conta_compartilhada_com_id_conhecido():
    assert produtos.classifica("GTA VI Conta Secundária", "KaBuM!", id_loja="1051619").produto is None


def _cupom(loja, codigo, titulo, regra=""):
    return Cupom("promobit", loja, codigo, titulo, "https://c", codigo, regra=regra)


def test_cupom_do_leitor_nao_serve_para_o_console():
    c = _cupom("KaBuM!", "LEITOR62", "R$ 62 OFF no Leitor de Disco PS5")
    assert cupom_compativel(c, None, "LEITOR_PS5")[0] is True
    for p in ("PS5_DIGITAL", "PS5_PRO", "PS5_DISCO", "GTA6_CODE_IN_BOX"):
        assert cupom_compativel(c, None, p)[0] is False, p
    # cupom dos consoles e dos leitores: os dois
    c2 = _cupom("KaBuM!", "PLAYLEITOR", "10% OFF em consoles e leitores de disco")
    assert cupom_compativel(c2, None, "PS5_DIGITAL")[0] is True and cupom_compativel(c2, None, "LEITOR_PS5")[0] is True


def test_cupom_de_games_e_consoles_serve_para_o_jogo():
    c = _cupom("KaBuM!", "GAMES10", "10% OFF em Games e Consoles")
    for p in ("PS5_DIGITAL", "PS5_PRO", "GTA6_CODE_IN_BOX"):
        assert cupom_compativel(c, None, p)[0] is True, p
    assert cupom_compativel(c, None, "GIFT_CARD_PSN")[0] is False
    assert cupom_compativel(_cupom("KaBuM!", "PS5200", "R$ 200 OFF no PS5"), None, "GTA6_CODE_IN_BOX")[0] is False


def test_limite_de_alertas_guarda_o_que_bate_a_meta():
    import run

    class Est:
        esqueceu = False

        def esquece_alertas_de_cupom_da_rodada(self):
            self.esqueceu = True

    comuns = [f"📣 Promoção postada · PS5 Slim Digital — <b>Amazon</b>\nPS5\n{i}" for i in range(16)]
    meta = "📣 Promoção postada 🎯 · GTA 6 PS5 Code in Box — <b>KaBuM!</b>\nGTA 6\nR$ 339"
    saida = run.limita_alertas(["⚠️ aviso"] + comuns + [meta], Est(), 15)
    assert len(saida) == 16 and meta in saida and saida[-1].startswith("… e mais 3 alertas")
    assert saida[0] == "⚠️ aviso", "a ordem das que ficam não muda"
    assert run.limita_alertas(["⚠️ aviso"] + comuns[:3], Est(), 15) == ["⚠️ aviso"] + comuns[:3]


def test_mesmo_post_de_ps5_em_varios_canais_vira_um_alerta(tmp_path, monkeypatch):
    e = _estado(tmp_path, monkeypatch)
    agora = agora_iso()
    canais = ["cupons_desconto", "tecnanofertas", "pelandobr", "promotop", "vrlofertas"]
    posts = [Oferta("telegram", "post", "Amazon", f"[{c}] Sony PlayStation 5 Edição Digital 825GB 1 Controle",
                    f"https://t.me/{c}/1", f"{c}/1", preco=3889.0, publicado=agora, modelo="PS5_DIGITAL")
             for c in canais]
    msgs, _ = gerar_alertas(e, posts, [])
    assert len(msgs) == 1 and "também postado em" in msgs[0] and "pelandobr" in msgs[0]
    # TV: como antes, uma mensagem por post
    tvs = [Oferta("telegram", "post", "Magazine Luiza", f"[{c}] Smart TV TCL 55C6K", f"https://t.me/{c}/2", f"{c}/2",
                  preco=3399.0, publicado=agora, modelo="55C6K") for c in canais[:2]]
    (tmp_path / "b").mkdir()
    msgs, _ = gerar_alertas(_estado(tmp_path / "b", monkeypatch), tvs, [])
    assert len(msgs) == 2


def _produto_magalu(tags, pix=4549.0):
    return {"seller": {"tags": tags}, "path": "/console-ps5/p/240604800/et/elit/"}, Oferta(
        "magalu", "loja", "Magazine Luiza", "Console PS5 Digital", "u", "240604800-magazineluiza", preco=4899.0,
        preco_pix=pix, modelo="PS5_DIGITAL")


def test_cupom_do_anuncio_do_magalu_usa_o_codigo_do_desconto(hoje_03_10):
    p, o = _produto_magalu([
        {"type": "coupon", "code": "PCT10", "discountType": "percentage", "discountValue": 10,
         "endDate": "2026-10-31T23:59:00-03:00", "message": "10% OFF com cupom: PCT10"},
        {"type": "coupon", "code": "LU325", "discountType": "absolute", "discountValue": 325,
         "endDate": "2026-10-05T23:59:00-03:00", "message": "R$ 325,00 OFF com cupom: LU325"}])
    magalu._aplica_cupom(o, p, magalu._cupons(p, "PS5_DIGITAL"))
    assert produtos.preco_com_cupom_do_anuncio(o) == (4224.0, "LU325")


def test_cupom_do_anuncio_vencido_ou_com_compra_minima_nao_conta(hoje_03_10):
    p, o = _produto_magalu([{"type": "coupon", "code": "LU325", "discountType": "absolute", "discountValue": 325,
                             "endDate": "2026-10-01T23:59:00-03:00", "message": "R$ 325,00 OFF com cupom: LU325"}])
    magalu._aplica_cupom(o, p, magalu._cupons(p, "PS5_DIGITAL"))
    assert produtos.preco_com_cupom_do_anuncio(o) is None, "venceu em 01/10"
    p, o = _produto_magalu([{"type": "coupon", "code": "LU500", "discountType": "absolute", "discountValue": 500,
                             "endDate": "2026-10-31T23:59:00-03:00",
                             "message": "R$ 500,00 OFF com cupom: LU500 em compras acima de R$ 5.000"}])
    magalu._aplica_cupom(o, p, magalu._cupons(p, "PS5_DIGITAL"))
    assert produtos.preco_com_cupom_do_anuncio(o) is None, "compra mínima acima do preço"


def _post_reg(chave, modelo, publicado):
    return {"fonte": "telegram", "tipo": "post", "loja": "Amazon", "titulo": f"[canal] {modelo}", "url": "https://t.me/x",
            "id": chave, "chave": f"telegram:{chave}", "preco": 400.0, "modelo": modelo, "publicado": publicado,
            "primeira_vez": publicado, "ativo": True, "extra": {}}


def test_poda_so_postagens_antigas_de_ps5_e_gta(tmp_path, monkeypatch):
    e = _estado(tmp_path, monkeypatch)
    e.dados["ofertas"] = {
        "telegram:velho_gta": _post_reg("velho_gta", "GTA6_CODE_IN_BOX", "2026-08-01T10:00:00-03:00"),
        "telegram:visto": _post_reg("visto", "PS5_DIGITAL", "2026-08-01T10:00:00-03:00"),
        "telegram:novo": _post_reg("novo", "PS5_DIGITAL", agora_iso()),
        "telegram:sem_data": _post_reg("sem_data", "PS5_DIGITAL", None),
        "telegram:tv_velha": _post_reg("tv_velha", "55C6K", "2026-08-01T10:00:00-03:00"),
        "telegram:legado": {**_post_reg("legado", None, "2026-08-01T10:00:00-03:00"), "modelo": None},
    }
    assert e.poda_postagens({"telegram:visto"}) == 1
    assert sorted(e.dados["ofertas"]) == ["telegram:legado", "telegram:novo", "telegram:sem_data", "telegram:tv_velha",
                                          "telegram:visto"]


def test_latest_tem_cota_para_as_postagens_das_tvs(tmp_path, monkeypatch):
    from monitor import estado as estado_mod

    e = _estado(tmp_path, monkeypatch)
    regs = {}
    for i in range(150):   # 150 postagens novas do PS5, mais recentes que as das TVs
        regs[f"telegram:p{i}"] = _post_reg(f"p{i}", "PS5_DIGITAL", f"2026-10-03T{10 + i // 60:02d}:{i % 60:02d}:00-03:00")
    for i in range(5):
        regs[f"telegram:t{i}"] = _post_reg(f"t{i}", "65C6K", f"2026-10-01T10:0{i}:00-03:00")
    e.dados["ofertas"] = regs
    e.escreve_latest([], [])
    posts = json.loads((tmp_path / "latest_cloud.json").read_text(encoding="utf-8"))["posts"]
    assert sum(p["modelo"] == "65C6K" for p in posts) == 5, "as postagens das TVs continuam no latest"
    assert sum(p["modelo"] == "PS5_DIGITAL" for p in posts) == estado_mod.POSTS_NAO_TV_NO_LATEST
    assert [p["publicado"] for p in posts] == sorted((p["publicado"] for p in posts), reverse=True)
