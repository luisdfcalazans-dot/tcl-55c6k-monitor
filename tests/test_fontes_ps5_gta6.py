"""Fontes do PS5 e do GTA 6 (frente B, 03/10/2026): lojas novas, ampliação das de antes, busca por termo no canal do
Pelando e o prazo de entrega do GTA 6 com o CEP de entrega.

Fixtures: páginas e respostas reais de 03/10/2026 (aparadas), lidas sem login e com o CEP de referência (centro de São
Paulo). Nenhum teste acessa a rede nem abre o Chrome: get_html/get_json/requests.post/_abrir/_avaliar são trocados.
O CEP de entrega dos testes é inventado (o do usuário nunca aparece em teste, log nem fixture).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import requests

from monitor import config, confianca, produtos
from monitor.models import Oferta
from monitor.sources import (amazon, carrefour, entrega, kabum, magalu, mercadolivre_loja, netshoes, promobit, psstore,
                             telegram_public, vtex)
from monitor.sources import playwright_sources as ps

FX = Path(__file__).parent / "fixtures"
D = "2026-10-03"
CEP_FALSO = "04567890"   # inventado: só para provar que o CEP vai para a loja e não para log/oferta


def _fx(nome: str) -> str:
    return (FX / nome).read_text(encoding="utf-8")


def _json(nome: str):
    return json.loads(_fx(nome))


@pytest.fixture
def hoje_03_10(monkeypatch):
    monkeypatch.setattr(entrega, "hoje", lambda: date(2026, 10, 3))


@pytest.fixture
def sem_cep(monkeypatch):
    monkeypatch.delenv("CEP_ENTREGA", raising=False)


@pytest.fixture
def com_cep(monkeypatch):
    monkeypatch.setenv("CEP_ENTREGA", CEP_FALSO)


def _sem_cep_em(ofertas, saida: str = "") -> None:
    """O CEP de entrega nunca vai para a oferta (state/latest/painel) nem para a saída (log)."""
    for o in ofertas:
        assert CEP_FALSO not in json.dumps(o.to_dict(), ensure_ascii=False, default=str), o.id
    assert CEP_FALSO not in saida


class _Resp:
    def __init__(self, dados, status: int = 200):
        self.dados, self.status_code = dados, status

    def json(self):
        return self.dados

    def raise_for_status(self):
        if self.status_code >= 400:
            r = requests.Response()
            r.status_code = self.status_code
            raise requests.HTTPError(str(self.status_code), response=r)


# ------------------------------------------------------------------------------------------------
# prazo de entrega (monitor/sources/entrega.py)
# ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("texto,iso", [
    ("Segunda-feira, 16 de Novembro", "2026-11-16"),
    ("Entrega GRÁTIS: seg., 16 de nov.", "2026-11-16"),
    ("Chega dia 30 de novembro", "2026-11-30"),
    ("até 17/11/2026", "2026-11-17"),
    ("17/11/26", "2026-11-17"),
    ("até quarta-feira (07/10/2026)", "2026-10-07"),
    ("sem data", None),
])
def test_data_por_extenso(texto, iso, hoje_03_10):
    assert entrega.data_por_extenso(texto) == iso


def test_estimativa_em_dias_uteis_pula_fim_de_semana_e_feriado(hoje_03_10):
    # sábado 03/10 + 5 dias úteis: 05, 06, 07, 08, 09/10
    assert entrega.data_da_estimativa("5bd") == "2026-10-09"
    # a segunda 12/10 é feriado: 7 dias úteis vão até 14/10
    assert entrega.data_da_estimativa("7bd") == "2026-10-14"
    assert entrega.data_da_estimativa("3d") == "2026-10-06"
    assert entrega.data_da_estimativa("39bd") > produtos.ENTREGA_LIMITE_GTA6   # a Webfones da Fast Shop
    assert entrega.data_da_estimativa("xyz") is None


@pytest.mark.parametrize("texto,iso", [
    ("<strong>ENVIO A PARTIR DE 19 DE NOVEMBRO</strong>", "2026-11-19"),                      # Carrefour
    ("PRÉ-VENDA LANÇAMENTO 12/11/2026, ESTE PRODUTO SERA ENVIADO A PARTIR DO DIA:\xa0 20/11/2026", "2026-11-20"),
    ("Envios a partir de 12/11/2026", "2026-11-12"),
    ("Lançamento 19/11", None),
])
def test_envio_a_partir(texto, iso, hoje_03_10):
    assert entrega.envio_a_partir(texto) == iso


def test_uf_do_cep_e_marca_so_no_gta_fisico():
    assert entrega.uf_do_cep("01310100") == "SP" and entrega.uf_do_cep("70002900") == "DF"
    assert entrega.uf_do_cep("90010000") == "RS" and entrega.uf_do_cep("123") == "SP"
    gta = Oferta("x", "loja", "KaBuM!", "GTA 6", "u", "1", preco=400, modelo="GTA6_CODE_IN_BOX")
    entrega.marca(gta, "2026-11-17", True, "cotação de frete")
    assert gta.extra["entrega_prevista"] == "2026-11-17" and gta.extra["entrega_ate_lancamento"] is True
    assert produtos.entrega(gta).classe == "a_tempo" and gta.extra["cep_referencia"] is True
    ps5 = Oferta("x", "loja", "KaBuM!", "PS5", "u", "2", preco=4000, modelo="PS5_DIGITAL")
    entrega.marca(ps5, "2026-10-09", False)
    assert "entrega_prevista" not in ps5.extra   # o prazo só importa no que traz o GTA 6 físico


def test_cep_de_referencia_sem_a_variavel(sem_cep):
    assert entrega.cep() == (config.CEP_REFERENCIA, True)


# ------------------------------------------------------------------------------------------------
# VTEX pelo EAN: Mais Correios, Americanas, Fast Shop e Webcontinental (PS5/GTA 6)
# ------------------------------------------------------------------------------------------------

def test_mais_correios_pelo_ean_tvs_e_ps5():
    ofs = vtex.parse_catalogo(_json(f"maiscorreios_ean_{D}.json"), "Mais Correios", "https://www.maiscorreios.com.br",
                              fonte="maiscorreios")
    por_id = {o.id: o for o in ofs}
    # o anúncio do Ponto Frio onde o usuário comprou a 65C6K (a busca por texto não achava) e o PS5 da Webcontinental
    pf = por_id["Mais Correios-900598-MCR010"]
    assert (pf.modelo, pf.vendedor, pf.preco, pf.preco_pix, pf.parcelado) == (
        "65C6K", "Ponto Frio", 4354.44, 4136.72, "10x R$ 435,44 sem juros")
    ps5 = por_id["Mais Correios-1474239-MCR008"]
    assert (ps5.modelo, ps5.preco_pix, ps5.fonte, ps5.loja) == ("PS5_DIGITAL", 5145.68, "maiscorreios", "Mais Correios")
    assert ps5.extra["sku"] == "1685969" and ps5.extra["seller_id"] == "MCR008"
    assert "vendedor_id" not in ps5.extra   # as listas de confiança da loja casam pelo nome
    # o vendedor "Infracommerce" sem estoque não vira oferta
    assert not any("-1" == o.id[-2:] for o in ofs)
    assert confianca.classifica_por_lista(ps5, ())[0] == confianca.CONFIAVEL
    assert confianca.classifica_por_lista(pf, ())[0] == confianca.CONFIAVEL


def test_americanas_cartao_da_loja_nao_e_o_parcelado():
    ofs = vtex.parse_catalogo(_json(f"americanas_ean_{D}.json"), "Americanas", "https://www.americanas.com.br",
                              fonte="americanas")
    por_id = {o.id: o for o in ofs}
    am = por_id["Americanas-8269631-1"]
    assert (am.modelo, am.vendedor, am.preco, am.parcelado) == ("PS5_DIGITAL", "AMERICANAS SA", 4599.99,
                                                                "12x R$ 383,33 sem juros")
    mg = por_id["Americanas-8299907-magazineluiza"]
    # 10x é com juros (1,84%) e o "Cartão Cliente A" (cartão da loja) não conta: 8x no cartão comum
    assert (mg.preco, mg.preco_pix, mg.parcelado) == (4599.0, 4369.05, "8x R$ 574,87 sem juros")
    assert {o.modelo for o in ofs} == {"65C6K", "PS5_DIGITAL"}   # a resposta pelo EAN do PS5 Digital e da 65C6K
    colombo = por_id["Americanas-8392053-TALD54891759267232"]
    assert colombo.preco_pix == 4887.81    # o Pix da parcela 1x (10%), não a soma dos selos
    for o in (am, mg, colombo):
        assert confianca.classifica_por_lista(o, ())[0] == confianca.CONFIAVEL, o.vendedor


def test_vtex_ean_um_pedido_com_os_eans_com_e_sem_zero_e_a_reserva(monkeypatch, sem_cep):
    pedidas = []

    def get_json(url, **k):
        pedidas.append(url)
        if url.startswith("https://www.maiscorreios.com.br"):
            raise requests.HTTPError("403")
        return _json(f"maiscorreios_ean_{D}.json")

    monkeypatch.setattr(vtex, "get_json", get_json)
    ofs, _ = vtex.VtexEan("maiscorreios").coletar()
    assert len(pedidas) == 2 and pedidas[1].startswith("https://maiscorreios.vtexcommercestable.com.br")
    assert "fq=alternateIds_Ean:711719023876" in pedidas[0] and "fq=alternateIds_Ean:0711719023876" in pedidas[0]
    assert "fq=alternateIds_Ean:7899968301754" in pedidas[0] and pedidas[0].endswith("&_from=0&_to=49")
    assert {o.fonte for o in ofs} == {"maiscorreios"} and {"65C6K", "PS5_DIGITAL"} <= {o.modelo for o in ofs}


def test_vtex_fast_shop_so_ps5_e_gta_com_prazo_da_simulacao(monkeypatch, hoje_03_10, com_cep, capsys):
    gta = {"productId": "175223", "productName": "Jogo PS5 Grand Theft Auto VI", "link": "https://site.fastshop.com.br/x/p",
           "description": "DATA DE LANÇAMENTO: 19 de Novembro de 2026",
           "items": [{"itemId": "185443", "ean": "710425676338", "sellers": [{"sellerId": "CNL132", "sellerName": "Webfones",
                      "commertialOffer": {"Price": 449.9, "ListPrice": 449.9, "AvailableQuantity": 100, "Teasers": [],
                                          "Installments": []}}]}]}
    tv = _json(f"maiscorreios_ean_{D}.json")[:1]
    monkeypatch.setattr(vtex, "get_json", lambda url, **k: tv + [gta])
    corpos = []

    def post(url, json=None, **k):
        corpos.append((url, json))
        return _Resp(_json(f"vtex_simulacao_gta_{D}.json"))

    monkeypatch.setattr(vtex.requests, "post", post)
    ofs, _ = vtex.VtexEan("vtex.fastshop.ps5").coletar()
    assert [o.modelo for o in ofs] == ["GTA6_CODE_IN_BOX"]   # a TV da resposta fica com a fonte vtex.fastshop
    o = ofs[0]
    # os 39 dias úteis contam de hoje, como a loja conta: já caem depois de 12/11 (01/12), então não são reprojetados
    # (2ª conferência de 03/10: contar de 12/11 punha a espera da pré-venda duas vezes e dava 11/01/2027)
    assert o.fonte == "vtex.fastshop.ps5" and o.extra["entrega_prevista"] == entrega.data_da_estimativa("39bd") \
        == "2026-12-01"
    assert o.extra["entrega_ate_lancamento"] is False and o.extra["cep_referencia"] is False
    (url, corpo), = corpos
    assert url.endswith("/api/checkout/pub/orderForms/simulation?sc=1")
    assert corpo["postalCode"] == CEP_FALSO and corpo["items"] == [{"id": "185443", "quantity": 1, "seller": "CNL132"}]
    _sem_cep_em(ofs, capsys.readouterr().out)
    assert produtos.alvos_da_oferta(o).pix == 300.0   # chega depois: meta do GTA tardio


def test_vtex_envio_depois_do_lancamento_na_descricao_dispensa_a_simulacao(monkeypatch, sem_cep):
    gta = {"productId": "9", "productName": "Jogo GTA 6 PS5", "description": "ENVIO A PARTIR DE 19 DE NOVEMBRO",
           "items": [{"itemId": "1", "ean": "0710425676338", "sellers": [{"sellerId": "1", "sellerName": "Loja",
                      "commertialOffer": {"Price": 449.9, "AvailableQuantity": 1, "Installments": []}}]}]}
    monkeypatch.setattr(vtex, "get_json", lambda url, **k: [gta])
    monkeypatch.setattr(vtex.requests, "post", lambda *a, **k: pytest.fail("não precisava simular"))
    (o,), _ = vtex.VtexEan("americanas").coletar()
    assert o.extra["entrega_ate_lancamento"] is False and produtos.entrega(o).classe == "depois"


# ------------------------------------------------------------------------------------------------
# KaBuM: lista de consoles, API do GTA 6 e cotação de frete
# ------------------------------------------------------------------------------------------------

@pytest.fixture
def durante_a_oferta(monkeypatch):
    """As ofertas relâmpago da lista acabam em 07/10 10:00: o relógio fica em 03/10 17:00."""
    monkeypatch.setattr(kabum.time, "time", lambda: 1791057600.0)


def test_kabum_lista_de_consoles(durante_a_oferta):
    por_id = {o.id: o for o in kabum.parse_lista(_fx(f"kabum_lista_consoles_{D}.html"))}
    # PS3 (614484) e o Portal (697721) ficam de fora; o "Standard 825GB e leitor de Blu-ray" é com leitor
    assert set(por_id) == {"989702", "1004851", "939943", "1065184", "1064155", "636960"}
    k = por_id["989702"]
    assert (k.modelo, k.vendedor, k.preco, k.preco_pix, k.extra["oferta"]) == (
        "PS5_DIGITAL", "KaBuM!", 4499.0, 4184.07, "OFERTAS KABUM")
    g = por_id["1004851"]
    assert (g.vendedor, g.preco_pix, g.extra["kabum_seller_id"], g.extra["kabum_oferta_id"]) == (
        "Loja Gazin", 4099.0, "8145", 2980774)
    assert por_id["1064155"].modelo == "PS5_DISCO" and por_id["636960"].modelo == "PS5_PRO"
    assert por_id["1065184"].modelo == "PS5_KIT" and {o.fonte for o in por_id.values()} == {"kabum.produtos"}
    assert confianca.classifica_por_lista(g, ())[0] == confianca.CONFIAVEL


def test_kabum_lista_fora_da_oferta_volta_ao_preco_normal(monkeypatch):
    monkeypatch.setattr(kabum.time, "time", lambda: 1791378000.0 + 60)
    k = {o.id: o for o in kabum.parse_lista(_fx(f"kabum_lista_consoles_{D}.html"))}["989702"]
    assert (k.preco, k.preco_pix) == (5052.69, 4699.0) and "oferta" not in k.extra


def test_kabum_cotacao_de_frete_ignora_a_entrega_agendada(monkeypatch):
    corpos = []
    monkeypatch.setattr(kabum.requests, "post",
                        lambda url, json=None, **k: corpos.append(json) or _Resp(_json(f"kabum_frete_gta_{D}.json")))
    assert kabum.prazo_cotacao("1051619", "KaBuM!", "0", CEP_FALSO) == "2026-11-17"
    assert corpos[0]["zip_code"] == CEP_FALSO and corpos[0]["sellers"][0]["products"][0]["offer_id"] == 0


def test_kabum_produtos_coleta_o_gta_com_prazo_e_o_parceiro_que_envia_depois(monkeypatch, durante_a_oferta, com_cep,
                                                                           capsys):
    def get_json(url, **k):
        pid = url.rsplit("/", 1)[1]
        if pid in ("1051619", "1066262"):
            return _json(f"kabum_{pid}_{D}.json")
        raise requests.HTTPError("404")

    monkeypatch.setattr(kabum, "get_html", lambda url, **k: _fx(f"kabum_lista_consoles_{D}.html"))
    monkeypatch.setattr(kabum, "get_json", get_json)
    cotados = []

    def post(url, json=None, **k):
        cotados.append(json["sellers"][0]["products"][0]["code"])
        return _Resp(_json(f"kabum_frete_gta_{D}.json"))

    monkeypatch.setattr(kabum.requests, "post", post)
    ofs, _ = kabum.KaBuMProdutos().coletar()
    por_id = {o.id: o for o in ofs}
    gta = por_id["1051619"]
    assert (gta.modelo, gta.preco_pix, gta.extra["pre_venda"], gta.extra["envio_a_partir"]) == (
        "GTA6_CODE_IN_BOX", 418.41, True, "2026-11-12")
    assert (gta.extra["entrega_prevista"], gta.extra["entrega_ate_lancamento"], gta.extra["cep_referencia"]) == (
        "2026-11-17", True, False)
    mo = por_id["1066262"]   # "SERA ENVIADO A PARTIR DO DIA: 20/11/2026": chega depois, sem cotar
    assert mo.extra["envio_a_partir"] == "2026-11-20" and produtos.entrega(mo).classe == "depois"
    assert cotados == [1051619]
    _sem_cep_em(ofs, capsys.readouterr().out)


def test_kabum_das_tvs_continua_igual(monkeypatch):
    # a fonte "kabum" (TVs) não pede a lista nem os anúncios do PS5
    pedidas = []

    def get_json(url, **k):
        pedidas.append(url)
        return {"id": url.rsplit("/", 1)[1], "attributes": {"title": "Smart TV TCL 55C6K", "price": 3999.0,
                                                            "available": True}}

    monkeypatch.setattr(kabum, "get_json", get_json)
    monkeypatch.setattr(kabum, "get_html", lambda *a, **k: pytest.fail("a fonte das TVs não lê a lista"))
    kabum.KaBuM().coletar()
    assert [u.rsplit("/", 1)[1] for u in pedidas] == ["911482", "911480", "938060"]


# ------------------------------------------------------------------------------------------------
# Magalu (magazinevoce): PS5 e GTA 6 pela busca, com o cupom do anúncio
# ------------------------------------------------------------------------------------------------

def test_magalu_busca_do_ps5_com_cupom_do_anuncio():
    ofs, cupons = magalu.parse_busca_produtos(_fx(f"magalu_busca_playstation_5_{D}.html"))
    por_id = {o.id: o for o in ofs}
    assert set(por_id) == {"240604800-magazineluiza", "240590800-magazineluiza", "dd7g1bc698-mmsantosinformatica"}
    d = por_id["240604800-magazineluiza"]
    assert (d.modelo, d.cupom, d.fonte, d.extra["preco_com_cupom"]) == ("PS5_DIGITAL", "LU325", "magalu.produtos", 4224.0)
    (c,) = cupons
    assert (c.codigo, c.modelo, c.especifico) == ("LU325", "PS5_DIGITAL", True)
    assert por_id["240590800-magazineluiza"].modelo == "PS5_DISCO"


def test_magalu_busca_do_gta_so_o_jogo():
    ofs, cupons = magalu.parse_busca_produtos(_fx(f"magalu_busca_gta_vi_{D}.html"))
    # GTA V "para PS5" do importador, caneca e "Decoração Logo GTA VI" ficam de fora
    (o,) = ofs
    assert (o.id, o.modelo, o.preco_pix, o.cupom, o.extra["preco_com_cupom"]) == (
        "241923300-magazineluiza", "GTA6_CODE_IN_BOX", 418.41, "GTA60", 358.41)
    assert [c.codigo for c in cupons] == ["GTA60"] and cupons[0].modelo == "GTA6_CODE_IN_BOX"
    assert produtos.entrega(o).classe == "desconhecida"   # o espelho não traz o prazo do Magalu


def test_magalu_produtos_orcamento_e_bloqueio(monkeypatch):
    pedidas = []

    def site(url, **k):
        pedidas.append(url)
        return _fx(f"magalu_busca_gta_vi_{D}.html") if "gta" in url else _fx(f"magalu_busca_playstation_5_{D}.html")

    monkeypatch.setattr(config, "MAGALU_PAUSA_S", 0)
    monkeypatch.setattr(magalu, "get_html", site)
    ofs, cupons = magalu.MagaluProdutos().coletar()
    assert len(pedidas) == len(config.MAGALU_TERMOS_PRODUTOS) <= config.MAGALU_PRODUTOS_MAX_REQUISICOES
    assert {"PS5_DIGITAL", "GTA6_CODE_IN_BOX"} <= {o.modelo for o in ofs} and {c.codigo for c in cupons} >= {"GTA60"}
    # o magazinevoce bloqueou há pouco (coleta das TVs): espera a próxima rodada, sem contar falha
    monkeypatch.setattr(magalu, "BLOQUEADO_EM", __import__("time").time())
    from monitor.sources import Pular
    with pytest.raises(Pular):
        magalu.MagaluProdutos().coletar()


# ------------------------------------------------------------------------------------------------
# Carrefour, PlayStation Store, loja oficial PlayStation no Mercado Livre, Promobit PS5
# ------------------------------------------------------------------------------------------------

def test_carrefour_busca():
    cartoes = {c["sku"]: c for c in carrefour.parse_busca(_fx(f"carrefour_busca_{D}.html"))}
    c = cartoes["336324399"]
    assert (c["pix"], c["cartao"]) == (4369.9, 4599.89) and c["url"].endswith("-336324399")
    assert "340270416" in cartoes


def test_carrefour_produto_do_gta_envia_depois_do_lancamento():
    o = carrefour.parse_produto(_fx(f"carrefour_produto_gta_{D}.html"), "340270416", "u")
    assert (o.modelo, o.vendedor, o.preco, o.preco_pix, o.parcelado) == (
        "GTA6_CODE_IN_BOX", "Carrefour", 449.9, None, "12x R$ 37,49 sem juros")
    assert o.extra["entrega_ate_lancamento"] is False and produtos.entrega(o).classe == "depois"
    assert confianca.classifica_por_lista(o, ())[0] == confianca.CONFIAVEL


def test_carrefour_produto_de_parceiro():
    o = carrefour.parse_produto(_fx(f"carrefour_produto_parceiro_{D}.html"), "340173928", "u")
    assert (o.modelo, o.vendedor, o.extra["vendedor_id"], o.preco_pix) == (
        "PS5_DIGITAL", "mcs variedades", "MCSVARIEDADES", 4859.1)
    assert confianca.classifica_por_lista(o, ())[0] is None   # parceiro desconhecido: passa pelas checagens


def test_carrefour_coleta_os_do_catalogo_primeiro_e_respeita_o_limite(monkeypatch):
    pedidas = []

    def site(url, **k):
        pedidas.append(url)
        if "/busca/" in url:
            return _fx(f"carrefour_busca_{D}.html")
        return _fx(f"carrefour_produto_gta_{D}.html") if "340270416" in url else _fx(f"carrefour_produto_parceiro_{D}.html")

    monkeypatch.setattr(carrefour, "get_html", site)
    monkeypatch.setattr(config, "CARREFOUR_PAUSA_S", 0)
    monkeypatch.setattr(config, "CARREFOUR_MAX_PRODUTOS", 3)
    ofs, _ = carrefour.Carrefour().coletar()
    assert len(pedidas) == 1 + 3
    assert "340270416" in {o.id for o in ofs}
    assert any(o.extra.get("origem") == "busca" for o in ofs)   # os não abertos ficam com o preço da busca


def test_ps_store_gta_e_a_melhoria_sem_preco(monkeypatch):
    o = psstore.parse_produto(_fx(f"psstore_gta_standard_{D}.html"), "EP1004-PPSA01547_00-GTAVISTANDARD001", "u")
    assert (o.modelo, o.preco, o.loja, o.vendedor) == ("GTA6_DIGITAL", 449.9, "PlayStation Store", "PlayStation Store")
    assert psstore.parse_produto(_fx(f"psstore_gta_upgrade_{D}.html"), "EP1004-PPSA01547_00-ULTEDTIONUPGRADE", "u") is None
    monkeypatch.setattr(psstore, "get_html", lambda url, **k: _fx(f"psstore_gta_standard_{D}.html"))
    ofs, _ = psstore.PlayStationStore().coletar()
    assert ofs and {o.fonte for o in ofs} == {"psstore"}


def test_ml_loja_oficial_playstation():
    (o,) = mercadolivre_loja.parse_loja(_fx(f"ml_loja_playstation_{D}.html"))   # controle, jogo, Portal, VR2 fora
    assert (o.id, o.modelo, o.preco, o.preco_pix, o.parcelado) == (
        "MLB4214670787", "PS5_DIGITAL", 4599.0, 4369.0, "10x R$ 459,99 sem juros")
    assert o.extra["catalogo"] == "MLB57081243" and o.vendedor == "Loja oficial PlayStation"
    assert confianca.classifica_por_lista(o, ())[0] == confianca.CONFIAVEL
    assert mercadolivre_loja.bloqueada('<a href="https://www.mercadolivre.com.br/gz/account-verification?x">')


def test_ml_loja_bloqueada_e_falha_sem_aviso(monkeypatch):
    monkeypatch.setattr(mercadolivre_loja, "get_html", lambda *a, **k: "<html>suspicious-traffic</html>")
    f = mercadolivre_loja.MercadoLivreLojaPlayStation()
    assert f.alerta_falha is False
    with pytest.raises(RuntimeError):
        f.coletar()


def test_promobit_subcategoria_ps5(monkeypatch):
    nd = {"props": {"pageProps": {"serverOffers": [
        {"offerId": 1, "offerTitle": "Grand Theft Auto VI - PlayStation 5", "offerPrice": 358.41,
         "storeName": "Magazine Luiza", "offerSlug": "gta", "offerCoupon": "GTA60"},
        {"offerId": 2, "offerTitle": "Controle Sem Fio Playstation Dualsense", "offerPrice": 399, "storeName": "Amazon"}]}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script>'
    monkeypatch.setattr(promobit, "get_html", lambda url, **k: html)
    ofs, _ = promobit.PromobitCategoriaPS5().coletar()
    assert [(o.modelo, o.cupom) for o in ofs] == [("GTA6_CODE_IN_BOX", "GTA60")]


# ------------------------------------------------------------------------------------------------
# Telegram: busca por termo no @pelandobr
# ------------------------------------------------------------------------------------------------

def test_busca_por_termo_tira_o_destaque_e_a_postagem_de_streaming():
    ofs = {o.id: o for o in telegram_public.parse_canal(_fx(f"telegram_pelandobr_busca_gta_{D}.html"), "pelandobr")}
    # "Ganhe até 30 Dias Grátis de NETFLIX - Filmes, Séries, GTA VI" não é o GTA 6
    assert set(ofs) == {"pelandobr/95375#GTA6_CODE_IN_BOX", "pelandobr/92999#PS5_DIGITAL_GTA6"}
    o = ofs["pelandobr/95375#GTA6_CODE_IN_BOX"]
    assert (o.loja, o.preco) == ("Netshoes", 323.0)
    assert "  " not in o.titulo and "Theft Auto VI GTA 6" in o.titulo


def test_urls_de_busca_cobrem_os_produtos():
    urls = [u for _c, u in telegram_public.urls_de_busca()]
    assert config.TELEGRAM_CANAIS_BUSCA == ["pelandobr"]
    for termo in ("PS5", "PlayStation%205", "GTA", "Grand%20Theft%20Auto", "gift%20card%20PlayStation",
                  "leitor%20de%20disco", "65C6K", "55C6K"):
        assert f"https://t.me/s/pelandobr?q={termo}" in urls, termo


def test_telegram_coleta_a_busca_sem_repetir_a_mesma_postagem(monkeypatch):
    pagina = _fx(f"telegram_pelandobr_busca_gta_{D}.html")
    monkeypatch.setattr(config, "TELEGRAM_CANAIS_PUBLICOS", ["pelandobr"])
    pedidas = []
    monkeypatch.setattr(telegram_public, "get_html", lambda url, **k: pedidas.append(url) or pagina)
    ofs, _ = telegram_public.TelegramPublico().coletar()
    assert len(ofs) == len({o.chave for o in ofs}) == 2
    assert pedidas[0] == "https://t.me/s/pelandobr" and len(pedidas) == 1 + len(telegram_public.urls_de_busca())


def test_falha_na_busca_por_termo_nao_derruba_o_canal(monkeypatch):
    pagina = _fx(f"telegram_pelandobr_busca_gta_{D}.html")
    monkeypatch.setattr(config, "TELEGRAM_CANAIS_PUBLICOS", ["pelandobr"])

    def site(url, **k):
        if "?q=" in url:
            raise requests.ConnectionError("x")
        return pagina

    monkeypatch.setattr(telegram_public, "get_html", site)
    ofs, _ = telegram_public.TelegramPublico().coletar()
    assert len(ofs) == 2


# ------------------------------------------------------------------------------------------------
# Amazon (PC): PS5/GTA 6 pela página do GTA e pelas buscas, com o CEP da sessão
# ------------------------------------------------------------------------------------------------

DP_GTA = """<html><body><span id="productTitle">Grand Theft Auto VI - PlayStation 5</span>
<input type="hidden" id="merchantID" value="A1ZZFT5FULY4LN">
<div id="corePriceDisplay_desktop_feature_div"><span class="a-price"><span class="a-offscreen">R$418,40</span></span></div>
<div id="oneTimePaymentPrice_feature_div">à vista no Pix ou NuPay (7% off)</div>
<div id="best-offer-string-cc">ou R$ 449,90 em até 12x de R$ 37,51 sem juros</div>
<div id="availability">Este produto será lançado em 19/Novembro/2026.</div>
<span data-csa-c-content-id="DEXUnifiedCXPDM" data-csa-c-delivery-time="Segunda-feira, 16 de Novembro">Entrega GRÁTIS</span>
</body></html>"""


def test_amazon_busca_do_gta_e_dos_pacotes(hoje_03_10):
    por_asin = {o.extra["asin"]: o for o in amazon.parse_busca_produtos(_fx(f"amazon_busca_gta_{D}.html"))}
    # o pacote GTA + DualSense (jogo + acessório) e o suporte de controle ficam de fora
    assert set(por_asin) == {"B0H6KT2RWH", "B0H6LVH152"}
    g = por_asin["B0H6KT2RWH"]
    assert (g.modelo, g.preco_pix, g.parcelado, g.extra["entrega_texto"]) == (
        "GTA6_CODE_IN_BOX", 418.4, "12x R$ 37,49 sem juros", "seg., 16 de nov.")
    b = por_asin["B0H6LVH152"]
    assert (b.modelo, b.preco, b.preco_pix) == ("PS5_DIGITAL_GTA6", 4948.9, 4602.47)


def test_amazon_pagina_do_gta_le_o_prazo():
    o = amazon.parse_produto(DP_GTA, "B0H6KT2RWH", "GTA6_CODE_IN_BOX")
    assert (o.modelo, o.vendedor, o.preco, o.preco_pix) == ("GTA6_CODE_IN_BOX", "Amazon.com.br", 449.9, 418.4)
    assert o.extra["entrega_texto"] == "Segunda-feira, 16 de Novembro"
    # nas TVs nada muda: a página do GTA não é a da 55C6K
    assert amazon.parse_produto(DP_GTA, "B0H6KT2RWH", "55C6K") is None


def test_amazon_produtos_troca_o_cep_da_sessao_e_marca_o_prazo(monkeypatch, hoje_03_10, com_cep, capsys):
    cargas, avaliados = [], []

    def abrir(url, *a, **k):
        cargas.append(url)
        return (DP_GTA if "/dp/" in url else _fx(f"amazon_busca_gta_{D}.html")), "", []

    def avaliar(js, arg=None, perfil="default"):
        avaliados.append(arg)
        return {"ok": True, "mudou": True}

    monkeypatch.setattr(ps, "_abrir", abrir)
    monkeypatch.setattr(ps, "_avaliar", avaliar)
    ofs, _ = amazon.AmazonProdutos().coletar()
    assert avaliados == [{"cep": CEP_FALSO}]
    assert cargas[:2] == ["https://www.amazon.com.br/dp/B0H6KT2RWH"] * 2   # recarrega depois de trocar o CEP
    # o painel de ofertas (vendedor dos preços da busca) tem o próprio limite, config.AMAZON_MAX_PAINEIS_PRODUTOS
    assert len([u for u in cargas if "aodAjax" not in u]) <= config.AMAZON_MAX_CARGAS_PRODUTOS
    por_id = {o.id: o for o in ofs}
    g = por_id["B0H6KT2RWH-A1ZZFT5FULY4LN"]
    assert (g.extra["entrega_prevista"], g.extra["entrega_ate_lancamento"], g.extra["cep_referencia"]) == (
        "2026-11-16", True, False)
    assert "entrega_texto" not in g.extra and {o.fonte for o in ofs} == {"amazon.produtos"}
    assert not any(o.extra.get("asin") == "B0H6KT2RWH" and o.id != g.id for o in ofs)   # a busca não duplica
    _sem_cep_em(ofs, capsys.readouterr().out)


def test_amazon_produtos_sem_trocar_o_cep_e_prazo_aproximado(monkeypatch, hoje_03_10, com_cep):
    monkeypatch.setattr(ps, "_abrir", lambda url, *a, **k: ((DP_GTA if "/dp/" in url else ""), "", []))
    monkeypatch.setattr(ps, "_avaliar", lambda *a, **k: {"ok": False, "erro": "sem token"})
    ofs, _ = amazon.AmazonProdutos().coletar()
    (g,) = ofs
    assert g.extra["cep_referencia"] is True


def test_amazon_das_tvs_nao_abre_as_paginas_do_ps5(monkeypatch):
    # a fonte "amazon" continua só com as TVs (os testes de carga dela contam as páginas)
    monkeypatch.setattr(config, "ASINS_AMAZON", {})
    monkeypatch.setattr(ps, "_abrir", lambda *a, **k: pytest.fail("não deveria abrir nada"))
    assert amazon.Amazon().coletar() == ([], [])


# ------------------------------------------------------------------------------------------------
# Netshoes (PC): a busca e as APIs da loja de dentro da página
# ------------------------------------------------------------------------------------------------

def test_netshoes_busca_e_preco():
    api = _json(f"netshoes_api_{D}.json")
    cartoes = {c["codigo"]: c for c in netshoes.parse_busca(api["busca_html"])}
    assert set(cartoes) == {"D32-286W-014", "POE-0002-006", "HTW-026A-014", "D32-2868-014"}
    d = netshoes.oferta_do_preco(cartoes["D32-286W-014"], api["precos"]["D32-286W-014"])
    assert (d.modelo, d.vendedor, d.preco, d.preco_pix, d.parcelado) == (
        "PS5_DIGITAL", "Magalu Oficial", 4549.0, 4094.1, "10x R$ 454,90 sem juros")
    assert d.extra["vendedor_id"] == "29198" and confianca.classifica_por_lista(d, ())[0] == confianca.CONFIAVEL
    g = netshoes.oferta_do_preco(cartoes["POE-0002-006"], api["precos"]["POE-0002-006"])
    assert (g.modelo, g.preco, g.preco_pix, g.parcelado) == ("GTA6_CODE_IN_BOX", 449.9, 404.91, "6x R$ 74,98 sem juros")
    assert netshoes.oferta_do_preco(cartoes["HTW-026A-014"], api["precos"]["D32-286W-014"]) is None   # controle
    assert netshoes.oferta_do_preco(cartoes["D32-286W-014"], {"erro": 404}) is None


def test_netshoes_url_e_resposta_do_frete():
    api = _json(f"netshoes_api_{D}.json")
    c = {x["codigo"]: x for x in netshoes.parse_busca(api["busca_html"])}["POE-0002-006"]
    g = netshoes.oferta_do_preco(c, api["precos"]["POE-0002-006"])
    u = netshoes.url_frete(g, CEP_FALSO)
    assert u.startswith("/pdp-api/api/shipping/calculate?sku=POE-0002-006-01&preSale=false")
    assert "productType=Jogos%2Bpara%2BConsoles" in u and "sellerId=29198&skuPrice=54900&weight=90" in u
    assert u.endswith(f"&priceWithDiscounts=44990&zipCode={CEP_FALSO}")
    assert netshoes.data_do_frete(api["frete_gta"]) == "2026-11-30"


def test_netshoes_coleta_com_prazo_e_sem_o_cep_na_oferta(monkeypatch, tmp_path, com_cep, capsys):
    api = _json(f"netshoes_api_{D}.json")
    monkeypatch.setattr(netshoes, "MARCA_BLOQUEIO", tmp_path / "netshoes_bloqueado_em")
    monkeypatch.setattr(ps, "_abrir", lambda *a, **k: (api["busca_html"], "", []))
    chamadas = []

    def avaliar(js, arg=None, perfil="default"):
        chamadas.append(arg)
        if isinstance(arg, dict):
            return {c: api["precos"].get(c, {"erro": 404}) for c in arg["codigos"]}
        return api["frete_gta"]

    monkeypatch.setattr(ps, "_avaliar", avaliar)
    ofs, _ = netshoes.Netshoes().coletar()
    por = {o.modelo: o for o in ofs}
    assert set(por) == {"PS5_DIGITAL", "GTA6_CODE_IN_BOX"}
    g = por["GTA6_CODE_IN_BOX"]
    assert (g.extra["entrega_prevista"], g.extra["entrega_ate_lancamento"], g.extra["cep_referencia"]) == (
        "2026-11-30", False, False)
    assert chamadas[0]["uf"] == "SP" and "HTW-026A-014" not in chamadas[0]["codigos"]   # o controle não é consultado
    assert "D32-2878-014" in chamadas[0]["codigos"]   # o Pro do catálogo, mesmo fora da busca
    assert all("_frete" not in o.extra for o in ofs)
    _sem_cep_em(ofs, capsys.readouterr().out)


def test_netshoes_bloqueio_espera_2_horas(monkeypatch, tmp_path):
    from monitor.sources import Pular

    marca = tmp_path / "netshoes_bloqueado_em"
    monkeypatch.setattr(netshoes, "MARCA_BLOQUEIO", marca)
    monkeypatch.setattr(ps, "_abrir", lambda *a, **k: ("<html>Access Denied</html>", "Access Denied", []))
    f = netshoes.Netshoes()
    assert f.alerta_falha is False
    with pytest.raises(RuntimeError, match="bloqueou"):
        f.coletar()
    assert marca.exists()
    with pytest.raises(Pular):
        f.coletar()
    # bloqueio só na consulta de preço (403 em todas) também conta
    marca.unlink()
    api = _json(f"netshoes_api_{D}.json")
    monkeypatch.setattr(ps, "_abrir", lambda *a, **k: (api["busca_html"], "", []))
    monkeypatch.setattr(ps, "_avaliar", lambda js, arg=None, perfil="default": {c: {"erro": 403} for c in arg["codigos"]})
    with pytest.raises(RuntimeError, match="consulta de preço"):
        f.coletar()


# ------------------------------------------------------------------------------------------------
# Casas Bahia e Mercado Livre (PC): fontes próprias do PS5
# ------------------------------------------------------------------------------------------------

CB_PS5 = """<html><body><h1>Console PlayStation 5 Slim Digital 825GB SSD 1 Controle DualSense</h1>
<script type="application/ld+json">{"@type":"Product","name":"Console PlayStation 5 Slim Digital 825GB SSD 1 Controle DualSense",
"offers":{"@type":"Offer","price":4179.05,"availability":"https://schema.org/InStock"}}</script>
<script>window.__x={"ProductPrice":{"sellPrice":{"skuId":"1581976879","priceWithoutDiscount":4399.0,"sellerId":35072},
"paymentMethodDiscount":{"hasDiscount":true,"discountDescription":"5% de desconto no Pix","sellPriceWithDiscount":4179.05},
"installmentOptions":[]},"sellers":[{"id":35072,"name":"LOJA GAZIN","elected":true,"sellPrice":4399,"buyButtonEnabled":true}]}
</script></body></html>"""


def test_casas_bahia_ps5_vendido_pela_gazin(monkeypatch):
    cargas = []
    monkeypatch.setattr(ps, "_abrir", lambda url, *a, **k: cargas.append(url) or (
        CB_PS5 if "1581976879" in url else "<html><h1>Outro</h1></html>", "", []))
    ofs, _ = ps.CasasBahiaProdutos().coletar()
    (o,) = [x for x in ofs if x.ativo]   # as outras páginas falsas não têm preço: ficam inativas, sem preço
    assert (o.modelo, o.vendedor, o.preco, o.preco_pix, o.fonte) == (
        "PS5_DIGITAL", "LOJA GAZIN", 4399.0, 4179.05, "casasbahia.produtos")
    assert confianca.classifica_por_lista(o, ())[0] == confianca.CONFIAVEL
    assert len(cargas) <= config.CASASBAHIA_MAX_CARGAS_PRODUTOS
    assert all("/console-playstation-5/p/" in u for u in cargas)   # só /p/<sku> dá 404: vai um slug qualquer


def test_casas_bahia_ps5_nao_abre_depois_do_bloqueio(monkeypatch):
    from monitor.sources import Pular

    ps._marca_cb_bloqueada()
    monkeypatch.setattr(ps, "_abrir", lambda *a, **k: pytest.fail("não deveria abrir"))
    with pytest.raises(Pular):
        ps.CasasBahiaProdutos().coletar()


def test_ml_ps5_respeita_e_poe_o_castigo(monkeypatch, tmp_path):
    from monitor.sources import Pular

    marca = tmp_path / "ml_bloqueado_em"
    monkeypatch.setattr(ps, "MARCA_BLOQUEIO_ML", marca)
    monkeypatch.setattr(ps, "_dir_perfil", lambda perfil: tmp_path / f"perfil-{perfil}")
    monkeypatch.setattr(ps, "_abrir", lambda *a, **k: ("<html>suspicious-traffic</html>", "", []))
    f = ps.MercadoLivreProdutos()
    assert f.alerta_falha is False
    with pytest.raises(RuntimeError):
        f.coletar()
    assert marca.exists()
    with pytest.raises(Pular):
        f.coletar()


# ------------------------------------------------------------------------------------------------
# registro das fontes, workflow e confiança
# ------------------------------------------------------------------------------------------------

def test_fontes_novas_registradas_por_modo():
    from monitor import sources

    nuvem = {f.nome for f in sources.por_modo("cloud")}
    pc = {f.nome for f in sources.por_modo("pc")}
    assert {"maiscorreios", "americanas", "vtex.fastshop.ps5", "vtex.webcontinental.ps5", "kabum.produtos",
            "magalu.produtos", "carrefour", "psstore", "mercadolivre.playstation", "promobit.ps5"} <= nuvem
    assert {"netshoes", "amazon.produtos", "casasbahia.produtos", "mercadolivre.produtos"} <= pc
    # as de antes continuam (as TVs não mudaram de fonte)
    assert {"kabum", "magalu", "vtex.fastshop", "telegram.publico", "zoom"} <= nuvem
    assert {"amazon", "casasbahia", "mercadolivre", "pelando.busca"} <= pc
    todas = sources.todas()
    assert len({f.nome for f in todas}) == len(todas)


def test_workflow_passa_o_cep_so_pelo_secret():
    yml = (Path(__file__).parent.parent / ".github" / "workflows" / "monitor.yml").read_text(encoding="utf-8")
    assert "CEP_ENTREGA: ${{ secrets.CEP_ENTREGA }}" in yml
    assert 'cron: "*/15 * * * *"' in yml   # o agendamento continua o mesmo


def test_vendedores_novos_na_lista_de_confianca():
    casos = [
        Oferta("x", "loja", "Mais Correios", "PS5", "u", "1", vendedor="Webcontinental Marketplace"),
        Oferta("x", "loja", "Fast Shop", "PS5", "u", "2", vendedor="Webcontinental Marketplace"),
        Oferta("x", "loja", "Americanas", "TV", "u", "3", vendedor="Lojas Colombo SA"),
        Oferta("x", "loja", "Casas Bahia", "PS5", "u", "4", vendedor="LOJA GAZIN", extra={"vendedor_id": "35072"}),
    ]
    for o in casos:
        assert confianca.classifica_por_lista(o, ())[0] == confianca.CONFIAVEL, (o.loja, o.vendedor)


# ------------------------------------------------------------------------------------------------
# classificador: títulos reais vistos nas fontes novas em 03/10
# ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("titulo,loja,esperado", [
    ("PlayStation 5 Slim Disk 1TB + 1 Controle Sony", "Netshoes", "PS5_DISCO"),
    ("Console Sony Playstation 5 Standard 825gb E Leitor De Blue Ray", "KaBuM!", "PS5_DISCO"),
    ("Console de Playstation 5 Bundle 2 Digital CFI-2000B Sony 1TB SSD Kit Astro Bot Gran Turismo 7 Branco",
     "Mais Correios", "PS5_DIGITAL"),
    ("Jogo Gran Theft Auto VI - GTA 6 PlayStation 5", "Carrefour", "GTA6_CODE_IN_BOX"),
    ("Console Playstation®5 Slim Digital - Pacote Astro Bot E Gran Turismo 7 - Branco", "Mercado Livre", "PS5_DIGITAL"),
    ("Grand Theft Auto VI: Melhoria Ultimate Edition", "PlayStation Store", "GTA6_UPGRADE"),
    ("Sony PS5® Console - Two DualSense Wireless Controllers Bundle", "Amazon", "PS5_KIT"),
])
def test_classifica_titulos_das_fontes_novas(titulo, loja, esperado):
    assert produtos.classifica(titulo, loja).produto == esperado


@pytest.mark.parametrize("titulo", [
    "Sony Playstation 3 Super Slim 500gb Grand Theft Auto V Cor Charcoal Black",
    "Sony Playstation 4 Slim 1TB Extra Dualshock 4 Controller Cor Preto Onyx",
    "Console Playstation Slim",
    "[Selecionados] Ganhe até 30 Dias Grátis de NETFLIX - Filmes, Séries, GTA VI",
    "Sony PlayStation 5 Slim Digital Edition Console - 825GB - Middle East Version",
    "Jogo de Vídeo Game Take 2 Interactive Grand Theft Auto 5 para PS5",
    "Decoração Logo GTA VI para decorar quarto",
    "Cofrinho GTA VI Economize com estilo de jogador",
    "Cubierta de Reemplazo para Placas Frontales de la Edición PS5 Pro Disc",
    "Artefato de Resfriamento Eficiente com 3 Ventiladores e Porta USB Console PS5 Slim",
    "Bundle GTA VI PlayStation 5 + Controle sem fio PlayStation DualSense Techno Red",
    "Reprodutor Remoto Portal Sony Para Console Ps5 Black Preto",
])
def test_nunca_vira_produto_nas_fontes_novas(titulo):
    assert produtos.classifica(titulo).produto is None, produtos.classifica(titulo)
