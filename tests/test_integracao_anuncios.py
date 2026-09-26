"""Contrato entre a COLETA (descoberta de todos os anúncios) e o TESTADOR de cupons (19/09/2026).

Pedido do usuário: "faça uma varredura em todos os anuncios e faça os teste de cupons dando prioridade ao mais
barato e troque de anuncio se não funcionar nos mais baratos".

A coleta grava uma Oferta tipo "loja" por anúncio+vendedor no latest_<modo>.json; o testador lê cada uma como um
anúncio. Aqui as ofertas saem dos PARSERS REAIS da coleta (fixtures de 19/09), passam por to_dict() como no latest
e entram no testador. Nenhum teste acessa a rede, abre o Chrome ou um perfil de carrinho.
"""

import copy
import importlib
import json
from pathlib import Path

import pytest

from monitor import config
from monitor.carrinho import Amazon, Magalu, MercadoLivre, item_ml_da_url
from monitor.sources import amazon, magalu
from monitor.sources import playwright_sources as ps
from monitor.util import next_data

FX = Path(__file__).parent / "fixtures"
P1P = (FX / "magalu_produto_1p_2026-09-19.html").read_text(encoding="utf-8")
PCOLOMBO = (FX / "magalu_produto_colombo_2026-09-19.html").read_text(encoding="utf-8")
AOD = (FX / "amazon_aod_2026-09-19.html").read_text(encoding="utf-8")
ML_BUSCA = (FX / "ml_busca_2026-09-19.html").read_text(encoding="utf-8")
ML_CAT_VEND = (FX / "ml_catalogo_vendedor_2026-09-19.html").read_text(encoding="utf-8")
ML_ITEM_NOVO = (FX / "ml_item_vendedor_novo_2026-09-19.html").read_text(encoding="utf-8")


def _importa_testar_cupons():
    """testar_cupons chama carrega_env() ao ser importado; no teste isso não lê o .env."""
    import run

    original = run.carrega_env
    run.carrega_env = lambda: None
    try:
        return importlib.import_module("testar_cupons")
    finally:
        run.carrega_env = original


tc = _importa_testar_cupons()


@pytest.fixture
def dados(tmp_path, monkeypatch):
    pasta = tmp_path / "data"
    pasta.mkdir()
    monkeypatch.setattr(config, "DIR_DADOS", pasta)
    monkeypatch.delenv("CUPONS_EXTRA", raising=False)

    def latest(modo: str, ofertas) -> None:
        d = {"modo": modo, "ofertas_loja": [o.to_dict() for o in ofertas], "cupons": [], "posts": []}
        (pasta / f"latest_{modo}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    return latest


# ------------------------------------------------------------------------------------------------
# Magalu
# ------------------------------------------------------------------------------------------------

def _html_produto(p: dict) -> str:
    nd = {"props": {"pageProps": {"data": {"product": p}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd, ensure_ascii=False)}</script>'


def _1p_com_outro_vendedor(pix: str) -> str:
    """O anúncio 1P real com um 2º vendedor na lista 'offers' (só o Pix, como a lista traz)."""
    p = copy.deepcopy(next_data(P1P)["props"]["pageProps"]["data"]["product"])
    p["offers"].append({"sku": "999", "price": {"paymentMethodDescription": "no Pix", "bestPrice": pix,
                                                "fullPrice": None, "price": "4199.00"},
                        "seller": {"id": "lojaxyz", "description": "Loja XYZ", "category": "3p", "tags": None}})
    return _html_produto(p)


def test_magalu_da_coleta_ao_testador_do_mais_barato_ao_mais_caro(dados):
    ofs_1p, _, _ = magalu.parse_produto_todas(_1p_com_outro_vendedor("3400.00"))
    ofs_colombo, _, _ = magalu.parse_produto_todas(PCOLOMBO)
    dados("cloud", ofs_colombo + ofs_1p)
    _, anuncios = tc.codigos_conhecidos(Magalu())
    # a chave do testador usa o /p/ da URL (240162700), não o id do JSON (240162800)
    assert [a.chave for a in anuncios] == [
        "240162700-lojaxyz", "240162700-magazineluiza", "kc7h6f4k4b-lojascolombooficial"]
    xyz, p1, colombo = anuncios
    # vendedor só da lista 'offers': só o Pix, sem cartão; a URL escolhe o vendedor no site
    assert (xyz.preco, xyz.preco_cartao, xyz.vendedor_id) == (3400.0, None, "lojaxyz")
    assert xyz.url.endswith("/p/240162700/et/elit/?seller_id=lojaxyz")
    assert Magalu._seller_da_url(xyz.url) == "lojaxyz"
    # vendedor do buy box: URL sem seletor, vendedor pelo extra.vendedor_id
    assert "seller_id" not in p1.url and p1.vendedor_id == "magazineluiza" and p1.produto == "240162700"
    assert (p1.preco, p1.preco_cartao) == (3561.55, 3749.0)
    assert colombo.vendedor_id == "lojascolombooficial" and colombo.produto == "kc7h6f4k4b"
    alvo = xyz.alvo()
    assert (alvo["chave"], alvo["vendedor_id"], alvo["produto"]) == ("240162700-lojaxyz", "lojaxyz", "240162700")


def test_magalu_registros_antigos_so_valem_para_o_mesmo_vendedor(dados):
    """Estado de cupons de antes de 19/09 (chave = fim da URL, vendedor 'Magalu'): vale para o 1P e não
    para outro vendedor do mesmo /p/ (senão a recusa do 1P esconderia o teste no outro vendedor)."""
    ofs_1p, _, _ = magalu.parse_produto_todas(_1p_com_outro_vendedor("3400.00"))
    dados("cloud", ofs_1p)
    _, (xyz, p1) = tc.codigos_conhecidos(Magalu())
    antigo = {"testado_em": "2026-09-19T10:00:00-03:00", "status": "recusado", "aceito": False,
              "mensagem": "Este cupom LU250 não se aplica para este pedido", "vendedor": "Magalu"}
    testados = {"LU250@-assistente-4-hdmi-2-usb/p/240162700/et/elit/": antigo}
    assert tc.registro_do_cupom(testados, "LU250", p1) is antigo
    assert tc.registro_do_cupom(testados, "LU250", xyz) is None


# ------------------------------------------------------------------------------------------------
# Mercado Livre
# ------------------------------------------------------------------------------------------------

_TITULO_ML = "Smart Tv Tcl 55 Polegadas Qd-Mini Led 4k C6k Wifi Bluetooth Google Tv 4 Hdmi 144hz Hdr10+ 55c6k"
_JSONLD_ML = {"@context": "https://schema.org", "@type": "Product", "name": _TITULO_ML,
              "offers": {"@type": "Offer", "price": 3749, "priceCurrency": "BRL",
                         "availability": "https://schema.org/InStock", "url": config.URL_ML_CATALOGO}}
_CATALOGO_ML = (f'<html><head><script type="application/ld+json">{json.dumps(_JSONLD_ML)}</script></head>'
                f"<body><h1>{_TITULO_ML}</h1>" + ML_CAT_VEND.split("<body>", 1)[1])
_TEXTO_CAT_ML = f"{_TITULO_ML}\nR$\n3.749\n10x R$ 374,90 sem juros\nOutras opções de compra\n"


def _coleta_ml(monkeypatch, tmp_path, busca: str, item_avulso: str | None = None) -> list:
    """coletar() do ML com as páginas das fixtures (o Chrome nunca abre)."""
    monkeypatch.setattr(ps, "MARCA_BLOQUEIO_ML", tmp_path / "ml_bloqueado_em")
    paginas = {"/p/MLB48808732": (_CATALOGO_ML, _TEXTO_CAT_ML), "lista.mercadolivre": (busca, "busca")}
    if item_avulso is not None:
        paginas["MLB-7523184294"] = (item_avulso, "")

    def abrir(url, *a, **k):
        for trecho, (html, texto) in paginas.items():
            if trecho in url:
                return html, texto, []
        raise AssertionError(f"URL inesperada {url}")

    monkeypatch.setattr(ps, "_abrir", abrir)
    return ps.MercadoLivre().coletar()[0]


def _ml_item_vendedor_bom() -> str:
    bom = ML_ITEM_NOVO.replace('"text": "0", "accessibility_text": "0 Vendas"',
                               '"text": "+5 mil", "accessibility_text": "mais de 5 mil Vendas"')
    assert bom != ML_ITEM_NOVO
    return bom


def test_ml_da_coleta_ao_testador_pelo_item_do_vendedor(dados, monkeypatch, tmp_path):
    # R$ 3.199 no anúncio avulso (85% do catálogo, R$ 3.749): vendedor fora da lista, sem sinal de risco. A R$ 2.769 da
    # fixture (26% abaixo) ele fica suspeito e não vai ao carrinho (teste abaixo; monitor/confianca.py)
    dados("pc", _coleta_ml(monkeypatch, tmp_path, ML_BUSCA.replace("2.769", "3.199"), _ml_item_vendedor_bom()))
    _, anuncios = tc.codigos_conhecidos(MercadoLivre())
    assert [a.chave for a in anuncios] == ["MLB7523184294", "MLB7574364080"]
    avulso, cat = anuncios
    # opção do catálogo: o carrinho abre o catálogo com a opção deste vendedor
    assert cat.item_id == "MLB7574364080" and cat.catalogo == "MLB48808732"
    assert item_ml_da_url(cat.url) == "MLB7574364080"
    # anúncio fora do catálogo, vendedor conferido pela coleta
    assert avulso.item_id == "MLB7523184294" and avulso.catalogo == ""
    assert item_ml_da_url(avulso.url) == "MLB7523184294"
    assert set(avulso.alvo(a.item_id for a in anuncios)["ids_tv"]) == {"MLB7523184294", "MLB7574364080"}


def test_ml_anuncio_muito_abaixo_do_catalogo_de_vendedor_fora_da_lista_nao_vai_para_o_carrinho(dados, monkeypatch,
                                                                                                 tmp_path):
    """Registro do latest sem veredito (como o testador lê): 26% abaixo do vendedor confiável é suspeito."""
    dados("pc", _coleta_ml(monkeypatch, tmp_path, ML_BUSCA, _ml_item_vendedor_bom()))
    _, anuncios = tc.codigos_conhecidos(MercadoLivre())
    assert [a.chave for a in anuncios] == ["MLB7574364080"]


def test_ml_anuncio_sem_vendedor_conferido_nao_vai_para_o_carrinho(dados, monkeypatch, tmp_path):
    # mais caro que o catálogo: a coleta grava sem conferir o vendedor (vendedor_conferido=False)
    ofertas = _coleta_ml(monkeypatch, tmp_path, ML_BUSCA.replace("2.769", "3.999"))
    assert {o.id: o.extra.get("vendedor_conferido") for o in ofertas} == {"MLB7574364080": None,
                                                                          "MLB7523184294": False}
    dados("pc", ofertas)
    _, anuncios = tc.codigos_conhecidos(MercadoLivre())
    assert [a.chave for a in anuncios] == ["MLB7574364080"]


# ------------------------------------------------------------------------------------------------
# Amazon (só leitura) e Casas Bahia (só coleta)
# ------------------------------------------------------------------------------------------------

def test_amazon_da_coleta_ao_testador_um_anuncio_por_vendedor(dados):
    dados("pc", amazon.parse_ofertas(AOD, "B0F7JZMVKF"))
    _, anuncios = tc.codigos_conhecidos(Amazon())
    assert [a.chave for a in anuncios] == ["B0F7JZMVKF-ACUNARZFR75ET", "B0F7JZMVKF-A30OZFNW1RCCSM"]
    magalu_amz, colombo = anuncios
    assert (magalu_amz.preco, magalu_amz.preco_cartao) == (3374.10, None)  # só o Pix no painel
    for a in anuncios:
        assert a.vendedor_id == Amazon._smid(a.url) == a.chave.split("-", 1)[1]


def test_casas_bahia_e_outras_lojas_nao_entram_no_testador(dados):
    cb = ps.Oferta(fonte="casasbahia", tipo="loja", loja="Casas Bahia", titulo="Smart TV 55” TCL 55C6K",
                   url="https://www.casasbahia.com.br/smart-tv-55-tcl-55c6k/p/55069456", id="55069456-10037",
                   preco=3998.99, preco_pix=3599.09, extra={"anuncio": "55069456", "vendedor_id": "10037"})
    dados("pc", [cb])
    assert "casasbahia" not in tc.LOJAS
    for loja in (Magalu(), MercadoLivre(), Amazon()):
        _, anuncios = tc.codigos_conhecidos(loja)
        assert all(loja.dominio_url in a.url for a in anuncios)
        assert all(a.chave != "55069456-10037" for a in anuncios)
