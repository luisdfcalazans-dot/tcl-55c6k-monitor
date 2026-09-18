"""Painel (docs/index.html): roda o <script> da página no Node com DOM/fetch falsos e confere o que aparece.

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

INDEX = Path(__file__).resolve().parent.parent / "docs" / "index.html"
NODE = shutil.which("node")

# Harness: executa o script da página num contexto do Node com document/fetch/canvas falsos,
# troca desenha() por um espião (para pegar a série do gráfico) e devolve o que foi renderizado.
HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [htmlPath, dadosPath] = process.argv.slice(2);
const html = fs.readFileSync(htmlPath, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const dados = JSON.parse(fs.readFileSync(dadosPath, 'utf8'));
const saida = {erro: null};
let pronto = false;
const ctx2d = new Proxy({}, {get: (t, k) => (k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; }});
const els = {};
const el = id => (els[id] ??= {textContent: '', innerHTML: '', width: 1060, height: 300, getContext: () => ctx2d});
const document = {getElementById: el, querySelector: el, documentElement: {}};
const fetch = async u => {
  const v = dados.arquivos[String(u).split('?')[0]];
  if (v == null) return {ok: false, json: async () => null, text: async () => ''};
  return {ok: true, json: async () => v, text: async () => (typeof v === 'string' ? v : JSON.stringify(v))};
};
const ctx = vm.createContext({document, fetch, getComputedStyle: () => ({getPropertyValue: () => '#000'}), console});
vm.runInContext('Date.now = () => ' + Date.parse(dados.agora) + ';', ctx);
process.on('unhandledRejection', e => { saida.erro = String((e && e.stack) || e); pronto = true; });
vm.runInContext(scripts[scripts.length - 1], ctx);
ctx.desenha = (serie, alvo) => { saida.serie = JSON.parse(JSON.stringify(serie)); pronto = true; };
const fmtData = s => new Date(s).toLocaleString('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
(async () => {
  for (let i = 0; i < 300 && !pronto; i++) await new Promise(r => setTimeout(r, 10));
  if (!pronto) saida.erro = 'o script não chegou ao gráfico';
  saida.melhor = el('f-melhor').textContent;
  saida.melhor_s = el('f-melhor-s').textContent;
  saida.min = el('f-min').textContent;
  saida.min_s = el('f-min-s').textContent;
  saida.tabela = el('#t-lojas tbody').innerHTML;
  saida.datas = Object.fromEntries((dados.formatar || []).map(s => [s, fmtData(s)]));
  process.stdout.write(JSON.stringify(saida));
})();
"""

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
    harness = tmp_path / "painel_harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    dados = tmp_path / "dados.json"
    dados.write_text(json.dumps({
        "agora": agora or AGORA, "formatar": list(formatar),
        "arquivos": {"data/latest_cloud.json": cloud, "data/latest_pc.json": pc,
                     "data/historico_cloud.csv": csv_cloud, "data/historico_pc.csv": csv_pc},
    }, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([NODE, str(harness), str(INDEX), str(dados)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["erro"] is None, out["erro"]
    return out


def linhas(tabela: str) -> list[dict]:
    """Quebra o <tbody> renderizado em linhas {loja, fonte, classe, html}."""
    out = []
    for tr in re.findall(r"<tr[\s\S]*?</tr>", tabela):
        loja = re.search(r"<b>(.*?)</b>", tr)
        fonte = re.search(r'chip mute">(.*?)<', tr)
        classe = re.search(r'<tr class="([^"]*)"', tr)
        out.append({"loja": loja and loja.group(1), "fonte": fonte and fonte.group(1),
                    "classe": classe.group(1) if classe else "", "html": tr})
    return out


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
    assert "antigo" not in out["tabela"]


def test_f11_modo_parado_fica_marcado_e_fora_do_melhor_preco(tmp_path):
    pc = [oferta("casasbahia", "Casas Bahia", 3000.0, vendedor="Casas Bahia"),
          oferta("amazon", "Amazon", 3749.0, vendedor="Magalu.", url=URL_AMAZON)]
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_PARADO, pc, MIN_AMAZON), formatar=[PC_PARADO])
    # antes: "R$ 3.000,00" da Casas Bahia coletada há 6h40
    assert out["melhor"] == brl(3561.55), out["melhor"]
    ls = linhas(out["tabela"])
    cb = next(l for l in ls if l["loja"] == "Casas Bahia")
    assert "antigo" in cb["html"] and out["datas"][PC_PARADO] in cb["html"]
    assert "best" not in cb["classe"]
    assert [l for l in ls if "best" in l["classe"]][0]["fonte"] == "magalu"
    # o PC parado ainda cobre a Amazon: o Zoom não volta para o lugar dela
    assert not [l for l in ls if l["fonte"] == "zoom" and l["loja"] == "Amazon"]


def test_f11_tudo_parado_nao_tem_melhor_preco(tmp_path):
    out = roda_painel(tmp_path, latest("cloud", "2026-09-18T07:30:00-03:00", ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", PC_PARADO, ofertas_pc_hoje(), MIN_AMAZON))
    assert out["melhor"] == "—"
    assert "best" not in out["tabela"]
    assert out["tabela"].count("antigo") == len(linhas(out["tabela"]))


def test_f11_visto_nao_cai_no_horario_mais_recente_entre_modos():
    # checagem estática (roda mesmo sem Node): a coluna não usa mais o "ultimo" global como horário da linha
    js = INDEX.read_text(encoding="utf-8")
    assert "o.ultima_vez || ultimo" not in js


# ---------------- REG-1: limite de "antigo" acima do intervalo real entre coletas ----------------

def _velho_ms_do_painel() -> float:
    js = INDEX.read_text(encoding="utf-8")
    m = re.search(r"const VELHO_H = ([\d.]+), VELHO_MS = VELHO_H \* 3600e3;", js)
    assert m, "VELHO_H/VELHO_MS não encontrados no index.html"
    return float(m.group(1)) * 3600e3


def test_reg1_limite_de_antigo_cobre_o_intervalo_real_do_cron():
    # checagem estática (roda mesmo sem Node): intervalos de até ~5,1 h entre coletas da nuvem foram observados
    assert _velho_ms_do_painel() == 6 * 3600e3
    assert "coleta com mais de 3 h" not in INDEX.read_text(encoding="utf-8")


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
    assert "antigo" not in out["tabela"]
    ls = linhas(out["tabela"])
    assert "best" in ls[0]["classe"] and ls[0]["fonte"] == "magalu"
    assert not [l for l in ls if "velho" in l["classe"]]


def test_reg1_passou_de_6h_continua_antigo(tmp_path):
    # nuvem com 6h05: aí sim é antigo; o destaque vai para o menor preço do modo recente (pc)
    out = roda_painel(tmp_path, latest("cloud", CLOUD_AT, ofertas_cloud_hoje(), MIN_MAGALU),
                      latest("pc", "2026-09-18T17:40:00-03:00", ofertas_pc_hoje(), MIN_AMAZON),
                      agora="2026-09-18T17:53:36-03:00")
    assert out["melhor"] == brl(3599.09), out["melhor"]
    ls = linhas(out["tabela"])
    antigas = {l["fonte"] + "/" + l["loja"] for l in ls if "antigo" in l["html"]}
    assert antigas == {"magalu/Magazine Luiza", "kabum/KaBuM!", "zoom/Carrefour"}, antigas
    assert 'title="coleta com mais de 6 h"' in out["tabela"]
