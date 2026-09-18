"""Encerramento garantido dos scripts do PC.

Uma rodada do PC que não termina deixa a tarefa agendada "em execução" e, com IgnoreNew, bloqueia as
seguintes. Isso não chegou a acontecer (em 18/09 foi alarme falso: fuso UTC lido como horário local),
mas o custo de prevenir é baixo. Duas proteções:
- `vigiar(segundos, nome)`: se o próprio Python travar, o faulthandler grava a pilha de todas as
  threads em logs/travou_<nome>.txt e mata o processo. Assim nunca trava para sempre e sabemos onde parou.
- `sair(codigo)`: depois que o trabalho acabou e a saída foi gravada, encerra na hora com os._exit,
  sem esperar finalizadores ou threads de bibliotecas (Playwright, rede) que possam segurar o processo.
"""

from __future__ import annotations

import faulthandler
import os
import sys
from pathlib import Path

_arquivo = None


def vigiar(segundos: int, nome: str) -> None:
    global _arquivo
    pasta = Path(__file__).resolve().parent.parent / "logs"
    pasta.mkdir(exist_ok=True)
    _arquivo = open(pasta / f"travou_{nome}.txt", "w", encoding="utf-8")
    faulthandler.dump_traceback_later(segundos, repeat=False, file=_arquivo, exit=True)
    try:
        sys.stdout.reconfigure(line_buffering=True)  # log em tempo real, mesmo redirecionado
    except Exception:
        pass


def sair(codigo: int) -> None:
    faulthandler.cancel_dump_traceback_later()
    for f in (sys.stdout, sys.stderr, _arquivo):
        try:
            if f:
                f.flush()
        except Exception:
            pass
    try:
        if _arquivo:
            _arquivo.close()
            p = Path(_arquivo.name)
            if p.exists() and p.stat().st_size == 0:
                p.unlink()  # não travou: não deixa arquivo vazio
    except Exception:
        pass
    os._exit(int(codigo or 0))
