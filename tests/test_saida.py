"""O processo do PC nunca pode ficar vivo depois do trabalho, nem travar para sempre."""

import subprocess
import sys
import textwrap
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _roda(codigo: str, limite: float = 30.0):
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, "-c", textwrap.dedent(codigo)], cwd=RAIZ, timeout=limite,
                       capture_output=True, text=True)
    return p, time.monotonic() - t0


def test_sair_nao_espera_thread_pendurada():
    p, dur = _roda("""
        import threading, time
        from monitor.saida import sair
        threading.Thread(target=lambda: time.sleep(600), daemon=False).start()   # seguraria o processo
        print('trabalho feito', flush=True)
        sair(0)
    """)
    assert p.returncode == 0 and "trabalho feito" in p.stdout
    assert dur < 15, f"demorou {dur:.1f}s para sair"


def test_vigiar_mata_processo_travado_e_grava_a_pilha():
    arq = RAIZ / "logs" / "travou_teste_vigia.txt"
    arq.unlink(missing_ok=True)
    p, dur = _roda("""
        import time
        from monitor.saida import vigiar
        vigiar(3, 'teste_vigia')
        time.sleep(600)   # trava
    """)
    assert dur < 20, f"o cão de guarda não matou o processo ({dur:.1f}s)"
    assert p.returncode != 0
    dump = arq.read_text(encoding="utf-8") if arq.exists() else ""
    assert "Timeout" in dump and "Thread" in dump, dump   # pilha de onde travou
    arq.unlink(missing_ok=True)
