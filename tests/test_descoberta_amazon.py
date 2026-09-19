"""Amazon: todos os vendedores do B0F7JZMVKF (painel aodAjaxMain) e outros ASINs da busca (19/09/2026).

Fixtures: trechos reais de 19/09 (painel de ofertas por HTTP: Magalu. em destaque com Pix R$ 3.374,10 e
Lojas Colombo S/A a R$ 4.184,88; cartões da busca 'tcl 55c6k'), sem tokens nem dados de sessão.
Nenhum teste acessa a rede nem abre o Chrome.
"""

from pathlib import Path

import pytest
import requests

from monitor import config
from monitor.sources import amazon
from monitor.sources import playwright_sources as ps

FX = Path(__file__).parent / "fixtures"
AOD = (FX / "amazon_aod_2026-09-19.html").read_text(encoding="utf-8")
BUSCA = (FX / "amazon_busca_2026-09-19.html").read_text(encoding="utf-8")
DP = (FX / "amazon_pix_2026-09-18.html").read_text(encoding="utf-8")
ASIN = "B0F7JZMVKF"


def test_painel_de_ofertas_um_vendedor_por_bloco():
    por_id = {o.id: o for o in amazon.parse_ofertas(AOD, ASIN)}
    assert set(por_id) == {"B0F7JZMVKF-ACUNARZFR75ET", "B0F7JZMVKF-A30OZFNW1RCCSM"}
    magalu = por_id["B0F7JZMVKF-ACUNARZFR75ET"]
    assert magalu.vendedor.startswith("Magalu") and magalu.extra["destaque"] is True
    # "à vista no Pix": o do painel é o Pix; o do cartão fica vazio (nunca repetir o Pix como cartão)
    assert (magalu.preco, magalu.preco_pix) == (None, 3374.10)
    assert magalu.url == "https://www.amazon.com.br/dp/B0F7JZMVKF?smid=ACUNARZFR75ET"
    colombo = por_id["B0F7JZMVKF-A30OZFNW1RCCSM"]
    assert (colombo.preco, colombo.preco_pix, colombo.vendedor) == (4184.88, None, "Lojas Colombo S/A")
    assert colombo.extra == {"anuncio": ASIN, "asin": ASIN, "vendedor_id": "A30OZFNW1RCCSM", "destaque": False}


def test_busca_so_asins_da_55c6k():
    ofs = amazon.parse_busca(BUSCA)
    assert [o.extra["asin"] for o in ofs] == [ASIN]  # 65C6K, 50C6KS e controle remoto ficam de fora
    (o,) = ofs
    assert (o.preco, o.preco_pix, o.parcelado) == (None, 3374.10, "12x R$ 312,41 sem juros")


def test_captcha_no_painel_e_erro():
    with pytest.raises(RuntimeError):
        amazon.parse_ofertas("<html>Digite os caracteres que você vê abaixo</html>", ASIN)


class _Contador:
    def __init__(self, http: dict[str, str], chrome: dict[str, str]):
        self.http, self.chrome, self.cargas = http, chrome, []

    def get_html(self, url, **kw):
        self.cargas.append(("http", url))
        for k, v in self.http.items():
            if k in url:
                return v
        raise AssertionError(url)

    def abrir(self, url, *a, **k):
        self.cargas.append(("chrome", url))
        for k2, v in self.chrome.items():
            if k2 in url:
                return v, "", []
        raise AssertionError(url)


def _stub(monkeypatch, http, chrome):
    c = _Contador(http, chrome)
    monkeypatch.setattr(amazon, "get_html", c.get_html)
    monkeypatch.setattr(ps, "_abrir", c.abrir)
    return c


def test_coletar_junta_pagina_painel_e_busca_em_ate_3_cargas(monkeypatch):
    busca_com_outro = BUSCA.replace('data-asin="B0F7JZMVKF"', 'data-asin="B0ZZZZZZZZ"', 1)
    c = _stub(monkeypatch, {"/dp/": DP}, {"aodAjaxMain": AOD, "/s?k=": busca_com_outro})
    ofertas, _ = amazon.Amazon().coletar()
    assert [k for k, _ in c.cargas] == ["http", "chrome", "chrome"]
    assert len(c.cargas) <= config.AMAZON_MAX_CARGAS
    por_id = {o.id: o for o in ofertas}
    assert set(por_id) == {"B0F7JZMVKF-ACUNARZFR75ET", "B0F7JZMVKF-A30OZFNW1RCCSM", "B0ZZZZZZZZ-destaque"}
    # o vendedor em destaque fica com os dados completos da página do produto (cartão + Pix + parcelado)
    m = por_id["B0F7JZMVKF-ACUNARZFR75ET"]
    assert (m.preco, m.preco_pix, m.parcelado) == (3749.0, 3374.10, "12x R$ 312,49 sem juros")
    assert m.url.endswith("?smid=ACUNARZFR75ET") and m.extra["vendedor_id"] == "ACUNARZFR75ET"


def test_pagina_com_503_no_http_vai_para_o_chrome_e_pula_a_busca(monkeypatch):
    # 19/09: por HTTP a Amazon às vezes responde 503 (robô) ou a página vem sem preço
    c = _Contador({}, {"aodAjaxMain": AOD, "/dp/": DP})

    def http(url, **kw):
        c.cargas.append(("http", url))
        resp = requests.Response()
        resp.status_code = 503
        raise requests.HTTPError("503 Server Error", response=resp)

    monkeypatch.setattr(amazon, "get_html", http)
    monkeypatch.setattr(ps, "_abrir", c.abrir)
    ofertas, _ = amazon.Amazon().coletar()
    assert [k for k, _ in c.cargas] == ["http", "chrome", "chrome"]  # teto de 3: a busca fica para depois
    por_id = {o.id: o for o in ofertas}
    assert set(por_id) == {"B0F7JZMVKF-ACUNARZFR75ET", "B0F7JZMVKF-A30OZFNW1RCCSM"}
    assert por_id["B0F7JZMVKF-ACUNARZFR75ET"].preco == 3749.0


def test_sem_preco_em_lugar_nenhum_fica_inativo_e_nao_inventa_preco(monkeypatch):
    sem_preco = DP.replace("corePriceDisplay_desktop_feature_div", "x").replace("displayPrice", "y") \
        .replace("a-offscreen", "z").replace("a-price-whole", "w")
    c = _stub(monkeypatch, {"/dp/": sem_preco}, {"aodAjaxMain": "<html></html>", "/dp/": sem_preco})
    ofertas, _ = amazon.Amazon().coletar()
    assert len(c.cargas) == 3
    (o,) = ofertas
    assert o.ativo is False and o.melhor_preco is None
