"""Mercado Livre: todas as opções do catálogo MLB48808732 + anúncios fora do catálogo (19/09/2026).

Fixtures: trechos reais de 19/09 (cartões da busca 'tcl-55c6k', componente seller_data do catálogo e
de um anúncio avulso de vendedor com 0 vendas a R$ 2.769). O Chrome nunca abre: _abrir é trocado.
"""

import json
from pathlib import Path

from monitor import config
from monitor.sources import playwright_sources as ps

FX = Path(__file__).parent / "fixtures"
BUSCA = (FX / "ml_busca_2026-09-19.html").read_text(encoding="utf-8")
ITEM_NOVO = (FX / "ml_item_vendedor_novo_2026-09-19.html").read_text(encoding="utf-8")
CAT_VEND = (FX / "ml_catalogo_vendedor_2026-09-19.html").read_text(encoding="utf-8")
TITULO = "Smart Tv Tcl 55 Polegadas Qd-Mini Led 4k C6k Wifi Bluetooth Google Tv 4 Hdmi 144hz Hdr10+ 55c6k"
JSONLD = {"@context": "https://schema.org", "@type": "Product", "name": TITULO,
          "offers": {"@type": "Offer", "price": 3749, "priceCurrency": "BRL",
                     "availability": "https://schema.org/InStock", "url": config.URL_ML_CATALOGO}}
# catálogo de 19/09: uma opção só no buy box (Magalu, 3.749 em 10x) e "Outras opções" vazia no HTML
CATALOGO = (f'<html><head><script type="application/ld+json">{json.dumps(JSONLD)}</script></head>'
            f"<body><h1>{TITULO}</h1>" + CAT_VEND.split("<body>", 1)[1])
TEXTO_CAT = f"{TITULO}\nR$\n3.749\n10x R$ 374,90 sem juros\nOutras opções de compra\n"


def _stub(monkeypatch, tmp_path, paginas: dict[str, tuple[str, str]], capt=None):
    monkeypatch.setattr(ps, "MARCA_BLOQUEIO_ML", tmp_path / "ml_bloqueado_em")
    chamadas = []

    def abrir(url, *a, **k):
        chamadas.append(url)
        for trecho, (html, texto) in paginas.items():
            if trecho in url:
                return html, texto, list(capt or []) if trecho == "/p/MLB48808732" else []
        raise AssertionError(f"URL inesperada {url}")

    monkeypatch.setattr(ps, "_abrir", abrir)
    return chamadas


def test_busca_real_cartao_de_catalogo_usa_o_item_vencedor():
    por_id = {o.id: o for o in ps.MercadoLivre._parse_lista(BUSCA)}
    assert set(por_id) == {"MLB7574364080", "MLB7523184294"}  # a 65C6K fica de fora
    cat = por_id["MLB7574364080"]
    assert cat.extra["catalogo"] == "MLB48808732" and cat.extra["item_id"] == "MLB7574364080"
    assert cat.url.endswith("/p/MLB48808732?pdp_filters=item_id%3AMLB7574364080")
    assert (cat.preco, cat.parcelado, cat.vendedor) == (3749.0, "10x R$ 374,90 sem juros", "Magalu")
    avulso = por_id["MLB7523184294"]
    assert avulso.url.startswith("https://produto.mercadolivre.com.br/MLB-7523184294")
    assert avulso.preco == 2769.0 and "catalogo" not in avulso.extra


def test_vendas_do_vendedor():
    novo = ps._ml_vendedor(ITEM_NOVO)
    assert novo["vendas"] == 0 and novo["vendedor"] == "FEGU20240217181722" and novo["vendedor_id"] == "1688518512"
    loja = ps._ml_vendedor(CAT_VEND)
    assert loja["vendas"] == 50000 and loja["tipo"] == "official_store" and loja["item_id"] == "MLB7574364080"
    assert [ps._ml_numero_vendas(t) for t in ("0", "+500", "+50 mil", "+1 M", "+5mil", "1.234", "")] == \
        [0, 500, 50000, 1000000, 5000, 1234, None]


def test_coletar_catalogo_e_descarta_anuncio_barato_de_vendedor_sem_vendas(monkeypatch, tmp_path, capsys):
    chamadas = _stub(monkeypatch, tmp_path, {
        "/p/MLB48808732": (CATALOGO, TEXTO_CAT), "lista.mercadolivre": (BUSCA, "busca"),
        "MLB-7523184294": (ITEM_NOVO, "Vendido por FEGU20240217181722")})
    ofertas, _ = ps.MercadoLivre().coletar()
    assert len(chamadas) <= config.ML_MAX_CARGAS
    (o,) = ofertas
    # opção única: o id é o item do vendedor (o mesmo de quando o buy box tem várias opções)
    assert o.id == "MLB7574364080" and o.vendedor == "Magalu" and o.preco == 3749.0
    assert o.url == config.URL_ML_CATALOGO + "?pdp_filters=item_id%3AMLB7574364080"
    assert o.extra["item_id"] == "MLB7574364080" and o.extra["vendedor_id"] == "3592255542"
    assert o.extra["catalogo"] == "MLB48808732" and o.extra["anuncio"] == "MLB7574364080"
    assert o.extra["opcoes_no_catalogo"] == 2  # "Ver 2 opções": a lista completa pede login
    log = capsys.readouterr().out
    assert "MLB7523184294" in log and "descartado" in log  # o descarte vai para o log


def test_anuncio_fora_do_catalogo_com_vendedor_bom_entra(monkeypatch, tmp_path):
    bom = ITEM_NOVO.replace('"text": "0", "accessibility_text": "0 Vendas"',
                            '"text": "+5 mil", "accessibility_text": "mais de 5 mil Vendas"')
    assert bom != ITEM_NOVO
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT), "lista.mercadolivre": (BUSCA, "busca"),
                                  "MLB-7523184294": (bom, "")})
    por_id = {o.id: o for o in ps.MercadoLivre().coletar()[0]}
    assert set(por_id) == {"MLB7574364080", "MLB7523184294"}
    x = por_id["MLB7523184294"]
    assert x.extra["vendedor_conferido"] is True and x.extra["vendas_vendedor"] == 5000
    assert x.vendedor == "FEGU20240217181722" and x.extra["item_id"] == "MLB7523184294"


def test_anuncio_mais_caro_que_o_catalogo_entra_sem_pagina_extra(monkeypatch, tmp_path):
    busca = BUSCA.replace("2.769", "3.999")
    chamadas = _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                             "lista.mercadolivre": (busca, "busca")})
    por_id = {o.id: o for o in ps.MercadoLivre().coletar()[0]}
    assert por_id["MLB7523184294"].preco == 3999.0 and por_id["MLB7523184294"].extra["vendedor_conferido"] is False
    assert len(chamadas) == 2


def test_outras_opcoes_de_compra_vindas_do_json_adiado(monkeypatch, tmp_path):
    # a página pede /p/api/deferred?component_ids=bbw_alternatives ao rolar; itens no formato do buy box
    item = {"item_id": "MLB9999999999", "type": "OTHER", "selected": False, "components": [
        {"id": "price", "price": {"value": 3690, "original_value": None}},
        {"id": "seller", "text": "Vendido por {seller}", "values": {"seller": {"text": "Loja Boa"}}},
        {"id": "payment", "subtitles": [{"text": "10x {v} sem juros", "values": {"v": {"type": "price", "value": 369}}}]},
    ]}
    capt = [{"url": "https://www.mercadolivre.com.br/p/api/deferred?id=MLB48808732&component_ids=bbw_alternatives",
             "json": {"components": {"bbw_alternatives": {"items": [item]}}}}]
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                  "lista.mercadolivre": ("<html></html>", "")}, capt=capt)
    por_id = {o.id: o for o in ps.MercadoLivre().coletar()[0]}
    x = por_id["MLB9999999999"]
    assert (x.preco, x.vendedor, x.parcelado) == (3690.0, "Loja Boa", "10x R$ 369,00 sem juros")
    assert x.url.endswith("?pdp_filters=item_id%3AMLB9999999999") and x.extra["catalogo"] == "MLB48808732"


# ------------------------------------------------------------------------------------------------
# revisao de 19/09 (M2): so entra como "outra opcao" o que a resposta prova ser opcao DESTE catalogo
# ------------------------------------------------------------------------------------------------

def _item(item_id: str, preco: float, vendedor: str = "Outra Loja", tipo: str = "OTHER", titulo=None) -> dict:
    comps = [{"id": "price", "price": {"value": preco}},
             {"id": "seller", "text": "Vendido por {seller}", "values": {"seller": {"text": vendedor}}}]
    if titulo:
        comps.insert(0, {"id": "title", "title": {"text": titulo}})
    return {"item_id": item_id, "type": tipo, "selected": False, "components": comps}


def _capt(corpo: dict, url: str = "https://www.mercadolivre.com.br/p/api/deferred?id=MLB48808732"
                                 "&component_ids=bbw_alternatives,reco") -> list[dict]:
    return [{"url": url, "json": corpo}]


def test_recomendado_do_deferred_nao_vira_anuncio_da_55c6k(monkeypatch, tmp_path, capsys):
    """O carrossel de recomendados vem na MESMA resposta de /p/api/deferred que as outras opcoes.
    Sem conferir de que componente a lista veio, ele virava um anuncio da 55C6K com o titulo e a URL
    da TV e um preco que nao e dela (mesma classe do erro da Casas Bahia de 17/09)."""
    capt = _capt({"components": {"bbw_alternatives": {"items": []},
                                 "reco_carousel": {"items": [_item("MLB3333333333", 1899)]}}})
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                  "lista.mercadolivre": ("<html></html>", "")}, capt=capt)
    ofertas = ps.MercadoLivre().coletar()[0]
    assert "MLB3333333333" not in {o.id for o in ofertas}, "produto recomendado virou anuncio da 55C6K"
    assert {o.id for o in ofertas} == {"MLB7574364080"}


def test_resposta_de_outro_catalogo_nao_entra(monkeypatch, tmp_path):
    """Outra aba/pedido do ML pode devolver as opcoes de OUTRO catalogo na mesma captura."""
    capt = _capt({"components": {"bbw_alternatives": {"items": [_item("MLB8888888888", 3690)]}}},
                 url="https://www.mercadolivre.com.br/p/api/deferred?id=MLB99999999&component_ids=bbw_alternatives")
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                  "lista.mercadolivre": ("<html></html>", "")}, capt=capt)
    assert {o.id for o in ps.MercadoLivre().coletar()[0]} == {"MLB7574364080"}


def test_opcao_com_titulo_de_outro_produto_e_descartada(monkeypatch, tmp_path, capsys):
    capt = _capt({"components": {"bbw_alternatives": {"items": [
        _item("MLB7777777777", 3600, titulo="Suporte de parede para TV 55 polegadas")]}}})
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                  "lista.mercadolivre": ("<html></html>", "")}, capt=capt)
    assert {o.id for o in ps.MercadoLivre().coletar()[0]} == {"MLB7574364080"}
    assert "MLB7777777777" in capsys.readouterr().out


def test_opcao_com_preco_fora_da_faixa_da_rodada_e_descartada(monkeypatch, tmp_path, capsys):
    # o buy box desta rodada esta em R$ 3.749; R$ 899 nao e o preco desta TV
    capt = _capt({"components": {"bbw_alternatives": {"items": [_item("MLB6666666666", 899)]}}})
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                  "lista.mercadolivre": ("<html></html>", "")}, capt=capt)
    assert {o.id for o in ps.MercadoLivre().coletar()[0]} == {"MLB7574364080"}
    assert "MLB6666666666" in capsys.readouterr().out


def test_opcao_do_catalogo_com_titulo_da_tv_continua_entrando(monkeypatch, tmp_path):
    capt = _capt({"components": {"bbw_alternatives": {"items": [
        _item("MLB5555555555", 3690, vendedor="Loja Boa", titulo=TITULO)]}}})
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                  "lista.mercadolivre": ("<html></html>", "")}, capt=capt)
    por_id = {o.id: o for o in ps.MercadoLivre().coletar()[0]}
    assert por_id["MLB5555555555"].preco == 3690.0 and por_id["MLB5555555555"].vendedor == "Loja Boa"


def test_listas_de_opcoes_so_debaixo_do_componente_do_catalogo():
    corpo = {"components": {"bbw_alternatives": {"items": [{"item_id": "MLB1"}]},
                            "reco_carousel": {"items": [{"item_id": "MLB2"}]}}}
    achadas = [i["item_id"] for lista in ps._listas_de_opcoes(corpo) for i in lista]
    assert achadas == ["MLB1"]


def test_catalogo_bloqueado_usa_o_cartao_da_busca(monkeypatch, tmp_path):
    bloqueio = ('<html><body><a href="https://www.mercadolivre.com.br/gz/account-verification?go=suspicious-traffic">'
                "x</a></body></html>")
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (bloqueio, ""), "lista.mercadolivre": (BUSCA, "busca")})
    por_id = {o.id: o for o in ps.MercadoLivre().coletar()[0]}
    # o cartão do catálogo entra com o item vencedor; o avulso barato não pôde ser conferido (sem páginas)
    assert set(por_id) == {"MLB7574364080"}
    assert not (tmp_path / "ml_bloqueado_em").exists()


def test_sessao_reaproveita_a_janela_e_nao_abre_chrome_sem_uso(monkeypatch):
    abertas = []

    class _Falsa(ps._Sessao):
        def abrir(self, url, *a):
            abertas.append((id(self), url))
            return "<html></html>", "", []

        def fechar(self):
            abertas.append((id(self), "fechou"))

    monkeypatch.setattr(ps, "_Sessao", _Falsa)
    with ps.sessao("ml"):
        ps._abrir("https://a", perfil="ml")
        ps._abrir("https://b", perfil="ml")
    assert [u for _, u in abertas] == ["https://a", "https://b", "fechou"]
    assert len({s for s, _ in abertas}) == 1  # mesma janela
    assert "ml" not in ps._SESSOES


def test_opcao_legitima_bem_mais_barata_entra(monkeypatch, tmp_path):
    # a rede de segurança de preço não pode derrubar justamente a promoção que o monitor procura
    capt = _capt({"components": {"bbw_alternatives": {"items": [
        _item("MLB4444444444", 2499, vendedor="Loja Boa", titulo=TITULO)]}}})
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                  "lista.mercadolivre": ("<html></html>", "")}, capt=capt)
    por_id = {o.id: o for o in ps.MercadoLivre().coletar()[0]}
    assert por_id["MLB4444444444"].melhor_preco == 2499.0


def test_opcao_com_rotulo_do_buy_box_no_lugar_do_titulo_entra(monkeypatch, tmp_path):
    # "Melhor preço" é rótulo do buy box, não nome de outro produto: não pode descartar a opção
    capt = _capt({"components": {"bbw_alternatives": {"items": [
        _item("MLB3333333333", 3690, vendedor="Loja Boa", titulo="Melhor preço")]}}})
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                  "lista.mercadolivre": ("<html></html>", "")}, capt=capt)
    assert "MLB3333333333" in {o.id for o in ps.MercadoLivre().coletar()[0]}


def test_opcao_absurdamente_cara_e_descartada(monkeypatch, tmp_path, capsys):
    capt = _capt({"components": {"bbw_alternatives": {"items": [_item("MLB2222222222", 12000)]}}})
    _stub(monkeypatch, tmp_path, {"/p/MLB48808732": (CATALOGO, TEXTO_CAT),
                                  "lista.mercadolivre": ("<html></html>", "")}, capt=capt)
    assert {o.id for o in ps.MercadoLivre().coletar()[0]} == {"MLB7574364080"}
    assert "MLB2222222222" in capsys.readouterr().out
