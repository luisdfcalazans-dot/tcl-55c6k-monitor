"""Junção das duas frentes da 65C6K (26/09/2026): o que a COLETA grava (latest_<modo>.json com o campo `modelo`, ids
únicos por modelo) é o que o TESTADOR de cupons lê (um anúncio por modelo, carrinho com uma TV de cada modelo).

Coleta falsa (páginas do Magalu montadas a partir da página real de 25/09) e carrinho falso: nada acessa a rede, nenhum
navegador, nenhum perfil de loja.
"""

from __future__ import annotations

import json

from monitor import config, filtro
from monitor.carrinho import CATALOGOS_ML, mesmo_vendedor, modelo_do_titulo
from monitor.estado import Estado
from monitor.sources import magalu
from test_modelo_65c6k import P1P, _html_busca, _html_produto, _pagina_1p_65, _Site
from test_testador_anuncios import CarrinhoFalsoMagalu, amb, tc  # noqa: F401 - amb: fixture do testador


def _coleta_magalu(monkeypatch) -> tuple[list, list]:
    """Coleta do Magalu com a página do 1P (55" e 65") e a busca da 65" trazendo a Colombo."""
    colombo65 = {"id": "jcefd125c3", "variationId": "jcefd125c3", "available": True,
                 "title": "Smart TV TCL 65C6K 65 4K Mini LED Android TV Semp Tcl",
                 "path": "/magazinecanaltechbr/smart-tv-tcl-65c6k-65-4k/p/jcefd125c3/et/elit/",
                 "price": {"fullPrice": "5274.90", "bestPrice": "4747.41", "price": "5274.90"},
                 "installment": {"quantity": 10, "amount": "527.49", "interest": "0.00"},
                 "seller": {"id": "lojascolombooficial", "description": "Lojas Colombo Oficial", "category": "3p"}}
    site = _Site({"/busca/tcl+65c6k/": _html_busca([colombo65]), "/busca/": _html_busca([]),
                  "/p/240162600/": _html_produto(_pagina_1p_65()), "/p/240162700/": P1P})
    monkeypatch.setattr(magalu, "get_html", site)
    for k, v in (("MAGALU_PAUSA_S", 0), ("MAGALU_ANUNCIOS_EXTRA", [])):
        monkeypatch.setattr(config, k, v)
    return magalu.Magalu().coletar()


def test_o_latest_da_coleta_vira_um_anuncio_por_modelo_no_testador(amb, monkeypatch):
    ofertas, cupons = _coleta_magalu(monkeypatch)
    Estado("cloud").escreve_latest(ofertas, cupons)
    lt = json.loads((config.DIR_DADOS / "latest_cloud.json").read_text(encoding="utf-8"))
    assert {(o["id"], o["modelo"]) for o in lt["ofertas_loja"]} == {
        ("240162700-magazineluiza", "55C6K"), ("240162600-magazineluiza", "65C6K"),
        ("jcefd125c3-lojascolombooficial", "65C6K")}
    assert lt["alvos"]["65C6K"] == {"pix": config.ALVO_PIX_65, "parcelado": config.ALVO_PARCELADO_65}

    codigos, anuncios = tc.codigos_conhecidos(CarrinhoFalsoMagalu(amb.pasta))
    # a chave do testador ('<id do /p/>-<vendedor>') é a mesma da coleta: 55" e 65" do mesmo grupo não colidem
    assert [(a.chave, a.modelo, a.produto) for a in anuncios] == [
        ("240162700-magazineluiza", "55C6K", "240162700"),
        ("240162600-magazineluiza", "65C6K", "240162600"),
        ("jcefd125c3-lojascolombooficial", "65C6K", "jcefd125c3")]
    assert "LU300" in codigos, "o cupom do anúncio (nas duas páginas) é testado"
    ctx = tc.contexto_do_carrinho(anuncios)
    # a sacola devolve o id da variação: o testador sabe qual TV é qual
    assert ctx["ids_modelo"] == {"240162700": "55C6K", "240162600": "65C6K", "jcefd125c3": "65C6K"}
    assert ctx["restauraveis"] == ["55C6K", "65C6K"]
    grupos = tc.por_modelo(anuncios)
    assert [a.chave for a in grupos["65C6K"]] == ["240162600-magazineluiza", "jcefd125c3-lojascolombooficial"]


def test_cupom_da_pagina_do_anuncio_vai_na_frente_num_anuncio_novo(amb, monkeypatch):
    # rodada seca de 26/09: o 1P da 65" (anúncio novo, 29 códigos pendentes, ~9 testes por rodada) deixava o LU300 da
    # própria página para a 3ª rodada; ele vence em 30/09
    ofertas, cupons = _coleta_magalu(monkeypatch)
    Estado("cloud").escreve_latest(ofertas, cupons)
    _, anuncios = tc.codigos_conhecidos(CarrinhoFalsoMagalu(amb.pasta))
    a65 = next(a for a in anuncios if a.chave == "240162600-magazineluiza")
    assert a65.cupom == "LU300"
    fila = ["DIADOCLIENTE14H", "INFLU300", "CUPOM25R", "LU300", "VELHO"]
    testados = {"VELHO@240162600-magazineluiza": {"status": "recusado", "testado_em": "2026-09-20T10:00:00-03:00"}}
    assert tc.ordenar_fila(fila, testados, a65.chave, a65) == ["DIADOCLIENTE14H", "LU300", "INFLU300", "CUPOM25R",
                                                                "VELHO"]
    # já testado nele: volta à regra de sempre (recusa antiga vai para o fim)
    testados["LU300@240162600-magazineluiza"] = {"status": "recusado", "testado_em": "2026-09-20T10:00:00-03:00"}
    assert tc.ordenar_fila(fila, testados, a65.chave, a65)[-2:] == ["LU300", "VELHO"]
    # anúncio sem cupom na página: a ordem de antes
    assert tc.ordenar_fila(fila, {}, "x") == ["DIADOCLIENTE14H", "INFLU300", "CUPOM25R", "LU300", "VELHO"]


def test_testador_usa_os_alvos_e_catalogos_da_coleta(monkeypatch):
    assert CATALOGOS_ML == config.ML_CATALOGOS == {"55C6K": "MLB48808732", "65C6K": "MLB50368907"}
    monkeypatch.setattr(config, "ALVO_PIX_65", 3100.0)
    monkeypatch.setattr(config, "ALVO_PARCELADO_65", 3250.0)
    assert tc.alvos_do_modelo("65C6K") == (3100.0, 3250.0) == (config.alvo_pix("65C6K"), config.alvo_parcelado("65C6K"))


def test_par_55_65_e_da_55_na_coleta_e_de_nenhum_no_carrinho():
    t = "Smart TV TCL 55C6K/65C6K"
    assert filtro.modelo_do_titulo(t) == "55C6K"      # postagem "a partir de": o preço da menor
    assert modelo_do_titulo(t) is None                 # no carrinho, texto que serve para as duas não é nenhuma
    assert modelo_do_titulo("Smart TV TCL C6K 65 Polegadas 4K QLED Mini LED Preto Bivolt") == "65C6K"
    assert modelo_do_titulo("Smart TV TCL 65C7K 65 polegadas") is None


def test_vendedor_1p_da_amazon_com_o_nome_da_coleta_bate_com_a_pagina():
    # a coleta grava "Amazon.com.br Política de devolução" (bloco do painel) com o id A1ZZFT5FULY4LN; a página do
    # anúncio (smid=A1ZZFT5FULY4LN) diz "Vendido por Amazon.com.br", sem link de vendedor
    assert mesmo_vendedor(None, "Amazon.com.br", "A1ZZFT5FULY4LN", "Amazon.com.br Política de devolução") is True
    assert mesmo_vendedor(None, "Vendido por Amazon.com.br", "A1ZZFT5FULY4LN", "Amazon.com.br") is True
    assert mesmo_vendedor("ACUNARZFR75ET", "Magalu.", "A1ZZFT5FULY4LN", "Amazon.com.br Política de devolução") is False
