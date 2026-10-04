"""Vendedor dos preços do PS5 na busca da Amazon (03/10/2026): o cartão da busca não diz quem vende (id
'<ASIN>-destaque') e o PS5 Digital mais barato (R$ 4.084,90) era de um vendedor com 40% de avaliações positivas. A
fonte abre o painel de ofertas do ASIN (por HTTP; Chrome se falhar) e a confiança passa a ver o vendedor, as avaliações
e o Full de cada preço.

Fixture: o painel de ofertas real do B0CQKJN2C6 (PS5 Slim Digital) de 03/10/2026, sem login, aparado aos blocos das
ofertas. Nenhum teste acessa a rede nem abre o Chrome.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from monitor import config, confianca
from monitor.models import Oferta
from monitor.sources import amazon
from monitor.sources import playwright_sources as ps

FX = Path(__file__).parent / "fixtures"
AOD = (FX / "amazon_aod_ps5_2026-10-03.html").read_text(encoding="utf-8")
ASIN = "B0CQKJN2C6"


def _cartao(asin: str, titulo: str, pix: str, parcelas: str = "") -> str:
    return (f'<div data-component-type="s-search-result" data-asin="{asin}"><h2><span>{titulo}</span></h2>'
            f'<span class="a-price"><span class="a-offscreen">R${pix}</span></span>'
            f'<span>à vista no Pix</span>{parcelas}<span>Entrega GRÁTIS: seg., 12 de out.</span></div>')


BUSCA = ("<html><body>"
         + _cartao(ASIN, "PlayStation®5 Slim Edição Digital", "4.084,90",
                   "<span>em até 10x de R$ 453,88 sem juros</span>")
         + _cartao("B0F8R9NDXC", "PlayStation®5 Slim com leitor de disco", "4.649,06")
         + _cartao("B0GWNKJDCZ", "Sony PlayStation 5 Edição Digital 825GB 1 Controle", "4.105,47")
         + "</body></html>")


@pytest.fixture
def sem_rede(monkeypatch):
    """GTA sem página (o foco aqui é a busca), busca dos consoles fixa e nada de Chrome por padrão."""
    cargas = []

    def abrir(url, *a, **k):
        cargas.append(url)
        if "/s?" in url:
            return BUSCA, "", []
        if "aodAjaxMain" in url:
            raise RuntimeError("Chrome não deveria abrir o painel (o HTTP deu certo)")
        return "", "", []

    monkeypatch.setattr(ps, "_abrir", abrir)
    monkeypatch.setattr(ps, "_avaliar", lambda *a, **k: {"ok": True, "mudou": False})
    monkeypatch.setattr(config, "URLS_AMAZON_BUSCA_PRODUTOS", ("https://www.amazon.com.br/s?k=console+playstation+5",))
    return cargas


def _http(paineis: dict[str, str], pedidos: list[str]):
    def get_html(url, *a, **k):
        pedidos.append(url)
        for asin, html in paineis.items():
            if f"asin={asin}" in url:
                return html
        raise RuntimeError("503 Service Unavailable")
    return get_html


def test_painel_troca_o_cartao_da_busca_pelos_vendedores(monkeypatch, sem_rede):
    pedidos: list[str] = []
    monkeypatch.setattr(amazon, "get_html", _http({ASIN: AOD}, pedidos))
    monkeypatch.setattr(config, "AMAZON_MAX_PAINEIS_PRODUTOS", 1)
    ofs, _ = amazon.AmazonProdutos().coletar()
    por_id = {o.id: o for o in ofs}
    # o mais barato sem vendedor foi o aberto, e o cartão dele saiu (os vendedores do painel ficam no lugar)
    assert pedidos == [config.URL_AMAZON_OFERTAS.format(asin=ASIN)]
    assert f"{ASIN}-destaque" not in por_id
    domus = por_id[f"{ASIN}-A5AWFXGJJU4NV"]
    assert (domus.vendedor, domus.modelo, domus.preco_pix, domus.extra["destaque"]) == (
        "DOMUS SHOP", "PS5_DIGITAL", 4084.9, True)
    # o vendedor do destaque é o do cartão (mesmo preço): herda o preço no cartão e o parcelado
    assert (domus.preco, domus.parcelado) == (4538.8, "10x R$ 453,88 sem juros")
    assert domus.extra["ficha"]["positivas_pct"] == 40 and domus.extra["ficha"]["full"] is False
    ideolab = por_id[f"{ASIN}-A7PTFS3I4Y64X"]
    assert (ideolab.preco, ideolab.parcelado, ideolab.preco_pix) == (None, None, 4084.9)
    assert len([o for o in ofs if o.extra.get("asin") == ASIN]) == 6
    # além do limite: os outros ASINs continuam com o cartão da busca (sem vendedor)
    assert {"B0F8R9NDXC-destaque", "B0GWNKJDCZ-destaque"} <= set(por_id)
    assert {o.fonte for o in ofs} == {"amazon.produtos"}


def test_um_de_cada_produto_antes_do_segundo_do_mesmo(monkeypatch, sem_rede):
    pedidos: list[str] = []
    monkeypatch.setattr(amazon, "get_html", _http({ASIN: AOD}, pedidos))
    monkeypatch.setattr(config, "AMAZON_MAX_PAINEIS_PRODUTOS", 2)
    amazon.AmazonProdutos().coletar()
    # o PS5 Digital mais barato e depois o com leitor (outro produto), antes do 2º PS5 Digital (B0GWNKJDCZ)
    assert [u.split("asin=")[1].split("&")[0] for u in pedidos] == [ASIN, "B0F8R9NDXC"]


def test_http_falhou_abre_no_chrome_e_sem_painel_fica_o_cartao(monkeypatch, sem_rede, capsys):
    monkeypatch.setattr(amazon, "get_html", _http({}, []))
    monkeypatch.setattr(config, "AMAZON_MAX_PAINEIS_PRODUTOS", 2)
    chrome = []

    def abrir(url, *a, **k):
        if "/s?" in url:
            return BUSCA, "", []
        if "aodAjaxMain" in url:
            chrome.append(url)
            if f"asin={ASIN}" in url:
                return AOD, "", []
            raise TimeoutError("o painel não carregou")
        return "", "", []

    monkeypatch.setattr(ps, "_abrir", abrir)
    ofs, _ = amazon.AmazonProdutos().coletar()
    ids = {o.id for o in ofs}
    assert len(chrome) == 2
    assert f"{ASIN}-A5AWFXGJJU4NV" in ids and f"{ASIN}-destaque" not in ids
    assert "B0F8R9NDXC-destaque" in ids   # o painel falhou: o preço da busca continua, sem vendedor
    assert "painel de ofertas B0F8R9NDXC" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------
# confiança: % de avaliações positivas do vendedor e a linha da busca sem vendedor
# ------------------------------------------------------------------------------------------------

def _ref(menor: float) -> confianca.Referencias:
    return confianca.Referencias(menor=(menor, "KaBuM!"), precos=[(menor, "KaBuM!")])


def _amazon(preco_pix: float, positivas: int | None = 40, avaliacoes: int = 2743, vid: str | None = "A5AWFXGJJU4NV"):
    ficha = {"avaliacoes_vendedor": avaliacoes, "full": False}
    if positivas is not None:
        ficha["positivas_pct"] = positivas
    return Oferta("amazon.produtos", "loja", "Amazon", "PlayStation®5 Slim Edição Digital",
                  amazon.url_vendedor(ASIN, vid), f"{ASIN}-{vid or 'destaque'}", preco_pix=preco_pix,
                  vendedor="DOMUS SHOP" if vid else None, modelo="PS5_DIGITAL",
                  extra={"asin": ASIN, "vendedor_id": vid, "ficha": ficha} if vid else {"asin": ASIN})


def test_mal_avaliado_com_preco_de_alerta_e_sinal_forte():
    sinais, feitas = confianca.sinais_da_oferta(_amazon(4084.90), _ref(4099.0))
    (s,) = [x for x in sinais if x.codigo == "vendedor_mal_avaliado"]
    assert s.forte and "40% de avaliações positivas (2.743 avaliações)" in s.texto
    assert confianca.decide(sinais) == confianca.SUSPEITO
    # não é prova: não vira reprovado automático (o vendedor é reavaliado a cada rodada)
    assert not confianca.reprova(sinais)


def test_mal_avaliado_com_preco_comum_e_sinal_fraco():
    sinais, _ = confianca.sinais_da_oferta(_amazon(4227.40), _ref(4099.0))
    (s,) = [x for x in sinais if x.codigo == "vendedor_mal_avaliado"]
    assert not s.forte and confianca.decide(sinais) == confianca.SEM_RISCO


@pytest.mark.parametrize("positivas,avaliacoes", [(60, 3579), (63, 81), (70, 702), (40, 2), (None, 2743)])
def test_grandes_lojas_da_amazon_e_conta_sem_historico_nao_caem_no_sinal(positivas, avaliacoes):
    # Magalu. 60%, TCL 63% e Lojas Colombo 70% em 03/10; com menos de 20 avaliações vale o "sem histórico"
    sinais, _ = confianca.sinais_da_oferta(_amazon(3000.0, positivas, avaliacoes), _ref(4099.0))
    assert "vendedor_mal_avaliado" not in [x.codigo for x in sinais]


def _estado(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    from monitor.estado import Estado
    return Estado("pc")


def _confiavel(preco_pix: float) -> Oferta:
    return Oferta("kabum", "loja", "KaBuM!", "PS5 Digital", "https://k/1", "k1", preco=4299.0, preco_pix=preco_pix,
                  vendedor="KaBuM!", modelo="PS5_DIGITAL")


def test_linha_da_busca_sem_vendedor_abaixo_da_confiavel_nao_alerta(tmp_path, monkeypatch):
    est = _estado(tmp_path, monkeypatch)
    sem_vendedor = _amazon(4084.90, vid=None)
    confianca.avaliar(est, [_confiavel(4099.0), sem_vendedor], rede=False)
    c = sem_vendedor.extra["confianca"]
    assert c["veredito"] == confianca.SUSPEITO and c["codigos"] == ["sem_vendedor"]
    assert "a busca da Amazon não diz quem vende" in c["sinais"][0]
    assert not c.get("reprovado_auto")


def test_linha_da_busca_sem_vendedor_acima_da_confiavel_segue_normal(tmp_path, monkeypatch):
    est = _estado(tmp_path, monkeypatch)
    sem_vendedor = _amazon(4300.0, vid=None)
    confianca.avaliar(est, [_confiavel(4099.0), sem_vendedor], rede=False)
    assert sem_vendedor.extra["confianca"]["veredito"] == confianca.SEM_RISCO


def test_aviso_sai_para_o_mal_avaliado_e_nao_para_a_linha_sem_vendedor(tmp_path, monkeypatch):
    from monitor.regras import CAB_SUSPEITO, gerar_alertas

    est = _estado(tmp_path, monkeypatch)
    est.bootstrap = False
    est._modelos_conhecidos.add("PS5_DIGITAL")   # a partida do PS5 já passou (na partida não sai aviso)
    mal = _amazon(4084.90)
    sem_vendedor = _amazon(4084.90, vid=None)
    sem_vendedor.id = "B0GWNKJDCZ-destaque"
    sem_vendedor.extra["asin"] = "B0GWNKJDCZ"
    ofertas = [_confiavel(4099.0), mal, sem_vendedor]
    confianca.avaliar(est, ofertas, rede=False)
    assert confianca.so_sem_vendedor(sem_vendedor) and not confianca.so_sem_vendedor(mal)
    msgs, _ = gerar_alertas(est, ofertas, [])
    avisos = [m for m in msgs if m.startswith(CAB_SUSPEITO)]
    assert len(avisos) == 1 and "DOMUS SHOP" in avisos[0] and "40% de avaliações positivas" in avisos[0]
    # nenhuma das duas ganha alerta de preço (🎯/🏆/🔻)
    assert not [m for m in msgs if not m.startswith(CAB_SUSPEITO) and "4.084,90" in m]
