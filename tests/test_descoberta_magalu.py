"""Magalu: descoberta de TODOS os anúncios e vendedores (pedido do usuário em 19/09/2026).

Fixtures: trechos reais do magazinevoce de 19/09 (busca 'tcl 55c6k', anúncio 1P 240162700 e o da
Lojas Colombo), com o JSON enxugado. Nenhum teste acessa a rede.
"""

import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
import requests

from monitor import config
from monitor.sources import magalu
from monitor.util import agora, next_data

FX = Path(__file__).parent / "fixtures"
BUSCA = (FX / "magalu_busca_2026-09-19.html").read_text(encoding="utf-8")
P1P = (FX / "magalu_produto_1p_2026-09-19.html").read_text(encoding="utf-8")
PCOLOMBO = (FX / "magalu_produto_colombo_2026-09-19.html").read_text(encoding="utf-8")


def _html_produto(p: dict) -> str:
    nd = {"props": {"pageProps": {"data": {"product": p}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd, ensure_ascii=False)}</script>'


def _produto(html: str) -> dict:
    return copy.deepcopy(next_data(html)["props"]["pageProps"]["data"]["product"])


def _com_outro_vendedor(pix: str = "3400.00") -> dict:
    """O anúncio 1P real com um 2º vendedor na lista 'offers' (como o site mostra quando há)."""
    p = _produto(P1P)
    p["offers"].append({"sku": "999", "price": {"paymentMethodDescription": "no Pix", "bestPrice": pix,
                                                "fullPrice": None, "price": "4199.00"},
                        "seller": {"id": "lojaxyz", "description": "Loja XYZ", "category": "3p", "tags": None}})
    return p


def test_busca_real_so_a_55c6k():
    ofs = magalu.parse_busca(BUSCA)
    assert {o.id for o in ofs} == {"240162800-magazineluiza", "kc7h6f4k4b-lojascolombooficial"}
    o1p = next(o for o in ofs if o.vendedor == "Magalu")
    assert (o1p.preco, o1p.preco_pix) == (3749.0, 3561.55)
    assert o1p.extra["anuncio"] == "240162700" and o1p.extra["vendedor_id"] == "magazineluiza"
    assert o1p.url.startswith("https://www.magazineluiza.com.br/") and "/p/240162700/" in o1p.url
    assert "seller_id" not in o1p.url  # vendedor do buy box: link sem seletor
    produtos, pagina, paginas = magalu.info_busca(BUSCA)
    assert (pagina, paginas) == (1, 1) and len(produtos) == 4  # os 2 controles remotos ficam de fora


def test_produto_1p_compativel_com_o_parse_antigo():
    o, cupons = magalu.parse_produto(P1P)
    assert o.id == "240162800-magazineluiza" and o.parcelado == "10x R$ 374,90 sem juros"
    ofs, cps, variacoes = magalu.parse_produto_todas(P1P)
    assert [x.id for x in ofs] == ["240162800-magazineluiza"]
    assert variacoes == []  # 65" e 75" não entram


def test_um_oferta_por_vendedor_da_lista_offers():
    ofs, _, _ = magalu.parse_produto_todas(_html_produto(_com_outro_vendedor()))
    por_id = {o.id: o for o in ofs}
    assert set(por_id) == {"240162800-magazineluiza", "240162800-lojaxyz"}
    x = por_id["240162800-lojaxyz"]
    assert x.vendedor == "Loja XYZ" and x.extra["vendedor_id"] == "lojaxyz" and x.extra["anuncio"] == "240162700"
    # a lista só traz o Pix: o do cartão fica vazio (nunca repetir o Pix como cartão)
    assert (x.preco, x.preco_pix, x.parcelado) == (None, 3400.0, None)
    assert x.url.endswith("/p/240162700/et/elit/?seller_id=lojaxyz")


def test_variacao_de_outro_tamanho_e_rejeitada():
    p = _produto(P1P)
    p["variationId"] = "240162600"  # a página seria a do 65" (título trocado de propósito)
    assert magalu.parse_produto_todas(_html_produto(p)) == ([], [], [])
    p = _produto(P1P)
    p["available"] = False
    assert magalu.parse_produto_todas(_html_produto(p)) == ([], [], [])


def test_variacao_55_nova_vira_candidata():
    p = _produto(P1P)
    p["variations"].append({"id": "abc123def4", "label": "Polegadas", "type": "inch", "value": "55\"",
                            "available": True, "path": "smart-tv-55-tcl-55c6k-full/p/abc123def4/et/elit/"})
    _, _, variacoes = magalu.parse_produto_todas(_html_produto(p))
    assert variacoes == ["/magazinecanaltechbr/smart-tv-55-tcl-55c6k-full/p/abc123def4/et/elit/"]


def test_anuncios_do_estado_so_os_ultimos_14_dias(tmp_path):
    def reg(url, dias, tipo="loja"):
        return {"tipo": tipo, "url": url, "ultima_vez": (agora() - timedelta(days=dias)).isoformat(timespec="seconds")}

    estado = {"ofertas": {
        "magalu:a-x": reg("https://www.magazineluiza.com.br/tv-55c6k/p/aaaa111111/et/elit/", 1),
        "magalu:b-x": reg("https://www.magazineluiza.com.br/tv-55c6k/p/bbbb222222/et/elit/", 20),
        "magalu:c-x": reg("https://www.magazineluiza.com.br/tv-55c6k/p/cccc333333/et/elit/", 3),
        "zoom:d": reg("https://www.magazineluiza.com.br/tv-55c6k/p/dddd444444/et/elit/", 1),
        "magalu:e": reg("https://www.magazineluiza.com.br/tv-55c6k/p/eeee555555/et/elit/", 1, tipo="post"),
    }}
    arq = tmp_path / "state_cloud.json"
    arq.write_text(json.dumps(estado), encoding="utf-8")
    urls = magalu.anuncios_do_estado(arquivo=arq)
    assert [magalu.id_anuncio(u) for u in urls] == ["aaaa111111", "cccc333333"]
    assert magalu.anuncios_do_estado(arquivo=tmp_path / "nao_existe.json") == []


def test_urls_do_magazinevoce_e_do_site():
    u = "https://www.magazineluiza.com.br/slug-55c6k/p/kb7d86eh39/et/elit/"
    assert magalu._url_mv(u) == "https://www.magazinevoce.com.br/magazinecanaltechbr/slug-55c6k/p/kb7d86eh39/et/elit/"
    assert magalu._url_mv("/magazinecanaltechbr/x/p/1/et/elit/") == "https://www.magazinevoce.com.br/magazinecanaltechbr/x/p/1/et/elit/"
    assert magalu.com_vendedor(u + "?seller_id=a", "b") == u + "?seller_id=b"
    assert magalu.id_anuncio(u + "?seller_id=a") == "kb7d86eh39"


class _SiteFalso:
    """Serve as fixtures por URL e conta as requisições (404 para anúncio que saiu do ar)."""

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


@pytest.fixture
def sem_pausa(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAGALU_PAUSA_S", 0)
    monkeypatch.setattr(config, "MAGALU_ANUNCIOS_EXTRA", [])
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)  # estado vazio: nada de docs/data nos testes
    return tmp_path


def test_coletar_todos_os_vendedores_e_completa_o_de_fora_do_buybox(monkeypatch, sem_pausa):
    # o 1P com um 2º vendedor; a página ?seller_id=lojaxyz mostra esse vendedor com cartão e parcelado
    p = _com_outro_vendedor("3400.00")
    pv = _produto(P1P)
    pv["seller"] = {"id": "lojaxyz", "description": "Loja XYZ", "category": "3p", "tags": []}
    pv["price"] = {"paymentMethodDescription": "no Pix", "price": "4199.00", "fullPrice": "3579.00",
                   "bestPrice": "3400.00"}
    pv["installment"] = {"quantity": 10, "amount": "357.90", "interest": "0.00"}
    site = _SiteFalso({"seller_id=lojaxyz": _html_produto(pv), "/p/240162700/": _html_produto(p),
                       "/p/kc7h6f4k4b/": PCOLOMBO, "/busca/": BUSCA})
    monkeypatch.setattr(magalu, "get_html", site)
    ofertas, cupons = magalu.Magalu().coletar()
    por_id = {o.id: o for o in ofertas}
    assert set(por_id) == {"240162800-magazineluiza", "240162800-lojaxyz", "kc7h6f4k4b-lojascolombooficial"}
    x = por_id["240162800-lojaxyz"]
    assert (x.preco, x.preco_pix, x.parcelado) == (3579.0, 3400.0, "10x R$ 357,90 sem juros")
    assert x.url.endswith("?seller_id=lojaxyz") and x.extra["vendedor_id"] == "lojaxyz"
    assert len(site.pedidas) <= config.MAGALU_MAX_REQUISICOES
    # 4 buscas (uma por termo) + 2 anúncios + 1 página do vendedor de fora do buy box
    assert sum("/busca/" in u for u in site.pedidas) == len(config.MAGALU_TERMOS)


def test_coletar_respeita_o_teto_e_pula_anuncio_que_saiu_do_ar(monkeypatch, sem_pausa):
    estado = {"ofertas": {f"magalu:x{i}": {
        "tipo": "loja", "url": f"https://www.magazineluiza.com.br/tv-55c6k/p/zz{i:08d}/et/elit/",
        "ultima_vez": agora().isoformat(timespec="seconds")} for i in range(20)}}
    (sem_pausa / "state_cloud.json").write_text(json.dumps(estado), encoding="utf-8")
    site = _SiteFalso({"/p/240162700/": P1P, "/p/kc7h6f4k4b/": PCOLOMBO, "/busca/": BUSCA})
    monkeypatch.setattr(magalu, "get_html", site)
    ofertas, _ = magalu.Magalu().coletar()
    assert len(site.pedidas) == config.MAGALU_MAX_REQUISICOES  # 20 anúncios antigos, mas só até o teto
    assert {o.id for o in ofertas} == {"240162800-magazineluiza", "kc7h6f4k4b-lojascolombooficial"}


def test_coletar_sem_nada_e_com_erro_de_rede_vira_falha(monkeypatch, sem_pausa):
    def fora_do_ar(url, **kw):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(magalu, "get_html", fora_do_ar)
    with pytest.raises(RuntimeError, match="nenhuma oferta"):
        magalu.Magalu().coletar()


def test_proxima_pagina_da_busca_quando_a_primeira_trouxe_a_tv(monkeypatch, sem_pausa):
    nd = next_data(BUSCA)
    nd["props"]["pageProps"]["data"]["search"]["pagination"] = {"page": 1, "pages": 3}
    pag1 = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd, ensure_ascii=False)}</script>'
    monkeypatch.setattr(config, "MAGALU_TERMOS", ["tcl 55c6k"])
    site = _SiteFalso({"?page=2": BUSCA, "/busca/": pag1, "/p/240162700/": P1P, "/p/kc7h6f4k4b/": PCOLOMBO})
    monkeypatch.setattr(magalu, "get_html", site)
    magalu.Magalu().coletar()
    assert any(u.endswith("/busca/tcl+55c6k/?page=2") for u in site.pedidas)
    assert not any("?page=3" in u for u in site.pedidas)  # a página 2 diz 'pages: 1'


# ------------------------------------------------------------------------------------------------
# revisão de 19/09: variações do mesmo grupo, vendedor pedido na URL, orçamento e antirrobô
# ------------------------------------------------------------------------------------------------

_P55 = '55"'


def _com_variacao(pid: str) -> dict:
    p = _produto(P1P)
    p["variations"].append({"id": pid, "label": "Polegadas", "type": "inch", "value": _P55, "available": True,
                            "path": f"smart-tv-55-tcl-4k-uhd-miniled-55c6k-full/p/{pid}/et/elit/"})
    return p


def _variacao_55(pid: str, pix: str, cartao: str) -> dict:
    """Outra variação de 55 polegadas do MESMO grupo do 1P (product.id 240162800), do mesmo vendedor."""
    p = _com_variacao(pid)
    p["variationId"] = pid
    p["path"] = p["path"].replace("/p/240162700/", f"/p/{pid}/")
    p["price"] = dict(p["price"], bestPrice=pix, fullPrice=cartao)
    return p


def test_variacao_mais_cara_do_mesmo_grupo_nao_apaga_a_mais_barata(monkeypatch, sem_pausa):
    # product.id é o do GRUPO: as duas variações de 55" do Magalu viram o mesmo id '240162800-magazineluiza'
    site = _SiteFalso({"/p/240162701/": _html_produto(_variacao_55("240162701", "3999.00", "4199.00")),
                       "/p/240162700/": _html_produto(_com_variacao("240162701"))})
    monkeypatch.setattr(magalu, "get_html", site)
    monkeypatch.setattr(config, "MAGALU_TERMOS", [])
    ofertas, _ = magalu.Magalu().coletar()
    assert any("/p/240162701/" in u for u in site.pedidas), "a variação foi visitada"
    assert [(o.id, o.extra["anuncio"], o.preco_pix) for o in ofertas] == \
        [("240162800-magazineluiza", "240162700", 3561.55)], "fica a mais barata (a visitada por último era mais cara)"


def test_variacao_mais_barata_do_mesmo_grupo_substitui(monkeypatch, sem_pausa):
    site = _SiteFalso({"/p/240162701/": _html_produto(_variacao_55("240162701", "3300.00", "3499.00")),
                       "/p/240162700/": _html_produto(_com_variacao("240162701"))})
    monkeypatch.setattr(magalu, "get_html", site)
    monkeypatch.setattr(config, "MAGALU_TERMOS", [])
    ofertas, _ = magalu.Magalu().coletar()
    assert [(o.extra["anuncio"], o.preco_pix) for o in ofertas] == [("240162701", 3300.0)]
    assert "/p/240162701/" in ofertas[0].url


def test_pagina_do_produto_substitui_a_leitura_da_busca_do_mesmo_anuncio(monkeypatch, sem_pausa):
    # a busca e a página são o MESMO anúncio: vale a página (tem os cupons), mesmo se o preço dela for maior
    p = _produto(P1P)
    p["price"] = dict(p["price"], bestPrice="3600.00")
    site = _SiteFalso({"/busca/": BUSCA, "/p/240162700/": _html_produto(p), "/p/kc7h6f4k4b/": PCOLOMBO})
    monkeypatch.setattr(magalu, "get_html", site)
    monkeypatch.setattr(config, "MAGALU_TERMOS", ["tcl 55c6k"])
    ofertas, _ = magalu.Magalu().coletar()
    assert {o.id: o.preco_pix for o in ofertas}["240162800-magazineluiza"] == 3600.0


def test_anuncio_extra_com_vendedor_na_url_guarda_o_vendedor_no_link(monkeypatch, sem_pausa):
    # anúncio que só existe no MAGALU_ANUNCIOS_EXTRA (ou no estado), aberto com ?seller_id=<vendedor fora do buy box>
    pv = _produto(PCOLOMBO)
    pv["id"] = pv["variationId"] = "zz11223344"
    pv["path"] = pv["path"].replace("/p/kc7h6f4k4b/", "/p/zz11223344/")
    pv["variations"] = []
    pv["seller"] = {"id": "lojaxyz", "description": "Loja XYZ", "category": "3p", "tags": []}
    pv["offers"] = [{"sku": "1", "price": {"paymentMethodDescription": "no Pix", "bestPrice": "3300.00",
                                           "fullPrice": "3499.00", "price": "4199.00"},
                     "seller": {"id": "lojaxyz", "description": "Loja XYZ", "category": "3p"}}]
    extra = "https://www.magazineluiza.com.br/smart-tv-55c6k/p/zz11223344/et/elit/?seller_id=lojaxyz"
    monkeypatch.setattr(config, "MAGALU_ANUNCIOS_EXTRA", [extra])
    monkeypatch.setattr(config, "MAGALU_TERMOS", [])
    site = _SiteFalso({"/p/zz11223344/": _html_produto(pv), "/p/240162700/": P1P})
    monkeypatch.setattr(magalu, "get_html", site)
    ofertas, _ = magalu.Magalu().coletar()
    x = next(o for o in ofertas if o.extra["anuncio"] == "zz11223344")
    assert x.url.endswith("/p/zz11223344/et/elit/?seller_id=lojaxyz"), "o link abre o vendedor desta oferta"
    # e o testador consegue escolher esse vendedor pela URL
    from monitor.carrinho import Magalu as CarrinhoMagalu
    assert CarrinhoMagalu._seller_da_url(x.url) == "lojaxyz"
    # o 1P (sem seletor na URL pedida) continua sem seller_id no link
    p1 = next(o for o in ofertas if o.extra["anuncio"] == "240162700")
    assert "seller_id" not in p1.url


def _http_erro(status: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(str(status), response=resp)


@pytest.mark.parametrize("status", [403, 429])
def test_bloqueio_403_ou_429_para_a_coleta_na_hora(monkeypatch, sem_pausa, status):
    pedidas = []

    def bloqueado(url, **kw):
        pedidas.append(url)
        raise _http_erro(status)

    monkeypatch.setattr(magalu, "get_html", bloqueado)
    with pytest.raises(RuntimeError, match="nenhuma oferta"):
        magalu.Magalu().coletar()
    assert len(pedidas) == 1, "não insiste depois do bloqueio"


def test_bloqueio_no_meio_guarda_o_que_ja_veio(monkeypatch, sem_pausa):
    pedidas = []

    def site(url, **kw):
        pedidas.append(url)
        if "/busca/" in url:
            return BUSCA
        raise _http_erro(429)

    monkeypatch.setattr(magalu, "get_html", site)
    monkeypatch.setattr(config, "MAGALU_TERMOS", ["tcl 55c6k", "55c6k"])
    ofertas, _ = magalu.Magalu().coletar()
    assert {o.id for o in ofertas} == {"240162800-magazineluiza", "kc7h6f4k4b-lojascolombooficial"}
    assert len(pedidas) == 3, "2 buscas e a 1ª página que deu 429; nada depois"


def test_vendedor_de_fora_do_buybox_antes_dos_anuncios_do_estado(monkeypatch, sem_pausa):
    # 20 anúncios antigos no estado (mortos): a página do vendedor de fora do buy box vem antes deles
    estado = {"ofertas": {f"magalu:x{i}": {
        "tipo": "loja", "url": f"https://www.magazineluiza.com.br/tv-55c6k/p/zz{i:08d}/et/elit/",
        "ultima_vez": agora().isoformat(timespec="seconds")} for i in range(20)}}
    (sem_pausa / "state_cloud.json").write_text(json.dumps(estado), encoding="utf-8")
    pv = _produto(P1P)
    pv["seller"] = {"id": "lojaxyz", "description": "Loja XYZ", "category": "3p", "tags": []}
    pv["price"] = {"paymentMethodDescription": "no Pix", "price": "4199.00", "fullPrice": "3579.00",
                   "bestPrice": "3400.00"}
    pv["installment"] = {"quantity": 10, "amount": "357.90", "interest": "0.00"}
    site = _SiteFalso({"seller_id=lojaxyz": _html_produto(pv), "/p/240162700/": _html_produto(_com_outro_vendedor()),
                       "/p/kc7h6f4k4b/": PCOLOMBO, "/busca/": BUSCA})
    monkeypatch.setattr(magalu, "get_html", site)
    ofertas, _ = magalu.Magalu().coletar()
    x = {o.id: o for o in ofertas}["240162800-lojaxyz"]
    assert x.parcelado == "10x R$ 357,90 sem juros", "a página do vendedor foi aberta"
    assert len(site.pedidas) == config.MAGALU_MAX_REQUISICOES, "o resto do orçamento vai para o estado"
    assert any("/p/zz000000" in u for u in site.pedidas)
    # a página do vendedor veio antes do 1º anúncio do estado
    primeiro_estado = next(i for i, u in enumerate(site.pedidas) if "/p/zz000000" in u)
    assert any("seller_id=lojaxyz" in u for u in site.pedidas[:primeiro_estado])


# ------------------------------------------------------------------------------------------------
# variação que não é de polegadas não apaga o anúncio (revisão de 19/09, item B2)
# ------------------------------------------------------------------------------------------------

def _com_variacao_de_cor(valor: str = "Preto") -> dict:
    """O anúncio 1P real, mas o Magalu passou a variar COR em vez de polegadas."""
    p = _produto(P1P)
    p["variations"] = [
        {"id": "240162700", "label": "Cor", "type": "color", "value": valor, "available": True,
         "path": "smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq/p/240162700/et/elit/"},
        {"id": "240162701", "label": "Cor", "type": "color", "value": "Cinza", "available": True,
         "path": "smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-cinza/p/240162701/et/elit/"},
    ]
    return p


def test_variacao_de_cor_nao_apaga_o_anuncio_1p():
    # o título continua sendo o da 55C6K de 55": quem decide é ele, não o valor da variação
    ofertas, cupons, _ = magalu.parse_produto_todas(_html_produto(_com_variacao_de_cor()))
    assert [o.id for o in ofertas][:1] == ["240162800-magazineluiza"]
    assert magalu.parse_produto(_html_produto(_com_variacao_de_cor()))[0] is not None
    assert cupons == magalu.parse_produto_todas(P1P)[1], "os cupons do anúncio continuam sendo lidos"


def test_variacao_de_voltagem_na_busca_nao_apaga_o_anuncio():
    produto = dict(_produto(P1P), variations=[
        {"id": "240162700", "label": "Voltagem", "type": "voltage", "value": "110V", "available": True,
         "path": "smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz/p/240162700/et/elit/"}])
    nd = {"props": {"pageProps": {"data": {"search": {"products": [produto]}}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd, ensure_ascii=False)}</script>'
    assert [o.id for o in magalu.parse_busca(html)] == ["240162800-magazineluiza"]


def test_variacao_de_polegadas_continua_mandando():
    # a regra antiga não se perde: variação de tamanho de outro tamanho segue rejeitando o anúncio
    p = _produto(P1P)
    p["variationId"] = "240162600"
    assert magalu.parse_produto_todas(_html_produto(p)) == ([], [], [])
    # e uma variação de tamanho sem 'label'/'type', só com o valor '65"', também
    p = _produto(P1P)
    p["variations"] = [{"id": "240162700", "value": '65"', "available": True,
                        "path": "smart-tv-65-tcl-65c6k/p/240162700/et/elit/"}]
    assert magalu.parse_produto_todas(_html_produto(p)) == ([], [], [])


def test_variacao_que_nao_e_de_tamanho_nao_vira_candidata():
    _, _, variacoes = magalu.parse_produto_todas(_html_produto(_com_variacao_de_cor()))
    assert variacoes == [], "a outra cor não é outro tamanho para visitar"
