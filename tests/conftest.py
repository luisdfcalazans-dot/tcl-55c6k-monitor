"""Configuração comum dos testes."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _sem_bloqueio_do_magalu_entre_testes(monkeypatch):
    """magalu.BLOQUEADO_EM é global do processo (a coleta levou 403/429 há pouco -> a checagem de confiança não
    insiste). Um teste que simula o 403 não pode desligar a checagem de rede dos testes seguintes."""
    from monitor.sources import magalu

    monkeypatch.setattr(magalu, "BLOQUEADO_EM", None)


@pytest.fixture(autouse=True)
def _sem_bloqueio_da_casasbahia_entre_testes(monkeypatch):
    """playwright_sources._CB_BLOQUEADA_EM é global do processo (a Casas Bahia bloqueou nesta execução -> a fonte do PS5
    não abre páginas): um teste que simula o bloqueio não pode pular a coleta dos testes seguintes."""
    from monitor.sources import playwright_sources

    monkeypatch.setattr(playwright_sources, "_CB_BLOQUEADA_EM", None)


@pytest.fixture(autouse=True)
def _sem_modo_vigia(monkeypatch):
    """O modo vigia (TV comprada em 03/10/2026) depende da data de hoje: os testes rodam com ele DESLIGADO, salvo os
    que ligam de propósito."""
    from monitor import config

    monkeypatch.setattr(config, "VIGIA_ATE", "")
