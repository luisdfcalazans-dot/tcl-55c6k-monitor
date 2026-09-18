"""Extração das lojas do PC (Casas Bahia, Mercado Livre, AliExpress) sem abrir navegador.

Os trechos embutidos aqui foram copiados das páginas salvas em 18/09/2026. Quando os snapshots
completos existem na máquina, os testes marcados também rodam contra eles.
Convenção da Oferta: preco = cartão/à vista no cartão; preco_pix = Pix (só se menor);
parcelado = condição SEM juros deste produto.
"""

import json
from pathlib import Path

import pytest

from monitor.sources import playwright_sources as ps

SNAP = Path(r"C:\Users\luisd\AppData\Local\Temp\claude\C--Users-luisd-OneDrive--rea-de-Trabalho-promos"
            r"\8294b9c9-bb7f-4112-99fd-4c7e3e9f239b\scratchpad\snapshots")


def _snap(nome: str) -> str:
    arq = SNAP / nome
    if not arq.exists():
        pytest.skip(f"snapshot {nome} não está nesta máquina")
    return arq.read_text(encoding="utf-8")


def _stub_abrir(monkeypatch, html: str, texto: str) -> None:
    monkeypatch.setattr(ps, "_abrir", lambda *a, **k: (html, texto, []))


# ---------------------------------------------------------------- Casas Bahia

NBSP = "\u00a0"
CB_TITULO = "Smart TV 55” TCL 55C6K 4K QD-Mini Led 144Hz Sistema Operacional Google TV"

# innerText da página (trecho do topo até o 1º patrocinado), como veio em casasbahia_produto.txt
CB_TEXTO = f"""{CB_TITULO}

(Cód. Item 55069456)

Vendido e entregue por Casas Bahia

4.8 de 5 estrelas

4.8

com 172 avaliações
172 avaliações
com 0 perguntas
Sem perguntas

Com instalação de TV

por mais R${NBSP}35,99 por mês*

*na compra parcelada em 10x

por R${NBSP}3.998,99
R${NBSP}3.998,99 em até 11x de R${NBSP}399,83 com juros (1.62% a.m) no cartão de crédito.

por R${NBSP}3.599,09
R${NBSP}3.599,09

No Pix com 10% de desconto

Ver mais opções de pagamento
Comprar
Retira Rápido

Carnê Digital

A partir de R${NBSP}3.599,09, em até 24x no Carnê Digital.

Comprar agora
Calcular o frete e prazo de entrega
Produtos Patrocinados

Patrocinado

Smart TV TCL QLED 50 Polegadas 4K HDR10 HDMI Wi-Fi 50P7K
0 avaliações com média 0 de 5 estrelas.
por R$ 3.416,60 ou em até 6x de R$ 569,43 sem juros ou
R$ 3.416,60 ou em até 6x de R$ 569,43 sem juros ou
Smart TV AOC DLED 32 Polegadas WI-FI Roku TV Quad Core 32S5155/78G
por R$ 1.109,90 ou em até 6x de R$ 184,98 sem juros ou

Descrição do produto
"""

# estado embutido "ProductPrice" (campos reais, lista de parcelas encurtada)
CB_PRODUCT_PRICE = {
    "sellPrice": {"skuId": 55069456, "sellerId": 10037, "priceBefore": 3998.99, "priceValue": 3599.09,
                  "priceWithoutDiscount": 3998.99, "tablePrice": 3998.99, "installment": "No Pix",
                  "parcelValue": 3599.09, "numberOfParcels": 1, "installmentDetails": "sem juros"},
    "paymentMethodDiscount": {"sellPriceWithDiscount": 3599.09, "hasDiscount": True, "discountDescription": "No Pix",
                              "discount": "10%", "hasPaymentFormPix": True},
    "cardConditions": {"hasStoreCardConditions": True, "installment": "até 1x de R$3.599,09 sem juros", "cash": 3998.99},
    "storeCardConditions": {"hasStoreCardConditions": True, "cash": 3998.99,
                            "installment": {"parcelQty": 24, "parcelValue": 166.63, "interest": "sem juros"}},
    "installmentOptions": [
        {"type": "Bandeira", "conditions": [
            {"option": "1x sem juros", "formattedOption": "1x R$ 3998.99 à vista", "price": 3998.99, "qtyParcels": 1,
             "monthlyInterest": 0, "totalPrice": 3998.99},
            {"option": "9x sem juros", "formattedOption": "9x R$ 444.33 sem juros", "price": 444.33, "qtyParcels": 9,
             "monthlyInterest": 0, "totalPrice": 3998.99},
            {"option": "10x sem juros", "formattedOption": "10x R$ 399.90 sem juros", "price": 399.9, "qtyParcels": 10,
             "monthlyInterest": 0, "totalPrice": 3998.99},
            {"option": "12x sem juros", "formattedOption": "12x R$ 333.25 sem juros", "price": 333.25, "qtyParcels": 12,
             "monthlyInterest": 0, "totalPrice": 3998.99},
            {"option": "14x com juros (1,99% a.m)", "formattedOption": "14x R$ 332.27 com juros (1.99% a.m.)",
             "price": 332.27, "qtyParcels": 14, "monthlyInterest": 1.99, "totalPrice": 4651.78},
            {"option": "24x sem juros", "formattedOption": "24x R$ 166.63 sem juros", "price": 166.63, "qtyParcels": 24,
             "monthlyInterest": 0, "totalPrice": 3998.99}]},
        {"type": "Outros", "conditions": [
            {"option": "1x sem juros", "formattedOption": "1x R$ 3998.99 à vista", "price": 3998.99, "qtyParcels": 1,
             "monthlyInterest": 0, "totalPrice": 3998.99},
            {"option": "11x com juros (1,62% a.m.)", "formattedOption": "11x R$ 399.83 com juros (1.62% a.m.)",
             "price": 399.83, "qtyParcels": 11, "monthlyInterest": 1.62, "totalPrice": 4398.13}]},
        {"type": "Pix", "conditions": [{"totalPrice": 3998.99}]},
    ],
}

CB_JSONLD = {"@context": "https://schema.org", "@type": "Product", "name": CB_TITULO,
             "offers": [{"@type": "Offer", "availability": "https://schema.org/InStock", "price": 3599.09,
                         "priceCurrency": "BRL", "seller": {"@type": "Organization", "name": "Casas Bahia"}}]}


def _cb_html(jsonld: bool = True, estado: bool = True) -> str:
    partes = [f"<html><head>"]
    if jsonld:
        partes.append(f'<script type="application/ld+json">{json.dumps(CB_JSONLD, ensure_ascii=False)}</script>')
    partes.append(f"</head><body><h1>{CB_TITULO}</h1>")
    if estado:
        partes.append('<script>self.__next_f.push({"ProductPrice":'
                      f'{json.dumps(CB_PRODUCT_PRICE, ensure_ascii=False)},"ProductFlags":{{"isLoading":false}}}})</script>')
    partes.append("</body></html>")
    return "".join(partes)


def _cb_coletar(monkeypatch, html: str, texto: str):
    _stub_abrir(monkeypatch, html, texto)
    ofertas, cupons = ps.CasasBahia().coletar()
    assert len(ofertas) == 1 and cupons == []
    return ofertas[0]


def test_cb_bloco_principal_nao_corta_nas_estrelas():
    # CB-2: "com 172 avaliações" fica acima do preço; o corte ali devolvia []
    assert ps._precos_do_bloco_principal(CB_TEXTO) == [3998.99, 3998.99, 3599.09, 3599.09, 3599.09]
    # e o patrocinado (50P7K por R$ 3.416,60) continua fora
    assert 3416.60 not in ps._precos_do_bloco_principal(CB_TEXTO)
    # título de seção "Avaliações" em linha própria ainda encerra o bloco
    assert ps._precos_do_bloco_principal("por R$ 3.998,99\n\nAvaliações dos clientes\nR$ 2.100,00") == [3998.99]


def test_cb_bloco_principal_snapshot():
    texto = _snap("casasbahia_produto.txt")
    assert ps._precos_do_bloco_principal(texto)[:3] == [3998.99, 3998.99, 3599.09]


def test_cb_cartao_e_pix_do_estado_embutido(monkeypatch):
    # CB-1: o price do JSON-LD (3.599,09) é o Pix; o de cartão (3.998,99) vem do ProductPrice
    o = _cb_coletar(monkeypatch, _cb_html(), CB_TEXTO)
    assert o.preco == 3998.99
    assert o.preco_pix == 3599.09
    assert o.melhor_preco == 3599.09
    assert o.ativo is True


def test_cb_sem_json_ld_usa_o_bloco_do_produto(monkeypatch):
    # CB-2 no caminho real: sem JSON-LD, a TV em estoque não pode virar ativo=False sem preço
    o = _cb_coletar(monkeypatch, _cb_html(jsonld=False, estado=False), CB_TEXTO)
    assert o.ativo is True
    assert (o.preco, o.preco_pix) == (3998.99, 3599.09)


def test_cb_parcelado_nunca_com_juros(monkeypatch):
    # CB-3: '11x de R$ 399,83 com juros' não é parcelado; o 10x sem juros vem da lista embutida
    o = _cb_coletar(monkeypatch, _cb_html(), CB_TEXTO)
    assert o.parcelado.startswith("10x R$ 399,90 sem juros")
    assert "com juros" not in o.parcelado and "11x" not in o.parcelado
    # só o texto (sem estado embutido): a única parcela do bloco é com juros -> nada; e nunca a do patrocinado
    o = _cb_coletar(monkeypatch, _cb_html(estado=False), CB_TEXTO)
    assert o.parcelado is None


def test_cb_snapshot_completo(monkeypatch):
    html, texto = _snap("casasbahia_produto.html"), _snap("casasbahia_produto.txt")
    o = _cb_coletar(monkeypatch, html, texto)
    assert (o.preco, o.preco_pix) == (3998.99, 3599.09)
    assert o.parcelado.startswith("10x R$ 399,90 sem juros")
    assert o.vendedor == "Casas Bahia" and o.ativo is True


# ---------------------------------------------------------------- Mercado Livre

ML_TITULO = "Smart Tv Tcl 55 Polegadas Qd-Mini Led 4k C6k Wifi Bluetooth Google Tv 4 Hdmi 144hz Hdr10+ 55c6k"

# innerText: topo, carrossel de relacionados e, bem mais abaixo, o buy box com as duas opções
ML_TEXTO = f"""Novo  |  +10 mil vendidos
{ML_TITULO}
MAIS VENDIDO
Avaliação 4.9 de 5. 3924 opiniões.
R$
3.599
R$
3.491
,
03
3% OFF

ou
R$
3.599
 em outros meios

Ver meios de pagamento e promoções
O que você precisa saber sobre este produto
Possui 4 portas HDMI.

Opções de compra:

3 produtos novos a partir de
R$
3.599
Ir para a compra
Produtos relacionados
Ad
Smart Tv Tcl 65 Polegadas Qd-Mini Led 4k C6k Wifi Bluetooth Google Tv 4 Hdmi 144hz Hdr10+ 65c6k
13% OFF
R$
4.699
R$
4.072
+5mil vendidos
no Pix
ou
R$
4.197
 em outros meios
Smart TV TCL 65 Polegadas SQD-Mini LED 4K Q7D Pro WiFi Bluetooth Google TV HDR10+ 144 Hz 65Q7DPRO
7% OFF
R$
6.700
R$
6.219
10x
R$
621
,
90
 sem juros
Descrição
Ver descrição completa
Parcelamento sem juros
R$
3.749

10x
R$
374
,
90
 sem juros

Vendido por Loja oficial Magalu

Melhor preço
R$
3.599
R$
3.491
,
03
3% OFF
Comprar agora
Adicionar ao carrinho
Loja oficial
Mercado Livre
"""

ML_BUY_BOX = {
    "id": "buy_box_offers", "type": "buy_box_offers", "state": "VISIBLE", "items": [
        {"selected": False, "type": "BEST_INSTALLMENTS", "item_id": "MLB7574364080",
         "title": {"text": "Parcelamento sem juros"},
         "components": [{"id": "price", "type": "price", "state": "VISIBLE",
                         "price": {"type": "price", "value": 3749, "currency_symbol": "R$"},
                         "subtitles": [
                             {"id": "pricing_price_subtitle", "text": "10x {price_installments} sem juros",
                              "values": {"price_installments": {"type": "price", "value": 374.9, "currency_symbol": "R$"}}},
                             {"id": "seller", "text": "Vendido por Loja oficial Magalu{cockade_icon}",
                              "values": {"cockade_icon": {"id": "COCKADE", "type": "icon"}}}]}]},
        {"selected": True, "type": "BEST_PRICE", "item_id": "MLB5417889802", "title": {"text": "Melhor preço"},
         "components": [{"id": "price", "type": "price", "state": "VISIBLE",
                         "price": {"type": "price", "value": 3491.03, "original_value": 3599}, "subtitles": []},
                        {"id": "seller", "type": "seller", "state": "HIDDEN"}]},
    ]}
ML_SELLER_DATA = {"id": "seller_data", "type": "seller_data", "state": "VISIBLE", "viewport_track": {"melidata_event": {
    "path": "/pdp/seller_data", "event_data": {"seller_type": "official_store", "seller_id": 480263032,
                                               "item_id": "MLB5417889802", "shop_name": "Mercado Livre"}}}}
ML_JSONLD = {"@context": "https://schema.org", "@type": "Product", "name": ML_TITULO,
             "offers": {"@type": "Offer", "price": 3491.03, "priceCurrency": "BRL",
                        "availability": "https://schema.org/InStock",
                        "url": "https://www.mercadolivre.com.br/p/MLB48808732"}}


def _ml_html(buy_box: dict | None = ML_BUY_BOX, seller_data: dict | None = ML_SELLER_DATA) -> str:
    comps = {}
    if buy_box is not None:
        comps["buy_box_offers"] = buy_box
    if seller_data is not None:
        comps["seller_data"] = seller_data
    return ("<html><head>"
            f'<script type="application/ld+json">{json.dumps(ML_JSONLD, ensure_ascii=False)}</script>'
            f"</head><body><h1>{ML_TITULO}</h1>"
            f"<script>window.__PRELOADED_STATE__ = {json.dumps({'components': comps}, ensure_ascii=False)};</script>"
            "</body></html>")


def _ml_coletar(monkeypatch, tmp_path, html: str, texto: str):
    # a marca de bloqueio do ML vai para uma pasta temporária: o teste nunca mexe em logs/
    monkeypatch.setattr(ps, "MARCA_BLOQUEIO_ML", tmp_path / "ml_bloqueado_em")
    _stub_abrir(monkeypatch, html, texto)
    ofertas, cupons = ps.MercadoLivre().coletar()
    assert cupons == []
    # cada opção do buy box vira uma oferta (ver tests/test_ml_opcoes.py); estes testes olham a opção
    # que a página abriu selecionada, que é a que tem os valores conferidos no texto
    sel = ps._ml_oferta_selecionada(html).get("item_id")
    escolhida = [o for o in ofertas if o.id == sel] if sel else ofertas
    assert len(escolhida) == 1, [o.id for o in ofertas]
    return escolhida[0]


def test_ml_preco_em_outros_meios_e_pix(monkeypatch, tmp_path):
    # ML-1: 'R$ 3.491,03 ... ou R$ 3.599 em outros meios' -> preco 3.599, Pix 3.491,03
    o = _ml_coletar(monkeypatch, tmp_path, _ml_html(), ML_TEXTO)
    assert o.preco == 3599.0
    assert o.preco_pix == 3491.03
    assert o.melhor_preco == 3491.03


def test_ml_parcelado_nao_vem_do_carrossel(monkeypatch, tmp_path):
    # ML-2: o '10x R$ 621' é da TCL 65Q7DPRO do carrossel; o 10x R$ 374,90 é da outra opção do buy box
    o = _ml_coletar(monkeypatch, tmp_path, _ml_html(), ML_TEXTO)
    assert o.parcelado is None
    # parcela sem juros no bloco do produto (oferta única) é aproveitada, com os centavos
    texto = ML_TEXTO.replace(" em outros meios\n", " em outros meios\n10x \nR$\n359\n,\n90\n sem juros\n", 1)
    o = _ml_coletar(monkeypatch, tmp_path, _ml_html(buy_box=None), texto)
    assert o.parcelado == "10x R$ 359,90 sem juros"


def test_ml_parcelado_da_opcao_escolhida(monkeypatch, tmp_path):
    # quando a opção ESCOLHIDA do buy box é a de parcelamento, o parcelado dela vale
    bb = json.loads(json.dumps(ML_BUY_BOX))
    bb["items"][0]["selected"], bb["items"][1]["selected"] = True, False
    o = _ml_coletar(monkeypatch, tmp_path, _ml_html(buy_box=bb, seller_data=None), ML_TEXTO)
    assert o.parcelado == "10x R$ 374,90 sem juros"
    assert o.vendedor == "Loja oficial Magalu"


def test_ml_vendedor_da_opcao_escolhida(monkeypatch, tmp_path):
    # ML-3: 'Vendido por Loja oficial Magalu' é da opção não escolhida; o preço gravado é da loja do ML
    o = _ml_coletar(monkeypatch, tmp_path, _ml_html(), ML_TEXTO)
    assert o.vendedor == "Mercado Livre"
    # buy box com várias opções e vendedor desconhecido: melhor nenhum do que o da outra opção
    o = _ml_coletar(monkeypatch, tmp_path, _ml_html(seller_data=None), ML_TEXTO)
    assert o.vendedor is None
    # página sem buy box múltiplo: o "Vendido por" do texto continua valendo
    o = _ml_coletar(monkeypatch, tmp_path, _ml_html(buy_box=None, seller_data=None), ML_TEXTO)
    assert o.vendedor == "Loja oficial Magalu"


def test_ml_snapshot_completo(monkeypatch, tmp_path):
    html, texto = _snap("mercadolivre_produto.html"), _snap("mercadolivre_produto.txt")
    o = _ml_coletar(monkeypatch, tmp_path, html, texto)
    assert (o.preco, o.preco_pix) == (3599.0, 3491.03)
    assert o.parcelado is None
    assert o.vendedor == "Mercado Livre"


# cartões da busca/carrossel do ML (estrutura real do poly-card; título trocado para a 55C6K)
def _poly_card(complementos: str, atual: str, antes: str) -> str:
    return f"""<div class="andes-card poly-card"><div class="poly-card__content">
<a href="https://www.mercadolivre.com.br/smart-tv-tcl-55c6k/p/MLB48808732" class="poly-component__title">{ML_TITULO}</a>
<div class="poly-component__price"><div class="poly-price__labels"><span class="poly-price__label">
<span class="polylabel-pill">3% OFF</span><span><s class="andes-money-amount andes-money-amount--previous">
<span class="andes-money-amount__currency"><span class="andes-money-amount__currency-symbol">R$</span></span>
<span class="andes-money-amount__fraction">{antes}</span></s></span></span></div>
<div class="poly-price__current"><span class="andes-money-amount poly-price__amount">
<span class="andes-money-amount__currency"><span class="andes-money-amount__currency-symbol">R$</span></span>
<span class="andes-money-amount__fraction">{atual}</span></span>
<span class="poly-price__disc-label">+5mil vendidos</span></div>
<div class="poly-price__complements">{complementos}</div></div></div></div>"""


_MONEY = ('<span class="andes-money-amount"><span class="andes-money-amount__currency">'
          '<span class="andes-money-amount__currency-symbol">R$</span></span>'
          '<span class="andes-money-amount__fraction">{f}</span>{c}</span>')
_CENTS = '<span aria-hidden="true">,</span><span class="andes-money-amount__cents">{c}</span>'


def test_ml_lista_outros_meios_e_parcela_sem_juros():
    pix_ou_outros = ('<span class="poly-price__complement">no Pix</span><span class="poly-price__complement">ou '
                     + _MONEY.format(f="3.599", c="") + " em outros meios</span>")
    (o,) = ps.MercadoLivre._parse_lista(_poly_card(pix_ou_outros, "3.491", "3.599"))
    assert (o.preco, o.preco_pix) == (3599.0, 3491.0)
    assert o.parcelado is None

    sem_juros = ('<span class="poly-price__complement">10x '
                 + _MONEY.format(f="359", c=_CENTS.format(c="90")) + " sem juros</span>")
    (o,) = ps.MercadoLivre._parse_lista(_poly_card(sem_juros, "3.599", "3.799"))
    assert (o.preco, o.preco_pix) == (3599.0, None)
    assert o.parcelado == "10x R$ 359,90 sem juros"

    # no ML, parcela sem o rótulo "sem juros" é com juros: não entra
    com_juros = ('<span class="poly-price__complement">12x '
                 + _MONEY.format(f="345", c=_CENTS.format(c="92")) + "</span>")
    (o,) = ps.MercadoLivre._parse_lista(_poly_card(com_juros, "3.599", "3.799"))
    assert o.parcelado is None


# ---------------------------------------------------------------- AliExpress

def _ali_card(pid: str, precos_html: str) -> str:
    return (f'<a class="search-card-item" href="//pt.aliexpress.com/item/{pid}.html?algo=1" target="_blank">'
            '<div><h3>Smart TV TCL 55C6K QD-Mini LED 4K 144Hz Google TV 55 polegadas 4 HDMI 2 USB</h3></div>'
            f"{precos_html}<span>-6%</span><span>4.8</span><span>5.000+ vendido(s)</span></a>")


def test_ali_preco_de_venda_em_spans_separados(monkeypatch):
    # ALI-1: 'R$ 3 . 499 R$3.749' gravava o riscado 3.749
    html = "<html><body>" + _ali_card(
        "1005001", '<div><span>R$</span><span>3</span><span>.</span><span>499</span></div><del>R$3.749</del>'
    ) + _ali_card(
        "1005002", '<div><span>R$</span><span>4</span><span>.</span><span>069</span><span>,</span><span>90</span></div>'
                   "<del>R$4.199</del>"
    ) + "</body></html>"
    _stub_abrir(monkeypatch, html, "")
    ofertas, _ = ps.AliExpress().coletar()
    precos = {o.id: o.preco for o in ofertas}
    assert precos == {"1005001": 3499.0, "1005002": 4069.90}


def test_junta_precos_nao_inventa_centavos():
    assert ps._junta_precos("R$ 3 . 499 R$3.749 -6%") == "R$ 3.499 R$ 3.749 -6%"
    assert ps._junta_precos("R$\n3.491\n,\n03\n3% OFF") == "R$ 3.491,03\n3% OFF"
    # vírgula de pontuação logo depois do preço não vira centavo
    assert ps._junta_precos("por R$ 3.599, 10x sem juros") == "por R$ 3.599, 10x sem juros"
    assert ps._junta_precos("R$ 3599.09") == "R$ 3599.09"
