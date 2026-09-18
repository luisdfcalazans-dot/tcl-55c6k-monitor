"""Teste de cupons no carrinho, sem navegador: páginas falsas com o que as lojas mostraram em 18/09/2026.

CARR-02 falha do robô não vira recusa; recusa vence em 24 h (cupom de horário: a cada hora)
CARR-03 Mercado Livre: só testa o anúncio 'Melhor preço' do catálogo, conferido no carrinho
CARR-05 o alerta só diz que o cupom ficou no carrinho quando isso foi conferido
CARR-07 Magalu: parcelas do 'Pague com Cartão Magalu' não são o parcelado
CARR-08 quantidade 1 (Magalu pela sacola, ML pelo seletor de quantidade) e 'antes' de UMA TV
"""

import importlib
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from monitor.carrinho import Magalu, MercadoLivre, ResultadoCupom, _SEL_ML_MENOS, ids_ml
from monitor.util import TZ_BR


def _importa_testar_cupons():
    """testar_cupons chama carrega_env() ao ser importado; no teste isso não lê o .env."""
    import run

    original = run.carrega_env
    run.carrega_env = lambda: None
    try:
        return importlib.import_module("testar_cupons")
    finally:
        run.carrega_env = original


tc = _importa_testar_cupons()

SNAPSHOTS = Path(r"C:\Users\luisd\AppData\Local\Temp\claude\C--Users-luisd-OneDrive--rea-de-Trabalho-promos"
                 r"\8294b9c9-bb7f-4112-99fd-4c7e3e9f239b\scratchpad\snapshots")

# ------------------------------------------------------------------------------------------------
# CARR-02: status do teste e fila de re-teste
# ------------------------------------------------------------------------------------------------

AGORA = datetime(2026, 9, 18, 14, 30, tzinfo=TZ_BR)


def _reg(**kw) -> dict:
    return {"testado_em": AGORA.isoformat(timespec="seconds"), **kw}


def test_falha_do_robo_tem_status_erro_e_recusa_da_loja_recusado():
    assert ResultadoCupom("TOMA100", False, "campo de cupom não encontrado", extra={"falha": True}).status == "erro"
    assert ResultadoCupom("X", False, "erro: TimeoutError: Timeout 8000ms exceeded").status == "erro"
    assert ResultadoCupom("X", False, "não consegui ler o total da sacola").status == "erro"
    assert ResultadoCupom("X", False, "Cupom inválido ou expirado").status == "recusado"
    assert ResultadoCupom("X", False, "Cupom não encontrado").status == "recusado", "mensagem da loja é recusa"
    assert ResultadoCupom("X", False, "sem mudança no total").status == "recusado"
    assert ResultadoCupom("X", True).status == "aceito"


def test_registro_antigo_de_campo_nao_encontrado_volta_para_a_fila():
    # como estava gravado em docs/data/cupons_carrinho.json (anúncio kc7h6f4k4b): preso para sempre no HEAD
    antigo = _reg(aceito=False, mensagem="campo de cupom não encontrado")
    assert tc.status_do_registro(antigo) == "erro"
    assert tc.precisa_testar("DIADOCLIENTE14H", antigo, AGORA + timedelta(minutes=30))
    assert tc.precisa_testar("TOMA100", antigo, AGORA + timedelta(minutes=30))
    assert tc.precisa_testar("TOMA100", _reg(status="erro", aceito=False, mensagem="x"), AGORA)


def test_recusa_da_loja_vence_em_24h():
    rec = _reg(status="recusado", aceito=False, mensagem="Cupom inválido")
    assert not tc.precisa_testar("TOMA100", rec, AGORA + timedelta(hours=23))
    assert tc.precisa_testar("TOMA100", rec, AGORA + timedelta(hours=24))
    # registro antigo sem status, com recusa de verdade da loja
    antigo = _reg(aceito=False, mensagem="Cupom inválido")
    assert tc.status_do_registro(antigo) == "recusado"
    assert not tc.precisa_testar("TOMA100", antigo, AGORA + timedelta(hours=1))


def test_cupom_de_horario_recusado_volta_a_cada_hora():
    rec = _reg(status="recusado", aceito=False, mensagem="Cupom inválido")
    assert not tc.precisa_testar("DIADOCLIENTE14H", rec, AGORA + timedelta(minutes=20)), "mesma hora: não repete"
    assert tc.precisa_testar("DIADOCLIENTE14H", rec, AGORA + timedelta(minutes=31)), "15h: testa de novo"
    assert tc.precisa_testar("diadocliente8h", rec, AGORA + timedelta(hours=1))


def test_aceito_e_nunca_testado():
    assert tc.precisa_testar("LU100", None, AGORA)
    ok = _reg(status="aceito", aceito=True)
    assert not tc.precisa_testar("LU100", ok, AGORA + timedelta(hours=2))
    assert tc.precisa_testar("LU100", ok, AGORA + timedelta(days=1))


# ------------------------------------------------------------------------------------------------
# CARR-03 / CARR-08: Mercado Livre
# ------------------------------------------------------------------------------------------------

# trecho do JSON da página do catálogo MLB48808732 em 18/09 (scratchpad/snapshots/mercadolivre_produto.html)
HTML_CATALOGO = (
    '<script>window.__PRELOADED_STATE__={"components":{"buy_box_offers":{"id":"buy_box_offers",'
    '"type":"buy_box_offers","state":"VISIBLE","components_ids":[],"items":['
    '{"selected":false,"type":"BEST_INSTALLMENTS","item_id":"MLB7574364080","title":{"text":"Parcelamento sem juros"},'
    '"components":[{"id":"pdp_filters_change","type":"ui_message","state":"HIDDEN","closeable":false},'
    '{"id":"price","type":"price","state":"VISIBLE","price":{"type":"price","value":3749,"currency_symbol":"R$",'
    '"currency_id":"BRL"},"subtitles":[{"id":"pricing_price_subtitle","text":"10x {price_installments} sem juros",'
    '"values":{"price_installments":{"type":"price","value":374.9,"currency_symbol":"R$"}}},'
    '{"id":"seller","text":"Vendido por Loja oficial Magalu{cockade_icon}"}]}]},'
    '{"selected":true,"type":"BEST_PRICE","item_id":"MLB5417889802","title":{"text":"Melhor preço"},'
    '"components":[{"id":"pdp_filters_change","type":"ui_message","state":"HIDDEN","closeable":false},'
    '{"id":"price","type":"price","state":"VISIBLE","price":{"type":"price","value":3491.03,"original_value":3599,'
    '"currency_symbol":"R$","currency_id":"BRL"}}]}]}}};</script>'
    '<script id="__GTM__">(function(w,l){w[l]=w[l]||[];w[l].push({"pageId":"PDP","itemId":"MLB5417889802",'
    '"signalsItemGroupId":"MLB48808732-product","catalogProductId":"MLB48808732","itemPrice":698.55,'
    '"localItemPrice":3599,"currencyId":"BRL"})})</script>'
)
URL_CATALOGO = "https://www.mercadolivre.com.br/p/MLB48808732"
ALVO = "MLB5417889802"          # 'Melhor preço' (R$ 3.599 / R$ 3.491,03)
PARCELADO = "MLB7574364080"     # 'Parcelamento sem juros' da Loja oficial Magalu (R$ 3.749)
TITULO = "Smart Tv Tcl 55 Polegadas Qled Mini Led 4k C6k Wifi Bluetooth Google Tv 4 Hdmi 144hz 55c6k"


def test_catalogo_ml_escolhe_o_anuncio_melhor_preco():
    alvo = MercadoLivre.anuncio_melhor_preco(HTML_CATALOGO)
    assert alvo["item_id"] == ALVO and alvo["tipo"] == "BEST_PRICE"
    assert set(alvo["precos"]) == {3491.03, 3599.0}
    ofertas = {o["item_id"]: o for o in MercadoLivre.ofertas_do_catalogo(HTML_CATALOGO)}
    assert ofertas[PARCELADO]["precos"] == [3749.0], "a parcela (374,90) não é o preço do anúncio"
    assert ofertas[ALVO]["selecionada"] and not ofertas[PARCELADO]["selecionada"]


@pytest.mark.skipif(not (SNAPSHOTS / "mercadolivre_produto.html").exists(), reason="snapshot de 18/09 ausente")
def test_catalogo_ml_snapshot_completo():
    html = (SNAPSHOTS / "mercadolivre_produto.html").read_text(encoding="utf-8")
    alvo = MercadoLivre.anuncio_melhor_preco(html)
    assert alvo["item_id"] == ALVO and 3599.0 in alvo["precos"]
    assert {o["item_id"] for o in MercadoLivre.ofertas_do_catalogo(html)} == {ALVO, PARCELADO}


def test_ids_ml():
    assert ids_ml("https://produto.mercadolivre.com.br/MLB-7574364080-smart-tv _JM MLB7574364080 MLB1002") == [PARCELADO]


def _totais_ml(texto: str) -> ResultadoCupom:
    return MercadoLivre().ler_totais(_SoTexto(texto))


class _SoTexto:
    def __init__(self, t):
        self.t = t

    def evaluate(self, js):
        return self.t


def _texto_carrinho(linhas: list[dict]) -> str:
    if not linhas:
        return "Carrinho\nSeu carrinho está vazio\nRecomendações para você"
    qtd = sum(l["qtd"] for l in linhas)
    soma = sum(l["preco"] * l["qtd"] for l in linhas)
    rot = "Produto" if qtd == 1 else f"Produtos ({qtd})"
    corpo = "\n".join(f"{l.get('titulo', TITULO)}\n{l['qtd']}\nR$ {l['preco']:,.0f}".replace(",", ".") for l in linhas)
    return (f"Todos os produtos\nProdutos de DAEFCGDHB88564\n{corpo}\nResumo da compra\n{rot}\n"
            f"R$ {soma:,.0f}\nFrete\nGrátis\nInserir código do cupom\nTotal\nR$ {soma:,.0f}\nContinuar ({qtd})"
            ).replace(",", ".")


def test_ml_ler_totais_com_uma_unidade_diz_so_produto():
    # como no print logs/carrinho_mercadolivre.png de 18/09: 'Produto R$ 3.749' (sem o número)
    r = _totais_ml(_texto_carrinho([{"preco": 3749, "qtd": 1}]))
    assert (r.quantidade, r.produtos, r.total_cartao) == (1, 3749.0, 3749.0)
    r2 = _totais_ml(_texto_carrinho([{"preco": 4169, "qtd": 2}]))
    assert (r2.quantidade, r2.produtos, r2.tv_cartao) == (2, 8338.0, 4169.0)


def test_situacao_do_carrinho_ml():
    alvo = MercadoLivre.anuncio_melhor_preco(HTML_CATALOGO)
    ofertas = MercadoLivre.ofertas_do_catalogo(HTML_CATALOGO)

    def sit(linhas_links, carrinho):
        texto = _texto_carrinho(carrinho)
        return MercadoLivre.situacao_do_carrinho(linhas_links, _totais_ml(texto), texto, alvo, ofertas, "MLB48808732")

    uma = [{"preco": 3749, "qtd": 1}]
    # carrinho de 18/09: anúncio de R$ 3.749 e a linha sem id legível -> confere pelo preço
    assert sit([], uma) == "outro"
    assert sit([[URL_CATALOGO]], uma) == "outro", "o id do catálogo não identifica o anúncio"
    assert sit([[f"https://produto.mercadolivre.com.br/MLB-{PARCELADO[3:]}-smart-tv"]], uma) == "outro"
    assert sit([[f"{URL_CATALOGO}?pdp_filters=item_id:{ALVO}"]], [{"preco": 3599, "qtd": 1}]) == "ok"
    assert sit([], [{"preco": 3599, "qtd": 1}]) == "ok"
    assert sit([["https://x/MLB-111111111"], ["https://x/MLB-222222222"]], uma + uma) == "outro"
    assert sit([], []) == "vazio"
    assert sit([], [{"preco": 1999, "qtd": 1}]) == "?", "preço que não é de nenhuma opção: não dá para afirmar"
    recomenda = "Carrinho\nSeu carrinho está vazio\nRecomendações para você\n" + TITULO
    assert MercadoLivre.situacao_do_carrinho([], _totais_ml(recomenda), recomenda, alvo, ofertas) == "vazio"
    ilegivel = "Carrinho\n" + TITULO  # resumo não lido e a TV na tela: não põe outra
    assert MercadoLivre.situacao_do_carrinho([], _totais_ml(ilegivel), ilegivel, alvo, ofertas) == "?"


class _Loc:
    def __init__(self, n=0, ao_clicar=None):
        self.n, self.ao_clicar = n, ao_clicar
        self.first = self

    def count(self):
        return self.n

    def is_visible(self):
        return True

    def click(self, timeout=None):
        if not self.n:
            raise AssertionError("clique em elemento inexistente")
        self.ao_clicar()


class PaginaML:
    """Catálogo + carrinho do ML. Cada linha do carrinho: {'id', 'preco', 'qtd', 'titulo'?}."""

    def __init__(self, carrinho: list[dict], com_id_no_link: bool = True):
        self.carrinho = [dict(l) for l in carrinho]
        self.com_id = com_id_no_link
        self.url = ""
        self.visitas: list[str] = []
        self.cliques: list[str] = []

    def goto(self, url, **k):
        self.url = url
        self.visitas.append(url)

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def _no_carrinho(self):
        return "/gz/cart" in self.url

    def content(self):
        return HTML_CATALOGO if "/p/" in self.url else "<html></html>"

    def evaluate(self, js):
        if "stepper" in js:  # links de cada linha
            if not self._no_carrinho():
                return []
            return [[f"https://produto.mercadolivre.com.br/MLB-{l['id'][3:]}-tv" if self.com_id else URL_CATALOGO]
                    for l in self.carrinho]
        if self._no_carrinho():
            return _texto_carrinho(self.carrinho)
        return TITULO + "\nMelhor preço\nComprar agora\nAdicionar ao carrinho"

    def _menos(self):
        self.cliques.append("menos")
        self.carrinho[0]["qtd"] -= 1

    def _adicionar(self):
        self.cliques.append("adicionar")
        sel = re.search(r"item_id%3A(MLB\d+)", self.url)
        item = sel.group(1) if sel else ALVO  # sem filtro, a página abre no 'Melhor preço' (selected)
        preco = 3599 if item == ALVO else 3749
        for l in self.carrinho:
            if l["id"] == item:
                l["qtd"] += 1
                return
        self.carrinho.append({"id": item, "preco": preco, "qtd": 1})

    def locator(self, sel):
        if sel == _SEL_ML_MENOS:
            return _Loc(len(self.carrinho) if self._no_carrinho() else 0, self._menos)
        return _Loc(0)

    def get_by_role(self, role, name=None, **k):
        if not self._no_carrinho() and name is not None and name.search("Adicionar ao carrinho"):
            return _Loc(1, self._adicionar)
        return _Loc(0)


def test_ml_nao_testa_o_anuncio_parcelado_que_esta_no_carrinho():
    # 18/09: carrinho com o 'Parcelamento sem juros' (R$ 3.749); o HEAD aceitava por ter '55C6K'
    for com_id in (True, False):
        ml = MercadoLivre()
        p = PaginaML([{"id": PARCELADO, "preco": 3749, "qtd": 1}], com_id_no_link=com_id)
        assert ml.garantir_item(p, URL_CATALOGO) is False
        assert p.cliques == [], "não mexe no carrinho da pessoa"
        assert ml.item_alvo is None


def test_ml_com_outro_produto_no_carrinho_nao_mexe():
    ml = MercadoLivre()
    p = PaginaML([{"id": ALVO, "preco": 3599, "qtd": 2}, {"id": "MLB999999999", "preco": 99, "qtd": 1,
                                                           "titulo": "Suporte de parede"}])
    assert ml.garantir_item(p, URL_CATALOGO) is False
    assert p.cliques == [], "com outro item, o 'menos' poderia ser o dele"


def test_ml_carrinho_vazio_adiciona_o_melhor_preco():
    ml = MercadoLivre()
    p = PaginaML([])
    assert ml.garantir_item(p, URL_CATALOGO) is True
    assert any(f"pdp_filters=item_id%3A{ALVO}" in u for u in p.visitas), "abre o catálogo já no 'Melhor preço'"
    assert p.cliques == ["adicionar"] and p.carrinho == [{"id": ALVO, "preco": 3599, "qtd": 1}]
    assert ml.item_alvo == ALVO


def test_ml_deixa_uma_unidade_so():
    # 17/09: 'Produtos (2) R$ 8.338' e os cupons foram medidos com 2 TVs
    for com_id in (True, False):
        ml = MercadoLivre()
        p = PaginaML([{"id": ALVO, "preco": 3599, "qtd": 2}], com_id_no_link=com_id)
        assert ml.garantir_item(p, URL_CATALOGO) is True
        assert p.carrinho[0]["qtd"] == 1 and p.cliques == ["menos"]


def test_ml_ajustar_quantidade_so_com_uma_linha():
    p = PaginaML([{"id": ALVO, "preco": 3599, "qtd": 2}, {"id": "MLB999999999", "preco": 3599, "qtd": 1}])
    p.goto(MercadoLivre.url_carrinho)
    assert MercadoLivre().ajustar_quantidade(p, 1) is False and p.cliques == []


# ------------------------------------------------------------------------------------------------
# CARR-07 / CARR-08: Magalu
# ------------------------------------------------------------------------------------------------

# resumo da sacola real de 18/09 (anúncio eecab9199g, Leonfer), como o innerText devolve
SACOLA_LEONFER = """Produtos
Leonfer

Smart TV C6K 55 Polegadas 4K 144 HZ QLED Mini Led TCL

55"
Excluir
1

R$ 4.859,91 no Pix

ou R$ 5.399,90 no cartão

Frete

R$ 193,33

Produtos (1):
R$ 5.399,90
Frete:
R$ 193,33

Tem um código de cupom?

Inserir
Total:
R$ 5.053,24 no PIX
ou R$ 5.593,23 no cartão
Continuar
(1 item)

Pague com Cartão Magalu

em 10x de R$ 559,32 sem juros
ou 21x de R$ 359,01 no Cartão Magalu"""


def test_magalu_parcelado_ignora_o_cartao_da_loja():
    r = Magalu().ler_totais(_SoTexto(SACOLA_LEONFER))
    assert r.parcelado is None, "10x é só no Cartão Magalu; a página do produto diz 7x nos cartões comuns"
    assert (r.produtos, r.frete, r.total_pix, r.total_cartao, r.quantidade) == (5399.9, 193.33, 5053.24, 5593.23, 1)


def test_magalu_parcelado_comum_continua_sendo_lido():
    t = SACOLA_LEONFER.replace("(1 item)\n", "(1 item)\nem 7x de R$ 799,03 sem juros\n")
    assert Magalu().ler_totais(_SoTexto(t)).parcelado == "7x R$ 799,03 sem juros"


def test_magalu_quantidade_do_resumo():
    t = SACOLA_LEONFER.replace("Produtos (1):", "Produtos (2):").replace("R$ 5.593,23 no cartão\nContinuar",
                                                                         "R$ 10.993,13 no cartão\nContinuar")
    r = Magalu().ler_totais(_SoTexto(t))
    assert r.quantidade == 2 and r.tv_cartao == round((10993.13 - 193.33) / 2, 2)


TV_MAGALU = 'Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz Google TV'
URL_MAGALU = "https://www.magazineluiza.com.br/smart-tv-55-tcl/p/240162700/et/elit/"


class _RespSacola:
    url = "https://federation.magazineluiza.com.br/graphql?operationName=GetPreBasketQuery"

    def __init__(self, itens):
        self._itens = [dict(i) for i in itens]

    def json(self):
        return {"data": {"itemList": {"appliedPromoCode": None, "items": self._itens}}}


class PaginaMagalu:
    def __init__(self, itens, excluir_quebrado=False):
        self.itens = [dict(i) for i in itens]
        self.excluir_quebrado = excluir_quebrado
        self.url = ""
        self.cbs = []
        self.cliques: list[str] = []

    def on(self, ev, cb):
        self.cbs.append(cb)

    def remove_listener(self, ev, cb):
        self.cbs.remove(cb)

    def goto(self, url, **k):
        self.url = url
        if "sacola" in url:
            for cb in list(self.cbs):
                cb(_RespSacola(self.itens))

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        if "sacola" in self.url:
            if not self.itens:
                return "Sua sacola está vazia"
            return "Produtos\n" + "\n".join(i["name"] for i in self.itens) + "\nExcluir"
        return "Smart TV\nComprar Agora\nAdicionar à Sacola"

    def _excluir(self):
        self.cliques.append("Excluir")
        self.itens.pop(0)

    def _adicionar(self):
        self.cliques.append("Adicionar")
        self.itens.append({"id": "240162700", "quantity": 1, "name": TV_MAGALU})

    def get_by_role(self, role, name=None, **k):
        if "sacola" in self.url:
            if self.itens and name.search("Excluir") and not self.excluir_quebrado:
                return _Loc(1, self._excluir)
            return _Loc(0)
        if name.search("Adicionar à Sacola"):
            return _Loc(1, self._adicionar)
        return _Loc(0)

    def get_by_text(self, rx):
        return self.get_by_role("button", rx)


def test_magalu_tv_com_2_unidades_e_trocada_por_1():
    p = PaginaMagalu([{"id": "240162700", "quantity": 2, "name": TV_MAGALU}])
    assert Magalu().garantir_item(p, URL_MAGALU) is True
    assert p.cliques == ["Excluir", "Adicionar"]
    assert [(i["id"], i["quantity"]) for i in p.itens] == [("240162700", 1)]


def test_magalu_nao_soma_unidades_quando_nao_consegue_esvaziar():
    p = PaginaMagalu([{"id": "240162700", "quantity": 2, "name": TV_MAGALU}], excluir_quebrado=True)
    assert Magalu().garantir_item(p, URL_MAGALU) is False
    assert "Adicionar" not in p.cliques and p.itens[0]["quantity"] == 2


def test_magalu_com_outro_produto_continua_sem_mexer():
    p = PaginaMagalu([{"id": "240162700", "quantity": 2, "name": TV_MAGALU},
                      {"id": "abc123", "quantity": 1, "name": "Air Fryer Mondial 4L"}])
    assert Magalu().garantir_item(p, URL_MAGALU) is False
    assert p.cliques == [] and len(p.itens) == 2


def test_magalu_uma_tv_certa_nao_mexe():
    p = PaginaMagalu([{"id": "240162700", "quantity": 1, "name": TV_MAGALU}])
    assert Magalu().garantir_item(p, URL_MAGALU) is True and p.cliques == []


# ------------------------------------------------------------------------------------------------
# CARR-05 / CARR-08: mensagem e passo final
# ------------------------------------------------------------------------------------------------

def _aceito(codigo="LU100", **kw) -> ResultadoCupom:
    base = dict(produtos=3599.0, frete=0.0, total_pix=3399.0, total_cartao=3399.0)
    base.update(kw)
    return ResultadoCupom(codigo=codigo, aceito=True, **base)


def test_msg_nao_diz_que_ficou_no_carrinho_da_amazon():
    amz = _aceito("cupom da página")
    amz.extra["so_leitura"] = True
    msg = tc.msg_melhor([("Amazon", amz)])
    assert "ficou aplicado" not in msg and "finalizar" in msg


def test_msg_so_afirma_carrinho_quando_conferido():
    r = _aceito()
    assert "ficou aplicado" not in tc.msg_melhor([("Magazine Luiza", r)]), "sem passo final: não afirma"
    r.extra.update(no_carrinho=False, motivo_carrinho="o carrinho não ficou só com a TV")
    msg = tc.msg_melhor([("Magazine Luiza", r)])
    assert "ficou aplicado" not in msg and "à mão" in msg and "LU100" in msg
    r.extra["no_carrinho"] = True
    assert "ficou aplicado no carrinho da Magazine Luiza" in tc.msg_melhor([("Magazine Luiza", r)])


def test_msg_antes_e_de_uma_tv():
    # 17/09 no ML: 2 unidades (R$ 8.338) e cupom de R$ 200
    ml = _aceito("CUPOMX", produtos=8338.0, desconto=200.0, total_pix=8138.0, total_cartao=8138.0, quantidade=2)
    ml.extra = {"antes_pix": 8338.0, "antes_cartao": 8338.0}
    msg = tc.msg_melhor([("Mercado Livre", ml)])
    assert "antes R$ 4.169,00, economia de R$ 100,00" in msg


class _LojaFalsa:
    nome = "falsa"

    def __init__(self, item_ok=True, resposta=None, explode=False):
        self.item_ok, self.resposta, self.explode = item_ok, resposta, explode
        self.aplicados: list[str] = []

    def garantir_item(self, page, url):
        if self.explode:
            raise TimeoutError("sacola não respondeu")
        return self.item_ok

    def aplicar(self, page, codigo):
        self.aplicados.append(codigo)
        return self.resposta or ResultadoCupom(codigo=codigo, aceito=True)


def test_passo_final_so_marca_no_carrinho_quando_conferido():
    r = _aceito()
    assert tc.deixar_cupom_no_carrinho(_LojaFalsa(), None, URL_MAGALU, r) is True and r.extra["no_carrinho"] is True

    r = _aceito()
    loja = _LojaFalsa(item_ok=False)
    assert tc.deixar_cupom_no_carrinho(loja, None, URL_MAGALU, r) is False
    assert r.extra["no_carrinho"] is False and loja.aplicados == [], "sem a TV certa não aplica"

    r = _aceito()
    assert not tc.deixar_cupom_no_carrinho(_LojaFalsa(explode=True), None, URL_MAGALU, r)
    assert r.extra["no_carrinho"] is False and "TimeoutError" in r.extra["motivo_carrinho"]

    r = _aceito()
    recusa = ResultadoCupom(codigo="LU100", aceito=False, mensagem="Cupom expirado")
    assert not tc.deixar_cupom_no_carrinho(_LojaFalsa(resposta=recusa), None, URL_MAGALU, r)
    assert r.extra["motivo_carrinho"] == "Cupom expirado"


def test_fila_prioriza_cupom_de_horario_e_nunca_testado():
    import sys
    sys.argv = ["x"]
    import testar_cupons as t

    testados = {"VELHO@a": {"status": "recusado", "testado_em": "2026-09-10T10:00:00-03:00"},
                "FALHOU@a": {"status": "erro", "testado_em": "2026-09-18T10:00:00-03:00"}}
    fila = ["VELHO", "FALHOU", "NOVO", "DIADOCLIENTE14H"]
    assert t.ordenar_fila(fila, testados, "a") == ["DIADOCLIENTE14H", "NOVO", "FALHOU", "VELHO"]


def test_sacola_que_nao_carrega_pausa_a_loja():
    from monitor.carrinho import LojaIndisponivel, Magalu

    class PaginaFalha:
        url = "https://sacola.magazineluiza.com.br/r/"

        def on(self, *a):
            pass

        def remove_listener(self, *a):
            pass

        def goto(self, *a, **k):
            pass

        def wait_for_load_state(self, *a, **k):
            pass

        def wait_for_timeout(self, *a):
            pass

        def evaluate(self, *a):
            return "Não conseguimos carregar sua sacola\nPor favor, tente novamente em instantes."

    import pytest
    with pytest.raises(LojaIndisponivel):
        Magalu().itens_da_sacola(PaginaFalha())
