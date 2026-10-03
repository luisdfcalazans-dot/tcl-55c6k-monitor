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


# ------------------------------------------------------------------------------------------------
# P3. cupom do console que cita "com leitor" é do console; só é do leitor quando o leitor é o assunto
# ------------------------------------------------------------------------------------------------

CONSOLES = ("PS5_DIGITAL", "PS5_DISCO", "PS5_PRO", "PS5_KIT")


def _cupom(loja, codigo, titulo, regra=""):
    return Cupom("promobit", loja, codigo, titulo, "https://c", codigo, regra=regra)


def _servem(c):
    return {p for p in CONSOLES + ("LEITOR_PS5", "GTA6_CODE_IN_BOX", "GIFT_CARD_PSN") if cupom_compativel(c, None, p)[0]}


@pytest.mark.parametrize("loja,codigo,titulo", [
    ("KaBuM!", "PS5C200", "R$ 200 OFF no PS5 Slim com Leitor de Disco"),
    ("KaBuM!", "PS5COMLEITOR", "Cupom PS5 com leitor"),
    ("Magazine Luiza", "PS5C300", "R$ 300 OFF no PlayStation 5 com leitor"),
    ("Amazon", "PS5STD", "10% OFF PS5 Slim Edição Standard (com leitor)"),
    ("KaBuM!", "PS5CL", "R$ 250 OFF no PS5 Slim c/ Leitor de Disco 1TB"),
    ("KaBuM!", "PS5SLD", "R$ 300 OFF no PS5 Slim Leitor de Disco 1TB"),   # o console com leitor (P2)
    ("Netshoes", "PS5KIT", "R$ 400 OFF no PS5 Digital + Leitor de Disco"),  # o kit (o leitor vem junto)
])
def test_cupom_do_console_com_leitor_serve_para_o_console(loja, codigo, titulo):
    c = _cupom(loja, codigo, titulo)
    assert cupom_compativel(c, None, "PS5_DISCO") == (True, "")
    assert _servem(c) == set(CONSOLES), _servem(c)
    assert cupom_compativel(c, None, "LEITOR_PS5")[1] == "cupom só de console"


@pytest.mark.parametrize("loja,codigo,titulo", [
    ("KaBuM!", "LEITOR62", "R$ 62 OFF no Leitor de Disco PS5"),               # o caso real da pesquisa (10/09)
    ("KaBuM!", "LEITOR399", "Leitor de Disco PS5 por R$ 399 com cupom"),
    ("KaBuM!", "LEITORPS5", "Cupom de R$ 50 OFF no Leitor de Disco do PS5 Digital"),
    ("Pelando", "DRIVE", "10% OFF Leitor de Disco Sony para PS5 Slim"),
    ("Netshoes", "UNIDADE", "R$ 80 OFF na Unidade de Disco PS5"),             # "unidade de disco" também é o leitor
    ("KaBuM!", "VIRADISC", "15% OFF no leitor de disco"),
    ("KaBuM!", "UNIDCONS", "R$ 50 OFF na Unidade de Disco para Consoles PS5 Digital"),
])
def test_cupom_do_leitor_continua_so_do_leitor(loja, codigo, titulo):
    c = _cupom(loja, codigo, titulo)
    assert _servem(c) == {"LEITOR_PS5"}, _servem(c)
    assert cupom_compativel(c, None, "PS5_DISCO")[1] == "cupom só de leitor"


@pytest.mark.parametrize("titulo", ["10% OFF em consoles e leitores de disco", "R$ 150 OFF em Consoles e Leitores"])
def test_cupom_de_consoles_e_leitores_serve_para_os_dois(titulo):
    assert _servem(_cupom("KaBuM!", "X", titulo)) == set(CONSOLES) | {"LEITOR_PS5"}


# ------------------------------------------------------------------------------------------------
# P4. acessórios e produtos temáticos do GTA e outros jogos: recusados pelo classificador
# ------------------------------------------------------------------------------------------------

# (título, loja): os da busca do Magalu de 03/10 (ANOTACOES), os do pedido e variações com a peça depois do nome
ACESSORIOS_E_TEMATICOS_GTA = [
    ("Mousepad Gamer Grande - GTA VI PAISAGEM 2 - 90x40", "Magazine Luiza"),          # Head Glitch Store
    ("Mousepad Gamer Grande - GTA VI PAISAGEM 2 - 90x40 - PS5", "Magazine Luiza"),
    ("Suporte para Controle Gamer GTA VI Edição Exclusiva", "Magazine Luiza"),         # mi7computadores
    ("Suporte para Controle Gamer GTA VI Edição Exclusiva PS5", "Magazine Luiza"),
    ("Pôster GTA VI Vice City 60x90", ""),
    ("Poster GTA 6 Lucia e Jason", ""),
    ("Camiseta GTA VI Vice City Unissex", ""),
    ("Camiseta Grand Theft Auto VI", ""),
    ("Caneca GTA 6 Porcelana 325ml", ""),
    ("Caneca Personalizada GTA VI PS5", ""),
    ("Chaveiro GTA VI Logo Metal", ""),
    ("Quadro Decorativo GTA VI 30x40", ""),
    ("Funko Pop GTA VI Lucia", ""),
    # a peça depois do nome do jogo (antes viravam o Code in Box ou o pacote com o PS5)
    ("GTA VI Mousepad Gamer Grande 90x40", ""),
    ("Grand Theft Auto VI Suporte de Controle", ""),
    ("Grand Theft Auto VI - Suporte para Controle Gamer", ""),
    ("GTA 6 Skin PS5 Slim", ""),
    ("GTA VI Headset Gamer", ""),
    ("GTA VI Teclado Mecânico", ""),
    ("GTA VI Caneca PS5 Slim", ""),
    ("GTA VI - Camiseta Vice City", ""),
    # temáticos que faltavam na lista
    ("Lençol GTA VI Vice City", ""),
    ("Moletom GTA VI", ""),
    ("Pelúcia GTA VI", ""),
    ("Relógio GTA VI", ""),
    ("Camisa GTA VI Lucia", ""),
    ("Estátua GTA VI Jason", ""),
    ("Quebra-Cabeça GTA VI 1000 peças", ""),
    # títulos reais da busca do Magalu por "gta vi" (03/10/2026): só o Code in Box do Magalu é o jogo
    ("Mouse pad Gamer Grande - GTA VI PAISAGEM 1 - 90x40 80x40 60x40 70x30", "Magazine Luiza"),     # Head Glitch Store
    ("Mouse pad Gamer Grande - GTA VI PAISAGEM COM MULHER 1 - 90x40 80x40 60x40 70x30", "Magazine Luiza"),
    ("Suporte para Controle Gamer GTA VI  Edição Exclusiva", "Magazine Luiza"),                     # mi7computadores
    ("Placa Decorativa GTA VI  Edição Exclusiva Fan Art", "Magazine Luiza"),
    ("Cofrinho GTA VI  Economize com estilo de jogador", "Magazine Luiza"),
    ("Capa Case Antipoeira Ps5 Protetora Console PS5 Fat GTA VI", "Magazine Luiza"),
    ("Capa Case Antipoeira Ps5 Prot PS5 FAT DIGITAL/DISCO GTA VI", "Magazine Luiza"),
    ("Kit GTA VI Caneca de Cerâmica + Garrafa Squeeze Exclusivo", "Magazine Luiza"),
    ("Caneca de Porcelana Lançamento Jogo GTA VI Vice City 325mL", "Magazine Luiza"),
    ("Caneca Jogo GTA VI 6 Gamer Presente Geek Videogame Decoração -", "Magazine Luiza"),
    ("Pôster Decorativo GTA VI Jason e Lucia - Arte A - 50cm x 70cm", "Magazine Luiza"),
    ("Pôsterzine PLAY Games - Grand Theft Auto VI - Cover - 50cm x 70cm", "Magazine Luiza"),
    ("Pôster Gigante - Grand Theft Auto VI", "Magazine Luiza"),
    ("Quadro Decorativo Grand Theft Auto VI geek.frame - 7898960704198", "Magazine Luiza"),
    ("Decoração Logo GTA VI para decorar quarto", "Magazine Luiza"),
    ("Camiseta Unissex Grand Theft Auto GTA VI - Premium Tamanho:PPCor:Preto", "Magazine Luiza"),
    ("Camiseta Manga Longa Grand Theft Auto GTA VI - Premium Tamanho:12Cor:Preto", "Magazine Luiza"),
]

OUTROS_JOGOS_GTA = [
    "Grand Theft Auto V PS5",
    "Grand Theft Auto V - PlayStation 5",
    "Jogo Grand Theft Auto V - PS5 Mídia Física",
    "GTA V Premium Edition PS5",
    "GTA V Premium",
    "Grand Theft Auto V Edição Premium Online",
    "Jogo GTA 5 Edição Premium PS5 Mídia Física",
    "Jogo Grand Theft Auto 5 Para PS5",
    "GTA Trilogy PS5",
    "GTA Trilogy Definitive Edition - PlayStation 5",
    "Grand Theft Auto: The Trilogy - The Definitive Edition PS5",
    "Grand Theft Auto: A Trilogia – Edição Definitiva",
    "GTA San Andreas PS5",
    "GTA Vice City",
    # reais da busca do Magalu por "gta vi" (03/10/2026, vendedor nocnocestadosunidos)
    "Jogo de Vídeo Game Take 2 Interactive Grand Theft Auto 5 para PS5",
    "Jogo de Vídeo Rockstar Games GTA Trilogy Definitiva PS4",
    "Jogo de Vídeo Game Aeuln Grand Theft Auto V Edição Premium",
    "Videojogo Rockstar Games GTA V Premium Online Edition",
    "Videojogo Rockstar Games Grand Theft Auto V Premium",
]


@pytest.mark.parametrize("titulo,loja", ACESSORIOS_E_TEMATICOS_GTA)
def test_acessorio_ou_tematico_do_gta_e_recusado_pelo_classificador(titulo, loja):
    c = produtos.classifica(titulo, loja or None)
    assert c.produto is None, c
    assert c.motivo.startswith(("acessório", "produto temático")), c


@pytest.mark.parametrize("titulo", OUTROS_JOGOS_GTA)
def test_outro_jogo_do_gta_e_recusado_pelo_classificador(titulo):
    c = produtos.classifica(titulo, "Magazine Luiza")
    assert c.produto is None and c.motivo.startswith("outro jogo"), c


@pytest.mark.parametrize("titulo,esperado", [
    # o jogo continua sendo o jogo (títulos reais dos caches/latest de 03/10 e os brindes do próprio jogo)
    ("Jogo Grand Theft Auto VI (GTA 6) PS5 - Code in Box Pré-venda - Lançamento 19/11", "GTA6_CODE_IN_BOX"),
    ("Jogo Grand Theft Auto VI GTA 6 PS5 Code In Box Pré-venda Lançamento Preto", "GTA6_CODE_IN_BOX"),
    ("[pelandobr] [Pré venda] Jogo Grand Theft Auto VI GTA 6 - PS5 - Mídia Física", "GTA6_CODE_IN_BOX"),
    ("Grand Theft Auto VI - PlayStation 5", "GTA6_CODE_IN_BOX"),
    ("GTA VI PS5 Pré-venda Mídia Física Brinde Mapa", "GTA6_CODE_IN_BOX"),
    ("Jogo GTA VI PS5 Code in Box + Brinde Mapa de Vice City", "GTA6_CODE_IN_BOX"),
    ("GTA 6 PS5 com brinde camiseta", "GTA6_CODE_IN_BOX"),
    ("GTA VI Edição Standard PS5 Digital", "GTA6_DIGITAL"),
    ("[Pré-venda] Grand Theft Auto VI: Ultimate Edition", "GTA6_ULTIMATE"),
    ("Bundle GTA VI + PlayStation 5 Slim Digital 825 GB Pacote Astro Bot e Gran Turismo 7", "PS5_DIGITAL_GTA6"),
    ("[pelandobr] GTA VI + PS5 Slim Disk + Astro Bot + GT7", "PS5_DISCO_GTA6"),
])
def test_o_jogo_e_os_pacotes_continuam(titulo, esperado):
    assert produtos.classifica(titulo).produto == esperado


@pytest.mark.parametrize("msg", [
    "🔥 GTA VI\nMousepad Gamer Grande 90x40\n💰 R$ 249",
    "Mousepad Gamer Grande - GTA VI PAISAGEM 2 - 90x40\n💰 R$ 249,90\nMagalu",
    "GTA VI Mousepad Gamer Grande 90x40 R$ 249",
    "Grand Theft Auto VI - Suporte para Controle Gamer\nR$ 259",
])
def test_mensagem_do_canal_com_acessorio_do_gta_nao_vira_o_jogo(msg):
    assert not any(p.startswith("GTA6") for p in produtos.extrai_produtos(msg))


def test_mensagem_do_jogo_com_descricao_continua_o_jogo():
    r = produtos.extrai_produtos("GTA VI PS5 Code in Box\n💰 R$ 339\n✅ Suporte a legendas em português")
    assert "GTA6_CODE_IN_BOX" in r


def test_mensagem_com_o_gta_6_e_outro_gta_separa_os_blocos():
    # a linha de outro GTA abre o bloco de outro produto: o preço dele não entra no do GTA 6
    r = produtos.extrai_produtos("GTA VI PS5 Code in Box\n💰 R$ 339\nGrand Theft Auto V para PS5\n💰 R$ 59")
    assert "R$ 59" not in r["GTA6_CODE_IN_BOX"].trecho and "R$ 339" in r["GTA6_CODE_IN_BOX"].trecho


# ------------------------------------------------------------------------------------------------
# P5. as duas edições do GTA 6: Ultimate digital × Standard (Code in Box ou digital) + upgrade, pelo custo final
# ------------------------------------------------------------------------------------------------

URL_ULT = "https://store.playstation.com/pt-br/product/EP1004-PPSA01547_00-GTAVIULTIMATE001"
URL_STD = "https://store.playstation.com/pt-br/product/EP1004-PPSA01547_00-GTAVISTANDARD001"


def _cib(loja="KaBuM!", preco=449.9, pix=418.41, oid="1051619", tipo="loja", entrega_prevista="2026-11-17"):
    return Oferta("kabum", tipo, loja, "Jogo Grand Theft Auto VI PS5 Code in Box", f"https://k/{oid}", oid, preco=preco,
                  preco_pix=pix, vendedor=loja, modelo="GTA6_CODE_IN_BOX", publicado=agora_iso(),
                  extra={"entrega_prevista": entrega_prevista} if entrega_prevista else {})


def _ps(pid, preco, url, oid):
    titulo = {"GTA6_DIGITAL": "Grand Theft Auto VI", "GTA6_ULTIMATE": "Grand Theft Auto VI: Ultimate Edition",
              "GTA6_UPGRADE": "Grand Theft Auto VI: Melhoria Ultimate Edition"}[pid]
    return Oferta("psstore", "loja", "PlayStation Store", titulo, url, oid, preco=preco, vendedor="PlayStation Store",
                  modelo=pid)


def _gift_nuuvem():
    return Oferta("promobit", "post", "Nuuvem", "Gift Card PlayStation R$ 300", "https://p/g", "g1", preco=242.74,
                  modelo="GIFT_CARD_PSN", publicado=agora_iso())


def test_custo_final_mostra_as_duas_edicoes_e_o_standard_mais_upgrade():
    linhas = produtos.custo_final_gta([_cib(), _ps("GTA6_DIGITAL", 449.90, URL_STD, "s"),
                                       _ps("GTA6_ULTIMATE", 549.90, URL_ULT, "u")])
    assert {l["edicao"] for l in linhas} == {"Standard", "Ultimate"}
    std = {l["produto"]: l for l in linhas if l["edicao"] == "Standard"}
    assert set(std) == {"GTA6_CODE_IN_BOX", "GTA6_DIGITAL"}
    ult = [l for l in linhas if l["edicao"] == "Ultimate"]
    # a Ultimate digital e o Standard (Code in Box e digital) + upgrade de R$ 100 (preço oficial: a PS Store ainda não
    # vende o upgrade), pelo custo final
    combos = {l["via"]: l for l in ult if l.get("via")}
    assert set(combos) == {"GTA6_CODE_IN_BOX", "GTA6_DIGITAL"}
    assert combos["GTA6_CODE_IN_BOX"]["custo_final"] == 518.41 and combos["GTA6_DIGITAL"]["custo_final"] == 549.90
    assert "Standard" in combos["GTA6_CODE_IN_BOX"]["forma"] and "upgrade" in combos["GTA6_CODE_IN_BOX"]["forma"]
    assert combos["GTA6_CODE_IN_BOX"]["entrega"] == "a_tempo"            # a caixa ainda tem de chegar
    assert combos["GTA6_CODE_IN_BOX"]["meta"] == 450.0                   # a meta da Ultimate
    (digital,) = [l for l in ult if l["produto"] == "GTA6_ULTIMATE"]
    assert digital["custo_final"] == 549.90 and digital["entrega"] == "digital"
    assert [l["custo_final"] for l in linhas] == sorted(l["custo_final"] for l in linhas)


def test_custo_final_com_gift_card_desconta_a_ultimate_e_o_upgrade():
    d = 1 - 242.74 / 300
    linhas = produtos.custo_final_gta([_cib(), _ps("GTA6_ULTIMATE", 549.90, URL_ULT, "u"), _gift_nuuvem()])
    (ult,) = [l for l in linhas if l["produto"] == "GTA6_ULTIMATE" and l["tipo"] == "loja"]
    assert ult["custo_final"] == round(549.90 * (1 - d), 2)
    (combo,) = [l for l in linhas if l.get("via") == "GTA6_CODE_IN_BOX"]
    assert combo["custo_final"] == round(418.41 + round(100.0 * (1 - d), 2), 2)   # o upgrade é pago na PS Store


def test_custo_final_sem_ultimate_vista_usa_o_preco_oficial():
    linhas = produtos.custo_final_gta([_cib()])
    ult = [l for l in linhas if l["edicao"] == "Ultimate"]
    assert any(l["produto"] == "GTA6_ULTIMATE" and l["custo_final"] == 549.90 and l["tipo"] == "calculo" for l in ult)
    assert any(l.get("via") == "GTA6_CODE_IN_BOX" and l["custo_final"] == 518.41 for l in ult)


def test_custo_final_nao_corta_a_ultimate_com_muitas_ofertas_standard():
    muitas = [_cib(loja="KaBuM!", preco=400.0 + i, pix=None, oid=f"k{i}") for i in range(40)]
    linhas = produtos.custo_final_gta(muitas + [_ps("GTA6_ULTIMATE", 549.90, URL_ULT, "u")])
    assert any(l["produto"] == "GTA6_ULTIMATE" for l in linhas) and any(l.get("via") for l in linhas)


def test_comparacao_da_ultimate_pelo_custo_final():
    c = produtos.comparacao_ultimate([_cib(pix=340.0), _ps("GTA6_ULTIMATE", 549.90, URL_ULT, "u")])
    assert c["ultimate"]["custo"] == 549.90 and c["upgrade"]["custo"] == 100.0
    assert c["standard"]["custo"] == 340.0 and c["standard"]["produto"] == "GTA6_CODE_IN_BOX"
    assert c["standard_mais_upgrade"] == 440.0 and c["mais_barato"] == "standard+upgrade"


def _estado_iniciado(tmp_path, monkeypatch):
    from monitor import config
    from monitor.estado import Estado

    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    d = {"ofertas": {}, "cupons": {}, "minimo": None, "saude": {}, "ultimo_resumo": None,
         "criado_em": "2026-09-13T15:22:00-03:00", "modelos_iniciados": list(produtos.IDS)}
    (tmp_path / "state_cloud.json").write_text(json.dumps(d), encoding="utf-8")
    return Estado("cloud")


def test_alerta_do_standard_compara_com_a_ultimate(tmp_path, monkeypatch):
    from monitor.regras import gerar_alertas

    e = _estado_iniciado(tmp_path, monkeypatch)
    post = _cib(loja="KaBuM!", preco=340.0, pix=None, oid="p1", tipo="post")
    msgs, _ = gerar_alertas(e, [post, _ps("GTA6_ULTIMATE", 549.90, URL_ULT, "u")], [])
    (m,) = [x for x in msgs if "Code in Box" in x.split("\n")[0]]
    linha = next(l for l in m.split("\n") if l.startswith("🆚"))
    assert "Ultimate" in linha and "Standard" in linha and "upgrade" in linha
    assert "R$ 440,00" in linha and "R$ 549,90" in linha and "R$ 109,90" in linha
    assert "meta da Ultimate" in linha


def test_alerta_da_ultimate_compara_com_o_standard_mais_upgrade(tmp_path, monkeypatch):
    from monitor.regras import gerar_alertas

    e = _estado_iniciado(tmp_path, monkeypatch)
    ult = Oferta("promobit", "post", "PlayStation Store", "GTA VI Ultimate Edition PS5", "https://p/u", "u1",
                 preco=499.90, modelo="GTA6_ULTIMATE", publicado=agora_iso())
    msgs, _ = gerar_alertas(e, [ult, _cib(pix=340.0)], [])
    (m,) = [x for x in msgs if "Ultimate" in x.split("\n")[0]]
    linha = next(l for l in m.split("\n") if l.startswith("🆚"))
    assert "Standard + upgrade" in linha and "R$ 440,00" in linha and "R$ 499,90" in linha and "R$ 59,90" in linha
    assert "Code in Box" in linha and "KaBuM!" in linha


def test_resumo_compara_as_duas_edicoes(tmp_path, monkeypatch):
    from monitor.regras import resumo_diario

    e = _estado_iniciado(tmp_path, monkeypatch)
    of = [_cib(pix=418.41), _ps("GTA6_ULTIMATE", 549.90, URL_ULT, "u")]
    r = resumo_diario(e, of, [])
    linha = next(l for l in r.split("\n") if l.startswith("🆚"))
    assert "Ultimate" in linha and "R$ 518,41" in linha and "R$ 549,90" in linha


def test_painel_mostra_as_duas_edicoes(tmp_path):
    import test_painel as tp

    if not tp.NODE:
        pytest.skip("node não encontrado no PATH")
    harness = tp.HARNESS.replace(
        "process.stdout.write(JSON.stringify(saida));",
        "saida.gta = el('secao-GTA6').innerHTML;\n  process.stdout.write(JSON.stringify(saida));")
    cat = produtos.para_painel()
    assert cat["GTA6_CODE_IN_BOX"]["edicao"] == "Standard" and cat["GTA6_ULTIMATE"]["edicao"] == "Ultimate"
    gta = tp.oferta("kabum", "KaBuM!", 449.9, 418.41, vendedor="KaBuM!", oid="1051619")
    gta.update(modelo="GTA6_CODE_IN_BOX", titulo="GTA VI")
    cloud = tp.latest("cloud", tp.CLOUD_AT, [*tp.ofertas_cloud_hoje(), gta], tp.MIN_MAGALU)
    cloud["produtos"] = cat
    # 14 linhas da Standard (mais que as 12 da tabela de antes) e as da Ultimate, mais caras: as duas aparecem
    muitas = [_cib(loja="KaBuM!", preco=400.0 + i, pix=None, oid=f"k{i}") for i in range(14)]
    cloud["gta6_custo_final"] = produtos.custo_final_gta(muitas + [_ps("GTA6_ULTIMATE", 549.90, URL_ULT, "u")])
    # o PC não lê a PS Store: a tabela dele traz a Ultimate pelo preço oficial (referência) e o Code in Box da Amazon
    pc = tp.latest("pc", tp.PC_AT, tp.ofertas_pc_hoje(), tp.MIN_AMAZON)
    pc["gta6_custo_final"] = produtos.custo_final_gta([_cib(loja="Amazon", preco=430.0, pix=None, oid="a1")])
    assert any(l["produto"] == "GTA6_ULTIMATE" and l["tipo"] == "calculo" for l in pc["gta6_custo_final"])
    dados = tmp_path / "dados.json"
    dados.write_text(json.dumps({"agora": tp.AGORA, "formatar": [], "arquivos": {
        "data/latest_cloud.json": cloud, "data/latest_pc.json": pc,
        "data/historico_cloud.csv": tp.CSV_CLOUD, "data/historico_pc.csv": tp.CSV_PC}}, ensure_ascii=False),
        encoding="utf-8")
    h = tmp_path / "h.js"
    h.write_text(harness, encoding="utf-8")
    p = subprocess.run([tp.NODE, str(h), str(tp.INDEX), str(dados)], capture_output=True, text=True, encoding="utf-8",
                       timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["erro"] is None, out["erro"]
    g = out["gta"]
    assert "Edição Standard" in g and "Edição Ultimate" in g
    assert "Standard (Code in Box) + upgrade" in g and "GTA 6 digital Ultimate" in g
    assert tp.brl(549.90) in g and tp.brl(500.0) in g          # o Code in Box de R$ 400 + upgrade de R$ 100
    assert "Ultimate mais barata" in g
    ult = g[g.index("Edição Ultimate"):]
    # a referência pelo preço oficial (do PC) não repete a Ultimate vista na PS Store (da nuvem), e de cada forma da
    # Standard + upgrade fica a mais barata (a do Code in Box de R$ 400 da nuvem, não a de R$ 430 do PC)
    assert "Ultimate (PS Store) (preço oficial)" not in ult and ult.count("GTA 6 digital Ultimate") == 1
    assert ult.count("Standard (Code in Box) + upgrade") == 2 and tp.brl(530.0) not in ult   # a nota + a linha
