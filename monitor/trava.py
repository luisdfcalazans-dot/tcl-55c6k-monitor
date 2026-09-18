"""Trava exclusiva por perfil do Chrome.

O Chrome não deixa dois processos usarem a mesma pasta de perfil: o segundo recebe
"Abrindo em uma sessão de navegador existente" e o Playwright morre com TargetClosedError.
Isso aconteceu quando a tarefa agendada e um teste manual rodaram ao mesmo tempo.

Uso:
    with trava_perfil(pasta_do_perfil):          # espera até 0 s por padrão
        ... abre o Chrome nesse perfil ...

Se o perfil estiver ocupado, levanta PerfilOcupado, que as fontes tratam como "pular desta vez".
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


class PerfilOcupado(Exception):
    """Outro processo está usando este perfil do Chrome agora."""


def _travar(fh) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _destravar(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def trava_perfil(pasta: Path, espera_s: float = 0.0):
    """Segura o perfil com um lock do sistema operacional (some sozinho se o processo morrer)."""
    pasta = Path(pasta)
    pasta.parent.mkdir(parents=True, exist_ok=True)
    arq = pasta.parent / f".{pasta.name}.lock"
    fh = open(arq, "a+b")
    try:
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        limite = time.monotonic() + max(0.0, espera_s)
        while not _travar(fh):
            if time.monotonic() >= limite:
                raise PerfilOcupado(f"perfil {pasta.name} em uso por outro processo")
            time.sleep(2)
        try:
            yield
        finally:
            _destravar(fh)
    finally:
        fh.close()
