"""Ajustes finais de 03/10 (sessão principal): títulos comuns do GTA 6, pacotes sem a palavra console e cupons que
citam o leitor junto do console. Casos achados na conferência da última passada e na checagem manual."""

import pytest

from monitor import produtos, regras
from monitor.util import sem_acentos

CASOS = [
    # títulos comuns de loja: o PS5 depois do GTA é a plataforma do jogo (eram descartados como acessório)
    ("Jogo GTA VI para PS5", "GTA6_CODE_IN_BOX"),
    ("GTA VI para PS5 Mídia Física", "GTA6_CODE_IN_BOX"),
    ("Grand Theft Auto VI para PlayStation 5", "GTA6_CODE_IN_BOX"),
    ("GTA 6 para PS5", "GTA6_CODE_IN_BOX"),
    ("GTA 6 para PS5 e PS5 Pro", "GTA6_CODE_IN_BOX"),
    ("GTA VI Ultimate para PS5", "GTA6_ULTIMATE"),
    ("Grand Theft Auto VI para PlayStation 5 - Digital", "GTA6_DIGITAL"),
    ("GTA VI para PS5 + Brinde Mapa", "GTA6_CODE_IN_BOX"),
    # pacotes sem a palavra console: o PS5 é o produto, não a plataforma de uma peça nem o jogo digital
    ("PS5 Digital + GTA VI", "PS5_DIGITAL_GTA6"),
    ("PlayStation 5 Digital + GTA VI", "PS5_DIGITAL_GTA6"),
    ("PS5 Slim Digital 825GB + GTA 6", "PS5_DIGITAL_GTA6"),
    ("PS5 Slim 1TB + GTA 6 + Controle", "PS5_DISCO_GTA6"),
    ("PlayStation 5 Digital + GTA VI + 2 Controles", "PS5_KIT"),
    # o que continua fora
    ("Controle para PS5 GTA VI Edition", None),
    ("Capa para PS5 GTA 6", None),
    ("Mousepad GTA VI para PS5", None),
    ("Mousepad Gamer Grande - GTA VI PAISAGEM 2 - 90x40", None),
    ("Suporte de Controle para PS5 GTA 6", None),
    ("Grand Theft Auto V para PS5", None),
    ("Pôster GTA VI para quarto", None),
    ("Notebook Gamer + GTA VI de brinde para PS5", None),
]


@pytest.mark.parametrize("titulo,esperado", CASOS)
def test_classifica_titulos_gta(titulo, esperado):
    assert produtos.classifica(titulo)[0] == esperado


@pytest.mark.parametrize("texto,temas", [
    ("Cupom para Leitor de Disco e Console PS5", {"console", "leitor"}),
    ("10% OFF em consoles e leitores de disco", {"console", "leitor"}),
    ("R$ 62 OFF no Leitor de Disco PS5", {"leitor"}),
    ("R$ 62 OFF no Leitor de Disco para Console PS5", {"leitor"}),
    ("R$ 200 OFF no PS5 Slim com Leitor de Disco", {"console"}),
])
def test_temas_do_cupom_leitor_e_console(texto, temas):
    t = regras._temas_do_texto(sem_acentos(texto).lower())
    assert {x for x in t if x in ("console", "leitor")} == temas
