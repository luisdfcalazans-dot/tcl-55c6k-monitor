"""Testa cupons no carrinho das lojas com a sua conta logada e avisa o melhor preço da TV.

  python testar_cupons.py --loja magalu --login          # abre o Chrome para VOCÊ fazer login (uma vez por loja)
  python testar_cupons.py --loja mercadolivre --login
  python testar_cupons.py                                 # testa os cupons novos em todas as lojas logadas
  python testar_cupons.py --loja magalu --codigos ABC,XYZ # testa códigos específicos
  python testar_cupons.py --forcar                        # testa de novo todos os cupons conhecidos
  opções: --no-notify  --visivel (mostra a janela)  --check (só confere a sessão)

O robô nunca avança para pagamento nem digita dados de conta. Só aplica cupom, lê o total e remove.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from run import carrega_env  # noqa: E402

carrega_env()

from monitor import config, notificar  # noqa: E402
from monitor.carrinho import LOJAS, LojaCarrinho, PrecisaLogin, ResultadoCupom, abrir_navegador  # noqa: E402
from monitor.util import agora_iso, fmt_preco, hoje, loja_canonica  # noqa: E402

ARQ_ESTADO = config.DIR_DADOS / "cupons_carrinho.json"
CODIGOS_IGNORAR = {"DIRETO NO LINK", "SEM CUPOM", "LINK"}
MAX_POR_RODADA = 25


def carrega_estado() -> dict:
    if ARQ_ESTADO.exists():
        try:
            return json.loads(ARQ_ESTADO.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def salva_estado(d: dict) -> None:
    config.DIR_DADOS.mkdir(parents=True, exist_ok=True)
    ARQ_ESTADO.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def codigos_conhecidos(loja: LojaCarrinho) -> tuple[list[str], str]:
    """Cupons da loja vindos das coletas (Promobit, Pelando, etiquetas, postagens) + CUPONS_EXTRA do .env.
    Devolve (códigos, url do anúncio mais barato dessa loja)."""
    import os

    cods: dict[str, str] = {}
    url_barato, preco_barato = "", 1e9
    for arq in ("latest_cloud.json", "latest_pc.json"):
        d = _json(config.DIR_DADOS / arq)
        for c in d.get("cupons") or []:
            if loja_canonica(c.get("loja", "")) == loja.loja_canonica and c.get("codigo"):
                cods.setdefault(c["codigo"].strip().upper(), c.get("fonte", ""))
        for p in d.get("posts") or []:
            if loja_canonica(p.get("loja", "")) == loja.loja_canonica and p.get("cupom"):
                cods.setdefault(str(p["cupom"]).strip().upper(), p.get("fonte", ""))
        for o in d.get("ofertas_loja") or []:
            if loja_canonica(o.get("loja", "")) != loja.loja_canonica:
                continue
            if o.get("cupom"):
                cods.setdefault(str(o["cupom"]).strip().upper(), "produto")
            mp = o.get("melhor_preco")
            if o.get("ativo", True) and mp and mp < preco_barato and loja.dominio_url in (o.get("url") or ""):
                preco_barato, url_barato = mp, o["url"]
    for c in os.environ.get("CUPONS_EXTRA", "").split(","):
        if c.strip():
            cods.setdefault(c.strip().upper(), "manual")
    lista = [c for c in cods if 3 <= len(c) <= 30 and c not in CODIGOS_IGNORAR and " " not in c]
    return lista, (url_barato or loja.url_produto)


def msg_melhor(resultados: list[tuple[str, ResultadoCupom]]) -> str:
    """Uma mensagem só, com o melhor preço à vista e o melhor parcelado entre todas as lojas."""
    validos = [(n, r) for n, r in resultados if r.aceito and (r.tv_pix or r.tv_cartao)]
    if not validos:
        return ""
    melhor_vista = min(validos, key=lambda x: x[1].tv_pix or x[1].tv_cartao or 9e9)
    com_parcela = [(n, r) for n, r in validos if r.parcelado and r.tv_cartao]
    melhor_parc = min(com_parcela, key=lambda x: x[1].tv_cartao or 9e9) if com_parcela else None

    r = melhor_vista[1]
    alvo = (r.tv_pix is not None and r.tv_pix <= config.ALVO_PIX) or \
           (melhor_parc and (melhor_parc[1].tv_cartao or 9e9) <= config.ALVO_PARCELADO)
    linhas = ["🎯 <b>META ATINGIDA</b>" if alvo else "✅ <b>Cupom funcionou</b>", ""]
    linhas.append(f"<b>Melhor à vista</b>: {fmt_preco(r.tv_pix or r.tv_cartao)} na {melhor_vista[0]} "
                  f"com <code>{r.codigo}</code>")
    if r.extra.get("antes_pix") and r.frete is not None:
        antes = round(r.extra["antes_pix"] - r.frete, 2)
        if antes > (r.tv_pix or 0):
            linhas.append(f"   antes {fmt_preco(antes)}, economia de {fmt_preco(antes - (r.tv_pix or 0))}")
    if melhor_parc:
        p = melhor_parc[1]
        linhas.append(f"<b>Melhor parcelado</b>: {fmt_preco(p.tv_cartao)} em {p.parcelado} na {melhor_parc[0]} "
                      f"com <code>{p.codigo}</code>")
    outros = [f"{n}: {fmt_preco(x.tv_pix or x.tv_cartao)} ({x.codigo})" for n, x in
              sorted(validos, key=lambda x: x[1].tv_pix or x[1].tv_cartao or 9e9)[1:5]]
    if outros:
        linhas.append("")
        linhas.append("Outros que funcionaram: " + " · ".join(outros))
    linhas.append("")
    linhas.append(f"Alvo: Pix {fmt_preco(config.ALVO_PIX)} · parcelado {fmt_preco(config.ALVO_PARCELADO)}")
    linhas.append("O melhor cupom ficou aplicado no carrinho; é só entrar e finalizar.")
    return "\n".join(linhas)


def testar_loja(loja_id: str, codigos: list[str] | None, forcar: bool, visivel: bool,
                notify: bool, estado: dict) -> list[ResultadoCupom]:
    loja = LOJAS[loja_id]
    reg = estado.setdefault(loja_id, {"cupons": {}, "aviso_login": None, "ultima_execucao": None})
    if not loja.perfil().exists():
        print(f"[{loja_id}] sem login salvo. Rode: python testar_cupons.py --loja {loja_id} --login")
        return []
    conhecidos, url = codigos_conhecidos(loja)
    fila = [c.upper() for c in (codigos or conhecidos)]
    testados = reg["cupons"]
    if not forcar and not codigos:
        fila = [c for c in fila if c not in testados
                or (testados[c].get("aceito") and (testados[c].get("testado_em") or "")[:10] < hoje())]
    if not fila:
        print(f"[{loja_id}] nada novo ({len(conhecidos)} cupons conhecidos, todos já testados)")
        return []
    print(f"[{loja_id}] {len(fila)} cupons: {', '.join(fila[:20])}{'…' if len(fila) > 20 else ''}")
    print(f"[{loja_id}] anúncio: {url}")

    from playwright.sync_api import sync_playwright

    aceitos: list[ResultadoCupom] = []
    with sync_playwright() as pw:
        ctx = abrir_navegador(pw, loja, visivel)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if not loja.garantir_item(page, url):
                print(f"[{loja_id}] não consegui colocar a TV no carrinho")
                return []
            base = loja.ler_totais(page)
            print(f"[{loja_id}] carrinho: produtos {fmt_preco(base.produtos)} frete {fmt_preco(base.frete)} "
                  f"Pix {fmt_preco(base.total_pix)} cartão {fmt_preco(base.total_cartao)} · logado={loja.logado(page)}")
            for i, cod in enumerate(fila[:MAX_POR_RODADA]):
                try:
                    r = loja.aplicar(page, cod)
                except PrecisaLogin:
                    raise
                except Exception as e:  # noqa: BLE001
                    r = ResultadoCupom(codigo=cod, aceito=False, mensagem=f"erro: {type(e).__name__}: {str(e)[:120]}")
                testados[cod] = {
                    "testado_em": agora_iso(), "aceito": r.aceito, "mensagem": r.mensagem[:200],
                    "tv_pix": r.tv_pix, "tv_cartao": r.tv_cartao, "total_pix": r.total_pix,
                    "total_cartao": r.total_cartao, "frete": r.frete, "desconto": r.desconto,
                    "parcelado": r.parcelado,
                }
                print(f"  {'✅' if r.aceito else '✗ '} {cod:<18} "
                      f"{('TV ' + fmt_preco(r.tv_pix or r.tv_cartao)) if r.aceito else r.mensagem[:90]}")
                if r.aceito:
                    aceitos.append(r)
                    loja.remover(page)
                    page.wait_for_timeout(1000)
                if i % 5 == 4:
                    page.wait_for_timeout(3000)  # respiro para não parecer ataque
            (RAIZ / "logs").mkdir(exist_ok=True)
            page.screenshot(path=str(RAIZ / "logs" / f"carrinho_{loja_id}.png"))
        except PrecisaLogin as e:
            print(f"[{loja_id}] {e}")
            if notify and reg.get("aviso_login") != hoje():
                notificar.enviar(f"🔐 <b>{loja.loja_canonica}</b>: a sessão expirou, não consigo testar cupons.\n"
                                 f"No PC, rode:\n<code>python testar_cupons.py --loja {loja_id} --login</code>")
                reg["aviso_login"] = hoje()
        finally:
            reg["ultima_execucao"] = agora_iso()
            ctx.close()

    # deixa o melhor cupom aplicado no carrinho
    if aceitos:
        melhor = min(aceitos, key=lambda r: r.tv_pix or r.tv_cartao or 9e9)
        with sync_playwright() as pw:
            ctx = abrir_navegador(pw, loja, visivel)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                loja.garantir_item(page, url)
                loja.aplicar(page, melhor.codigo)
            except Exception:
                pass
            finally:
                ctx.close()
    print(f"[{loja_id}] {len(aceitos)} aceito(s) de {len(fila[:MAX_POR_RODADA])} testados")
    return aceitos


def executar(lojas: list[str], codigos: list[str] | None, forcar: bool, visivel: bool, notify: bool) -> int:
    estado = carrega_estado()
    resultados: list[tuple[str, ResultadoCupom]] = []
    for loja_id in lojas:
        try:
            for r in testar_loja(loja_id, codigos, forcar, visivel, notify, estado):
                resultados.append((LOJAS[loja_id].loja_canonica, r))
        except Exception as e:  # noqa: BLE001
            print(f"[{loja_id}] falhou: {type(e).__name__}: {str(e)[:160]}")
        salva_estado(estado)
    msg = msg_melhor(resultados)
    if msg:
        if notify:
            notificar.enviar(msg)
        else:
            print("\n[alerta]\n" + msg + "\n")
    return 0


def checar_sessao(loja_id: str, visivel: bool = False) -> bool:
    """Abre o carrinho num contexto novo do perfil salvo e diz se a sessão está logada (com foto em logs/)."""
    loja = LOJAS[loja_id]
    from playwright.sync_api import sync_playwright

    (RAIZ / "logs").mkdir(exist_ok=True)
    with sync_playwright() as pw:
        ctx = abrir_navegador(pw, loja, visivel=visivel)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(loja.url_carrinho, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            ok = loja.logado(page)
            texto = page.evaluate("() => document.body ? document.body.innerText : ''")
            foto = RAIZ / "logs" / f"sessao_{loja_id}.png"
            page.screenshot(path=str(foto))
            print(f"[{loja_id}] url: {page.url}")
            print(f"[{loja_id}] cabeçalho: {texto[:260].replace(chr(10), ' | ')}")
            print(f"[{loja_id}] foto: {foto}")
        except Exception as e:  # noqa: BLE001
            print(f"[{loja_id}] erro ao abrir o carrinho: {type(e).__name__}: {str(e)[:120]}")
            ok = False
        finally:
            ctx.close()
    print(f"[{loja_id}] sessão logada: {'SIM' if ok else 'NÃO'}")
    return ok


def login(loja_id: str) -> int:
    loja = LOJAS[loja_id]
    from playwright.sync_api import sync_playwright

    print(f"Vai abrir uma janela do Chrome na página de login do {loja.loja_canonica}.")
    print("Faça o login normalmente (e-mail/CPF, senha, código se pedir). Eu não vejo nem guardo esses dados;")
    print("ficam só no perfil do Chrome desta pasta. NÃO feche a janela: quando terminar, volte aqui e aperte Enter.")
    with sync_playwright() as pw:
        ctx = abrir_navegador(pw, loja, visivel=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(loja.url_login, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        input("\n>>> Terminou o login? Aperte Enter para continuar... ")
        try:
            page.goto(loja.url_carrinho, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
    ok = checar_sessao(loja_id)
    if ok:
        print(f"Login salvo. Agora rode: python testar_cupons.py --loja {loja_id} --visivel --forcar")
        return 0
    print("Não detectei a sessão logada. Veja a foto em logs\\ e me mande o cabeçalho acima.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loja", default="todas", choices=sorted(LOJAS) + ["todas"])
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--check", action="store_true", help="só confere se a sessão salva está logada")
    ap.add_argument("--codigos", default="")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--visivel", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    a = ap.parse_args()
    (RAIZ / "logs").mkdir(exist_ok=True)
    lojas = sorted(LOJAS) if a.loja == "todas" else [a.loja]
    if a.login:
        if a.loja == "todas":
            return print("escolha a loja: --loja magalu --login") or 1
        return login(a.loja)
    if a.check:
        return 0 if all(checar_sessao(l, a.visivel) for l in lojas) else 1
    cods = [c.strip() for c in a.codigos.split(",") if c.strip()] or None
    return executar(lojas, cods, a.forcar, a.visivel, not a.no_notify)


if __name__ == "__main__":
    sys.exit(main())
