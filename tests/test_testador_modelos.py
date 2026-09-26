"""Testador de cupons com os DOIS modelos (pedido do usuário em 26/09) e as correções G1-G5 do testador (22/09).

26/09: "monitorar também a 65C6K"; carrinho: "coloque as duas, uma de cada modelo" -> no máximo 1 unidade de cada
modelo (55C6K e 65C6K), nunca outro produto. O cupom vale para o pedido inteiro: para medir um cupom num modelo, o
anúncio fica sozinho no carrinho e a TV do outro modelo sai só se o testador souber devolvê-la; no fim da rodada, uma
TV de cada modelo e o melhor cupom do pedido. A mensagem traz o melhor Pix e o melhor parcelado de CADA modelo.

G1 ML troca de anúncio tirando primeiro e pondo depois, com pré-checagem; G2 botão de tirar por aria-label; G3 linha
tirada é conferida e o passo final compara o preço de agora do cupom de até 48 h; G4 F5 só com título legível do
modelo; G5 o resto (F1/F3/F4/F5) continua.

Tudo com páginas e carrinhos falsos (nenhum navegador de verdade, nenhum perfil de loja), menos o teste do JS do
carrinho do ML, que roda num navegador sem perfil e sem rede sobre um HTML sintético (pulado se não houver navegador).
"""

import re
from contextlib import contextmanager
from datetime import timedelta

import pytest

from monitor import config
from monitor.carrinho import (
    CATALOGOS_ML, CarrinhoOcupado, Magalu, MercadoLivre, ResultadoCupom, eh_do_modelo, modelo_da_linha,
    modelo_da_oferta, modelo_do_titulo,
)
from test_carrinho import (  # noqa: F401 - fakes de página (ML e Magalu)
    ALVO, COLOMBO, HTML_CATALOGO, MAGALU_1P, PARCELADO, TITULO, TV_COLOMBO, TV_MAGALU, URL_CATALOGO, URL_MAGALU,
    PaginaMagalu, PaginaML, _Loc,
)
from test_testador_anuncios import (  # noqa: F401 - ambiente do testador (dados, relógio, sessão falsa)
    FIXO, A, B, CarrinhoFalsoMagalu, KA, KB, _iso, _rec, amb, oferta_magalu, tc,
)

TV65 = 'Smart TV 65" TCL 4K UHD MiniLED 65C6K 120Hz Google TV AiPQ Google Assistente 4 HDMI 2 USB'
TV65_COLOMBO = "Smart TV TCL 65C6K 65 4K Mini LED Android TV Semp Tcl"
TV65_LEONFER = "Smart TV C6K 65 Polegadas 4K 144 HZ QLED Mini Led TCL"
# levantamento de 26/09: Magalu 1P 65" /p/240162600 (Pix 4.559,05), Colombo /p/jcefd125c3 (Pix 4.747,41)
A65 = oferta_magalu("240162600", "magazineluiza", "Magalu", 4559.05, cartao=4799.0, titulo=TV65, modelo="65C6K")
B65 = oferta_magalu("jcefd125c3", "lojascolombooficial", "Lojas Colombo Oficial", 4747.41, cartao=5274.90,
                    titulo=TV65_COLOMBO, modelo="65C6K")
KA65, KB65 = "240162600-magazineluiza", "jcefd125c3-lojascolombooficial"
MODELOS_CHAVE = {KA: "55C6K", KB: "55C6K", KA65: "65C6K", KB65: "65C6K"}
PRECOS = {KA: 3561.55, KB: 3937.15, KA65: 4559.05, KB65: 4747.41}


# ------------------------------------------------------------------------------------------------
# 1. qual TV é qual: título com o tamanho, vizinhos fora, registro antigo = 55C6K
# ------------------------------------------------------------------------------------------------

def test_modelo_pelo_titulo():
    assert modelo_do_titulo(TV_MAGALU) == "55C6K" and modelo_do_titulo(TITULO) == "55C6K"
    for t in (TV65, TV65_COLOMBO, TV65_LEONFER, "Smart TV TCL C6K 65 Polegadas 4K QLED Mini LED Preto Bivolt",
              "Smart TV 65” TCL 65C6K"):
        assert modelo_do_titulo(t) == "65C6K", t
    # vizinhos (levantamento de 26/09) nunca são a 65C6K
    for t in ("Smart TV TCL 65C7K 65 polegadas QD-Mini LED", "Smart TV TCL 65P7L 65 polegadas", "TCL 65QM8K 65 Mini LED",
              "Smart TV TCL 65P8K 65", "Smart TV TCL 65C755 65 polegadas", "TCL 65C69K 65 QD-Mini LED",
              "Smart TV TCL 65C6KS 65 polegadas", "Smart TV TCL 75C6K 75 polegadas"):
        assert modelo_do_titulo(t) is None, t
    assert modelo_do_titulo("Controle remoto para TV TCL 55C6K 65C6K 55P8K 65P8K") is None
    assert modelo_do_titulo("Smart TV TCL 55C6K/65C6K") is None, "texto que serve para os dois: nenhum"
    assert modelo_da_linha('Garantia Estendida 12 meses - Smart TV 65" TCL 65C6K') is None, "serviço não é a TV"
    assert eh_do_modelo(TV65, "65C6K") and not eh_do_modelo(TV65, "55C6K")
    assert modelo_da_oferta({"titulo": TV65}) == "55C6K", "registro sem o campo 'modelo' é da 55C6K (contrato)"
    assert modelo_da_oferta({"modelo": "65c6k"}) == "65C6K"


def test_anuncios_por_modelo_da_coleta(amb):
    # o anúncio de 25/09 que dizia 55" no título na opção de 65" (vendedor já barrado pela lista): mesmo sem a lista,
    # título que não é do modelo da oferta não vai ao carrinho
    titulo_errado = oferta_magalu("kd99999999", "lojax", "Loja X", 3054.56,
                                  titulo='Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz', modelo="65C6K")
    vizinha = oferta_magalu("zz65c7k000", "magazineluiza", "Magalu", 4999.0,
                            titulo="Smart TV TCL 65C7K 65 polegadas QD-Mini LED", modelo="65C6K")
    amb.latest("cloud", [A, B, A65, B65, titulo_errado, vizinha])
    _, anuncios = tc.codigos_conhecidos(CarrinhoFalsoMagalu(amb.pasta))
    assert [(a.chave, a.modelo) for a in anuncios] == [
        (KA, "55C6K"), (KB, "55C6K"), (KA65, "65C6K"), (KB65, "65C6K")]
    grupos = tc.por_modelo(anuncios)
    assert list(grupos) == ["55C6K", "65C6K"] and [a.chave for a in grupos["65C6K"]] == [KA65, KB65]
    ctx = tc.contexto_do_carrinho(anuncios)
    assert ctx["ids_modelo"]["240162600"] == "65C6K" and ctx["ids_modelo"]["240162700"] == "55C6K"
    assert ctx["restauraveis"] == ["55C6K", "65C6K"]
    alvo = grupos["65C6K"][0].alvo((), ctx)
    assert alvo["modelo"] == "65C6K" and alvo["restauraveis"] == ["55C6K", "65C6K"]


def test_checagem_de_confianca_compara_com_o_mesmo_modelo(amb, monkeypatch):
    from monitor import confianca

    vistos: dict = {}

    def pode(o, todas, auto=None):
        vistos[o["id"]] = {x["id"] for x in todas}
        return True, "confiavel"

    monkeypatch.setattr(confianca, "pode_ir_ao_carrinho", pode)
    amb.latest("cloud", [A, B, A65, B65])
    tc.codigos_conhecidos(CarrinhoFalsoMagalu(amb.pasta))
    ids55, ids65 = {A["id"], B["id"]}, {A65["id"], B65["id"]}
    assert vistos[A65["id"]] == ids65, "a 65C6K é comparada só com ofertas da 65C6K"
    assert vistos[A["id"]] == ids55


def test_f1_por_modelo_usa_a_65_lida_pelo_testador(amb):
    # a coleta trouxe só a 55C6K (a da 65C6K falhou); o testador leu a 65C6K no carrinho há 5 h
    amb.latest("cloud", [A])
    reg = {"precos": {KA65: {"vendedor": "Magalu", "url": A65["url"], "modelo": "65C6K", "tv_pix": 4559.05,
                             "tv_cartao": 4799.0, "sem_cupom_pix": 4559.05, "sem_cupom_cartao": 4799.0,
                             "lido_em": _iso(FIXO - timedelta(hours=5))},
                      "velho": {"vendedor": "X", "url": B["url"], "tv_pix": 3900.0,     # sem 'modelo': 55C6K
                                "lido_em": _iso(FIXO - timedelta(hours=5))}}}
    _, anuncios = tc.codigos_conhecidos(CarrinhoFalsoMagalu(amb.pasta), reg)
    assert [(a.chave, a.modelo, a.origem) for a in anuncios] == [(KA, "55C6K", "coleta"), (KA65, "65C6K", "estado")]


def test_f1_65_de_vendedor_reprovado_nao_volta_pelo_estado(amb):
    # revisão de 26/09: a coleta desta rodada não trouxe a 65C6K do Magalu; o testador leu há 3 h um anúncio da 65"
    # que está na lista curada de reprovados (o de 25/09, /p/kd12g2e47k). Ele não volta como anúncio (F1).
    from monitor import confianca

    amb.latest("cloud", [A], codigos=["LU300"])
    url = ("https://www.magazineluiza.com.br/smart-tv-65-tcl-4k-uhd-miniled-65c6k/p/kd12g2e47k/et/elit/"
           "?seller_id=importadoslili")
    lili = {"vendedor": "Importados Lili", "url": url, "modelo": "65C6K", "titulo": 'Smart TV 65" TCL 65C6K',
            "tv_pix": 3054.56, "tv_cartao": 4559.05, "sem_cupom_pix": 3054.56, "sem_cupom_cartao": 4559.05,
            "lido_em": _iso(FIXO - timedelta(hours=3))}
    assert confianca.motivo_bloqueio({"loja": "Magazine Luiza", "url": url, "vendedor": "Importados Lili"}, ())
    legit = {"vendedor": "Magalu", "url": A65["url"], "modelo": "65C6K", "tv_pix": 4559.05, "tv_cartao": 4799.0,
             "sem_cupom_pix": 4559.05, "sem_cupom_cartao": 4799.0, "lido_em": _iso(FIXO - timedelta(hours=3))}
    reg = {"precos": {"kd12g2e47k-importadoslili": lili, KA65: legit}}
    _, anuncios = tc.codigos_conhecidos(CarrinhoFalsoMagalu(amb.pasta), reg)
    assert [(a.chave, a.modelo, a.origem) for a in anuncios] == [(KA, "55C6K", "coleta"), (KA65, "65C6K", "estado")]
    # sem o nome do vendedor no registro: a chave '<anúncio>-<vendedor>' ainda diz quem vende
    sem_nome = {k: v for k, v in lili.items() if k != "vendedor"}
    sem_nome["url"] = url.split("?")[0]
    _, anuncios = tc.codigos_conhecidos(CarrinhoFalsoMagalu(amb.pasta),
                                        {"precos": {"kd12g2e47k-importadoslili": sem_nome}})
    assert [a.chave for a in anuncios] == [KA]


def test_f5_opcao_da_65_e_comparada_com_a_65(amb):
    # a 65C6K do ML 1P (confiável) a Pix R$ 4.219; a página logada da 65" mostrou um vendedor desconhecido a R$ 3.300
    # (22% abaixo da 65" confiável). Perto do preço da 55" (R$ 3.491), mas é da 65": fica de fora.
    from test_testador_anuncios import CarrinhoFalsoML, _confiavel, _opcao as _opcao_f5, oferta_ml

    ml65 = _confiavel(_oferta_ml(M65, "Mercado Livre", 4624.0, 4219.0))
    ml55 = _confiavel(oferta_ml("MLB5417889802", "Mercado Livre", 3599.0, pix=3491.03))
    amb.latest("pc", [ml55, ml65], codigos=["CUPOMML"], loja="Mercado Livre")
    opcao = _opcao_f5(P65, 3300.0, vendedor="Loja Nova XYZ", quando=FIXO - timedelta(hours=1), titulo=TITULO65,
                      url=_url_ml(P65), catalogo=CAT65, modelo="65C6K")
    _, anuncios = tc.codigos_conhecidos(CarrinhoFalsoML(amb.pasta), {"opcoes_catalogo": {P65: opcao}})
    assert [(a.chave, a.modelo) for a in anuncios] == [("MLB5417889802", "55C6K"), (M65, "65C6K")]
    # a mesma opção a R$ 4.100 (3% abaixo da 65" confiável) é legítima e entra
    opcao["preco"] = 4100.0
    _, anuncios = tc.codigos_conhecidos(CarrinhoFalsoML(amb.pasta), {"opcoes_catalogo": {P65: opcao}})
    assert [(a.chave, a.origem) for a in anuncios][1] == (P65, "catalogo_logado")


# ------------------------------------------------------------------------------------------------
# 2. Magalu: isolar o modelo do cupom e, no fim, uma TV de cada modelo
# ------------------------------------------------------------------------------------------------

PRODUTOS = {"240162700": {"titulo": TV_MAGALU, "vendedores": [MAGALU_1P]},
            "kc7h6f4k4b": {"titulo": TV_COLOMBO, "vendedores": [COLOMBO]},
            "240162600": {"titulo": TV65, "vendedores": [MAGALU_1P]},
            "jcefd125c3": {"titulo": TV65_COLOMBO, "vendedores": [COLOMBO]}}
URL65 = "https://www.magazineluiza.com.br/smart-tv-65-tcl/p/240162600/et/elit/"
URL65_COLOMBO = "https://www.magazineluiza.com.br/smart-tv-tcl-65c6k/p/jcefd125c3/et/elit/"
CTX = {"ids_modelo": {"240162700": "55C6K", "kc7h6f4k4b": "55C6K", "240162600": "65C6K", "jcefd125c3": "65C6K"},
       "restauraveis": ["55C6K", "65C6K"]}


def _alvo_magalu(chave, url, vendedor, vendedor_id, modelo, **kw):
    return {"chave": chave, "url": url, "vendedor": vendedor, "vendedor_id": vendedor_id, "modelo": modelo,
            **CTX, **kw}


ALVO55 = _alvo_magalu(KA, URL_MAGALU, "Magalu", "magazineluiza", "55C6K")
ALVO65 = _alvo_magalu(KA65, URL65, "Magalu", "magazineluiza", "65C6K")


class SacolaDoisModelos(PaginaMagalu):
    """PaginaMagalu com as duas TVs. O "Excluir" da sacola tira o 1º item; a confirmação do diálogo não tira outro
    (na sacola falsa de uma TV só, os dois padrões caíam no mesmo botão)."""

    def __init__(self, itens, **k):
        super().__init__(itens, produtos=dict(PRODUTOS), **k)

    def get_by_role(self, role, name=None, **k):
        if "sacola" in self.url and name is not None and name.pattern != r"^excluir$":
            return _Loc(0)
        return super().get_by_role(role, name, **k)


def _item(pid, qtd=1, seller=MAGALU_1P):
    return {"id": pid, "quantity": qtd, "name": PRODUTOS[pid]["titulo"], "seller": seller}


def _sacola(p):
    return [(i["id"], i["quantity"]) for i in p.itens]


def test_magalu_isola_a_55_tirando_a_65_que_sabe_devolver():
    m = Magalu()
    m.comecar_rodada()
    p = SacolaDoisModelos([_item("240162700"), _item("240162600")])
    assert m.garantir_item(p, URL_MAGALU, ALVO55) is True
    assert _sacola(p) == [("240162700", 1)], "o cupom é medido com a 55C6K sozinha"
    assert p.cliques == ["Excluir", "Excluir", "Adicionar"]
    assert sorted(m.removidos) == ["55C6K", "65C6K"] and m.remocoes == 2


def test_magalu_nao_tira_a_65_sem_anuncio_para_devolver():
    m = Magalu()
    p = SacolaDoisModelos([_item("240162700"), _item("240162600")])
    with pytest.raises(CarrinhoOcupado, match="65C6K"):
        m.garantir_item(p, URL_MAGALU, {**ALVO55, "restauraveis": ["55C6K"]})
    assert p.cliques == [] and len(p.itens) == 2


def test_magalu_passo_final_so_poe_a_que_falta():
    m = Magalu()
    m.comecar_rodada()
    p = SacolaDoisModelos([_item("240162700")])
    assert m.garantir_itens(p, [ALVO55, ALVO65]) == {KA, KA65}
    assert p.cliques == ["Adicionar"] and _sacola(p) == [("240162700", 1), ("240162600", 1)]
    assert m.remocoes == 0, "nada foi tirado"


def test_magalu_passo_final_ja_certo_nao_mexe():
    m = Magalu()
    p = SacolaDoisModelos([_item("240162600"), _item("240162700")])
    assert m.garantir_itens(p, [ALVO55, ALVO65]) == {KA, KA65}
    assert p.cliques == [] and p.paginas == []


def test_magalu_passo_final_troca_o_anuncio_errado_conferindo_as_paginas_antes():
    m = Magalu()
    m.comecar_rodada()
    p = SacolaDoisModelos([_item("kc7h6f4k4b", seller=COLOMBO), _item("240162600")])
    assert m.garantir_itens(p, [ALVO55, ALVO65]) == {KA, KA65}
    assert p.cliques == ["Excluir", "Excluir", "Adicionar", "Adicionar"]
    assert sorted(_sacola(p)) == [("240162600", 1), ("240162700", 1)]
    # as duas páginas foram conferidas ANTES de esvaziar (e de novo antes de cada clique em "Adicionar")
    assert [re.search(r"/p/([^/]+)", u).group(1) for u in p.paginas[:2]] == ["240162700", "240162600"]


def test_magalu_passo_final_pagina_que_nao_confere_nao_esvazia():
    m = Magalu()
    p = SacolaDoisModelos([_item("kc7h6f4k4b", seller=COLOMBO), _item("240162600")])
    # pede a 65C6K da Colombo no /p/ do 1P (só o Magalu vende): a página mostra outro vendedor
    colombo_no_1p = _alvo_magalu("240162600-lojascolombooficial", URL65 + "?seller_id=lojascolombooficial",
                                 "Lojas Colombo Oficial", "lojascolombooficial", "65C6K")
    assert m.garantir_itens(p, [ALVO55, colombo_no_1p]) == set()
    assert p.cliques == [] and len(p.itens) == 2, "a sacola fica como estava"


def test_magalu_passo_final_duas_unidades_da_65_vira_uma():
    m = Magalu()
    p = SacolaDoisModelos([_item("240162700"), _item("240162600", qtd=2)])
    assert m.garantir_itens(p, [ALVO55, ALVO65]) == {KA, KA65}
    assert sorted(_sacola(p)) == [("240162600", 1), ("240162700", 1)], "no máximo 1 unidade de cada modelo"


def test_magalu_passo_final_com_outro_produto_nao_mexe():
    m = Magalu()
    p = SacolaDoisModelos([_item("240162700"), {"id": "abc123", "quantity": 1, "name": "Air Fryer Mondial 4L"}])
    with pytest.raises(CarrinhoOcupado):
        m.garantir_itens(p, [ALVO55, ALVO65])
    assert p.cliques == []


def test_magalu_passo_final_de_um_modelo_mantem_a_tv_do_outro():
    # sem anúncio da 65C6K para pôr, a 65C6K que a pessoa tem fica (nunca é tirada)
    m = Magalu()
    p = SacolaDoisModelos([_item("240162600")])
    assert m.garantir_itens(p, [ALVO55]) == {KA}
    assert sorted(_sacola(p)) == [("240162600", 1), ("240162700", 1)] and p.cliques == ["Adicionar"]


# ------------------------------------------------------------------------------------------------
# 3. Mercado Livre: dois catálogos, isolar o modelo do cupom e uma TV de cada no fim
# ------------------------------------------------------------------------------------------------

CAT65 = CATALOGOS_ML["65C6K"]
URL_CAT65 = f"https://www.mercadolivre.com.br/p/{CAT65}"
M65, P65 = "MLB6500000001", "MLB6500000002"
TITULO65 = "Smart TV TCL 65 Polegadas QLED Mini LED 4K C6K Wifi Bluetooth Google TV 4 HDMI 144hz HDR10 65C6K"
HTML65 = (HTML_CATALOGO.replace(ALVO, M65).replace(PARCELADO, P65).replace("MLB48808732", CAT65)
          .replace('"value":3749,', '"value":4699,')
          .replace('"value":3491.03,"original_value":3599', '"value":4399,"original_value":4499')
          .replace('"localItemPrice":3599', '"localItemPrice":4499'))
PRECOS_ML = {ALVO: 3599, PARCELADO: 3749, M65: 4499, P65: 4699}
IDS_ML = {ALVO: "55C6K", PARCELADO: "55C6K", M65: "65C6K", P65: "65C6K"}


def _seleciona(html, item):
    return re.sub(r'"selected":(?:true|false),("type":"BEST_[A-Z_]+","item_id":"(MLB\d+)")',
                  lambda m: f'"selected":{"true" if m.group(2) == item else "false"},{m.group(1)}', html)


def _linha65(item, qtd=1):
    return {"id": item, "preco": PRECOS_ML[item], "qtd": qtd, "titulo": TITULO65}


class PaginaMLDoisModelos(PaginaML):
    """Carrinho do ML e as páginas dos DOIS catálogos (55C6K MLB48808732, 65C6K MLB50368907)."""

    def content(self):
        if CAT65 not in self.url:
            return super().content()
        sel = re.search(r"item_id(?:%3A|:)(MLB\d+)", self.url)
        titulo = f'<h1 class="ui-pdp-title">{TITULO65}</h1>' if self.com_titulo else ""
        return titulo + _seleciona(HTML65, sel.group(1) if sel else M65)

    def _item_da_url(self):
        sel = re.search(r"item_id%3A(MLB\d+)", self.url)
        return sel.group(1) if sel else (M65 if CAT65 in self.url else ALVO)

    def _adicionar(self):
        self.cliques.append("adicionar")
        item = self._item_da_url()
        for l in self.carrinho:
            if l["id"] == item:
                l["qtd"] += 1
                return
        self.carrinho.append(_linha65(item) if item in (M65, P65) else {"id": item, "preco": PRECOS_ML[item], "qtd": 1})


def _url_ml(item):
    cat = CAT65 if IDS_ML[item] == "65C6K" else "MLB48808732"
    return f"https://www.mercadolivre.com.br/p/{cat}?pdp_filters=item_id%3A{item}"


def _alvo_ml(item, **kw):
    return {"chave": item, "item_id": item, "url": _url_ml(item), "modelo": IDS_ML[item],
            "catalogo": CAT65 if IDS_ML[item] == "65C6K" else "MLB48808732", "ids_modelo": dict(IDS_ML),
            "restauraveis": ["55C6K", "65C6K"], **kw}


def _ids(p):
    return [(l["id"], l["qtd"]) for l in p.carrinho]


def test_ml_isola_a_55_tirando_a_65_que_sabe_devolver():
    ml = MercadoLivre()
    ml.comecar_rodada()
    p = PaginaMLDoisModelos([{"id": PARCELADO, "preco": 3749, "qtd": 1}, _linha65(M65)])
    assert ml.garantir_item(p, _url_ml(ALVO), _alvo_ml(ALVO)) is True
    assert _ids(p) == [(ALVO, 1)] and p.cliques == ["excluir", "excluir", "adicionar"]
    assert sorted(ml.removidos) == ["55C6K", "65C6K"]


def test_ml_nao_tira_a_65_sem_anuncio_para_devolver():
    ml = MercadoLivre()
    p = PaginaMLDoisModelos([{"id": ALVO, "preco": 3599, "qtd": 1}, _linha65(M65)])
    with pytest.raises(CarrinhoOcupado, match="65C6K"):
        ml.garantir_item(p, _url_ml(ALVO), _alvo_ml(ALVO, restauraveis=["55C6K"], ids_modelo={ALVO: "55C6K"}))
    assert p.cliques == [] and len(p.carrinho) == 2


def test_ml_passo_final_poe_a_65_sem_tirar_a_55():
    ml = MercadoLivre()
    ml.comecar_rodada()
    p = PaginaMLDoisModelos([{"id": ALVO, "preco": 3599, "qtd": 1}])
    assert ml.garantir_itens(p, [_alvo_ml(ALVO), _alvo_ml(M65)]) == {ALVO, M65}
    assert p.cliques == ["adicionar"] and _ids(p) == [(ALVO, 1), (M65, 1)] and ml.remocoes == 0


def test_ml_passo_final_troca_so_a_linha_errada_do_modelo():
    ml = MercadoLivre()
    ml.comecar_rodada()
    p = PaginaMLDoisModelos([{"id": PARCELADO, "preco": 3749, "qtd": 1}, _linha65(M65)])
    assert ml.garantir_itens(p, [_alvo_ml(ALVO), _alvo_ml(M65)]) == {ALVO, M65}
    assert p.cliques == ["excluir", "adicionar"], "tira a 55C6K errada e põe a certa; a 65C6K fica"
    assert sorted(_ids(p)) == [(ALVO, 1), (M65, 1)] and ml.removidos == ["55C6K"]


def test_ml_passo_final_pre_checagem_que_falha_mantem_o_modelo_como_esta():
    class NaoSeleciona55(PaginaMLDoisModelos):
        def content(self):
            html = super().content()
            return html if CAT65 in self.url else html.replace('"selected":true', '"selected":false').replace(
                f'"selected":false,"type":"BEST_INSTALLMENTS","item_id":"{PARCELADO}"',
                f'"selected":true,"type":"BEST_INSTALLMENTS","item_id":"{PARCELADO}"')

    ml = MercadoLivre()
    p = NaoSeleciona55([{"id": PARCELADO, "preco": 3749, "qtd": 1}, _linha65(P65)])
    assert ml.garantir_itens(p, [_alvo_ml(ALVO), _alvo_ml(M65)]) == {M65}
    assert (PARCELADO, 1) in _ids(p), "a página não selecionou o anúncio da 55C6K: a 55C6K antiga fica"
    assert (M65, 1) in _ids(p) and (P65, 1) not in _ids(p)


def test_ml_passo_final_deixa_uma_unidade_de_cada_pela_linha():
    ml = MercadoLivre()
    p = PaginaMLDoisModelos([{"id": ALVO, "preco": 3599, "qtd": 1}, _linha65(M65, qtd=2)], com_qtd=True)
    assert ml.garantir_itens(p, [_alvo_ml(ALVO), _alvo_ml(M65)]) == {ALVO, M65}
    assert _ids(p) == [(ALVO, 1), (M65, 1)] and p.cliques == ["menos"], "o 'menos' de DENTRO da linha da 65C6K"


def test_ml_passo_final_sem_saber_qual_linha_tem_unidade_a_mais_nao_clica():
    ml = MercadoLivre()
    p = PaginaMLDoisModelos([{"id": ALVO, "preco": 3599, "qtd": 1}, _linha65(M65, qtd=2)])
    assert ml.garantir_itens(p, [_alvo_ml(ALVO), _alvo_ml(M65)]) == set()
    assert p.cliques == [] and ml.tvs_a_mais is True, "a pessoa é avisada; o robô não chuta"


def test_ml_passo_final_com_outro_produto_nao_mexe():
    ml = MercadoLivre()
    p = PaginaMLDoisModelos([{"id": ALVO, "preco": 3599, "qtd": 1},
                             {"id": "MLB999999999", "preco": 99, "qtd": 1, "titulo": "Suporte de parede"}])
    with pytest.raises(CarrinhoOcupado):
        ml.garantir_itens(p, [_alvo_ml(ALVO), _alvo_ml(M65)])
    assert p.cliques == []


# --- G4: opções do catálogo só com título legível da TV do modelo ---

def test_g4_opcoes_do_catalogo_so_com_titulo_legivel():
    ml = MercadoLivre()
    ml.comecar_rodada()
    ml._anota_opcoes(HTML_CATALOGO, URL_CATALOGO)   # sem <h1> nem og:title (R9 da revisão de 22/09)
    assert ml.opcoes_vistas == {}
    ml._anota_opcoes(f'<h1 class="ui-pdp-title">{TITULO}</h1>' + HTML_CATALOGO, URL_CATALOGO)
    assert set(ml.opcoes_vistas) == {ALVO, PARCELADO}
    assert {v["modelo"] for v in ml.opcoes_vistas.values()} == {"55C6K"}


def test_g4_opcoes_do_catalogo_da_65():
    ml = MercadoLivre()
    ml.comecar_rodada()
    ml._anota_opcoes(f'<h1 class="ui-pdp-title">{TITULO65}</h1>' + HTML65, URL_CAT65)
    assert set(ml.opcoes_vistas) == {M65, P65}
    assert {v["modelo"] for v in ml.opcoes_vistas.values()} == {"65C6K"}
    assert ml.opcoes_vistas[M65]["preco"] == 4399.0 and "MLB50368907" in ml.opcoes_vistas[M65]["url"]
    ml.comecar_rodada()
    # título da 55C6K na página do catálogo da 65C6K (ou o contrário): nada é anotado
    ml._anota_opcoes(f'<h1 class="ui-pdp-title">{TITULO}</h1>' + HTML65, URL_CAT65)
    ml._anota_opcoes(f'<h1 class="ui-pdp-title">{TITULO65}</h1>' + HTML_CATALOGO, URL_CATALOGO)
    assert ml.opcoes_vistas == {}


def test_g2_js_do_carrinho_num_dom_parecido_com_o_real():
    """O _JS_ML_LINHAS num navegador sem perfil e sem rede, sobre um HTML sintético com a forma do carrinho de 22/09:
    ícone com aria-label "Remover produto" e sem texto; outra linha com o botão "Excluir"; um produto sem controle."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from monitor.carrinho import _JS_ML_LINHAS

    linha = ('<div class="row"><input type="checkbox" checked>'
             '<a href="https://produto.mercadolivre.com.br/MLB-{id}-tv-_JM">{titulo}</a>'
             '<span>R$ {preco}</span><div>{remover}<button>Salvar</button></div>'
             '<div class="andes-input-stepper"><button class="andes-input-stepper__button" '
             'data-andes-input-stepper-control-type="decrement">-</button><input value="{qtd}">'
             '<button class="andes-input-stepper__button" data-andes-input-stepper-control-type="increment">+</button>'
             '</div></div>')
    icone = '<button aria-label="Remover produto"><svg width="8" height="8"><path d="M0 0h8v8H0z"/></svg></button>'
    html = ("<html><body><section>"
            + linha.format(id="7574364080", titulo=TITULO, preco="3.749", qtd=1, remover=icone)
            + linha.format(id="6500000001", titulo=TITULO65, preco="4.499", qtd=2, remover="<button>Excluir</button>")
            + linha.format(id="999999999", titulo="Suporte de parede", preco="99", qtd=1, remover="")
            + "</section><aside>Resumo da compra</aside></body></html>")
    with sync_api.sync_playwright() as pw:
        nav = None
        for kw in ({}, {"channel": "chrome"}):
            try:
                nav = pw.chromium.launch(headless=True, **kw)
                break
            except Exception:  # noqa: BLE001
                continue
        if nav is None:
            pytest.skip("sem navegador para o teste do JS")
        try:
            page = nav.new_page()
            page.set_content(html)
            linhas = page.evaluate(_JS_ML_LINHAS)
            marcados = [page.locator(f"[data-tv55-excluir='{k}']").count() for k in range(3)]
        finally:
            nav.close()
    assert [(l["excluir"], l["qtd"]) for l in linhas] == [(True, 1), (True, 2), (False, 1)]
    assert marcados == [1, 1, 0]
    cl = MercadoLivre.classificar_linhas(linhas, ALVO, "MLB48808732", (), "55C6K", {PARCELADO: "55C6K"})
    assert [(c["tv"], c["modelo"]) for c in cl] == [(True, "55C6K"), (True, "65C6K"), (False, None)]


# ------------------------------------------------------------------------------------------------
# 4. rodada do testador com os dois modelos (carrinho falso)
# ------------------------------------------------------------------------------------------------

class CarrinhoDoisModelos(Magalu):
    """Identidade real do Magalu; carrinho falso que guarda as chaves dos anúncios que estão lá.

    `aceita`: {(chave, código): desconto} medido com a TV sozinha. Com as duas TVs, o cupom vale para o pedido quando
    vale para um dos itens (vale o maior desconto). garantir_item isola o anúncio (esvazia e põe), com a mesma trava
    do adaptador real para a TV do outro modelo; garantir_itens deixa uma de cada. `nao_entra`: anúncios que não
    entram no carrinho (a página não conferiu, antes de mexer)."""

    def __init__(self, pasta, carrinho=(), aceita=None, nao_entra=(), precos=None):
        self.pasta = pasta
        self.carrinho = list(carrinho)
        self.aceita = dict(aceita or {})
        self.nao_entra = set(nao_entra)
        self.precos = dict(precos or PRECOS)
        self.eventos: list[tuple] = []

    def perfil(self):
        return self.pasta

    def _tira(self, chaves):
        for c in list(chaves):
            self.carrinho.remove(c)
            self._tirou(MODELOS_CHAVE.get(c))

    def garantir_item(self, page, url, alvo=None):
        chave = alvo["chave"]
        self.eventos.append(("garantir", chave))
        if self.carrinho == [chave]:
            return True
        sem_volta = {MODELOS_CHAVE[c] for c in self.carrinho} - (set(alvo.get("restauraveis") or ()) | {alvo["modelo"]})
        if sem_volta:
            raise CarrinhoOcupado(f"tem a {sem_volta} e não sei devolver")
        if chave in self.nao_entra:
            return False
        self._tira(self.carrinho)
        self.carrinho = [chave]
        return True

    def garantir_itens(self, page, alvos):
        chaves = [a["chave"] for a in alvos]
        self.eventos.append(("garantir_itens", tuple(chaves)))
        ok = [c for c in chaves if c not in self.nao_entra]
        modelos = {a["modelo"] for a in alvos}
        self._tira([c for c in self.carrinho if c not in ok and MODELOS_CHAVE[c] in modelos])
        for c in ok:
            if c not in self.carrinho:
                self.carrinho.append(c)
        return set(ok)

    def _res(self, codigo, desconto=0.0):
        soma = sum(self.precos[c] for c in self.carrinho)
        return ResultadoCupom(codigo=codigo, aceito=bool(desconto), produtos=soma, frete=0.0, desconto=desconto or None,
                              total_pix=round(soma - desconto, 2),
                              total_cartao=round(soma + 180 * len(self.carrinho) - desconto, 2),
                              parcelado="10x R$ 374,90 sem juros", quantidade=max(1, len(self.carrinho)))

    def ler_totais(self, page):
        return self._res("")

    def aplicar(self, page, codigo):
        self.eventos.append(("aplicar", tuple(self.carrinho), codigo))
        d = max([self.aceita.get((c, codigo), 0.0) for c in self.carrinho] or [0.0])
        if d:
            return self._res(codigo, d)
        r = self._res(codigo)
        r.mensagem = "Este cupom não se aplica para este pedido"
        return r

    def remover(self, page):
        self.eventos.append(("remover", tuple(self.carrinho)))

    def tem_cupom_aplicado(self, page, base):
        return False


def _aplicados(loja):
    return [(e[1][0] if len(e[1]) == 1 else e[1], e[2]) for e in loja.eventos if e[0] == "aplicar"]


def test_rodada_com_os_dois_modelos_termina_com_uma_tv_de_cada_e_o_cupom_do_pedido(amb):
    amb.latest("cloud", [A, B, A65, B65], codigos=["INFLU300", "LU300"])
    loja = CarrinhoDoisModelos(amb.pasta, carrinho=[KA, KA65],
                               aceita={(KA, "INFLU300"): 300.0, (KA65, "LU300"): 300.0})
    aceitos, estado = amb.rodar(loja)
    testes = _aplicados(loja)
    # cada modelo do mais barato ao mais caro, com a TV sozinha no carrinho
    assert testes[:2] == [(KA, "INFLU300"), (KA, "LU300")]
    assert (KB, "LU300") in testes and (KB, "INFLU300") not in testes, "aceito no 1P da 55C6K: não vai ao Colombo"
    assert (KA65, "INFLU300") in testes and (KA65, "LU300") in testes, "os cupons são testados na 65C6K também"
    assert (KB65, "INFLU300") in testes and (KB65, "LU300") not in testes
    # fim: uma TV de cada modelo e o cupom do pedido (o de maior economia; empate: o da 55C6K)
    assert loja.eventos[-2:] == [("garantir_itens", (KA, KA65)), ("aplicar", tuple(loja.carrinho), "INFLU300")]
    assert sorted(loja.carrinho) == sorted([KA, KA65])
    por_codigo = {(r.codigo, r.extra["modelo"]): r for r in aceitos}
    assert set(por_codigo) == {("INFLU300", "55C6K"), ("LU300", "65C6K")}
    assert por_codigo[("INFLU300", "55C6K")].extra["no_carrinho"] is True
    lu300 = por_codigo[("LU300", "65C6K")]
    assert lu300.extra["no_carrinho"] is False and lu300.extra["cupom_do_pedido"] == "INFLU300"
    assert tc.AVISOS_CARRINHO == []
    cup = estado["magalu"]["cupons"]
    assert cup[f"LU300@{KA65}"]["status"] == "aceito" and cup[f"LU300@{KA65}"]["modelo"] == "65C6K"
    assert estado["magalu"]["precos"][KA65]["modelo"] == "65C6K"
    msg = tc.msg_melhor([("Magazine Luiza", r) for r in aceitos])
    assert 'TV 55" (55C6K)' in msg and 'TV 65" (65C6K)' in msg
    assert "Melhor à vista</b>: R$ 3.261,55" in msg and "Melhor à vista</b>: R$ 4.259,05" in msg
    assert "Alvo: Pix R$ 2.900,00 · parcelado R$ 3.000,00" in msg
    assert "Alvo: Pix R$ 3.300,00 · parcelado R$ 3.500,00" in msg
    assert "com uma TV de cada modelo" in msg
    assert "vale um cupom por pedido); para esta TV sozinha, o cupom é <code>LU300</code>" in msg
    assert "à mão" not in msg


def test_cupom_de_um_modelo_mede_so_com_ele_e_a_outra_tv_volta_no_fim(amb):
    # só a 55C6K tem cupom pendente: a 65C6K sai para o teste e volta no passo final
    amb.latest("cloud", [A, A65], codigos=["CUPOMX"])
    estado = {"magalu": {"cupons": {f"CUPOMX@{KA65}": _rec("recusado", FIXO - timedelta(hours=1))}}}
    loja = CarrinhoDoisModelos(amb.pasta, carrinho=[KA, KA65])
    amb.rodar(loja, estado)
    assert [e for e in loja.eventos if e[0] == "aplicar"] == [("aplicar", (KA,), "CUPOMX")]
    assert loja.eventos[-1] == ("garantir_itens", (KA, KA65))
    assert sorted(loja.carrinho) == sorted([KA, KA65]) and tc.AVISOS_CARRINHO == []


def test_tv_do_outro_modelo_que_nao_volta_avisa(amb):
    amb.latest("cloud", [A, A65, B65], codigos=["CUPOMX"])
    uma_hora = FIXO - timedelta(hours=1)
    estado = {"magalu": {"cupons": {f"CUPOMX@{KA65}": _rec("recusado", uma_hora),
                                    f"CUPOMX@{KB65}": _rec("recusado", uma_hora)}}}
    loja = CarrinhoDoisModelos(amb.pasta, carrinho=[KA, KA65], nao_entra={KA65, KB65})
    amb.rodar(loja, estado)
    assert loja.carrinho == [KA]
    (aviso,) = tc.AVISOS_CARRINHO
    assert "65C6K" in aviso and "Magazine Luiza" in aviso and "vazia" not in aviso
    assert [e[1] for e in loja.eventos if e[0] == "garantir_itens"] == [(KA, KA65), (KA, KB65)], \
        "tenta a mais barata da 65C6K e, sem ela, a próxima"


class CarrinhoQueCaiNoFim(CarrinhoDoisModelos):
    """O passo final (garantir_itens) leva o antirrobô do Magalu ('Não conseguimos carregar sua sacola') enquanto
    `cai` for True; garantir_item (o isolamento para medir o cupom) funciona."""

    def __init__(self, *a, cai=True, **k):
        super().__init__(*a, **k)
        self.cai = cai

    def garantir_itens(self, page, alvos):
        if self.cai:
            self.eventos.append(("garantir_itens", tuple(a["chave"] for a in alvos)))
            from monitor.carrinho import LojaIndisponivel
            raise LojaIndisponivel("Não conseguimos carregar sua sacola")
        return super().garantir_itens(page, alvos)


def _relogio(monkeypatch, quando):
    monkeypatch.setattr(tc, "agora", lambda: quando)
    monkeypatch.setattr(tc, "agora_iso", lambda: _iso(quando))


def _rodada_que_deixa_a_65_fora(amb):
    """Rodada 1 (revisão de 26/09): só a 55C6K tem cupom pendente; a 65C6K sai para medir o cupom e o passo final leva o
    antirrobô. A sacola termina só com a 55C6K e a pessoa recebe UM aviso."""
    amb.latest("cloud", [A, A65], codigos=["NOVO50"])
    estado = {"magalu": {"cupons": {f"NOVO50@{KA65}": _rec("recusado", FIXO - timedelta(hours=1))}}}
    loja = CarrinhoQueCaiNoFim(amb.pasta, carrinho=[KA, KA65])
    amb.rodar(loja, estado)
    assert loja.carrinho == [KA]
    (aviso,) = tc.AVISOS_CARRINHO
    assert "65C6K" in aviso and "não consegui devolver" in aviso
    assert set(estado["magalu"]["tvs_fora"]) == {"65C6K"}, "o estado lembra que a 65C6K saiu e não voltou"
    tc.AVISOS_CARRINHO.clear()
    loja.eventos.clear()
    return loja, estado


def test_tv_que_saiu_e_nao_voltou_e_devolvida_na_rodada_seguinte_sem_cupom_pendente(amb, monkeypatch):
    loja, estado = _rodada_que_deixa_a_65_fora(amb)
    # rodada 2, depois da pausa de 3 h: nada pendente (NOVO50 recusado nos dois), mas a 65C6K tem de voltar
    _relogio(monkeypatch, FIXO + timedelta(hours=3, minutes=10))
    loja.cai = False
    amb.rodar(loja, estado)
    assert loja.eventos == [("garantir_itens", (KA65,))], "só põe a que falta, sem mexer na 55C6K nem aplicar cupom"
    assert sorted(loja.carrinho) == sorted([KA, KA65])
    assert "tvs_fora" not in estado["magalu"]
    (aviso,) = tc.AVISOS_CARRINHO
    assert "65C6K" in aviso and "de volta" in aviso and "⚠" not in aviso
    # rodada 3: tudo certo, o carrinho não é tocado
    tc.AVISOS_CARRINHO.clear()
    loja.eventos.clear()
    amb.rodar(loja, estado)
    assert loja.eventos == [] and tc.AVISOS_CARRINHO == []


def test_tv_fora_respeita_a_pausa_da_loja(amb, monkeypatch):
    loja, estado = _rodada_que_deixa_a_65_fora(amb)
    assert "pausa_ate" in estado["magalu"]
    _relogio(monkeypatch, FIXO + timedelta(hours=1))
    loja.cai = False
    amb.rodar(loja, estado)
    assert loja.eventos == [] and loja.carrinho == [KA], "em pausa: a loja não é aberta"
    assert set(estado["magalu"]["tvs_fora"]) == {"65C6K"}


def test_tv_fora_que_nao_volta_de_novo_nao_repete_o_aviso_e_desiste_depois_de_3_tentativas(amb, monkeypatch, capsys):
    loja, estado = _rodada_que_deixa_a_65_fora(amb)
    loja.cai = False
    loja.nao_entra = {KA65}   # o anúncio da 65C6K não entra (a página não confere)
    for k in range(1, 4):
        _relogio(monkeypatch, FIXO + timedelta(hours=3 + k))
        amb.rodar(loja, estado)
        assert [e[0] for e in loja.eventos] == ["garantir_itens"], f"rodada {k + 1}: uma tentativa"
        assert tc.AVISOS_CARRINHO == [], "o aviso já foi dado na rodada em que a TV saiu"
        loja.eventos.clear()
    assert estado["magalu"]["tvs_fora"]["65C6K"]["tentativas"] == 3
    _relogio(monkeypatch, FIXO + timedelta(hours=7))
    capsys.readouterr()
    amb.rodar(loja, estado)
    assert loja.eventos == [] and "tvs_fora" not in estado["magalu"]
    assert "desisto de devolver" in capsys.readouterr().out


def test_tv_fora_sem_anuncio_conhecido_espera_a_rodada_em_que_ele_aparece(amb, monkeypatch):
    loja, estado = _rodada_que_deixa_a_65_fora(amb)
    loja.cai = False
    _relogio(monkeypatch, FIXO + timedelta(hours=4))
    amb.latest("cloud", [A], codigos=["NOVO50"])          # a coleta desta rodada não trouxe a 65C6K
    amb.rodar(loja, estado)
    assert loja.eventos == [] and estado["magalu"]["tvs_fora"]["65C6K"]["tentativas"] == 0
    amb.latest("cloud", [A, A65], codigos=["NOVO50"])
    amb.rodar(loja, estado)
    assert loja.eventos == [("garantir_itens", (KA65,))] and sorted(loja.carrinho) == sorted([KA, KA65])
    assert "tvs_fora" not in estado["magalu"]


def test_tv_fora_volta_no_passo_final_de_uma_rodada_com_cupom(amb, monkeypatch):
    loja, estado = _rodada_que_deixa_a_65_fora(amb)
    loja.cai = False
    _relogio(monkeypatch, FIXO + timedelta(hours=4))
    amb.latest("cloud", [A, A65], codigos=["NOVO50", "OUTRO10"])   # cupom novo: rodada normal
    amb.rodar(loja, estado)
    assert loja.eventos[-1] == ("garantir_itens", (KA, KA65)), "o passo final de sempre devolve a 65C6K"
    assert [e for e in loja.eventos if e[0] == "garantir_itens"] == [("garantir_itens", (KA, KA65))]
    assert sorted(loja.carrinho) == sorted([KA, KA65]) and "tvs_fora" not in estado["magalu"]


def test_65_sem_anuncio_conhecido_nao_deixa_isolar_a_55(amb):
    amb.latest("cloud", [A], codigos=["CUPOMX"])
    loja = CarrinhoDoisModelos(amb.pasta, carrinho=[KA, KA65])
    aceitos, estado = amb.rodar(loja)
    assert loja.eventos == [("garantir", KA)], "o carrinho tem a 65C6K e não há anúncio dela para devolver"
    assert loja.carrinho == [KA, KA65] and aceitos == [] and tc.AVISOS_CARRINHO == []
    assert "pausa_ate" not in estado["magalu"]


def test_orcamento_de_testes_dividido_entre_os_modelos(amb, monkeypatch):
    monkeypatch.setattr(tc, "MAX_APLICACOES_POR_RODADA", 4)
    amb.latest("cloud", [A, B, A65, B65], codigos=["C1X", "C2X", "C3X", "C4X", "C5X"])
    loja = CarrinhoDoisModelos(amb.pasta)
    amb.rodar(loja)
    assert _aplicados(loja) == [(KA, "C1X"), (KA, "C2X"), (KA65, "C1X"), (KA65, "C2X")]


def test_sobra_do_orcamento_de_um_modelo_vai_para_o_outro(amb, monkeypatch):
    monkeypatch.setattr(tc, "MAX_APLICACOES_POR_RODADA", 4)
    amb.latest("cloud", [A, A65], codigos=["C1X", "C2X", "C3X", "C4X"])
    uma_hora = FIXO - timedelta(hours=1)
    estado = {"magalu": {"cupons": {f"{c}@{KA}": _rec("recusado", uma_hora) for c in ("C1X", "C2X", "C3X")}}}
    loja = CarrinhoDoisModelos(amb.pasta)
    amb.rodar(loja, estado)
    assert _aplicados(loja) == [(KA, "C4X"), (KA65, "C1X"), (KA65, "C2X"), (KA65, "C3X")]


def test_so_a_65_na_loja_usa_o_passo_final_de_um_modelo(amb):
    amb.latest("cloud", [A65, B65], codigos=["LU300"])
    loja = CarrinhoDoisModelos(amb.pasta, aceita={(KA65, "LU300"): 300.0})
    aceitos, _ = amb.rodar(loja)
    assert loja.eventos[-2:] == [("garantir", KA65), ("aplicar", (KA65,), "LU300")]
    msg = tc.msg_melhor([("Magazine Luiza", r) for r in aceitos])
    assert msg.startswith("✅ <b>Cupom funcionou</b>") and 'TV 65" (65C6K)' in msg
    assert "Alvo: Pix R$ 3.300,00 · parcelado R$ 3.500,00" in msg and "R$ 2.900" not in msg


def test_cupom_do_pedido_que_nao_compensa_com_o_preco_de_agora(amb, monkeypatch):
    # G3 com os dois modelos: COLOMBO500 foi aceito há 40 h na 55C6K da Colombo (3.400); hoje dá 3.700, pior que o 1P
    # sem cupom (3.561,55). O pedido com ele sai mais caro que as duas TVs mais baratas sem cupom: fica sem cupom.
    monkeypatch.setattr(tc, "MAX_APLICACOES_POR_RODADA", 2)
    amb.latest("cloud", [A, B, A65], codigos=["COLOMBO500", "NOVO1"])
    quarenta = FIXO - timedelta(hours=40)
    estado = {"magalu": {"cupons": {
        f"COLOMBO500@{KB}": _rec("aceito", quarenta, "Lojas Colombo Oficial", total_pix=3400.0, total_cartao=3580.0,
                                 frete=0.0, desconto=537.15, tv_pix=3400.0, quantidade=1),
        f"COLOMBO500@{KA}": _rec("recusado", FIXO - timedelta(hours=1)),
        f"COLOMBO500@{KA65}": _rec("recusado", FIXO - timedelta(hours=1))}}}
    loja = CarrinhoDoisModelos(amb.pasta, carrinho=[KA, KA65], aceita={(KB, "COLOMBO500"): 237.15})
    amb.rodar(loja, estado)
    assert ("garantir_itens", (KB, KA65)) in loja.eventos
    assert loja.eventos[-1] == ("garantir_itens", (KA, KA65)), "volta para as mais baratas sem cupom"
    assert sorted(loja.carrinho) == sorted([KA, KA65])


# ------------------------------------------------------------------------------------------------
# 5. G3 com um modelo: o aceite de até 48 h é conferido com o preço de agora (R8 da revisão de 22/09)
# ------------------------------------------------------------------------------------------------

def test_g3_aceite_antigo_que_nao_compensa_mais_volta_ao_mais_barato(amb, monkeypatch):
    monkeypatch.setattr(tc, "MAX_APLICACOES_POR_RODADA", 1)
    amb.latest("cloud", [A, B], codigos=["COLOMBO500", "NOVO1"])
    rec = {f"COLOMBO500@{KB}": _rec("aceito", FIXO - timedelta(hours=40), vendedor="Lojas Colombo Oficial",
                                    total_pix=3400.0, total_cartao=3580.0, frete=0.0, desconto=537.15,
                                    tv_pix=3400.0, quantidade=1)}
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KB, "COLOMBO500"): 237.15})
    loja.no_carrinho = KA
    _, estado = amb.rodar(loja, {"magalu": {"cupons": rec}})
    assert loja.eventos[-3:] == [("garantir", KB), ("aplicar", KB, "COLOMBO500"), ("garantir", KA)]
    assert loja.no_carrinho == KA, "o carrinho não fica no Colombo a 3.700 com o 1P a 3.561,55 sem cupom"
    reg = estado["magalu"]["cupons"][f"COLOMBO500@{KB}"]
    assert reg["testado_em"] == _iso(FIXO) and reg["tv_pix"] == 3700.0, "o registro fica com o preço de agora"


# ------------------------------------------------------------------------------------------------
# 6. ML com o adaptador REAL sobre páginas falsas (cenários da revisão de 22/09, agora com G1)
# ------------------------------------------------------------------------------------------------

class MLReal(MercadoLivre):
    """Adaptador REAL do ML; só perfil, aplicar e remover são falsos (a página de cupons não é simulada)."""

    def __init__(self, pasta):
        self.pasta = pasta

    def perfil(self):
        return self.pasta

    def aplicar(self, page, codigo):
        page.goto(self.url_carrinho)
        r = self.ler_totais(page)
        r.codigo, r.aceito, r.mensagem = codigo, False, "sem mudança no total"
        return r

    def remover(self, page):
        pass


def _rodar_ml(amb, monkeypatch, pagina, estado, ofertas=(), codigos=("CUPOMML",)):
    amb.latest("pc", list(ofertas), codigos=list(codigos), loja="Mercado Livre")
    loja = MLReal(amb.pasta)

    @contextmanager
    def sessao(l, v):
        yield pagina

    monkeypatch.setattr(tc, "_sessao", sessao)
    aceitos, estado = amb.rodar(loja, estado, loja_id="mercadolivre")
    return loja, aceitos, estado


def _lido(item, vendedor, valor, horas=1, modelo=None):
    d = {"vendedor": vendedor, "url": _url_ml(item), "tv_pix": valor, "tv_cartao": valor, "parcelado": None,
         "cupom": "(sem cupom)", "lido_em": _iso(FIXO - timedelta(hours=horas))}
    if modelo:
        d["modelo"] = modelo
    return d


def _opcao(item, preco, pix=None, vendedor="Mercado Livre", titulo=TITULO):
    return {"item_id": item, "preco": preco, "preco_pix": pix, "vendedor": vendedor, "parcelado": None,
            "tipo": "BEST_PRICE", "titulo": titulo, "url": _url_ml(item), "catalogo": "MLB48808732",
            "visto_em": _iso(FIXO - timedelta(minutes=30))}


def _estado_r(excluir_ok=None):
    return {"mercadolivre": {"cupons": {}, "precos": {PARCELADO: _lido(PARCELADO, "Magalu", 3749.0)},
                             "opcoes_catalogo": {ALVO: _opcao(ALVO, 3599.0, 3491.03)}}}


@pytest.mark.parametrize("funciona", [lambda n, item: False,            # R3: nenhum Excluir tem efeito
                                      lambda n, item: n >= 3,           # R5: os 2 primeiros cliques não pegam
                                      lambda n, item: item != PARCELADO])  # R7: só o da linha antiga quebrado
def test_ml_excluir_sem_efeito_nunca_deixa_duas_tvs_nem_aviso_falso(amb, monkeypatch, funciona):
    class Pagina(PaginaML):
        n = 0

        def _excluir(self, k):
            Pagina.n += 1
            self.cliques.append("excluir")
            if funciona(Pagina.n, self.carrinho[k]["id"]):
                del self.carrinho[k]

    p = Pagina([{"id": PARCELADO, "preco": 3749, "qtd": 1}])
    _loja, _aceitos, _est = _rodar_ml(amb, monkeypatch, p, _estado_r())
    assert len(p.carrinho) == 1, p.carrinho
    assert not any("mais de uma TV" in a for a in tc.AVISOS_CARRINHO)
    assert not any("vazia" in a.lower() for a in tc.AVISOS_CARRINHO)


def test_ml_duas_tvs_do_mesmo_modelo_nao_viram_tres(amb, monkeypatch):
    # R4: carrinho já com duas TVs da 55C6K (efeito da F2) e uma 3ª opção mais barata; o Excluir não tem efeito
    terceira = "MLB9000000001"
    IDS_ML[terceira] = "55C6K"
    PRECOS_ML[terceira] = 3400

    class Pagina(PaginaMLDoisModelos):
        def _excluir(self, k):
            self.cliques.append("excluir")

        def content(self):
            html = super().content()
            item3 = ('{"selected":false,"type":"BEST_INSTALLMENTS","item_id":"%s","title":{"text":"Outra opção"},'
                     '"components":[{"id":"price","type":"price","state":"VISIBLE","price":{"type":"price",'
                     '"value":3400,"currency_symbol":"R$","currency_id":"BRL"}}]},' % terceira)
            html = html.replace('"items":[', '"items":[' + item3, 1)
            sel = re.search(r"item_id(?:%3A|:)(MLB\d+)", self.url)
            return _seleciona(html, sel.group(1)) if sel else html

    try:
        p = Pagina([{"id": PARCELADO, "preco": 3749, "qtd": 1}, {"id": ALVO, "preco": 3599, "qtd": 1}])
        est = _estado_r()
        est["mercadolivre"]["opcoes_catalogo"][terceira] = _opcao(terceira, 3400.0, vendedor="Loja X")
        _rodar_ml(amb, monkeypatch, p, est)
    finally:
        IDS_ML.pop(terceira, None)
        PRECOS_ML.pop(terceira, None)
    assert len(p.carrinho) == 2 and "adicionar" not in p.cliques, "nunca uma 3ª TV"
    assert any("mais de uma TV do mesmo modelo" in a for a in tc.AVISOS_CARRINHO), "a pessoa sabe das duas"


def _oferta_ml(item, vendedor, preco, pix=None):
    modelo = IDS_ML[item]
    return {"fonte": "mercadolivre", "tipo": "loja", "loja": "Mercado Livre", "ativo": True, "modelo": modelo,
            "titulo": TITULO65 if modelo == "65C6K" else TITULO, "url": _url_ml(item), "id": item,
            "vendedor": vendedor, "preco": preco, "preco_pix": pix, "melhor_preco": min(x for x in (preco, pix) if x),
            "extra": {"anuncio": item, "item_id": item,
                      "catalogo": CAT65 if modelo == "65C6K" else "MLB48808732"}}


def test_ml_rodada_com_os_dois_modelos_adaptador_real(amb, monkeypatch):
    p = PaginaMLDoisModelos([{"id": PARCELADO, "preco": 3749, "qtd": 1}, _linha65(M65)])
    ofertas = [_oferta_ml(PARCELADO, "Magalu", 3749.0), _oferta_ml(M65, "Mercado Livre", 4499.0, 4399.0)]
    loja, aceitos, est = _rodar_ml(amb, monkeypatch, p, {}, ofertas)
    assert sorted(_ids(p)) == sorted([(PARCELADO, 1), (M65, 1)]), "termina com uma TV de cada modelo"
    # 55C6K: tira a 65C6K para medir; 65C6K: tira a 55C6K, põe a 65C6K; fim: põe a 55C6K de volta
    assert p.cliques == ["excluir", "excluir", "adicionar", "adicionar"]
    assert tc.AVISOS_CARRINHO == []
    assert set(est["mercadolivre"]["cupons"]) == {f"CUPOMML@{PARCELADO}", f"CUPOMML@{M65}"}
    opcoes = est["mercadolivre"]["opcoes_catalogo"]
    assert opcoes[P65]["modelo"] == "65C6K" and opcoes[ALVO]["modelo"] == "55C6K"


def test_ml_tv_fora_de_rodada_anterior_volta_sem_tirar_a_outra_adaptador_real(amb, monkeypatch):
    # a 65C6K saiu do carrinho do ML numa rodada anterior e não voltou; nada pendente agora: ela volta, e a 55C6K da
    # pessoa fica onde está
    p = PaginaMLDoisModelos([{"id": PARCELADO, "preco": 3749, "qtd": 1}])
    ofertas = [_oferta_ml(PARCELADO, "Magalu", 3749.0), _oferta_ml(M65, "Mercado Livre", 4499.0, 4399.0)]
    uma_hora = FIXO - timedelta(hours=1)
    estado = {"mercadolivre": {"cupons": {f"CUPOMML@{PARCELADO}": _rec("recusado", uma_hora),
                                          f"CUPOMML@{M65}": _rec("recusado", uma_hora)},
                               "tvs_fora": {"65C6K": {"desde": _iso(FIXO - timedelta(hours=2)), "tentativas": 0}}}}
    loja, _aceitos, est = _rodar_ml(amb, monkeypatch, p, estado, ofertas)
    assert sorted(_ids(p)) == sorted([(PARCELADO, 1), (M65, 1)])
    assert p.cliques == ["adicionar"], "só põe a 65C6K; nada é tirado"
    assert "tvs_fora" not in est["mercadolivre"]
    (aviso,) = tc.AVISOS_CARRINHO
    assert "Mercado Livre" in aviso and "de volta" in aviso


# ------------------------------------------------------------------------------------------------
# 7. mensagem por modelo
# ------------------------------------------------------------------------------------------------

def _res(codigo, pix, cartao, modelo, **extra):
    return ResultadoCupom(codigo=codigo, aceito=True, produtos=cartao, frete=0.0, total_pix=pix, total_cartao=cartao,
                          parcelado="10x R$ 400,00 sem juros", extra={"modelo": modelo, **extra})


def test_msg_por_modelo_com_alvo_de_cada_um():
    r55 = _res("INFLU300", 3261.55, 3449.0, "55C6K")
    r65 = _res("LU300", 3290.0, 3480.0, "65C6K")          # abaixo dos alvos da 65C6K (3.300 / 3.500)
    msg = tc.msg_melhor([("Magazine Luiza", r55), ("Magazine Luiza", r65)])
    assert msg.startswith("🎯 <b>META ATINGIDA</b>")
    assert '🎯 <b>TV 65" (65C6K)</b>' in msg and '📺 <b>TV 55" (55C6K)</b>' in msg
    assert msg.index("TV 55") < msg.index("TV 65")
    assert "<b>Melhor parcelado</b>: R$ 3.480,00" in msg and "<b>Melhor parcelado</b>: R$ 3.449,00" in msg
    # a 55C6K sozinha: o formato de sempre
    so55 = tc.msg_melhor([("Magazine Luiza", _res("INFLU300", 3261.55, 3449.0, "55C6K"))])
    assert so55.startswith("✅ <b>Cupom funcionou</b>\n\n<b>Melhor à vista</b>") and "TV 55" not in so55


def test_alvos_por_modelo(monkeypatch):
    # os mesmos alvos da coleta e do painel (config.alvo_pix/alvo_parcelado por modelo)
    for k, v in (("ALVO_PIX", 2900.0), ("ALVO_PARCELADO", 3000.0), ("ALVO_PIX_65", 3300.0),
                 ("ALVO_PARCELADO_65", 3500.0)):
        monkeypatch.setattr(config, k, v)
    assert tc.alvos_do_modelo("55C6K") == (2900.0, 3000.0)
    assert tc.alvos_do_modelo("65C6K") == (3300.0, 3500.0)
    monkeypatch.setattr(config, "ALVO_PIX_65", 3200.0)
    monkeypatch.setattr(config, "ALVO_PARCELADO_65", 3400.0)
    assert tc.alvos_do_modelo("65C6K") == (3200.0, 3400.0)
    assert tc.alvos_do_modelo("55C6K") == (2900.0, 3000.0)
