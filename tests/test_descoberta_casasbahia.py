"""Casas Bahia: busca por outros skus da 55C6K e "outros vendedores" do 55069456 (19/09/2026).

Fixtures: cartões reais da busca /tcl-55c6k/b de 19/09 (55069456 da Casas Bahia e 1582483296) e a
lista "sellers" real do item (só a Casas Bahia hoje). O Chrome nunca abre: _abrir é trocado.
"""

import json
from pathlib import Path

from monitor import config
from monitor.sources import playwright_sources as ps

FX = Path(__file__).parent / "fixtures"
BUSCA = (FX / "casasbahia_busca_2026-09-19.html").read_text(encoding="utf-8")
VENDEDORES = (FX / "casasbahia_vendedores_2026-09-19.txt").read_text(encoding="utf-8").strip()
TITULO = "Smart TV 55” TCL 55C6K 4K QD-Mini Led 144Hz Sistema Operacional Google TV"


def _pagina(sku: str, titulo: str, pix: float, cartao: float, vendedores: str, seller_id: int = 10037) -> str:
    ld = {"@context": "https://schema.org", "@type": "Product", "name": titulo,
          "offers": [{"@type": "Offer", "availability": "https://schema.org/InStock", "price": pix,
                      "priceCurrency": "BRL", "seller": {"@type": "Organization", "name": "Casas Bahia"}}]}
    pp = {"sellPrice": {"skuId": int(sku), "sellerId": seller_id, "priceWithoutDiscount": cartao, "priceValue": pix},
          "paymentMethodDiscount": {"hasDiscount": True, "discountDescription": "10% no Pix",
                                    "sellPriceWithDiscount": pix}}
    return (f'<html><head><script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script></head>'
            f"<body><h1>{titulo}</h1><script>self.__next_f.push({{\"ProductPrice\":{json.dumps(pp)},"
            f"\"ProductFlags\":{{}},\"BuyBox\":{{{vendedores}}}}})</script></body></html>")


def test_busca_real_so_skus_da_55c6k():
    por_sku = {o.extra["sku"]: o for o in ps._cb_parse_busca(BUSCA)}
    assert set(por_sku) == {"55069456", "1582483296"}  # as 65C6K ficam de fora
    cb = por_sku["55069456"]
    assert (cb.preco, cb.preco_pix) == (3998.99, 3599.09)
    assert cb.parcelado is None  # "11x de R$ 399,83" sem "sem juros" é com juros
    outro = por_sku["1582483296"]
    assert (outro.preco, outro.preco_pix) == (5283.38, None) and outro.id == "1582483296-destaque"
    assert outro.url.endswith("/p/1582483296")
    # fora da grade de resultados (carrossel, página de produto) nada é lido
    assert ps._cb_parse_busca(BUSCA.replace("product-card-ProductsGrid", "carrossel")) == []


def test_vendedores_reais_e_outro_vendedor():
    (v,) = ps._cb_vendedores(VENDEDORES)
    assert v == {"id": "10037", "nome": "Casas Bahia", "eleito": True, "preco": 3998.99, "ativo": True}
    dois = VENDEDORES.replace(
        "}]", '},{"id":55123,"name":"Loja Parceira","elected":false,"sellPrice":3899.0,"buyButtonEnabled":true}]')
    html = _pagina("55069456", TITULO, 3599.09, 3998.99, dois)
    ofs = ps.CasasBahia._do_produto(html, TITULO, config.URL_CASASBAHIA_PRODUTO, "55069456")
    por_id = {o.id: o for o in ofs}
    assert set(por_id) == {"55069456-10037", "55069456-55123"}
    cb = por_id["55069456-10037"]
    assert (cb.preco, cb.preco_pix, cb.vendedor) == (3998.99, 3599.09, "Casas Bahia")
    assert cb.url == config.URL_CASASBAHIA_PRODUTO and cb.extra["vendedor_id"] == "10037"
    parc = por_id["55069456-55123"]
    assert (parc.preco, parc.preco_pix, parc.vendedor) == (3899.0, None, "Loja Parceira")
    assert parc.url.endswith("/p/55069456?idLojista=55123") and parc.extra["anuncio"] == "55069456"


def test_pagina_de_outro_item_nao_vira_preco():
    html = _pagina("55069456", TITULO, 3599.09, 3998.99, VENDEDORES)
    assert ps.CasasBahia._do_produto(html, TITULO, "https://x/p/1582483296", "1582483296") == []


def test_coletar_item_busca_e_pagina_do_outro_sku_em_ate_3_cargas(monkeypatch):
    t2 = "Smart TV TCL 55 AI, 4K UHD, QLED Mini LED, Android TV - 55C6K"
    v2 = '"sellers":[{"id":999,"name":"Lojas Colombo","elected":true,"sellPrice":5283.38,"buyButtonEnabled":true}]'
    paginas = {"/p/55069456": _pagina("55069456", TITULO, 3599.09, 3998.99, VENDEDORES),
               "/tcl-55c6k/b": BUSCA,
               "/p/1582483296": _pagina("1582483296", t2, 5283.38, 5283.38, v2, seller_id=999)}
    chamadas = []

    def abrir(url, *a, **k):
        chamadas.append(url)
        for trecho, html in paginas.items():
            if trecho in url:
                return html, "", []
        raise AssertionError(url)

    monkeypatch.setattr(ps, "_abrir", abrir)
    ofertas, _ = ps.CasasBahia().coletar()
    assert len(chamadas) == 3 <= config.CASASBAHIA_MAX_CARGAS
    por_id = {o.id: o for o in ofertas}
    assert set(por_id) == {"55069456-10037", "1582483296-999"}
    assert por_id["1582483296-999"].vendedor == "Lojas Colombo" and por_id["1582483296-999"].preco == 5283.38


def test_esgotado_continua_sem_preco(monkeypatch):
    ld = {"@type": "Product", "name": TITULO,
          "offers": {"@type": "Offer", "price": 0, "availability": "https://schema.org/OutOfStock"}}
    html = f'<html><script type="application/ld+json">{json.dumps(ld)}</script><h1>{TITULO}</h1></html>'
    texto = "Produto indisponível\nVocê também pode gostar\nSmart TV Hisense R$ 2.189,00"
    monkeypatch.setattr(ps, "_abrir", lambda url, *a, **k: (html, texto, []) if "55069456" in url
                        else ("<html></html>", "", []))
    (o,) = ps.CasasBahia().coletar()[0]
    assert o.ativo is False and o.melhor_preco is None and o.extra["motivo"] == "esgotado"
