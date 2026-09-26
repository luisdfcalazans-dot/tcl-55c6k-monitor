"""Primeira rodada REAL do código novo (PC, 26/09 17:12-17:28), com uma TV de cada modelo no carrinho:

L1  o resumo do carrinho do ML mudou ("Desconto de produtos", frete e total com o valor antigo riscado, total "no Pix")
    e a leitura antiga (janela fixa de 24 linhas) deixava o Total de fora: "Pix — cartão —" na 65C6K;
L2  com o total ilegível o MELIPROMOBIT saiu "aceito" ("TV —"), e dois cupons "aceitos" na 55C6K deixaram a TV no
    mesmo preço: qualquer linha "Desconto" (a do Pix, a "de produtos") contava como cupom;
L3  a Amazon não leu o anúncio da própria Amazon (1P, A1ZZFT5FULY4LN): "a página mostrou o vendedor ?";
L4  o frete do anúncio no carrinho (R$ 278,60 na 55C6K e R$ 395,00 na 65C6K no 1P do ML) tem de entrar no preço.

A fixture tests/fixtures/ml_carrinho_2tvs_2026-09-26.txt é o innerText REAL do carrinho do ML às 17:29 (salvo só
lendo), APARADO: só as duas linhas das TVs e o resumo (sem cabeçalho com nome/endereço, sem rodapé, sem
recomendações). Os textos de 1 TV e com cupom são montados no MESMO formato (texto_carrinho_ml reproduz a fixture).
Nenhum navegador, nenhum perfil de carrinho.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest

from monitor import config
from monitor.carrinho import Amazon, MercadoLivre, ResultadoCupom, ler_resumo_ml, medir_cupom
from test_testador_anuncios import FIXO, _iso, _rec, amb, tc  # noqa: F401 - amb: fixture do testador

FIXTURE = Path(__file__).parent / "fixtures" / "ml_carrinho_2tvs_2026-09-26.txt"
TEXTO_REAL = FIXTURE.read_text(encoding="utf-8")

ML55, ML65 = "MLB5417889802", "MLB5446673958"      # 1P do ML de cada modelo (os dois no carrinho em 26/09)
ML_MAGALU55 = "MLB7574364080"                      # a Loja oficial Magalu no catálogo da 55C6K (frete grátis)
TITULO = {"55C6K": "Smart Tv Tcl 55 Polegadas Qd-mini Led 4k C6k Wifi Bluetooth Google Tv 4 Hdmi 144hz Hdr10+ 55c6k",
          "65C6K": "Smart Tv Tcl 65 Polegadas Qd-mini Led 4k C6k Wifi Bluetooth Google Tv 4 Hdmi 144hz Hdr10+ 65c6k"}
# cada TV no carrinho de 26/09: preço riscado da linha, selo de desconto, Pix da linha, "Desconto de produtos" dela e
# o frete dela SOZINHA no carrinho (o log da rodada: 55C6K R$ 278,60; 65C6K R$ 395,00)
TV = {"55C6K": {"lista": 3599.0, "off": None, "pix": 3491.03, "desc_produtos": 0.0, "frete": 278.60},
      "65C6K": {"lista": 4699.0, "off": "11% OFF", "pix": 4151.51, "desc_produtos": 235.01, "frete": 395.00}}
FRETE_DAS_DUAS = (632.0, 203.99)                   # riscado, cobrado (as duas TVs juntas)


# ------------------------------------------------------------------------------------------------
# o carrinho do ML no formato real (innerText), com 1 ou 2 TVs e com o efeito de um cupom
# ------------------------------------------------------------------------------------------------

def _dinheiro(v: float, negativo: bool = False) -> list[str]:
    """'R$' / '3.491' / ',' / '03' como o innerText do ML (sem centavos quando é redondo)."""
    c = int(round(v * 100))
    linhas = (["-"] if negativo else []) + ["R$", f"{c // 100:,}".replace(",", ".")]
    return linhas + ([",", f"{c % 100:02d}"] if c % 100 else [])


def texto_carrinho_ml(modelos: list[str], cupom: tuple | None = None, recomendacoes: bool = False) -> str:
    """innerText do carrinho do ML com estas TVs (1 unidade cada), no formato real de 26/09.

    `cupom`: ('tv', código, valor) -> linha "Cupom <código>" e o total cai; ('frete', código, frete novo) -> o frete
    cai (o antigo fica riscado); None -> sem cupom."""
    tvs = [TV[m] for m in modelos]
    out: list[str] = []
    for m in modelos:
        t = TV[m]
        out += [TITULO[m], TITULO[m], "Não há mais unidades desse produto no seu carrinho.",
                "Você atingiu a quantidade máxima disponível.", "1 undefined", "Excluir", "1", "Adicionar",
                "Você pode comprar até 1 un."]
        out += _dinheiro(t["lista"]) + ([t["off"]] if t["off"] else []) + _dinheiro(t["pix"]) + ["no Pix"]
    riscado, frete = FRETE_DAS_DUAS if len(modelos) == 2 else (None, tvs[0]["frete"])
    if cupom and cupom[0] == "frete":
        riscado, frete = frete, cupom[2]
    linhas_frete = (_dinheiro(riscado) if riscado else []) + (_dinheiro(frete) if frete else ["Grátis"])
    out += ["Frete"] + linhas_frete
    if frete:
        out.append("Não é possível oferecer frete grátis no seu carrinho devido ao peso, tamanho ou distância, mas "
                   "aproveite o frete e adicione mais produtos .")
    out += ["Produtos FULL", "Ver produtos", "Resumo da compra"]
    produtos = sum(t["lista"] for t in tvs)
    desc_prod = round(sum(t["desc_produtos"] for t in tvs), 2)
    desc_cupom = cupom[2] if cupom and cupom[0] == "tv" else 0.0
    cartao = round(produtos - desc_prod - desc_cupom + frete, 2)
    pix = round(sum(t["pix"] for t in tvs) - desc_cupom + frete, 2)
    bruto = round(produtos + (riscado or frete), 2)
    out += ["Produto" if len(modelos) == 1 else f"Produtos ({len(modelos)})"] + _dinheiro(produtos)
    if desc_prod:
        out += ["Desconto de produtos"] + _dinheiro(desc_prod, negativo=True)
    out += ["Frete"] + linhas_frete
    out += [f"Cupom {cupom[1]}"] + _dinheiro(desc_cupom, negativo=True) if desc_cupom else ["Inserir código do cupom"]
    out += ["Desconto no Pix"] + _dinheiro(round(cartao - pix, 2), negativo=True)
    out += ["Total"] + _dinheiro(bruto) + [" "] + _dinheiro(pix) + ["no Pix"]
    out += ["Economize "] + _dinheiro(round(bruto - pix, 2)) + [f"Economize R$ {bruto - pix:.2f}",
                                                                f"Continuar ({len(modelos)})"]
    if recomendacoes:
        # como no carrinho real: racks e suportes com preço, Pix e parcelado (e até a palavra "Total" e "Frete")
        out += ["Recomendações para você", "Rack com Painel para TV até 85\", com LED, Rodízios e 3 Gavetas",
                "22% OFF", "R$", "2.450", "R$", "1.900", "+1000 vendidos", "no Pix", "ou ", "R$", "2.111",
                " em 10x de R$ 211,20 sem juros", "Frete", "R$", "19", ",", "90", "Desconto", "-", "R$", "50",
                "Total", "R$", "99", "Suporte Tv Tri-articulado Universal 14 A 55 Polegadas", "R$", "56", ",", "30",
                "Frete grátis", "Produtos que te interessaram", "Soundbar Tcl 580w", "R$", "1.614", "no Pix"]
    return "\n".join(out) + "\n"


class _SoTexto:
    def __init__(self, t):
        self.t = t

    def evaluate(self, js):
        return self.t


def test_o_gerador_reproduz_o_carrinho_real():
    # a base dos casos de 1 TV e com cupom é o formato real: com as duas TVs o gerador dá a fixture, linha a linha
    assert texto_carrinho_ml(["55C6K", "65C6K"]) == TEXTO_REAL


def test_fixture_aparada_sem_dado_pessoal():
    t = TEXTO_REAL
    for proibido in ("Enviar para", "Quadra", "Conjunto", "CEP", "@", "Luís", "LH\n", "destination_value",
                     "Recomendações", "Produtos que te interessaram", "CNPJ"):
        assert proibido not in t, proibido
    assert t.startswith(TITULO["55C6K"]) and t.rstrip().endswith("Continuar (2)")


# ------------------------------------------------------------------------------------------------
# L1: leitura do resumo novo (e do antigo), com 1 ou 2 TVs, sem nunca ler as recomendações
# ------------------------------------------------------------------------------------------------

def test_l1_resumo_real_com_as_duas_tvs():
    r = MercadoLivre().ler_totais(_SoTexto(TEXTO_REAL))
    assert (r.quantidade, r.produtos, r.frete) == (2, 8298.0, 203.99), "frete: o valor cobrado, não o riscado (632)"
    assert r.total_pix == 7846.53 and r.pix_real is True, "o Total 'no Pix' (o de R$ 8.930 está riscado)"
    assert r.total_cartao == 8266.98, "cartão = produtos - desconto de produtos + frete = Pix + desconto do Pix"
    assert r.desconto is None, "'Desconto de produtos' e 'Desconto no Pix' não são cupom"
    assert r.extra["desconto_produtos"] == 235.01 and r.extra["desconto_pix"] == 420.45
    assert r.extra["riscados"] == {"frete": 632.0, "total": 8930.0}
    assert "cartao_pelas_linhas" not in r.extra, "as duas contas do cartão batem"
    assert r.parcelado is None


@pytest.mark.parametrize("modelo, pix, cartao, frete", [("55C6K", 3491.03, 3599.0, 278.60),
                                                         ("65C6K", 4151.51, 4463.99, 395.00)])
def test_l1_resumo_com_uma_tv(modelo, pix, cartao, frete):
    # 65C6K sozinha: com "Desconto de produtos" o Total ficava além da janela de 24 linhas ("Pix — cartão —")
    r = ler_resumo_ml(texto_carrinho_ml([modelo]))
    assert (r.quantidade, r.frete, r.pix_real) == (1, frete, True)
    assert (r.tv_pix, r.tv_cartao) == (pix, cartao), "preço de UMA TV, sem o frete"
    assert r.total_pix == round(pix + frete, 2) and r.total_cartao == round(cartao + frete, 2)


def test_l1_recomendacoes_nunca_contam():
    com = texto_carrinho_ml(["55C6K", "65C6K"], recomendacoes=True)
    r = MercadoLivre().ler_totais(_SoTexto(com))
    assert (r.produtos, r.frete, r.total_pix, r.total_cartao, r.desconto, r.parcelado) == \
        (8298.0, 203.99, 7846.53, 8266.98, None, None), "nem o '10x de R$ 211,20' do rack, nem o 'Desconto' dele"
    # sem o "Resumo da compra" (a página mudou de novo): as recomendações continuam fora; sem total, nada é inventado
    sem_resumo = com.replace("Resumo da compra\n", "").split("Produto")[0] + "Recomendações para você\n" + \
        com.split("Recomendações para você\n", 1)[1]
    r2 = ler_resumo_ml(sem_resumo)
    assert r2.total_pix is None and r2.total_cartao is None and r2.desconto is None


def test_l1_as_linhas_do_carrinho_real_sao_as_duas_tvs():
    # o bloco de cada linha (como o JS entrega: links + texto) vira uma TV de cada modelo; recomendação não é linha
    blocos = TEXTO_REAL.split("Frete\n", 1)[0].split(TITULO["65C6K"] + "\n" + TITULO["65C6K"])
    linhas = [{"links": [f"https://produto.mercadolivre.com.br/MLB-{ML55[3:]}-smart-tv"], "texto": blocos[0],
               "excluir": True},
              {"links": [f"https://produto.mercadolivre.com.br/MLB-{ML65[3:]}-smart-tv"],
               "texto": TITULO["65C6K"] + blocos[1], "excluir": True}]
    cl = MercadoLivre.classificar_linhas(linhas, None, ids_modelo={ML55: "55C6K", ML65: "65C6K"})
    assert [(c["modelo"], sorted(c["ids"])) for c in cl] == [("55C6K", [ML55]), ("65C6K", [ML65])]


def test_l1_layout_antigo_continua():
    antigo = ("Resumo da compra\nProduto\nR$ 3.749\nFrete\nGrátis\nInserir código do cupom\nTotal\nR$ 3.749\n"
              "Continuar (1)")
    r = ler_resumo_ml(antigo)
    assert (r.produtos, r.frete, r.total_cartao, r.total_pix, r.pix_real) == (3749.0, 0.0, 3749.0, 3749.0, False)
    em_pedacos = ("Resumo da compra\nProdutos (2)\nR$\n8.338\nFrete\nR$\n278\n,\n60\nCupom DESCONTO100\n-R$ 100\n"
                  "Total\nR$\n8.516\n,\n60\nContinuar (2)")
    r = ler_resumo_ml(em_pedacos)
    assert (r.quantidade, r.produtos, r.frete, r.desconto, r.total_cartao) == (2, 8338.0, 278.6, 100.0, 8516.6)


# ------------------------------------------------------------------------------------------------
# L2: preço ilegível é 'erro'; cupom que só mexe no frete é 'só frete'
# ------------------------------------------------------------------------------------------------

def _r(**kw) -> ResultadoCupom:
    return ResultadoCupom(codigo="X", aceito=False, **kw)


def test_l2_medir_cupom():
    antes = ler_resumo_ml(texto_carrinho_ml(["55C6K"]))
    # 1) o caso do MELIPROMOBIT na 65C6K: depois ilegível -> erro, nunca aceito (nem com linha de desconto)
    ilegivel = _r(produtos=4699.0, frete=395.0, desconto=100.0)
    medir_cupom(antes, ilegivel)
    assert ilegivel.status == "erro" and not ilegivel.aceito
    # 2) a TV no mesmo preço e o frete de 278,60 para 0: só frete (nunca desconto na TV)
    frete = ler_resumo_ml(texto_carrinho_ml(["55C6K"], ("frete", "MELIPROMOBIT", 0.0)))
    medir_cupom(antes, frete)
    assert frete.status == "so_frete" and not frete.aceito and frete.tv_pix == 3491.03
    assert "só frete" in frete.mensagem and frete.extra["antes_frete"] == 278.60
    # 3) nada mudou: recusado (antes, a linha "Desconto no Pix" fazia disto um "aceito" com a TV a R$ 3.599)
    igual = ler_resumo_ml(texto_carrinho_ml(["55C6K"]))
    medir_cupom(antes, igual)
    assert igual.status == "recusado" and igual.mensagem == "sem mudança no preço da TV"
    # 4) cupom de verdade: a TV cai
    tv = ler_resumo_ml(texto_carrinho_ml(["55C6K"], ("tv", "CUPOM100", 100.0)))
    medir_cupom(antes, tv)
    assert tv.status == "aceito" and (tv.tv_pix, tv.tv_cartao, tv.desconto) == (3391.03, 3499.0, 100.0)
    # 5) resposta da loja: recusado, com a mensagem dela
    rec = ler_resumo_ml(texto_carrinho_ml(["55C6K"]))
    medir_cupom(antes, rec, "O cupom não está mais disponível.")
    assert rec.status == "recusado" and rec.mensagem == "O cupom não está mais disponível."
    # 6) o resumo mostra um cupom, mas o preço da TV não caiu: erro (testa de novo), nunca aceito
    estranho = ler_resumo_ml(texto_carrinho_ml(["55C6K"]))
    estranho.desconto = 50.0
    medir_cupom(antes, estranho)
    assert estranho.status == "erro"


class PaginaCarrinhoML:
    """O carrinho do ML (texto real, texto_carrinho_ml) e a página de cupons, para o aplicar/remover REAIS.

    `efeitos`: código -> ('tv', valor) | ('frete', frete novo) | ('nada',) | ('recusa', mensagem da loja) |
    ('some',) (o resumo não carrega depois do cupom)."""

    def __init__(self, modelos: list[str], efeitos: dict):
        self.modelos, self.efeitos = list(modelos), dict(efeitos)
        self.url = ""
        self.cupom = None           # código ativo no carrinho
        self.digitado = None
        self.erro = ""
        self.cliques: list[str] = []

    # navegação
    def goto(self, url, **k):
        self.url = url
        self.erro = "" if "/cupons" in url else self.erro

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        if "stepper" in js:
            return []
        if "/cupons" in self.url:
            return "Cupons\nInserir código do cupom\n" + (self.erro or "")
        ef = self.efeitos.get(self.cupom) if self.cupom else None
        if ef and ef[0] == "some":
            self.cupom = None          # a página não carregou uma vez (e o cupom não ficou)
            return "Carrinho\nAlgo deu errado\n"
        cupom = None
        if ef and ef[0] == "tv":
            cupom = ("tv", self.cupom, ef[1])
        elif ef and ef[0] == "frete":
            cupom = ("frete", self.cupom, ef[1])
        return texto_carrinho_ml(self.modelos, cupom, recomendacoes=True)

    # campo e botões da página de cupons
    def locator(self, sel):
        pagina = self

        class Campo:
            first = None

            def count(self):
                return 1 if "/cupons" in pagina.url else 0

            def fill(self, v):
                pagina.digitado = v

            def press(self, tecla):
                pagina._inserir()

        c = Campo()
        c.first = c
        return c

    def get_by_role(self, role, name=None, **k):
        pagina = self
        remover = bool(name and name.search("remover"))

        class Botao:
            first = None

            def count(self):
                return 1 if "/cupons" in pagina.url and (not remover or pagina.cupom) else 0

            def click(self, timeout=None):
                if remover:
                    pagina.cliques.append("remover")
                    pagina.cupom = None
                else:
                    pagina._inserir()

        b = Botao()
        b.first = b
        return b

    def _inserir(self):
        cod = self.digitado
        self.cliques.append(f"inserir:{cod}")
        ef = self.efeitos.get(cod, ("recusa", "Confira se o cupom está correto"))
        if ef[0] == "recusa":
            self.erro = ef[1]
        else:
            self.cupom = cod


@pytest.mark.parametrize("efeito, status", [(("nada",), "recusado"), (("frete", 0.0), "so_frete"),
                                            (("tv", 150.0), "aceito"), (("some",), "erro"),
                                            (("recusa", "O cupom não está mais disponível."), "recusado")])
def test_l2_aplicar_real_do_ml_na_65(efeito, status):
    # a 65C6K sozinha no carrinho (o caso de 26/09: total ilegível, "✅ MELIPROMOBIT TV —")
    p = PaginaCarrinhoML(["65C6K"], {"MELIPROMOBIT": efeito})
    r = MercadoLivre().aplicar(p, "MELIPROMOBIT")
    assert r.status == status, (r.status, r.mensagem)
    assert r.aceito is (status == "aceito")
    if status == "aceito":
        assert (r.tv_pix, r.tv_cartao, r.frete) == (4001.51, 4313.99, 395.0)
    if status == "so_frete":
        assert (r.tv_pix, r.frete, r.extra["antes_frete"]) == (4151.51, 0.0, 395.0)


SACOLA_ANTES = ("Sua sacola\nProdutos (1):\nR$ 4.124,00\nFrete total\nR$ 166,08\nTotal:\nR$ 4.290,08\n"
                "R$ 3.877,68 no Pix\nou R$ 4.290,08 no cartão\nProdutos recomendados\n")


@pytest.mark.parametrize("depois, status", [
    # cupom na TV: a linha "Cupom" e o total caem
    (SACOLA_ANTES.replace("Total:", "Cupom:\n- R$ 150,00\nTotal:").replace("4.290,08", "4.140,08")
     .replace("3.877,68", "3.727,68"), "aceito"),
    # só o frete (R$ 166,08 -> grátis): o total cai, a TV não
    (SACOLA_ANTES.replace("R$ 166,08", "Grátis").replace("4.290,08", "4.124,00").replace("3.877,68", "3.711,60"),
     "so_frete"),
    # a sacola não carregou depois do cupom: erro, nunca aceito
    ("Sua sacola\nNão conseguimos carregar sua sacola\n", "erro"),
    # nada mudou
    (SACOLA_ANTES, "recusado"),
])
def test_l2_magalu_mede_pelo_preco_da_tv(depois, status):
    from test_carrinho import SacolaCupomForaDoDialogo
    from monitor.carrinho import Magalu

    class Sacola(SacolaCupomForaDoDialogo):
        def evaluate(self, js):
            return depois if self.cliques else SACOLA_ANTES

    r = Magalu().aplicar(Sacola(), "LU250")
    assert r.status == status, (r.status, r.mensagem)
    if status == "aceito":
        assert (r.tv_pix, r.tv_cartao, r.desconto) == (3561.60, 3974.0, 150.0)


def test_l2_carrinho_ja_com_cupom_nao_mede():
    p = PaginaCarrinhoML(["55C6K"], {"VELHO": ("tv", 100.0), "NOVO": ("nada",)})
    p.cupom = "VELHO"     # ficou de antes (o remover falhou)
    r = MercadoLivre().aplicar(p, "NOVO")
    assert r.status == "erro" and "já estava com um cupom" in r.mensagem


def test_l2_registro_aceito_sem_preco_volta_como_erro():
    # como ficou gravado em 26/09 17:2x: MELIPROMOBIT@MLB5446673958 "aceito" com tudo None
    reg = _rec("aceito", FIXO - timedelta(minutes=10), tv_pix=None, tv_cartao=None, total_pix=None, total_cartao=None)
    assert tc.status_do_registro(reg) == "erro" and tc.precisa_testar("MELIPROMOBIT", reg, FIXO)
    # aceite antigo sem os campos (formato de antes): continua aceito
    assert tc.status_do_registro(_rec("aceito", FIXO)) == "aceito"
    sf = _rec("so_frete", FIXO - timedelta(hours=2))
    assert tc.status_do_registro(sf) == "so_frete"
    assert not tc.precisa_testar("MELIPROMOBIT", sf, FIXO) and \
        tc.precisa_testar("MELIPROMOBIT", sf, FIXO + timedelta(hours=23))
    assert not tc.aceito_valido("MELIPROMOBIT", sf, FIXO), "só frete nunca é aceite de desconto na TV"


# ------------------------------------------------------------------------------------------------
# rodada do testador com o adaptador REAL do ML (ler_totais, aplicar, remover) sobre o texto real
# ------------------------------------------------------------------------------------------------

def _url_ml(item: str, modelo: str = "55C6K") -> str:
    return f"https://www.mercadolivre.com.br/p/{config.ML_CATALOGOS[modelo]}?pdp_filters=item_id%3A{item}"


def oferta_ml(item: str, vendedor: str, cartao: float, pix: float | None, modelo: str = "55C6K") -> dict:
    return {"fonte": "mercadolivre", "tipo": "loja", "loja": "Mercado Livre", "ativo": True, "modelo": modelo,
            "titulo": TITULO[modelo], "url": _url_ml(item, modelo), "id": item, "vendedor": vendedor,
            "preco": cartao, "preco_pix": pix, "melhor_preco": min(x for x in (cartao, pix) if x),
            "extra": {"anuncio": item, "item_id": item, "catalogo": config.ML_CATALOGOS[modelo]}}


class MLComTextoReal(MercadoLivre):
    """Adaptador REAL do ML (ler_totais, aplicar, remover, tem_cupom_aplicado); só pôr/tirar TV é falso: o carrinho
    fica com as TVs pedidas e o texto é o do carrinho real (texto_carrinho_ml). `anuncios`: item -> modelo do TV."""

    def __init__(self, pasta, pagina: PaginaCarrinhoML, anuncios: dict, tv_do_item: dict | None = None):
        self.pasta, self.pagina, self.anuncios = pasta, pagina, dict(anuncios)
        self.tv_do_item = dict(tv_do_item or {})     # item -> dados da linha (lista, pix, frete...) quando não é o 1P
        self.no_carrinho: dict = {}                  # modelo -> item
        self.eventos: list[tuple] = []

    def perfil(self):
        return self.pasta

    def _poe(self, item):
        m = self.anuncios[item]
        self.no_carrinho[m] = item
        TV[m] = {**TV_1P[m], **self.tv_do_item.get(item, {})}
        self.pagina.modelos = [x for x in ("55C6K", "65C6K") if x in self.no_carrinho]

    def garantir_item(self, page, url, alvo=None):
        item = (alvo or {}).get("item_id")
        self.eventos.append(("garantir", item))
        self.no_carrinho = {}
        self._poe(item)
        self.item_alvo = item
        return True

    def garantir_itens(self, page, alvos):
        self.eventos.append(("garantir_itens", tuple(a.get("item_id") for a in alvos)))
        for a in alvos:
            self._poe(a.get("item_id"))
        return {a["chave"] for a in alvos}


TV_1P = {m: dict(v) for m, v in TV.items()}


@pytest.fixture
def tv_1p():
    """TV[...] é mudada pelo carrinho falso (anúncio de outro vendedor): volta ao 1P no fim de cada teste."""
    yield
    for m, v in TV_1P.items():
        TV[m] = dict(v)


def _rodar_ml(amb, monkeypatch, loja, estado, ofertas, codigos):
    from contextlib import contextmanager

    amb.latest("pc", ofertas, codigos=codigos, loja="Mercado Livre")

    @contextmanager
    def sessao(l, v):
        yield loja.pagina

    monkeypatch.setattr(tc, "_sessao", sessao)
    return amb.rodar(loja, estado, loja_id="mercadolivre")


def test_rodada_ml_texto_real_grava_so_frete_e_erro_e_o_aceito_com_frete(amb, monkeypatch, tv_1p, capsys):
    pagina = PaginaCarrinhoML(["55C6K", "65C6K"], {"MELIPROMOBIT": ("frete", 0.0), "DESCONTOESPECIAL": ("nada",),
                                                   "SUMIU": ("some",), "CUPOM150": ("tv", 150.0)})
    loja = MLComTextoReal(amb.pasta, pagina, {ML55: "55C6K"})
    ofertas = [oferta_ml(ML55, "Mercado Livre", 3599.0, 3491.03)]
    aceitos, estado = _rodar_ml(amb, monkeypatch, loja, {}, ofertas,
                                ["MELIPROMOBIT", "DESCONTOESPECIAL", "SUMIU", "CUPOM150"])
    assert [e for e in pagina.cliques if e.startswith("inserir")] == [
        "inserir:MELIPROMOBIT", "inserir:DESCONTOESPECIAL", "inserir:SUMIU", "inserir:CUPOM150", "inserir:CUPOM150"], \
        "o CUPOM150 volta no passo final"
    cup = estado["mercadolivre"]["cupons"]
    st = {k.split("@")[0]: v["status"] for k, v in cup.items()}
    assert st == {"MELIPROMOBIT": "so_frete", "DESCONTOESPECIAL": "recusado", "SUMIU": "erro", "CUPOM150": "aceito"}
    assert cup[f"MELIPROMOBIT@{ML55}"]["frete_antes"] == 278.60 and cup[f"MELIPROMOBIT@{ML55}"]["frete"] == 0.0
    assert cup[f"CUPOM150@{ML55}"]["tv_pix"] == 3341.03 and cup[f"CUPOM150@{ML55}"]["frete"] == 278.60
    assert [r.codigo for r in aceitos if r.aceito] == ["CUPOM150"]
    msg = tc.msg_melhor([("Mercado Livre", r) for r in aceitos])
    assert "<b>Melhor à vista</b>: R$ 3.341,03 no Pix + frete R$ 278,60 = R$ 3.619,63" in msg
    assert "🚚 Só frete: <code>MELIPROMOBIT</code>" in msg and "R$ 278,60 → R$ 0,00" in msg
    assert "MELIPROMOBIT</code> na" not in msg.split("🚚")[0], "só frete nunca é o melhor preço da TV"
    # o frete do anúncio sozinho fica no estado para as próximas rodadas (L4)
    assert estado["mercadolivre"]["precos"][ML55]["frete"] == 278.60
    out = capsys.readouterr().out
    assert "🚚 MELIPROMOBIT" in out and "⚠  SUMIU" in out


def test_so_frete_sozinho_vira_mensagem_de_frete_e_nao_de_cupom(amb, monkeypatch, tv_1p):
    pagina = PaginaCarrinhoML(["55C6K"], {"MELIPROMOBIT": ("frete", 0.0)})
    loja = MLComTextoReal(amb.pasta, pagina, {ML55: "55C6K"})
    aceitos, _ = _rodar_ml(amb, monkeypatch, loja, {}, [oferta_ml(ML55, "Mercado Livre", 3599.0, 3491.03)],
                           ["MELIPROMOBIT"])
    msg = tc.msg_melhor([("Mercado Livre", r) for r in aceitos])
    assert msg.startswith("🚚 <b>Cupom só de frete</b>") and "Melhor à vista" not in msg and "META" not in msg


def test_total_ilegivel_nao_gasta_teste(amb, monkeypatch, tv_1p, capsys):
    pagina = PaginaCarrinhoML(["55C6K"], {})
    pagina.evaluate = lambda js: [] if "stepper" in js else "Carrinho\nAlgo deu errado\n"
    loja = MLComTextoReal(amb.pasta, pagina, {ML55: "55C6K"})
    aceitos, estado = _rodar_ml(amb, monkeypatch, loja, {}, [oferta_ml(ML55, "Mercado Livre", 3599.0, 3491.03)],
                                ["MELIPROMOBIT"])
    assert estado["mercadolivre"]["cupons"] == {} and aceitos == [], "o cupom fica pendente, sem registro"
    assert "não consegui ler o total do carrinho" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------
# L4: o anúncio mais barato é o de menor preço COM o frete lido no carrinho
# ------------------------------------------------------------------------------------------------

MAGALU_NO_ML = {"lista": 3749.0, "off": None, "pix": 3749.0, "desc_produtos": 0.0, "frete": 0.0}


def test_l4_o_mais_barato_do_fim_e_o_de_menor_preco_com_frete(amb, monkeypatch, tv_1p, capsys):
    # 1P do ML: R$ 3.491,03 no Pix + frete R$ 278,60 = R$ 3.769,63; Magalu no ML: R$ 3.749 com frete grátis
    pagina = PaginaCarrinhoML(["55C6K"], {})
    loja = MLComTextoReal(amb.pasta, pagina, {ML55: "55C6K", ML_MAGALU55: "55C6K"},
                          tv_do_item={ML_MAGALU55: MAGALU_NO_ML})
    ofertas = [oferta_ml(ML55, "Mercado Livre", 3599.0, 3491.03), oferta_ml(ML_MAGALU55, "Magalu", 3749.0, None)]
    uma_hora = FIXO - timedelta(hours=1)
    estado = {"mercadolivre": {"cupons": {f"CUPOMX@{ML_MAGALU55}": _rec("recusado", uma_hora)}}}
    aceitos, estado = _rodar_ml(amb, monkeypatch, loja, estado, ofertas, ["CUPOMX"])
    # só o 1P tinha cupom pendente: o robô leu o frete dele (278,60) e, no fim, o carrinho vai para a Magalu
    assert loja.eventos == [("garantir", ML55), ("garantir", ML_MAGALU55)]
    assert estado["mercadolivre"]["precos"][ML55]["frete"] == 278.60
    # o anúncio que entrou só no fim também tem o total lido ali (e o frete dele fica gravado)
    assert estado["mercadolivre"]["precos"][ML_MAGALU55]["frete"] == 0.0
    out = capsys.readouterr().out
    assert "Magalu [MLB7574364080] (R$ 3.749,00)" in out
    assert "Magalu [MLB7574364080] no carrinho: R$ 3.749,00 (frete lido)" in out
    # na rodada seguinte a ordem já sai com o frete: a Magalu na frente
    _, anuncios = tc.codigos_conhecidos(loja, estado["mercadolivre"], FIXO)
    assert [(a.chave, a.frete) for a in anuncios] == [(ML_MAGALU55, 0.0), (ML55, 278.60)]
    assert tc.texto_com_frete(anuncios[1].preco, anuncios[1].frete) == "R$ 3.491,03 + frete R$ 278,60 = R$ 3.769,63"
    # frete lido há mais de 72 h não vale mais
    assert tc.codigos_conhecidos(loja, estado["mercadolivre"], FIXO + timedelta(hours=73))[1][0].chave == ML55


def test_l4_cupom_num_anuncio_com_frete_caro_nao_vence_o_frete_gratis(amb, monkeypatch, tv_1p):
    # CUPOM150 deixa o 1P a R$ 3.341,03 no Pix, mas com o frete (R$ 278,60) sai R$ 3.619,63; a Magalu no ML, sem
    # cupom e com frete grátis, sai R$ 3.500 (preço de agora): o carrinho fica com a Magalu, sem cupom
    barata = {**MAGALU_NO_ML, "lista": 3500.0, "pix": 3500.0}
    pagina = PaginaCarrinhoML(["55C6K"], {"CUPOM150": ("tv", 150.0)})
    loja = MLComTextoReal(amb.pasta, pagina, {ML55: "55C6K", ML_MAGALU55: "55C6K"}, tv_do_item={ML_MAGALU55: barata})
    ofertas = [oferta_ml(ML55, "Mercado Livre", 3599.0, 3491.03), oferta_ml(ML_MAGALU55, "Magalu", 3500.0, None)]
    uma_hora = FIXO - timedelta(hours=1)
    estado = {"mercadolivre": {"cupons": {f"CUPOM150@{ML_MAGALU55}": _rec("recusado", uma_hora)},
                               "precos": {ML_MAGALU55: {"vendedor": "Magalu", "url": _url_ml(ML_MAGALU55),
                                                        "tv_pix": 3500.0, "tv_cartao": 3500.0, "frete": 0.0,
                                                        "lido_em": _iso(uma_hora)}}}}
    aceitos, _ = _rodar_ml(amb, monkeypatch, loja, estado, ofertas, ["CUPOM150"])
    assert loja.eventos[-1] == ("garantir", ML_MAGALU55), "o fim vai para o frete grátis, sem cupom"
    (r,) = [x for x in aceitos if x.aceito]
    assert r.codigo == "CUPOM150" and r.extra["pior_a_vista"] is True
    assert tc.msg_melhor([("Mercado Livre", x) for x in aceitos]) == ""


def test_l4_mensagem_mostra_o_frete_e_escolhe_pelo_preco_final():
    caro = ResultadoCupom(codigo="A", aceito=True, frete=278.60, total_pix=3619.63, total_cartao=3727.60,
                          extra={"modelo": "55C6K"})
    gratis = ResultadoCupom(codigo="B", aceito=True, frete=0.0, total_pix=3600.0, total_cartao=3600.0,
                            pix_real=False, extra={"modelo": "55C6K"})
    msg = tc.msg_melhor([("Mercado Livre", caro), ("Magazine Luiza", gratis)])
    assert "<b>Melhor à vista</b>: R$ 3.600,00 na Magazine Luiza com <code>B</code>" in msg, \
        "R$ 3.341,03 + R$ 278,60 = R$ 3.619,63 perde para R$ 3.600 com frete grátis"
    assert "Mercado Livre: R$ 3.341,03 no Pix + frete R$ 278,60 = R$ 3.619,63 (A)" in msg


def test_l4_passo_final_com_as_duas_tvs_mostra_o_frete(amb, monkeypatch, tv_1p, capsys):
    pagina = PaginaCarrinhoML(["55C6K", "65C6K"], {})
    loja = MLComTextoReal(amb.pasta, pagina, {ML55: "55C6K", ML65: "65C6K"})
    ofertas = [oferta_ml(ML55, "Mercado Livre", 3599.0, 3491.03),
               oferta_ml(ML65, "Mercado Livre", 4463.99, 4151.51, "65C6K")]
    _rodar_ml(amb, monkeypatch, loja, {}, ofertas, ["TECH200"])
    out = capsys.readouterr().out
    assert "passo final, sem cupom: 55C6K Mercado Livre [MLB5417889802] (R$ 3.491,03 + frete R$ 278,60 = " \
           "R$ 3.769,63) + 65C6K Mercado Livre [MLB5446673958] (R$ 4.151,51 + frete R$ 395,00 = R$ 4.546,51)" in out
    assert pagina.modelos == ["55C6K", "65C6K"], "termina com uma TV de cada modelo"


# ------------------------------------------------------------------------------------------------
# L3: Amazon lê o anúncio da própria Amazon (1P) pelo merchantID ou pelo nome "Amazon.com.br"
# ------------------------------------------------------------------------------------------------

ASIN = {"55C6K": "B0F7JZMVKF", "65C6K": "B0F7K7B2PD"}


def pagina_1p(modelo: str, pix: float, cartao: float, com_merchant_id: bool = True, nome_no_bloco: bool = False,
              vendedor_link: str | None = None) -> str:
    """Página do anúncio (/dp/<ASIN>?smid=...) no formato da coleta (parse_produto): o 1P não tem link de perfil do
    vendedor; o id vem do campo escondido merchantID do formulário de compra."""
    titulo = TITULO[modelo]
    vend = (f'<a id="sellerProfileTriggerId" href="/gp/help/seller/at-a-glance.html?seller={vendedor_link}">Magalu.</a>'
            if vendedor_link else "")
    bloco = ('<div id="merchantInfoFeature_feature_div"><div class="offer-display-feature-text">'
             '<span class="a-size-small offer-display-feature-text-message">Amazon.com.br</span></div></div>'
             if nome_no_bloco else "")
    mid = ('<form id="addToCart"><input type="hidden" id="merchantID" name="merchantID" value="%s"></form>'
           % (vendedor_link or config.AMAZON_1P_ID)) if com_merchant_id else ""
    reais = f"{pix:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    cartao_txt = f"{cartao:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (f'<html><body><span id="productTitle">{titulo}</span>'
            f'<div id="corePriceDisplay_desktop_feature_div"><span class="a-price"><span class="a-offscreen">'
            f'R$ {reais}</span></span></div>'
            f'<div id="oneTimePaymentPrice_feature_div">à vista no Pix ou NuPay (10% off)</div>'
            f'<div id="best-offer-string-cc">ou R$ {cartao_txt} em até 12x de R$ {cartao / 12:.2f} sem juros</div>'
            f'<div id="availability">Em estoque</div>{vend}{bloco}{mid}</body></html>').replace(
        f"{cartao / 12:.2f}", f"{cartao / 12:.2f}".replace(".", ","))


class PaginaAmazonFalsa:
    """Página da Amazon por URL (ASIN), com locator/inner_text sobre o HTML (BeautifulSoup)."""

    def __init__(self, paginas: dict):
        from bs4 import BeautifulSoup

        self.paginas, self.url, self.visitas = paginas, "", []
        self._bs = BeautifulSoup

    def _html(self):
        asin = re.search(r"/dp/([A-Z0-9]{10})", self.url)
        return self.paginas.get(asin.group(1) if asin else "", "<html></html>")

    def goto(self, url, **k):
        self.url = url
        self.visitas.append(url)

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        return self._bs(self._html(), "html.parser").get_text("\n", strip=True)

    def content(self):
        return self._html()

    def locator(self, sel):
        soup = self._bs(self._html(), "html.parser")
        el = None
        for s in sel.split(","):
            s = s.strip()
            if s.startswith("#") and " " not in s:
                el = soup.select_one(s) if s != "#couponFeature input[type=checkbox]" else None
            if el is not None:
                break

        class Loc:
            first = None

            def count(self):
                return 1 if el is not None else 0

            def inner_text(self):
                return el.get_text(" ", strip=True) if el is not None else ""

        loc = Loc()
        loc.first = loc
        return loc


def test_l3_vendedor_1p_pelo_merchant_id_e_pelo_nome():
    assert Amazon.vendedor_da_pagina(pagina_1p("65C6K", 4219.07, 4624.22)) == (config.AMAZON_1P_ID, "Amazon.com.br")
    so_nome = pagina_1p("65C6K", 4219.07, 4624.22, com_merchant_id=False, nome_no_bloco=True)
    assert Amazon.vendedor_da_pagina(so_nome) == (config.AMAZON_1P_ID, "Amazon.com.br")
    # outro vendedor continua pelo id dele (link de perfil e merchantID)
    magalu = pagina_1p("55C6K", 3699.34, 4099.0, vendedor_link="ACUNARZFR75ET")
    assert Amazon.vendedor_da_pagina(magalu) == ("ACUNARZFR75ET", "Magalu.")
    sem_link = re.sub(r'<a id="sellerProfileTriggerId".*?</a>', "", magalu)
    assert Amazon.vendedor_da_pagina(sem_link) == ("ACUNARZFR75ET", None)


@pytest.mark.parametrize("pedido, pagina, esperado", [
    ({"vendedor_id": "A1ZZFT5FULY4LN", "vendedor": "Amazon.com.br"}, "1p", True),
    ({"vendedor_id": "A1ZZFT5FULY4LN", "vendedor": "Amazon.com.br Política de devolução"}, "1p", True),
    ({"vendedor_id": "A1ZZFT5FULY4LN"}, "1p_so_nome", True),
    ({"vendedor_id": "A1ZZFT5FULY4LN", "vendedor": "Amazon.com.br"}, "magalu", False),
    ({"vendedor_id": "ACUNARZFR75ET", "vendedor": "Magalu."}, "1p", False),
    ({"vendedor_id": "ACUNARZFR75ET", "vendedor": "Magalu."}, "magalu", True),
])
def test_l3_garantir_item_confere_o_1p(pedido, pagina, esperado):
    html = {"1p": pagina_1p("65C6K", 4219.07, 4624.22),
            "1p_so_nome": pagina_1p("65C6K", 4219.07, 4624.22, com_merchant_id=False, nome_no_bloco=True),
            "magalu": pagina_1p("65C6K", 4331.09, 4799.0, vendedor_link="ACUNARZFR75ET")}[pagina]
    p = PaginaAmazonFalsa({ASIN["65C6K"]: html})
    url = f"https://www.amazon.com.br/dp/{ASIN['65C6K']}?smid={pedido['vendedor_id']}"
    assert Amazon().garantir_item(p, url, pedido) is esperado


def test_l3_testador_le_o_1p_dos_dois_modelos(amb, monkeypatch):
    from contextlib import contextmanager

    ofs = []
    for m, pix, cartao in (("55C6K", 3491.03, 3879.0), ("65C6K", 4219.07, 4624.22)):
        ofs.append({"fonte": "amazon", "tipo": "loja", "loja": "Amazon", "ativo": True, "modelo": m,
                    "titulo": TITULO[m], "url": f"https://www.amazon.com.br/dp/{ASIN[m]}?smid={config.AMAZON_1P_ID}",
                    "id": f"{ASIN[m]}-{config.AMAZON_1P_ID}", "vendedor": "Amazon.com.br", "preco": cartao,
                    "preco_pix": pix, "melhor_preco": pix,
                    "extra": {"anuncio": ASIN[m], "asin": ASIN[m], "vendedor_id": config.AMAZON_1P_ID}})
    amb.latest("pc", ofs, loja="Amazon")
    pagina = PaginaAmazonFalsa({ASIN["55C6K"]: pagina_1p("55C6K", 3491.03, 3879.0),
                                ASIN["65C6K"]: pagina_1p("65C6K", 4219.07, 4624.22)})

    @contextmanager
    def sessao(l, v):
        yield pagina

    class AmazonDoTeste(Amazon):
        def perfil(self):
            return amb.pasta

    monkeypatch.setattr(tc, "_sessao", sessao)
    _, estado = amb.rodar(AmazonDoTeste(), {}, loja_id="amazon")
    precos = estado["amazon"]["precos"]
    assert precos[f"{ASIN['55C6K']}-{config.AMAZON_1P_ID}"]["tv_pix"] == 3491.03
    assert precos[f"{ASIN['65C6K']}-{config.AMAZON_1P_ID}"]["tv_pix"] == 4219.07
    assert precos[f"{ASIN['65C6K']}-{config.AMAZON_1P_ID}"]["frete"] is None, "a Amazon não mostra o frete: não é 0"
