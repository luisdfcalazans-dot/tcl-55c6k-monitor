"""Contrato coleta -> testador (19/09): cada anúncio é uma Oferta tipo "loja" com id único por anúncio+vendedor
e uma URL que abre AQUELE anúncio/vendedor. Aqui: a chave que o testador usa para cada loja, e a conferência
do vendedor na página da Amazon (só leitura)."""

from pathlib import Path

from bs4 import BeautifulSoup

from monitor.carrinho import Amazon, Magalu, MercadoLivre, item_ml_da_url, mesmo_vendedor

FIXTURE_AMAZON = Path(__file__).parent / "fixtures" / "amazon_pix_2026-09-18.html"


# ------------------------------------------------------------------------------------------------
# identidade do anúncio
# ------------------------------------------------------------------------------------------------

def test_identidade_magalu():
    m = Magalu()
    # contrato: id '<productId>-<sellerId>', URL com ?seller_id quando não é o do buy box
    o = {"id": "kc7h6f4k4b-lojascolombooficial", "extra": {"anuncio": "kc7h6f4k4b", "vendedor_id": "lojascolombooficial"},
         "url": "https://www.magazineluiza.com.br/smart-tv-tcl-55/p/kc7h6f4k4b/et/elit/?seller_id=lojascolombooficial"}
    i = m.identidade(o)
    assert (i["chave"], i["vendedor_id"], i["produto"]) == ("kc7h6f4k4b-lojascolombooficial", "lojascolombooficial",
                                                            "kc7h6f4k4b")
    # só o seller_id da URL
    o2 = {"id": "x", "url": "https://www.magazineluiza.com.br/tv/p/240162700/et/elit/?seller_id=magazineluiza"}
    assert m.identidade(o2)["chave"] == "240162700-magazineluiza"
    # a chave usa o /p/ da URL (o que a sacola devolve), não o id do JSON
    o3 = {"id": "240162800-magazineluiza", "url": "https://www.magazineluiza.com.br/tv/p/240162700/et/elit/"}
    assert m.identidade(o3)["chave"] == "240162700-magazineluiza"


def test_identidade_mercado_livre():
    ml = MercadoLivre()
    cat = "https://www.mercadolivre.com.br/smart-tv-tcl-55/p/MLB48808732"
    assert ml.identidade({"id": "MLB7574364080", "url": cat + "?pdp_filters=item_id%3AMLB7574364080"})["chave"] == \
        "MLB7574364080"
    assert ml.identidade({"id": "x", "url": "https://produto.mercadolivre.com.br/MLB-5417889802-smart-tv-tcl-_JM"})[
        "chave"] == "MLB5417889802"
    assert ml.identidade({"id": "x", "url": cat, "extra": {"item_id": "MLB5417889802"}})["chave"] == "MLB5417889802"
    antigo = ml.identidade({"id": "MLB48808732", "url": cat})  # formato de antes (só o catálogo)
    assert (antigo["chave"], antigo["item_id"], antigo["catalogo"]) == ("MLB48808732", None, "MLB48808732")
    # id da oferta = item, URL só do catálogo: o item vem do id (senão testaria o 'Melhor preço' no lugar)
    assert ml.identidade({"id": "MLB7574364080", "url": cat})["item_id"] == "MLB7574364080"
    assert item_ml_da_url(cat + "?pdp_filters=item_id:MLB7574364080&x=1") == "MLB7574364080"
    assert item_ml_da_url(cat) is None


def test_identidade_amazon():
    a = Amazon()
    o = {"id": "B0F7JZMVKF-ACUNARZFR75ET", "url": "https://www.amazon.com.br/dp/B0F7JZMVKF?smid=ACUNARZFR75ET"}
    i = a.identidade(o)
    assert (i["chave"], i["vendedor_id"]) == ("B0F7JZMVKF-ACUNARZFR75ET", "ACUNARZFR75ET")
    assert a.identidade({"id": "B0F7JZMVKF", "url": "https://www.amazon.com.br/dp/B0F7JZMVKF"})["vendedor_id"] is None


def test_mesmo_vendedor():
    assert mesmo_vendedor("magazineluiza", None, None, "Magalu") is True
    assert mesmo_vendedor(None, "Magalu.", None, "Magalu") is True, "Amazon escreve 'Magalu.'"
    assert mesmo_vendedor(None, "Lojas Colombo Oficial", "lojascolombooficial", None) is True
    assert mesmo_vendedor(None, "Lojas Colombo Oficial", "magazineluiza", "Magalu") is False
    assert mesmo_vendedor(None, None, "magazineluiza", None) is None


# ------------------------------------------------------------------------------------------------
# Amazon: página do vendedor (smid), sem carrinho
# ------------------------------------------------------------------------------------------------

class _Loc:
    def __init__(self, n):
        self.n = n
        self.first = self

    def count(self):
        return self.n


class PaginaAmazon:
    def __init__(self, html):
        self.html = html
        self.texto = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
        self.url = ""
        self.visitas: list[str] = []

    def goto(self, url, **k):
        self.url = url
        self.visitas.append(url)

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        return self.texto

    def content(self):
        return self.html

    def locator(self, sel):
        return _Loc(1 if sel == "#productTitle" else 0)


def test_amazon_vendedor_da_pagina_real():
    html = FIXTURE_AMAZON.read_text(encoding="utf-8")
    assert Amazon.vendedor_da_pagina(html) == ("ACUNARZFR75ET", "Magalu.")
    assert Amazon.vendedor_da_pagina("", "Enviado por\nAmazon.com.br\nVendido por\nAmazon.com.br\n") == \
        (None, "Amazon.com.br")


def test_amazon_confere_o_vendedor_do_anuncio():
    html = FIXTURE_AMAZON.read_text(encoding="utf-8")
    url = "https://www.amazon.com.br/dp/B0F7JZMVKF?smid=ACUNARZFR75ET"
    p = PaginaAmazon(html)
    assert Amazon().garantir_item(p, url, {"vendedor": "Magalu.", "vendedor_id": "ACUNARZFR75ET"}) is True
    assert p.visitas == [url]
    # pediu a Colombo e a página mostrou o Magalu.: o preço lido não seria do anúncio
    url_c = "https://www.amazon.com.br/dp/B0F7JZMVKF?smid=A2COLOMBO01"
    assert Amazon().garantir_item(PaginaAmazon(html), url_c, {"vendedor": "Lojas Colombo",
                                                             "vendedor_id": "A2COLOMBO01"}) is False
    # sem vendedor no anúncio (formato antigo): lê o que a página mostrar
    assert Amazon().garantir_item(PaginaAmazon(html), "https://www.amazon.com.br/dp/B0F7JZMVKF") is True
