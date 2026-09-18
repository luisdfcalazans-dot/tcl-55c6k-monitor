"""Amazon: desde 18/09/2026 o número grande da página é o preço do Pix/NuPay, e o do cartão vem na frase
"ou R$ 3.749,00 em até 12x de R$ 312,49 sem juros". O coletor gravava o do Pix como preço de cartão, o que
poderia disparar um 🎯 de parcelado falso (a regra do alvo parcelado usa o.preco + o.parcelado)."""

from pathlib import Path

from bs4 import BeautifulSoup

from monitor.carrinho import Amazon as AmazonCarrinho
from monitor.sources.amazon import parse_produto, separa_pix_cartao

FIXTURE = Path(__file__).parent / "fixtures" / "amazon_pix_2026-09-18.html"

TITULO = ("Smart TV TCL 55 Polegadas QLED Mini LED 4K C6K WiFi Bluetooth Google TV 4 HDMI 144Hz HDR10+ 55C6K")


def test_pagina_real_separa_pix_e_cartao():
    o = parse_produto(FIXTURE.read_text(encoding="utf-8"))
    assert o is not None and o.ativo
    assert o.preco_pix == 3374.10
    assert o.preco == 3749.00, "o do cartão é o da frase 'em até 12x', não o do destaque"
    assert o.parcelado == "12x R$ 312,49 sem juros"
    assert o.melhor_preco == 3374.10
    assert o.vendedor and "Magalu" in o.vendedor


def test_layout_antigo_sem_pix_continua_igual():
    html = f"""<html><body><span id="productTitle">{TITULO}</span>
    <div id="corePriceDisplay_desktop_feature_div"><span class="a-price"><span class="a-offscreen">R$ 3.749,00</span></span></div>
    <div id="availability">Em estoque</div>
    <p>Em até 12x de R$ 312,49 sem juros</p></body></html>"""
    o = parse_produto(html)
    assert (o.preco, o.preco_pix) == (3749.0, None)
    assert o.parcelado == "12x R$ 312,49 sem juros"


def test_separa_pix_cartao_casos():
    frase = "ou R$ 3.749,00 em até 12x de R$ 312,49 sem juros"
    assert separa_pix_cartao(3374.10, "à vista no Pix ou NuPay (10% off)", frase) == \
        (3749.0, 3374.10, "12x R$ 312,49 sem juros")
    # sem a frase do Pix: o destaque é o do cartão
    assert separa_pix_cartao(3749.0, "", frase) == (3749.0, None, "12x R$ 312,49 sem juros")
    # Pix sem a frase do cartão: nunca repetir o do Pix como cartão
    assert separa_pix_cartao(3374.10, "à vista no Pix", "") == (None, 3374.10, None)
    # frase do cartão incoerente (menor que o Pix): descarta
    assert separa_pix_cartao(3374.10, "à vista no Pix", "ou R$ 3.000,00 em até 10x de R$ 300,00 sem juros") == \
        (None, 3374.10, None)
    # parcelado com juros não vira "sem juros"
    assert separa_pix_cartao(3374.10, "à vista no Pix", "ou R$ 3.999,00 em até 12x de R$ 333,25")[2] == \
        "12x R$ 333,25"


class _Loc:
    def __init__(self, txt):
        self.txt = txt

    @property
    def first(self):
        return self

    def count(self):
        return 1 if self.txt is not None else 0

    def inner_text(self):
        return self.txt


class _PaginaAmazon:
    """Página falsa montada com os trechos reais salvos em FIXTURE."""

    def __init__(self, html):
        self.html = html
        self.soup = BeautifulSoup(html, "html.parser")
        self.url = "https://www.amazon.com.br/dp/B0F7JZMVKF"

    def locator(self, sel):
        for s in sel.split(","):
            e = self.soup.select_one(s.strip())
            if e is not None:
                return _Loc(e.get_text(" ", strip=True))
        return _Loc(None)

    def evaluate(self, js):
        return self.soup.get_text("\n", strip=True)

    def content(self):
        return self.html


def test_carrinho_amazon_le_pix_e_cartao_separados():
    r = AmazonCarrinho().ler_totais(_PaginaAmazon(FIXTURE.read_text(encoding="utf-8")))
    assert r.total_pix == 3374.10
    assert r.total_cartao == 3749.00
    assert r.parcelado == "12x R$ 312,49 sem juros"
    assert r.tv_pix == 3374.10 and r.tv_cartao == 3749.00
