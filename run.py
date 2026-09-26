"""Executa uma rodada do monitor.

  python run.py --mode cloud     # fontes por API/HTML (GitHub Actions)
  python run.py --mode pc        # fontes que exigem IP residencial / navegador (seu PC)
  python run.py --mode all       # tudo (para testar localmente)
  opções: --no-notify (não envia Telegram) --so fonte1,fonte2 (roda só essas) --resumo (força resumo diário)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

RAIZ = Path(__file__).resolve().parent


def carrega_env() -> None:
    """Carrega .env da raiz (só no PC; no GitHub Actions os segredos já vêm no ambiente)."""
    arq = RAIZ / ".env"
    if not arq.exists():
        return
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def limita_alertas(msgs: list[str], estado, maximo: int) -> list[str]:
    """Corta as mensagens da rodada no limite. Se a de cupons fica de fora, os cupons dela não foram alertados."""
    if len(msgs) <= maximo:
        return msgs
    from monitor.regras import e_mensagem_de_cupons

    if any(e_mensagem_de_cupons(m) for m in msgs[maximo:]):
        estado.esquece_alertas_de_cupom_da_rodada()
    return msgs[:maximo] + [f"… e mais {len(msgs) - maximo} alertas nesta rodada (veja o painel)."]


def main() -> int:
    carrega_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="cloud", choices=["cloud", "pc", "all"])
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--so", default="", help="lista de fontes separadas por vírgula")
    ap.add_argument("--resumo", action="store_true")
    args = ap.parse_args()

    from monitor import config, notificar
    from monitor.estado import Estado
    from monitor.regras import (
        cupons_aplicaveis, e_mensagem_de_cupons, gerar_alertas, mensagem_bootstrap, mensagem_fonte_quebrada,
        resumo_diario, sanear,
    )
    from monitor.sources import Pular, por_modo
    from monitor.util import agora, hoje

    estado = Estado(args.mode)
    fontes = por_modo(args.mode)
    # fontes que mudaram de modo não devem continuar aparecendo na saúde deste modo
    nomes_modo = {f.nome for f in fontes}
    estado.dados["saude"] = {k: v for k, v in estado.dados["saude"].items() if k in nomes_modo}
    if args.so:
        quer = {s.strip() for s in args.so.split(",")}
        fontes = [f for f in fontes if f.nome in quer or f.nome.split(".")[0] in quer]

    ofertas, cupons, avisos = [], [], []
    executadas: set[str] = set()
    t0 = time.time()
    for f in fontes:
        ini = time.time()
        try:
            o, c = f.coletar()
            ofertas.extend(o)
            cupons.extend(c)
            estado.fonte_ok(f.nome)
            executadas.add(f.nome)
            print(f"[ok]   {f.nome:<22} {len(o):>2} ofertas {len(c):>2} cupons  {time.time()-ini:4.1f}s")
        except Pular as e:
            print(f"[skip] {f.nome:<22} {e}")
        except Exception as e:  # noqa: BLE001
            n = estado.fonte_falhou(f.nome, f"{type(e).__name__}: {e}")
            print(f"[erro] {f.nome:<22} {type(e).__name__}: {str(e)[:160]}  (falha {n})")
            if os.environ.get("DEBUG"):
                traceback.print_exc()
            if n in (3, 10, 30) and getattr(f, "alerta_falha", True):
                avisos.append(mensagem_fonte_quebrada(f.nome, n, str(e)))
        time.sleep(0.5)

    # dedupe por chave (a mesma oferta pode vir de duas buscas)
    unicas: dict[str, object] = {}
    for o in ofertas:
        unicas.setdefault(o.chave, o)
    ofertas = list(unicas.values())  # type: ignore[assignment]
    unicos: dict[str, object] = {}
    for c in cupons:
        unicos.setdefault(c.chave, c)
    cupons = list(unicos.values())  # type: ignore[assignment]

    # confiança (monitor/confianca.py): vendedor/anúncio reprovado (lista curada ou reprovado automático) sai de cara,
    # sem alerta, mínimo, histórico, painel nem carrinho
    from monitor import confianca
    ofertas = confianca.descarta_reprovados(estado, ofertas)  # type: ignore[arg-type]

    ofertas, avisos_sanidade = sanear(ofertas)  # type: ignore[arg-type]
    for a in avisos_sanidade:
        print(f"[sanidade] {a}")

    # veredito de cada oferta de loja: confiável (lista) passa direto; desconhecido passa pelas checagens rápidas
    # (dados da coleta + 1-2 requisições só para vendedor novo com preço atraente); suspeito vira aviso de golpe
    t_conf = time.time()
    contagem = confianca.avaliar(estado, ofertas)  # type: ignore[arg-type]
    if contagem:
        print(f"[confiança] {', '.join(f'{v}: {n}' for v, n in sorted(contagem.items()))} "
              f"({time.time() - t_conf:.1f}s)")

    # chave de oferta que mudou de formato (a coleta passou a pôr o vendedor nela) leva o histórico junto:
    # sem isto a rodada não manda 🔻 e pode repetir 🎯 no mesmo anúncio
    for velha, nova in estado.migra_chaves_de_oferta(ofertas).items():  # type: ignore[arg-type]
        print(f"[estado] histórico de {velha} passou para {nova}")

    msgs, alertados = gerar_alertas(estado, ofertas, cupons)  # type: ignore[arg-type]
    aplicaveis = cupons_aplicaveis(ofertas, cupons, estado)  # type: ignore[arg-type]
    # lojas com fonte direta nesta rodada, no state ou no outro modo: a linha do agregador (Zoom) delas não é preço
    diretas = estado.lojas_diretas_conhecidas(ofertas)  # type: ignore[arg-type]

    if estado.bootstrap and (ofertas or cupons):
        msgs = [mensagem_bootstrap(ofertas, aplicaveis, args.mode, diretas)]  # type: ignore[arg-type]

    # resumo diário
    h = agora().hour
    if args.resumo or (config.HORA_RESUMO_DIARIO >= 0 and h >= config.HORA_RESUMO_DIARIO
                       and estado.dados.get("ultimo_resumo") != hoje() and args.mode != "pc"):
        if not estado.bootstrap:
            msgs.append(resumo_diario(estado, ofertas, aplicaveis))  # type: ignore[arg-type]
        estado.dados["ultimo_resumo"] = hoje()

    msgs = limita_alertas(avisos + msgs, estado, config.MAX_ALERTAS_POR_EXECUCAO)

    enviados = 0
    for m in msgs:
        if args.no_notify:
            print("[alerta]\n" + m + "\n")
        elif not notificar.enviar(m) and config.TELEGRAM_BOT_TOKEN and e_mensagem_de_cupons(m):
            estado.esquece_alertas_de_cupom_da_rodada()  # não chegou ao Telegram: os cupons não foram alertados
        enviados += 1

    # persistência
    chaves_vistas = set()
    for o in ofertas:  # type: ignore[assignment]
        estado.registra_oferta(o, alertados.get(o.chave))  # type: ignore[union-attr]
        # inativa/descartada nunca vira "menor já visto"; agregador só quando a loja não tem fonte direta conhecida
        estado.atualiza_minimo(o, diretas)  # type: ignore[arg-type]
        chaves_vistas.add(o.chave)  # type: ignore[union-attr]
    for c in cupons:  # type: ignore[assignment]
        estado.registra_cupom(c)  # type: ignore[arg-type]
    estado.marca_inativas(chaves_vistas, executadas)
    # histórico/gráfico: só preços ativos (esgotado ou descartado pelo sanear não é preço da TV)
    estado.anexa_historico([o for o in ofertas if o.tipo == "loja" and o.ativo and o.melhor_preco])  # type: ignore[union-attr]
    if not args.so:  # uma execução parcial (--so) não deve sobrescrever o painel com dados incompletos
        estado.escreve_latest(ofertas, aplicaveis)  # type: ignore[arg-type]
    estado.salva()

    n_loja = sum(1 for o in ofertas if o.tipo == "loja")  # type: ignore[union-attr]
    n_post = len(ofertas) - n_loja
    melhor = min([o.melhor_preco for o in ofertas  # type: ignore[union-attr]
                  if o.tipo == "loja" and o.ativo and o.melhor_preco and not confianca.fora_de_preco(o)] or [0])
    print(f"\n{args.mode}: {n_loja} preços de loja, {n_post} postagens, {len(cupons)} cupons, "
          f"{enviados} alertas, melhor preço {melhor:.2f}, {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    if "--mode" in sys.argv and sys.argv[sys.argv.index("--mode") + 1:][:1] == ["pc"]:
        # só no PC: garante que o processo termina (ver monitor/saida.py). Na nuvem o Actions já tem prazo.
        from monitor.saida import sair, vigiar

        vigiar(8 * 60, "coleta")
        sair(main())
    sys.exit(main())
