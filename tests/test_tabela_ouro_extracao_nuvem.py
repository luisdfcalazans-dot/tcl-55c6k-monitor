"""Tabela de ouro do grupo extracao-nuvem (rodadas 3, 4 e 5; as linhas das rodadas 4 e 5 estão no fim do arquivo).

Uma linha por exemplo concreto do arquivo de retrabalho: evidência de cada achado original (N-F1..N-F10),
cada regressão das rodadas 1 e 2 e cada caso "tem de continuar funcionando" citado pelos verificadores.
Entrada -> saída esperada (aceita/rejeita, preço, parcelado, cupom, alerta 🎯 ou não).

Quando uma expectativa antiga e uma nova se contradizem, vale a do verificador mais recente (comentário na linha).
Linha OuRejeita(...): "sem alerta falso" em que o preço certo da 55C6K também é seguro — a postagem sai ou traz
exatamente aqueles campos; nunca o preço do outro produto, nunca um 🎯 falso.
Quando uma heurística não consegue ao mesmo tempo "não perder" e "não dar alerta falso", vale NÃO DAR ALERTA
FALSO e a linha "não perder" fica xfail com o motivo.

Os snapshots de 18/09 ficam fora do repositório; sem eles, as linhas que dependem deles são puladas.
"""

import json
import re
from pathlib import Path

import pytest

from monitor import config, regras
from monitor.filtro import eh_55c6k, linha_55c6k
from monitor.models import Oferta
from monitor.sources import kabum, magalu, telegram_public, vtex, zoom
from monitor.sources import playwright_sources as ps
from monitor.util import cupom_no_texto, parcelado_no_texto, preco_postagem, precos_no_texto

FIX = Path(__file__).parent / "fixtures"
SNAP = Path(r"C:\Users\luisd\AppData\Local\Temp\claude\C--Users-luisd-OneDrive--rea-de-Trabalho-promos"
            r"\8294b9c9-bb7f-4112-99fd-4c7e3e9f239b\scratchpad\snapshots")
PROBES = SNAP.parent / "probes"

REJEITA = None  # saída esperada de uma postagem descartada


def _snap(nome: str) -> str:
    arq = SNAP / nome
    if not arq.exists():
        pytest.skip(f"snapshot {nome} não está nesta máquina")
    return arq.read_text(encoding="utf-8", errors="replace")


def _fix(nome: str) -> str:
    return (FIX / nome).read_text(encoding="utf-8", errors="replace")


# ================================================================ títulos (eh_55c6k)

TITULOS = [
    # --- N-F1: acessórios, peças, estado do produto e anúncio de vários tamanhos (evidência do achado)
    ("N-F1 controle 5 tamanhos", "Controle comando de voz para tv tcl 55c6k 65c6k 75c6k 85c6k 98c6k", False),
    ("N-F1 barra de LED", "Barra de LED para TV TCL 55C6K", False),
    ("N-F1 placa", "Placa principal TCL 55C6K", False),
    ("N-F1 fonte", "Fonte de alimentação TV TCL 55C6K", False),
    ("N-F1 tela display painel", "Tela display painel TCL 55C6K", False),
    ("N-F1 reembalado", "Smart TV TCL 55C6K Reembalado", False),
    ("N-F1 mostruario", "Smart TV TCL 55C6K Mostruário", False),
    ("N-F1 recertificado", "Smart TV TCL 55C6K Recertificado", False),
    ("N-F1 avaria", "Smart TV TCL 55C6K com avaria na embalagem", False),
    ("N-F1 varios tamanhos", "Smart TV TCL 65C6K 55C6K 75C6K Mini LED", False),
    ("N-F1 dois tamanhos", "Smart TV TCL 55C6K 65C6K", False),
    # mesma classe do N-F1 (acessório barato aceito como a TV); "rack" não era barrado nem na main
    ("N-F1 rack", "Rack para TV TCL 55C6K", False),
    # --- rodada 1, regressão 3: TV + suporte de parede é combo
    ("R1-REG3 suporte a parede", "Smart TV TCL 55C6K com suporte à parede", False),
    ("R1-REG3 suporte articulado", "Smart TV TCL 55C6K + Suporte a Parede Articulado", False),
    # --- rodada 1, regressão 5b: títulos da própria TV com controle/display/"para TV"
    ("R1-REG5b controle por voz", 'Smart TV TCL 55" QD-Mini LED 4K 55C6K com Controle por Voz', True),
    ("R1-REG5b display 144Hz", "Smart TV TCL 55C6K QD-Mini LED Display 144Hz", True),
    ("R1-REG5b ideal para TV", 'Smart TV TCL 55" 55C6K ideal para TV e games', True),
    # --- rodada 2, regressão 4: controle remoto anunciado começando por "Smart TV"
    ("R2-REG4 controle compativel", "Smart Tv Tcl Controle Remoto Compatível 55c6k", False),
    ("R2-REG4 controle substituto", "Smart TV TCL 55C6K Controle Remoto Substituto", False),
    ("R2-REG4 controle extra", "Smart TV TCL 55C6K + Controle Remoto Extra", False),
    ("R2-REG4 controle de voz (TV)", 'Smart TV TCL 55" QD-Mini LED 4K 55C6K com Controle de Voz', True),
    # anúncio de loja que começa por "Tela" continua sendo a peça (a main aceitava; tela de reposição da 55C6K
    # existe nas buscas e viraria "menor preço"). Sem alerta falso vale mais; o verificador da rodada 2 só
    # apontou a LINHA de uma postagem começando por "Tela de 55\"", que continua aceita (R2-REG4 tela de 55)
    ("R2-REG4 tela de 55 (anuncio de loja)", 'Tela de 55" QD-Mini LED TCL 55C6K Google TV', False),
    ("R2-REG4 tela de reposicao", "Tela De 55 Polegadas Tcl 55c6k Original", False),
    # saídas do verificador da rodada 2 em que a rodada 2 se afastou da main (adv.py): a main estava certa
    ("R2-REG4 suporte 4K no inicio", "Suporte 4K para TV TCL 55C6K", False),
    ("R2-REG4 suporte USB no inicio", "Suporte USB 55C6K TCL", False),
    ("R2-REG4 + suporte USB", "TCL 55C6K Smart TV + Suporte USB", False),
    ("R2-REG4 HDR10+ suporte a Dolby (TV)", "Smart TV TCL 55C6K HDR10+ Suporte a Dolby Vision", True),
    # --- N-F6: "suporte a <recurso>" é recurso da TV
    ("N-F6 suporte a Dolby", '🔥 Smart TV TCL 55" QD-Mini LED 55C6K com suporte a Dolby Vision IQ, HDR10+ e 144Hz', True),
    # --- tem de continuar funcionando: títulos reais das lojas (snapshots de 13/09 e 18/09)
    ("real Magalu 1P", 'Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz Google TV AiPQ Google Assistente 4 HDMI 2 USB', True),
    ("real Amazon/ML/KaBuM", "Smart TV TCL 55 Polegadas QLED Mini LED 4K C6K WiFi Bluetooth Google TV 4 HDMI 144Hz HDR10+ 55C6K", True),
    ("real ML", "Smart Tv Tcl 55 Polegadas Qd-Mini Led 4k C6k Wifi Bluetooth Google Tv 4 Hdmi 144hz Hdr10+ 55c6k", True),
    ("real Fast Shop", "Smart TV 4K TCL QD-Mini LED 55” Polegadas com HDMI 2.1, Dolby Vision IQ, Subwoofer, 144Hz VRR e Wi-Fi - 55C6K", True),
    ("real Casas Bahia", "Smart TV 55” TCL 55C6K 4K QD-Mini Led 144Hz Sistema Operacional Google TV", True),
    ("real Colombo", "Smart TV TCL 55 AI, 4K UHD, QLED Mini LED, Android TV - 55C6K", True),
    ("real Magalu 3P", "Smart TV C6K 55 Polegadas 4K 144 HZ QLED Mini Led TCL", True),
    ("real Webcontinental", "Smart TV TCL C6K 55 Polegadas 4K QLED Mini LED Preto Android TV 144Hz Bivolt", True),
    ("real Loja TCL", "TCL PREMIUM 4K QD-Mini LED TV 55“ C6K GOOGLE TV, DOLBY VISION IQ, ATMOS, Subwoofer, HDR10+", True),
    ("real Zoom", 'Smart TV Mini LED 55" TCL 4K 55C6K', True),
    ("par 55/65 da postagem", "Smart TV TCL 55C6K/65C6K QD-Mini LED (loja oficial)", True),
]


@pytest.mark.parametrize("titulo,aceita", [pytest.param(t, a, id=i) for i, t, a in TITULOS])
def test_titulo(titulo, aceita):
    assert eh_55c6k(titulo) is aceita


# ================================================================ postagens do Telegram (parse_canal)

class _EstadoMemoria:
    """Estado vazio em memória (não lê nem grava docs/data), fora do bootstrap."""
    bootstrap = False

    def minimo(self):
        return None

    def oferta_anterior(self, chave):
        return None

    def cupom_anterior(self, chave):
        return None

    # métodos que o grupo estado-alertas acrescentou ao Estado (junção das rodadas): estado vazio, sem outro modo
    def lojas_diretas_conhecidas(self, ofertas=()):
        from monitor.regras import lojas_diretas
        return lojas_diretas(list(ofertas))

    def minimo_geral(self, diretas=None):
        return None

    def cupons_vistos(self, *a, **k):
        return []

    def ofertas_diretas_de_outros_modos(self, *a, **k):
        return []

    def migra_alertas_de_cupom(self, *a, **k):
        return None

    def registra_alerta_cupom(self, *a, **k):
        return None


def _canal(*linhas: str) -> str:
    return ('<div class="tgme_widget_message" data-post="canal/1"><div class="tgme_widget_message_text">'
            + "<br>".join(linhas) + '</div><time datetime="2026-09-18T10:00:00+00:00"></time></div>')


def _post(html: str, monkeypatch) -> dict | None:
    ofs = telegram_public.parse_canal(html, "canal")
    if not ofs:
        return None
    assert len(ofs) == 1, ofs
    o = ofs[0]
    monkeypatch.setattr(config, "ALVO_PIX", 2900.0)
    monkeypatch.setattr(config, "ALVO_PARCELADO", 3000.0)
    o.publicado = None  # o teste não depende do dia em que roda
    msgs, _ = regras.gerar_alertas(_EstadoMemoria(), [o], [])
    assert len(msgs) == 1 and "📣" in msgs[0]
    return {"preco": o.preco, "parcelado": o.parcelado, "cupom": o.cupom, "alvo": "🎯" in msgs[0], "titulo": o.titulo}


class OuRejeita(dict):
    """Linha "sem alerta falso" em que o preço certo da 55C6K também é seguro: a postagem sai OU traz exatamente
    estes campos (o preço da 55C6K, sem 🎯) — nunca o preço do outro produto, nunca um 🎯 falso."""


def _confere(res: dict | None, esperado: dict | None):
    if esperado is None:
        assert res is None, f"devia rejeitar, saiu {res}"
        return
    if isinstance(esperado, OuRejeita) and res is None:
        return
    assert res is not None, "postagem rejeitada"
    for k, v in esperado.items():
        assert res[k] == v, f"{k}: {res[k]!r} != {v!r} ({res})"


_MINIMOS_CUPOM = ["Cupom TV300 (mín. R$ 2.500)", "compra mínima de R$ 2.500", "em pedidos a partir de R$ 2.500",
                  "a partir de R$ 2.500 em compras", "gastando R$ 2.500", "(R$300 OFF > R$2.500)"]

POSTS = [
    # --- N-F2: valor sem ponto de milhar
    ("N-F2 3599 sem ponto", ("Smart TV TCL 55C6K", "De R$ 4.199 por R$ 3599 no Pix", "ou 10x de R$ 399,90 sem juros"),
     {"preco": 3599.0, "parcelado": "10x R$ 399,90 sem juros"}),
    # --- N-F3: mínimo do cupom nunca é o preço (e não gera 🎯)
    ("N-F3 acima de 2.499", ('🔥 Smart TV TCL 55" QD-Mini LED 55C6K', "💰 R$ 3.599,00 no Pix",
                             "🎟️ Cupom: TV300 (R$ 300 OFF acima de R$ 2.499)"),
     {"preco": 3599.0, "cupom": "TV300", "alvo": False}),
    ("N-F3 compras acima de 1.999", ("Smart TV TCL 55C6K", "R$ 3.599,00 no Pix",
                                     "Cupom TV300: R$ 300 OFF em compras acima de R$ 1.999"),
     {"preco": 3599.0, "alvo": False}),
    # N-F3 pendente da rodada 1: seis redações do mínimo, sem marcador de Pix, depois e antes do título
    *[(f"N-F3 r1 depois: {c}", ("Smart TV TCL 55C6K", "R$ 3.599", c), {"preco": 3599.0, "alvo": False})
      for c in _MINIMOS_CUPOM],
    *[(f"N-F3 r1 antes: {c}", (c, "Smart TV TCL 55C6K", "R$ 3.599"), {"preco": 3599.0, "alvo": False})
      for c in _MINIMOS_CUPOM],
    # --- N-F6: descrição da TV no corpo não derruba a postagem
    ("N-F6 canaltech 3 linhas", ('🔥 Smart TV TCL 55" QD-Mini LED 55C6K com suporte a Dolby Vision IQ, HDR10+ e 144Hz',
                                 "CUPOM + PIX", "A partir de R$ 3.349,00"), {"preco": 3349.0}),
    ("N-F6 canaltech 1 linha", ('🔥 Smart TV TCL 55" QD-Mini LED 55C6K com suporte a Dolby Vision IQ, HDR10+ e 144Hz'
                                " / CUPOM + PIX / A partir de R$ 3.349,00",), {"preco": 3349.0}),
    ("N-F6 descricao antes do titulo", ("🔥 🔥", "Suporte a HDR10+ e IMAX Enhanced, controle remoto com comando de voz, "
                                        "base de metal e pedestal.",
                                        'PARCELADO | Smart TV TCL 55" QD-Mini LED 55C6K | CUPOM + PIX',
                                        "A partir de R$ 3.349,00"), {"preco": 3349.0}),
    # --- N-F10: "CUPOM DISPONÍVEL" não é código
    ("N-F10 cupom disponivel", ("Smart TV TCL 55C6K Mini LED", "R$ 3.599,09 no Pix", "CUPOM DISPONÍVEL NA PÁGINA"),
     {"preco": 3599.09, "cupom": None}),
    # --- rodada 1, regressão 1: postagem com vários produtos nunca usa o preço do outro (nem dá 🎯 falso).
    # A orientação da rodada 3 aceita rejeitar a postagem inteira; aqui a linha do outro produto tem o
    # próprio preço, então só esse valor sai e o da 55C6K fica.
    ("R1-REG1 43S5K na linha de baixo", ('Smart TV TCL 55" 55C6K: R$ 3.599', 'Smart TV TCL 43" 43S5K: R$ 1.799'),
     {"preco": 3599.0, "alvo": False}),
    ("R1-REG1 65P7K no Pix", ('55" 55C6K — R$ 3.599 no Pix', '65" 65P7K — R$ 2.799 no Pix'),
     {"preco": 3599.0, "alvo": False}),
    # controle da rodada 2 (não perder): a própria 55C6K abaixo do alvo continua com 🎯
    ("R2 controle 55C6K a 2.799", ('Smart TV TCL 55" 55C6K: R$ 2.799 no Pix', 'Smart TV TCL 43" 43S5K: R$ 1.799'),
     {"preco": 2799.0, "alvo": True}),
    # rodada 2 esperava 3599 nestas; a rodada 3 rejeitava a postagem. Rodada 4 (segmentação por produto): cada
    # linha de preço é do cabeçalho de produto mais próximo acima dela, então sai 3599 — ou a postagem é
    # rejeitada; nunca o preço (nem o cupom) do outro produto, nunca 🎯 falso
    ("R2 outra TV acima da 55C6K", ('Smart TV TCL 43" 43S5K', "R$ 1.799 no Pix", 'Smart TV TCL 55" 55C6K',
                                    "R$ 3.599 no Pix"), OuRejeita(preco=3599.0, alvo=False)),
    ("R2 Samsung sem codigo", ("Smart TV TCL 55C6K", "R$ 3.599", "Smart TV Samsung Crystal UHD", "R$ 2.299 no Pix"),
     OuRejeita(preco=3599.0, alvo=False)),
    ("R2 43S5K com cupom proprio", ("Smart TV TCL 55C6K", "R$ 3.599", "Smart TV TCL 43S5K",
                                    "R$ 1.799 ou 10x de R$ 179,90 sem juros", "Cupom TCL43"),
     OuRejeita(preco=3599.0, alvo=False, cupom=None, parcelado=None)),
    ("R2 50 P7L sem aspas", ("Smart TV TCL 55C6K: R$ 3.599", "Smart TV TCL 50 P7L: R$ 2.069 no Pix"),
     {"preco": 3599.0, "alvo": False}),
    ("R2 mesma linha com |", ('Smart TV TCL 55" 55C6K: R$ 3.599 | Smart TV Samsung 43" Crystal: R$ 1.799 no Pix',),
     {"preco": 3599.0, "alvo": False}),
    # --- rodada 1, regressão 4: "por" depois do valor não é De/Por
    ("R1-REG4 por tempo limitado", ("Smart TV TCL 55C6K", "R$ 3.599 por tempo limitado", "ou 10x de R$ 399,90 sem juros"),
     {"preco": 3599.0, "parcelado": "10x R$ 399,90 sem juros"}),
    # --- rodada 1, regressão 5a: tamanho 3 linhas acima do "C6K"
    ("R1-REG5a 55 na linha 1", ('Smart TV TCL 55"', "QD-Mini LED 4K", "Google TV 144Hz", "Modelo C6K", "R$ 3.599 no Pix"),
     {"preco": 3599.0}),
    ("R2 55 em qualquer linha", ("Smart TV TCL", "Modelo C6K", "QD-Mini LED", "4K", "144Hz", "Google TV", 'Tela de 55"',
                                 "R$ 3.599"), {"preco": 3599.0}),
    # --- rodada 2, regressão 1: palavra de estado em qualquer linha rejeita (como a main)
    ("R2-REG1 usada", ('Smart TV TCL 55" 55C6K', "Usada, 3 meses de uso, com nota", "R$ 2.200"), REJEITA),
    ("R2-REG1 vitrine", ('Smart TV TCL 55" 55C6K', "Produto de vitrine, sem caixa", "R$ 2.500"), REJEITA),
    ("R2-REG1 seminova", ('Smart TV TCL 55" 55C6K', "Seminova, 3 meses de uso", "R$ 2.500"), REJEITA),
    ("R2-REG1 defeito", ('Smart TV TCL 55" 55C6K', "Com pequeno defeito na tela", "R$ 1.800"), REJEITA),
    ("R2-REG1 estado usado", ('Smart TV TCL 55" 55C6K', "Estado: usado", "R$ 2.200"), REJEITA),
    ("R2-REG1 recondicionado", ('Smart TV TCL 55" 55C6K', "Recondicionado pela loja", "R$ 2.500"), REJEITA),
    ("R2-REG1 open box", ('Smart TV TCL 55" 55C6K', "Open box, caixa aberta", "R$ 2.600"), REJEITA),
    ("R2-REG1 kit suporte", ('Smart TV TCL 55" 55C6K', "Kit com suporte de parede", "R$ 3.799"), REJEITA),
    ("R2-REG1 acompanha suporte", ('Smart TV TCL 55" 55C6K', "Acompanha suporte de parede", "R$ 3.799"), REJEITA),
    ("R2-REG1 combo soundbar", ('Smart TV TCL 55" 55C6K', "Combo com soundbar", "R$ 4.299 no Pix"), REJEITA),
    # --- rodada 2, regressão 2: preço com cupom / seta vence; o De nunca
    ("R2-REG2 com o cupom", ("Smart TV TCL 55C6K", "R$ 3.199", "Com o cupom TCL300: R$ 2.899"),
     {"preco": 2899.0, "cupom": "TCL300", "alvo": True}),
    ("R2-REG2 com cupom linha propria", ("Smart TV TCL 55C6K", "💰 R$ 3.199", "🎟️ Cupom TCL300", "✅ Com cupom: R$ 2.899"),
     {"preco": 2899.0, "alvo": True}),
    ("R2-REG2 sem cupom / com cupom", ("Smart TV TCL 55C6K", "R$ 3.199 (sem cupom)", "R$ 2.899 com cupom"),
     {"preco": 2899.0, "alvo": True}),
    ("R2-REG2 seta emoji", ("Smart TV TCL 55C6K", "R$ 4.199 ➡️ R$ 3.599"), {"preco": 3599.0}),
    ("R2-REG2 seta", ("Smart TV TCL 55C6K", "💸 R$ 4.199 → R$ 3.599"), {"preco": 3599.0}),
    ("R2-REG2 preco antes do titulo", ("R$ 3.599", "Smart TV TCL 55C6K", "R$ 3.999 em até 10x"), {"preco": 3599.0}),
    ("R2-REG2 pix antes do titulo", ("🔥 R$ 3.599 no Pix", "Smart TV TCL 55C6K", "R$ 3.999 em até 10x"), {"preco": 3599.0}),
    ("R2 De/Por/Pix", ("Smart TV TCL 55C6K", "De R$ 4.199", "Por R$ 3.799", "R$ 3.599 no Pix"), {"preco": 3599.0}),
    # --- rodada 2, regressão 3: linhas comuns de uma postagem de um produto não são "outro produto"
    ("R2-REG3 celular", ("Smart TV TCL 55C6K", "Oferta válida no app pelo celular", "R$ 3.599"), {"preco": 3599.0}),
    ("R2-REG3 LG e Samsung", ("Smart TV TCL 55C6K", "Melhor que muita TV da LG e Samsung", "R$ 3.599"), {"preco": 3599.0}),
    ("R2-REG3 monitor", ("Smart TV TCL 55C6K", "Serve até como monitor gamer 144Hz", "R$ 3.599"), {"preco": 3599.0}),
    ("R2-REG3 link curto", ("Smart TV TCL 55C6K", "https://tidd.ly/45ab3cd", "R$ 3.599 no Pix"), {"preco": 3599.0}),
    ("R2-REG3 tambem disponivel na", ("Smart TV TCL 55C6K", "Também disponível na Amazon", "R$ 3.599"), {"preco": 3599.0}),
    ("R2-REG3 TV que bate LG", ("Smart TV TCL 55C6K", "TV com imagem que bate LG e Samsung", "R$ 3.599"),
     {"preco": 3599.0}),
    # outro tamanho numa linha SEM preço: o preço das linhas de baixo pode ser dele (43" é mais barata). Rodada 4:
    # a linha de disponibilidade encerra o bloco da 55C6K e os preços de cima ficam (3599) — ou rejeita
    ("R2-REG3 outro tamanho sem preco (sem alerta falso)", ("Smart TV TCL 55C6K", "R$ 3.599", "Também tem a de 43 polegadas",
                                                            "R$ 1.999"), OuRejeita(preco=3599.0, alvo=False)),
    # linha de disponibilidade COM o próprio preço: só ela sai do bloco (o 3599 de baixo é da 55C6K)
    ("R2-REG3 tambem em 65", ('Smart TV TCL 55" 55C6K', 'Também disponível em 65" por R$ 4.999', "R$ 3.599"),
     {"preco": 3599.0}),
    ("R2-REG3 par 65 primeiro", ("TCL 55C6K e 65C6K em promoção", '65": R$ 4.999', '55": R$ 3.599'), {"preco": 3599.0}),
    ("R2-REG3 par 55 primeiro", ("TCL 55C6K e 65C6K em promoção", '55": R$ 3.599', '65": R$ 4.999'), {"preco": 3599.0}),
    # --- rodada 2, regressão 4 (outra direção): linha do C6K que começa por Tela/Display
    ("R2-REG4 tela de 55", ("🔥 Smart TV TCL QD-Mini LED", '📺 Tela de 55" (modelo 55C6K)', "💰 R$ 3.599 no Pix"),
     {"preco": 3599.0}),
    ("R2-REG4 display de 55", ("Smart TV TCL QD-Mini LED 4K", 'Display de 55" 144Hz - 55C6K', "R$ 3.599 no Pix"),
     {"preco": 3599.0}),
    # sem o título da TV na linha de cima, "Tela de 55\" ... 55C6K" é a tela de reposição (sem alerta falso)
    ("R2-REG4 tela de reposicao no post", ('📺 Tela de 55" (modelo 55C6K)', "R$ 1.499"), REJEITA),
    ("R2-REG4 tela de reposicao apos cupom", ("Use o cupom TELA10", '📺 Tela de 55" (modelo 55C6K)', "R$ 1.499"),
     REJEITA),
    # --- tem de continuar funcionando (rodada 2)
    ("R2 riscado", ("Smart TV TCL 55C6K", "<s>R$ 4.199</s> R$ 3.599"), {"preco": 3599.0}),
    ("R2 cupom antes do titulo", ("Use o cupom SOLTAODESCONTO", "Smart TV TCL 55C6K | CUPOM + PIX", "A partir de R$ 3.349,00"),
     {"preco": 3349.0, "cupom": "SOLTAODESCONTO"}),
    ("R2 parcela sem rotulo primeiro", ("Smart TV TCL 55C6K", "R$ 3.599 no Pix", "10x de R$ 399,90",
                                        "ou 12x de R$ 333,25 sem juros"), {"preco": 3599.0, "parcelado": None}),
    ("R2 parcela antes do pix", ("Smart TV TCL 55C6K", "10x de R$ 399,90 sem juros", "ou R$ 3.599 no Pix"),
     {"preco": 3599.0, "parcelado": "10x R$ 399,90 sem juros"}),
    ("R2 C6K 55 polegadas", ("Smart TV TCL C6K 55 polegadas", "R$ 3.599 no Pix"), {"preco": 3599.0}),
    ("R2 controle de voz na linha", ("Controle comando de voz para TV TCL 55C6K", "R$ 149,99"), REJEITA),
    ("R2 reembalada no corpo", ("Smart TV TCL 55C6K", "TV reembalada, R$ 2.999"), REJEITA),
    ("R2 65C6K", ("Smart TV TCL 65C6K", "R$ 4.999"), REJEITA),
]


@pytest.mark.parametrize("linhas,esperado", [pytest.param(l, e, id=i) for i, l, e in POSTS])
def test_postagem(linhas, esperado, monkeypatch):
    _confere(_post(_canal(*linhas), monkeypatch), esperado)


def test_postagem_nao_perder_outros_tamanhos_sem_preco(monkeypatch):
    """xfail da rodada 3 (estrito), resolvido na rodada 4: a linha de disponibilidade sem preço encerra o bloco da
    55C6K, mas os preços acima dela ficam."""
    linhas = ("Smart TV TCL 55C6K", "R$ 3.599", "Disponível também em 65 e 75 polegadas")
    _confere(_post(_canal(*linhas), monkeypatch), {"preco": 3599.0})


def _kabum_descricao() -> list[str]:
    a = json.loads(_fix("kabum_api.json"))["attributes"]
    texto = re.sub(r"<br\s*/?>|</p>|</li>", "\n", a.get("description") or "", flags=re.I)
    texto = re.sub(r"<[^>]+>", " ", texto)
    return [l.strip() for l in texto.splitlines() if l.strip()]


def test_nf6_descricao_real_da_kabum_no_corpo(monkeypatch):
    """N-F6: título + descrição real da 55C6K (kabum_api.json: 'Suporte a HDR10+', 'controle remoto', 'base',
    'pedestal de plástico', 'Suporte de Parede:') + preço. A main descartava por 'negativo: suporte'."""
    linhas = ['🔥 Smart TV TCL 55" QD-Mini LED 55C6K', *_kabum_descricao(), "R$ 3.599 no Pix"]
    assert len(linhas) > 20
    _confere(_post(_canal(*linhas), monkeypatch), {"preco": 3599.0})


def _post_real_11614(extra: str | None = None) -> str:
    arq = PROBES / "tg_achadosdotb.out"
    if not arq.exists():
        pytest.skip("dump real do achadosdotb não está nesta máquina")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(arq.read_text(encoding="utf-8", errors="replace"), "html.parser")
    el = soup.select_one('.tgme_widget_message[data-post="achadosdotb/11614"] .tgme_widget_message_text')
    html = str(el)
    if extra:  # linha nova logo depois do título, como fez o verificador
        partes = re.split(r"(<br\s*/?>)", html)
        i = next(k for k, p in enumerate(partes) if re.match(r"<br", p))
        html = "".join(partes[:i]) + "<br/>" + extra + "".join(partes[i:])
    return ('<div class="tgme_widget_message" data-post="achadosdotb/11614">' + html
            + '<time datetime="2026-09-18T10:00:00+00:00"></time></div>')


@pytest.mark.parametrize("extra,esperado", [
    pytest.param(None, {"preco": 2910.14, "cupom": "TECNOBLOG250", "alvo": False}, id="real 11614"),
    pytest.param("📦 Usado - Como novo (Amazon)", REJEITA, id="R2-REG1 real 11614 + usado"),
    pytest.param("⚠️ Produto de vitrine", REJEITA, id="R2-REG1 real 11614 + vitrine"),
    pytest.param("⚠️ Com pequeno defeito na moldura", REJEITA, id="R2-REG1 real 11614 + defeito"),
])
def test_postagem_real_achadosdotb(extra, esperado, monkeypatch):
    _confere(_post(_post_real_11614(extra), monkeypatch), esperado)


@pytest.mark.parametrize("texto", [
    pytest.param('Smart TV Samsung 55" Crystal R$ 2.299\nTCL C6K Mini LED\nR$ 3.599', id="R2 55 da Samsung"),
    pytest.param("Smart TV TCL C6K\nR$ 55,00 de desconto\nR$ 3.599", id="R2 R$ 55 nao e tamanho"),
])
def test_titulo_sem_55_de_outro_produto(texto):
    assert linha_55c6k(texto) is None


# ================================================================ util: preço, parcelado, cupom

UTIL = [
    # N-F2
    ("N-F2 3599,00", precos_no_texto, "R$ 3599,00", [3599.0]),
    ("N-F2 3599", precos_no_texto, "R$ 3599", [3599.0]),
    ("N-F2 12345,67", precos_no_texto, "R$ 12345,67", [12345.67]),
    ("N-F2 3.599,00", precos_no_texto, "R$ 3.599,00", [3599.0]),
    ("N-F2 parcela sem ponto", parcelado_no_texto, "10x de R$ 1234,56 sem juros", "10x R$ 1234,56 sem juros"),
    # R1-REG2: a 1ª parcela é com juros; nunca pula para a do patrocinado
    ("R1-REG2 com juros e patrocinado", parcelado_no_texto,
     "R$ 3.998,99 em até 11x de R$ 399,83 com juros (1.62% a.m) no cartão de crédito.\n"
     "Produtos Patrocinados\nSmart TV TCL QLED 50 Polegadas 4K HDR10 HDMI Wi-Fi 50P7K\n"
     "por R$ 3.416,60 ou em até 6x de R$ 569,43 sem juros ou", None),
    ("R2 parcela sem rotulo", parcelado_no_texto, "10x de R$ 399,90 ou 12x de R$ 350,00 sem juros", None),
    ("R2 1x", parcelado_no_texto, "1x de R$ 3.599,09 sem juros", None),
    ("R2 sem juros explicito", parcelado_no_texto, "ou 10x de R$ 399,90 sem juros", "10x R$ 399,90 sem juros"),
    ("R2 sem juros de", parcelado_no_texto, "10x sem juros de R$ 399,90", "10x R$ 399,90 sem juros"),
    ("R2 s/ juros", parcelado_no_texto, "10x R$ 399,90 (s/ juros)", "10x R$ 399,90 sem juros"),
    ("parcela 15x", parcelado_no_texto, "Por R$2.760,00 em até 15x de R$ 184,00 sem juros", "15x R$ 184,00 sem juros"),
    # N-F10
    ("N-F10 disponivel", cupom_no_texto, "CUPOM DISPONÍVEL NA PÁGINA", None),
    ("N-F10 ativado", cupom_no_texto, "CUPOM ATIVADO NO LINK", None),
    ("N-F10 mercado", cupom_no_texto, "CUPOM MERCADO PAGO", None),
    ("N-F10 primeira", cupom_no_texto, "CUPOM PRIMEIRA COMPRA", None),
    ("N-F10 minusculo", cupom_no_texto, "cupom disponível no app", None),
    ("N-F10 codigo real", cupom_no_texto, "Use o cupom SOLTAODESCONTO na finalização", "SOLTAODESCONTO"),
    ("N-F10 codigo com OFF", cupom_no_texto, "Cupom: TV300 (R$ 300 OFF)", "TV300"),
    ("N-F10 tecnoblog", cupom_no_texto, "cupom TECNOBLOG250 somado ao Pix", "TECNOBLOG250"),
    # preço de postagem (R1-REG4, R2-REG2 e os casos de N-F3)
    ("R1-REG4 por tempo limitado", preco_postagem, "R$ 3.599 por tempo limitado", 3599.0),
    ("R1-REG4 De/por", preco_postagem, "R$ 4.199 por R$ 3.599", 3599.0),
    ("R1-REG4 De por no Pix", preco_postagem, "De R$ 4.199 por R$ 3.599 no Pix", 3599.0),
    ("R1-REG4 caiu de", preco_postagem, "Caiu de R$ 4.199 para R$ 3.599", 3599.0),
    ("R2-REG2 seta", preco_postagem, "R$ 4.199 → R$ 3.599", 3599.0),
    ("R2-REG2 cupom", preco_postagem, "R$ 3.199\nCom o cupom TCL300: R$ 2.899", 2899.0),
    ("N-F3 a partir de (Canaltech)", preco_postagem, "A partir de R$1.049,00", 1049.0),
    ("N-F3 cartao ou pix", preco_postagem, "R$ 3.599 no cartão ou R$ 3.419 no Pix", 3419.0),
    ("N-F3 parcela acima de mil", preco_postagem, "R$ 3.599,00 à vista ou 10x de R$ 1.059,90", 3599.0),
    ("N-F3 economize", preco_postagem, "Economize R$ 1.200! Sai por R$ 3.299", 3299.0),
    ("N-F3 economia de", preco_postagem, "R$ 3.299 no Pix (economia de R$ 1.200)", 3299.0),
    ("N-F3 mais barato", preco_postagem, "R$ 3.299 no Pix, R$ 1.100 mais barato que em agosto", 3299.0),
    ("N-F3 cashback", preco_postagem, "R$ 3.599 no Pix + cashback R$ 1.000", 3599.0),
    ("N-F3 pedido minimo", preco_postagem, "Preço: R$ 3.599 | Pedido mínimo R$ 2.000", 3599.0),
    ("N-F3 valor minimo", preco_postagem, "R$ 3.599 | Valor mínimo: R$ 2.000", 3599.0),
    ("N-F3 De: Por:", preco_postagem, "De: R$ 4.199,00\nPor: R$ 3.599,00", 3599.0),
]


@pytest.mark.parametrize("func,entrada,esperado", [pytest.param(f, e, s, id=i) for i, f, e, s in UTIL])
def test_util(func, entrada, esperado):
    assert func(entrada) == esperado


def test_r1_reg2_parcelado_snapshot_casas_bahia():
    """R1-REG2: o texto inteiro da página da Casas Bahia não pode dar o '6x R$ 569,43 sem juros' do patrocinado."""
    assert parcelado_no_texto(_snap("casasbahia_produto.txt")) is None


# ================================================================ fontes (snapshots e fixtures)

def _magalu_busca(prod: dict) -> str:
    nd = {"props": {"pageProps": {"data": {"search": {"products": [prod]}}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script>'


def test_nf1_controle_magalu_sintetico():
    """N-F1: o controle de R$ 149,99 da busca do Magalu sem os tokens p8k não vira oferta de loja."""
    prod = {
        "id": "fa14gj5k07", "available": True,
        "title": "Controle comando de voz para tv tcl 55c6k 65c6k 75c6k 85c6k 98c6k 55c6k 65c6k 75c6k 85c6k 98c6k",
        "path": "/magazinecanaltechbr/controle-comando-de-voz-para-tv-tcl-55c6k/p/fa14gj5k07/et/cttv/",
        "price": {"bestPrice": "149.99", "fullPrice": "149.99", "price": "199.99"},
        "installment": {"amount": "75.00", "interest": "0.00", "quantity": 2},
        "seller": {"id": "lfacomercial", "description": "Lfa.Comercial", "category": "3p"},
    }
    assert magalu.parse_busca(_magalu_busca(prod)) == []


def test_nf1_controle_magalu_snapshot():
    """N-F1: magalu_busca.html de 18/09 com ' 55p8k 65p8k' tirado do título do controle (simulação do achado)."""
    html = _snap("magalu_busca.html").replace(" 55p8k 65p8k", "")
    ofs = magalu.parse_busca(html)
    assert ofs and all(o.preco >= 3000 for o in ofs), [(o.titulo[:40], o.preco) for o in ofs]
    assert not any("controle" in o.titulo.lower() for o in ofs)
    # as 4 ofertas reais da 55C6K continuam
    assert {o.id for o in ofs} == {"240162800-magazineluiza", "kc7h6f4k4b-lojascolombooficial",
                                   "eecab9199g-leonfer", "kkfe3d8a79-lojawebcontinentalmarketplace"}


@pytest.mark.xfail(reason="N-F1, 2ª parte: Estado.atualiza_minimo (monitor/estado.py) é do grupo estado-alertas, "
                          "fora dos arquivos deste grupo", strict=False)
def test_nf1_minimo_ignora_oferta_descartada(tmp_path, monkeypatch):
    from monitor.estado import Estado
    monkeypatch.setattr(config, "DIR_DADOS", tmp_path)
    e = Estado("teste")
    e.dados["minimo"] = {"preco": 2991.6, "loja": "x", "quando": "", "url": "", "titulo": ""}
    o = Oferta(fonte="magalu", tipo="loja", loja="Magazine Luiza", titulo="Controle comando de voz ...", url="u",
               id="c", preco=149.99, ativo=False)
    e.atualiza_minimo(o)
    assert e.minimo()["preco"] == 2991.6


def _vtex(price: float, installments: list) -> list:
    of = {"Price": price, "ListPrice": 4359.0, "AvailableQuantity": 1, "Teasers": [], "DiscountHighLight": [],
          "Installments": installments}
    return [{"productId": "114589", "link": "https://site.fastshop.com.br/x/p",
             "productName": "Smart TV 4K TCL QD-Mini LED 55” Polegadas com HDMI 2.1, Dolby Vision IQ, "
                            "Subwoofer, 144Hz VRR e Wi-Fi - 55C6K",
             "items": [{"sellers": [{"sellerId": "1", "sellerName": "Fast Shop", "commertialOffer": of}]}]}]


def test_nf4_fixture_fast_shop():
    ofs = vtex.parse_catalogo(json.loads(_fix("fastshop_vtex.json")), "Fast Shop", "https://site.fastshop.com.br")
    fs = [o for o in ofs if o.vendedor == "Fast Shop"]
    assert fs and (fs[0].preco, fs[0].preco_pix, fs[0].melhor_preco) == (3296.81, 3099.0, 3099.0)


def test_nf4_snapshot_fast_shop():
    """vtex_fastshop.json de 18/09 (esgotado; AvailableQuantity=1 simulado como no achado): 3350 no cartão, 3149 no Pix."""
    d = json.loads(_snap("vtex_fastshop.json"))
    for p in d:
        for it in p.get("items") or []:
            for s in it.get("sellers") or []:
                s["commertialOffer"]["AvailableQuantity"] = 1
    [o] = [o for o in vtex.parse_catalogo(d, "Fast Shop", "https://site.fastshop.com.br") if o.vendedor == "Fast Shop"]
    assert (o.preco, o.preco_pix, o.melhor_preco) == (3350.0, 3149.0, 3149.0)


def test_nf4_sintetico_pix_nas_parcelas():
    inst = [{"PaymentSystemName": "Visa", "NumberOfInstallments": 12, "Value": 306.93, "InterestRate": 1.49},
            {"PaymentSystemName": "Pix", "NumberOfInstallments": 1, "Value": 3149.0, "InterestRate": 0.0}]
    [o] = vtex.parse_catalogo(_vtex(3350.0, inst), "Fast Shop", "https://site.fastshop.com.br")
    assert (o.preco, o.preco_pix, o.parcelado) == (3350.0, 3149.0, None)


def test_nf5_zoom_snapshot_agregador():
    ofs = {o.id: o for o in zoom.parse_produto(_snap("zoom_produto.html"))}
    assert ofs and all(o.extra.get("agregador") is True for o in ofs.values())
    assert ofs["1489104908"].loja == "Amazon" and ofs["1489104908"].preco == 3279.0


def test_nf5_zoom_fixture_agregador():
    ofs = zoom.parse_produto(_fix("zoom_produto.html"))
    assert len(ofs) == 6 and all(o.extra.get("agregador") is True for o in ofs)


def test_nf7_zoom_snapshot_cartao_pix_parcelas():
    """N-F7: Zoom, oferta Magazine Luiza/Colombo: cartão 4101,20, Pix 3937,15, 10x 410,12 (bate com o Magalu)."""
    o = {o.id: o for o in zoom.parse_produto(_snap("zoom_produto.html"))}["1561988278"]
    assert (o.preco, o.preco_pix, o.parcelado) == (4101.2, 3937.15, "10x R$ 410,12 sem juros")


def test_nf7_zoom_fixture_magalu():
    o = {o.id: o for o in zoom.parse_produto(_fix("zoom_produto.html"))}["1484766165"]
    assert (o.preco, o.preco_pix, o.parcelado) == (3899.0, 3704.05, "10x R$ 389,90 sem juros")


def test_nf8_kabum_snapshot_vendedor():
    o = kabum.parse_api(json.loads(_snap("kabum_api.json")))
    assert o and o.vendedor == "LOJAS COLOMBO" and o.preco == 4184.88


def test_nf8_kabum_fixture_vendedor():
    o = kabum.parse_api(json.loads(_fix("kabum_api.json")))
    assert o and o.vendedor == "FAST SHOP"


def test_casas_bahia_snapshot(monkeypatch):
    """Helpers compartilhados (precos_no_texto, parcelado_no_texto, eh_55c6k) sem desvio na Casas Bahia real."""
    html, texto = _snap("casasbahia_produto.html"), _snap("casasbahia_produto.txt")
    monkeypatch.setattr(ps, "_abrir", lambda *a, **k: (html, texto, []))
    [o], cupons = ps.CasasBahia().coletar()
    assert (o.preco, o.preco_pix, o.parcelado) == (3998.99, 3599.09, "10x R$ 399,90 sem juros (cartão Casas Bahia)")
    assert o.ativo is True and cupons == []


def test_mercado_livre_snapshot(monkeypatch, tmp_path):
    """Helpers compartilhados sem desvio no Mercado Livre real: a opção selecionada é 3.599 / Pix 3.491,03."""
    html, texto = _snap("mercadolivre_produto.html"), _snap("mercadolivre_produto.txt")
    monkeypatch.setattr(ps, "MARCA_BLOQUEIO_ML", tmp_path / "ml_bloqueado_em")
    monkeypatch.setattr(ps, "_abrir", lambda *a, **k: (html, texto, []))
    ofertas, _ = ps.MercadoLivre().coletar()
    sel = ps._ml_oferta_selecionada(html).get("item_id")
    [o] = [o for o in ofertas if o.id == sel]
    assert (o.preco, o.preco_pix) == (3599.0, 3491.03)



# ================================================================ rodada 4
# Uma linha por exemplo concreto de regressoes_rodada3 e nao_resolvidos_rodada3 (entradas exatas; "\n" do
# verificador vira uma linha da postagem), mais casos do verificador da rodada 3 (v4n/casos*.json) em que a saída
# mudou. Regras de princípio: segmentação por produto (filtro.bloco_55c6k), classificação dos valores
# (util.valores_postagem) e código de cupom (util.cupom_no_texto).

TITULOS_R4 = [
    # N-F1 (não resolvido na rodada 3): peças e acessórios aceitos como a TV
    ("N-F1 r3 retirada de pecas", "Tv Tcl 55c6k Para Retirada De Peças", False),
    ("N-F1 r3 pe", "Pé Para TV TCL 55C6K Original", False),
    ("N-F1 r3 pes par", "Pés Tv Tcl 55c6k Par Original", False),
    ("N-F1 r3 pezinho", "Pezinho Tv Tcl 55c6k", False),
    ("N-F1 r3 alto falante", "Alto Falante Tv Tcl 55c6k Original", False),
    ("N-F1 r3 sucata", "Tv Tcl 55c6k Sucata", False),
    # mesma classe (verificador da rodada 3, v4n/casos4)
    ("N-F1 r3 pecas sem acento", "Tv Tcl 55c6k Retirada De Pecas", False),
    ("N-F1 r3 cabo flat", "Cabo Flat Lvds Tv Tcl 55c6k", False),
    ("N-F1 r3 placa t-con", "Placa T-con Tcl 55c6k", False),
    ("N-F1 r3 kit parafusos pe", "Kit Parafusos Pé Tv Tcl 55c6k", False),
    ("N-F1 r3 parafusos base", "Parafusos Base Tv Tcl 55c6k", False),
    ("N-F1 r3 backlight", "Backlight Tv Tcl 55c6k", False),
    ("N-F1 r3 barra led sem de", "Barra Led Tv Tcl 55c6k", False),
    ("N-F1 r3 painel avulso", "Tcl 55c6k Painel Avulso", False),
    ("N-F1 r3 par de pes", "Tcl 55c6k Par De Pés", False),
    # TV com recurso no meio do título (a peça é o 1º substantivo; depois da vírgula é lista de recursos)
    ("R4 sensor de luz (TV)", "TCL 55C6K 4K 144Hz, sensor de luz ambiente, Google TV", True),
    ("R4 com alto-falantes (TV)", "Smart TV TCL 55C6K com alto-falantes Onkyo 2.1", True),
    ("R4 controle por voz na lista (TV)", "🔥 Controle por voz, 144Hz e Mini LED: TCL 55C6K", True),
    ("R4 controle por voz para TV (peça)", "Controle por voz para TV TCL 55C6K", False),
    ("R4 controle de voz com (TV)", 'Smart TV TCL 55" QD-Mini LED 4K 55C6K com Controle de Voz', True),
]


@pytest.mark.parametrize("titulo,aceita", [pytest.param(t, a, id=i) for i, t, a in TITULOS_R4])
def test_titulo_r4(titulo, aceita):
    assert eh_55c6k(titulo) is aceita


def test_nf1_r3_peca_na_faixa_do_sanear_nao_vira_oferta():
    """N-F1: TV 'para retirada de peças' a R$ 2.300 (dentro da faixa do sanear) não entra como oferta de loja."""
    prod = {"id": "x1", "available": True, "title": "Tv Tcl 55c6k Para Retirada De Peças", "path": "/x/p/x1/",
            "price": {"bestPrice": "2300.00", "fullPrice": "2300.00", "price": "2300.00"},
            "seller": {"id": "v", "description": "Vendedor", "category": "3p"}}
    assert magalu.parse_busca(_magalu_busca(prod)) == []


_R3_MULTI = OuRejeita(preco=3599.0, alvo=False)  # nunca o preço do outro produto, nunca 🎯 falso

POSTS_R4 = [
    # --- regressão 1 da rodada 3 (e R1-REG1 não resolvido): o preço da outra TV numa peça "|" ou na linha de baixo
    ("R3-REG1 a 43S5K com | e Pix", ('Smart TV TCL 55" 55C6K: R$ 3.799 | R$ 3.599 no Pix',
                                    'Smart TV TCL 43" 43S5K: R$ 1.999 | R$ 1.799 no Pix'), _R3_MULTI),
    ("R3-REG1 b lista numerada", ("1️⃣ Smart TV TCL 55C6K — R$ 3.599 (Pix)",
                                  "2️⃣ Smart TV TCL 65C6K — R$ 4.999 | R$ 4.799 no Pix",
                                  "3️⃣ Smart TV TCL 50P7K — R$ 2.299 | R$ 2.199 no Pix"), _R3_MULTI),
    ("R3-REG1 c 43S5K primeiro, Pix embaixo", ("🔥 TVs TCL em oferta na Amazon", "📺 TCL 43S5K — R$ 1.999",
                                              "💸 Pix: R$ 1.799", "📺 TCL 55C6K — R$ 3.799", "💸 Pix: R$ 3.599"),
     _R3_MULTI),
    ("R3-REG1 d De/Por em 2 linhas", ('📺 Smart TV TCL 43" 43S5K — De R$ 2.199', "💰 Por R$ 1.799 no Pix",
                                      '📺 Smart TV TCL 55" 55C6K — De R$ 4.199', "💰 Por R$ 3.599 no Pix"), _R3_MULTI),
    ("R3-REG1 e 50P7K De | Por", ("🔥 TCL 55C6K", "De R$ 4.199 | Por R$ 3.599 no Pix",
                                  "🔥 TCL 50P7K: De R$ 2.799 | Por R$ 2.199 no Pix"), _R3_MULTI),
    ("R3-REG1 f 65P7K com ou no Pix", ("🔥 TCL 55C6K por R$ 3.599 no Pix", "🔥 TCL 65P7K por R$ 2.999",
                                       "ou R$ 2.849 no Pix"), _R3_MULTI),
    ("R3-REG1 g 50P7K Pix embaixo", ("📺 TCL 55C6K — R$ 3.799", "💸 Pix: R$ 3.599", "📺 TCL 50P7K — R$ 2.399",
                                     "💸 Pix: R$ 2.199"), _R3_MULTI),
    # controle: com a segmentação, os casos acima dão o preço da 55C6K (a main rejeitava todos)
    ("R3-REG1 controle bullets", ("🔥 TVs TCL em oferta na Amazon", "• 55C6K: R$ 3.599", "• 65C6K: R$ 4.799",
                                  "• 43S5K: R$ 1.799"), {"preco": 3599.0, "alvo": False}),
    ("R3-REG1 controle 43S5K parcela embaixo", ('Smart TV TCL 55" 55C6K R$ 3.599 no Pix',
                                                'Smart TV TCL 43" 43S5K R$ 1.999', "💳 ou R$ 1.899 no Pix"),
     {"preco": 3599.0, "alvo": False}),
    ("R3-REG1 controle Samsung com •", ("Smart TV TCL 55C6K • R$ 3.599",
                                        'Smart TV Samsung 50" Crystal UHD: R$ 2.199 • Pix R$ 2.089'),
     {"preco": 3599.0, "alvo": False}),
    ("R3-REG1 controle vrl 2a linha Pix", ('Smart Tv 55" TCL 55C6K QD-Mini LED | R$ 3.487,50 no Pix',
                                           'Smart Tv 43" TCL 43S5K: R$ 1.999,00 | R$ 1.799,00 no Pix'),
     {"preco": 3487.5, "alvo": False}),
    ("R3-REG1 controle a 55C6K abaixo do alvo", ("📺 TCL 43S5K — R$ 1.999", "💸 Pix: R$ 1.799",
                                                 "📺 TCL 55C6K — R$ 3.099", "💸 Pix: R$ 2.799"),
     {"preco": 2799.0, "alvo": True}),
    # outro produto DEPOIS do título, sem linha de preço da 55C6K: o preço que vem é do outro produto
    ("R4 outro produto sem preco da 55C6K", ("Smart TV TCL 55C6K", "Smart TV TCL 43S5K", "R$ 1.799 no Pix"), REJEITA),
    ("R4 comparacao na linha de outro produto", ("📺 TCL 43S5K — R$ 1.999 (mais barata que a 55C6K)",
                                                 "💸 Pix: R$ 1.799"), REJEITA),
    # --- regressão 2 da rodada 3 (e R2-REG2 não resolvido): seta ASCII entre o preço antigo e o novo
    ("R3-REG2 seta ->", ("Smart TV TCL 55C6K", "R$ 4.199 -> R$ 3.599"), {"preco": 3599.0}),
    ("R3-REG2 De seta ->", ("Smart TV TCL 55C6K", "De R$ 4.199 -> R$ 3.599 no Pix"), {"preco": 3599.0}),
    ("R3-REG2 seta =>", ("Smart TV TCL 55C6K", "R$ 4.199 => R$ 2.899 no Pix"), {"preco": 2899.0, "alvo": True}),
    ("R3-REG2 seta >>", ("🔥 TCL 55C6K Mini LED", "R$ 4.199 >> R$ 2.899"), {"preco": 2899.0, "alvo": True}),
    ("R4 seta ⏩", ("Smart TV TCL 55C6K", "R$ 4.199 ⏩ R$ 2.899"), {"preco": 2899.0, "alvo": True}),
    # "> R$" fora de seta continua sendo o mínimo do cupom
    ("R4 maior que fora de seta", ("Smart TV TCL 55C6K", "R$ 3.599", "Cupom TV300: R$ 300 OFF > R$ 2.500"),
     {"preco": 3599.0, "alvo": False, "cupom": "TV300"}),
    # --- regressão 3 da rodada 3 (e R2-REG4 não resolvido): linha da 55C6K que começa por "Tela"
    ("R3-REG3 Tela: | Modelo:", ("🔥 Smart TV TCL QD-Mini LED", '📺 Tela: 55" | Modelo: 55C6K', "💰 R$ 3.599 no Pix"),
     {"preco": 3599.0}),
    ("R3-REG3 Tela de 55 depois de Baixou", ("🔥 Baixou! TCL QD-Mini LED 144Hz", '📺 Tela de 55" (modelo 55C6K)',
                                            "💰 R$ 3.599 no Pix"), {"preco": 3599.0}),
    # a tela de reposição de verdade continua fora (sem "modelo", com "original")
    ("R4 tela de reposicao original", ("Tela De 55 Polegadas Tcl 55c6k Original", "R$ 1.899"), REJEITA),
    # --- regressão 4 da rodada 3: linha comum que cita tamanho, sem preço
    ("R3-REG4 cupom TVs a partir de 50", ('🔥 Smart TV TCL 55" QD-Mini LED 55C6K', "💰 R$ 2.899 no Pix",
                                          "🎟️ Cupom TV10 válido para TVs a partir de 50 polegadas"),
     {"preco": 2899.0, "alvo": True, "cupom": "TV10"}),
    ("R3-REG4 mais barata que a 65C6K", ("Smart TV TCL 55C6K por R$ 3.299", "R$ 700 mais barata que a 65C6K"),
     {"preco": 3299.0}),
    ("R4 faixa de tamanhos do cupom", ("Smart TV TCL 55C6K", "R$ 3.599 no Pix", 'Cupom TV200 para TVs de 50" a 85"'),
     {"preco": 3599.0, "cupom": "TV200"}),
    ("R4 outros tamanhos no fim", ("Smart TV TCL 55C6K QD-Mini LED", "R$ 3.599 no Pix",
                                   'Outros tamanhos: 65" e 75" no link'), {"preco": 3599.0}),
    ("R4 tambem tem a de 65 no link", ("Smart TV TCL 55C6K", "R$ 3.599", 'Também tem a de 65" no mesmo link'),
     {"preco": 3599.0}),
    # disponibilidade com o próprio preço seguida da continuação dele: a continuação também sai
    ("R4 tambem em 43 com ou no Pix", ("Smart TV TCL 55C6K", "R$ 3.599", 'Também disponível em 43" por R$ 1.999',
                                       "ou R$ 1.899 no Pix"), {"preco": 3599.0, "alvo": False}),
    # --- regressão 5 da rodada 3: exclusões que tiravam o único preço
    ("R3-REG5 preco minimo", ("Smart TV TCL 55C6K", "📉 Preço mínimo: R$ 2.899", "🛒 Amazon"),
     {"preco": 2899.0, "alvo": True}),
    ("R3-REG5 mais barato que na Black Friday", ("Smart TV TCL 55C6K", "💥 R$ 2.899 mais barato que na Black Friday"),
     {"preco": 2899.0, "alvo": True}),
    # "mais barato" com outro preço na postagem é a diferença, não o preço
    ("R4 mais barato com outro preco", ("Smart TV TCL 55C6K", "R$ 3.599 no Pix", "R$ 1.600 mais barato que em agosto"),
     {"preco": 3599.0, "alvo": False}),
    # --- N-F3 (não resolvido na rodada 3): condição do cupom como preço
    *[(f"N-F3 r3 {i} {sufixo}", ("Smart TV TCL 55C6K", preco, cupom), {"preco": 3599.0, "alvo": False})
      for i, cupom in [
          ("a", "Garanta até R$ 250 OFF em  qualquer produto  a partir de R$ 2.500 no Magalu"),
          ("c", "Cupom TV300 · Valor mínimo do pedido: R$ 2.500"),
          ("d", "Cupom TV300 de R$ 300, válido a partir de R$ 2.500"),
          ("e", "🏷 Cupom MAGALU300: R$ 300 OFF em produtos a partir de R$ 2.500"),
          ("f", "Cupom TV300 dá R$ 300 de desconto a partir de R$ 2.500"),
          ("g1", "Cupom 10% OFF (desconto máximo de R$ 1.000): TCL10"),
          ("g2", "🏷 10% OFF acima de R$ 2.000, limitado a R$ 1.000: TCL10"),
      ] for preco, sufixo in [("R$ 3.599", "sem Pix"), ("R$ 3.599 no Pix", "no Pix")]],
    ("N-F3 r3 b TECNOBLOG250 a partir de", ("Smart TV TCL 55C6K", "Por R$ 3.349 no Pix",
                                            "🏷 Aplique o cupom TECNOBLOG250 (R$ 250 OFF a partir de R$ 2.500)"),
     {"preco": 3349.0, "alvo": False, "cupom": "TECNOBLOG250"}),
    # condição partida em duas linhas e cashback na linha de baixo (verificador da rodada 3, E23/E24)
    ("R4 pedido minimo em 2 linhas", ("Smart TV TCL 55C6K", "R$ 3.599", "Cupom TV300 para pedidos acima de",
                                      "R$ 2.500"), {"preco": 3599.0, "alvo": False, "cupom": "TV300"}),
    ("R4 cashback em 2 linhas", ("Smart TV TCL 55C6K", "R$ 3.599 no Pix", "Cashback:", "R$ 1.000"),
     {"preco": 3599.0, "alvo": False}),
    # "A partir de R$ X" sem cupom continua sendo o preço (Canaltech)
    ("R4 a partir de sozinho", ("Smart TV TCL 55C6K", "A partir de R$ 2.899"), {"preco": 2899.0, "alvo": True}),
    # --- N-F10 (não resolvido na rodada 3): "CUPOM LIBERADO" não é código
    ("N-F10 r3 CUPOM LIBERADO", ("🚨 CUPOM LIBERADO 🚨", "Smart TV TCL 55C6K", "R$ 3.199 no Pix", "Use o cupom TCL300"),
     {"preco": 3199.0, "cupom": "TCL300"}),
    ("N-F10 r3 CUPOM EXTRA NO APP", ("Smart TV TCL 55C6K", "R$ 3.199 no Pix", "CUPOM EXTRA NO APP: TCL300"),
     {"preco": 3199.0, "cupom": "TCL300"}),
    ("R4 codigo entre aspas curvas", ("Smart TV TCL 55C6K", "R$ 2.899 no Pix", "Código promocional: “TCL100”"),
     {"preco": 2899.0, "alvo": True, "cupom": "TCL100"}),
    # --- verificador da rodada 3: controle por voz como recurso na linha da 55C6K (H7)
    ("R4 controle por voz no inicio da linha", ("🔥 Controle por voz, 144Hz e Mini LED: TCL 55C6K por R$ 2.899 no Pix",),
     {"preco": 2899.0, "alvo": True}),
    # só o preço "De" (verificador da rodada 3, E21): preço antigo nunca é candidato
    ("R4 so o De", ("Smart TV TCL 55C6K", "🔥De R$ 3.599 no Pix"), {"preco": None, "alvo": False}),
    # --- outros casos da segmentação e da classificação (sondas da rodada 4 contra a main)
    # disponibilidade sem preço entre o título e o preço: encerra o bloco; o preço de baixo pode ser do outro tamanho
    ("R4 disponibilidade 43 sem preco no meio", ("Smart TV TCL 55C6K", "Também tem a de 43 polegadas", "R$ 1.999"),
     REJEITA),
    # disponibilidade na própria linha da 55C6K não encerra o bloco
    ("R4 disponibilidade na linha do titulo", ('Smart TV TCL 55C6K (também em 65" e 75")', "R$ 3.599 no Pix"),
     {"preco": 3599.0}),
    # linha de disponibilidade não é "outro produto" para as linhas antes do título
    ("R4 preco antes do titulo + disponibilidade", ("🔥 R$ 3.599 no Pix", "Smart TV TCL 55C6K", 'Também em 43"'),
     {"preco": 3599.0}),
    # a continuação ("ou ... no Pix") de uma comparação é da 55C6K
    ("R4 comparacao + ou no Pix", ("Smart TV TCL 55C6K por R$ 3.299", "R$ 700 mais barata que a 65C6K",
                                   "ou R$ 3.199 no Pix"), {"preco": 3199.0}),
    ("R4 comparacao com palavras no meio", ("Smart TV TCL 55C6K", 'Mais barata que muita TV de 65" por aí', "R$ 3.599"),
     {"preco": 3599.0}),
    # outra tela em polegadas (monitor de 27") é outro produto
    ("R4 monitor 27 na postagem", ("Smart TV TCL 55C6K", "R$ 3.599", 'Monitor Gamer 27" R$ 1.599'),
     {"preco": 3599.0, "alvo": False}),
    ("R4 modelo TCL sem tamanho", ("Smart TV TCL 55C6K R$ 3.599", "TCL QM7K R$ 2.199"), {"preco": 3599.0, "alvo": False}),
    # sem preço, só o valor do cupom: a postagem continua (sem preço), não é peça
    ("R4 cupom (R$ 300) sem preco", ("Smart TV TCL 55C6K", "Cupom TCL300 (R$ 300)"), {"preco": None, "cupom": "TCL300"}),
    # "com cupom a partir de R$ X" sem código antes: é o preço
    ("R4 com cupom a partir de", ("🔥 Smart TV TCL 55C6K com cupom a partir de R$ 2.899",), {"preco": 2899.0, "alvo": True}),
    # "A partir de R$ X" abrindo a linha concorre com os outros candidatos
    ("R4 a partir de + menor preco antigo", ("Smart TV TCL 55C6K", "A partir de R$ 3.349,00",
                                            "📉 Menor preço: R$ 3.999 em agosto"), {"preco": 3349.0}),
    ("R4 estava", ("Smart TV TCL 55C6K", "A partir de R$ 3.349,00", "Estava R$ 4.299 semana passada"),
     {"preco": 3349.0}),
    # "sem juros" de uma linha não se junta ao valor da linha de baixo
    ("R4 parcelado nao cruza linha", ("Smart TV TCL 55C6K", "✅ Parcelado em 10x sem juros", "R$ 3.599"),
     {"preco": 3599.0, "parcelado": None}),
    ("R4 espaco duplo", ("Smart TV TCL 55C6K", "Por  R$  2.899  no Pix"), {"preco": 2899.0, "alvo": True}),
    # "#55polegadas" e medidas da própria TV não são outro produto
    ("R4 hashtag 55polegadas no meio", ("Smart TV TCL 55C6K", "#tv #tcl #55polegadas", "R$ 3.599"), {"preco": 3599.0}),
    ("R4 medida em cm da propria TV", ("Smart TV TCL 55C6K", 'Tela 139,7 cm (55")', "R$ 3.599"), {"preco": 3599.0}),
]


@pytest.mark.parametrize("linhas,esperado", [pytest.param(l, e, id=i) for i, l, e in POSTS_R4])
def test_postagem_r4(linhas, esperado, monkeypatch):
    _confere(_post(_canal(*linhas), monkeypatch), esperado)


def test_nf3_r3_real_11614_com_linha_da_11611(monkeypatch):
    """N-F3 (a): o texto real do achadosdotb/11614 com a linha real do 11611 ('Garanta até R$ 250 OFF em qualquer
    produto a partir de R$ 2.500 no Magalu'). A rodada 3 dava 2500 com 🎯."""
    extra = "Garanta até R$ 250 OFF em  qualquer produto  a partir de R$ 2.500 no Magalu"
    _confere(_post(_post_real_11614(extra), monkeypatch), {"preco": 2910.14, "cupom": "TECNOBLOG250", "alvo": False})


UTIL_R4 = [
    ("N-F10 r3 extra no app", cupom_no_texto, "CUPOM EXTRA NO APP: TCL300", "TCL300"),
    ("N-F10 r3 surpresa", cupom_no_texto, "CUPOM SURPRESA", None),
    ("N-F10 r3 esgotado", cupom_no_texto, "CUPOM ESGOTADO", None),
    ("N-F10 r3 voltou", cupom_no_texto, "CUPOM VOLTOU", None),
    ("N-F10 r3 liberado", cupom_no_texto, "🚨 CUPOM LIBERADO 🚨\nSmart TV TCL 55C6K\nUse o cupom TCL300", "TCL300"),
    ("R4 cupom dois codigos", cupom_no_texto, "🎟️  Cupom:  IFPF2XZ6  ou  BRAE11", "IFPF2XZ6"),
    ("R4 cupom + cartao", cupom_no_texto, "CUPOM + CARTÃO MERCADO PAGO", None),
    ("R4 cupom exclusivo:", cupom_no_texto, "Cupom exclusivo: SOLTAODESCONTO", "SOLTAODESCONTO"),
    ("R3-REG2 seta -> (util)", preco_postagem, "R$ 4.199 -> R$ 3.599", 3599.0),
    ("R3-REG2 seta => (util)", preco_postagem, "R$ 4.199 => R$ 2.899 no Pix", 2899.0),
    ("R3-REG5 preco minimo (util)", preco_postagem, "📉 Preço mínimo: R$ 2.899", 2899.0),
    ("R4 menor preco (util)", preco_postagem, "Menor preço: R$ 2.899", 2899.0),
    ("N-F3 r3 limitado a (util)", preco_postagem, "10% OFF acima de R$ 2.000, limitado a R$ 1.000", None),
    ("N-F3 r3 maximo de (util)", preco_postagem, "Cupom 10% OFF (desconto máximo de R$ 1.000)", None),
    ("R4 cupom colado em ou", cupom_no_texto, "com cupom: BRAE2ou BRFSAFF02", "BRAE2"),
    ("R4 cupom colado em de", cupom_no_texto, "usando o cupom RISE15de Desconto", "RISE15"),
    ("R4 cupom na linha de baixo", cupom_no_texto, "Use o cupom abaixo 👇\nTCL300", "TCL300"),
    ("R4 cupom liberado + palavra embaixo", cupom_no_texto, "🚨 CUPOM LIBERADO 🚨\nAPROVEITE", None),
    ("R4 codigo:", cupom_no_texto, "Use o codigo PRAVC20", "PRAVC20"),
    ("R4 horario nao e codigo", cupom_no_texto, "Cupom válido até 23h59", None),
    ("R4 parcelado nao cruza linha (util)", parcelado_no_texto, "Parcelado em 10x sem juros\nR$ 3.599", None),
    ("R4 estava (util)", preco_postagem, "Estava R$ 4.299, agora R$ 3.599", 3599.0),
]


@pytest.mark.parametrize("func,entrada,esperado", [pytest.param(f, e, s, id=i) for i, f, e, s in UTIL_R4])
def test_util_r4(func, entrada, esperado):
    assert func(entrada) == esperado


# ================================================================ rodada 4, retrabalho (veredito do verificador)
# Uma linha por entrada exata do veredito (itens não resolvidos, regressões e "preexistentes" bloqueantes), mais os
# casos do verificador (v5n/casos*.json) que não constavam do texto. A frase "na mesma posição" do veredito usa o
# título e a linha de preço do exemplo anterior.

TITULOS_R4B = [
    # N-F1: estado do produto (danificado, para conserto, exposição, caixa aberta) e peças aceitos como a TV
    ("N-F1 v tela trincada", "Tv Tcl 55c6k Tela Trincada", False),
    ("N-F1 v nao liga conserto", "Smart Tv Tcl 55c6k Não Liga Para Conserto", False),
    ("N-F1 v display quebrado", "Tv Tcl 55c6k Display Quebrado", False),
    ("N-F1 v tela rachada", "Smart Tv Tcl 55c6k Tela Rachada Funcionando", False),
    ("N-F1 v para reparo", "Tv Tcl 55c6k Para Reparo", False),
    ("N-F1 v queimada", "Smart Tv Tcl 55c6k Queimada", False),
    ("N-F1 v sem imagem", "Tv Tcl 55c6k Sem Imagem", False),
    ("N-F1 v listras", "Tv Tcl 55c6k Com Listras Na Tela", False),
    ("N-F1 v caixa aberta", "Smart TV TCL 55C6K (Caixa Aberta)", False),
    ("N-F1 v embalagem danificada", "Smart TV TCL 55C6K Embalagem Danificada", False),
    ("N-F1 v exposicao", "Smart TV TCL 55C6K Produto de Exposição", False),
    ("N-F1 v grade B", "Smart TV TCL 55C6K Grade B", False),
    ("N-F1 v difusor", "Difusor De Luz Tv Tcl 55c6k", False),
    ("N-F1 v lente difusora", "Lente Difusora Tv Tcl 55c6k Original", False),
    # casos do verificador (v5n/casos5) que a branch já rejeitava
    ("N-F1 v cabo de forca", "Cabo De Força Tv Tcl 55c6k", False),
    ("N-F1 v tampa traseira", "Tampa Traseira Tv Tcl 55c6k", False),
    ("N-F1 v chicote", "Chicote Tv Tcl 55c6k", False),
    ("N-F1 v wifi modulo", "Wifi Módulo Tv Tcl 55c6k", False),
    ("N-F1 v placa wifi", "Placa Wifi Tv Tcl 55c6k", False),
    # regressão 5: títulos reais da TV que a branch passou a rejeitar (a peça começa pelo nome da peça)
    ("REG5 alto-falantes Onkyo (TV)",
     "Smart TV TCL 55C6K 55 Polegadas QD-Mini LED 4K 144Hz Google TV Alto-Falantes Onkyo 2.1", True),
    ("REG5 QD-Mini LED Backlight (TV)", 'Smart TV TCL 55" 55C6K QD-Mini LED Backlight 4K 144Hz Google TV', True),
    ("REG5 pelando tela mini led (TV)", "Tela Mini LED de 55 polegadas: TCL 55C6K por R$ 2.899", True),
    # verificador (v5n/casos1): títulos da TV que continuam aceitos
    ("REG5 amazon controle com comando de voz (TV)",
     "TCL Smart TV QD-Mini LED 55” C6K 4K UHD, Google TV, Dolby Vision IQ & Atmos, Som Onkyo 2.1, 144Hz VRR/ALLM, "
     "HDMI 2.1, Controle Remoto com Comando de Voz", True),
    ("REG5 com alto-falante Onkyo e subwoofer (TV)", "Smart TV TCL 55C6K Google TV com Alto-falante Onkyo e Subwoofer",
     True),
    ("REG5 pes centrais (TV)", "Smart TV TCL 55C6K QD-Mini LED 4K com Pés Centrais", True),
    ("REG5 painel VA (TV)", "Smart TV TCL 55C6K 4K QD Mini LED Tela 55 Polegadas Painel VA 144Hz", True),
    # a peça continua fora quando o título começa por ela
    ("REG5 alto falante no inicio (peca)", "Alto Falante Tv Tcl 55c6k Original", False),
    ("REG5 backlight no inicio (peca)", "Backlight Tv Tcl 55c6k", False),
    ("REG5 tela display para TV (peca)", "Tela Display Painel Para TV TCL 55C6K", False),
]


@pytest.mark.parametrize("titulo,aceita", [pytest.param(t, a, id=i) for i, t, a in TITULOS_R4B])
def test_titulo_r4b(titulo, aceita):
    assert eh_55c6k(titulo) is aceita


def test_nf1_v_trincada_na_faixa_do_sanear_nao_vira_oferta():
    """N-F1: TV com a tela trincada a R$ 2.300 (dentro da faixa do sanear) não entra como oferta de loja."""
    prod = {"id": "x2", "available": True, "title": "Tv Tcl 55c6k Tela Trincada", "path": "/x/p/x2/",
            "price": {"bestPrice": "2300.00", "fullPrice": "2300.00", "price": "2300.00"},
            "seller": {"id": "v", "description": "Vendedor", "category": "3p"}}
    assert magalu.parse_busca(_magalu_busca(prod)) == []


_T = "Smart TV TCL 55C6K"
_ALVO_2899 = {"preco": 2899.0, "alvo": True}
_NF3_V = [
    "Cupom TV300: R$ 300 OFF para compras superiores a R$ 2.500",
    "🏷 Cupom TV300 (R$ 300 OFF em compras iguais ou superiores a R$ 2.500)",
    "🎟️ Cupom TV300 — R$ 300 OFF em compras de +R$ 2.500",
    "🎟️ R$ 300 OFF comprando R$ 2.500 ou mais: TV300",
    "Cupom TV300 · R$ 300 OFF · Compra mín: R$ 2.500",
    # verificador (v5n/casos4)
    "🎟️ TV300: R$ 300 de desconto no carrinho a partir de R$ 2.500",
    "🎟 Cupom TV300 dá R$ 300 OFF na compra de R$ 2.500 ou mais",
    "Cupom TV300 - R$ 300 OFF levando R$ 2.500 em produtos",
    "🎟️ Cupom TV300 | Válido acima de R$ 2.500",
    "🎟️ Cupom TV300 para quem gastar R$ 2.500",
    "🎟️ Cupom TV300 (R$ 300 OFF / pedido mín. R$ 2.500)",
    "Cupom de 10% (até R$ 1.000 de desconto): TCL10",
    "🎟️ 10% OFF no app, máx R$ 1.000: TCL10",
    "🎟️ Cupom TV300 válido em pedidos com valor mínimo de R$ 2.500",
    "🏷 R$ 300 OFF a partir de R$ 2.500 em compras no app: TV300",
]
_CUPOM_FALSO = ["🚨 CUPOM VALENDO 🚨", "🔥 CUPOM FUNCIONANDO 🔥", "🎟️ CUPOM MAGALU", "CUPOM AMAZON LIBERADO",
                "🎟️ CUPOM SHOPEE", "CUPOM QUENTE NO APP", "CUPOM ACABOU", "CUPOM OFICIAL DA LOJA", "CUPOM RENOVADO",
                "CUPOM ABERTO", "CUPOM BOMBA 💣", "CUPOM INSANO", "CUPOM ENCONTRADO", "CUPOM REATIVADO",
                "⚠️ CUPOM ACUMULATIVO COM PIX"]
_VRL = ("(Lançamento 2025) Smart Tv TCL QD-Mini LED C6K 4K 144Hz", "☝️ Use o Cupom: APROVEITANOML",
        "🚛 Frete Grátis (Consultar CEP)", "✅ Parcelado em 10x sem juros",
        "➡️ 55''  | De R$ 3.999,90 Por R$ 2.879,24 https://cutt.ly/LyzITSKh",
        "➡️ 65''  | De R$ 4.799,90 Por R$ 3.979,16 https://cutt.ly/EyzIYk6M")

POSTS_R4B = [
    # --- regressão 1 (ALTA): preço ANTES do nome de cada TV. Nunca o preço da outra TV, nunca 🎯 falso
    ("REG1 a preco antes, 43S5K depois", ("💥 R$ 3.599 no Pix 💥", 'Smart TV TCL 55" QD-Mini LED 55C6K',
                                          "🔗 https://amzn.to/4abc123", "💥 R$ 1.799 no Pix 💥",
                                          'Smart TV TCL 43" QLED 43S5K', "🔗 https://amzn.to/4def456"),
     OuRejeita(preco=3599.0, alvo=False)),
    ("REG1 b preco antes sem Pix", ("🔥 R$ 3.599", 'Smart TV TCL 55" 55C6K QD-Mini LED', "🛒 Magalu: https://tecno.click/abc",
                                    "🔥 R$ 1.799", 'Smart TV TCL 43" 43S5K QLED', "🛒 Magalu: https://tecno.click/def"),
     OuRejeita(preco=3599.0, alvo=False)),
    ("REG1 c roundup TCL preco antes", ("📺 TVs TCL com desconto na Amazon 👇", "💰 R$ 3.499", "TCL 55C6K QD-Mini LED 144Hz",
                                        "https://amzn.to/aaa", "💰 R$ 2.199", "TCL 50P7K QLED", "https://amzn.to/bbb"),
     OuRejeita(preco=3499.0, alvo=False)),
    # preexistente: preço antes do nome com outra marca
    ("REG1 preexistente Samsung preco antes", ("💰 R$ 3.599 no Pix", "📺 Smart TV TCL 55C6K", "💰 R$ 2.199 no Pix",
                                               '📺 Smart TV Samsung 50" Crystal UHD'), OuRejeita(preco=3599.0, alvo=False)),
    # verificador (v5n/casos1-2): o mesmo formato com numeração e com a 55C6K em segundo
    ("REG1 v emoji-numero preco antes", ("1️⃣ R$ 3.599 no Pix", "📺 Smart TV TCL 55C6K QD-Mini LED", "2️⃣ R$ 1.799 no Pix",
                                         "📺 Smart TV TCL 43S5K QLED"), OuRejeita(preco=3599.0, alvo=False)),
    ("REG1 v preco antes, 55C6K em segundo", ("💰 R$ 1.799 no Pix", "📺 Smart TV TCL 43S5K", "💰 R$ 3.599 no Pix",
                                              "📺 Smart TV TCL 55C6K"), OuRejeita(preco=3599.0, alvo=False)),
    # controle: resumo "a partir de" antes e preço DEPOIS de cada TV continua lido de cima para baixo
    ("REG1 controle resumo antes, precos depois", ("🔥 TVs TCL a partir de R$ 1.799", "Smart TV TCL 43S5K", "R$ 1.799 no Pix",
                                                   "Smart TV TCL 55C6K", "R$ 3.599 no Pix"),
     OuRejeita(preco=3599.0, alvo=False)),
    # preexistente: roundup com produto que não é TV (notebook, cadeira) na linha com o próprio preço
    ("REG1 preexistente roundup notebook", ("🔥 OFERTAS DO DIA 🔥", "📺 Smart TV TCL 55C6K — R$ 3.599 no Pix",
                                            "💻 Notebook Acer Aspire 5 — R$ 2.499"), OuRejeita(preco=3599.0, alvo=False)),
    ("REG1 preexistente roundup cadeira", ("🔥 OFERTAS DO DIA 🔥", "📺 Smart TV TCL 55C6K — R$ 3.599 no Pix",
                                           "🪑 Cadeira Gamer com suporte lombar — R$ 1.899"),
     OuRejeita(preco=3599.0, alvo=False)),
    # --- regressão 2: "desconto:" depois de "com o"/"após"/"c/" é o preço final, não o valor do desconto
    ("REG2 preco final com o desconto", ('📺 Smart TV TCL QLED Mini LED C6K de 55" 55C6K', "De R$ 3.999", "Por R$ 3.199 no Pix",
                                         "🏷 Aplique o cupom TECNOBLOG300 (exclusivo!)",
                                         "✅ Preço final com o desconto: R$ 2.899"),
     {"preco": 2899.0, "alvo": True, "cupom": "TECNOBLOG300"}),
    ("REG2 apos o desconto", (_T, "R$ 3.199", "✅ Após o desconto: R$ 2.899"), _ALVO_2899),
    ("REG2 valor apos desconto", (_T, "R$ 3.199", "Valor após desconto: R$ 2.899"), _ALVO_2899),
    ("REG2 pix c/ desconto", (_T, "💵 R$ 3.049 no cartão", "💠 Pix c/ desconto: R$ 2.896"), {"preco": 2896.0, "alvo": True}),
    ("REG2 total c/ desconto", (_T, "R$ 3.199", "Total c/ desconto: R$ 2.899"), _ALVO_2899),
    ("REG2 De + com o desconto", (_T, "De R$ 3.999", "Com o desconto: R$ 2.899"), _ALVO_2899),
    # verificador (v5n/casos1-2)
    ("REG2 v ja com o desconto", (_T, "R$ 3.199", "Já com o desconto: R$ 2.899"), _ALVO_2899),
    ("REG2 v aplicando o desconto", (_T, "R$ 3.199", "Aplicando o desconto: R$ 2.899"), _ALVO_2899),
    ("REG2 v no pix com 5% desconto", (_T, "R$ 3.049 no cartão", "No Pix com 5% desconto: R$ 2.896"),
     {"preco": 2896.0, "alvo": True}),
    ("REG2 v cupom + apos o desconto", ("🔥 Smart TV TCL 55C6K", "💰 R$ 3.199", "🏷 Cupom TCL300", "✅ Após o desconto: R$ 2.899"),
     {"preco": 2899.0, "alvo": True, "cupom": "TCL300"}),
    # controle: "Desconto: R$ X" sozinho (rótulo) continua sendo o valor do desconto
    ("REG2 controle rotulo Desconto:", (_T, "R$ 3.599 no Pix", "💸 Desconto: R$ 1.600"), {"preco": 3599.0, "alvo": False}),
    # --- regressão 3: "a partir de R$ X" sem cupom/desconto na mesma frase é o preço
    ("REG3 frete gratis, a partir de", ('📺 Smart TV TCL QLED Mini LED C6K de 55" 55C6K',
                                        "💰 Com frete grátis, a partir de R$ 2.899 no Pix"), _ALVO_2899),
    ("REG3 5% OFF no Pix, a partir de", (_T, "Com 5% OFF no Pix, a partir de R$ 2.899"), _ALVO_2899),
    ("REG3 produto a partir de", (_T, "Produto a partir de R$ 2.899 no app"), _ALVO_2899),
    ("REG3 ate 20% OFF: TV a partir de", ("🔥 Até 20% OFF: Smart TV TCL 55C6K a partir de R$ 2.899",), _ALVO_2899),
    ("REG3 v frete gratis sem Pix", (_T, "Com frete grátis, a partir de R$ 2.899"), _ALVO_2899),
    # controle: com o código do cupom antes da vírgula continua sendo o mínimo do cupom
    ("REG3 controle cupom, a partir de", (_T, "R$ 3.599 no Pix", "Cupom TV300, a partir de R$ 2.500"),
     {"preco": 3599.0, "alvo": False}),
    # --- regressão 4: linha comum entre o título e o preço lida como cabeçalho de outro produto
    ("REG4 cupom TVs de 50 ou mais", ("📺 Smart TV TCL 55C6K QD-Mini LED", '🎟️ Cupom TVTCL150 válido para TVs de 50" ou mais',
                                      "💰 R$ 2.849 no Pix com cupom"), {"preco": 2849.0, "alvo": True, "cupom": "TVTCL150"}),
    ("REG4 cupom TVs de 50 pra cima", (_T, 'Cupom TV100 para TVs de 50" pra cima', "R$ 2.899 no Pix"),
     {**_ALVO_2899, "cupom": "TV100"}),
    ("REG4 cupom TVs com 50 polegadas ou mais", (_T, "Cupom TV100 em TVs com 50 polegadas ou mais", "R$ 2.899 no Pix"),
     {**_ALVO_2899, "cupom": "TV100"}),
    ("REG4 metade do preco da 65C6K", (_T, "Metade do preço da 65C6K!", "R$ 2.899 no Pix"), _ALVO_2899),
    ("REG4 sucessora da C755", (_T, "Sucessora da C755", "R$ 2.899 no Pix"), _ALVO_2899),
    ("REG4 brilho superior ao da C755", (_T, "Brilho superior ao da C755", "R$ 2.899 no Pix"), _ALVO_2899),
    ("REG4 mesmo processador da QM7K", ("📺 Smart TV TCL 55C6K", "Mesmo processador da QM7K, por bem menos",
                                        "R$ 2.899 no Pix"), _ALVO_2899),
    ("REG4 tambem disponivel em 65 e 75", ("🔥 Smart TV TCL 55C6K QD-Mini LED 144Hz", '📏 Também disponível em 65" e 75"',
                                           "💰 R$ 2.899 no Pix"), _ALVO_2899),
    ("REG4 tambem em 65 e 75", ("🔥 Smart TV TCL 55C6K QD-Mini LED 144Hz", 'Também em 65" e 75"', "💰 R$ 2.899 no Pix"),
     _ALVO_2899),
    ("REG4 versao de 65 no mesmo link", ("🔥 Smart TV TCL 55C6K QD-Mini LED 144Hz", '(versão de 65" no mesmo link)',
                                         "💰 R$ 2.899 no Pix"), _ALVO_2899),
    ("REG4 cupom 43 ou mais depois do preco", (_T, "R$ 2.899 no Pix", 'Cupom TV100 só vale para TVs de 43" ou mais'),
     {**_ALVO_2899, "cupom": "TV100"}),
    # verificador (v5n/casos1-3)
    ("REG4 v sucessora da C755, agora com 144Hz", ("📺 Smart TV TCL 55C6K QD-Mini LED", "Sucessora da C755, agora com 144Hz",
                                                   "💰 R$ 2.899 no Pix"), _ALVO_2899),
    ("REG4 v cupom 43 ou mais antes do preco", (_T, 'Cupom TV100 só vale para TVs de 43" ou mais', "R$ 2.899 no Pix"),
     {**_ALVO_2899, "cupom": "TV100"}),
    ("REG4 v cupom 43 ou mais, preco com o cupom", ('🔥 Smart TV TCL 55" QD-Mini LED 55C6K',
                                                    'Cupom TV100 válido para TVs de 43" ou mais',
                                                    "💰 R$ 2.899 no Pix com o cupom"), {**_ALVO_2899, "cupom": "TV100"}),
    ("REG4 v tambem em 65 e 75 (titulo curto)", (_T, 'Também em 65" e 75"', "R$ 2.899 no Pix"), _ALVO_2899),
    ("REG4 v versao de 65 (titulo curto)", (_T, '(versão de 65" no mesmo link)', "R$ 2.899 no Pix"), _ALVO_2899),
    # preexistentes neutros (a main também rejeitava): "Custa menos que a 50P7K", VESA 100x100, "Peça já"
    ("REG4 preexistente custa menos que a 50P7K", (_T, "Custa menos que a 50P7K do ano passado", "R$ 2.899 no Pix"),
     _ALVO_2899),
    ("REG4 preexistente VESA 100x100", (_T, "Padrão VESA 100x100 (suporte vendido à parte)", "R$ 2.899 no Pix"),
     _ALVO_2899),
    ("REG4 preexistente peca ja", ("🔥 Peça já: Smart TV TCL 55C6K por R$ 2.899 no Pix",), _ALVO_2899),
    # outro tamanho MENOR sem preço entre o título e o preço continua encerrando o bloco (o preço pode ser dela)
    ("REG4 controle tambem tem a de 43 no meio", (_T, "Também tem a de 43 polegadas", "R$ 1.999"), REJEITA),
    # --- regressão 5: títulos de postagem da própria TV com recurso no começo ou alto-falantes/backlight
    ("REG5 alto-falantes Onkyo no titulo do post", ("🔥 Smart TV TCL 55C6K | Alto-falantes Onkyo", "R$ 2.899 no Pix"),
     _ALVO_2899),
    ("REG5 display 144Hz: TCL 55C6K", ("Display 144Hz, Mini LED e Google TV: TCL 55C6K por R$ 2.899 no Pix",), _ALVO_2899),
    ("REG5 tela de 55 com 144Hz: Smart TV", ('Tela de 55" com 144Hz e Mini LED: Smart TV TCL 55C6K', "R$ 2.899 no Pix"),
     _ALVO_2899),
    # verificador (v5n/casos1-2)
    ("REG5 v alto-falantes Onkyo 2.1 com |", ("🔥 Smart TV TCL 55C6K | Mini LED | Alto-falantes Onkyo 2.1", "R$ 2.899 no Pix"),
     _ALVO_2899),
    ("REG5 v display + Mini LED:", ("🔥 Display 144Hz + Mini LED: TCL 55C6K", "R$ 2.899 no Pix"), _ALVO_2899),
    ("REG5 v Mini LED Backlight", ("🔥 TCL 55C6K Mini LED Backlight, 144Hz", "R$ 2.899 no Pix"), _ALVO_2899),
    # --- regressão 6: cupom compartilhado acima das linhas de tamanho (vrlofertas)
    ("REG6 vrl cupom acima dos tamanhos", _VRL, {"preco": 2879.24, "alvo": True, "cupom": "APROVEITANOML"}),
    ("REG6 v vrl com espacos", tuple(re.sub(r"(\S) (\S)", r"\1   \2", l, count=1) for l in _VRL),
     {"preco": 2879.24, "alvo": True, "cupom": "APROVEITANOML"}),
    # --- regressão 7: regras novas que rebaixavam o preço real
    ("REG7 (mais barato do ano!)", (_T, "💰 R$ 2.899 (mais barato do ano!)", "💳 ou R$ 3.099 em 10x sem juros"), _ALVO_2899),
    ("REG7 mais barato no Pix", (_T, "R$ 2.899 mais barato no Pix", "R$ 3.099 no cartão"), _ALVO_2899),
    ("REG7 seta para link", ("🔥 Smart TV TCL 55C6K", "💰 R$ 2.799 ➡️ https://amzn.to/4xyz"), {"preco": 2799.0, "alvo": True}),
    ("REG7 > como marcador", ("> Smart TV TCL 55C6K QD-Mini LED", "> R$ 2.899 no Pix", "> Cupom: TCL100"),
     {**_ALVO_2899, "cupom": "TCL100"}),
    # controle: "R$ X mais barato que ..." com outro preço continua sendo a diferença
    ("REG7 controle diferenca mais barato que", (_T, "R$ 3.599 no Pix", "R$ 1.600 mais barato que em agosto"),
     {"preco": 3599.0, "alvo": False}),
    # --- N-F3: redações do mínimo do cupom, com e sem "no Pix" (e as do verificador, v5n/casos4)
    *[(f"N-F3 v {i} {suf}", (_T, preco, cupom), {"preco": 3599.0, "alvo": False})
      for i, cupom in enumerate(_NF3_V, 1) for preco, suf in [("R$ 3.599", "sem Pix"), ("R$ 3.599 no Pix", "no Pix")]],
    # --- N-F10: palavra de manchete depois de "CUPOM" não é código (e o alerta não leva o cupom falso)
    *[(f"N-F10 v post {c}", (c, _T, "R$ 3.199 no Pix"), {"preco": 3199.0, "cupom": None}) for c in _CUPOM_FALSO],
]


@pytest.mark.parametrize("linhas,esperado", [pytest.param(l, e, id=i) for i, l, e in POSTS_R4B])
def test_postagem_r4b(linhas, esperado, monkeypatch):
    _confere(_post(_canal(*linhas), monkeypatch), esperado)


UTIL_R4B = [
    *[(f"N-F10 v {c}", cupom_no_texto, c, None) for c in _CUPOM_FALSO],
    # regressão 6: códigos que a main lia e a branch perdia
    ("REG6 misto com digito", cupom_no_texto, "🏷 Cupom: Magalu10", "MAGALU10"),
    ("REG6 hifen TCL-300", cupom_no_texto, "Cupom: TCL-300", "TCL-300"),
    ("REG6 hifen MELI-300", cupom_no_texto, "Cupom: MELI-300", "MELI-300"),
    ("REG6 50OFF100", cupom_no_texto, "🎟️ Cupom: 50OFF100", "50OFF100"),
    ("REG6 20OFF150", cupom_no_texto, "Cupom 20OFF150 no carrinho", "20OFF150"),
    ("REG6 v BlackFriday10", cupom_no_texto, "Use o cupom BlackFriday10 no app", "BLACKFRIDAY10"),
    # continuam: letras só depois de ':' ou de um verbo; código com dígito em qualquer ponto da linha
    ("N-F10 v use o cupom: letras", cupom_no_texto, "Use o cupom: BLACKTCL", "BLACKTCL"),
    ("N-F10 v use o cupom letras", cupom_no_texto, "Use o cupom SOLTAODESCONTO na finalização", "SOLTAODESCONTO"),
    ("N-F10 v CUPOM LEVE300", cupom_no_texto, "CUPOM LEVE300", "LEVE300"),
    ("N-F10 v modelo nao e codigo", cupom_no_texto, "Cupom válido para a 55C6K", None),
    # regressão 7 / regressão 2 / N-F3 (util)
    ("REG7 seta para link (util)", preco_postagem, "💰 R$ 2.799 ➡️ https://amzn.to/4xyz", 2799.0),
    ("REG2 com o desconto (util)", preco_postagem, "De R$ 3.999\nCom o desconto: R$ 2.899", 2899.0),
    ("N-F3 v superiores a (util)", preco_postagem, "Cupom TV300: R$ 300 OFF para compras superiores a R$ 2.500", None),
    ("N-F3 v comprando ou mais (util)", preco_postagem, "🎟️ R$ 300 OFF comprando R$ 2.500 ou mais: TV300", None),
]


@pytest.mark.parametrize("func,entrada,esperado", [pytest.param(f, e, s, id=i) for i, f, e, s in UTIL_R4B])
def test_util_r4b(func, entrada, esperado):
    assert func(entrada) == esperado


# verificador (v5n): casos fora do texto do veredito em que a branch se afastava da main, e o estado do produto no
# corpo da postagem (N-F1 também vale nas postagens)
POSTS_R4B_EXTRA = [
    ("R4B v 10x sem juros: total", (_T, "💳 10x sem juros: R$ 2.990"), {"preco": 2990.0}),
    ("R4B controle 2x de R$ 1.799 e parcela", (_T, "R$ 3.599 no Pix", "ou 2x de R$ 1.799"), {"preco": 3599.0, "alvo": False}),
    ("R4B v rack de 60", (_T, 'Cabe no rack de 60"? Sim', "R$ 2.899 no Pix"), _ALVO_2899),
    ("R4B controle rack com preco", (_T, "R$ 3.599 no Pix", 'Rack para TV de 65" — R$ 1.599'), {"preco": 3599.0, "alvo": False}),
    ("N-F1 v post tela trincada", (_T, "Tela trincada no canto, funcionando", "R$ 1.800"), REJEITA),
    ("N-F1 v post para conserto", (_T, "Não liga, para conserto", "R$ 1.600"), REJEITA),
    ("N-F1 v post embalagem danificada", (_T, "Embalagem danificada, produto novo", "R$ 2.700 no Pix"), REJEITA),
    ("N-F1 v post caixa aberta", (_T, "Caixa aberta, nunca usada", "R$ 2.600 no Pix"), REJEITA),
    ("N-F1 v post grade B", (_T, "Grade B (marcas leves)", "R$ 2.500 no Pix"), REJEITA),
    ("N-F1 v post exposicao", (_T, "Produto de exposição", "R$ 2.500 no Pix"), REJEITA),
    ("N-F1 v controle queimadao de precos", ("🔥 QUEIMADÃO DE PREÇOS 🔥", _T, "R$ 2.899 no Pix"), _ALVO_2899),
    ("N-F1 v controle preco quebrado", (_T, "Preço quebrado hoje!", "R$ 2.899 no Pix"), _ALVO_2899),
]


@pytest.mark.parametrize("linhas,esperado", [pytest.param(l, e, id=i) for i, l, e in POSTS_R4B_EXTRA])
def test_postagem_r4b_extra(linhas, esperado, monkeypatch):
    _confere(_post(_canal(*linhas), monkeypatch), esperado)


UTIL_R4B_EXTRA = [
    ("R4B v parcela - sem juros", parcelado_no_texto, "10x de R$ 289,90 - sem juros", "10x R$ 289,90 sem juros"),
    ("R4B v parcela no cartao sem juros", parcelado_no_texto, "10x de R$ 289,90 no cartão sem juros",
     "10x R$ 289,90 sem juros"),
    ("R4B v 1a parcela com juros", parcelado_no_texto, "12x de R$ 299,90 com juros ou 10x de R$ 359,90 sem juros", None),
    ("R4B v rotulo Cupom sozinho", cupom_no_texto, "🎟️ Cupom\nDESCONTAO", "DESCONTAO"),
    ("R4B manchete CUPOM + palavra embaixo", cupom_no_texto, "🔥 CUPOM 🔥\nAPROVEITE", None),
    ("R4B v codigo entre crases", cupom_no_texto, "Cupom: `TCL300`", "TCL300"),
]


@pytest.mark.parametrize("func,entrada,esperado", [pytest.param(f, e, s, id=i) for i, f, e, s in UTIL_R4B_EXTRA])
def test_util_r4b_extra(func, entrada, esperado):
    assert func(entrada) == esperado


# sondas próprias da rodada 4 (retrabalho): casos que as varreduras main x branch acharam durante a correção
POSTS_R4B_SONDAS = [
    # mínimo do cupom escrito de outros jeitos (nunca o preço)
    ("R4B s mín entre parenteses", (_T, "R$ 3.599", "🎟️ R$ 250 OFF (mín R$ 2.500)"), {"preco": 3599.0, "alvo": False}),
    ("R4B s mínimo de", (_T, "R$ 3.599", "R$ 300 OFF - mínimo de R$ 2.500"), {"preco": 3599.0, "alvo": False}),
    ("R4B s carrinhos de", (_T, "R$ 3.599", "Cupom TV300 para carrinhos de R$ 2.500"), {"preco": 3599.0, "alvo": False}),
    # o preço na frase do desconto do cupom continua sendo o preço
    ("R4B s Cupom de R$ 300 OFF: preco", (_T, "Cupom de R$ 300 OFF: R$ 3.299"), {"preco": 3299.0}),
    ("R4B s OFF nesta TV de", (_T, "Cupom TV300 garante R$ 300 OFF nesta TV de R$ 3.599"), {"preco": 3599.0}),
    ("R4B s OFF + Pix = preco", (_T, "Cupom de R$ 300 + Pix = R$ 2.899"), _ALVO_2899),
    ("R4B s OFF sai por", (_T, "🔥 R$ 300 OFF, sai por R$ 3.299"), {"preco": 3299.0}),
    ("R4B s ate 10% OFF, a partir de", (_T, "Até 10% OFF, a partir de R$ 2.899"), _ALVO_2899),
    # ">" marcador depois de uma linha que termina em ':'
    ("R4B s > depois de linha com :", (_T, "⭐ Bot de descontos AliExpress:", "> R$ 2.899 no Pix"), _ALVO_2899),
    # "quebrado" fora da tela/TV e em outra linha não é o estado da TV
    ("R4B s preco quebrado depois de Google TV", ('Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz Google TV',
                                                 "Preço quebrado hoje!", "R$ 2.899 no Pix"), _ALVO_2899),
    ("R4B s nao liga pra marca", (_T, "Quem não liga pra marca vai amar", "R$ 2.899 no Pix"), _ALVO_2899),
    # preço antes e depois de cada produto: não dá para saber de quem é cada preço
    ("R4B s misto preco antes e depois", ("🔥 R$ 3.599 no Pix", _T, "💳 ou R$ 3.799 no cartão", "🔥 R$ 1.799 no Pix",
                                          "Smart TV TCL 43S5K", "💳 ou R$ 1.899 no cartão"),
     OuRejeita(preco=3599.0, alvo=False)),
    ("R4B s resumo + precos na linha de cada TV", ("🔥 TVs TCL a partir de R$ 1.799", "📺 TCL 43S5K — R$ 1.799",
                                                   "📺 TCL 55C6K — R$ 3.599"), {"preco": 3599.0, "alvo": False}),
    # brinde não é outro produto à venda
    ("R4B s monitor de brinde", ("R$ 2.899 no Pix", _T, 'Monitor LG 27" de brinde'), _ALVO_2899),
    # comparação com o próprio preço sai da postagem
    ("R4B s mesma tela da 43S5K por", ("Smart TV TCL 55C6K por R$ 3.599", "Mesma tela da TCL 43S5K por R$ 1.799"),
     {"preco": 3599.0, "alvo": False}),
    # troca consciente da regra da manchete: "CUPOM PALAVRA" sem ':' nem verbo não é código (nem LEVOUBARATO)
    ("R4B s CUPOM LEVOUBARATO sem dois-pontos", (_T, "R$ 2.899 no Pix", "CUPOM LEVOUBARATO"), {**_ALVO_2899, "cupom": None}),
    ("R4B s CUPOM: LEVOUBARATO", (_T, "R$ 2.899 no Pix", "CUPOM: LEVOUBARATO"), {**_ALVO_2899, "cupom": "LEVOUBARATO"}),
]


@pytest.mark.parametrize("linhas,esperado", [pytest.param(l, e, id=i) for i, l, e in POSTS_R4B_SONDAS])
def test_postagem_r4b_sondas(linhas, esperado, monkeypatch):
    _confere(_post(_canal(*linhas), monkeypatch), esperado)


POSTS_R4B_SONDAS2 = [
    # linha de cupom sem valor com "TVs de 43\"" (as TVs em geral) não é outro produto, nem com o preço antes do nome
    ("R4B s cupom para TVs de 43 depois, preco antes", ("R$ 2.899 no Pix", _T, 'Cupom TV100 para TVs de 43"'),
     {**_ALVO_2899, "cupom": "TV100"}),
    # ... mas com o próprio preço é outro produto: o preço dele nunca vai para a 55C6K
    ("R4B s TVs de 43 com cupom e preco", (_T, "R$ 3.599", 'TVs de 43" com cupom TV10: R$ 1.799'),
     {"preco": 3599.0, "alvo": False}),
]


@pytest.mark.parametrize("linhas,esperado", [pytest.param(l, e, id=i) for i, l, e in POSTS_R4B_SONDAS2])
def test_postagem_r4b_sondas2(linhas, esperado, monkeypatch):
    _confere(_post(_canal(*linhas), monkeypatch), esperado)


# ================================================================ rodada 5 (lista fechada N1-N9)
# Uma linha por entrada exata do veredito final da rodada 4 (regressões, itens não resolvidos e preexistentes), mais
# os controles que a correção não pode quebrar. Quando a main também erra, vale o resultado correto.

_T5 = '📺 Smart TV TCL 55" QD-Mini LED 4K 55C6K'
_T5_ALI = '💥   😱  Smart TV 55" TCL 4K UHD MiniLED 55C6K'
_3599_SEM_ALVO = {"preco": 3599.0, "alvo": False}

# N1: mínimo do cupom sem "de" ou sem ponto de milhar é condição, nunca o preço
_N1_ALI = ['🎟️ Cupom TV300 (a partir de R$2500)', '🎟️ Cupom TV300 | a partir de R$ 2500', '🎟️ Cupom: IFPF2XZ6 (acima R$2500)',
           '🎟️ 10% OFF, a partir de R$2500', '🎟️ R$ 300 OFF na AliExpress com cupom (a partir de R$2500): BRGM6',
           '🎟️ Cupom TV300 válido acima R$2500', '🎟️ Cupom TV300: R$ 300 OFF p/ compras +R$2500',
           '🎟️ Cupom de R$ 300 (a partir de R$2500): TV300', '🎟️ Cupom TV300 - compras acima R$2500']
_N1_PRE = ['🎟️ Cupom TV300 (a partir de R$ 2.500)', '🎟️ Cupom TV300 | a partir de R$ 2.500',
           '🎟️ Cupom de R$ 300 (a partir de R$ 2.500): TV300', '🎟️  Cupom:  BRAE11  (acima R$ 2.550)',
           '🎟️  Cupom BRAE11: R$ 305 acima R$ 2.550', '🏷️ Cupom MAGALU250 válido acima R$ 2.500',
           '🎟️ Cupom TV300: R$ 300 OFF p/ compras +R$2.500', '🎟️ Cupom TV300 válido p/ compras acima R$ 2.500',
           '🎟️ 10% OFF, a partir de R$ 2.500', '🎟️ R$ 300 OFF na AliExpress com cupom (a partir de R$ 2.200): BRGM6',
           '🎟️ DESCONTO IMPERDÍVEL: R$ 300 OFF na AliExpress (a partir de R$ 2.200) com cupom: MEGABR06']
# as redações do mínimo já na tabela (_NF3_V 1-5), escritas sem ponto de milhar
_N1_SEM_PONTO = [c.replace("R$ 2.500", "R$2500") for c in _NF3_V[:5]]

POSTS_R5 = [
    # --- N1 (regressão ALTA do veredito: o valor sem ponto de milhar virava o preço)
    ("N1 a pelando DIADOCLIENTE14H", (_T5, '💰 R$ 3.599 no Pix',
                                      '🎟️ Cupom Magazine Luiza R$ 250 acima R$2500: DIADOCLIENTE14H'),
     {**_3599_SEM_ALVO, "cupom": "DIADOCLIENTE14H"}),
    ("N1 b cupom CLIENTE em faixas", (_T5, '💰 R$ 3.599 no Pix',
                                      '🎟️ Compras de R$800 a R$1999 | 8% de Desconto | Limitado a R$160',
                                      'Compras de R$ 2000 a R$3999 | 10% de Desconto | Limitado a R$220',
                                      'Compras acima R$4000 | 12% de Desconto | Limitado a R$500: CLIENTE'), _3599_SEM_ALVO),
    *[(f"N1 c {x}", (_T5_ALI, '🤑  R$ 3.599 no Pix', x), _3599_SEM_ALVO) for x in _N1_ALI],
    # a linha de preço do canal da AliExpress ("R$ 3599 em 12x sem juros"): a main dava preço None (lia 359)
    *[(f"N1 c ali {x}", (_T5_ALI, '💵  R$ 3599 em 12x sem juros', x), _3599_SEM_ALVO) for x in _N1_ALI],
    *[(f"N1 pre {x} {suf}", (_T5, preco, x), _3599_SEM_ALVO)
      for x in _N1_PRE for preco, suf in [("R$ 3.599", "sem Pix"), ("R$ 3.599 no Pix", "no Pix")]],
    *[(f"N1 sem ponto {x} {suf}", (_T, preco, x), _3599_SEM_ALVO)
      for x in _N1_SEM_PONTO for preco, suf in [("R$ 3.599", "sem Pix"), ("R$ 3.599 no Pix", "no Pix")]],
    ("N1 faixas em linhas", (_T5, 'R$ 3.599', '🎟️ Cupom CLIENTE:', '• Compras de R$ 800 a R$ 1.999: 8% OFF',
                             '• Compras de R$ 2.000 a R$ 3.999: 10% OFF', '• Acima de R$ 4.000: 12% OFF'), _3599_SEM_ALVO),
    # controles: o mínimo no Pix continua condição
    ("N1 controle cupom a partir de ... no Pix", (_T5, 'R$ 3.599', 'Cupom TV300 a partir de R$ 2.500 no Pix'), _3599_SEM_ALVO),
    ("N1 controle (a partir de ... no Pix)", (_T5, 'R$ 3.599', '🎟️ Cupom TV300 (a partir de R$ 2.500 no Pix)'),
     _3599_SEM_ALVO),
    # --- N2: dano no CORPO só rejeita com palavra explícita de estado do item; marketing/negação não
    *[(f"N2 {x}", ('📺   Smart TV TCL QLED Mini LED C6K de 55"   55C6K', 'Por  R$  2.849  no Pix', x),
       {"preco": 2849.0, "alvo": True})
      for x in ['✨  Mini LED: sem risco de tela queimada', '✨  Diferente da OLED, não tem problema de tela queimada',
                '✨  Mini LED traz melhor contraste sem risco de tela queimada']],
    ("N2 com cupom TECNOBLOG300", ('📺   Smart TV TCL QLED Mini LED C6K de 55"   55C6K', 'Por  R$  2.849  no Pix',
                                   '✨  Mini LED traz melhor contraste sem risco de tela queimada',
                                   '🏷  Aplique o cupom TECNOBLOG300'),
     {"preco": 2849.0, "alvo": True, "cupom": "TECNOBLOG300"}),
    *[(f"N2 {x}", (_T5, '💰 R$ 2.899 no Pix', x), _ALVO_2899)
      for x in ['✅ Mini LED não sofre com display queimado (burn-in)', '🛡️ Seguro contra TV quebrada por + R$ 149',
                '📦 Se chegar danificado, a Amazon troca sem custo']],
    # controles: palavra explícita de estado do item no corpo continua rejeitando
    ("N2 controle avariada", (_T5, '💰 R$ 2.899 no Pix', '⚠️ TV avariada no transporte'), REJEITA),
    ("N2 controle retirada de pecas", (_T5, 'R$ 1.899', 'Para retirada de peças'), REJEITA),
    ("N2 controle com defeito", (_T5, '💰 R$ 2.899 no Pix', 'Com defeito na tela'), REJEITA),
    ("N2 controle seminova", (_T5, '💰 R$ 2.899 no Pix', 'Seminova, na caixa'), REJEITA),
    # --- N3: valor depois de ':' que segue o desconto/cupom é o preço final
    ("N3 OFF no app:", (_T5, '💰 R$ 3.199', '🔻 R$ 300 OFF no app: R$ 2.899'), _ALVO_2899),
    ("N3 cupom aplicado no carrinho:", (_T5, '💰 R$ 3.199 no Pix', '✅ Cupom de R$ 300 aplicado no carrinho: R$ 2.899'),
     _ALVO_2899),
    ("N3 OFF hoje:", (_T5, 'De R$ 3.299', '🔥 R$ 400 OFF hoje: R$ 2.899'), _ALVO_2899),
    ("N3 de desconto no carrinho:", (_T5, 'De R$ 3.199', 'R$ 300 de desconto no carrinho: R$ 2.899'), _ALVO_2899),
    # controles: com termo de compra antes do ':' continua sendo o mínimo do cupom; faixa depois do preço
    ("N3 controle valido para compras:", (_T5, 'R$ 3.599', 'Cupom de R$ 300 válido para compras: R$ 2.500'),
     _3599_SEM_ALVO),
    ("N3 controle pedidos acima de:", (_T5, 'R$ 3.599', 'R$ 300 OFF para pedidos acima de: R$ 2.500'), _3599_SEM_ALVO),
    ("N1 controle faixa depois do preco", (_T, 'R$ 2.899 no Pix', 'Compras de R$ 2.000 a R$ 3.999 ganham 10% OFF'),
     _ALVO_2899),
    # --- N4: preço no Pix continua candidato com "a partir de"/"mínimo" na frase
    ("N4 no Pix sai a partir de", (_T5, '💳 R$ 3.049 em até 10x sem juros', '💠 No Pix sai a partir de R$ 2.899'), _ALVO_2899),
    ("N4 Pix a partir de", (_T5, 'R$ 3.049 no cartão', 'Pix a partir de R$ 2.899'), _ALVO_2899),
    ("N4 ou a partir de ... no Pix", (_T5, '💰 R$ 3.049', 'ou a partir de R$ 2.899 no Pix'), _ALVO_2899),
    ("N4 preco a partir de ... no Pix", (_T5, '💳 R$ 3.049 no cartão', 'Preço a partir de R$ 2.899 no Pix'), _ALVO_2899),
    ("N4 historico minimo no Pix", (_T5, '💳 R$ 3.049 no cartão', '📉 Histórico mínimo: R$ 2.899 no Pix'), _ALVO_2899),
    ("N4 com o cupom, a partir de", (_T5, '💰 R$ 3.199 no Pix', '🎟️ Com o cupom TV300, a partir de R$ 2.899'),
     {**_ALVO_2899, "cupom": "TV300"}),
    # --- N5: manchete que começa pelos recursos é a TV
    ("N5 tela mini led na smart tv", ('🔥 Tela Mini LED e 144 Hz na Smart TV TCL 55C6K', '💰 R$ 2.899 no Pix'), _ALVO_2899),
    ("N5 painel mini led na TCL", ('🔥 Painel Mini LED, 144Hz e Google TV na TCL 55C6K por R$ 2.899 no Pix',), _ALVO_2899),
    # --- N7: código entre aspas ou depois de um traço é marcador explícito
    ("N7 CUPOM entre aspas", (_T5, '💰 R$ 2.899 no Pix', '🎟️ CUPOM "LEVOUBARATO"'), {**_ALVO_2899, "cupom": "LEVOUBARATO"}),
    ("N7 CUPOM - codigo", (_T5, '💰 R$ 2.899 no Pix', '🎟️ CUPOM - LEVOUBARATO'), {**_ALVO_2899, "cupom": "LEVOUBARATO"}),
    ("N7 Cupom SHOPEE liberado no post", ('🎟️ Cupom SHOPEE liberado', _T5, '💰 R$ 2.899 no Pix'), {**_ALVO_2899, "cupom": None}),
    # --- N8 (ALTA): vários produtos, nunca o preço do outro (nem 🎯 falso)
    ("N8 roundup Galaxy", ('🔥 OFERTAS DO DIA 🔥', '📺 Smart TV TCL 55C6K — R$ 3.599 no Pix', '📱 Galaxy S24 FE — R$ 2.599'),
     OuRejeita(preco=3599.0, alvo=False)),
    ("N8 Samsung 55 sem TV antes", ('📺 Smart TV TCL 55C6K — R$ 3.599 no Pix', '📺 Samsung 55" Crystal UHD — R$ 2.199 no Pix'),
     OuRejeita(preco=3599.0, alvo=False)),
    ("N8 preco antes, Galaxy", ('💰 R$ 3.599 no Pix', '📺 Smart TV TCL 55C6K', '💰 R$ 2.599', '📱 Galaxy S24 FE'),
     OuRejeita(preco=3599.0, alvo=False)),
    ("N8 preco antes, Samsung 55", ('💰 R$ 3.599 no Pix', '📺 Smart TV TCL 55C6K', '💰 R$ 2.199 no Pix',
                                    '📺 Samsung 55" Crystal UHD'), OuRejeita(preco=3599.0, alvo=False)),
    ("N8 Galaxy primeiro", ('📱 Galaxy S24 FE', 'R$ 2.599', '📺 Smart TV TCL 55C6K', 'R$ 3.599 no Pix'),
     OuRejeita(preco=3599.0, alvo=False)),
    ("N8 Samsung 55 primeiro", ('📺 Samsung 55" Crystal UHD', 'R$ 2.199 no Pix', '📺 Smart TV TCL 55C6K', 'R$ 3.599 no Pix'),
     OuRejeita(preco=3599.0, alvo=False)),
    # controles: linha comum que cita a marca no meio da frase continua da 55C6K; linha que abre com outro tipo de
    # produto entre o título e o preço da 55C6K continua da 55C6K (como na main)
    ("N8 controle Samsung no meio da frase", (_T, 'Bate a Samsung de 55" no contraste', "R$ 2.899 no Pix"), _ALVO_2899),
    ("N8 controle celular entre titulo e preco", (_T, "📱 Celular? Compre pelo app", "R$ 2.899 no Pix"), _ALVO_2899),
    ("N8 controle fone de brinde", ("💰 R$ 2.899 no Pix", _T, "🎧 Fone JBL de brinde"), _ALVO_2899),
]


@pytest.mark.parametrize("linhas,esperado", [pytest.param(l, e, id=i) for i, l, e in POSTS_R5])
def test_postagem_r5(linhas, esperado, monkeypatch):
    _confere(_post(_canal(*linhas), monkeypatch), esperado)


@pytest.mark.parametrize("extra", ["✨  Mini LED traz melhor contraste sem risco de tela queimada",
                                   "✅ Mini LED não sofre com display queimado (burn-in)"])
def test_n2_real_11614_com_linha_de_marketing(extra, monkeypatch):
    """N2: o texto real do achadosdotb/11614 com uma linha de marketing sobre tela queimada continua valendo."""
    _confere(_post(_post_real_11614(extra), monkeypatch), {"preco": 2910.14, "cupom": "TECNOBLOG250", "alvo": False})


TITULOS_R5 = [
    # N2: "Preço quebrado" não é dano
    ("N2 preco quebrado no titulo", 'Smart TV TCL 55" QD-Mini LED 55C6K 4K 144Hz Google TV - Preço quebrado', True),
    # N5: manchete que começa pelos recursos da TV
    ("N5 tela mini led na smart tv", "Tela Mini LED e 144 Hz na Smart TV TCL 55C6K", True),
    ("N5 painel mini led na TCL", "Painel Mini LED, 144Hz e Google TV na TCL 55C6K por R$ 2.899", True),
    ("N5 sensor de luz ambiente", "TCL 55C6K Sensor de Luz Ambiente, 144Hz, Google TV", True),
    ("N5 controle tela para TV (peca)", "Tela para TV TCL 55C6K", False),
    ("N5 controle tela mini led para TV (peca)", "Tela Mini LED para TV TCL 55C6K", False),
    # N6: peça com o nome da TV primeiro (o anúncio termina na peça)
    *[(f"N6 {t}", t, False) for t in [
        "Tv Tcl 55c6k Pezinho", "Tv Tcl 55c6k Pés Originais", "Tv Tcl 55c6k Fonte", "Tv Tcl 55c6k Tampa Traseira",
        "Tv Tcl 55c6k Carcaça Traseira", "Tv Tcl 55c6k Módulo Wifi", "Tv Tcl 55c6k Só A Tela", "Tv Tcl 55c6k Lente",
        "Tv Tcl 55c6k Base",
        # estado do produto escrito de outros jeitos (veredito: N-F1 e preexistentes)
        "Tv Tcl 55c6k Semi Nova", "Tv Tcl 55c6k Com Mancha Na Tela", "Tv Tcl 55c6k Tela Manchada",
        "Smart Tv Tcl 55c6k Pixel Morto", "Tv Tcl 55c6k Com Marcas De Uso", "Tv Tcl 55c6k Com Risco Na Tela",
        "Smart TV TCL 55C6K Outlet"]],
    # controles: recurso da TV depois do modelo continua sendo a TV
    ("N6 controle pes ajustaveis", "Smart TV TCL 55C6K Pés Ajustáveis", True),
    ("N6 controle fonte bivolt", "Smart TV TCL 55C6K Fonte bivolt", True),
    ("N6 controle modulo wi-fi integrado", "Smart TV TCL 55C6K Módulo Wi-Fi integrado", True),
    ("N6 controle original", "Smart TV TCL 55C6K Original", True),
    # N9: alto-falantes/backlight num título real da TV; só a peça que começa por eles (ou termina neles) é peça
    ("N9 backlight local dimming", "Smart TV TCL 55C6K QD-Mini LED 4K Backlight Local Dimming", True),
    ("N9 backlight LED", "Smart TV TCL 55C6K 4K 144Hz Backlight LED", True),
    ("N9 alto-falantes Onkyo no fim", "Smart TV TCL 55C6K 144Hz Google TV Alto-Falantes Onkyo", True),
    ("N9 alto-falantes 20W", "Smart TV TCL 55C6K 4K Alto-Falantes 20W e Subwoofer", True),
    ("N9 controle alto falante original (peca)", "Tv Tcl 55c6k Alto Falante Original", False),
    ("N9 controle backlight no fim (peca)", "Tv Tcl 55c6k Backlight", False),
]


@pytest.mark.parametrize("titulo,aceita", [pytest.param(t, a, id=i) for i, t, a in TITULOS_R5])
def test_titulo_r5(titulo, aceita):
    assert eh_55c6k(titulo) is aceita


UTIL_R5 = [
    # N7: palavra só de letras logo depois de "cupom" só é código com marcador explícito
    ("N7 CUPOM VALENDO", cupom_no_texto, "CUPOM VALENDO", None),
    ("N7 CUPOM FUNCIONANDO", cupom_no_texto, "CUPOM FUNCIONANDO", None),
    ("N7 CUPOM MAGALU", cupom_no_texto, "CUPOM MAGALU", None),
    ("N7 Cupom SHOPEE liberado", cupom_no_texto, "🎟️ Cupom SHOPEE liberado", None),
    ("N7 Cupom MAGALU de R$ 300 OFF", cupom_no_texto, "Cupom MAGALU de R$ 300 OFF", None),
    ("N7 Cupom DESBLOQUEADO", cupom_no_texto, "🔓 Cupom DESBLOQUEADO no app", None),
    ("N7 Cupom TELEGRAM", cupom_no_texto, "Cupom TELEGRAM", None),
    ("N7 Cupom NATAL", cupom_no_texto, "Cupom NATAL", None),
    ("N7 CUPOM entre aspas", cupom_no_texto, '🎟️ CUPOM "LEVOUBARATO"', "LEVOUBARATO"),
    ("N7 CUPOM - codigo", cupom_no_texto, "🎟️ CUPOM - LEVOUBARATO", "LEVOUBARATO"),
    ("N7 Codigo LEVOUBARATO", cupom_no_texto, "Código LEVOUBARATO", "LEVOUBARATO"),
    ("N7 Magalu10", cupom_no_texto, "Cupom: Magalu10", "MAGALU10"),
    ("N7 TCL-300", cupom_no_texto, "Cupom: TCL-300", "TCL-300"),
    ("N7 50OFF100", cupom_no_texto, "Cupom 50OFF100", "50OFF100"),
    # N1 / N3 / N4 (util)
    ("N1 acima sem de (util)", preco_postagem, "🎟️ Cupom Magazine Luiza R$ 250 acima R$2500: DIADOCLIENTE14H", None),
    ("N1 faixa (util)", preco_postagem, "🎟️ Compras de R$800 a R$1999 | 8% de Desconto | Limitado a R$160", None),
    ("N3 OFF no app: (util)", preco_postagem, "🔻 R$ 300 OFF no app: R$ 2.899", 2899.0),
    ("N4 Pix a partir de (util)", preco_postagem, "R$ 3.049 no cartão\nPix a partir de R$ 2.899", 2899.0),
]


@pytest.mark.parametrize("func,entrada,esperado", [pytest.param(f, e, s, id=i) for i, f, e, s in UTIL_R5])
def test_util_r5(func, entrada, esperado):
    assert func(entrada) == esperado
