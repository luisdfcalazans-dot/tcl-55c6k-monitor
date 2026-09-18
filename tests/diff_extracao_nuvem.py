"""Diferencial do grupo extracao-nuvem: roda as funções da main e as desta branch no MESMO corpus e lista toda
entrada cuja saída muda. Toda diferença tem de ser uma linha da tabela de ouro ou ter um motivo de correção
intencional, conferido por diff_explica.explica(); o que sobra é bug.

Não é coletado pelo pytest (o nome não começa com test_). Uso, na raiz do repositório:

    python tests/diff_extracao_nuvem.py              # resumo + diferenças sem explicação
    python tests/diff_extracao_nuvem.py --todas      # também lista as diferenças explicadas, com o motivo
    python tests/diff_extracao_nuvem.py --base REF   # compara com outro commit (padrão 8e21e6d)

Corpus:
  (a) entradas reais de TODAS as versões de docs/data/latest_*.json e state_*.json no histórico do git (títulos
      de ofertas, postagens e cupons; título e regra dos cupons; texto das postagens do Telegram) e os títulos da
      versão mais nova de docs/data/historico_*.csv;
  (b) entradas sintéticas: tabela de ouro, test_filtro, arquivos de retrabalho das rodadas 1-4 (trechos entre
      aspas simples em todas as strings) e os casos do verificador da rodada 3 (v4n/*.json), quando estão nesta
      máquina;
  (c) páginas reais: prévias t.me salvas (probes/tg*_*.out) e a fixture do Telegram;
  (d) fixtures e snapshots das fontes deste grupo (vtex, zoom, kabum, magalu).
A main é extraída com `git show <base>:<arquivo>` para um diretório temporário e roda num subprocesso.
"""

from __future__ import annotations

import argparse
import csv
import glob
import html as html_mod
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASE_PADRAO = "8e21e6d"
SCRATCH = Path(r"C:\Users\luisd\AppData\Local\Temp\claude\C--Users-luisd-OneDrive--rea-de-Trabalho-promos"
               r"\8294b9c9-bb7f-4112-99fd-4c7e3e9f239b\scratchpad")
ARQS_DADOS = ["latest_cloud.json", "latest_pc.json", "state_cloud.json", "state_pc.json"]


# ================================================================ corpus

def _git(*args: str, entrada: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(RAIZ), *args], input=entrada, capture_output=True, check=True).stdout


def _cat_blobs(blobs: dict[str, str]) -> list[tuple[str, bytes]]:
    if not blobs:
        return []
    out = _git("cat-file", "--batch", entrada=("\n".join(blobs) + "\n").encode())
    res, i = [], 0
    while i < len(out):
        fim = out.index(b"\n", i)
        cab = out[i:fim].decode().split()
        tam = int(cab[2])
        res.append((blobs[cab[0]], out[fim + 1: fim + 1 + tam]))
        i = fim + 1 + tam + 1
    return res


def _blobs_do_historico() -> list[tuple[str, bytes]]:
    """(nome, conteúdo) de toda versão distinta de docs/data/{latest,state}_*.json no histórico."""
    shas = _git("log", "--all", "--format=%H", "--", "docs/data").decode().split()
    blobs: dict[str, str] = {}
    for sha in shas:
        saida = _git("ls-tree", sha, "docs/data/").decode("utf-8", "replace")
        for linha in saida.splitlines():
            meta, _, caminho = linha.partition("\t")
            nome = caminho.rsplit("/", 1)[-1]
            if nome in ARQS_DADOS:
                blobs.setdefault(meta.split()[2], nome)
    return _cat_blobs(blobs)


def _html_canal(linhas: list[str], post: str = "canal/1", ja_html: bool = False) -> str:
    corpo = "<br>".join(linhas if ja_html else [html_mod.escape(l, quote=False) for l in linhas])
    return (f'<div class="tgme_widget_message" data-post="{post}"><div class="tgme_widget_message_text">'
            + corpo + '</div><time datetime="2026-09-18T10:00:00+00:00"></time></div>')


class Corpus:
    def __init__(self) -> None:
        self.itens: dict[str, dict] = {}
        self._vistos: set[tuple] = set()

    def add(self, tipo: str, origem: str, **dados) -> None:
        chave = (tipo, json.dumps(dados, sort_keys=True, ensure_ascii=False))
        if chave in self._vistos:
            return
        self._vistos.add(chave)
        self.itens[f"{tipo}#{len(self.itens):05d}"] = {"tipo": tipo, "origem": origem, **dados}

    def texto_livre(self, texto: str, origem: str) -> None:
        """Um texto sintético entra como título, como texto (cupom/preços/parcela) e como postagem."""
        texto = texto.strip()
        if not texto:
            return
        self.add("titulo", origem, texto=texto)
        self.add("texto", origem, texto=texto)
        self.add("post", origem, html=_html_canal(texto.splitlines()))


def _dados_reais(c: Corpus) -> None:
    for nome, conteudo in _blobs_do_historico():
        try:
            d = json.loads(conteudo)
        except json.JSONDecodeError:
            continue
        origem = f"docs/data/{nome}"
        ofertas = list(d.get("ofertas_loja") or []) + list(d.get("posts") or [])
        if isinstance(d.get("ofertas"), dict):
            ofertas += list(d["ofertas"].values())
        cupons = d.get("cupons") or []
        if isinstance(cupons, dict):
            cupons = list(cupons.values())
        for o in ofertas:
            if o.get("titulo"):
                tit = re.sub(r"^\[[^\]]+\]\s*", "", o["titulo"])  # "[canal] título" das postagens
                c.add("titulo", origem + " (título de oferta)", texto=tit)
            texto = (o.get("extra") or {}).get("texto")
            if texto:
                c.add("texto", origem + " (texto de postagem)", texto=texto)
                c.add("titulo", origem + " (texto de postagem)", texto=texto)
                c.add("post", origem + " (texto de postagem)", html=_html_canal(texto.splitlines()))
        for cp in cupons:
            for campo in ("titulo", "regra"):
                if cp.get(campo):
                    c.add("texto", f"{origem} (cupom: {campo})", texto=cp[campo])
            if cp.get("titulo"):
                c.add("titulo", f"{origem} (cupom: titulo)", texto=cp["titulo"])
    # títulos do histórico (versão mais nova de cada CSV em qualquer ref)
    for nome in ("historico_cloud.csv", "historico_pc.csv"):
        sha = _git("rev-list", "--all", "-1", "--", f"docs/data/{nome}").decode().strip()
        if not sha:
            continue
        bruto = _git("show", f"{sha}:docs/data/{nome}").decode("utf-8", "replace")
        for linha in csv.DictReader(io.StringIO(bruto)):
            if linha.get("titulo"):
                c.add("titulo", f"docs/data/{nome} (título)", texto=re.sub(r"^\[[^\]]+\]\s*", "", linha["titulo"]))


def _paginas_telegram(c: Corpus) -> None:
    from bs4 import BeautifulSoup
    arqs = sorted(glob.glob(str(SCRATCH / "probes" / "tg*_*.out"))) + [str(RAIZ / "tests/fixtures/telegram_ctofertaseletroetv.html")]
    for arq in arqs:
        if not os.path.exists(arq):
            continue
        soup = BeautifulSoup(open(arq, encoding="utf-8", errors="replace").read(), "html.parser")
        for msg in soup.select(".tgme_widget_message[data-post]"):
            el = msg.select_one(".tgme_widget_message_text")
            if not el:
                continue
            post = msg.get("data-post") or "x/0"
            origem = f"t.me real ({Path(arq).name})"
            c.add("post", origem, html=f'<div class="tgme_widget_message" data-post="{post}">{el}</div>')
            for br in el.find_all("br"):
                br.replace_with("\n")
            texto = "\n".join(l.strip() for l in el.get_text(" ").splitlines() if l.strip())
            c.add("texto", origem, texto=texto)
            c.add("titulo", origem, texto=texto)


def _strings(no) -> list[str]:
    if isinstance(no, str):
        return [no]
    if isinstance(no, dict):
        return [s for v in no.values() for s in _strings(v)]
    if isinstance(no, list):
        return [s for v in no for s in _strings(v)]
    return []


def _trechos_entre_aspas(s: str) -> list[str]:
    """Entradas citadas na prosa dos arquivos de retrabalho ('...'). '\\n' escrito na prosa vira quebra de linha
    e a variante com ' / ' vira linhas separadas (o verificador escreve as linhas de uma postagem assim)."""
    out = []
    for m in re.finditer(r"'([^'\n]{4,500})'", s):
        t = re.sub(r"<br\s*/?>", "\n", m.group(1).replace("\\n", "\n"))  # "<br>" citado na prosa = quebra de linha
        if not re.search(r"c6k|r\$|cupom|\d{2}\s*(?:\"|pol)", t, re.I):
            continue
        out.append(t)
        if " / " in t:
            out.append("\n".join(p.strip() for p in t.split(" / ")))
    return out


def _sinteticos(c: Corpus) -> None:
    sys.path.insert(0, str(RAIZ))
    import importlib
    ouro = importlib.import_module("tests.test_tabela_ouro_extracao_nuvem")
    for lista in ("TITULOS", "TITULOS_R4"):
        for i, t, _a in getattr(ouro, lista, []):
            c.add("titulo", f"ouro:{i}", texto=t)
    for lista in ("POSTS", "POSTS_R4"):
        for i, linhas, _e in getattr(ouro, lista, []):
            c.add("post", f"ouro:{i}", html=_html_canal(list(linhas), ja_html=True))
            c.add("texto", f"ouro:{i}", texto="\n".join(linhas))
    for lista in ("UTIL", "UTIL_R4"):
        for i, _f, e, _s in getattr(ouro, lista, []):
            if isinstance(e, str):
                c.add("texto", f"ouro:{i}", texto=e)
    tf = importlib.import_module("tests.test_filtro")
    for t in tf.ACEITA + tf.REJEITA:
        c.add("titulo", "test_filtro", texto=t)
    # arquivos de retrabalho das rodadas 1-4: todas as strings, com os trechos entre aspas simples
    for arq in sorted(glob.glob(str(SCRATCH / "correcoes" / "extracao-nuvem*.json"))):
        bruto = json.load(open(arq, encoding="utf-8"))
        for s in _strings(bruto):
            for t in _trechos_entre_aspas(s):
                c.texto_livre(t, f"retrabalho:{Path(arq).name}")
    # casos do verificador da rodada 3
    for arq in sorted(glob.glob(str(SCRATCH / "v4n" / "*.json"))):
        if not re.fullmatch(r"casos\d+|titulos", Path(arq).stem):
            continue
        for caso in json.load(open(arq, encoding="utf-8")):
            origem = f"verificador r3:{Path(arq).stem}:{caso.get('id')}"
            if caso.get("tipo") == "titulo":
                c.add("titulo", origem, texto=caso["texto"])
            elif caso.get("tipo") == "util":
                c.add("texto", origem, texto=caso["texto"])
            elif caso.get("linhas"):
                c.add("post", origem, html=_html_canal(caso["linhas"], ja_html=True))
                c.add("texto", origem, texto="\n".join(caso["linhas"]))
            elif caso.get("html"):
                c.add("post", origem, html=caso["html"])


def _fontes(c: Corpus) -> None:
    fx = RAIZ / "tests" / "fixtures"
    snap = SCRATCH / "snapshots"
    for parser, arqs in {
        "vtex": [fx / "fastshop_vtex.json", snap / "vtex_fastshop.json", snap / "vtex_lojatcl.json"],
        "zoom": [fx / "zoom_produto.html", snap / "zoom_produto.html"],
        "kabum": [fx / "kabum_api.json", snap / "kabum_api.json"],
        "magalu": [snap / "magalu_busca.html"],
    }.items():
        for a in arqs:
            if a.exists():
                c.add("fonte", str(a.name), parser=parser, arquivo=str(a))


def monta_corpus() -> dict[str, dict]:
    c = Corpus()
    _dados_reais(c)
    _paginas_telegram(c)
    _sinteticos(c)
    _fontes(c)
    return c.itens


# ================================================================ execução (subprocesso, uma raiz por vez)

def _texto_da_postagem(html: str) -> str:
    """O texto que parse_canal vê (na branch: sem o preço riscado)."""
    from bs4 import BeautifulSoup
    el = BeautifulSoup(html, "html.parser").select_one(".tgme_widget_message_text")
    if not el:
        return ""
    for br in el.find_all("br"):
        br.replace_with("\n")
    for riscado in el.find_all(["s", "del", "strike"]):
        riscado.decompose()
    return "\n".join(l.strip() for l in el.get_text(" ", strip=False).splitlines() if l.strip())


def _diag_postagem(filtro, util, texto: str) -> dict:
    """Por que a postagem saiu como saiu (só na branch; na main só o motivo do filtro da mensagem inteira)."""
    d = {"motivo_msg": filtro.motivo_rejeicao(texto)}
    if not hasattr(filtro, "_segmenta"):
        return d
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    tudo = " ".join(filtro.normaliza(l) for l in linhas)
    d["valores"] = util.valores_postagem(texto)
    if not linhas:
        d["rejeicao"] = "vazia"
        return d
    if any(n in tudo for n in filtro._NEGATIVOS_TEXTO_LIVRE):
        d["rejeicao"] = "estado/combo: " + next(n for n in filtro._NEGATIVOS_TEXTO_LIVRE if n in tudo)
        return d
    segs = filtro._segmenta(linhas)
    d["donos"] = sorted({dn for sj in segs for dn, _ in sj})
    d["segs"] = segs
    titulo = filtro._titulo(linhas, segs)
    d["motivos_c6k"] = [filtro.motivo_rejeicao(l) for l in linhas if filtro._RE_C6K.search(filtro.normaliza(l))]
    if not titulo:
        d["rejeicao"] = "sem título da 55C6K"
        return d
    bloco = filtro.bloco_55c6k(texto)
    if bloco is None:
        d["rejeicao"] = "outro produto sem preço da 55C6K" if set(d["donos"]) & {"outro", "disp"} else "abaixo do piso"
    else:
        d["trecho"] = bloco[1]
        d["valores_trecho"] = util.valores_postagem(bloco[1])
    return d


def roda(raiz: str, arq_corpus: str, arq_saida: str) -> None:
    sys.path.insert(0, raiz)
    from monitor import config, regras, util
    from monitor import filtro
    from monitor.sources import telegram_public

    config.ALVO_PIX = 2900.0
    config.ALVO_PARCELADO = 3000.0

    class Est:
        bootstrap = False

        def minimo(self):
            return None

        def oferta_anterior(self, c):
            return None

        def cupom_anterior(self, c):
            return None

    corpus = json.load(open(arq_corpus, encoding="utf-8"))
    out: dict[str, object] = {}
    for k, it in corpus.items():
        try:
            if it["tipo"] == "titulo":
                out[k] = {"aceita": filtro.eh_55c6k(it["texto"]), "motivo": filtro.motivo_rejeicao(it["texto"])}
            elif it["tipo"] == "texto":
                out[k] = {"cupom": util.cupom_no_texto(it["texto"]), "precos": util.precos_no_texto(it["texto"]),
                          "parcelado": util.parcelado_no_texto(it["texto"])}
            elif it["tipo"] == "post":
                res = []
                for o in telegram_public.parse_canal(it["html"], "canal"):
                    o.publicado = None
                    msgs, _ = regras.gerar_alertas(Est(), [o], [])
                    res.append({"id": o.id, "preco": o.preco, "parcelado": o.parcelado, "cupom": o.cupom,
                                "alvo": any("🎯" in m for m in msgs)})
                out[k] = {"ofertas": res, "diag": _diag_postagem(filtro, util, _texto_da_postagem(it["html"]))}
            elif it["tipo"] == "fonte":
                out[k] = _roda_fonte(it["parser"], it["arquivo"])
        except Exception as e:  # noqa: BLE001 — a diferença de exceção também é diferença
            out[k] = f"ERRO {type(e).__name__}: {e}"
    json.dump(out, open(arq_saida, "w", encoding="utf-8"), ensure_ascii=False)


def _roda_fonte(parser: str, arquivo: str) -> list[dict]:
    from monitor.sources import kabum, magalu, vtex, zoom
    bruto = open(arquivo, encoding="utf-8", errors="replace").read()
    if parser == "vtex":
        d = json.loads(bruto)
        for p in d if isinstance(d, list) else []:
            for item in p.get("items") or []:
                for s in item.get("sellers") or []:
                    s.get("commertialOffer", {})["AvailableQuantity"] = 1  # snapshot esgotado: simula estoque
        ofs = vtex.parse_catalogo(d, "Loja", "https://x")
    elif parser == "zoom":
        ofs = zoom.parse_produto(bruto)
    elif parser == "kabum":
        o = kabum.parse_api(json.loads(bruto))
        ofs = [o] if o else []
    else:
        ofs = magalu.parse_busca(bruto)
    return [{"id": o.id, "loja": o.loja, "vendedor": o.vendedor, "preco": o.preco, "preco_pix": o.preco_pix,
             "parcelado": o.parcelado, "agregador": (o.extra or {}).get("agregador")} for o in ofs]


def _extrai_base(base: str, destino: Path) -> None:
    nomes = _git("ls-tree", "-r", "--name-only", base, "monitor").decode().split()
    for nome in nomes:
        alvo = destino / nome
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(_git("show", f"{base}:{nome}"))


# ================================================================ principal

def compara(base: str = BASE_PADRAO) -> tuple[dict, list]:
    """(corpus, diferenças): cada diferença é (chave, item, saída da main, saída da branch, motivo ou None)."""
    corpus = monta_corpus()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _extrai_base(base, tmp / "base")
        arq_corpus = tmp / "corpus.json"
        json.dump(corpus, open(arq_corpus, "w", encoding="utf-8"), ensure_ascii=False)
        saidas = {}
        for lado, raiz in (("main", tmp / "base"), ("branch", RAIZ)):
            arq = tmp / f"{lado}.json"
            r = subprocess.run([sys.executable, __file__, "--rodar", str(raiz), str(arq_corpus), str(arq)],
                               capture_output=True, text=True, encoding="utf-8")
            if r.returncode:
                raise RuntimeError(r.stderr[-4000:])
            saidas[lado] = json.load(open(arq, encoding="utf-8"))
    sys.path.insert(0, str(RAIZ))
    from tests import diff_explica
    difs = []
    for k, it in corpus.items():
        a, b = saidas["main"].get(k), saidas["branch"].get(k)
        if diff_explica.normaliza_saida(it, a) == diff_explica.normaliza_saida(it, b):
            continue
        difs.append((k, it, a, b, diff_explica.explica(it, a, b)))
    return corpus, difs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_PADRAO)
    ap.add_argument("--todas", action="store_true")
    ap.add_argument("--rodar", nargs=3, metavar=("RAIZ", "CORPUS", "SAIDA"))
    ap.add_argument("--json", metavar="ARQ", help="grava as diferenças (com motivo) neste arquivo")
    args = ap.parse_args()
    if args.rodar:
        roda(*args.rodar)
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    corpus, difs = compara(args.base)
    from tests import diff_explica
    por_tipo: dict[str, int] = {}
    for it in corpus.values():
        por_tipo[it["tipo"]] = por_tipo.get(it["tipo"], 0) + 1
    sem = [d for d in difs if not d[4]]
    motivos: dict[str, int] = {}
    for d in difs:
        if d[4]:
            motivos[d[4].split(":")[0]] = motivos.get(d[4].split(":")[0], 0) + 1
    print(f"corpus: {len(corpus)} entradas {por_tipo}")
    print(f"diferenças main x branch: {len(difs)} | explicadas: {len(difs) - len(sem)} | sem explicação: {len(sem)}")
    for m, n in sorted(motivos.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {m}")
    for k, it, a, b, mot in difs:
        if mot and not args.todas:
            continue
        entrada = it.get("texto") or it.get("html") or it.get("arquivo")
        print(f"\n{'OK ' if mot else '!! '}{k} [{it['origem']}] {mot or 'SEM EXPLICAÇÃO'}")
        print("   entrada:", repr(entrada[:300]))
        print("   main   :", json.dumps(diff_explica.normaliza_saida(it, a), ensure_ascii=False)[:300])
        print("   branch :", json.dumps(diff_explica.normaliza_saida(it, b), ensure_ascii=False)[:300])
    if args.json:
        json.dump([{"k": k, "item": it, "main": a, "branch": b, "motivo": mot} for k, it, a, b, mot in difs],
                  open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 1 if sem else 0


if __name__ == "__main__":
    sys.exit(main())
