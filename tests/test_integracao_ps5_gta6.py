"""Integração das três frentes do PS5/GTA 6 (03/10/2026): catálogo (A), fontes novas (B) e testador por produto (C).

Cobre o que só aparece com as três juntas: o anúncio que a fonte nova grava no latest chega ao testador com o produto,
a meta e o cupom da página; o preço com o cupom da página do anúncio conta no custo final do PS5/GTA 6 (e nunca nas
TVs); a TV tirada do carrinho fica fora durante a vigia enquanto o testador roda para o PS5/GTA 6; e os títulos reais
que a rodada seca de 03/10 mostrou mal classificados. Nenhum teste acessa a rede nem abre navegador.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from monitor import config, produtos
from monitor.carrinho import Magalu, MercadoLivre
from monitor.estado import Estado
from monitor.models import Oferta
from monitor.regras import gerar_alertas, mensagem_bootstrap, resumo_diario
from monitor.sources import magalu, mercadolivre_loja
from test_testador_anuncios import FIXO, _iso, amb, tc  # noqa: F401 - ambiente do testador (dados, relógio, sessão)
from test_testador_produtos import (  # noqa: F401
    K_GTA, K_PS5D, O_GTA, O_PS5D, CarrinhoProdutos, _latest, vigia,
)

FX = Path(__file__).parent / "fixtures"
D = "2026-10-03"


def _fx(nome: str) -> str:
    return (FX / nome).read_text(encoding="utf-8")


class _Hoje(date):
    """03/10/2026: antes do lançamento do GTA 6 (depois de 19/11 a meta do Code in Box é a de quem chega depois)."""

    @classmethod
    def today(cls):
        return date(2026, 10, 3)


@pytest.fixture(autouse=True)
def _antes_do_lancamento(monkeypatch):
    monkeypatch.setattr(produtos, "date", _Hoje)


# ------------------------------------------------------------------------------------------------
# 1. títulos reais da rodada seca de 03/10
# ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("titulo,esperado", [
    # Magalu 240590700: a versão escrita depois do pacote não é um extra (antes virava kit "+ edicao digital")
    ("Console Sony PlayStation 5 SSD 825GB Controle sem fio DualSense + 2 Jogos Digitais Edição Digital", "PS5_DIGITAL"),
    ("PlayStation 5 Slim Digital + Astro Bot + Gran Turismo 7 Edição Digital", "PS5_DIGITAL"),
    ("Console PlayStation 5 Slim Digital 825GB + Jogo EA FC 26", "PS5_KIT"),   # outro jogo no pacote continua kit
    ("Console PS5 Slim Digital + Edição Limitada Wolverine", "PS5_KIT"),
    # nocnoc no Magalu: jogo "Edição Console" para PS5 não é o console (antes virava PS5 Digital a R$ 315,06)
    ("Jogo de Vídeo Ubisoft Anno 1800 Edição Console PS5", None),
])
def test_titulos_da_rodada_seca(titulo, esperado):
    assert produtos.classifica(titulo, "Magazine Luiza").produto == esperado


# ------------------------------------------------------------------------------------------------
# 2. o cupom da página do anúncio no custo final (PS5/GTA 6; as TVs como antes)
# ------------------------------------------------------------------------------------------------

def _gta_magalu(pix: float, com_cupom: float, **extra) -> Oferta:
    return Oferta(fonte="magalu.produtos", tipo="loja", loja="Magazine Luiza",
                  titulo="Jogo Grand Theft Auto VI (GTA 6) PS5 - Code in Box Pré-venda - Lançamento 19/11",
                  url="https://www.magazineluiza.com.br/jogo-gta-6/p/241923300/ga/jgpn/", id="241923300-magazineluiza",
                  preco=449.90, preco_pix=pix, parcelado="10x R$ 44,99 sem juros", cupom="GTA60", vendedor="Magalu",
                  modelo="GTA6_CODE_IN_BOX",
                  extra={"anuncio": "241923300", "vendedor_id": "magazineluiza", "preco_com_cupom": com_cupom,
                         "cupom_regra": "R$ 60,00 OFF com cupom: GTA60", "entrega_prevista": "2026-11-16", **extra})


def test_cupom_da_pagina_entra_no_custo_final_do_gta():
    o = _gta_magalu(398.0, 338.0)
    assert produtos.preco_com_cupom_do_anuncio(o) == (338.0, "GTA60")
    assert produtos.preco_comparavel(o) == 338.0
    linhas = produtos.linhas_da_oferta(o)
    assert "🎟️ Com o cupom GTA60 do anúncio: R$ 338,00" in linhas
    assert any(l.startswith("🎯 Meta: Pix R$ 345,00") and "abaixo da meta" in l for l in linhas)
    (linha,) = [l for l in produtos.custo_final_gta([o]) if l["loja"] == "Magazine Luiza"]
    assert (linha["custo_final"], linha["preco"], linha["cupom"]) == (338.0, 398.0, "GTA60")


def test_cupom_so_de_assinante_ou_preco_fora_da_faixa_nao_conta():
    assert produtos.preco_com_cupom_do_anuncio(_gta_magalu(398.0, 338.0, cupom_regra="Exclusivo Prime")) is None
    assert produtos.preco_com_cupom_do_anuncio(_gta_magalu(398.0, 120.0)) is None, "abaixo da faixa do produto"
    assert produtos.preco_com_cupom_do_anuncio(_gta_magalu(398.0, 410.0)) is None, "não baixa o preço"


def test_cupom_da_pagina_da_tv_nao_muda_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    tv = Oferta(fonte="magalu", tipo="loja", loja="Magazine Luiza", titulo='Smart TV 65" TCL 4K 65C6K',
                url="https://www.magazineluiza.com.br/tv/p/240162600/", id="240162600-magazineluiza", preco=4299.0,
                preco_pix=4084.05, cupom="LU175", vendedor="Magalu", modelo="65C6K",
                extra={"preco_com_cupom": 3200.0})
    assert produtos.preco_com_cupom_do_anuncio(tv) is None
    assert produtos.preco_comparavel(tv) == 4084.05, "nas TVs o preço da meta continua o melhor preço da loja"


def test_alerta_do_gta_com_o_cupom_da_pagina_na_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    # state de um modo em que a partida do GTA 6 já passou
    d = {"ofertas": {}, "cupons": {}, "minimo": None, "saude": {}, "ultimo_resumo": None,
         "criado_em": "2026-09-13T15:22:00-03:00", "modelos_iniciados": list(produtos.IDS)}
    (tmp_path / "state_cloud.json").write_text(json.dumps(d), encoding="utf-8")
    e = Estado("cloud")
    assert not e.bootstrap and not e.bootstrap_modelo("GTA6_CODE_IN_BOX")
    msgs, alertados = gerar_alertas(e, [_gta_magalu(398.0, 338.0)], [])
    (m,) = [x for x in msgs if "GTA 6" in x]
    assert "🎯 Abaixo do alvo" in m and "cupom <code>GTA60</code>" in m and "Com o cupom GTA60 do anúncio" in m
    assert "chega a tempo" in m
    assert alertados["magalu.produtos:241923300-magazineluiza"] == 338.0
    resumo = resumo_diario(e, [_gta_magalu(398.0, 338.0)], [], False)
    assert "com o cupom GTA60 (sem ele R$ 398,00)" in resumo and "com gift card" not in resumo
    inicio = mensagem_bootstrap([_gta_magalu(398.0, 338.0)], [], "cloud", set(), ["GTA6_CODE_IN_BOX"])
    assert "<b>R$ 338,00</b> com o cupom GTA60 (Magazine Luiza/Magalu) · meta R$ 345,00" in inicio


def test_codigo_de_assinante_no_cupom_da_postagem_nao_vale(tmp_path, monkeypatch):
    # Promobit 29/09: "Grand Theft Auto VI - PlayStation 5" a R$ 395,91 com PRIMEGAME5 (só Prime; o usuário não assina)
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    post = Oferta(fonte="promobit", tipo="post", loja="Amazon", titulo="Grand Theft Auto VI - PlayStation 5",
                  url="https://www.promobit.com.br/oferta/x/", id="p1", preco=339.0, cupom="PRIMEGAME5",
                  modelo="GTA6_CODE_IN_BOX")
    assert produtos.exige_assinatura(post) == "prime"
    assert any("exclusivo de assinatura (prime)" in l for l in produtos.linhas_da_oferta(post))
    assert produtos.custo_final_gta([post]) == [], "preço de assinante não é o custo final do usuário"
    primeira = Oferta(fonte="promobit", tipo="post", loja="Netshoes", titulo="Jogo GTA 6 PS5 Code in Box",
                      url="https://www.promobit.com.br/oferta/y/", id="p2", preco=339.0, cupom="PRIMEIRA20",
                      modelo="GTA6_CODE_IN_BOX")
    assert produtos.exige_assinatura(primeira) is None, "primeira compra não é assinatura"


# ------------------------------------------------------------------------------------------------
# 3. da fonte nova (frente B) ao testador (frente C)
# ------------------------------------------------------------------------------------------------

def test_gta_da_busca_do_magalu_chega_ao_testador_com_o_cupom_e_a_meta(amb):
    ofs, cupons = magalu.parse_busca_produtos(_fx(f"magalu_busca_gta_vi_{D}.html"))
    produtos.anota(ofs)
    d = {"modo": "cloud", "ofertas_loja": [o.to_dict() for o in ofs], "cupons": [c.to_dict() for c in cupons],
         "posts": []}
    (config.DIR_DADOS / "latest_cloud.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    cods, anuncios = tc.codigos_conhecidos(Magalu())
    (a,) = anuncios
    assert (a.chave, a.modelo, a.cupom, a.preco) == ("241923300-magazineluiza", "GTA6_CODE_IN_BOX", "GTA60", 418.41)
    assert (a.alvo_pix, a.alvo_parcelado) == (345.0, 370.0) and "prazo desconhecido" in (a.entrega or "")
    assert cods.compat("GTA60", "GTA6_CODE_IN_BOX") == "sim" and cods.compat("GTA60", "PS5_DIGITAL") == "nao"
    assert "magazineluiza.com.br" in a.url, "o carrinho do Magalu reconhece a URL da fonte nova"


def test_ps5_da_loja_oficial_do_ml_chega_ao_testador(amb):
    (o,) = mercadolivre_loja.parse_loja(_fx(f"ml_loja_playstation_{D}.html"))
    produtos.anota([o])
    d = {"modo": "cloud", "ofertas_loja": [o.to_dict()], "cupons": [], "posts": []}
    (config.DIR_DADOS / "latest_cloud.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    _, anuncios = tc.codigos_conhecidos(MercadoLivre())
    (a,) = anuncios
    assert (a.modelo, a.item_id, a.preco) == ("PS5_DIGITAL", "MLB4214670787", 4369.0)
    assert (a.alvo_pix, a.alvo_parcelado) == (3550.0, 3700.0)


def test_cupom_de_assinante_da_postagem_nao_gasta_teste_no_ps5_e_gta():
    fontes = {"PRIMEGAME5": [{"tipo": "post", "produto": "GTA6_CODE_IN_BOX"}],
              "PRIMEIRA20": [{"tipo": "post", "produto": "GTA6_CODE_IN_BOX"}],
              "OFERTAMELIMAIS": [{"tipo": "post", "produto": "PS5_DIGITAL"}]}
    cods = tc.Codigos(list(fontes), fontes)
    assert cods.compat("PRIMEGAME5", "GTA6_CODE_IN_BOX") == "nao", "o usuário não tem Prime"
    assert cods.compat("OFERTAMELIMAIS", "PS5_DIGITAL") == "nao", "nem Meli+"
    assert cods.compat("PRIMEIRA20", "GTA6_CODE_IN_BOX") == "sim", "primeira compra não é assinatura"
    manual = tc.Codigos(["PRIMEGAME5"], {"PRIMEGAME5": [{"tipo": "manual"}]})
    assert manual.compat("PRIMEGAME5", "GTA6_CODE_IN_BOX") == "sim", "CUPONS_EXTRA/--codigos valem para todos"


# ------------------------------------------------------------------------------------------------
# 4. testador durante a vigia: a TV que saiu do carrinho fica fora
# ------------------------------------------------------------------------------------------------

def test_tv_tirada_do_carrinho_fica_fora_durante_a_vigia(amb, vigia, capsys):
    _latest(amb, [O_PS5D, O_GTA])
    estado = {"magalu": {"cupons": {}, "tvs_fora": {"55C6K": {"desde": _iso(FIXO), "tentativas": 0}}}}
    loja = CarrinhoProdutos(amb.pasta)
    amb.rodar(loja, estado)
    out = capsys.readouterr().out
    assert "fora do testador nesta rodada (modo vigia); não volta ao carrinho" in out
    assert "vai de volta nesta rodada" not in out
    assert "tvs_fora" not in estado["magalu"], "o registro de devolver a TV sai (decisão do usuário: TVs fora)"
    assert sorted(loja.carrinho) == sorted([K_PS5D, K_GTA]), "o PS5 e o GTA 6 seguem; nenhuma TV volta"
    assert not any("TV" in a for a in tc.AVISOS_CARRINHO)


# ------------------------------------------------------------------------------------------------
# 5. histórico: o PS5/GTA 6 só grava quando o preço muda (ou uma vez por dia); as TVs, toda rodada
# ------------------------------------------------------------------------------------------------

def test_historico_do_ps5_e_gta_so_grava_quando_muda(tmp_path, monkeypatch):
    import csv

    from monitor import estado as est_mod

    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    relogio = {"agora": "2026-10-03T18:00:00-03:00"}
    monkeypatch.setattr(est_mod, "agora_iso", lambda: relogio["agora"])
    tv = Oferta(fonte="magalu", tipo="loja", loja="Magazine Luiza", titulo='Smart TV 65" TCL 4K 65C6K',
                url="https://www.magazineluiza.com.br/tv/p/240162600/", id="240162600-magazineluiza", preco=4299.0,
                preco_pix=4084.05, vendedor="Magalu", modelo="65C6K")

    def rodada(pix):
        e = Estado("cloud")
        e.anexa_historico([tv, _gta_magalu(pix, pix - 60)])
        e.salva()

    def linhas():
        with (tmp_path / "historico_cloud.csv").open(encoding="utf-8") as f:
            return [(r["modelo"], r["preco_pix"]) for r in csv.DictReader(f)]

    rodada(418.41)
    rodada(418.41)                                   # 15 min depois, nada mudou: só a TV repete
    assert linhas() == [("65C6K", "4084.05"), ("GTA6_CODE_IN_BOX", "418.41"), ("65C6K", "4084.05")]
    rodada(398.0)                                    # o preço mudou: a linha do GTA entra
    assert linhas()[-1] == ("GTA6_CODE_IN_BOX", "398.0")
    relogio["agora"] = "2026-10-04T09:00:00-03:00"
    rodada(398.0)                                    # dia novo: entra de novo (o gráfico tem um ponto por dia)
    assert linhas()[-1] == ("GTA6_CODE_IN_BOX", "398.0") and len(linhas()) == 7
    ultimas = json.loads((tmp_path / "state_cloud.json").read_text(encoding="utf-8"))["historico_ultimas"]
    assert list(ultimas) == ["magalu.produtos:241923300-magazineluiza"], "só o dia de hoje e sem as TVs"
    assert ultimas["magalu.produtos:241923300-magazineluiza"]["dia"] == "2026-10-04"
