"""TCL 65C6K monitorada junto com a 55C6K (pedido do usuário em 26/09/2026).

Cobre o contrato das duas frentes (campo `modelo` na Oferta, ids únicos por modelo, alvos por modelo, confiança
comparando com a loja confiável do MESMO modelo) e as armadilhas do levantamento de 26/09: id do Magalu pela variação (a
55" e a 65" do 1P colidiam em '240162800-magazineluiza'), tamanho pela variação e não pelo título (Importados Lili),
parcelado da VTEX só dos cartões ('APP Vendedor' 12x), discussão do Pelando (/t/) não é oferta, os dois anúncios da
KaBuM, SKU 55069453 da Casas Bahia, ASIN B0F7K7B2PD com o vendedor 1P pelo merchantID, catálogo MLB50368907 do ML e o
produto 13992309 do Zoom com slug próprio. Nenhum teste acessa a rede nem abre o Chrome.
"""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest
import requests

from monitor import config, confianca, filtro
from monitor.estado import CAMPOS_HISTORICO, Estado, chave_minimo
from monitor.models import Cupom, Oferta, modelo_de
from monitor.regras import (
    cupom_compativel, cupons_aplicaveis, gerar_alertas, mensagem_bootstrap, resumo_diario, sanear,
)
from monitor.sources import amazon, kabum, magalu, pelando, promobit, telegram_public, vtex, zoom
from monitor.sources import playwright_sources as ps
from monitor.util import agora, next_data

FX = Path(__file__).parent / "fixtures"
P1P = (FX / "magalu_produto_1p_2026-09-25.html").read_text(encoding="utf-8")
LILI65 = (FX / "magalu_produto_lili65_2026-09-25.html").read_text(encoding="utf-8")
AOD = (FX / "amazon_aod_2026-09-19.html").read_text(encoding="utf-8")
DP55 = (FX / "amazon_pix_2026-09-18.html").read_text(encoding="utf-8")

T65_MAGALU = 'Smart TV 65" TCL 4K UHD MiniLED 65C6K 120Hz Google TV AiPQ Google Assistente 4 HDMI 2 USB'
PATH65 = "smart-tv-65-tcl-4k-uhd-miniled-65c6k-120hz-google-tv-aipq-google-assistente-4-hdmi-2-usb/p/240162600/et/elit/"


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    """docs/data num diretório temporário e os alvos padrão (nada lê nem grava o repositório)."""
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    for k, v in (("ALVO_PIX", 2900.0), ("ALVO_PARCELADO", 3000.0), ("ALVO_PIX_65", 3300.0),
                 ("ALVO_PARCELADO_65", 3500.0), ("MAGALU_PAUSA_S", 0), ("VTEX_PAUSA_S", 0)):
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(config, "MAGALU_ANUNCIOS_EXTRA", [])
    return tmp_path


# ------------------------------------------------------------------------------------------------
# filtro: classificador 55C6K / 65C6K / nenhum
# ------------------------------------------------------------------------------------------------

TITULOS_65 = [
    T65_MAGALU,
    "Smart TV TCL 65C6K 65 4K Mini LED Android TV Semp Tcl",                # Colombo no Magalu (título errado, TV certa)
    "Smart TV C6K 65 Polegadas 4K 144 Hz QLED Mini LED TCL",                 # Leonfer: sem o código colado
    "Smart TV TCL C6K 65 Polegadas 4K QLED Mini LED Preto Bivolt",           # Webcontinental Marketplace
    "Smart Tv 65 65c6k 4k Qd-mini Led 144hz Com Google Tv Tcl",              # ML fora do catálogo
    "Tcl 4k Qd-mini Led Tv 65 C6k Google Tv",
    "TV 65C6K QLED 65'' Advanced 4K QD-Mini ... TCL",
    "Smart TV 4K TCL QD-Mini LED 65” Polegadas com HDMI 2.1, Dolby Vision IQ, Subwoofer, 144Hz VRR e Wi-Fi - 65C6K",
    'Smart TV TCL QLED 65" 4K Mini LED 144hz 65C6K',
    "[MAGALU] Smart TV 65\" TCL Mini LED 4K 120Hz C6K",
]
NAO_SAO_A_65 = [
    "Smart TV TCL 65C7K QD-Mini LED 4K",                                       # vizinhos
    "Smart TV TCL 65P7L 4K Google TV",
    "Smart TV TCL 65QM8K QD-Mini LED",
    "Smart TV TCL 65P8K C6K",
    "Smart TV TCL 65C755 QD-Mini LED",
    "Smart TV TCL 65C69K",
    "Smart TV TCL 65C6KS",
    "Smart TV TCL 75C6K 4K",
    "Controle comando de voz para tv tcl 55c6k 65c6k 55p8k 65p8k 75c6k 85c6k",  # acessório (Magalu fa14gj5k07)
    "Combo Smart TV TCL 65C6K e Soundbar TCL",                                   # combo da Casas Bahia
    "TV TCL C6K 55 e 65 polegadas",                                              # vários tamanhos
    "Smart TV 55 TCL 4K UHD MiniLED 55C6K 120Hz",                                # é a 55C6K
]


@pytest.mark.parametrize("titulo", TITULOS_65)
def test_titulos_da_65(titulo):
    assert filtro.modelo_do_titulo(titulo) == "65C6K"
    assert filtro.eh_65c6k(titulo) and not filtro.eh_55c6k(titulo)


@pytest.mark.parametrize("titulo", NAO_SAO_A_65)
def test_nao_sao_a_65(titulo):
    assert not filtro.eh_65c6k(titulo), filtro.motivo_rejeicao(titulo, "65C6K")


def test_par_55_65_fica_com_a_55():
    t = "Smart TV TCL 55C6K/65C6K QD-Mini LED (loja oficial)"
    assert filtro.eh_55c6k(t) and not filtro.eh_65c6k(t) and filtro.modelo_do_titulo(t) == "55C6K"


def test_titulo_de_tv_c6k_sem_olhar_o_tamanho():
    # o anúncio de 65" da Importados Lili tinha o título da 55": com a variação dizendo o tamanho, basta ser TV C6K
    assert filtro.eh_tv_c6k("Smart TV 55 TCL 4K UHD MiniLED 55C6K 120Hz Google TV AiPQ")
    assert not filtro.eh_tv_c6k("Controle remoto para TV TCL 55C6K")
    assert not filtro.eh_tv_c6k("Smart TV TCL 65C7K")


def _texto(*linhas: str) -> str:
    return "\n".join(linhas)


@pytest.mark.parametrize("texto,preco", [
    # grafias dos canais (o negrito quebra o título em linhas)
    (_texto("🔥 Smart Tv TCL", "65", '"', "C6K", "QD-Mini LED 4K 120Hz", "💰 R$ 3.999 no Pix"), 3999.0),
    (_texto("Smart TV TCL", "65", "Polegadas QLED Mini LED 4K", "C6K", "Por: R$3.463,00"), 3463.0),
    (_texto('Smart TV 65" TCL 4K UHD MiniLED', "65C6K", "120Hz Google TV", "💰 R$ 3.787,55 no Pix",
            "cupom DESCONTA100"), 3787.55),
])
def test_mensagem_livre_da_65(texto, preco):
    achados = filtro.extrai_modelos(texto)
    assert set(achados) == {"65C6K"}
    from monitor.util import PISO_PRECO_TV, preco_postagem
    assert preco_postagem(achados["65C6K"][1], PISO_PRECO_TV) == preco


def test_mensagem_com_as_duas_tvs_separa_os_precos():
    texto = _texto("Cupom da Amazon para TVs:", 'TCL C6K 55"', "R$ 2.999", "https://amzn.to/a",
                   'TCL C6K 65"', "R$ 3.999", "https://amzn.to/b")
    achados = filtro.extrai_modelos(texto)
    assert set(achados) == {"55C6K", "65C6K"}
    assert "2.999" in achados["55C6K"][1] and "3.999" not in achados["55C6K"][1]
    assert "3.999" in achados["65C6K"][1] and "2.999" not in achados["65C6K"][1]


def test_mensagem_do_par_nao_vira_65():
    assert set(filtro.extrai_modelos(_texto("Smart TV TCL 55C6K/65C6K", "A partir de R$ 2.999"))) == {"55C6K"}


# ------------------------------------------------------------------------------------------------
# Magalu: id pela variação, modelo pela variação/ficha
# ------------------------------------------------------------------------------------------------

def _produto(html: str) -> dict:
    return copy.deepcopy(next_data(html)["props"]["pageProps"]["data"]["product"])


def _html_produto(p: dict) -> str:
    nd = {"props": {"pageProps": {"data": {"product": p}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd, ensure_ascii=False)}</script>'


def _html_busca(prods: list[dict]) -> str:
    nd = {"props": {"pageProps": {"data": {"search": {"products": prods, "pagination": {"page": 1, "pages": 1}}}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd, ensure_ascii=False)}</script>'


def _pagina_1p_65() -> dict:
    """A página real do Magalu 1P (25/09), na variação de 65" (240162600), com os preços do levantamento de 26/09."""
    p = _produto(P1P)
    p["variationId"] = "240162600"
    p["title"] = T65_MAGALU
    p["path"] = "/magazinecanaltechbr/" + PATH65
    p["price"] = dict(p["price"], fullPrice="4799.00", bestPrice="4559.05", price="4899.00")
    p["installment"] = dict(p["installment"], amount="479.90", totalAmount="4799.00")
    p["attributes"] = [dict(p["attributes"][0], value='65"', current='65"')]
    for secao in p["factsheet"]:
        for e in secao.get("elements") or []:
            if e.get("keyName") in ("Polegadas", "Modelo", "Referência"):
                e["elements"][0]["value"] = '65"' if e["keyName"] == "Polegadas" else "65C6K"
    return p


def test_magalu_55_e_65_do_mesmo_grupo_nao_colidem():
    (o55,), c55, var55 = magalu.parse_produto_todas(P1P)
    (o65,), c65, _var65 = magalu.parse_produto_todas(_html_produto(_pagina_1p_65()))
    assert (o55.id, o55.modelo, o55.preco_pix) == ("240162700-magazineluiza", "55C6K", 3894.05)
    assert (o65.id, o65.modelo, o65.preco, o65.preco_pix) == ("240162600-magazineluiza", "65C6K", 4799.0, 4559.05)
    assert o65.parcelado == "10x R$ 479,90 sem juros" and o65.extra["anuncio"] == "240162600"
    # a página da 55" lista a da 65" (reaproveitada na fila de visita, sem busca extra)
    assert any("/p/240162600/" in v for v in var55)
    # o cupom do anúncio leva o modelo da página (o da 65" com o modelo no id)
    assert [(c.codigo, c.modelo, c.id) for c in c55] == [("LU300", "55C6K", "LU300-2026-09-30")]
    assert [(c.codigo, c.modelo, c.id) for c in c65] == [("LU300", "65C6K", "LU300-2026-09-30-65C6K")]


def test_magalu_tamanho_pela_variacao_e_nao_pelo_titulo():
    (o,) = magalu.parse_produto_todas(LILI65)[0]
    assert "55C6K" in o.titulo and o.modelo == "65C6K" and o.id == "kd12g2e47k-importadoslili"
    assert confianca.motivo_bloqueio(o, ())  # a lista curada barra o vendedor nas duas medidas


def test_magalu_tamanho_pela_ficha_quando_nao_ha_variacao():
    p = _produto(P1P)
    p["variations"], p["attributes"] = [], []
    for secao in p["factsheet"]:
        for e in secao.get("elements") or []:
            if e.get("keyName") == "Polegadas":
                e["elements"][0]["value"] = '65"'
    (o,) = magalu.parse_produto_todas(_html_produto(p))[0]
    assert "55C6K" in o.titulo and o.modelo == "65C6K"


def test_magalu_busca_da_65_e_controle_de_fora():
    p = _pagina_1p_65()
    for k in ("variations", "attributes", "factsheet"):
        p.pop(k)  # a busca não traz variações nem ficha: o título decide
    controle = {"id": "fa14gj5k07", "variationId": "fa14gj5k07", "available": True,
                "title": "Controle comando de voz para tv tcl 55c6k 65c6k 55p8k 65p8k 75c6k",
                "path": "/magazinecanaltechbr/controle/p/fa14gj5k07/", "price": {"bestPrice": "149.99"},
                "seller": {"id": "lfacomercial"}}
    ofs = magalu.parse_busca(_html_busca([p, controle]))
    assert [(o.id, o.modelo) for o in ofs] == [("240162600-magazineluiza", "65C6K")]


class _Site:
    def __init__(self, paginas: dict[str, str]):
        self.paginas, self.pedidas = paginas, []

    def __call__(self, url, **kw):
        self.pedidas.append(url)
        for trecho, html in self.paginas.items():
            if trecho in url:
                return html
        resp = requests.Response()
        resp.status_code = 404
        raise requests.HTTPError("404", response=resp)


def test_magalu_coleta_as_duas_tvs_no_mesmo_orcamento(monkeypatch):
    p65 = _pagina_1p_65()
    colombo65 = {"id": "jcefd125c3", "variationId": "jcefd125c3", "available": True,
                 "title": "Smart TV TCL 65C6K 65 4K Mini LED Android TV Semp Tcl",
                 "path": "/magazinecanaltechbr/smart-tv-tcl-65c6k-65-4k/p/jcefd125c3/et/elit/",
                 "price": {"fullPrice": "5274.90", "bestPrice": "4747.41", "price": "5274.90"},
                 "installment": {"quantity": 10, "amount": "527.49", "interest": "0.00"},
                 "seller": {"id": "lojascolombooficial", "description": "Lojas Colombo Oficial", "category": "3p"}}
    site = _Site({"/busca/tcl+65c6k/": _html_busca([colombo65]), "/busca/": _html_busca([]),
                  "/p/240162600/": _html_produto(p65), "/p/240162700/": P1P})
    monkeypatch.setattr(magalu, "get_html", site)
    ofertas, cupons = magalu.Magalu().coletar()
    por_id = {o.id: o.modelo for o in ofertas}
    assert por_id == {"240162700-magazineluiza": "55C6K", "240162600-magazineluiza": "65C6K",
                      "jcefd125c3-lojascolombooficial": "65C6K"}
    assert len(site.pedidas) <= config.MAGALU_MAX_REQUISICOES
    assert sum("/busca/" in u for u in site.pedidas) == len(config.MAGALU_TERMOS)
    # a página da 65" é a 2ª visita (logo depois do 1P da 55"), antes de qualquer anúncio da busca
    paginas = [u for u in site.pedidas if "/busca/" not in u]
    assert "/p/240162700/" in paginas[0] and "/p/240162600/" in paginas[1]
    # o LU300 aparece nas duas páginas: é um cupom só, que vale para as duas TVs
    (lu,) = [c for c in cupons if c.codigo == "LU300"]
    assert lu.modelo is None


# ------------------------------------------------------------------------------------------------
# Amazon: ASIN da 65", vendedor 1P pelo merchantID
# ------------------------------------------------------------------------------------------------

ASIN65 = "B0F7K7B2PD"
T65_AMAZON = "TCL Smart TV 65 Polegadas QD-Mini LED 4K UHD Google TV 65C6K"


def _dp_65(com_preco: bool = True) -> str:
    preco = ('<div id="corePriceDisplay_desktop_feature_div"><span class="a-price"><span class="a-offscreen">'
             "R$ 4.219,07</span></span></div>"
             '<div id="oneTimePaymentPrice_feature_div">à vista no Pix ou NuPay (8% off)</div>'
             '<div id="best-offer-string-cc">ou R$ 4.624,22 em até 12x de R$ 385,37 sem juros</div>') if com_preco else ""
    return (f'<html><span id="productTitle">{T65_AMAZON}</span>{preco}'
            '<div id="availability">Em estoque</div><input type="hidden" id="merchantID" name="merchantID" '
            'value="A1ZZFT5FULY4LN"></html>')


def _aod_65() -> str:
    return (f'<div id="aod-asin-title"><h5 id="aod-asin-title-text">{T65_AMAZON}</h5></div>'
            '<div id="aod-pinned-offer"><div id="aod-offer-heading"><h5>Novo</h5></div>'
            '<div id="aod-offer-price"><span class="a-price"><span class="a-offscreen">R$ 4.219,07</span></span>'
            '<span>à vista no Pix</span></div>'
            '<div id="aod-offer-soldBy"><span>Vendido por</span> <span>Amazon.com.br</span></div></div>'
            '<div id="aod-offer"><div id="aod-offer-heading"><h5>Novo</h5></div>'
            '<div id="aod-offer-price"><span class="a-price"><span class="a-offscreen">R$ 4.331,09</span></span></div>'
            '<div id="aod-offer-soldBy"><a href="/gp/aag/main?seller=ACUNARZFR75ET">Magalu.</a></div></div>')


def test_amazon_bloco_da_propria_amazon_sem_link_ganha_o_id_do_merchantid():
    por_id = {o.id: o for o in amazon.parse_ofertas(_aod_65(), ASIN65)}
    assert set(por_id) == {f"{ASIN65}-A1ZZFT5FULY4LN", f"{ASIN65}-ACUNARZFR75ET"}
    am = por_id[f"{ASIN65}-A1ZZFT5FULY4LN"]
    assert am.modelo == "65C6K" and am.extra["vendedor_id"] == "A1ZZFT5FULY4LN" and am.preco_pix == 4219.07
    assert confianca.classifica_por_lista(am, ())[0] == confianca.CONFIAVEL


def test_amazon_painel_de_outro_modelo_e_ignorado():
    assert amazon.parse_ofertas(AOD, ASIN65) == []  # o painel real da 55" servido para o ASIN da 65"


def test_amazon_coleta_por_modelo(monkeypatch):
    cargas = []

    def http(url, **kw):
        cargas.append(("http", url))
        return DP55 if "B0F7JZMVKF" in url else _dp_65(com_preco=False)   # a dp da 65" por HTTP vem sem preço

    def abrir(url, *a, **k):
        cargas.append(("chrome", url))
        if "aodAjaxMain" in url:
            return (AOD if "B0F7JZMVKF" in url else _aod_65()), "", []
        if "/dp/" + ASIN65 in url:
            return _dp_65(), "", []
        return "<html></html>", "", []

    monkeypatch.setattr(amazon, "get_html", http)
    monkeypatch.setattr(ps, "_abrir", abrir)
    ofertas, _ = amazon.Amazon().coletar()
    por_id = {o.id: o for o in ofertas}
    am = por_id[f"{ASIN65}-A1ZZFT5FULY4LN"]
    assert (am.modelo, am.preco, am.preco_pix, am.parcelado) == ("65C6K", 4624.22, 4219.07, "12x R$ 385,37 sem juros")
    assert am.vendedor == "Amazon.com.br" and am.url.endswith("?smid=A1ZZFT5FULY4LN")
    assert por_id[f"{ASIN65}-ACUNARZFR75ET"].modelo == "65C6K"
    # a 55" continua igual (o destaque Magalu. com os dados da página)
    assert por_id["B0F7JZMVKF-ACUNARZFR75ET"].modelo == "55C6K" and por_id["B0F7JZMVKF-ACUNARZFR75ET"].preco == 3749.0
    assert sum(1 for _k, u in cargas if ASIN65 in u) <= config.AMAZON_MAX_CARGAS


# ------------------------------------------------------------------------------------------------
# Casas Bahia (SKU 55069453), Mercado Livre (catálogo MLB50368907), AliExpress
# ------------------------------------------------------------------------------------------------

T65_CB = "Smart TV 65” TCL 65C6K 4K QD-Mini LED 144Hz com Sistema Operacional Google TV"
T55_CB = "Smart TV 55” TCL 55C6K 4K QD-Mini Led 144Hz Sistema Operacional Google TV"


def _pagina_cb(sku: str, titulo: str, pix: float, cartao: float) -> str:
    ld = {"@context": "https://schema.org", "@type": "Product", "name": titulo,
          "offers": [{"@type": "Offer", "availability": "https://schema.org/InStock", "price": pix,
                      "seller": {"@type": "Organization", "name": "Casas Bahia"}}]}
    pp = {"sellPrice": {"skuId": int(sku), "sellerId": 10037, "priceWithoutDiscount": cartao, "priceValue": pix},
          "paymentMethodDiscount": {"hasDiscount": True, "discountDescription": "No Pix", "sellPriceWithDiscount": pix},
          "installmentOptions": [
              {"type": "Bandeira", "conditions": [{"option": "12x sem juros", "price": int(cartao / 12 * 100) / 100,
                                                   "qtyParcels": 12, "monthlyInterest": 0}]},
              {"type": "Outros", "conditions": [{"option": "12x com juros (2,99% a.m.)", "price": 470.67,
                                                 "qtyParcels": 12, "monthlyInterest": 2.99}]}]}
    vend = '"sellers":[{"id":10037,"name":"Casas Bahia","elected":true,"sellPrice":%s,"buyButtonEnabled":true}]' % cartao
    return (f'<html><head><script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script></head>'
            f"<body><h1>{titulo}</h1><script>self.__next_f.push({{\"ProductPrice\":{json.dumps(pp)},"
            f"\"BuyBox\":{{{vend}}}}})</script></body></html>")


def test_casasbahia_coleta_o_sku_da_65(monkeypatch):
    paginas = {"/p/55069456": _pagina_cb("55069456", T55_CB, 3599.09, 3998.99),
               "/p/55069453": _pagina_cb("55069453", T65_CB, 4219.08, 4687.87)}
    chamadas = []

    def abrir(url, *a, **k):
        chamadas.append(url)
        for trecho, html in paginas.items():
            if trecho in url:
                return html, "", []
        return "<html></html>", "", []   # buscas vazias

    monkeypatch.setattr(ps, "_abrir", abrir)
    ofertas, _ = ps.CasasBahia().coletar()
    por_id = {o.id: o for o in ofertas}
    o65 = por_id["55069453-10037"]
    assert (o65.modelo, o65.preco, o65.preco_pix) == ("65C6K", 4687.87, 4219.08)
    assert o65.parcelado == "12x R$ 390,65 sem juros (cartão Casas Bahia)"
    assert por_id["55069456-10037"].modelo == "55C6K"
    assert len(chamadas) <= config.CASASBAHIA_MAX_CARGAS
    # a página da 55" servida no lugar da 65" (redirecionamento) não vira preço da 65"
    assert ps.CasasBahia._do_produto(paginas["/p/55069456"], "", "u", "55069453", "65C6K") == []
    # o EAN do JSON-LD é o da 55C6K: o título dizendo 65" não basta
    com_ean = paginas["/p/55069453"].replace('"@type": "Product",', '"@type": "Product", "gtin13": "7899968301747",')
    assert '"gtin13"' in com_ean
    assert ps._oferta_jsonld(com_ean, "casasbahia", "Casas Bahia", "u", "55069453", "65C6K") is None
    assert ps._oferta_jsonld(paginas["/p/55069453"], "casasbahia", "Casas Bahia", "u", "55069453", "65C6K")


T65_ML = "Smart TV TCL 65 Polegadas QLED Mini LED 4K C6K Wifi Bluetooth Google TV 4 HDMI 144Hz HDR10+ 65C6K"
T55_ML = "Smart Tv Tcl 55 Polegadas Qd-Mini Led 4k C6k Wifi Bluetooth Google Tv 4 Hdmi 144hz Hdr10+ 55c6k"


def _catalogo_ml(titulo: str, preco: float) -> tuple[str, str]:
    ld = {"@context": "https://schema.org", "@type": "Product", "name": titulo,
          "offers": {"@type": "Offer", "price": preco, "availability": "https://schema.org/InStock"}}
    html = f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body><h1>{titulo}</h1></body></html>'
    return html, f"{titulo}\nR$ {preco:.0f}\n"


def test_mercadolivre_catalogo_da_65(monkeypatch, tmp_path):
    monkeypatch.setattr(ps, "MARCA_BLOQUEIO_ML", tmp_path / "ml_bloqueado_em")
    paginas = {"/p/MLB48808732": _catalogo_ml(T55_ML, 3749.0), "/p/MLB50368907": _catalogo_ml(T65_ML, 4299.0)}
    chamadas = []

    def abrir(url, *a, **k):
        chamadas.append(url)
        for trecho, (html, texto) in paginas.items():
            if trecho in url:
                return html, texto, []
        return "<html></html>", "", []

    monkeypatch.setattr(ps, "_abrir", abrir)
    ofertas, _ = ps.MercadoLivre().coletar()
    por_modelo = {o.modelo: o for o in ofertas}
    assert por_modelo["65C6K"].preco == 4299.0 and por_modelo["65C6K"].extra["catalogo"] == "MLB50368907"
    assert por_modelo["55C6K"].extra["catalogo"] == "MLB48808732"
    assert len(chamadas) <= config.ML_MAX_CARGAS
    # a ordem: catálogo e busca da 55", depois catálogo e busca da 65"
    assert "MLB48808732" in chamadas[0] and "MLB50368907" in chamadas[2]


def test_mercadolivre_bloqueio_na_65_guarda_a_55_e_para(monkeypatch, tmp_path):
    marca = tmp_path / "ml_bloqueado_em"
    monkeypatch.setattr(ps, "MARCA_BLOQUEIO_ML", marca)
    monkeypatch.setattr(ps, "_dir_perfil", lambda perfil: tmp_path / f"perfil-{perfil}")  # nunca o perfil de verdade
    bloqueio = ('<html>suspicious-traffic</html>', "Para continuar, acesse")
    paginas = {"/p/MLB48808732": _catalogo_ml(T55_ML, 3749.0), "tcl-55c6k": ("<html></html>", ""),
               "/p/MLB50368907": bloqueio, "tcl-65c6k": bloqueio}
    chamadas = []

    def abrir(url, *a, **k):
        chamadas.append(url)
        for trecho, (html, texto) in paginas.items():
            if trecho in url:
                return html, texto, []
        raise AssertionError(url)

    monkeypatch.setattr(ps, "_abrir", abrir)
    ofertas, _ = ps.MercadoLivre().coletar()
    assert [o.modelo for o in ofertas] == ["55C6K"]
    assert marca.exists(), "o perfil foi marcado: a próxima tentativa é em 2 h"


def test_aliexpress_busca_da_65(monkeypatch):
    card = ('<a class="search-card-item" href="//pt.aliexpress.com/item/1005009036343124.html?algo=1">'
            f"<div><h3>Smart TV 65\" TCL 4K UHD MiniLED 65C6K 120Hz Google TV AiPQ</h3></div>"
            "<div><span>R$</span><span>4</span><span>.</span><span>659</span></div><del>R$4.899</del></a>")
    card55 = card.replace("1005009036343124", "1005009459962683").replace("65\"", "55\"").replace("65C6K", "55C6K") \
        .replace("659", "199")
    monkeypatch.setattr(ps, "_abrir", lambda url, *a, **k: ((card if "65c6k" in url else card55), "", []))
    ofertas, _ = ps.AliExpress().coletar()
    por_id = {o.id: (o.modelo, o.preco) for o in ofertas}
    assert por_id == {"1005009036343124": ("65C6K", 4659.0), "1005009459962683": ("55C6K", 4199.0)}


# ------------------------------------------------------------------------------------------------
# KaBuM (911480, 938060), VTEX (EAN, parcelado dos cartões), Zoom (13992309)
# ------------------------------------------------------------------------------------------------

def _kabum(pid: int, titulo: str, preco: float, vendedor: str) -> dict:
    return {"id": pid, "attributes": {"title": titulo, "price": preco, "price_with_discount": preco, "available": True,
                                      "max_installment": f"10x de R$ {preco / 10:.2f}".replace(".", ","),
                                      "is_marketplace": True, "marketplace": {"seller_name": vendedor}}}


def test_kabum_os_dois_anuncios_da_65_e_o_vizinho(monkeypatch):
    t65 = 'Smart TV  65" TCL 4K UHD MiniLED 65C6K 120Hz Google TV'
    respostas = {"911482": _kabum(911482, "Smart TV TCL 55 Polegadas QD-Mini LED 4K C6K 55C6K", 3699.0, "LOJAS COLOMBO"),
                 "911480": _kabum(911480, "Smart TV TCL 65C6K 65 4K Mini LED", 4736.0, "LOJAS COLOMBO"),
                 "938060": _kabum(938060, t65, 4799.0, "Magalu")}
    monkeypatch.setattr(kabum, "get_json", lambda url, **k: respostas[url.rsplit("/", 1)[1]])
    ofertas, _ = kabum.KaBuM().coletar()
    assert {(o.id, o.modelo, o.url) for o in ofertas} == {
        ("911482", "55C6K", "https://www.kabum.com.br/produto/911482"),
        ("911480", "65C6K", "https://www.kabum.com.br/produto/911480"),
        ("938060", "65C6K", "https://www.kabum.com.br/produto/938060")}
    # 938062 é a 65C7K do mesmo vendedor: não é a 65C6K
    assert kabum.parse_api(_kabum(938062, "Smart TV 65\" TCL 65C7K QD-Mini LED", 5299.0, "Magalu"), "65C6K") is None


def _vtex_produto(pid: str, nome: str, ean: str, preco: float, pix: float, vendedor: str, seller_id: str) -> dict:
    inst = [{"PaymentSystemName": "Visa", "NumberOfInstallments": n, "Value": round(preco / n, 2), "InterestRate": 0}
            for n in (1, 8)]
    inst += [{"PaymentSystemName": "Visa", "NumberOfInstallments": 10, "Value": 468.0, "InterestRate": 1.99},
             {"PaymentSystemName": "Pix", "NumberOfInstallments": 1, "Value": pix, "InterestRate": 0}]
    inst += [{"PaymentSystemName": "Outros Pagamentos APP Vendedor (12x - s/ juros)", "NumberOfInstallments": n,
              "Value": round(preco / n, 2), "InterestRate": 0} for n in (1, 12)]
    of = {"Price": preco, "ListPrice": 4499.0, "AvailableQuantity": 10, "Teasers": [], "DiscountHighLight": [],
          "Installments": inst}
    return {"productId": pid, "productName": nome, "link": f"https://www.webcontinental.com.br/{pid}/p",
            "productReference": ean, "items": [{"ean": ean, "sellers": [
                {"sellerId": seller_id, "sellerName": vendedor, "commertialOffer": of}]}]}


def test_vtex_65_pelo_ean_e_parcelado_dos_cartoes():
    dados = [_vtex_produto("4806999", "Smart TV 65 TCL 65C6K 4K QD-Mini Led 144Hz", "7899968301754", 4274.05, 3963.60,
                           "Casas Bahia", "003731"),
             # título com a medida errada, mas o EAN é o da 65C6K
             _vtex_produto("5364479", "Smart TV TCL C6K 55 Polegadas Mini LED", "7899968301754", 5059.61, 4844.31,
                           "Lojas Colombo SA", "003082"),
             _vtex_produto("9", "Combo Smart TV TCL 65C6K e Soundbar", "7899968301754", 7299.0, 7299.0, "X", "1")]
    ofs = vtex.parse_catalogo(dados, "Webcontinental", config.LOJAS_VTEX["Webcontinental"], "65C6K")
    por_id = {o.id: o for o in ofs}
    assert set(por_id) == {"Webcontinental-4806999-003731", "Webcontinental-5364479-003082"}
    cb = por_id["Webcontinental-4806999-003731"]
    assert (cb.modelo, cb.preco, cb.preco_pix) == ("65C6K", 4274.05, 3963.6)
    # 8x sem juros no cartão (o 12x sem juros do "APP Vendedor" não é cartão; o 10x do cartão é com juros)
    assert cb.parcelado == "8x R$ 534,26 sem juros"
    assert por_id["Webcontinental-5364479-003082"].modelo == "65C6K"
    # a busca da 55" não pega a 65"
    assert vtex.parse_catalogo(dados, "Webcontinental", config.LOJAS_VTEX["Webcontinental"], "55C6K") == []


def test_vtex_coleta_uma_busca_por_modelo(monkeypatch):
    pedidas = []

    def get_json(url, **k):
        pedidas.append(url)
        if url.endswith("ft=65c6k"):
            return [_vtex_produto("136904", "Smart TV 65” TCL 65C6K 4K QD-Mini LED", "7899968301754", 4687.87, 4687.87,
                                  "Ponto", "cnl222")]
        return json.loads((FX / "fastshop_vtex.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(vtex, "get_json", get_json)
    ofertas, _ = vtex.Vtex("Fast Shop").coletar()
    assert [u.rsplit("=", 1)[1] for u in pedidas] == ["55c6k", "65c6k"]
    assert {o.modelo for o in ofertas} == {"55C6K", "65C6K"}


def _zoom_html(nome: str, oid: str, loja: str, preco: float) -> str:
    ld = {"@context": "https://schema.org", "@type": "Product", "name": nome,
          "offers": {"@type": "AggregateOffer", "offers": [{"@type": "Offer", "id": oid, "price": preco,
                                                             "offeredBy": loja, "url": f"https://www.zoom.com.br/x?{oid}"}]}}
    return f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'


def test_zoom_pagina_da_65_com_slug_proprio(monkeypatch, capsys):
    assert config.URL_ZOOM_65.endswith("/smart-tv-qd-mini-led-65-tcl-4k-65c6k")
    paginas = {config.URL_ZOOM: _zoom_html("Smart TV 55 TCL 55C6K", "1", "Magazine Luiza", 3894.05),
               config.URL_ZOOM_65: _zoom_html("Smart TV 65 TCL 65C6K", "2", "Webcontinental", 3963.60)}
    monkeypatch.setattr(zoom, "get_html", lambda url, **k: paginas[url])
    ofertas, _ = zoom.Zoom().coletar()
    assert {(o.id, o.modelo, o.extra["agregador"]) for o in ofertas} == {("1", "55C6K", True), ("2", "65C6K", True)}
    # a página de busca (slug errado) vem sem ofertas: vai para o log, não passa em silêncio
    paginas[config.URL_ZOOM_65] = "<html><link rel=canonical href='/tv?q=65c6k'></html>"
    ofertas, _ = zoom.Zoom().coletar()
    assert {o.modelo for o in ofertas} == {"55C6K"} and "sem ofertas" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------
# Promobit, Pelando (discussão /t/ não é oferta), Telegram (duas TVs na mesma mensagem)
# ------------------------------------------------------------------------------------------------

def test_promobit_postagem_da_65():
    item = {"offer_id": 3051199, "offer_title": "Smart TV 4K TCL QD-Mini LED 65 Polegadas com HDMI 2.1 - 65C6K",
            "offer_slug": "tv-65", "offer_price": 3787.55, "store_name": "Magazine Luiza", "offer_status_name": "APPROVED"}
    o = promobit._oferta_de_item(item, True)
    assert (o.modelo, o.id, o.preco) == ("65C6K", "3051199", 3787.55)


def test_pelando_discussao_nao_e_oferta():
    def card(href, did, titulo):
        return (f'<li><h3><a href="{href}" data-deal-id="{did}">{titulo}</a></h3>'
                '<div class="deal-card-stamp">R$ 3.999</div></li>')
    html = "<ul>" + card("https://www.pelando.com.br/t/65c6k-por-r3999-em-15x", "t1",
                         "65c6k por R$3.999 em 15x sem juros é bom negócio?") \
        + card("https://www.pelando.com.br/d/smart-tv-65-tcl-65c6k-abcd", "d1", 'Smart TV 65" TCL 65C6K') + "</ul>"
    ofs = pelando.parse_busca(html)
    assert [(o.id, o.modelo) for o in ofs] == [("d1", "65C6K")]


def _canal(*linhas: str) -> str:
    return ('<div class="tgme_widget_message" data-post="canal/7"><div class="tgme_widget_message_text">'
            + "<br>".join(linhas) + '</div><time datetime="2026-09-26T10:00:00+00:00"></time></div>')


def test_telegram_mensagem_com_as_duas_tvs_vira_duas_postagens():
    ofs = telegram_public.parse_canal(_canal("🔥 TVs TCL na Amazon", "Smart TV TCL 55C6K", "R$ 3.499 no Pix",
                                             "Smart TV TCL 65C6K", "R$ 4.199 no Pix"), "canal")
    assert {(o.id, o.modelo, o.preco) for o in ofs} == {("canal/7", "55C6K", 3499.0), ("canal/7#65C6K", "65C6K", 4199.0)}
    assert len({o.chave for o in ofs}) == 2


# ------------------------------------------------------------------------------------------------
# estado e alertas: alvo, mínimo, partida e histórico por modelo
# ------------------------------------------------------------------------------------------------

def _loja(preco, pix=None, modelo="65C6K", oid=None, loja="Magazine Luiza", vendedor="Magalu", fonte="magalu",
          parcelado=None, confiavel=True):
    extra = {"confianca": {"veredito": "confiavel"}} if confiavel else {}
    return Oferta(fonte, "loja", loja, f"Smart TV TCL {modelo}", f"https://loja.example/{oid or preco}",
                  oid or f"{modelo}-{preco}", preco=preco, preco_pix=pix, vendedor=vendedor, parcelado=parcelado,
                  extra=extra, modelo=modelo)


def _state(pasta: Path, modo: str = "cloud", **kw) -> None:
    st = {"ofertas": {}, "cupons": {}, "minimo": None, "saude": {}, "criado_em": "2026-09-13T15:00:00-03:00",
          "cupons_alertados": {}, **kw}
    (pasta / f"state_{modo}.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def _reg(o: Oferta) -> dict:
    return {**o.to_dict(), "primeira_vez": "2026-09-20T10:00:00-03:00", "ultima_vez": "2026-09-26T10:00:00-03:00",
            "ultimo_preco": o.melhor_preco, "menor_preco": o.melhor_preco, "preco_alertado": None}


def test_alvo_da_65_e_nao_o_da_55(dados):
    antigo = _loja(4799.0, 4559.05, oid="p65")
    _state(dados, ofertas={f"magalu:{antigo.id}": _reg(antigo)}, modelos_iniciados=["55C6K", "65C6K"])
    est = Estado("cloud")
    # 3.250 na 65": abaixo do alvo dela (3.300); na 55" o mesmo preço não é alvo (2.900)
    msgs, alertados = gerar_alertas(est, [_loja(3450.0, 3250.0, oid="p65"), _loja(3450.0, 3250.0, modelo="55C6K",
                                                                                 oid="p55")], [])
    cab = [m.split("\n")[0] for m in msgs]
    (c65,) = [c for c in cab if "65C6K" in c]
    assert "🎯 Abaixo do alvo" in c65 and "TCL 65C6K" in c65 and "🔻" in c65
    assert not any("🎯" in c for c in cab if "55C6K" in c)
    assert alertados == {"magalu:p65": 3250.0}


def test_minimo_por_modelo(dados):
    _state(dados, minimo={"preco": 2991.6, "loja": "Magazine Luiza", "quando": "2026-09-14T21:04:38-03:00"},
           modelos_iniciados=["55C6K", "65C6K"])
    est = Estado("cloud")
    assert est.atualiza_minimo(_loja(4799.0, 4559.05), set()) is False       # o primeiro da 65" não é "novo mínimo"
    assert est.minimo("65C6K")["preco"] == 4559.05 and est.minimo()["preco"] == 2991.6
    assert est.dados[chave_minimo("65C6K")]["modelo"] == "65C6K"
    assert est.atualiza_minimo(_loja(4274.05, 3963.60, oid="webc", loja="Webcontinental", fonte="vtex"), set())
    assert est.minimo_geral(set(), "65C6K")["preco"] == 3963.6
    assert est.minimo_geral(set())["preco"] == 2991.6
    # o outro modo lê o mínimo da 65" do latest (chave própria)
    est.escreve_latest([], [])
    lt = json.loads((dados / "latest_cloud.json").read_text(encoding="utf-8"))
    assert lt["minimo_65C6K"]["preco"] == 3963.6 and lt["minimo"]["preco"] == 2991.6
    assert lt["alvos"] == {"55C6K": {"pix": 2900.0, "parcelado": 3000.0}, "65C6K": {"pix": 3300.0, "parcelado": 3500.0}}
    assert Estado("pc").minimo_geral(set(), "65C6K")["preco"] == 3963.6


def test_novo_minimo_da_65_nao_compara_com_a_55(dados):
    reg = _reg(_loja(4799.0, 4559.05, oid="p65"))
    _state(dados, ofertas={"magalu:p65": reg}, minimo={"preco": 2991.6, "loja": "Magazine Luiza", "quando": "x"},
           minimo_65C6K={"preco": 4559.05, "loja": "Magazine Luiza", "quando": "x", "modelo": "65C6K"},
           modelos_iniciados=["55C6K", "65C6K"])
    msgs, _ = gerar_alertas(Estado("cloud"), [_loja(4599.0, 4369.05, oid="p65")], [])
    assert any("🏆 MENOR PREÇO já visto" in m.split("\n")[0] and "65C6K" in m.split("\n")[0] for m in msgs)


def test_partida_da_65_num_state_que_ja_existia(dados):
    """A 65" entra num state só com a 55": a primeira rodada dela registra ofertas e postagens sem alerta (as postagens
    antigas da 65" virariam uma enxurrada de 📣); na seguinte, a postagem nova sai com o modelo."""
    o55 = _loja(3749.0, 3561.55, modelo="55C6K", oid="p55")
    _state(dados, ofertas={"magalu:p55": _reg(o55)})
    est = Estado("cloud")
    assert not est.bootstrap and not est.bootstrap_modelo("55C6K") and est.bootstrap_modelo("65C6K")
    post = Oferta("promobit", "post", "Magazine Luiza", "Smart TV TCL 65C6K", "https://pb/1", "1", preco=3200.0,
                  publicado=agora().isoformat(timespec="seconds"), modelo="65C6K")
    ofertas = [o55, _loja(3400.0, 3200.0, oid="p65"), post]
    msgs, _ = gerar_alertas(est, ofertas, [])
    assert msgs == []
    partida = mensagem_bootstrap(ofertas, [], "cloud", set(), ["65C6K"])
    assert partida.startswith("✅ <b>Monitor da TCL 65C6K iniciado</b>") and "3.200,00" in partida
    for o in ofertas:
        est.registra_oferta(o)
    est.marca_modelos_iniciados({modelo_de(o) for o in ofertas})
    est.salva()
    est = Estado("cloud")
    assert not est.bootstrap_modelo("65C6K")
    novo = Oferta("promobit", "post", "Magazine Luiza", "Smart TV TCL 65C6K", "https://pb/2", "2", preco=3250.0,
                  publicado=agora().isoformat(timespec="seconds"), modelo="65C6K")
    msgs, _ = gerar_alertas(est, [o55, _loja(3400.0, 3200.0, oid="p65"), novo], [])
    (m,) = [m for m in msgs if m.startswith("📣")]
    assert "🎯" in m.split("\n")[0] and "TCL 65C6K" in m.split("\n")[0]


def test_historico_ganha_a_coluna_modelo_e_as_linhas_antigas_ficam(dados):
    cab = "quando,fonte,tipo,loja,vendedor,titulo,preco,preco_pix,parcelado,cupom,url\r\n"
    antiga = "2026-09-14T21:04:38-03:00,magalu,loja,Magazine Luiza,Fast Shop,TV 55C6K,3099.0,2991.6,,,https://m/p/x/\r\n"
    (dados / "historico_cloud.csv").write_bytes((cab + antiga).encode("utf-8"))
    est = Estado("cloud")
    est.anexa_historico([])
    assert (dados / "historico_cloud.csv").read_bytes() == (cab + antiga).encode("utf-8"), "sem linha nova, nada muda"
    est.anexa_historico([_loja(4274.05, 3963.60, loja="Webcontinental", fonte="vtex", oid="w")])
    texto = (dados / "historico_cloud.csv").read_text(encoding="utf-8")
    linhas = texto.splitlines()
    assert linhas[0].split(",") == CAMPOS_HISTORICO
    assert linhas[1] + "\r\n" == antiga, "a linha antiga fica byte a byte"
    rows = list(csv.DictReader(texto.splitlines()))
    assert [modelo_de(r) for r in rows] == ["55C6K", "65C6K"]
    assert est._minimo_do_historico(set(), modelo="65C6K")["preco"] == 3963.6
    assert est._minimo_do_historico(set())["preco"] == 2991.6


def test_sanear_compara_cada_modelo_com_o_dele():
    # mediana misturada (3.6k-4.6k) não pode derrubar nada; e o preço impossível de um modelo sai pelo modelo dele
    ofs = [_loja(p, modelo="55C6K", oid=f"a{p}") for p in (3561.55, 3599.0, 3699.0, 3711.6, 1800.0)] + \
          [_loja(p, oid=f"b{p}") for p in (4559.05, 4687.87, 4736.0, 4799.0)]
    _, avisos = sanear(ofs)
    assert [o.id for o in ofs if not o.ativo] == ["a1800.0"] and len(avisos) == 1


def test_cupom_da_65_so_serve_para_a_65():
    c = Cupom("promobit", "Magazine Luiza", "TV65C6K300", "R$ 300 OFF na Smart TV TCL 65C6K", "u", "1")
    assert cupom_compativel(c, 3561.55, "55C6K")[0] is False
    assert cupom_compativel(c, 4559.05, "65C6K")[0] is True
    acima = Cupom("promobit", "Magazine Luiza", "TV400", "R$ 400 OFF em TVs acima de R$ 4.000", "u", "2")
    assert cupom_compativel(acima, 3561.55, "55C6K")[0] is False and cupom_compativel(acima, 4559.05, "65C6K")[0]
    prod = Cupom("magalu", "Magazine Luiza", "LU300", "R$ 300 OFF", "u", "3", especifico=True, modelo="65C6K")
    assert cupom_compativel(prod, 3561.55, "55C6K")[0] is False and cupom_compativel(prod, 4559.05, "65C6K")[0]


def test_alerta_de_cupom_diz_para_qual_tv(dados):
    _state(dados, modelos_iniciados=["55C6K", "65C6K"])
    ofs = [_loja(3749.0, 3561.55, modelo="55C6K", oid="p55"), _loja(4799.0, 4559.05, oid="p65")]
    c = Cupom("promobit", "Magazine Luiza", "TV400", "R$ 400 OFF em TVs acima de R$ 4.000", "u", "2")
    msgs, _ = gerar_alertas(Estado("cloud"), ofs, [c])
    (m,) = msgs
    assert "TV400" in m and "R$ 4.559,05 (65\")" in m and "só 65\"" in m
    assert [x.codigo for x in cupons_aplicaveis(ofs, [c], Estado("cloud"))] == ["TV400"]
    # só com a 55" em jogo (sem preço da 65" na rodada), como antes: não serve
    assert cupons_aplicaveis(ofs[:1], [c], Estado("cloud")) == []


def test_resumo_e_partida_com_as_duas_tvs(dados):
    _state(dados)
    ofs = [_loja(3749.0, 3561.55, modelo="55C6K", oid="p55"),
           _loja(4274.05, 3963.60, loja="Webcontinental", vendedor="Casas Bahia", fonte="vtex", oid="w")]
    r = resumo_diario(Estado("cloud"), ofs, [])
    assert "Resumo diário — TCL 55C6K" in r and "📺 <b>TCL 65C6K</b>" in r
    assert "• Webcontinental/Casas Bahia: <b>R$ 3.963,60</b>" in r and "Alvo (65\"): Pix R$ 3.300,00" in r
    partida = mensagem_bootstrap(ofs, [], "cloud", set())
    assert "Monitor da TCL 55C6K e da TCL 65C6K iniciado" in partida
    assert partida.index("📺 <b>TCL 55C6K</b>") < partida.index("📺 <b>TCL 65C6K</b>")


# ------------------------------------------------------------------------------------------------
# confiança: referência e tamanho do MESMO modelo
# ------------------------------------------------------------------------------------------------

def test_confianca_compara_a_65_com_a_65(dados):
    _state(dados, modelos_iniciados=["55C6K", "65C6K"])
    confiaveis = [_loja(3749.0, 3561.55, modelo="55C6K", oid="p55", confiavel=False),
                  _loja(4799.0, 4559.05, oid="p65", confiavel=False)]
    for o in confiaveis:
        o.extra["vendedor_id"] = "magazineluiza"
    # vendedor desconhecido da 65" a 3.350: 27% abaixo da 65" confiável (4.559,05), mas acima da 55" confiável
    novo = _loja(3700.0, 3350.0, oid="x65", vendedor="Loja Nova", confiavel=False)
    novo.extra.update(vendedor_id="lojanova", ficha={"anatel": "00738-24-06714", "modelo": "65C6K", "tamanho": '65"',
                                                   "avaliacoes": 10})
    est = Estado("cloud")
    confianca.avaliar(est, confiaveis + [novo], rede=False)
    c = novo.extra["confianca"]
    assert c["veredito"] == confianca.SUSPEITO and "preco_muito_abaixo" in c["codigos"]
    assert "tamanho_diferente" not in c["codigos"], "a ficha de 65\" é a desta TV"
    # a mesma ficha de 65" numa oferta da 55C6K é sinal de identidade
    o55 = Oferta("magalu", "loja", "Magazine Luiza", "TV", "u", "y-z", preco=3600.0, extra={"ficha": {"tamanho": '65"'}})
    s, _ = confianca.sinais_da_oferta(o55, confianca.Referencias())
    assert any(x.codigo == "tamanho_diferente" for x in s)


def test_carrinho_usa_a_referencia_do_modelo():
    todas = [_loja(4799.0, 4559.05, oid="p65")]
    o = _loja(4300.0, 4250.0, oid="z", vendedor="Loja Z", confiavel=False)
    o.extra["vendedor_id"] = "lojaz"
    assert confianca.pode_ir_ao_carrinho(o, todas, ())[0] is True
    o55 = _loja(3300.0, 3250.0, modelo="55C6K", oid="z55", vendedor="Loja Z", confiavel=False)
    o55.extra["vendedor_id"] = "lojaz"
    # sem 55" confiável de referência, a 65" não serve de régua para a 55"
    assert confianca.pode_ir_ao_carrinho(o55, todas, ())[0] is True


def test_catalogo_da_65_no_ml_nao_e_anuncio_de_um_vendedor():
    o = Oferta("mercadolivre", "loja", "Mercado Livre", "TV", "u", "MLB50368907", preco=4000.0, modelo="65C6K",
               extra={"item_id": "MLB50368907", "vendedor_id": "123"})
    assert confianca._anuncio_proprio(o) == ""


# ------------------------------------------------------------------------------------------------
# rodada inteira (run.main) com fontes falsas: a 65" entra num state que já existia
# ------------------------------------------------------------------------------------------------

class _FonteFalsa:
    nome = "falsa"
    modo = "cloud"
    alerta_falha = True

    def __init__(self, ofertas):
        self.ofertas = ofertas

    def coletar(self):
        return list(self.ofertas), []


def _roda(monkeypatch, ofertas, capsys) -> str:
    import sys

    import run
    from monitor import sources

    monkeypatch.setattr(run, "carrega_env", lambda: None)  # nunca lê .env
    monkeypatch.setattr(sources, "por_modo", lambda modo: [_FonteFalsa(ofertas)])
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["run.py", "--mode", "cloud", "--no-notify"])
    monkeypatch.setattr(config, "HORA_RESUMO_DIARIO", -1)
    assert run.main() == 0
    return capsys.readouterr().out


def test_rodada_inteira_com_a_65_entrando(dados, monkeypatch, capsys):
    o55 = _loja(3749.0, 3561.55, modelo="55C6K", oid="240162700-magazineluiza")
    _state(dados, ofertas={f"magalu:{o55.id}": _reg(o55)})
    cab = "quando,fonte,tipo,loja,vendedor,titulo,preco,preco_pix,parcelado,cupom,url\n"
    (dados / "historico_cloud.csv").write_text(cab + "2026-09-20T10:00:00-03:00,magalu,loja,Magazine Luiza,Magalu,TV,"
                                               "3749.0,3561.55,,,https://loja.example/x\n", encoding="utf-8")
    rodada1 = [o55, _loja(4799.0, 4559.05, oid="240162600-magazineluiza"),
               _loja(4274.05, 3963.60, oid="w65", loja="Webcontinental", vendedor="Casas Bahia", fonte="vtex")]
    out = _roda(monkeypatch, rodada1, capsys)
    assert "Monitor da TCL 65C6K iniciado" in out and "Webcontinental/Casas Bahia: <b>R$ 3.963,60</b>" in out
    st = json.loads((dados / "state_cloud.json").read_text(encoding="utf-8"))
    assert st["modelos_iniciados"] == ["55C6K", "65C6K"] and st["minimo_65C6K"]["preco"] == 3963.6
    lt = json.loads((dados / "latest_cloud.json").read_text(encoding="utf-8"))
    assert {o["modelo"] for o in lt["ofertas_loja"]} == {"55C6K", "65C6K"} and lt["alvos"]["65C6K"]["pix"] == 3300.0
    linhas = (dados / "historico_cloud.csv").read_text(encoding="utf-8").splitlines()
    assert linhas[0].endswith(",modelo") and linhas[1].endswith("https://loja.example/x")
    assert sorted(l.rsplit(",", 1)[1] for l in linhas[2:]) == ["55C6K", "65C6K", "65C6K"]
    # 2ª rodada: a 65" cai para 3.290 no Pix na Webcontinental -> 🎯 e 🏆 da 65C6K (a 55" não muda)
    rodada2 = [o55, rodada1[1], _loja(4274.05, 3290.0, oid="w65", loja="Webcontinental", vendedor="Casas Bahia",
                                      fonte="vtex")]
    out = _roda(monkeypatch, rodada2, capsys)
    assert "iniciado" not in out
    (cab65,) = [l for l in out.splitlines() if "65C6K — <b>" in l]
    assert "🏆" in cab65 and "🎯 Abaixo do alvo" in cab65 and "🔻" in cab65
    assert not any("55C6K — <b>" in l for l in out.splitlines())
    assert "melhor preço 55C6K 3561.55 / 65C6K 3290.00" in out
