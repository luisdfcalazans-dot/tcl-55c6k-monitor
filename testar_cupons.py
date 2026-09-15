"""Testa cupons no carrinho da loja com a sua conta logada e avisa no Telegram quando um funciona.

  python testar_cupons.py --loja magalu --login        # abre o Chrome para VOCÊ fazer login (uma vez)
  python testar_cupons.py --loja magalu                # testa os cupons novos (roda sozinho com a tarefa do PC)
  python testar_cupons.py --loja magalu --codigos ABC,XYZ   # testa códigos específicos
  python testar_cupons.py --loja magalu --forcar       # testa de novo todos os cupons conhecidos
  opções: --no-notify  --visivel (mostra a janela)

O robô nunca avança para pagamento nem digita dados de conta. Só aplica cupom, lê o total e remove.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from run import carrega_env  # noqa: E402

carrega_env()

from monitor import config, notificar  # noqa: E402
from monitor.carrinho import LOJAS, PrecisaLogin, ResultadoCupom, abrir_navegador  # noqa: E402
from monitor.util import agora_iso, fmt_preco, hoje, loja_canonica  # noqa: E402

ARQ_ESTADO = config.DIR_DADOS / "cupons_carrinho.json"
CODIGOS_IGNORAR = {"DIRETO NO LINK", "SEM CUPOM", "LINK"}


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


def codigos_conhecidos(loja_nome: str) -> tuple[list[str], str | None]:
    """Cupons da loja vindos das coletas (Promobit, Pelando, etiquetas do produto, postagens) + extras do .env.
    Devolve (códigos, url do anúncio mais barato da loja)."""
    cods: dict[str, str] = {}
    url_barato, preco_barato = None, 1e9
    for arq in ("latest_cloud.json", "latest_pc.json"):
        d = _json(config.DIR_DADOS / arq)
        for c in d.get("cupons") or []:
            if loja_canonica(c.get("loja", "")) == loja_nome and c.get("codigo"):
                cods.setdefault(c["codigo"].strip().upper(), c.get("fonte", ""))
        for p in d.get("posts") or []:
            if loja_canonica(p.get("loja", "")) == loja_nome and p.get("cupom"):
                cods.setdefault(str(p["cupom"]).strip().upper(), p.get("fonte", ""))
        for o in d.get("ofertas_loja") or []:
            if loja_canonica(o.get("loja", "")) == loja_nome:
                if o.get("cupom"):
                    cods.setdefault(str(o["cupom"]).strip().upper(), "produto")
                mp = o.get("melhor_preco")
                if o.get("ativo", True) and mp and mp < preco_barato and "magazineluiza.com.br" in (o.get("url") or ""):
                    preco_barato, url_barato = mp, o["url"]
    for c in (config.__dict__.get("CUPONS_EXTRA") or []):
        cods.setdefault(c.upper(), "manual")
    import os
    for c in os.environ.get("CUPONS_EXTRA", "").split(","):
        if c.strip():
            cods.setdefault(c.strip().upper(), "manual")
    lista = [c for c in cods if 3 <= len(c) <= 30 and c not in CODIGOS_IGNORAR and " " not in c]
    return lista, url_barato


def msg_resultado(loja_nome: str, r: ResultadoCupom) -> str:
    alvo_pix = r.tv_pix is not None and r.tv_pix <= config.ALVO_PIX
    alvo_parc = r.tv_cartao is not None and r.tv_cartao <= config.ALVO_PARCELADO
    cab = "🎯 META ATINGIDA" if (alvo_pix or alvo_parc) else "✅ Cupom funcionou"
    linhas = [f"{cab} — <b>{loja_nome}</b> · cupom <code>{r.codigo}</code>"]
    if r.tv_pix is not None:
        linhas.append(f"TV no Pix: <b>{fmt_preco(r.tv_pix)}</b>" + (f" (era {fmt_preco((r.extra.get('antes_pix') or 0) - (r.frete or 0))})" if r.extra.get("antes_pix") else ""))
    if r.tv_cartao is not None:
        linhas.append(f"TV no cartão: <b>{fmt_preco(r.tv_cartao)}</b>" + (f" · {r.parcelado}" if r.parcelado else ""))
    if r.frete:
        linhas.append(f"frete: {fmt_preco(r.frete)} (total Pix {fmt_preco(r.total_pix)})")
    if r.desconto:
        linhas.append(f"desconto do cupom: {fmt_preco(r.desconto)}")
    linhas.append("O cupom está aplicado no seu carrinho; é só entrar e finalizar.")
    linhas.append(LOJAS[loja_nome.lower().replace(" ", "")].url_carrinho if loja_nome.lower().replace(" ", "") in LOJAS else "")
    return "\n".join(l for l in linhas if l)


def executar(loja_id: str, codigos: list[str] | None, forcar: bool, visivel: bool, notify: bool) -> int:
    loja = LOJAS[loja_id]
    estado = carrega_estado()
    reg = estado.setdefault(loja_id, {"cupons": {}, "aviso_login": None, "ultima_execucao": None})
    conhecidos, url_barato = codigos_conhecidos(loja.loja_canonica)
    fila = [c.upper() for c in (codigos or conhecidos)]
    testados = reg["cupons"]
    if not forcar and not codigos:
        # novos + aceitos há mais de 1 dia (para detectar expiração)
        fila = [c for c in fila if c not in testados or (testados[c].get("aceito") and (testados[c].get("testado_em") or "")[:10] < hoje())]
    if not fila:
        print(f"[{loja_id}] nada novo para testar ({len(conhecidos)} cupons conhecidos, todos já testados)")
        return 0
    if not loja.perfil().exists():
        print(f"[{loja_id}] perfil não existe. Rode: python testar_cupons.py --loja {loja_id} --login")
        return 0
    if not url_barato:
        url_barato = config.URL_MAGALU_PRODUTO.replace("https://www.magazinevoce.com.br/magazinecanaltechbr", "https://www.magazineluiza.com.br")
    print(f"[{loja_id}] {len(fila)} cupons para testar: {', '.join(fila[:20])}{'…' if len(fila) > 20 else ''}")
    print(f"[{loja_id}] anúncio usado: {url_barato}")

    from playwright.sync_api import sync_playwright

    aceitos: list[ResultadoCupom] = []
    with sync_playwright() as pw:
        ctx = abrir_navegador(pw, loja, visivel)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if not loja.garantir_item(page, url_barato):
                print(f"[{loja_id}] não consegui colocar a TV no carrinho")
                return 1
            base = loja.ler_totais(page)
            print(f"[{loja_id}] carrinho: produtos {fmt_preco(base.produtos)} frete {fmt_preco(base.frete)} "
                  f"Pix {fmt_preco(base.total_pix)} cartão {fmt_preco(base.total_cartao)} · logado={loja.logado(page)}")
            for i, cod in enumerate(fila[:25]):
                try:
                    r = loja.aplicar(page, cod)
                except PrecisaLogin as e:
                    raise
                except Exception as e:  # noqa: BLE001
                    r = ResultadoCupom(codigo=cod, aceito=False, mensagem=f"erro: {type(e).__name__}: {str(e)[:120]}")
                testados[cod] = {
                    "testado_em": agora_iso(), "aceito": r.aceito, "mensagem": r.mensagem[:200],
                    "tv_pix": r.tv_pix, "tv_cartao": r.tv_cartao, "total_pix": r.total_pix, "total_cartao": r.total_cartao,
                    "frete": r.frete, "desconto": r.desconto, "parcelado": r.parcelado,
                }
                print(f"  {'✅' if r.aceito else '✗ '} {cod:<18} {('TV Pix ' + fmt_preco(r.tv_pix)) if r.aceito else r.mensagem[:90]}")
                if r.aceito:
                    aceitos.append(r)
                    loja.remover(page)
                    page.wait_for_timeout(1000)
                if i % 5 == 4:
                    page.wait_for_timeout(3000)  # respiro para não parecer ataque
            page.screenshot(path=str(RAIZ / "logs" / f"carrinho_{loja_id}.png"))
        except PrecisaLogin as e:
            print(f"[{loja_id}] {e}")
            if notify and reg.get("aviso_login") != hoje():
                notificar.enviar(f"🔐 <b>{loja.loja_canonica}</b>: a sessão expirou, não consigo testar cupons.\n"
                                 f"No PC, rode:\n<code>python testar_cupons.py --loja {loja_id} --login</code>")
                reg["aviso_login"] = hoje()
        finally:
            reg["ultima_execucao"] = agora_iso()
            salva_estado(estado)
            ctx.close()

    # o melhor cupom aceito fica aplicado no carrinho para a compra
    if aceitos:
        melhor = min(aceitos, key=lambda r: r.tv_pix or r.tv_cartao or 9e9)
        with sync_playwright() as pw:
            ctx = abrir_navegador(pw, loja, visivel)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                loja.garantir_item(page, url_barato)
                loja.aplicar(page, melhor.codigo)
            except Exception:
                pass
            finally:
                ctx.close()
        for r in sorted(aceitos, key=lambda r: r.tv_pix or r.tv_cartao or 9e9):
            m = msg_resultado(loja.loja_canonica, r)
            if notify:
                notificar.enviar(m)
            else:
                print("[alerta]\n" + m + "\n")
    print(f"[{loja_id}] {len(aceitos)} aceito(s) de {len(fila[:25])} testados")
    return 0


def login(loja_id: str) -> int:
    loja = LOJAS[loja_id]
    from playwright.sync_api import sync_playwright

    print(f"Vai abrir uma janela do Chrome na página de login do {loja.loja_canonica}.")
    print("Faça o login normalmente (e-mail/CPF, senha, código se pedir). Eu não vejo nem guardo esses dados;")
    print("ficam só no perfil do Chrome desta pasta. Quando terminar, volte aqui e aperte Enter.")
    with sync_playwright() as pw:
        ctx = abrir_navegador(pw, loja, visivel=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(loja.url_login, wait_until="domcontentloaded", timeout=60000)
        input("\n>>> Terminou o login? Aperte Enter para continuar... ")
        try:
            page.goto(loja.url_carrinho, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            ok = loja.logado(page)
        except Exception:
            ok = False
        ctx.close()
    if ok:
        print(f"Login salvo. Agora rode: python testar_cupons.py --loja {loja_id} --visivel   (para ver o primeiro teste)")
        return 0
    print("Não detectei a sessão logada. Tente de novo com --login e complete o login antes de apertar Enter.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loja", default="magalu", choices=sorted(LOJAS))
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--codigos", default="")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--visivel", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    a = ap.parse_args()
    (RAIZ / "logs").mkdir(exist_ok=True)
    if a.login:
        return login(a.loja)
    cods = [c.strip() for c in a.codigos.split(",") if c.strip()] or None
    return executar(a.loja, cods, a.forcar, a.visivel, not a.no_notify)


if __name__ == "__main__":
    sys.exit(main())
