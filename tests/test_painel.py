"""Painel (painel/src/logica.js, as regras do painel React): roda montaPainel() no Node e confere o modelo de tela.

Cobre:
- F6: Zoom/Buscapé é agregador; a linha dele some quando a loja tem fonte direta, não vira "Melhor preço agora",
  não entra no "Menor já visto" nem no gráfico dessa loja; vendedor 1P ("Magalu", "Amazon.com.br") conta como a loja.
- F11: a coluna "Visto" mostra o horário do próprio modo (latest_<modo>.atualizado) e linhas de modo parado há
  mais de 6 h ficam marcadas como antigas e fora do "Melhor preço agora".
- REG-1: o limite de "antigo" (6 h) fica acima do intervalo real entre coletas da nuvem (o GitHub espaça o cron
  para ~1 execução a cada 4 h; intervalos de até ~5,1 h observados), então o monitor rodando no ritmo normal
  não tira o menor preço do destaque.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

LOGICA = Path(__file__).resolve().parent.parent / "painel" / "src" / "logica.js"
NODE = shutil.which("node")

# Harness: importa a lógica do painel no Node, roda montaPainel() com os arquivos de docs/data e devolve o modelo de
# tela (o que os componentes React desenham) e as datas formatadas pelo próprio Node.
HARNESS = r"""
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const [logicaPath, dadosPath] = process.argv.slice(2);
const dados = JSON.parse(fs.readFileSync(dadosPath, 'utf8'));
const arq = dados.arquivos;
const saida = {erro: null};
try {
  const {montaPainel} = await import(pathToFileURL(logicaPath).href);
  saida.vm = montaPainel({cloud: arq['data/latest_cloud.json'] ?? null, pc: arq['data/latest_pc.json'] ?? null,
    csvCloud: arq['data/historico_cloud.csv'] ?? '', csvPc: arq['data/historico_pc.csv'] ?? ''}, Date.parse(dados.agora));
} catch (e) { saida.erro = String((e && e.stack) || e); }
const fmtData = s => new Date(s).toLocaleString('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
saida.datas = Object.fromEntries((dados.formatar || []).map(s => [s, fmtData(s)]));
process.stdout.write(JSON.stringify(saida));
"""


def _js(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def achata(vm: dict) -> dict:
    """As chaves de sempre dos testes (os cartões da 55C6K e da 65C6K, as tabelas, os gráficos) a partir do modelo."""
    out = {"graficos": {}}
    for fam in vm["familias"]:
        for p in fam["produtos"]:
            if p["grafico"]:
                out["graficos"]["chart-" + p["id"]] = p["grafico"]
    tvs = vm["tvs"]
    if tvs:
        m55, m65 = tvs["modelos"]["55C6K"], tvs["modelos"]["65C6K"]
        for k, d in m55["destaques"].items():   # melhor, melhor_s, parc, parc_s, min, min_s
            out[k], out[k + "_s"] = d["v"], d["s"]
        for k, d in m65["destaques"].items():   # f65-melhor, f65-melhor-s...
            out["f65-" + k], out["f65-" + k + "-s"] = d["v"], d["s"]
        out["tabela"], out["tabela65"] = _js(m55["linhas"]), _js(m65["linhas"])
        out["serie"], out["alvo"] = m55["serie"], m55["alvo"]
        out["graficos"]["chart-65"] = {"serie": m65["serie"], "alvo": m65["alvo"]}
        out["f-dif-pix"], out["f-dif-pix-s"] = tvs["dif"]["pix"]["v"], tvs["dif"]["pix"]["s"]
        out["f-dif-parc"], out["f-dif-parc-s"] = tvs["dif"]["parc"]["v"], tvs["dif"]["parc"]["s"]
        out["alvo-pix"], out["alvo-parc"] = tvs["alvos"]["55C6K"]["pix"], tvs["alvos"]["55C6K"]["parcelado"]
        out["alvo-pix-65"], out["alvo-parc-65"] = tvs["alvos"]["65C6K"]["pix"], tvs["alvos"]["65C6K"]["parcelado"]
        out["comparar"] = tvs["comparar"]
    out["l-posts"], out["l-cupons"] = _js(vm["posts"]), _js(vm["cupons"])
    return out

AGORA = "2026-09-18T14:40:00-03:00"
CLOUD_AT = "2026-09-18T11:48:36-03:00"   # 2h51 antes de AGORA: ainda vale
PC_AT = "2026-09-18T14:37:35-03:00"
PC_PARADO = "2026-09-18T08:00:00-03:00"  # 6h40 antes de AGORA: antigo (limite de 6 h)

URL_ZOOM = "https://www.zoom.com.br/tv/smart-tv-mini-led-55-tcl-4k-55c6k?highlightedItemId="
URL_MAGALU = "https://www.magazineluiza.com.br/smart-tv-55-tcl-4k-uhd-miniled-55c6k/p/240162700/et/elit/"
URL_AMAZON = "https://www.amazon.com.br/dp/B0F7JZMVKF"


def oferta(fonte, loja, preco, preco_pix=None, vendedor=None, parcelado=None, extra=None, url=None, oid=None):
    """Mesmo formato de Oferta.to_dict() gravado em latest_<modo>.json (amostras copiadas dos latest de 18/09)."""
    oid = oid or f"{loja}-{preco}"
    return {
        "fonte": fonte, "tipo": "loja", "loja": loja, "titulo": "Smart TV TCL 55C6K", "url": url or f"https://{fonte}.example/{oid}",
        "id": oid, "preco": preco, "preco_pix": preco_pix, "parcelado": parcelado, "cupom": None, "publicado": None,
        "ativo": True, "vendedor": vendedor, "extra": extra or {}, "chave": f"{fonte}:{oid}",
        "melhor_preco": min(v for v in (preco, preco_pix) if v),
    }


def latest(modo, atualizado, ofertas, minimo=None):
    return {"modo": modo, "atualizado": atualizado, "alvo_pix": 2900.0, "alvo_parcelado": 3000.0, "minimo": minimo,
            "ofertas_loja": ofertas, "posts": [], "cupons": [], "saude": {}}


def ofertas_cloud_hoje():
    # Trecho do latest_cloud.json de 18/09: o Zoom repete Amazon/Magalu/KaBuM! que já têm fonte direta.
    return [
        oferta("zoom", "Amazon", 3279.0, url=URL_ZOOM + "1489104908", oid="1489104908"),
        oferta("zoom", "Magazine Luiza", 3561.55, url=URL_ZOOM + "1484766165", oid="1484766165"),
        oferta("magalu", "Magazine Luiza", 3749.0, 3561.55, vendedor="Magalu", parcelado="10x R$ 374,90 sem juros",
               extra={"preco_de": 4199.0, "1p": True}, url=URL_MAGALU),
        oferta("zoom", "KaBuM!", 3749.0, url=URL_ZOOM + "1572257841", oid="1572257841"),
        oferta("kabum", "KaBuM!", 4184.88, parcelado="10x de R$ 418,48 sem juros"),
        # loja que só o agregador cobre: continua aparecendo
        oferta("zoom", "Carrefour", 3899.0, url=URL_ZOOM + "1", oid="1"),
    ]


def ofertas_pc_hoje():
    return [
        oferta("amazon", "Amazon", 3749.0, vendedor="Magalu.", parcelado="12x R$ 312,49 sem juros", url=URL_AMAZON),
        oferta("casasbahia", "Casas Bahia", 3599.09, vendedor="Casas Bahia"),
    ]


CAB = "quando,fonte,tipo,loja,vendedor,titulo,preco,preco_pix,parcelado,cupom,url\n"
CSV_CLOUD = CAB + (
    f"2026-09-17T12:00:00-03:00,zoom,loja,Amazon,,TV,3279.0,,,,{URL_ZOOM}1489104908\n"
    f"2026-09-17T12:00:00-03:00,magalu,loja,Magazine Luiza,Magalu,TV,3749.0,3561.55,\"10x R$ 374,90 sem juros\",,{URL_MAGALU}\n"
    f"2026-09-17T12:00:00-03:00,zoom,loja,Carrefour,,TV,3899.0,,,,{URL_ZOOM}1\n"
    f"2026-09-18T11:48:36-03:00,zoom,loja,Amazon,,TV,3279.0,,,,{URL_ZOOM}1489104908\n"
    f"2026-09-18T11:48:36-03:00,magalu,loja,Magazine Luiza,Magalu,TV,3749.0,3561.55,\"10x R$ 374,90 sem juros\",,{URL_MAGALU}\n"
)
CSV_PC = CAB + (
    f"2026-09-17T13:00:00-03:00,amazon,loja,Amazon,Magalu.,TV,4034.5,,\"12x R$ 336,21 sem juros\",,{URL_AMAZON}\n"
    f"2026-09-18T14:37:35-03:00,amazon,loja,Amazon,Magalu.,TV,3749.0,,\"12x R$ 312,49 sem juros\",,{URL_AMAZON}\n"
)

MIN_MAGALU = {"preco": 2991.6, "loja": "Magazine Luiza", "quando": "2026-09-14T21:04:38-03:00",
              "url": "https://www.magazineluiza.com.br/smart-tv-4k-tcl-qd-mini-led-55/p/kb7d86eh39/et/elit/", "titulo": "TV"}
MIN_AMAZON = {"preco": 3199.0, "loja": "Amazon", "quando": "2026-09-14T21:08:06-03:00", "url": URL_AMAZON, "titulo": "TV"}


def roda_painel(tmp_path, cloud, pc, csv_cloud=CSV_CLOUD, csv_pc=CSV_PC, formatar=(), agora=None):
    if not NODE:
        pytest.skip("node não encontrado no PATH")
    return roda_modelo(tmp_path, {"data/latest_cloud.json": cloud, "data/latest_pc.json": pc,
                                  "data/historico_cloud.csv": csv_cloud, "data/historico_pc.csv": csv_pc},
                       agora or AGORA, formatar)


def roda_modelo(tmp_path, arquivos: dict, agora: str, formatar=()) -> dict:
    """Roda montaPainel() no Node com os arquivos de docs/data; devolve as chaves achatadas, o modelo ('vm') e 'datas'."""
    if not NODE:
        pytest.skip("node não encontrado no PATH")
    harness = tmp_path / "painel_harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8")
    dados = tmp_path / "dados.json"
    dados.write_text(json.dumps({"agora": agora, "formatar": list(formatar), "arquivos": arquivos},
                                ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([NODE, str(harness), str(LOGICA), str(dados)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    s = json.loads(p.stdout)
    assert s["erro"] is None, s["erro"]
    return {**achata(s["vm"]), "vm": s["vm"], "datas": s["datas"]}


def linhas(tabela: str) -> list[dict]:
    """As linhas da tabela de ofertas (JSON do modelo), cada uma com 'html' = o texto todo da linha para buscas."""
    return [{**l, "html": _js(l)} for l in json.loads(tabela)]


def brl(v: float) -> str:
    inteiro, cent = f"{v:,.2f}".split(".")
    return "R$ " + inteiro.replace(",", ".") + "," + cent


# ---------------- F6: agregador x fonte direta ----------------

def test_f6_zoom_nao_vira_melhor_preco_quando_a_loja_tem_fonte_direta(tmp_path):
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_AT, ofertas_pc_hoje(), MIN_AMAZON))
    # antes: "R$ 3.279,00" (preço parado do Zoom para a Amazon)
    assert out["melhor"] == brl(3561.55), out["melhor"]
    assert out["melhor_s"].startswith("Magazine Luiza")
    ls = linhas(out["tabela"])
    zoom = [(l["loja"], l["fonte"]) for l in ls if l["fonte"] == "zoom"]
    assert zoom == [("Carrefour", "zoom")], f"linhas do agregador para lojas com fonte direta: {zoom}"
    assert "best" in ls[0]["classe"] and ls[0]["fonte"] == "magalu"
    # a mesma oferta 1P da Magalu (3.561,55) aparecia duas vezes (via zoom e via magalu)
    assert sum(1 for l in ls if brl(3561.55) in l["html"]) == 1
    assert {l["loja"] for l in ls} == {"Magazine Luiza", "Casas Bahia", "Amazon", "Carrefour", "KaBuM!"}


def test_f6_grafico_ignora_zoom_da_loja_com_fonte_direta(tmp_path):
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_AT, ofertas_pc_hoje(), MIN_AMAZON))
    serie = out["serie"]
    # antes: a série "Amazon" ficava travada em 3.279 (mínimo do dia entre Zoom e Amazon direta)
    assert serie["Amazon"] == {"2026-09-17": 4034.5, "2026-09-18": 3749.0}
    assert serie["Magazine Luiza"] == {"2026-09-17": 3561.55, "2026-09-18": 3561.55}
    assert serie["Carrefour"] == {"2026-09-17": 3899.0}, "loja só vista no agregador continua no gráfico"


def test_f6_menor_ja_visto_nao_usa_minimo_do_agregador(tmp_path):
    min_zoom = {"preco": 2899.0, "loja": "Amazon", "quando": "2026-09-15T10:00:00-03:00",
                "url": URL_ZOOM + "1489104908", "titulo": "TV"}
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), min_zoom),
                      latest("pc", PC_AT, ofertas_pc_hoje(), MIN_AMAZON))
    # antes: "R$ 2.899,00 · Amazon" vindo do Zoom
    assert out["min"] == brl(3199.0), out["min"]
    assert out["min_s"].startswith("Amazon")
    # sem outro mínimo válido: recalcula pelo histórico do modo só com linhas válidas (Magalu 3.561,55)
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), min_zoom),
                      latest("pc", PC_AT, ofertas_pc_hoje(), None))
    assert out["min"] == brl(3561.55), out["min"]
    assert out["min_s"].startswith("Magazine Luiza")


def test_f6_agregador_marcado_em_extra_tambem_conta(tmp_path):
    # quando o monitor passar a gravar extra.agregador=True, vale o mesmo, qualquer que seja o nome da fonte
    cloud = [oferta("buscape", "Amazon", 3100.0, extra={"agregador": True}), *ofertas_cloud_hoje()[1:]]
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, cloud, MIN_MAGALU),
                      latest("pc", PC_AT, ofertas_pc_hoje(), MIN_AMAZON))
    assert out["melhor"] == brl(3561.55)
    assert not [l for l in linhas(out["tabela"]) if l["fonte"] == "buscape"]


def test_f6_vendedor_1p_conta_como_a_propria_loja(tmp_path):
    cloud = [
        oferta("magalu", "Magazine Luiza", 3749.0, 3561.55, vendedor="Magalu", url=URL_MAGALU),
        oferta("outra", "Magazine Luiza", 3600.0, vendedor="Magazine Luiza"),
        oferta("outra", "Amazon", 3800.0),
    ]
    pc = [oferta("amazon", "Amazon", 3749.0, vendedor="Amazon.com.br", url=URL_AMAZON),
          oferta("amazon", "Amazon", 3700.0, vendedor="Magalu.", oid="3p")]  # 3P dentro da Amazon: linha própria
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, cloud), latest("pc", PC_AT, pc))
    ls = linhas(out["tabela"])
    assert [l["loja"] for l in ls].count("Magazine Luiza") == 1
    assert [l["loja"] for l in ls].count("Amazon") == 2
    amazon_1p = [l for l in ls if l["loja"] == "Amazon" and "Magalu." not in l["html"]]
    assert len(amazon_1p) == 1 and brl(3749.0) in amazon_1p[0]["html"]


# ---------------- F11: "Visto" por modo e modo parado ----------------

def test_f11_visto_mostra_o_horario_do_proprio_modo(tmp_path):
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_AT, ofertas_pc_hoje(), MIN_AMAZON), formatar=[CLOUD_AT, PC_AT])
    ls = {l["fonte"] + "/" + l["loja"]: l["html"] for l in linhas(out["tabela"])}
    d_cloud, d_pc = out["datas"][CLOUD_AT], out["datas"][PC_AT]
    assert d_cloud != d_pc
    for k in ("magalu/Magazine Luiza", "kabum/KaBuM!", "zoom/Carrefour"):
        assert d_cloud in ls[k] and d_pc not in ls[k], k  # antes: todas com o horário do pc
    for k in ("amazon/Amazon", "casasbahia/Casas Bahia"):
        assert d_pc in ls[k], k
    assert not any(l["velho"] for l in linhas(out["tabela"]))


def test_f11_modo_parado_fica_marcado_e_fora_do_melhor_preco(tmp_path):
    pc = [oferta("casasbahia", "Casas Bahia", 3000.0, vendedor="Casas Bahia"),
          oferta("amazon", "Amazon", 3749.0, vendedor="Magalu.", url=URL_AMAZON)]
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_PARADO, pc, MIN_AMAZON), formatar=[PC_PARADO])
    # antes: "R$ 3.000,00" da Casas Bahia coletada há 6h40
    assert out["melhor"] == brl(3561.55), out["melhor"]
    ls = linhas(out["tabela"])
    cb = next(l for l in ls if l["loja"] == "Casas Bahia")
    assert cb["velho"] and cb["visto"] == out["datas"][PC_PARADO]
    assert "best" not in cb["classe"]
    assert [l for l in ls if "best" in l["classe"]][0]["fonte"] == "magalu"
    # o PC parado ainda cobre a Amazon: o Zoom não volta para o lugar dela
    assert not [l for l in ls if l["fonte"] == "zoom" and l["loja"] == "Amazon"]


def test_f11_tudo_parado_nao_tem_melhor_preco(tmp_path):
    out = roda_painel(tmp_path, latest("cloud", "2026-09-18T07:30:00-03:00", ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_PARADO, ofertas_pc_hoje(), MIN_AMAZON))
    assert out["melhor"] == "—"
    ls = linhas(out["tabela"])
    assert not [l for l in ls if l["classe"] == "best"]
    assert ls and all(l["velho"] for l in ls)


def test_f11_visto_nao_cai_no_horario_mais_recente_entre_modos():
    # checagem estática (roda mesmo sem Node): a coluna não usa mais o "ultimo" global como horário da linha
    js = LOGICA.read_text(encoding="utf-8")
    assert "o.ultima_vez || ultimo" not in js


# ---------------- REG-1: limite de "antigo" acima do intervalo real entre coletas ----------------

def _velho_ms_do_painel() -> float:
    js = LOGICA.read_text(encoding="utf-8")
    m = re.search(r"const VELHO_H = ([\d.]+), VELHO_MS = VELHO_H \* 3600e3;", js)
    assert m, "VELHO_H/VELHO_MS não encontrados em painel/src/logica.js"
    return float(m.group(1)) * 3600e3


def test_reg1_limite_de_antigo_cobre_o_intervalo_real_do_cron():
    # checagem estática (roda mesmo sem Node): intervalos de até ~5,1 h entre coletas da nuvem foram observados
    assert _velho_ms_do_painel() == 6 * 3600e3


@pytest.mark.parametrize("agora", [
    "2026-09-18T14:50:00-03:00",  # nuvem com 3h01: antes o destaque ia para a Casas Bahia (R$ 3.599,09, mais caro)
    "2026-09-18T16:54:00-03:00",  # nuvem com 5h05 (maior intervalo observado entre coletas)
    "2026-09-18T17:45:00-03:00",  # nuvem com 5h56 e pc com 3h07: antes "—" / "sem coleta recente"
])
def test_reg1_intervalo_normal_entre_coletas_nao_marca_antigo(tmp_path, agora):
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_AT, ofertas_pc_hoje(), MIN_AMAZON), agora=agora)
    assert out["melhor"] == brl(3561.55), out["melhor"]
    assert out["melhor_s"].startswith("Magazine Luiza"), out["melhor_s"]
    ls = linhas(out["tabela"])
    assert not any(l["velho"] for l in ls)
    assert "best" in ls[0]["classe"] and ls[0]["fonte"] == "magalu"
    assert not [l for l in ls if "velho" in l["classe"]]


def test_reg1_passou_de_6h_continua_antigo(tmp_path):
    # nuvem com 6h05: aí sim é antigo; o destaque vai para o menor preço do modo recente (pc)
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", "2026-09-18T17:40:00-03:00", ofertas_pc_hoje(), MIN_AMAZON),
                      agora="2026-09-18T17:53:36-03:00")
    assert out["melhor"] == brl(3599.09), out["melhor"]
    ls = linhas(out["tabela"])
    antigas = {l["fonte"] + "/" + l["loja"] for l in ls if l["velho"]}
    assert antigas == {"magalu/Magazine Luiza", "kabum/KaBuM!", "zoom/Carrefour"}, antigas


# ---------------- Parcelado: total do parcelamento e "Melhor parcelado agora" (pedido do usuário, 18/09) ----------------

def _parcelado(linha: dict) -> dict:
    """A célula 'Parcelado (total)': {total, texto, melhor} quando dá para somar; senão {texto} como veio."""
    return linha["parc"] or {"total": None, "texto": linha["parcTexto"], "melhor": False}


def test_parcelado_mostra_o_total_e_a_parcela(tmp_path):
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_AT, [ofertas_pc_hoje()[0],
                          oferta("casasbahia", "Casas Bahia", 3998.99, 3599.09, vendedor="Casas Bahia",
                                 parcelado="10x R$ 399,90 sem juros (cartão Casas Bahia)")], MIN_AMAZON))
    cel = {(l["loja"], l["fonte"]): _parcelado(l) for l in linhas(out["tabela"])}
    # Amazon arredonda a parcela: 12 x 312,49 = 3.749,88, mas o total cobrado é o preço do cartão (3.749,00)
    assert cel[("Amazon", "amazon")]["total"] == brl(3749.0) and cel[("Amazon", "amazon")]["texto"] == f"12x {brl(312.49)} sem juros"
    assert cel[("Magazine Luiza", "magalu")]["total"] == brl(3749.0)
    assert cel[("KaBuM!", "kabum")]["total"] == brl(4184.88), "aceita '10x de R$ ...'"
    cb = [c for (l, f), c in cel.items() if l == "Casas Bahia" and c["total"] == brl(3998.99)]
    assert cb and "(cartão Casas Bahia)" in cb[0]["texto"], "a condição do parcelamento continua visível"


def test_parcelado_com_juros_soma_as_parcelas(tmp_path):
    pc = [oferta("amazon", "Amazon", 3749.0, vendedor="Magalu.", parcelado="12x R$ 350,00", url=URL_AMAZON)]
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, []), latest("pc", PC_AT, pc))
    cel = _parcelado(linhas(out["tabela"])[0])
    assert cel["total"] == brl(4200.0) and "sem juros" not in cel["texto"]
    assert out["parc"] == brl(4200.0)


def test_parcelado_nao_usa_pix_gravado_como_cartao(tmp_path):
    # dado antigo (antes do commit 3e15985): preço do Pix gravado no campo do cartão
    pc = [oferta("amazon", "Amazon", 3374.10, vendedor="Magalu.", parcelado="12x R$ 312,49", url=URL_AMAZON)]
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, []), latest("pc", PC_AT, pc))
    assert out["parc"] == brl(3749.88), out["parc"]


def test_melhor_parcelado_agora(tmp_path):
    cloud = [oferta("magalu", "Magazine Luiza", 3749.0, 3561.55, vendedor="Magalu", parcelado="10x R$ 374,90 sem juros",
                    url=URL_MAGALU),
             oferta("kabum", "KaBuM!", 4184.88, parcelado="10x de R$ 418,48 sem juros"),
             oferta("vtex", "Fast Shop", 3698.0, parcelado="12x R$ 308,17 sem juros (cartão Fast Shop)")]
    pc = [oferta("amazon", "Amazon", 3699.0, 3329.1, vendedor="Magalu.", parcelado="12x R$ 308,25 sem juros", url=URL_AMAZON),
          oferta("casasbahia", "Casas Bahia", 3599.09, vendedor="Casas Bahia")]   # sem parcelamento: não disputa
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, cloud), latest("pc", PC_AT, pc))
    assert out["parc"] == brl(3698.0), out["parc"]
    assert out["parc_s"].startswith("Fast Shop") and "12x" in out["parc_s"] and "cartão Fast Shop" in out["parc_s"]
    # "Melhor à vista" continua sendo o menor preço (Pix), não o parcelado
    assert out["melhor"] == brl(3329.1) and "Pix" in out["melhor_s"]
    fast = [l for l in linhas(out["tabela"]) if l["loja"] == "Fast Shop"][0]
    assert fast["parc"]["melhor"], "selo 'melhor' no parcelado da Fast Shop"
    assert sum(1 for l in linhas(out["tabela"]) if l["parc"] and l["parc"]["melhor"]) == 1


def test_melhor_parcelado_empate_prefere_sem_condicao(tmp_path):
    cloud = [oferta("vtex", "Fast Shop", 3749.0, parcelado="10x R$ 374,90 sem juros (cartão Fast Shop)"),
             oferta("magalu", "Magazine Luiza", 3749.0, 3561.55, vendedor="Magalu", parcelado="10x R$ 374,90 sem juros",
                    url=URL_MAGALU)]
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, cloud), latest("pc", PC_AT, []))
    assert out["parc_s"].startswith("Magazine Luiza"), out["parc_s"]


def test_melhor_parcelado_ignora_modo_antigo_e_agregador(tmp_path):
    cloud = [oferta("zoom", "Carrefour", 2999.0, parcelado="10x R$ 299,90 sem juros", url=URL_ZOOM + "1", oid="1"),
             oferta("magalu", "Magazine Luiza", 3749.0, 3561.55, vendedor="Magalu", parcelado="10x R$ 374,90 sem juros",
                    url=URL_MAGALU)]
    pc = [oferta("amazon", "Amazon", 3000.0, vendedor="Magalu.", parcelado="12x R$ 250,00 sem juros", url=URL_AMAZON)]
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, cloud), latest("pc", PC_PARADO, pc))
    # PC parado há mais de 6 h: a Amazon 3.000 não disputa; o Carrefour só existe no agregador e continua valendo
    assert out["parc"] == brl(2999.0), out["parc"]


def test_sem_parcelamento_informado(tmp_path):
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, [oferta("casasbahia", "Casas Bahia", 3599.09)]),
                      latest("pc", PC_AT, [oferta("amazon", "Amazon", 3749.0, parcelado="em até 12x sem juros", url=URL_AMAZON)]))
    assert out["parc"] == "—" and "parcelamento" in out["parc_s"]
    cel = [_parcelado(l) for l in linhas(out["tabela"]) if l["loja"] == "Amazon"][0]
    assert cel["total"] is None and cel["texto"] == "em até 12x sem juros", "texto que não dá para somar aparece como veio"


# ---------------- Confiança (monitor/confianca.py): caso real de 25/09/2026 ----------------
# O anúncio suspeito da "Importados Lili" (R$ 2.609,01 no Pix) virou o "Melhor à vista" e o "Menor já visto" do painel.
# Reprovado some de tudo (tabela, destaques, mínimo, gráfico), inclusive das linhas antigas do latest/histórico;
# suspeito aparece riscado no fim; vendedor fora da lista de confiáveis ganha um selo.

URL_LILI = ("https://www.magazineluiza.com.br/smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-google-"
            "assistente-4-hdmi-2-usb/p/kc3ca4k960/et/elit/")
REPROVADOS = [{"loja": "Magazine Luiza", "ids": ["importadoslili"], "nomes": ["importadoslili"],
               "anuncios": ["kc3ca4k960", "kd12g2e47k"]}]
MIN_LILI = {"preco": 2609.01, "loja": "Magazine Luiza", "quando": "2026-09-25T20:18:28-03:00", "url": URL_LILI,
            "titulo": "Smart TV 55 TCL 4K UHD MiniLED 55C6K 120Hz Google TV AiPQ Google Assistente 4 HDMI 2 USB"}
LINHAS_LILI = (
    f"2026-09-18T10:18:28-03:00,magalu,loja,Magazine Luiza,Importados Lili,Smart TV 55 TCL,3894.05,2609.01,"
    f"\"10x R$ 389,41 sem juros\",,{URL_LILI}\n")


def _lili_latest():
    # o registro real do latest_cloud de 25/09 (sem veredito: gravado antes da checagem existir)
    return oferta("magalu", "Magazine Luiza", 3894.05, 2609.01, vendedor="Importados Lili",
                  parcelado="10x R$ 389,41 sem juros", url=URL_LILI, oid="kd12g2e47k-importadoslili",
                  extra={"preco_de": 3894.05, "1p": False, "anuncio": "kc3ca4k960", "vendedor_id": "importadoslili"})


def test_confianca_reprovado_some_da_tabela_dos_destaques_do_minimo_e_do_grafico(tmp_path):
    cloud = latest("cloud", CLOUD_AT, [_lili_latest(), *ofertas_cloud_hoje()], MIN_LILI)
    cloud["confianca"] = {"reprovados": REPROVADOS}
    out = roda_painel(tmp_path, cloud, latest("pc", PC_AT, ofertas_pc_hoje(), MIN_AMAZON),
                      csv_cloud=CSV_CLOUD + LINHAS_LILI)
    assert out["melhor"] == brl(3561.55), out["melhor"]     # antes: R$ 2.609,01 (Importados Lili)
    assert "Lili" not in out["tabela"] and "Lili" not in out["parc_s"]
    assert out["min"] == brl(3199.0), out["min"]             # antes: R$ 2.609,01
    assert out["serie"]["Magazine Luiza"] == {"2026-09-17": 3561.55, "2026-09-18": 3561.55}


def test_confianca_lista_de_reprovados_vale_para_o_latest_do_outro_modo(tmp_path):
    """O PC ainda sem a lista (latest antigo) e a nuvem com ela: a lista de um vale para as linhas do outro."""
    cloud = latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU)
    cloud["confianca"] = {"reprovados": REPROVADOS}
    pc = latest("pc", PC_AT, [*ofertas_pc_hoje(), _lili_latest()], MIN_LILI)
    out = roda_painel(tmp_path, cloud, pc, csv_pc=CSV_PC + LINHAS_LILI)
    assert "Lili" not in out["tabela"] and out["min"] == brl(2991.6)


def test_confianca_suspeito_riscado_no_fim_e_vendedor_novo_com_selo(tmp_path):
    sus = oferta("magalu", "Magazine Luiza", 3000.0, 2500.0, vendedor="Loja X", parcelado="10x R$ 300,00 sem juros",
                 oid="kx-lojax", extra={"vendedor_id": "lojax", "confianca": {
                     "veredito": "suspeito", "sinais": ["certificado Anatel 09573-24-00953 não é o da 55C6K"]}})
    novo = oferta("magalu", "Magazine Luiza", 3600.0, 3500.0, vendedor="Loja Boa Eletro", oid="kb-lojaboa",
                  parcelado="10x R$ 360,00 sem juros",
                  extra={"vendedor_id": "lojaboa", "confianca": {"veredito": "sem_risco_aparente",
                                                                 "checagens": ["preço", "Anatel"], "sinais": []}})
    p1 = oferta("magalu", "Magazine Luiza", 3749.0, 3561.55, vendedor="Magalu", parcelado="10x R$ 374,90 sem juros",
                url=URL_MAGALU, extra={"confianca": {"veredito": "confiavel"}})
    cloud = latest("cloud", CLOUD_AT, [sus, novo, p1])
    # o suspeito já vira reprovado automático na mesma rodada: mesmo assim aparece (riscado) até a próxima coleta
    cloud["confianca"] = {"reprovados": [{"loja": "Magazine Luiza", "ids": ["lojax"], "nomes": ["lojax"],
                                          "anuncios": []}]}
    out = roda_painel(tmp_path, cloud, latest("pc", PC_AT, []))
    assert out["melhor"] == brl(3500.0) and "Loja Boa Eletro" in out["melhor_s"]
    assert out["parc"] == brl(3600.0)
    ls = linhas(out["tabela"])
    assert ls[-1]["vendedor"] == "Loja X" and ls[-1]["classe"] == "sus"
    assert ls[-1]["selo"]["tipo"] == "risco" and "09573-24-00953" in ls[-1]["selo"]["titulo"]
    boa = [l for l in ls if l["vendedor"] == "Loja Boa Eletro"][0]
    assert boa["selo"] == {"tipo": "novo", "rotulo": "vendedor novo", "titulo": "checagens: preço, Anatel"}
    assert [l for l in ls if l["vendedor"] == "Magalu"][0]["selo"] is None


# ---- 2ª passada (revisão de 26/09) ----

def test_confianca_reprovado_automatico_com_anuncio_nao_esconde_outro_vendedor_do_mesmo_anuncio(tmp_path):
    """Reprovado automático antigo com o /p/ do buy box (240162700, do Magalu 1P): a linha do 1P, a do CSV e a série
    do gráfico continuam. Anúncio de reprovado automático só vale para linha sem vendedor ou do próprio vendedor."""
    cloud = latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU)
    cloud["confianca"] = {"reprovados": [
        *REPROVADOS,
        {"loja": "Magazine Luiza", "ids": ["lojagolpe"], "nomes": ["lojagolpe"], "anuncios": ["240162700"],
         "origem": "automatico"}]}
    out = roda_painel(tmp_path, cloud, latest("pc", PC_AT, ofertas_pc_hoje()))
    assert [l for l in linhas(out["tabela"]) if l["vendedor"] == "Magalu"]
    assert out["melhor"] == brl(3561.55) and out["melhor_s"].startswith("Magazine Luiza")
    assert out["serie"]["Magazine Luiza"] == {"2026-09-17": 3561.55, "2026-09-18": 3561.55}


def test_confianca_nome_com_ruido_repetido_casa_como_no_python(tmp_path):
    """nomeNorm do painel tira TODAS as ocorrências do ruído, como nome_normalizado() do Python."""
    sus = oferta("amazon", "Amazon", 2500.0, vendedor="Loja X Política de devolução Política de devolução",
                 oid="amz-lojax", url=URL_AMAZON)
    cloud = latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU)
    pc = latest("pc", PC_AT, [*ofertas_pc_hoje(), sus], MIN_AMAZON)
    pc["confianca"] = {"reprovados": [{"loja": "Amazon", "ids": [], "nomes": ["lojax"], "anuncios": []}]}
    out = roda_painel(tmp_path, cloud, pc)
    assert "Loja X" not in out["tabela"] and out["melhor"] == brl(3561.55)


# ---- 3ª passada (2ª revisão de 26/09): rótulo neutro no painel público ----

def test_confianca_selo_do_suspeito_tem_rotulo_neutro(tmp_path):
    """O painel é público e a empresa do anúncio pode ser vítima (conta invadida): o selo diz 'sinais de risco', não
    'suspeito', e os sinais ficam no title."""
    sus = oferta("magalu", "Magazine Luiza", 3000.0, 2500.0, vendedor="Loja X", oid="kx-lojax",
                 extra={"vendedor_id": "lojax", "confianca": {
                     "veredito": "suspeito", "sinais": ["certificado Anatel 09573-24-00953 não é o da 55C6K"]}})
    p1 = oferta("magalu", "Magazine Luiza", 3749.0, 3561.55, vendedor="Magalu", url=URL_MAGALU,
                extra={"confianca": {"veredito": "confiavel"}})
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, [sus, p1]), latest("pc", PC_AT, []))
    (linha,) = [l for l in linhas(out["tabela"]) if "Loja X" in l["html"]]
    assert linha["selo"]["rotulo"] == "sinais de risco" and "suspeito" not in linha["html"]
    assert "09573-24-00953" in linha["selo"]["titulo"]


# ---------------- 65C6K (26/09): uma tabela e um gráfico por modelo, e a coluna "65\" a mais" na mesma loja ----------------

URL_MAGALU_65 = "https://www.magazineluiza.com.br/smart-tv-65-tcl-4k-uhd-miniled-65c6k/p/240162600/et/elit/"


def oferta65(fonte, loja, preco, preco_pix=None, **kw):
    o = oferta(fonte, loja, preco, preco_pix, **kw)
    o.update(modelo="65C6K", titulo="Smart TV TCL 65C6K", id=o["id"] + "-65", chave=o["chave"] + "-65")
    return o


def _latest65(modo, atualizado, ofertas, minimo=None, minimo65=None):
    lt = latest(modo, atualizado, ofertas, minimo)
    lt["alvos"] = {"55C6K": {"pix": 2900.0, "parcelado": 3000.0}, "65C6K": {"pix": 3300.0, "parcelado": 3500.0}}
    lt["minimo_65C6K"] = minimo65
    return lt


def _cloud_com_65():
    return ofertas_cloud_hoje() + [
        oferta65("magalu", "Magazine Luiza", 4799.0, 4559.05, vendedor="Magalu", parcelado="10x R$ 479,90 sem juros",
                 url=URL_MAGALU_65),
        oferta65("vtex", "Webcontinental", 4274.05, 3963.60, vendedor="Casas Bahia", parcelado="8x R$ 534,25 sem juros"),
        oferta65("kabum", "KaBuM!", 4736.0, parcelado="10x de R$ 473,60 sem juros", vendedor="LOJAS COLOMBO"),
    ]


CAB65 = CAB.rstrip("\n") + ",modelo\n"
CSV_CLOUD_65 = CAB65 + CSV_CLOUD[len(CAB):] + (   # linhas antigas (sem a coluna) continuam valendo como 55C6K
    f"2026-09-26T11:00:00-03:00,magalu,loja,Magazine Luiza,Magalu,TV 65,4799.0,4559.05,,,{URL_MAGALU_65},65C6K\n"
    f"2026-09-26T11:00:00-03:00,vtex,loja,Webcontinental,Casas Bahia,TV 65,4274.05,3963.6,,,https://w/p,65C6K\n")


def test_65_tabela_destaques_e_comparacao_na_mesma_loja(tmp_path):
    min65 = {"preco": 3963.6, "loja": "Webcontinental", "quando": "2026-09-26T11:03:00-03:00"}
    out = roda_painel(tmp_path, _latest65("cloud", CLOUD_AT, _cloud_com_65(), MIN_MAGALU, min65),
                      _latest65("pc", PC_AT, ofertas_pc_hoje(), MIN_AMAZON), csv_cloud=CSV_CLOUD_65)
    # a 55C6K continua como antes (as linhas da 65C6K não entram na tabela, no destaque nem no gráfico dela)
    assert out["melhor"] == brl(3561.55)
    assert {l["loja"] for l in linhas(out["tabela"])} == {"Magazine Luiza", "Casas Bahia", "Amazon", "Carrefour", "KaBuM!"}
    assert brl(4559.05) not in out["tabela"]
    assert out["serie"]["Magazine Luiza"] == {"2026-09-17": 3561.55, "2026-09-18": 3561.55}
    # a 65C6K tem os dela, com os alvos dela
    assert out["f65-melhor"] == brl(3963.6) and out["f65-melhor-s"].startswith("Webcontinental (Casas Bahia)")
    assert out["f65-parc"] == brl(4274.05) and out["f65-min"] == brl(3963.6)
    assert (out["alvo-pix"], out["alvo-pix-65"], out["alvo-parc-65"]) == (brl(2900.0), brl(3300.0), brl(3500.0))
    l65 = linhas(out["tabela65"])
    assert [l["loja"] for l in l65] == ["Webcontinental", "Magazine Luiza", "KaBuM!"] and "best" in l65[0]["classe"]
    assert out["graficos"]["chart-65"]["serie"] == {"Magazine Luiza": {"2026-09-26": 4559.05},
                                                     "Webcontinental": {"2026-09-26": 3963.6}}
    assert out["graficos"]["chart-65"]["alvo"] == 3300.0
    # diferença entre os melhores de cada TV
    assert out["f-dif-pix"] == "+" + brl(3963.6 - 3561.55) and "melhor da 65" in out["f-dif-pix-s"]
    # a coluna nova: quanto a 65" custa a mais NA MESMA LOJA (à vista e parcelado)
    # células: [55 à vista, 65 à vista, dif à vista, 55 parcelado, 65 parcelado, dif parcelado]
    v = lambda c: c["v"] if isinstance(c, dict) else (c or "—")   # noqa: E731 (célula de preço ou de diferença)
    comp = {l["loja"]: [v(c) for c in l["celulas"]] for l in out["comparar"]}
    mg = comp["Magazine Luiza"]
    assert mg[0] == brl(3561.55) and mg[1] == brl(4559.05) and mg[2].startswith("+" + brl(4559.05 - 3561.55))
    assert mg[3] == brl(3749.0) and mg[4] == brl(4799.0) and mg[5].startswith("+" + brl(4799.0 - 3749.0))
    assert comp["KaBuM!"][2].startswith("+" + brl(4736.0 - 4184.88))
    webc = comp["Webcontinental"]
    assert webc[0] == "—" and webc[1] == brl(3963.6) and webc[2] == "—", "sem a 55\" na loja, não há diferença"


def test_65_reprovado_e_suspeito_valem_para_a_65(tmp_path):
    lili = oferta65("magalu", "Magazine Luiza", 4559.05, 3054.56, vendedor="Importados Lili",
                    url="https://www.magazineluiza.com.br/x/p/kd12g2e47k/et/elit/?seller_id=importadoslili",
                    extra={"vendedor_id": "importadoslili"})
    cloud = _latest65("cloud", CLOUD_AT, _cloud_com_65() + [lili], MIN_MAGALU)
    cloud["confianca"] = {"reprovados": REPROVADOS}
    out = roda_painel(tmp_path, cloud, _latest65("pc", PC_AT, []))
    assert "Lili" not in out["tabela65"] and "Lili" not in out["comparar"] and out["f65-melhor"] == brl(3963.6)


def test_65_postagem_com_selo_do_modelo(tmp_path):
    cloud = _latest65("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU)
    cloud["posts"] = [{"fonte": "telegram", "tipo": "post", "loja": "Shopee", "titulo": "[canal] Smart TV 65 65C6K",
                       "url": "https://t.me/c/1", "id": "c/1#65C6K", "chave": "telegram:c/1#65C6K", "preco": 3464.0,
                       "melhor_preco": 3464.0, "publicado": "2026-09-18T10:00:00-03:00", "modelo": "65C6K"},
                      {"fonte": "promobit", "tipo": "post", "loja": "Magazine Luiza", "titulo": "Smart TV 55C6K",
                       "url": "https://pb/1", "id": "1", "chave": "promobit:1", "preco": 3261.55,
                       "melhor_preco": 3261.55, "publicado": "2026-09-17T10:00:00-03:00"}]
    out = roda_painel(tmp_path, cloud, _latest65("pc", PC_AT, []))
    chips = [p["chip"] for p in out["vm"]["posts"]]
    assert {"texto": '65"', "classe": "m65"} in chips and {"texto": '55"', "classe": "m55"} in chips


def test_65_sem_dados_da_65_nao_quebra_o_painel(tmp_path):
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_AT, ofertas_pc_hoje(), MIN_AMAZON))
    assert out["f65-melhor"] == "—" and out["f-dif-pix"] == "—" and linhas(out["tabela65"]) == []
    assert out["graficos"]["chart-65"]["serie"] == {}
