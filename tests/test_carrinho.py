"""Teste de cupons no carrinho, sem navegador: páginas falsas com o que as lojas mostraram em 18/09/2026.

CARR-02 falha do robô não vira recusa; recusa vence em 24 h (cupom de horário: a cada hora)
CARR-03 Mercado Livre: testa o anúncio pedido (item da URL; sem item, o 'Melhor preço'), conferido no carrinho;
        desde 19/09 troca a TV do carrinho pelo anúncio pedido quando o carrinho só tem a 55C6K, e com
        qualquer outro produto não mexe (CarrinhoOcupado: a loja fica para a próxima rodada)
19/09   Magalu: o vendedor do anúncio (?seller_id=) é conferido na página ANTES de mexer na sacola
CARR-05 o alerta só diz que o cupom ficou no carrinho quando isso foi conferido
CARR-07 Magalu: parcelas do 'Pague com Cartão Magalu' não são o parcelado
CARR-08 quantidade 1 (Magalu pela sacola, ML pelo seletor de quantidade) e 'antes' de UMA TV
"""

import importlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from monitor.carrinho import CarrinhoOcupado, Magalu, MercadoLivre, ResultadoCupom, _SEL_ML_MENOS, ids_ml
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


def test_ml_cupom_de_antes_no_carrinho():
    sem = _texto_carrinho([{"preco": 3749, "qtd": 1}])
    assert not MercadoLivre().tem_cupom_aplicado(_SoTexto(sem), _totais_ml(sem))
    com = sem.replace("Inserir código do cupom", "Cupom DESCONTO100\n-R$ 100")
    assert MercadoLivre().tem_cupom_aplicado(_SoTexto(com), _totais_ml(com))


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
    # carrinho de 18/09: anúncio de R$ 3.749 e a linha sem id legível -> confere pelo preço; sem a linha lida
    # não há onde clicar em "Excluir": não mexe
    assert sit([], uma) == "outro"
    # a linha é da TV (link do catálogo / item conhecido do catálogo), mas de outro anúncio: pode trocar (19/09)
    assert sit([[URL_CATALOGO]], uma) == "trocar", "o id do catálogo não identifica o anúncio"
    assert sit([[f"https://produto.mercadolivre.com.br/MLB-{PARCELADO[3:]}-smart-tv"]], uma) == "trocar"
    assert sit([[f"{URL_CATALOGO}?pdp_filters=item_id:{ALVO}"]], [{"preco": 3599, "qtd": 1}]) == "ok"
    assert sit([], [{"preco": 3599, "qtd": 1}]) == "ok"
    # itens desconhecidos, sem texto: não dá para dizer que são a TV -> não mexe
    assert sit([["https://x/MLB-111111111"], ["https://x/MLB-222222222"]], uma + uma) == "outro"
    assert sit([], []) == "vazio"
    assert sit([], [{"preco": 1999, "qtd": 1}]) == "?", "preço que não é de nenhuma opção: não dá para afirmar"
    recomenda = "Carrinho\nSeu carrinho está vazio\nRecomendações para você\n" + TITULO
    assert MercadoLivre.situacao_do_carrinho([], _totais_ml(recomenda), recomenda, alvo, ofertas) == "vazio"
    ilegivel = "Carrinho\n" + TITULO  # resumo não lido e a TV na tela: não põe outra
    assert MercadoLivre.situacao_do_carrinho([], _totais_ml(ilegivel), ilegivel, alvo, ofertas) == "?"


def test_situacao_ml_linhas_com_texto():
    alvo = MercadoLivre.anuncio_melhor_preco(HTML_CATALOGO)
    ofertas = MercadoLivre.ofertas_do_catalogo(HTML_CATALOGO)
    duas = [{"preco": 3749, "qtd": 1}, {"preco": 3599, "qtd": 1}]
    texto = _texto_carrinho(duas)

    def sit(linhas, ids_tv=()):
        return MercadoLivre.situacao_do_carrinho(linhas, _totais_ml(texto), texto, alvo, ofertas, "MLB48808732", ids_tv)

    tv_desconhecida = {"links": ["https://produto.mercadolivre.com.br/MLB-111111111-tv"], "texto": TITULO + "\nExcluir"}
    tv_alvo = {"links": [f"https://produto.mercadolivre.com.br/MLB-{ALVO[3:]}-tv"], "texto": TITULO}
    suporte = {"links": ["https://produto.mercadolivre.com.br/MLB-222222222-x"],
               "texto": "Suporte de parede articulado para TV 32 a 75\nExcluir"}
    assert sit([tv_desconhecida, tv_alvo]) == "trocar", "só TVs 55C6K (pelo título): pode trocar"
    assert sit([suporte, tv_alvo]) == "outro", "suporte no carrinho: não mexe em nada"
    assert sit([{"links": ["https://x/MLB-111111111"], "texto": ""}, tv_alvo], ids_tv={"MLB111111111"}) == "trocar", \
        "item conhecido da 55C6K (coleta) conta como TV mesmo sem texto"
    tv65 = {"links": ["https://x/MLB-333333333"], "texto": "Smart TV TCL 65C6K 65 polegadas QD-Mini LED"}
    assert sit([tv65, tv_alvo]) == "outro", "a 65C6K não é a TV do usuário"
    # carrinho com UM produto qualquer: se o bloco lido passou da linha e pegou recomendações (com a própria
    # 55C6K e o link do catálogo), não pode virar "é a TV" (o robô excluiria o produto da pessoa)
    recomendacoes = "\n".join(f"{TITULO}\nR$ 3.749\n10x R$ 374,90" for _ in range(5))
    capa = {"links": ["https://produto.mercadolivre.com.br/MLB-444444444-capa", URL_CATALOGO],
            "texto": "Capa de celular\nR$ 29\nExcluir\nVocê também pode gostar\n" + recomendacoes, "excluir": True}
    um = _texto_carrinho([{"preco": 29, "qtd": 1, "titulo": "Capa de celular"}])
    assert MercadoLivre.situacao_do_carrinho([capa], _totais_ml(um), um, alvo, ofertas, "MLB48808732") == "outro"


class _Loc:
    """Localizador falso: count/click/is_visible, e locator()/filter() encadeados."""

    def __init__(self, n=0, ao_clicar=None, filhos=None):
        self.n, self.ao_clicar, self.filhos = n, ao_clicar, filhos
        self.first = self

    def count(self):
        return self.n

    def is_visible(self):
        return True

    def click(self, timeout=None):
        if not self.n:
            raise AssertionError("clique em elemento inexistente")
        self.ao_clicar()

    def locator(self, sel):
        return self.filhos(sel) if self.filhos else _Loc(0)

    def filter(self, has_text=None, **k):
        return self


def _html_catalogo(selecionado: str = ALVO) -> str:
    """HTML_CATALOGO com a opção `selecionado` marcada (como ?pdp_filters=item_id:<X> faz na página real)."""
    return re.sub(r'"selected":(?:true|false),("type":"BEST_[A-Z_]+","item_id":"(MLB\d+)")',
                  lambda m: f'"selected":{"true" if m.group(2) == selecionado else "false"},{m.group(1)}', HTML_CATALOGO)


class PaginaML:
    """Catálogo + carrinho do ML. Cada linha do carrinho: {'id', 'preco', 'qtd', 'titulo'?}.

    com_id_no_link: o link da linha traz o item (senão só o catálogo); com_texto: o bloco da linha traz o
    título; com_excluir: a linha tem o botão "Excluir"."""

    def __init__(self, carrinho: list[dict], com_id_no_link: bool = True, com_texto: bool = True,
                 com_excluir: bool = True):
        self.carrinho = [dict(l) for l in carrinho]
        self.com_id, self.com_texto, self.com_excluir = com_id_no_link, com_texto, com_excluir
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
        if "/p/" not in self.url:
            return "<html></html>"
        sel = re.search(r"item_id(?:%3A|:)(MLB\d+)", self.url)
        return _html_catalogo(sel.group(1) if sel else ALVO)

    def evaluate(self, js):
        if "stepper" in js:  # uma entrada por linha do carrinho
            if not self._no_carrinho():
                return []
            return [{"links": [f"https://produto.mercadolivre.com.br/MLB-{l['id'][3:]}-tv" if self.com_id else URL_CATALOGO],
                     "texto": (l.get("titulo", TITULO) + "\nExcluir\nSalvar") if self.com_texto else "",
                     "excluir": self.com_excluir}
                    for l in self.carrinho]
        if self._no_carrinho():
            return _texto_carrinho(self.carrinho)
        return TITULO + "\nMelhor preço\nComprar agora\nAdicionar ao carrinho"

    def _menos(self):
        self.cliques.append("menos")
        self.carrinho[0]["qtd"] -= 1

    def _excluir(self, k):
        self.cliques.append("excluir")
        del self.carrinho[k]

    def _adicionar(self):
        self.cliques.append("adicionar")
        sel = re.search(r"item_id%3A(MLB\d+)", self.url) or re.search(r"MLB-(\d+)", self.url)
        item = (sel.group(1) if sel.group(1).startswith("MLB") else "MLB" + sel.group(1)) if sel else ALVO
        preco = 3599 if item == ALVO else 3749  # sem filtro, a página abre no 'Melhor preço' (selected)
        for l in self.carrinho:
            if l["id"] == item:
                l["qtd"] += 1
                return
        self.carrinho.append({"id": item, "preco": preco, "qtd": 1})

    def locator(self, sel):
        if sel == _SEL_ML_MENOS:
            return _Loc(len(self.carrinho) if self._no_carrinho() else 0, self._menos)
        m = re.fullmatch(r"\[data-tv55-linha='(\d+)'\]", sel)
        if m and self._no_carrinho() and int(m.group(1)) < len(self.carrinho):
            k = int(m.group(1))
            return _Loc(1, filhos=lambda s: _Loc(1 if self.com_excluir else 0, lambda: self._excluir(k)))
        return _Loc(0)

    def get_by_role(self, role, name=None, **k):
        if not self._no_carrinho() and name is not None and name.search("Adicionar ao carrinho"):
            return _Loc(1, self._adicionar)
        return _Loc(0)


def test_ml_troca_o_anuncio_parcelado_pelo_alvo_quando_so_tem_tv():
    # 18/09: carrinho com o 'Parcelamento sem juros' (R$ 3.749). Desde 19/09, com só a TV no carrinho, o
    # robô troca pelo anúncio pedido (aqui o 'Melhor preço', formato antigo sem item na URL), 1 unidade.
    for com_id in (True, False):
        ml = MercadoLivre()
        p = PaginaML([{"id": PARCELADO, "preco": 3749, "qtd": 1}], com_id_no_link=com_id)
        assert ml.garantir_item(p, URL_CATALOGO) is True
        assert p.cliques == ["excluir", "adicionar"]
        assert p.carrinho == [{"id": ALVO, "preco": 3599, "qtd": 1}]
        assert ml.item_alvo == ALVO


def test_ml_sem_botao_excluir_nao_troca():
    ml = MercadoLivre()
    p = PaginaML([{"id": PARCELADO, "preco": 3749, "qtd": 1}], com_excluir=False)
    assert ml.garantir_item(p, URL_CATALOGO) is False
    assert p.cliques == [] and ml.item_alvo is None


def test_ml_linha_ilegivel_nao_mexe_e_pula_a_loja():
    # link só do item (desconhecido) e sem texto: não dá para afirmar que é a TV
    ml = MercadoLivre()
    p = PaginaML([{"id": "MLB123456789", "preco": 3749, "qtd": 1}], com_texto=False)
    with pytest.raises(CarrinhoOcupado):
        ml.garantir_item(p, URL_CATALOGO)
    assert p.cliques == []


def test_ml_com_outro_produto_no_carrinho_nao_mexe():
    ml = MercadoLivre()
    p = PaginaML([{"id": ALVO, "preco": 3599, "qtd": 2}, {"id": "MLB999999999", "preco": 99, "qtd": 1,
                                                           "titulo": "Suporte de parede"}])
    with pytest.raises(CarrinhoOcupado):  # a loja inteira fica para a próxima rodada
        ml.garantir_item(p, URL_CATALOGO)
    assert p.cliques == [], "com outro item, o 'menos' poderia ser o dele"
    assert len(p.carrinho) == 2 and p.carrinho[0]["qtd"] == 2


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

    def __init__(self, itens, com_vendedor=True):
        # formato da GetPreBasketQuery: items[].id / quantity / name / item.offers[0].seller
        self._itens = []
        for i in itens:
            it = {k: v for k, v in i.items() if k != "seller"}
            if com_vendedor and i.get("seller"):
                it["item"] = {"offers": [{"seller": dict(i["seller"])}]}
            self._itens.append(it)

    def json(self):
        return {"data": {"itemList": {"appliedPromoCode": None, "items": self._itens}}}


MAGALU_1P = {"id": "magazineluiza", "name": "Magalu"}
COLOMBO = {"id": "lojascolombooficial", "name": "Lojas Colombo Oficial"}


class PaginaMagalu:
    """Sacola + páginas de produto do Magalu.

    `produtos`: {id do /p/: {"titulo", "vendedores": [vendedor, ...]}}; o 1º vendedor é o do buy box. Como
    no site (conferido em 19/09), ?seller_id=<quem não vende o produto> redireciona para o do buy box."""

    def __init__(self, itens, excluir_quebrado=False, produtos=None, sacola_com_vendedor=True):
        self.itens = [dict(i) for i in itens]
        self.excluir_quebrado = excluir_quebrado
        self.produtos = produtos or {"240162700": {"titulo": TV_MAGALU, "vendedores": [MAGALU_1P]},
                                     "kc7h6f4k4b": {"titulo": TV_MAGALU, "vendedores": [COLOMBO]}}
        self.sacola_com_vendedor = sacola_com_vendedor
        self.url = ""
        self.cbs = []
        self.cliques: list[str] = []
        self.paginas: list[str] = []

    def on(self, ev, cb):
        self.cbs.append(cb)

    def remove_listener(self, ev, cb):
        self.cbs.remove(cb)

    def _produto(self):
        m = re.search(r"/p/([^/?#]+)", self.url)
        return (m.group(1), self.produtos.get(m.group(1))) if m else (None, None)

    def _vendedor_atual(self):
        pid, prod = self._produto()
        if not prod:
            return None
        m = re.search(r"seller_id=([^&#]+)", self.url)
        pedido = next((v for v in prod["vendedores"] if m and v["id"] == m.group(1)), None)
        return pedido or prod["vendedores"][0]

    def goto(self, url, **k):
        self.url = url
        if "sacola" in url:
            for cb in list(self.cbs):
                cb(_RespSacola(self.itens, self.sacola_com_vendedor))
            return
        self.paginas.append(url)
        v = self._vendedor_atual()
        if v and "seller_id=" in url:  # redireciona para o vendedor que a página mostra
            self.url = re.sub(r"seller_id=[^&#]+", f"seller_id={v['id']}", url)

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        pid, prod = self._produto()
        if "sacola" in self.url or not prod:
            return "<html></html>"
        v = self._vendedor_atual()
        nd = {"props": {"pageProps": {"data": {"item": {
            "id": pid, "title": prod["titulo"],
            "offers": [{"seller": {"id": x["id"], "description": x["name"]}} for x in prod["vendedores"]]}}}},
            "query": {"path2": pid, "seller_id": v["id"]}}
        return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script>'

    def evaluate(self, js):
        if "sacola" in self.url:
            if not self.itens:
                return "Sua sacola está vazia"
            return "Produtos\n" + "\n".join(i["name"] for i in self.itens) + "\nExcluir"
        v = self._vendedor_atual() or MAGALU_1P
        return f"Smart TV\nVendido por {v['name']}\nComprar Agora\nAdicionar à Sacola"

    def _excluir(self):
        self.cliques.append("Excluir")
        self.itens.pop(0)

    def _adicionar(self):
        self.cliques.append("Adicionar")
        pid, prod = self._produto()
        self.itens.append({"id": pid, "quantity": 1, "name": prod["titulo"], "seller": self._vendedor_atual()})

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
    with pytest.raises(CarrinhoOcupado):  # a loja inteira fica para a próxima rodada
        Magalu().garantir_item(p, URL_MAGALU)
    assert p.cliques == [] and len(p.itens) == 2 and p.paginas == []


def test_magalu_uma_tv_certa_nao_mexe():
    p = PaginaMagalu([{"id": "240162700", "quantity": 1, "name": TV_MAGALU}])
    assert Magalu().garantir_item(p, URL_MAGALU) is True and p.cliques == []


# --- 19/09: vendedor do anúncio ---

URL_1P = URL_MAGALU + "?seller_id=magazineluiza"
ALVO_1P = {"chave": "240162700-magazineluiza", "vendedor": "Magalu", "vendedor_id": "magazineluiza"}
URL_COLOMBO = "https://www.magazineluiza.com.br/smart-tv-tcl-55-ai-4k-uhd-qled-mini-led-android-tv-55c6k/p/kc7h6f4k4b/et/elit/"
TV_COLOMBO = "Smart TV TCL 55 AI, 4K UHD, QLED Mini LED, Android TV - 55C6K"


def test_magalu_troca_colombo_pelo_anuncio_1p_mais_barato():
    p = PaginaMagalu([{"id": "kc7h6f4k4b", "quantity": 1, "name": TV_COLOMBO, "seller": COLOMBO}])
    assert Magalu().garantir_item(p, URL_1P, ALVO_1P) is True
    assert p.cliques == ["Excluir", "Adicionar"]
    assert [(i["id"], i["seller"]["id"]) for i in p.itens] == [("240162700", "magazineluiza")]


def test_magalu_ja_com_o_anuncio_e_vendedor_certos_nao_abre_nada():
    p = PaginaMagalu([{"id": "240162700", "quantity": 1, "name": TV_MAGALU, "seller": MAGALU_1P}])
    assert Magalu().garantir_item(p, URL_1P, ALVO_1P) is True
    assert p.cliques == [] and p.paginas == []


def test_magalu_vendedor_que_a_pagina_nao_oferece_pula_sem_mexer_na_sacola():
    # pede a Colombo no produto 240162700 (só o Magalu vende): o site redireciona para o Magalu
    p = PaginaMagalu([{"id": "kc7h6f4k4b", "quantity": 1, "name": TV_COLOMBO, "seller": COLOMBO}])
    alvo = {"chave": "240162700-lojascolombooficial", "vendedor": "Lojas Colombo Oficial",
            "vendedor_id": "lojascolombooficial"}
    assert Magalu().garantir_item(p, URL_MAGALU + "?seller_id=lojascolombooficial", alvo) is False
    assert p.cliques == [], "a sacola fica como estava"
    assert p.itens[0]["id"] == "kc7h6f4k4b"


def test_magalu_escolhe_o_vendedor_do_anuncio_no_produto_com_varios_vendedores():
    produtos = {"240162700": {"titulo": TV_MAGALU, "vendedores": [MAGALU_1P, COLOMBO]}}
    # na sacola, o mesmo produto do vendedor do buy box: é outro anúncio (outro vendedor) -> troca
    p = PaginaMagalu([{"id": "240162700", "quantity": 1, "name": TV_MAGALU, "seller": MAGALU_1P}], produtos=produtos)
    alvo = {"chave": "240162700-lojascolombooficial", "vendedor": "Lojas Colombo Oficial",
            "vendedor_id": "lojascolombooficial"}
    assert Magalu().garantir_item(p, URL_MAGALU + "?seller_id=lojascolombooficial", alvo) is True
    assert p.cliques == ["Excluir", "Adicionar"]
    assert p.itens[0]["seller"]["id"] == "lojascolombooficial"


def test_magalu_vendedor_so_no_alvo_sem_seller_na_url():
    # a coleta deu o vendedor em extra (vendedor_id), mas a URL não tem ?seller_id: a página mostra o buy box
    p = PaginaMagalu([])
    alvo = {"chave": "240162700-lojascolombooficial", "vendedor": "Lojas Colombo Oficial",
            "vendedor_id": "lojascolombooficial"}
    assert Magalu().garantir_item(p, URL_MAGALU, alvo) is False
    assert p.cliques == [] and p.itens == []


def test_magalu_sacola_sem_vendedor_confere_pela_pagina():
    p = PaginaMagalu([{"id": "240162700", "quantity": 1, "name": TV_MAGALU, "seller": MAGALU_1P}],
                     sacola_com_vendedor=False)
    assert Magalu().garantir_item(p, URL_1P, ALVO_1P) is True
    assert p.cliques == [] and len(p.paginas) == 1 and "sacola" in p.url, "volta para a sacola para ler o total"


def test_magalu_nao_adiciona_pagina_que_nao_e_a_55():
    produtos = {"240162800": {"titulo": 'Smart TV 75" TCL 4K UHD MiniLED 75C6K 120Hz', "vendedores": [MAGALU_1P]}}
    p = PaginaMagalu([], produtos=produtos)
    url75 = "https://www.magazineluiza.com.br/smart-tv-75-tcl/p/240162800/et/elit/?seller_id=magazineluiza"
    assert Magalu().garantir_item(p, url75, ALVO_1P) is False
    assert p.cliques == []


def test_magalu_info_da_pagina_real_de_19_09():
    # trecho do __NEXT_DATA__ de magazineluiza.com.br/…/p/240162700/et/elit/ (19/09): item.offers[0].seller
    nd = {"props": {"pageProps": {"data": {"item": {"id": "240162700", "title": TV_MAGALU, "offers": [
        {"seller": {"deliveryDescription": "Magalu", "description": "Magalu", "id": "magazineluiza", "sku": "240162700"},
         "bestPrice": {"totalAmount": 3561.55}}]}}}}, "query": {"path2": "240162700", "seller_id": "magazineluiza"}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script>'
    info = Magalu.info_da_pagina(html, "Vendido e entregue por Magalu\nPreço R$ 3.561,55", URL_1P)
    assert (info["vendedor_id"], info["vendedor"], info["titulo"]) == ("magazineluiza", "Magalu", TV_MAGALU)
    assert len(info["sinais"]) == 4, "URL, query, oferta única e a frase 'Vendido e entregue por'"
    # sem JSON: pela frase da página
    assert Magalu.info_da_pagina("", "Vendido por Lojas Colombo Oficial e entregue por Magalu\n")["vendedor"] == \
        "Lojas Colombo Oficial"


def test_magalu_sinais_da_pagina_em_conflito_nao_adiciona():
    # a URL diz Colombo, mas a página mostra "Vendido e entregue por Magalu": não dá para confiar
    p = PaginaMagalu([], produtos={"240162700": {"titulo": TV_MAGALU, "vendedores": [MAGALU_1P, COLOMBO]}})
    alvo = {"chave": "240162700-lojascolombooficial", "vendedor": "Lojas Colombo Oficial",
            "vendedor_id": "lojascolombooficial"}
    p.evaluate = lambda js: "Smart TV\nVendido e entregue por Magalu\nAdicionar à Sacola" if "sacola" not in p.url \
        else "Sua sacola está vazia"
    assert Magalu().garantir_item(p, URL_MAGALU + "?seller_id=lojascolombooficial", alvo) is False
    assert p.cliques == []


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
        self.alvos: list = []

    def garantir_item(self, page, url, alvo=None):
        self.alvos.append(alvo)
        if self.explode == "ocupado":
            raise CarrinhoOcupado("tem air fryer")
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


def test_passo_final_passa_o_anuncio_e_nao_mexe_em_carrinho_ocupado():
    r = _aceito()
    loja = _LojaFalsa()
    assert tc.deixar_cupom_no_carrinho(loja, None, URL_1P, r, ALVO_1P) is True
    assert loja.alvos == [ALVO_1P], "o adaptador recebe o anúncio+vendedor"

    r = _aceito()
    loja = _LojaFalsa()
    loja.explode = "ocupado"
    assert tc.deixar_cupom_no_carrinho(loja, None, URL_1P, r, ALVO_1P) is False
    assert loja.aplicados == [] and r.extra["motivo_carrinho"] == "o carrinho tem outros produtos além da TV"

    # aceite de mais cedo: o passo final atualiza o total com o que a loja mostra agora
    r = _aceito(total_pix=3399.0)
    agora_ = ResultadoCupom(codigo="LU100", aceito=True, total_pix=3419.0, total_cartao=3599.0, frete=0.0)
    assert tc.deixar_cupom_no_carrinho(_LojaFalsa(resposta=agora_), None, URL_1P, r, ALVO_1P) is True
    assert r.tv_pix == 3419.0


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
