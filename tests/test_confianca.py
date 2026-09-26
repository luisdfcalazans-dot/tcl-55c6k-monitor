"""Confiança nos anúncios (monitor/confianca.py): listas curadas, veredito rápido e o efeito em alertas, estado,
histórico, carrinho e postagens.

Caso real de 25/09/2026: "Importados Lili" no Magalu (anúncios kc3ca4k960 55" e kd12g2e47k 65", mesmo grupo) vendendo a
TV a R$ 2.609,01 no Pix / R$ 3.894,05 no cartão. O monitor alertou (abaixo do alvo) e o anúncio virou o "menor já
visto". Sinais: homologação Anatel de um Galaxy S25 Ultra (09573-24-00953; a da C6K é 00738-24-06714), "preço cheio"
igual ao Pix do Magalu 1P com 33% de desconto só no Pix/1x, modelo "Vários", 0 avaliações, loja de outro ramo.
As fixtures magalu_*_2026-09-25.html são as páginas reais do magazinevoce daquela noite, reduzidas aos campos usados.
Nenhum teste acessa a rede.
"""

from __future__ import annotations

import copy
import csv
import importlib
import json
import time
from pathlib import Path

import pytest

from monitor import config, confianca
from monitor.estado import Estado
from monitor.models import Oferta
from monitor.regras import CAB_SUSPEITO, gerar_alertas, resumo_diario, sanear
from monitor.sources import amazon, kabum, magalu, vtex
from monitor.util import agora_iso, next_data

FX = Path(__file__).parent / "fixtures"
URL_LILI = ("https://www.magazineluiza.com.br/smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-google-"
            "assistente-4-hdmi-2-usb/p/kc3ca4k960/et/elit/")
URL_1P = ("https://www.magazineluiza.com.br/smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-google-"
          "assistente-4-hdmi-2-usb/p/240162700/et/elit/")


def _fx(nome: str) -> str:
    return (FX / nome).read_text(encoding="utf-8")


LILI55 = _fx("magalu_produto_lili55_2026-09-25.html")
LILI65 = _fx("magalu_produto_lili65_2026-09-25.html")
P1P = _fx("magalu_produto_1p_2026-09-25.html")
LOJISTA_LILI = _fx("magalu_lojista_importadoslili_2026-09-25.html")


def _html_produto(p: dict) -> str:
    nd = {"props": {"pageProps": {"data": {"product": p}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd, ensure_ascii=False)}</script>'


def _produto(html: str) -> dict:
    return copy.deepcopy(next_data(html)["props"]["pageProps"]["data"]["product"])


def lili() -> Oferta:
    (o,) = magalu.parse_produto_todas(LILI55)[0]
    return o


def magalu_1p() -> Oferta:
    (o,) = magalu.parse_produto_todas(P1P)[0]
    return o


def vendedor_limpo(pix: str = "2890.00", cartao: str = "3099.00") -> Oferta:
    """Vendedor desconhecido de verdade limpo: a página do 1P (ficha certa, Anatel da C6K) com outro lojista."""
    p = _produto(P1P)
    sel = {"id": "lojaboaeletro", "sku": "1", "description": "Loja Boa Eletro", "category": "3p",
           "deliveryId": "magazineluiza", "tags": [],
           "details": {"id": "lojaboaeletro", "legalName": "Boa Eletro Comercio de Eletronicos Ltda", "score": 4.8,
                       "sellerSince": "2019-03-01T00:00:00.000+00:00", "totalSales": 25000}}
    p.update({"seller": sel, "offers": [{"sku": "1", "price": {"paymentMethodDescription": "no Pix", "bestPrice": pix,
                                                              "fullPrice": None, "price": cartao}, "seller": sel}],
              "price": {"paymentMethodDescription": "no Pix", "price": cartao, "fullPrice": cartao, "bestPrice": pix},
              "rating": {"count": 57, "score": 4.7}, "path": p["path"].replace("240162700", "kb0aeletro1"),
              "url": p["url"].replace("240162700", "kb0aeletro1"), "id": "kb0aeletro0", "variationId": "kb0aeletro1"})
    p["variations"] = [{**v, "id": "kb0aeletro1", "path": v["path"].replace("240162700", "kb0aeletro1")}
                       for v in p["variations"] if v.get("id") == "240162700"]
    (o,) = magalu.parse_produto_todas(_html_produto(p))[0]
    return o


def catalogo_html(total: int, cats: list[tuple[str, str, int]]) -> str:
    """Página da loja do vendedor no magazinevoce (só o filtro Categoria e a paginação)."""
    s = {"pagination": {"page": 1, "pages": 1, "records": total, "size": 60},
         "filters": [{"slug": "category", "type": "category",
                      "values": [{"id": i, "label": lbl, "count": n} for i, lbl, n in cats]}]}
    nd = {"props": {"pageProps": {"data": {"search": s}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script>'


class Rede:
    """obter() falso: responde pelas URLs conhecidas e conta as requisições (a rede de verdade nunca é usada)."""

    def __init__(self, paginas: dict[str, str] | None = None):
        self.paginas = paginas or {}
        self.pedidas: list[str] = []

    def __call__(self, url: str) -> str:
        self.pedidas.append(url)
        for trecho, html in self.paginas.items():
            if trecho in url:
                return html
        raise AssertionError(f"requisição inesperada: {url}")


@pytest.fixture
def dados(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    return tmp_path


@pytest.fixture
def sem_lili_na_lista(monkeypatch):
    """A lista curada sem a Lili: o veredito tem que sair só das checagens (como seria em 25/09 20:18)."""
    listas = copy.deepcopy(confianca.listas())
    listas["reprovados"].pop("Magazine Luiza", None)
    monkeypatch.setattr(confianca, "listas", lambda: listas)
    return listas


def rodada(modo, ofertas, rede=None, bootstrap=False):
    """A sequência do run.py: descarta reprovados -> sanear -> veredito -> alertas -> estado -> histórico -> latest."""
    est = Estado(modo)
    est.bootstrap = bootstrap
    ofertas = confianca.descarta_reprovados(est, ofertas)
    ofertas, _av = sanear(ofertas)
    confianca.avaliar(est, ofertas, rede=rede is not None, obter=rede, pausa_s=0)
    est.migra_chaves_de_oferta(ofertas)
    msgs, alertados = gerar_alertas(est, ofertas, [])
    diretas = est.lojas_diretas_conhecidas(ofertas)
    for o in ofertas:
        est.registra_oferta(o, alertados.get(o.chave))
        est.atualiza_minimo(o, diretas)
    est.anexa_historico([o for o in ofertas if o.tipo == "loja" and o.ativo and o.melhor_preco])
    est.escreve_latest(ofertas, [])
    est.salva()
    return est, ofertas, msgs


def cabecalhos(msgs):
    return [m.split("\n")[0] for m in msgs]


# ------------------------------------------------------------------------------------------------
# bloqueio emergencial (continua valendo pela lista curada)
# ------------------------------------------------------------------------------------------------

def test_oferta_real_da_lili_bloqueada():
    # o registro real do latest_cloud de 25/09 20:18
    o = {"loja": "Magazine Luiza", "vendedor": "Importados Lili", "id": "kd12g2e47k-importadoslili", "url": URL_LILI,
         "extra": {"vendedor_id": "importadoslili"}}
    assert confianca.motivo_bloqueio(o, ())


def test_bloqueia_por_qualquer_pista():
    base = dict(fonte="magalu", tipo="loja", loja="Magazine Luiza", titulo="Smart TV 55 TCL 55C6K")
    assert confianca.motivo_bloqueio(Oferta(**base, url=URL_1P + "?seller_id=importadoslili", id="x"), ())  # só a URL
    assert confianca.motivo_bloqueio(Oferta(**base, url="u", id="y", vendedor="Importados  Lili"), ())       # só o nome
    assert confianca.motivo_bloqueio(Oferta(**base, url=URL_LILI, id="z", vendedor="Outro"), ())             # só o anúncio


def test_nao_bloqueia_vendedor_confiavel_nem_outra_loja():
    base = dict(fonte="magalu", tipo="loja", titulo="Smart TV 55 TCL 55C6K")
    assert confianca.motivo_bloqueio(Oferta(**base, loja="Magazine Luiza", url=URL_1P, id="240162800-magazineluiza",
                                            vendedor="Magalu", extra={"vendedor_id": "magazineluiza"}), ()) is None
    assert confianca.motivo_bloqueio(Oferta(**base, loja="Amazon", url="https://www.amazon.com.br/dp/B0F7JZMVKF", id="a",
                                            vendedor="Importados Lili"), ()) is None


def test_linha_do_historico_real_da_lili_bloqueada():
    """A linha do historico_cloud.csv não tem id nem vendedor_id: o nome e o /p/ bastam."""
    linha = {"quando": "2026-09-25T20:18:28-03:00", "fonte": "magalu", "tipo": "loja", "loja": "Magazine Luiza",
             "vendedor": "Importados Lili", "preco": "3894.05", "preco_pix": "2609.01", "url": URL_LILI}
    assert confianca.motivo_bloqueio(linha, ())
    assert confianca.motivo_bloqueio({"preco": 2609.01, "loja": "Magazine Luiza", "url": URL_LILI}, ())  # o 'minimo'


# ------------------------------------------------------------------------------------------------
# listas curadas: formato e texto neutro
# ------------------------------------------------------------------------------------------------

def test_listas_curadas_tem_formato_valido_e_texto_neutro():
    d = json.loads(confianca.ARQ_LISTAS.read_text(encoding="utf-8"))
    for tipo in ("confiaveis", "reprovados"):
        for loja, entradas in d[tipo].items():
            assert loja in set(config.LOJAS_CANONICAS.values()), loja
            for e in entradas:
                assert e.get("ids") or e.get("nomes") or e.get("anuncios"), e
                assert e.get("motivo") and e.get("desde"), e
    texto = json.dumps(d["reprovados"], ensure_ascii=False).lower()
    for palavra in ("golpista", "fraudador", "criminoso", "ladr", "bandid"):
        assert palavra not in texto  # a empresa listada pode ser vítima (conta invadida)
    assert "vítima" in texto
    # ASIN/sku são de todos os vendedores: nunca na lista de anúncios reprovados
    assert not d["reprovados"].get("Amazon") and not d["reprovados"].get("Casas Bahia")


def test_nome_com_ruido_da_amazon_e_id_casam_com_a_lista():
    base = dict(fonte="amazon", tipo="loja", loja="Amazon", titulo="TCL 55C6K", url="https://www.amazon.com.br/dp/X")
    ruido = Oferta(**base, id="B0F7JZMVKF-amazoncombrpolticadedevoluo", vendedor="Amazon.com.br Política de devolução")
    so_id = Oferta(**base, id="B0F7JZMVKF-A1ZZFT5FULY4LN", extra={"vendedor_id": "A1ZZFT5FULY4LN"})
    assert confianca.classifica_por_lista(ruido, ())[0] == confianca.CONFIAVEL
    assert confianca.classifica_por_lista(so_id, ())[0] == confianca.CONFIAVEL


def test_nome_de_confiavel_com_id_diferente_nao_e_confiavel():
    """Na lista estrita, quando há id dos dois lados, só o id decide (nome igual com id diferente é outro vendedor)."""
    o = Oferta("magalu", "loja", "Magazine Luiza", "TCL 55C6K", URL_1P + "?seller_id=magalu2", "240162800-magalu2",
               vendedor="Magalu", extra={"vendedor_id": "magalu2"})
    assert confianca.classifica_por_lista(o, ())[0] is None


# ------------------------------------------------------------------------------------------------
# o anúncio real da Lili, sem a lista curada: vira suspeito pelas checagens
# ------------------------------------------------------------------------------------------------

def test_coleta_do_magalu_guarda_a_ficha_real():
    o = lili()
    assert (o.id, o.vendedor, o.preco, o.preco_pix) == ("kd12g2e47k-importadoslili", "Importados Lili", 3894.05, 2609.01)
    f = o.extra["ficha"]
    assert (f["anatel"], f["modelo"], f["avaliacoes"], f["peso_kg"]) == ("095732400953", "Vários", 0, 0.1)
    assert f["razao_social"] == "Comercial De Brinquedos Lili Ltda" and f["vendedor_desde"] == "2022-07-25"
    p = magalu_1p()
    assert (p.extra["ficha"]["anatel"], p.extra["ficha"]["modelo"], p.extra["ficha"]["avaliacoes"]) == \
        ("00738-24-06714", "55C6K", 3644)
    # o de 65" do mesmo grupo (título diz 55") nem entra na coleta
    assert magalu.parse_produto_todas(LILI65)[0] == []


def test_lili_real_vira_suspeito_so_pelas_checagens(dados, sem_lili_na_lista):
    rede = Rede()
    est, ofertas, msgs = rodada("cloud", [lili(), magalu_1p()], rede=rede)
    li = next(o for o in ofertas if o.vendedor == "Importados Lili")
    c = li.extra["confianca"]
    assert c["veredito"] == confianca.SUSPEITO
    texto = " | ".join(c["sinais"])
    for trecho in ("33% menor", "“preço cheio” R$ 3.894,05 igual", "09573-24-00953", "'Vários'", "sem avaliações",
                   "peso na ficha 0,1 kg", "Brinquedos"):
        assert trecho in texto, trecho
    assert rede.pedidas == []  # sinais fortes já com o que a coleta tem: nenhuma requisição extra
    # UMA mensagem de aviso, sem 🎯/🏆/🔻
    assert cabecalhos(msgs) == [CAB_SUSPEITO]
    assert not any(e in m for m in msgs for e in ("🎯", "🏆", "🔻"))
    assert "Importados Lili" in msgs[0] and "R$ 2.609,01" in msgs[0] and "09573-24-00953" in msgs[0]
    # nunca vira mínimo, histórico nem melhor preço do latest
    assert est.dados["minimo"]["preco"] == 3894.05
    with (dados / "historico_cloud.csv").open(encoding="utf-8") as f:
        assert [r["vendedor"] for r in csv.DictReader(f)] == ["Magalu"]
    assert "Magazine Luiza|importadoslili" in est.dados["confianca"]["reprovados_auto"]
    auto = est.dados["confianca"]["reprovados_auto"]["Magazine Luiza|importadoslili"]
    assert auto["origem"] == "automatico" and auto["anuncios"] == ["kc3ca4k960"]


def test_suspeito_vira_reprovado_e_some_de_cara_na_proxima_rodada(dados, sem_lili_na_lista):
    rodada("cloud", [lili(), magalu_1p()], rede=Rede())
    rede = Rede()
    est, ofertas, msgs = rodada("cloud", [lili(), magalu_1p()], rede=rede)
    assert [o.vendedor for o in ofertas] == ["Magalu"]
    assert msgs == [] and rede.pedidas == []
    # o outro modo (PC) e o testador leem o reprovado automático do state
    assert confianca.motivo_bloqueio({"loja": "Magazine Luiza", "vendedor": "Importados Lili", "url": URL_LILI})
    assert Estado("pc").reprovados_auto()


def test_lili_da_busca_sem_ficha_e_preco_menos_agressivo_usa_catalogo_e_anuncio(dados, sem_lili_na_lista):
    """Anúncio que a coleta só viu na busca (sem ficha) e com preço que sozinho não assusta: 1 requisição ao anúncio
    e 1 à página da loja do vendedor (as páginas reais de 25/09). O catálogo de brinquedos entrega."""
    o = lili()
    o.extra.pop("ficha")
    o.preco, o.preco_pix = 3894.05, 3600.00
    rede = Rede({"/lojista/importadoslili/": LOJISTA_LILI, "/p/kc3ca4k960/": LILI55})
    est, ofertas, msgs = rodada("cloud", [o, magalu_1p()], rede=rede)
    li = next(x for x in ofertas if x.vendedor == "Importados Lili")
    assert li.extra["confianca"]["veredito"] == confianca.SUSPEITO
    assert any("2.667 itens e só 9 de TV" in s for s in li.extra["confianca"]["sinais"])
    assert len(rede.pedidas) == 2
    assert "seller_id=importadoslili" in rede.pedidas[0] and "/lojista/importadoslili/" in rede.pedidas[1]
    assert cabecalhos(msgs) == [CAB_SUSPEITO]


def test_resumo_do_catalogo_real():
    r = confianca.resumo_catalogo_magalu(LOJISTA_LILI)
    assert (r["total"], r["tv"]) == (2667, 9)
    assert r["principais"][:3] == ["Utilidades Domésticas", "Beleza e Perfumaria", "Brinquedos"]


# ------------------------------------------------------------------------------------------------
# confiáveis reais: continuam confiáveis e sem demora nenhuma
# ------------------------------------------------------------------------------------------------

def _confiaveis_reais() -> list[Oferta]:
    out = [magalu_1p()]
    out += magalu.parse_produto_todas(_fx("magalu_produto_colombo_2026-09-19.html"))[0]
    out += amazon.parse_ofertas(_fx("amazon_aod_2026-09-19.html"), "B0F7JZMVKF")
    out.append(kabum.parse_api(json.loads(_fx("kabum_api.json"))))
    out += vtex.parse_catalogo(json.loads(_fx("fastshop_vtex.json")), "Fast Shop", config.LOJAS_VTEX["Fast Shop"])
    # registros reais do latest_pc de 24/09 (ML e Casas Bahia)
    out.append(Oferta("mercadolivre", "loja", "Mercado Livre", "TCL 55C6K", config.URL_ML_CATALOGO, "MLB7574364080",
                      preco=3894.05, vendedor="Magalu", extra={"vendedor_id": "3592255542", "item_id": "MLB7574364080"}))
    out.append(Oferta("casasbahia", "loja", "Casas Bahia", "TCL 55C6K", config.URL_CASASBAHIA_PRODUTO,
                      "55069456-10037", preco=3998.99, preco_pix=3599.09, vendedor="Casas Bahia",
                      extra={"vendedor_id": "10037"}))
    out.append(Oferta("vtex", "loja", "Loja TCL", "TCL 55C6K", "https://www.lojatcl.com.br/x/p", "Loja TCL-32054-1",
                      preco=3421.48, vendedor="TCL - Brasil"))
    return [o for o in out if o]


def test_confiaveis_reais_ficam_confiaveis_e_rapidos(dados):
    ofertas = _confiaveis_reais()
    assert len(ofertas) >= 8
    est = Estado("cloud")
    rede = Rede()
    t0 = time.perf_counter()
    contagem = confianca.avaliar(est, ofertas, rede=True, obter=rede, pausa_s=0)
    assert time.perf_counter() - t0 < 0.5
    assert rede.pedidas == []
    nao = [(o.loja, o.vendedor) for o in ofertas if confianca.veredito_de(o) != confianca.CONFIAVEL]
    assert not nao, nao
    assert contagem == {confianca.CONFIAVEL: len(ofertas)}


def test_promocao_real_de_confiavel_alerta_na_hora(dados):
    rodada("cloud", _confiaveis_reais())
    promo = magalu_1p()
    promo.preco_pix = 2799.00  # 1P abaixo do alvo do Pix
    rede = Rede()
    est, _ofs, msgs = rodada("cloud", [promo] + _confiaveis_reais()[1:], rede=rede)
    (m,) = [m for m in msgs if "Magalu" in m.split("\n")[0]]
    assert "🎯" in m and "🏆" in m
    assert "🔎" not in m and CAB_SUSPEITO not in m
    assert rede.pedidas == []
    assert est.dados["minimo"]["preco"] == 2799.00


def test_promocao_real_de_vendedor_desconhecido_limpo_alerta_com_linha_de_checagem(dados):
    rodada("cloud", _confiaveis_reais())
    novo = vendedor_limpo(pix="2890.00", cartao="3099.00")
    rede = Rede({"/lojista/lojaboaeletro/": catalogo_html(900, [("ET", "Tv e Vídeo", 140), ("IN", "Informática", 300),
                                                                   ("ED", "Eletrodomésticos", 200)])})
    est, ofs, msgs = rodada("cloud", [novo] + _confiaveis_reais(), rede=rede)
    o = next(x for x in ofs if x.vendedor == "Loja Boa Eletro")
    c = o.extra["confianca"]
    assert c["veredito"] == confianca.SEM_RISCO
    assert {"Anatel", "modelo", "avaliações", "catálogo da loja"} <= set(c["checagens"])
    assert rede.pedidas == [f"{magalu.BASE_MV}/lojista/lojaboaeletro/"]  # a ficha já veio da coleta: só o catálogo
    (m,) = [m for m in msgs if "Loja Boa Eletro" in m]
    assert "🎯" in m and CAB_SUSPEITO not in m
    assert "🔎 vendedor novo: checagens ok (" in m and "catálogo da loja" in m
    assert "atenção" not in m  # 7% abaixo da confiável mais barata (Fast Shop 3.099,00): nada a apontar
    assert est.dados["minimo"]["preco"] == 2890.00
    # a próxima rodada usa o catálogo guardado (nenhuma requisição); preço 23% abaixo da confiável mais barata vira
    # uma nota na linha 🔎, sem bloquear o alerta (promoção de verdade não pode ser perdida)
    rede2 = Rede()
    _est, _ofs, msgs2 = rodada("cloud", [vendedor_limpo(pix="2400.00", cartao="3099.00")] + _confiaveis_reais(),
                               rede=rede2)
    assert rede2.pedidas == []
    (m2,) = [m for m in msgs2 if "Loja Boa Eletro" in m]
    assert "🎯" in m2 and "🔎 vendedor novo: checagens ok (" in m2
    assert "atenção: preço R$ 2.400,00 é 23% menor que o da loja confiável mais barata (R$ 3.099,00, Fast Shop)" in m2


def test_vendedor_desconhecido_caro_nao_gasta_requisicao(dados):
    caro = vendedor_limpo(pix="4500.00", cartao="4700.00")
    rede = Rede()
    _est, ofs, _msgs = rodada("cloud", [caro, magalu_1p()], rede=rede)
    assert rede.pedidas == []
    assert confianca.veredito_de(next(o for o in ofs if o.vendedor == "Loja Boa Eletro")) == confianca.SEM_RISCO


def test_no_maximo_dois_vendedores_novos_com_rede_por_rodada(dados):
    novos = []
    for i in range(4):
        o = vendedor_limpo(pix=f"{3000 + i}.00", cartao="3199.00")
        o.extra["vendedor_id"] = f"loja{i}"
        o.vendedor = f"Loja {i}"
        o.id = f"kb0aeletro0-loja{i}"
        o.extra.pop("ficha")
        novos.append(o)
    rede = Rede({"/lojista/": catalogo_html(500, [("ET", "Tv e Vídeo", 100)]), "/p/kb0aeletro1/": P1P})
    rodada("cloud", novos + [magalu_1p()], rede=rede)
    assert len(rede.pedidas) <= 2 * confianca.MAX_VENDEDORES_COM_REDE


def test_anuncio_e_catalogo_checados_nao_sao_pedidos_de_novo_no_mesmo_dia(dados):
    rede = Rede({"/lojista/lojaboaeletro/": catalogo_html(500, [("ET", "Tv e Vídeo", 100)]),
                 "/p/kb0aeletro1/": "<html>página sem dados</html>"})
    est = Estado("cloud")
    for _ in range(2):
        o = vendedor_limpo(pix="3000.00", cartao="3199.00")
        o.extra.pop("ficha")
        confianca.avaliar(est, [o, magalu_1p()], rede=True, obter=rede, pausa_s=0)
        assert confianca.veredito_de(o) == confianca.SEM_RISCO
    assert len(rede.pedidas) == 2  # 1ª rodada: anúncio + catálogo; 2ª: nada (aberto há pouco / catálogo guardado)


def test_bloqueio_403_encerra_as_checagens_de_rede(dados):
    novos = []
    for i in range(2):
        o = vendedor_limpo(pix=f"{3000 + i}.00", cartao="3199.00")
        o.extra["vendedor_id"] = f"loja{i}"
        o.vendedor, o.id = f"Loja {i}", f"kb0aeletro0-loja{i}"
        novos.append(o)
    pedidas = []

    def bloqueia(url):
        pedidas.append(url)
        raise confianca._Bloqueio("403")

    est = Estado("cloud")
    confianca.avaliar(est, novos + [magalu_1p()], rede=True, obter=bloqueia, pausa_s=0)
    assert len(pedidas) == 1
    assert all(confianca.veredito_de(o) == confianca.SEM_RISCO for o in novos)


# ------------------------------------------------------------------------------------------------
# dado real já gravado: o mínimo e as linhas de 25/09 somem por código
# ------------------------------------------------------------------------------------------------

MIN_LILI = {"preco": 2609.01, "loja": "Magazine Luiza", "quando": "2026-09-25T20:18:28-03:00", "url": URL_LILI,
            "titulo": "Smart TV 55 TCL 4K UHD MiniLED 55C6K 120Hz Google TV AiPQ Google Assistente 4 HDMI 2 USB"}
CAB_CSV = "quando,fonte,tipo,loja,vendedor,titulo,preco,preco_pix,parcelado,cupom,url\r\n"
LINHA_FASTSHOP = ("2026-09-14T21:04:38-03:00,magalu,loja,Magazine Luiza,Fast Shop,Smart TV 4K TCL 55C6K,3099.0,2991.6,,,"
                  "https://www.magazineluiza.com.br/smart-tv-4k-tcl-55c6k/p/kb7d86eh39/et/elit/\r\n")
LINHA_1P = (f"2026-09-25T20:18:28-03:00,magalu,loja,Magazine Luiza,Magalu,Smart TV 55\" TCL 55C6K,4099.0,3894.05,"
            f"\"10x R$ 409,90 sem juros\",,{URL_1P}\r\n")
LINHA_LILI = ("2026-09-25T20:18:28-03:00,magalu,loja,Magazine Luiza,Importados Lili,Smart TV 55 TCL 4K UHD MiniLED 55C6K "
              "120Hz Google TV AiPQ Google Assistente 4 HDMI 2 USB,3894.05,2609.01,\"10x R$ 389,41 sem juros\",,"
              f"{URL_LILI}\r\n")


def _grava_dado_real(pasta: Path) -> None:
    reg_lili = {"primeira_vez": "2026-09-25T20:18:28-03:00", "preco_alertado": 2609.01, "fonte": "magalu",
                "tipo": "loja", "loja": "Magazine Luiza", "titulo": MIN_LILI["titulo"], "url": URL_LILI,
                "id": "kd12g2e47k-importadoslili", "preco": 3894.05, "preco_pix": 2609.01, "ativo": True,
                "vendedor": "Importados Lili", "extra": {"anuncio": "kc3ca4k960", "vendedor_id": "importadoslili"},
                "ultima_vez": "2026-09-25T23:17:48-03:00", "ultimo_preco": 2609.01, "menor_preco": 2609.01}
    st = {"ofertas": {"magalu:kd12g2e47k-importadoslili": reg_lili}, "cupons": {}, "minimo": MIN_LILI, "saude": {},
          "criado_em": "2026-09-13T15:00:00-03:00", "cupons_alertados": {}}
    (pasta / "state_cloud.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    with (pasta / "historico_cloud.csv").open("w", encoding="utf-8", newline="") as f:
        f.write(CAB_CSV + LINHA_FASTSHOP + LINHA_LILI + LINHA_1P + LINHA_LILI)


def test_purga_do_minimo_e_do_registro_ao_carregar(dados):
    _grava_dado_real(dados)
    est = Estado("cloud")
    assert "magalu:kd12g2e47k-importadoslili" not in est.dados["ofertas"]
    m = est.dados["minimo"]
    # o mínimo de antes do anúncio (o mesmo que o state_cloud tinha às 17:50 de 25/09), com o horário da linha
    assert (m["preco"], m["quando"], m["vendedor"]) == (2991.6, "2026-09-14T21:04:38-03:00", "Fast Shop")
    # o PC, lendo o state da nuvem ainda não limpo, também não vê o 2.609,01
    assert (Estado("pc").minimo_geral() or {}).get("preco") != 2609.01


def test_purga_do_historico_na_gravacao_mantem_o_resto_byte_a_byte(dados):
    _grava_dado_real(dados)
    est = Estado("cloud")
    est.anexa_historico([])
    assert (dados / "historico_cloud.csv").read_bytes() == (CAB_CSV + LINHA_FASTSHOP + LINHA_1P).encode("utf-8")


def test_resumo_e_latest_sem_o_suspeito(dados, sem_lili_na_lista):
    est, ofertas, _msgs = rodada("cloud", [lili(), magalu_1p()], rede=Rede())
    r = resumo_diario(est, ofertas, [])
    assert "2.609,01" not in r and "Importados Lili" not in r
    lt = json.loads((dados / "latest_cloud.json").read_text(encoding="utf-8"))
    sus = [o for o in lt["ofertas_loja"] if o["vendedor"] == "Importados Lili"]
    assert sus and sus[0]["extra"]["confianca"]["veredito"] == confianca.SUSPEITO  # o painel mostra riscado
    assert lt["minimo"]["preco"] == 3894.05
    assert any(e["ids"] == ["importadoslili"] for e in lt["confianca"]["reprovados"])


# ------------------------------------------------------------------------------------------------
# carrinho: só confiável ou sem risco aparente
# ------------------------------------------------------------------------------------------------

def _importa_testar_cupons():
    import run

    original = run.carrega_env
    run.carrega_env = lambda: None
    try:
        return importlib.import_module("testar_cupons")
    finally:
        run.carrega_env = original


def test_carrinho_so_recebe_confiavel_ou_sem_risco(dados, monkeypatch):
    tc = _importa_testar_cupons()
    from monitor.carrinho import Magalu

    monkeypatch.delenv("CUPONS_EXTRA", raising=False)
    p1 = magalu_1p()
    p1.extra["confianca"] = {"veredito": confianca.CONFIAVEL}
    limpo = vendedor_limpo(pix="3500.00", cartao="3699.00")
    limpo.extra["confianca"] = {"veredito": confianca.SEM_RISCO, "checagens": ["preço"], "sinais": []}
    sus = vendedor_limpo(pix="2500.00", cartao="3894.05")
    sus.vendedor, sus.id, sus.extra["vendedor_id"] = "Loja Suspeita", "kb0aeletro0-lojasuspeita", "lojasuspeita"
    sus.extra["confianca"] = {"veredito": confianca.SUSPEITO, "sinais": ["x"]}
    antigo = lili().to_dict()             # registro de antes da checagem (sem veredito): a lista curada barra
    antigo["extra"].pop("confianca", None)
    legado = vendedor_limpo(pix="2600.00", cartao="3894.05").to_dict()   # desconhecido sem veredito, 33% abaixo
    legado.update(vendedor="Loja Legado", id="kb0aeletro0-lojalegado")
    legado["extra"]["vendedor_id"] = "lojalegado"
    lt = {"modo": "cloud", "ofertas_loja": [p1.to_dict(), limpo.to_dict(), sus.to_dict(), antigo, legado],
          "cupons": [], "posts": []}
    (dados / "latest_cloud.json").write_text(json.dumps(lt, ensure_ascii=False), encoding="utf-8")
    _cods, anuncios = tc.codigos_conhecidos(Magalu())
    assert sorted(a.vendedor for a in anuncios) == ["Loja Boa Eletro", "Magalu"]
    ok, _m = confianca.pode_ir_ao_carrinho(legado, lt["ofertas_loja"], ())
    assert not ok


# ------------------------------------------------------------------------------------------------
# postagens: preço muito abaixo das lojas confiáveis ganha aviso, sem 🎯
# ------------------------------------------------------------------------------------------------

def test_postagem_muito_abaixo_das_confiaveis_ganha_aviso_sem_alvo(dados):
    rodada("cloud", [magalu_1p()])
    post = Oferta("promobit", "post", "Magazine Luiza", "Smart TV 55 TCL 55C6K", "https://www.promobit.com.br/x/1",
                  "p1", preco=2609.01, publicado=agora_iso())
    ok = Oferta("promobit", "post", "Magazine Luiza", "Smart TV 55 TCL 55C6K", "https://www.promobit.com.br/x/2",
                "p2", preco=3594.05, publicado=agora_iso())
    _est, _ofs, msgs = rodada("cloud", [magalu_1p(), post, ok])
    (m_sus,) = [m for m in msgs if "2.609,01" in m]
    assert "⚠️ confira: preço muito abaixo das lojas confiáveis" in m_sus and "🎯" not in m_sus
    (m_ok,) = [m for m in msgs if "3.594,05" in m]
    assert "confira" not in m_ok


def test_postagem_com_link_do_anuncio_reprovado_nem_entra(dados):
    post = Oferta("promobit", "post", "Magazine Luiza", "Smart TV 55 TCL 55C6K", URL_LILI, "p3", preco=2609.01,
                  publicado=agora_iso())
    _est, ofs, msgs = rodada("cloud", [magalu_1p(), post])
    assert [o.id for o in ofs if o.tipo == "post"] == [] and msgs == []
