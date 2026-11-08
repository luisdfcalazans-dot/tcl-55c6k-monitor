"""PS5 do AliExpress (pedido de 08/11/2026): a página pública do item 1005010260639712 (Magalu Store, "Produto já no
Brasil") no modo pc e o preço com o melhor cupom AliExpress ativo.

Cobre: o parser (API mtop em JSONP e texto renderizado, fixtures de 08/11/2026; a página ao vivo levou o slider do
anti-robô no perfil novo, então o texto/JSON de sucesso é a fixture com a estrutura conhecida), a verificação anti-robô
(registra, espera e não quebra a rodada), o registro da fonte (só pc, fora das fontes das TVs), o catálogo e a lista de
confiáveis, o item por variável, a escolha do melhor cupom (mínimo <= preço do item, maior desconto, 1 por pedido) e o
preço com cupom no alerta/🎯/painel. Nenhum teste abre o Chrome, vai à rede ou toca o docs/data do repositório.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from monitor import config, lista_cupons as lc, produtos
from monitor.models import Oferta
from monitor.sources import Pular, playwright_sources as ps
from monitor.util import TZ_BR, agora, agora_iso, hoje

FX = Path(__file__).parent / "fixtures"
ITEM = "1005010260639712"
URL_API = "https://acs.aliexpress.com/h5/mtop.aliexpress.pdp.pc.query/1.0/"
HTML_OG = ('<html><head><meta property="og:title" content="PlayStation 5 Edição Digital 825GB 1 Controle Branco Sony - '
           'AliExpress 44"></head><body></body></html>')
TEXTO_VAZIO = "AliExpress\nFaça o download do aplicativo AliExpress\nEntre / Registrar\nCarrinho"


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    monkeypatch.setattr(ps, "MARCA_BLOQUEIO_ALI", tmp_path / "logs" / "aliexpress_bloqueado_em")
    monkeypatch.setattr(ps, "_dir_perfil", lambda perfil: tmp_path / f".pw-profile-{perfil}")
    monkeypatch.setattr(config, "ALIEXPRESS_ITENS", {ITEM: "PS5_DIGITAL"})
    monkeypatch.setattr(config, "ALIEXPRESS_MAX_CARGAS", 1)
    monkeypatch.setattr(config, "CUPONS_ATIVOS_DIAS_TELEGRAM", 2.0)
    monkeypatch.setattr(config, "CUPONS_ATIVOS_DIAS", 3.0)
    return tmp_path


def _fx(nome: str) -> str:
    return (FX / nome).read_text(encoding="utf-8")


def _api(nome: str = "aliexpress_pdp_mtop_2026-11-08.jsonp") -> list[dict]:
    return [{"url": URL_API, "json": ps.jsonp(_fx(nome))}]


def _stub(monkeypatch, html: str, texto: str, capt: list) -> list[str]:
    abertas: list[str] = []

    def abrir(url, *a, **k):
        abertas.append(url)
        assert k.get("perfil") == "ali", "o AliExpress usa um perfil só dele, nunca logado"
        return html, texto, capt

    monkeypatch.setattr(ps, "_abrir", abrir)
    return abertas


# ---------------------------------------------------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------------------------------------------------
def test_jsonp():
    assert ps.jsonp('mtopjsonp2({"a": 1})') == {"a": 1}
    assert ps.jsonp('cb({"a": [1, 2]});') == {"a": [1, 2]}
    assert ps.jsonp('{"a": 1}') == {"a": 1}
    assert ps.jsonp("<html>punish</html>") is None


def test_item_pelo_texto_renderizado():
    o = ps.AliExpressProdutos._parse(HTML_OG, _fx("aliexpress_item_ps5_texto_2026-11-08.txt"), [], ITEM, "PS5_DIGITAL")
    assert (o.fonte, o.tipo, o.loja, o.vendedor, o.modelo) == ("aliexpress.produtos", "loja", "AliExpress", "Magalu Store",
                                                               "PS5_DIGITAL")
    assert (o.id, o.url) == (ITEM, f"https://pt.aliexpress.com/item/{ITEM}.html")
    assert o.titulo == "PlayStation 5 Edição Digital 825GB 1 Controle Branco Sony"
    assert o.preco == 4500.0 and o.preco_pix is None and o.ativo
    assert o.parcelado == "12x R$ 375,00 sem juros"
    assert o.extra["frete"] == 21.63 and o.extra["no_brasil"] is True and o.extra["preco_original"] == 4749.0
    assert o.extra["cupom_pagina"] == "R$ 670,00 OFF em compras acima de R$ 4.200,00"
    # preços dos recomendados e de "Mais desta loja" não entram
    assert 399.0 not in (o.preco, o.extra.get("preco_original")) and o.preco != 6999.0


def test_item_pela_api_mtop_jsonp():
    o = ps.AliExpressProdutos._parse(HTML_OG, TEXTO_VAZIO, _api(), ITEM, "PS5_DIGITAL")
    assert (o.preco, o.vendedor, o.parcelado) == (4500.0, "Magalu Store", "12x R$ 375,00 sem juros")
    assert o.extra["frete"] == 21.63 and o.extra["no_brasil"] is True and o.extra["preco_original"] == 4749.0


def test_titulo_errado_moeda_estrangeira_ou_preco_fora_da_faixa_nao_viram_oferta():
    texto = _fx("aliexpress_item_ps5_texto_2026-11-08.txt")
    controle = HTML_OG.replace("PlayStation 5 Edição Digital 825GB 1 Controle Branco Sony", "Controle DualSense Branco")
    assert ps.AliExpressProdutos._parse(controle, texto, [], ITEM, "PS5_DIGITAL") is None
    dolar = texto.replace("R$\n4\n.\n500\n,\n00\nR$4.749,00", "US $812.00\nUS $857.00")
    assert ps.AliExpressProdutos._parse(HTML_OG, dolar, [], ITEM, "PS5_DIGITAL") is None
    # preço abaixo do piso do produto: nada (o riscado de R$ 4.749 nunca toma o lugar do preço)
    barato = texto.replace("R$\n4\n.\n500\n,\n00", "R$ 450,00")
    assert ps.AliExpressProdutos._parse(HTML_OG, barato, [], ITEM, "PS5_DIGITAL") is None


def test_vendedor_da_lista_de_confiaveis_quando_a_pagina_nao_diz_vendido_por():
    texto = _fx("aliexpress_item_ps5_texto_2026-11-08.txt").replace("Vendido por\n", "")
    o = ps.AliExpressProdutos._parse(HTML_OG, texto, [], ITEM, "PS5_DIGITAL")
    assert o.vendedor == "Magalu Store"


# ---------------------------------------------------------------------------------------------------------------------
# coleta: 1 página por rodada, bloqueio
# ---------------------------------------------------------------------------------------------------------------------
def test_coleta_abre_so_a_pagina_publica_do_item(monkeypatch):
    abertas = _stub(monkeypatch, HTML_OG, _fx("aliexpress_item_ps5_texto_2026-11-08.txt"), [])
    ofs, cupons = ps.AliExpressProdutos().coletar()
    assert abertas == [f"https://pt.aliexpress.com/item/{ITEM}.html"] and cupons == []
    assert [(o.loja, o.preco, o.vendedor) for o in ofs] == [("AliExpress", 4500.0, "Magalu Store")]


def test_coleta_com_dois_itens_abre_uma_pagina_por_rodada(monkeypatch):
    monkeypatch.setattr(config, "ALIEXPRESS_ITENS", {ITEM: "PS5_DIGITAL", "1005000000000001": "PS5_DIGITAL"})
    abertas = _stub(monkeypatch, HTML_OG, _fx("aliexpress_item_ps5_texto_2026-11-08.txt"), [])
    ps.AliExpressProdutos().coletar()
    assert len(abertas) == 1


def test_slider_registra_espera_e_nao_quebra_a_rodada(monkeypatch, isolado):
    perfil = isolado / ".pw-profile-ali"
    perfil.mkdir()
    (perfil / "cookie").write_text("x", encoding="utf-8")
    html = '<html><iframe src="https://acs.aliexpress.com//h5/x/_____tmd_____/punish?x5secdata=XXXX"></iframe></html>'
    _stub(monkeypatch, html, TEXTO_VAZIO, _api("aliexpress_pdp_mtop_bloqueio_2026-11-08.jsonp"))
    with pytest.raises(RuntimeError, match="verificação"):
        ps.AliExpressProdutos().coletar()
    assert ps.MARCA_BLOQUEIO_ALI.exists() and not perfil.exists(), "marca o castigo e apaga o perfil marcado"
    abertas = _stub(monkeypatch, HTML_OG, _fx("aliexpress_item_ps5_texto_2026-11-08.txt"), [])
    with pytest.raises(Pular):
        ps.AliExpressProdutos().coletar()
    assert abertas == [], "de castigo: nenhuma página aberta"
    assert ps.AliExpressProdutos.alerta_falha is False   # sem aviso de "falhou 3 vezes"


def test_bloqueio_so_pela_resposta_da_api():
    assert ps._ali_bloqueado("<html></html>", TEXTO_VAZIO, _api("aliexpress_pdp_mtop_bloqueio_2026-11-08.jsonp"))
    assert ps._ali_bloqueado("", "Por favor, deslize para verificar", [])
    assert not ps._ali_bloqueado(HTML_OG + "<script src='//g.alicdn.com/baxia/x.js'></script>",
                                 _fx("aliexpress_item_ps5_texto_2026-11-08.txt"), _api())


def test_pagina_sem_preco_e_sem_bloqueio_nao_derruba(monkeypatch, capsys):
    _stub(monkeypatch, HTML_OG, TEXTO_VAZIO, [])
    assert ps.AliExpressProdutos().coletar() == ([], [])
    assert "preço não encontrado" in capsys.readouterr().out
    assert not ps.MARCA_BLOQUEIO_ALI.exists()


def test_jsonp_capturado_mesmo_com_content_type_de_json():
    """A API mtop responde JSONP com content-type 'application/json' (visto ao vivo em 08/11/2026): resp.json() falha e
    o texto é lido como JSONP (só nos padrões "mtop.")."""

    class Resp:
        url = URL_API + "?jsv=2.7.2"
        headers = {"content-type": "application/json;charset=UTF-8"}

        def json(self):
            raise ValueError("JSONP")

        def text(self):
            return _fx("aliexpress_pdp_mtop_2026-11-08.jsonp")

    class Page:
        def __init__(self):
            self.cb = None

        def on(self, ev, cb):
            self.cb = cb

        def goto(self, url, **k):
            self.cb(Resp())

        def wait_for_load_state(self, *a, **k):
            pass

        def wait_for_selector(self, *a, **k):
            pass

        def content(self):
            return HTML_OG

        def evaluate(self, js):
            return TEXTO_VAZIO

        def remove_listener(self, *a):
            pass

    _html, _texto, capt = ps._carregar(Page(), "https://pt.aliexpress.com/item/x.html", [ps._ALI_API], None, False, 1000)
    assert capt and capt[0]["json"]["data"]["result"]["SHOP_CARD_PC"]["storeName"] == "Magalu Store"


# ---------------------------------------------------------------------------------------------------------------------
# registro, catálogo, confiança, configuração
# ---------------------------------------------------------------------------------------------------------------------
def test_fonte_so_no_pc_e_fora_das_fontes_das_tvs(monkeypatch):
    from monitor import sources

    for desligadas in (False, True):
        monkeypatch.setattr(config, "TVS_DESLIGADAS", desligadas)
        assert "aliexpress.produtos" in {f.nome for f in sources.por_modo("pc")}
        assert "aliexpress.produtos" not in {f.nome for f in sources.por_modo("cloud")}
    assert "aliexpress.produtos" not in sources.FONTES_SO_TV


def test_catalogo_e_lista_de_confiaveis():
    from monitor import confianca

    assert produtos.produto_por_id_loja("AliExpress", ITEM) == "PS5_DIGITAL"
    o = ps.AliExpressProdutos._parse(HTML_OG, _fx("aliexpress_item_ps5_texto_2026-11-08.txt"), [], ITEM, "PS5_DIGITAL")
    assert confianca.entrada_confiavel(o) is not None
    assert "Magalu Store" in confianca.nomes_confiaveis("AliExpress")


def test_itens_do_aliexpress_por_variavel():
    assert config._itens_aliexpress(f"{ITEM}:PS5_DIGITAL") == {ITEM: "PS5_DIGITAL"}
    assert config._itens_aliexpress(ITEM) == {ITEM: "PS5_DIGITAL"}                # o produto sai do catálogo
    assert config._itens_aliexpress("123:PS5_PRO, 999") == {"123": "PS5_PRO"}     # id desconhecido sem produto: fora
    assert config._itens_aliexpress("") == {}


# ---------------------------------------------------------------------------------------------------------------------
# melhor cupom
# ---------------------------------------------------------------------------------------------------------------------
def _c(codigo, titulo, fonte="telegram", publicado=None, **kw):
    return {"fonte": fonte, "loja": "AliExpress", "codigo": codigo, "titulo": titulo, "url": "https://t.me/canal/1",
            "id": f"{codigo}-{titulo[:12]}", "regra": kw.pop("regra", ""), "validade": kw.pop("validade", None),
            "publicado": publicado or (agora() - timedelta(hours=2)).isoformat(timespec="seconds"),
            "extra": kw.pop("extra", {}), **kw}


HOJE = [_c("AFFNOV22", "R$ 670 OFF acima de R$ 4.200"), _c("AFFNOV09", "R$ 750 OFF acima de R$ 4.500"),
        _c("AEMEGA8", "R$ 580 OFF acima de R$ 3.700")]


def _opcoes(preco, regs):
    return [(o["codigo"], o["desconto"]) for o in lc.opcoes_de_cupom(preco, lc.cupons_ativos(regs, set())["AliExpress"])]


def test_melhor_cupom_item_de_4500_e_de_4499():
    assert _opcoes(4500, HOJE) == [("AFFNOV09", 750.0), ("AFFNOV22", 670.0), ("AEMEGA8", 580.0)]
    # o mínimo do AFFNOV09 é R$ 4.500: no item de R$ 4.499 não vale
    assert _opcoes(4499, HOJE) == [("AFFNOV22", 670.0), ("AEMEGA8", 580.0)]
    # o AFFNOV11 (R$ 785 em R$ 4.200) ganha quando está ativo
    com_11 = HOJE + [_c("AFFNOV11", "R$ 785 OFF acima de R$ 4.200")]
    assert _opcoes(4500, com_11)[0] == ("AFFNOV11", 785.0)


def test_esgotado_cai_para_o_seguinte():
    regs = HOJE + [_c("AFFNOV11", "R$ 785 OFF acima de R$ 4.200", extra={"esgotado_em": agora_iso()},
                      publicado=(agora() - timedelta(hours=3)).isoformat(timespec="seconds"))]
    assert _opcoes(4500, regs)[0] == ("AFFNOV09", 750.0)
    # "só para quem resgatou" vai para o fim
    regs = HOJE + [_c("AFFNOV11", "R$ 785 OFF acima de R$ 4.200", regra="só para quem resgatou")]
    assert [c for c, _d in _opcoes(4500, regs)][-1] == "AFFNOV11"


def test_especiais_de_10_a_12_11(monkeypatch):
    from monitor import util

    especial = _c("IFP1ZYZM", "R$ 800 OFF acima de R$ 4.000", publicado="2026-11-08T14:30:48-03:00",
                  validade="2026-11-12", extra={"inicio": "2026-11-10"})
    regs = [dict(r, publicado="2026-11-08T12:34:49-03:00") for r in HOJE] + [especial]
    for quando, primeiro in ((datetime(2026, 11, 8, 18, 0, tzinfo=TZ_BR), "AFFNOV09"),
                             (datetime(2026, 11, 10, 9, 0, tzinfo=TZ_BR), "IFP1ZYZM")):
        monkeypatch.setattr(util, "agora", lambda q=quando: q)
        monkeypatch.setattr(lc, "agora", lambda q=quando: q)
        assert _opcoes(4500, regs)[0][0] == primeiro


def test_percentual_com_teto_e_exclusoes():
    regs = [_c("PCT10", "10% OFF acima de R$ 149, limite de R$ 200"),
            _c("SELEC1", "R$ 900 OFF acima de R$ 4.000", regra="Cupons · itens selecionados"),
            _c("NOVOS1", "R$ 950 OFF acima de R$ 1.000", regra="Cupons NOVOS Compradores"),
            _c("FRETE1", "R$ 30 OFF no frete"),
            _c("CATEG1", "R$ 990 OFF em Eletrodomésticos")]
    assert _opcoes(4500, regs) == [("PCT10", 200.0)]
    # desconto fixo sem a compra mínima: só até 15% do item (o título genérico "R$ 785 OFF" não vira conta errada)
    assert _opcoes(4500, [_c("SEMMIN1", "Cupom AliExpress R$ 785 OFF", fonte="promobit"),
                          _c("SEMMIN2", "Cupom AliExpress R$ 650 OFF", fonte="promobit")]) == [("SEMMIN2", 650.0)]


def test_aplica_melhor_cupom_no_anuncio_do_aliexpress():
    o = ps.AliExpressProdutos._parse(HTML_OG, _fx("aliexpress_item_ps5_texto_2026-11-08.txt"), [], ITEM, "PS5_DIGITAL")
    kabum = Oferta(fonte="kabum.produtos", tipo="loja", loja="KaBuM!", titulo="Console PlayStation 5 Digital", url="u",
                   id="1", preco=4500, modelo="PS5_DIGITAL")
    regs = HOJE + [_c("AFFNOV11", "R$ 785 OFF acima de R$ 4.200")]
    assert lc.aplica_melhor_cupom([o, kabum], regs, expirados=set()) == 1
    assert kabum.extra == {} and kabum.cupom is None
    assert o.extra["preco_com_cupom"] == 3736.63            # 4.500 - 785 + 21,63 de frete
    assert (o.extra["cupom_preco"], o.extra["cupom_origem"], o.cupom) == ("AFFNOV11", "lista", "AFFNOV11")
    assert o.extra["cupom_regra"] == "R$ 785 OFF acima de R$ 4.200"
    assert [a["codigo"] for a in o.extra["cupons_alternativos"]] == ["AFFNOV09", "AFFNOV22", "AEMEGA8"]
    assert produtos.preco_com_cupom_do_anuncio(o) == (3736.63, "AFFNOV11")
    assert produtos.preco_comparavel(o) == 3736.63
    linhas = "\n".join(produtos.linhas_da_oferta(o))
    assert ("🎟️ Com o cupom AFFNOV11 (melhor cupom AliExpress ativo; 1 por pedido, digite no app): R$ 3.736,63 "
            "(item R$ 4.500 − R$ 785 + frete R$ 21,63) · se esgotado: AFFNOV09 → R$ 3.771,63, AFFNOV22 → R$ 3.851,63") \
        in linhas
    # R$ 3.736,63 ainda está acima da meta do PS5 Digital: sem 🎯; num item de R$ 4.200 o cupom põe abaixo
    assert produtos.preco_comparavel(o) > config.alvo_pix("PS5_DIGITAL")
    o2 = ps.AliExpressProdutos._parse(HTML_OG, _fx("aliexpress_item_ps5_texto_2026-11-08.txt").replace(
        "R$\n4\n.\n500\n,\n00", "R$ 4.200,00"), [], ITEM, "PS5_DIGITAL")
    lc.aplica_melhor_cupom([o2], regs, expirados=set())
    assert o2.extra["cupom_preco"] == "AFFNOV11" and produtos.preco_comparavel(o2) == 3436.63
    assert produtos.preco_comparavel(o2) <= config.alvo_pix("PS5_DIGITAL")


def test_sem_cupom_que_sirva_nada_muda():
    o = ps.AliExpressProdutos._parse(HTML_OG, _fx("aliexpress_item_ps5_texto_2026-11-08.txt"), [], ITEM, "PS5_DIGITAL")
    assert lc.aplica_melhor_cupom([o], [_c("BIG", "R$ 900 OFF acima de R$ 9.000")], expirados=set()) == 0
    assert "preco_com_cupom" not in o.extra and produtos.preco_comparavel(o) == 4500.0


def test_run_pc_grava_o_preco_com_o_melhor_cupom_no_latest(isolado, monkeypatch, capsys):
    """Rodada do pc com o item do AliExpress e os cupons do Telegram que a nuvem gravou no state dela."""
    import run
    from monitor import sources

    st = {"ofertas": {}, "cupons": {}, "minimo": None, "saude": {}, "ultimo_resumo": hoje(),
          "criado_em": "2026-09-13T15:22:00-03:00", "cupons_alertados": {}, "modelos_iniciados": list(produtos.IDS)}
    (isolado / "state_pc.json").write_text(json.dumps(st), encoding="utf-8")
    nuvem = dict(st, cupons={f"telegram:{r['id']}": dict(r, ultima_vez=agora_iso())
                             for r in HOJE + [_c("AFFNOV11", "R$ 785 OFF acima de R$ 4.200")]})
    (isolado / "state_cloud.json").write_text(json.dumps(nuvem), encoding="utf-8")
    oferta = ps.AliExpressProdutos._parse(HTML_OG, _fx("aliexpress_item_ps5_texto_2026-11-08.txt"), [], ITEM,
                                          "PS5_DIGITAL")

    class Fake(sources.Fonte):
        nome = "aliexpress.produtos"
        modo = "pc"

        def coletar(self):
            return [oferta], []

    monkeypatch.setattr(sources, "por_modo", lambda m: [Fake()])
    monkeypatch.setattr(run, "carrega_env", lambda: None)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(sys, "argv", ["run.py", "--mode", "pc", "--no-notify"])
    assert run.main() == 0
    assert "melhor cupom do AliExpress calculado em 1" in capsys.readouterr().out
    lt = json.loads((isolado / "latest_pc.json").read_text(encoding="utf-8"))
    [reg] = [o for o in lt["ofertas_loja"] if o.get("fonte") == "aliexpress.produtos"]
    assert reg["extra"]["preco_com_cupom"] == 3736.63 and reg["extra"]["cupom_preco"] == "AFFNOV11"
    assert reg["vendedor"] == "Magalu Store"
