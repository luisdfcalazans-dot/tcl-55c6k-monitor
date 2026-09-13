"""Testes com arquivos reais salvos em 13/09/2026. Se um site mudar, o teste quebra antes do monitor."""

import json
from pathlib import Path

from monitor.regras import cupom_compativel
from monitor.models import Cupom
from monitor.sources import kabum, magalu, pelando, promobit, telegram_public, vtex, zoom
from monitor.util import parse_preco, parcelado_no_texto, cupom_no_texto

FIX = Path(__file__).parent / "fixtures"


def le(nome: str) -> str:
    return (FIX / nome).read_text(encoding="utf-8", errors="replace")


def test_parse_preco():
    assert parse_preco("R$ 3.082,61") == 3082.61
    assert parse_preco("R$2.799") == 2799
    assert parse_preco("3082.61") == 3082.61
    assert parse_preco("3704.05") == 3704.05
    assert parse_preco(2799) == 2799
    assert parse_preco("") is None


def test_texto_utils():
    assert parcelado_no_texto("Por R$2.760,00 em até 15x de R$ 184,00 sem juros") == "15x R$ 184,00 sem juros"
    assert cupom_no_texto("Use o cupom SOLTAODESCONTO na finalização") == "SOLTAODESCONTO"
    assert cupom_no_texto("cupom TECNOBLOG250 somado ao Pix") == "TECNOBLOG250"


def test_promobit_api():
    data = json.loads(le("promobit_search.json"))
    ofs = [promobit._oferta_de_item(i, False) for i in data["finished_offers"]]
    ofs = [o for o in ofs if o]
    assert len(ofs) == 3
    assert ofs[0].preco == 2840.14 and ofs[0].cupom == "ESQUENTA320" and ofs[0].loja == "Magazine Luiza"
    assert ofs[0].url.startswith("https://www.promobit.com.br/oferta/")


def test_pelando_busca():
    ofs = pelando.parse_busca(le("pelando_busca.html"))
    assert len(ofs) >= 4
    assert all(o.tipo == "post" for o in ofs)
    precos = sorted(o.preco for o in ofs if o.preco)
    assert precos and precos[0] >= 2000
    assert any(o.loja == "AliExpress" for o in ofs)
    assert all(o.ativo is False for o in ofs)  # todas expiradas no dia da coleta


def test_pelando_cupons():
    cs = pelando.parse_cupons(le("pelando_cupons_magalu.html"), "magalu", "x")
    assert cs and all(c.loja == "Magazine Luiza" for c in cs)
    assert any(c.codigo == "ESPECIALISTAEMTI100" for c in cs)


def test_zoom():
    ofs = zoom.parse_produto(le("zoom_produto.html"))
    lojas = {o.loja for o in ofs}
    assert {"Webcontinental", "Fast Shop", "KaBuM!", "Amazon", "Magazine Luiza"} <= lojas
    assert min(o.preco for o in ofs) == 3082.61


def test_magalu():
    o, cupons = magalu.parse_produto(le("magalu_produto.html"))
    assert o and o.loja == "Magazine Luiza" and o.vendedor == "Magalu"
    assert o.preco == 3899.0 and o.preco_pix == 3704.05
    assert o.parcelado == "10x R$ 389,90 sem juros"
    assert cupons and cupons[0].codigo == "LU250" and cupons[0].especifico
    assert o.url.startswith("https://www.magazineluiza.com.br/") and "magazinecanaltechbr" not in o.url
    assert o.extra["preco_com_cupom"] == 3454.05


def test_kabum():
    o = kabum.parse_api(json.loads(le("kabum_api.json")))
    assert o and o.loja == "KaBuM!" and o.parcelado == "10x de R$ 315,89 sem juros"
    assert o.preco in (3159.0, 3408.9)  # depende da data da oferta relâmpago


def test_vtex():
    ofs = vtex.parse_catalogo(json.loads(le("fastshop_vtex.json")), "Fast Shop", "https://site.fastshop.com.br")
    assert ofs and all("Combo" not in o.titulo for o in ofs)
    assert any(o.preco == 3296.81 and o.vendedor == "Fast Shop" for o in ofs)
    assert any(o.vendedor == "TCL SEMP" and o.parcelado == "12x R$ 334,08 sem juros" for o in ofs)


def test_telegram_publico():
    ofs = telegram_public.parse_canal(le("telegram_ctofertaseletroetv.html"), "ctofertaseletroetv")
    # neste arquivo há posts de TCL P8K/S5K/P7L, mas nenhum da 55C6K
    assert all("c6k" in o.titulo.lower() for o in ofs)


def test_cupom_compativel():
    c = Cupom(fonte="x", loja="Magazine Luiza", codigo="A", titulo="Cupom Magalu 10% OFF", url="", id="1",
              regra="Válido para compras até R$300.")
    assert cupom_compativel(c, 3700)[0] is False
    c2 = Cupom(fonte="x", loja="Magazine Luiza", codigo="B", titulo="Cupom Magalu R$ 100 acima de R$ 1000", url="", id="2")
    assert cupom_compativel(c2, 3700)[0] is True
    c3 = Cupom(fonte="x", loja="Amazon", codigo="C", titulo="10% OFF em moda", url="", id="3")
    assert cupom_compativel(c3, 3200)[0] is False
    fora = ["Cupom de desconto Magalu oferece 20% OFF em Cervejas", "Cupom de desconto Magalu oferece 5% OFF em entrega FULL",
            "Cupom de desconto Magalu oferece 10% OFF em Cuidados Pessoais", "Cupom de desconto Magalu oferece 10% OFF em itens de treino",
            "Cupom de desconto Magalu oferece 10% OFF em Bikes", "Cupom Magalu 15% OFF em compras de até R$ 1000"]
    for t in fora:
        assert cupom_compativel(Cupom(fonte="x", loja="Magazine Luiza", codigo="Z", titulo=t, url="", id=t), 3091)[0] is False, t
    dentro = ["Cupom de desconto Magalu oferece R$100 OFF em suas compras", "Cupom de desconto Magalu oferece 10% OFF em suas compras",
              "Cupom Magalu R$ 100 acima de R$ 1000", "Cupom de desconto Magalu oferece 10% OFF em TVs",
              "Cupom Amazon 10% OFF em eletrônicos"]
    for t in dentro:
        assert cupom_compativel(Cupom(fonte="x", loja="Magazine Luiza", codigo="Z", titulo=t, url="", id=t), 3091)[0] is True, t
