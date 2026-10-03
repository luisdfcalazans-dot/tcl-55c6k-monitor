"""Passada de lista fechada do PS5/GTA 6 (03/10/2026, depois da 2ª conferência).

P1. (média) Entrega do GTA na VTEX contada em dobro: a estimativa ("39bd") conta a partir de HOJE; só a data que cai
    antes de 12/11 (quando as caixas saem) é reprojetada (entrega.ajusta_pre_venda). Mantém o limite de 18/11 e o feriado
    de 20/11.
P2. (média) PS5 COM leitor cujo título não traz "Console" antes de "Leitor de Disco" ("PlayStation 5 Slim 1TB Leitor de
    Disco Branco", "PS5 Slim Leitor de Disco 1TB + 2 Jogos") é o console (PS5_DISCO), não o leitor avulso. O leitor
    avulso é o assunto do título ("Leitor de Disco para PS5 Digital/Pro", "Unidade de Disco ... para console PS5").
P3. (média) Cupom do console que cita "com leitor" sem a palavra console ("R$ 200 OFF no PS5 Slim com Leitor de Disco")
    é do console; só é cupom do leitor quando o leitor é o assunto ("no Leitor de Disco", "Leitor de Disco PS5 por R$").
P4. (baixa) Acessórios e produtos temáticos do GTA ("Mousepad Gamer Grande - GTA VI PAISAGEM 2 - 90x40", "Suporte para
    Controle Gamer GTA VI Edição Exclusiva", pôster, camiseta, caneca, chaveiro) e outros jogos (GTA V, Trilogy, GTA V
    Premium) são recusados pelo CLASSIFICADOR, não só pela faixa de preço.
P5. (conferência) As duas edições do GTA 6: Standard (Code in Box e digital) e Ultimate (só digital no Brasil). A tabela
    "GTA 6 em todas as formas pelo custo final", o alerta e o resumo comparam a Ultimate digital com "Standard (Code in
    Box ou digital) + upgrade R$ 100" pelo custo final e mostram as duas edições.

Nada acessa a rede nem abre navegador.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date

import pytest

from monitor import produtos
from monitor.models import Cupom, Oferta
from monitor.regras import cupom_compativel, sanear
from monitor.sources import entrega, vtex
from monitor.util import agora_iso


class _Hoje(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 3)


@pytest.fixture
def hoje_03_10(monkeypatch):
    monkeypatch.setattr(entrega, "hoje", lambda: date(2026, 10, 3))
    monkeypatch.setattr(produtos, "date", _Hoje)


# ------------------------------------------------------------------------------------------------
# P1. entrega do GTA na VTEX: a estimativa conta de hoje; só o que cai antes de 12/11 é reprojetado
# ------------------------------------------------------------------------------------------------

class _Resp:
    def __init__(self, d):
        self.d = d

    def json(self):
        return self.d

    def raise_for_status(self):
        pass


def _gta_vtex(monkeypatch, estimativa, descricao="Pré-venda. Lançamento 19/11/2026", preco=340.0):
    gta = {"productId": "9", "productName": "Jogo Grand Theft Auto VI PS5 Code in Box", "link": "https://x/p",
           "description": descricao,
           "items": [{"itemId": "1", "ean": "0710425676338", "sellers": [{"sellerId": "1", "sellerName": "AMERICANAS SA",
                      "commertialOffer": {"Price": preco, "AvailableQuantity": 5, "Installments": []}}]}]}
    monkeypatch.setattr(vtex, "get_json", lambda url, **k: [gta])
    sim = {"logisticsInfo": [{"itemIndex": 0, "slas": [{"id": "NORMAL", "shippingEstimate": estimativa,
                                                       "deliveryChannel": "delivery"}]}]}
    monkeypatch.setattr(vtex.requests, "post", lambda *a, **k: _Resp(sim))
    (o,), _ = vtex.VtexEan("americanas").coletar()
    return o


@pytest.mark.parametrize("estimativa,data,classe,meta", [
    # sábado 03/10 + N dias úteis (12/10 e 02/11 são feriados): já cai depois de 12/11, vale como está
    ("28bd", "2026-11-13", "a_tempo", 345.0),
    ("30bd", "2026-11-17", "a_tempo", 345.0),
    ("31bd", "2026-11-18", "a_tempo", 345.0),     # 18/11: o último dia para jogar à meia-noite
    ("32bd", "2026-11-19", "no_dia", 300.0),
    ("33bd", "2026-11-23", "depois", 300.0),      # 20/11 (sexta) é feriado nacional: pula para segunda 23/11
    ("39bd", "2026-12-01", "depois", 300.0),      # a Webfones da Fast Shop (rodada seca): não 11/01/2027
    # antes de 12/11: o trânsito conta a partir de 12/11 (correção da 1ª revisão, mantida)
    ("5bd", "2026-11-19", "no_dia", 300.0),
])
def test_vtex_estimativa_conta_de_hoje_e_so_reprojeta_antes_de_12_11(monkeypatch, hoje_03_10, estimativa, data,
                                                                       classe, meta):
    monkeypatch.delenv("CEP_ENTREGA", raising=False)
    o = _gta_vtex(monkeypatch, estimativa)
    assert o.extra["entrega_prevista"] == data
    assert o.extra["entrega_ate_lancamento"] is (data <= produtos.ENTREGA_LIMITE_GTA6)
    assert produtos.entrega(o).classe == classe
    assert produtos.alvos_da_oferta(o, "2026-10-03").pix == meta


def test_vtex_data_depois_de_12_11_nao_diz_contado_a_partir_de_12_11(monkeypatch, hoje_03_10):
    monkeypatch.delenv("CEP_ENTREGA", raising=False)
    o = _gta_vtex(monkeypatch, "30bd")
    assert "12/11" not in o.extra.get("entrega_origem", "")
    e = produtos.entrega(o)
    assert "previsão 17/11" in e.texto and "contado a partir de 12/11" not in e.texto and "chega a tempo" in e.texto
    # o que é reprojetado continua dizendo
    o5 = _gta_vtex(monkeypatch, "5bd")
    assert "12/11" in o5.extra["entrega_origem"] and "contado a partir de 12/11" in produtos.entrega(o5).texto


def test_vtex_envio_informado_continua_valendo(monkeypatch, hoje_03_10):
    monkeypatch.delenv("CEP_ENTREGA", raising=False)
    # "Envios a partir de 16/11": 2 dias úteis contados de hoje (06/10) viram 2 dias úteis depois de 16/11
    o = _gta_vtex(monkeypatch, "2bd", "Envios a partir de 16/11/2026")
    assert o.extra["entrega_prevista"] == "2026-11-18" and produtos.entrega(o).classe == "a_tempo"
    # uma estimativa que já cai depois do envio informado vale como está
    o = _gta_vtex(monkeypatch, "32bd", "Envios a partir de 16/11/2026")
    assert o.extra["entrega_prevista"] == "2026-11-19"


def test_simula_prazo_com_inicio_nao_conta_em_dobro(monkeypatch, hoje_03_10):
    for est, sem, com in (("5bd", "2026-10-09", "2026-11-19"), ("39bd", "2026-12-01", "2026-12-01"),
                          ("28bd", "2026-11-13", "2026-11-13")):
        sim = {"logisticsInfo": [{"slas": [{"shippingEstimate": est, "deliveryChannel": "delivery"}]}]}
        monkeypatch.setattr(vtex.requests, "post", lambda *a, sim=sim, **k: _Resp(sim))
        assert vtex.simula_prazo("https://x", "1", "1", "01310100") == sem, est
        assert vtex.simula_prazo("https://x", "1", "1", "01310100", inicio=date(2026, 11, 12)) == com, est
