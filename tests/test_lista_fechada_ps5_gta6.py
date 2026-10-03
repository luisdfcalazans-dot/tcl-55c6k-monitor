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


# ------------------------------------------------------------------------------------------------
# P2. PS5 com leitor sem "Console" antes do leitor é o console; o leitor avulso é o assunto do título
# ------------------------------------------------------------------------------------------------

# o console com leitor (o leitor é uma característica dele): os da 2ª conferência e os reais dos caches/latest de 03/10
CONSOLES_COM_LEITOR = [
    "PlayStation 5 Slim 1TB Leitor de Disco Branco",
    "PS5 Slim Leitor de Disco 1TB + 2 Jogos",
    "PS5 Slim Leitor de Disco 1TB",
    "Playstation 5 Slim Leitor De Disco 1tb Branco",
    "PlayStation 5 Slim - Leitor de Disco - 1TB - Sony",
    "Sony Playstation 5 Slim Leitor de Disco Branco",
    "PlayStation 5 Slim Leitor de Disco 1TB 2 Jogos",
    "PS5 Slim Mídia Física Leitor de Disco",
    "PS5 Slim Standard (Leitor de Disco) 1TB",
    "PS5 Leitor de Disco 1TB Slim",
    # reais (caches e latest de 03/10)
    "Console PlayStation 5 Slim 1TB SSD com Leitor de Disco - Sony",
    "Console PlayStation 5 Sony, SSD 1TB, Leitor de Discos, Controle DualSense, Astro's Playroom, Branco - 1000049892",
    "Console Sony PlayStation 5 Com Leitor De Discos SSD 1TB Controle Sem Fio Dualsense - 2 Jogos Branco",
    "Console Sony PlayStation 5 Slim 1TB Leitor de Discos",
    "[REGIONAL] Console Sony PlayStation 5 Slim 1TB Leitor de Discos",
    "[pelandobr] 🌡️ 211° - PlayStation 5 com leitor de disco , 1TB, DualSense",
    "[pelandobr] 🌡️ 225° - PlayStation 5 com leitor de disco e 1 TB de armazenamento",
    "Console Sony Playstation 5 Standard 825GB e leitor de blue ray",
    "Console PlayStation 5 Slim Leitor de Disco 1TB Branco",
    "PlayStation®5 Slim com leitor de disco",
]

# o leitor avulso (o assunto do título): reais dos caches/latest de 03/10, os da 1ª revisão e os do pedido
LEITORES_AVULSOS = [
    "(Saldo MP / Meli+) Unidade De Disco Leitor Playstation 5 Slim / Pro",
    "15% OFF no Leitor de Disco PS5 Slim",
    "15% OFF no leitor de disco para PlayStation 5 Slim e PS5 Pro",
    "Leitor Disco Playstation 5 Slim PS5 Pro Sony Branco",
    "Leitor de Disco PS5 Slim Pro Digital Branco CFI-2000",
    "Leitor de Disco PS5 Sony - Compatível Slim/Pro",
    "Leitor de Disco Para Playstation 5 Slim, PS5 Pro Sony, Edição digital, Branco - CFI-2000 - slim",
    "Leitor de Disco Sony PS5 Slim/Pro Branco",
    "Unidade de disco Leitor PS5 Edição Digital PS5 Pro",
    "Unidade de disco para PS5® digital/slim ou PS5 Pro",
    "[PRIME] Leitor de Disco Para Playstation 5 Slim, PS5 Pro Sony, Edição digital",
    "[pelandobr] 🌡️ 228° - Leitor de Disco PS5 Slim Pro Digital Branco CFI-2000",
    # 1ª revisão (o nome oficial da Sony e "Console" depois do leitor)
    "Unidade de Disco para Consoles PS5 Digital Edition - Sony",
    "Leitor de Disco Ultra HD Blu-ray Console PS5 Slim",
    "Sony - Leitor de Disco Console PS5 Slim",
    "Drive de Disco para Console PlayStation 5 Pro",
    # os do pedido: o leitor "para" o PS5, mesmo com o PS5 escrito antes
    "Leitor de Disco para PS5 Digital/Pro",
    "Unidade de Disco Blu-ray para console PS5",
    "Unidade de Disco Sony para console PS5 Digital Edition",
    "Sony PS5 Unidade de Disco para PS5 Slim Digital e PS5 Pro",
    "PS5 Leitor de Disco para Console Digital",
    # a versão que não tem leitor (Pro, Digital) seguida do leitor, sem nada de console: a peça para ela
    "PlayStation 5 Pro Leitor de Disco",
    "PS5 Slim Digital Leitor de Disco Sony",
]


@pytest.mark.parametrize("titulo", CONSOLES_COM_LEITOR)
def test_console_com_leitor_sem_console_antes_e_ps5_disco(titulo):
    c = produtos.classifica(titulo)
    assert c.produto == "PS5_DISCO", c


@pytest.mark.parametrize("titulo", LEITORES_AVULSOS)
def test_leitor_avulso_continua_leitor(titulo):
    c = produtos.classifica(titulo)
    assert c.produto == "LEITOR_PS5", c


@pytest.mark.parametrize("titulo", ["PS5 Slim Leitor de Disco 1TB", "Playstation 5 Slim Leitor De Disco 1tb Branco",
                                    "PlayStation 5 Slim - Leitor de Disco - 1TB - Sony"])
def test_console_com_leitor_abaixo_da_meta_nao_some_no_sanear(titulo):
    c = produtos.classifica(titulo)
    o = Oferta("promobit", "post", "Amazon", titulo, "https://p/x", "x", preco=3799.0, modelo=c.produto,
               publicado=agora_iso())
    fica, avisos = sanear([o])
    assert fica and fica[0].modelo == "PS5_DISCO", avisos


@pytest.mark.parametrize("titulo,esperado", [
    # kits e consoles que já davam certo continuam
    ("Console PS5 Slim Digital + Leitor de Disco Sony", "PS5_KIT"),
    ("PlayStation 5 Slim Digital + Unidade de Disco", "PS5_KIT"),
    ("Console PS5 Pro + Leitor de Disco + GTA VI", "PS5_KIT"),
    ("Leitor de Disco + Console PS5 Digital", "PS5_DIGITAL"),
    ("PS5 Pro 2TB com Unidade de Disco", "PS5_PRO"),
    ("PlayStation 5 Pro Console 2TB (sem leitor de disco)", "PS5_PRO"),
    ("PS5 Slim c/ Leitor de Disco 1TB", "PS5_DISCO"),
])
def test_kits_e_versoes_com_leitor_nao_mudam(titulo, esperado):
    assert produtos.classifica(titulo).produto == esperado


def test_leitor_da_pessoa_no_carrinho_continua_fora_dos_principais():
    from monitor.carrinho import modelo_da_linha, produto_do_titulo

    # a defesa do carrinho (1ª revisão) não muda: uma linha que cita o leitor como peça nunca é um principal
    for t in LEITORES_AVULSOS[:16]:
        assert produto_do_titulo(t) is None and modelo_da_linha(t) is None, t
