"""Tabela de ouro do grupo extracao-nuvem (rodada 3).

Uma linha por exemplo concreto do arquivo de retrabalho: evidência de cada achado original (N-F1..N-F10),
cada regressão das rodadas 1 e 2 e cada caso "tem de continuar funcionando" citado pelos verificadores.
Entrada -> saída esperada (aceita/rejeita, preço, parcelado, cupom, alerta 🎯 ou não).

Quando uma expectativa antiga e uma nova se contradizem, vale a do verificador mais recente (comentário na linha).
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


def _confere(res: dict | None, esperado: dict | None):
    if esperado is None:
        assert res is None, f"devia rejeitar, saiu {res}"
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
    # rodada 2 esperava 3599 nestas; a orientação da rodada 3 prefere rejeitar a postagem quando o outro produto
    # aparece numa linha sem preço (o preço dele vem depois e não dá para saber de quem é)
    ("R2 outra TV acima da 55C6K", ('Smart TV TCL 43" 43S5K', "R$ 1.799 no Pix", 'Smart TV TCL 55" 55C6K',
                                    "R$ 3.599 no Pix"), REJEITA),
    ("R2 Samsung sem codigo", ("Smart TV TCL 55C6K", "R$ 3.599", "Smart TV Samsung Crystal UHD", "R$ 2.299 no Pix"),
     REJEITA),
    ("R2 43S5K com cupom proprio", ("Smart TV TCL 55C6K", "R$ 3.599", "Smart TV TCL 43S5K",
                                    "R$ 1.799 ou 10x de R$ 179,90 sem juros", "Cupom TCL43"), REJEITA),
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
    # outro tamanho numa linha SEM preço: o preço das linhas de baixo pode ser dele (43" é mais barata): sai tudo
    ("R2-REG3 outro tamanho sem preco (sem alerta falso)", ("Smart TV TCL 55C6K", "R$ 3.599", "Também tem a de 43 polegadas",
                                                            "R$ 1.999"), REJEITA),
    # a mesma regra perde esta postagem legítima (65"/75" da C6K são mais caras): ver test_postagem_nao_perder
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


@pytest.mark.xfail(strict=True, reason=(
    "não perder x sem alerta falso: a linha 'outro tamanho sem preço' pode vir seguida do preço de uma TV mais barata "
    "(43\", ou 65\" de outro modelo sem código); a regra simples descarta a postagem inteira, como a main fazia com "
    "outro modelo. Vale 'sem alerta falso'."))
def test_postagem_nao_perder_outros_tamanhos_sem_preco(monkeypatch):
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
