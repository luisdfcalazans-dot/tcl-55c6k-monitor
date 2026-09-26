"""Configuração comum dos testes."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _sem_bloqueio_do_magalu_entre_testes(monkeypatch):
    """magalu.BLOQUEADO_EM é global do processo (a coleta levou 403/429 há pouco -> a checagem de confiança não
    insiste). Um teste que simula o 403 não pode desligar a checagem de rede dos testes seguintes."""
    from monitor.sources import magalu

    monkeypatch.setattr(magalu, "BLOQUEADO_EM", None)
