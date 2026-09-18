"""Regressões do grupo extracao-nuvem (achados N-F1..N-F10 de 18/09/2026 e regressões REG-1..REG-5 da rodada 2).

As amostras são trechos copiados das páginas salvas em 18/09 (snapshots) ou dos fixtures de 13/09.
"""

import json
from pathlib import Path

import pytest

from monitor import config, regras
from monitor.filtro import bloco_55c6k, eh_55c6k, linha_55c6k, motivo_rejeicao
from monitor.sources import kabum, magalu, telegram_public, vtex, zoom
from monitor.util import cupom_no_texto, parcelado_no_texto, preco_postagem, precos_no_texto

FIX = Path(__file__).parent / "fixtures"
SNAP = Path(r"C:\Users\luisd\AppData\Local\Temp\claude\C--Users-luisd-OneDrive--rea-de-Trabalho-promos"
            r"\8294b9c9-bb7f-4112-99fd-4c7e3e9f239b\scratchpad\snapshots")


def le(nome: str) -> str:
    return (FIX / nome).read_text(encoding="utf-8", errors="replace")


def canal(*linhas: str) -> str:
    """Prévia t.me/s/<canal> com uma única mensagem; cada item vira uma linha (<br>)."""
    corpo = "<br>".join(linhas)
    return ('<div class="tgme_widget_message" data-post="canal/1"><div class="tgme_widget_message_text">'
            + corpo + '</div><time datetime="2026-09-18T10:00:00+00:00"></time></div>')


def um_post(*linhas: str):
    ofs = telegram_public.parse_canal(canal(*linhas), "canal")
    assert len(ofs) == 1, ofs
    return ofs[0]


# ---------- N-F1: acessórios, peças e anúncios de vários tamanhos ----------

def test_nf1_controle_da_busca_magalu_nao_vira_oferta():
    """Busca real do Magalu (18/09) sem os tokens p8k: o controle de R$ 149,99 entrava como oferta de loja."""
    prod = {
        "id": "fa14gj5k07", "available": True,
        "title": "Controle comando de voz para tv tcl 55c6k 65c6k 75c6k 85c6k 98c6k 55c6k 65c6k 75c6k 85c6k 98c6k",
        "path": "/magazinecanaltechbr/controle-comando-de-voz-para-tv-tcl-55c6k/p/fa14gj5k07/et/cttv/",
        "price": {"bestPrice": "149.99", "fullPrice": "149.99", "price": "199.99"},
        "installment": {"amount": "75.00", "interest": "0.00", "quantity": 2},
        "seller": {"id": "lfacomercial", "description": "Lfa.Comercial", "category": "3p"},
    }
    nd = {"props": {"pageProps": {"data": {"search": {"products": [prod]}}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script>'
    assert magalu.parse_busca(html) == []


def test_nf1_motivos():
    assert motivo_rejeicao("Smart TV TCL 65C6K 55C6K 75C6K Mini LED") == "vários tamanhos"
    assert motivo_rejeicao("Placa principal TCL 55C6K").startswith("negativo")
    assert motivo_rejeicao("Painel LED TCL 55C6K").startswith("acessório")
    # o par "55C6K/65C6K" das postagens continua aceito
    assert eh_55c6k("Smart TV TCL 55C6K/65C6K QD-Mini LED (loja oficial)")


# ---------- N-F2: valores sem ponto de milhar ----------

def test_nf2_precos_sem_ponto_de_milhar():
    assert precos_no_texto("R$ 3599,00") == [3599.0]
    assert precos_no_texto("R$ 3599") == [3599.0]
    assert precos_no_texto("R$ 12345,67") == [12345.67]
    assert precos_no_texto("R$ 3.599,00 ou R$3.082,61") == [3599.0, 3082.61]
    assert parcelado_no_texto("10x de R$ 1234,56 sem juros") == "10x R$ 1234,56 sem juros"


def test_nf2_telegram_preco_sem_ponto():
    o = um_post("Smart TV TCL 55C6K", "De R$ 4.199 por R$ 3599 no Pix", "ou 10x de R$ 399,90 sem juros")
    assert o.preco == 3599.0
    assert o.parcelado == "10x R$ 399,90 sem juros"


def test_parcelado_com_juros_nunca_e_guardado():
    # rodada 2 (REG-2): a 1ª parcela "com juros" não é pulada para uma "sem juros" mais adiante
    assert parcelado_no_texto("12x de R$ 380,00 com juros ou 10x de R$ 399,90 sem juros") is None
    assert parcelado_no_texto("12x de R$ 380,00 com juros") is None


# ---------- N-F3: mínimo do cupom tomado como preço ----------

def test_nf3_minimo_do_cupom_nao_e_preco():
    o = um_post('🔥 Smart TV TCL 55" QD-Mini LED 55C6K', "💰 R$ 3.599,00 no Pix",
                "🎟️ Cupom: TV300 (R$ 300 OFF acima de R$ 2.499)")
    assert o.preco == 3599.0 and o.cupom == "TV300"
    o = um_post("Smart TV TCL 55C6K", "R$ 3.599,00 no Pix", "Cupom TV300: R$ 300 OFF em compras acima de R$ 1.999")
    assert o.preco == 3599.0


def test_nf3_preco_postagem():
    assert preco_postagem("A partir de R$1.049,00") == 1049.0          # formato do Canaltech
    assert preco_postagem("Por R$2.760,00 em até 15x") == 2760.0
    assert preco_postagem("R$ 3.599 no cartão ou R$ 3.419 no Pix") == 3419.0
    assert preco_postagem("R$ 3.599,00 à vista ou 10x de R$ 1.059,90") == 3599.0
    assert preco_postagem("Economize R$ 1.200! Sai por R$ 3.299") == 3299.0
    assert preco_postagem("Preço: R$ 3.599 | Pedido mínimo R$ 2.000") == 3599.0
    assert preco_postagem("R$ 3.599 | Valor mínimo: R$ 2.000") == 3599.0
    assert preco_postagem("De: R$ 4.199,00\nPor: R$ 3.599,00") == 3599.0


# ---------- N-F4: Pix da VTEX que vem em Installments (Fast Shop) ----------

def _vtex(price: float, installments: list, teasers: list | None = None) -> list:
    of = {"Price": price, "ListPrice": 4359.0, "AvailableQuantity": 1, "Teasers": teasers or [],
          "DiscountHighLight": [], "Installments": installments}
    return [{"productId": "114589", "link": "https://site.fastshop.com.br/x/p",
             "productName": "Smart TV 4K TCL QD-Mini LED 55” Polegadas com HDMI 2.1, Dolby Vision IQ, "
                            "Subwoofer, 144Hz VRR e Wi-Fi - 55C6K",
             "items": [{"sellers": [{"sellerId": "1", "sellerName": "Fast Shop", "commertialOffer": of}]}]}]


def test_nf4_pix_nas_parcelas_da_fast_shop():
    # vtex_fastshop.json de 18/09 (AvailableQuantity simulado): Price 3350, Pix 1x 3149, cartão 12x com juros
    inst = [{"PaymentSystemName": "Visa", "NumberOfInstallments": 1, "Value": 3350.0, "InterestRate": 0.0},
            {"PaymentSystemName": "Visa", "NumberOfInstallments": 12, "Value": 306.93, "InterestRate": 1.49},
            {"PaymentSystemName": "Pix", "NumberOfInstallments": 1, "Value": 3149.0, "InterestRate": 0.0}]
    [o] = vtex.parse_catalogo(_vtex(3350.0, inst), "Fast Shop", "https://site.fastshop.com.br")
    assert o.preco == 3350.0 and o.preco_pix == 3149.0 and o.melhor_preco == 3149.0
    assert o.parcelado is None  # 12x com juros não é guardado


def test_nf4_pix_fixture_fast_shop():
    ofs = vtex.parse_catalogo(json.loads(le("fastshop_vtex.json")), "Fast Shop", "https://site.fastshop.com.br")
    fs = [o for o in ofs if o.vendedor == "Fast Shop"]
    assert fs and fs[0].preco == 3296.81 and fs[0].preco_pix == 3099.0
    tcl = [o for o in ofs if o.vendedor == "TCL SEMP"]
    assert tcl and tcl[0].preco_pix is None  # Pix 1x igual ao preço: não há desconto


def test_nf4_pix_menor_entre_teaser_e_parcelas():
    inst = [{"PaymentSystemName": "Pix", "NumberOfInstallments": 1, "Value": 3700.0, "InterestRate": 0.0}]
    [o] = vtex.parse_catalogo(_vtex(4000.0, inst, [{"<Name>k__BackingField": "5% no Pix"}]), "Fast Shop", "b")
    assert o.preco_pix == 3700.0


# ---------- N-F5 / N-F7: Zoom é agregador; cartão, Pix e parcelas do estado da página ----------

def _zoom_html(offer_list: list, jsonld_offers: list) -> str:
    ld = {"@context": "https://schema.org", "@type": "Product", "name": 'Smart TV Mini LED 55" TCL 4K 55C6K',
          "offers": {"@type": "AggregateOffer", "offers": jsonld_offers}}
    nd = {"props": {"initialReduxState": {"offers": {"offerList": offer_list}}}}
    return (f'<script type="application/ld+json">{json.dumps(ld)}</script>'
            f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script>')


def _ld(oid: str, loja: str, preco: float) -> dict:
    return {"@type": "Offer", "id": oid, "name": "Smart TV TCL 55C6K", "offeredBy": loja, "price": preco,
            "url": f"https://www.zoom.com.br/tv/x?highlightedItemId={oid}"}


def test_nf5_ofertas_do_zoom_saem_marcadas_como_agregador():
    ofs = zoom.parse_produto(le("zoom_produto.html"))
    assert len(ofs) == 6  # nenhuma oferta é descartada, só marcada
    assert all(o.extra.get("agregador") is True for o in ofs)
    # sem o estado da página (só JSON-LD) também marca
    html = _zoom_html([], [_ld("1489104908", "Amazon", 3279)])
    [o] = zoom.parse_produto(html)
    assert o.extra.get("agregador") is True and o.preco == 3279.0


def test_nf7_zoom_le_cartao_pix_e_parcelas_do_estado():
    # valores do offerList de 18/09 (Magazine Luiza/Colombo, Amazon, KaBuM!) e uma oferta com juros
    estado = [
        {"id": "1561988278", "price": 3937.15, "totalPrice": 4101.2, "numParcels": 10, "parcelValue": 410.12,
         "hasInterest": True},
        {"id": "1489104908", "price": 3279, "totalPrice": 3279, "numParcels": 0, "parcelValue": 0, "hasInterest": True},
        {"id": "1572257801", "price": 4184.88, "totalPrice": 4184.8, "numParcels": 10, "parcelValue": 418.48,
         "hasInterest": False},
        {"id": "999", "price": 3500, "totalPrice": 3500, "numParcels": 12, "parcelValue": 330.0, "hasInterest": True},
    ]
    ld = [_ld("1561988278", "Magazine Luiza", 3937.15), _ld("1489104908", "Amazon", 3279),
          _ld("1572257801", "KaBuM!", 4184.88), _ld("999", "Loja X", 3500)]
    ofs = {o.id: o for o in zoom.parse_produto(_zoom_html(estado, ld))}
    colombo = ofs["1561988278"]
    assert (colombo.preco, colombo.preco_pix, colombo.parcelado) == (4101.2, 3937.15, "10x R$ 410,12 sem juros")
    assert (ofs["1489104908"].preco, ofs["1489104908"].preco_pix, ofs["1489104908"].parcelado) == (3279.0, None, None)
    assert ofs["1572257801"].preco == 4184.88 and ofs["1572257801"].preco_pix is None
    assert ofs["1572257801"].parcelado == "10x R$ 418,48 sem juros"
    assert ofs["999"].parcelado is None  # 12x 330 = 3960 > 3500: com juros, não é guardado


def test_nf7_zoom_fixture_magalu():
    ofs = {o.id: o for o in zoom.parse_produto(le("zoom_produto.html"))}
    o = ofs["1484766165"]  # bate com magalu_produto.html: 3899 no cartão, 3704,05 no Pix, 10x 389,90 sem juros
    assert (o.preco, o.preco_pix, o.parcelado) == (3899.0, 3704.05, "10x R$ 389,90 sem juros")


# ---------- N-F6: filtro do Telegram na linha-título ----------

def test_nf6_descricao_nao_derruba_postagem():
    o = um_post("🔥 🔥",
                "Suporte a HDR10+ e IMAX Enhanced, controle remoto com comando de voz, base de metal e pedestal.",
                'PARCELADO | Smart TV TCL 55" QD-Mini LED 55C6K | CUPOM + PIX', "A partir de R$ 3.349,00")
    assert o.preco == 3349.0 and "55C6K" in o.titulo


def test_nf6_titulo_com_suporte_a_recurso():
    t = '🔥 Smart TV TCL 55" QD-Mini LED 55C6K com suporte a Dolby Vision IQ, HDR10+ e 144Hz / CUPOM + PIX / A partir de R$ 3.349,00'
    assert motivo_rejeicao(t) == ""
    o = um_post('🔥 Smart TV TCL 55" QD-Mini LED 55C6K com suporte a Dolby Vision IQ, HDR10+ e 144Hz',
                "CUPOM + PIX", "A partir de R$ 3.349,00")
    assert o.preco == 3349.0


def test_nf6_filtro_continua_barrando():
    assert telegram_public.parse_canal(canal("Controle comando de voz para TV TCL 55C6K", "R$ 149,99"), "c") == []
    assert telegram_public.parse_canal(canal("Smart TV TCL 55C6K", "TV reembalada, R$ 2.999"), "c") == []
    assert telegram_public.parse_canal(canal("Smart TV TCL 65C6K", "R$ 4.999"), "c") == []
    # tamanho na linha de cima do modelo: janela curta
    assert linha_55c6k("Smart TV TCL 55 polegadas QD-Mini LED\n4K C6K Google TV\nR$ 3.599 no Pix")


# ---------- N-F8: vendedor do marketplace da KaBuM! ----------

def test_nf8_kabum_vendedor_do_marketplace():
    o = kabum.parse_api(json.loads(le("kabum_api.json")))
    assert o and o.vendedor == "FAST SHOP"
    base = {"title": "Smart TV TCL 55 Polegadas QD-Mini LED 4K C6K WiFi Bluetooth Google TV 4 HDMI 144Hz HDR10+ 55C6K",
            "price": 4184.88, "price_with_discount": 4184.88, "available": True, "max_installment": "10x de R$ 418,48"}
    mkp = kabum.parse_api({"id": 911482, "attributes": dict(base, is_marketplace=True, seller_type="3P",
                                                            marketplace={"seller_name": "LOJAS COLOMBO"})})
    assert mkp.vendedor == "LOJAS COLOMBO"
    propria = kabum.parse_api({"id": 911482, "attributes": dict(base, is_marketplace=False, seller_type="1P")})
    assert propria.vendedor == "KaBuM!"


# ---------- N-F10: código de cupom falso ----------

def test_nf10_cupom_falso():
    for t in ["CUPOM DISPONÍVEL NA PÁGINA", "CUPOM ATIVADO NO LINK", "CUPOM MERCADO PAGO", "CUPOM PRIMEIRA COMPRA",
              "cupom disponível no app"]:
        assert cupom_no_texto(t) is None, t
    assert cupom_no_texto("Use o cupom SOLTAODESCONTO na finalização") == "SOLTAODESCONTO"
    assert cupom_no_texto("Cupom: TV300 (R$ 300 OFF)") == "TV300"
    o = um_post("Smart TV TCL 55C6K Mini LED", "R$ 3.599,09 no Pix", "CUPOM DISPONÍVEL NA PÁGINA")
    assert o.cupom is None and o.preco == 3599.09


# ================================================================ rodada 2: regressões do verificador

class _EstadoMemoria:
    """Estado vazio em memória (não lê nem grava docs/data), fora do bootstrap."""
    bootstrap = False

    def minimo(self):
        return None

    def oferta_anterior(self, chave):
        return None

    def cupom_anterior(self, chave):
        return None


def _alertas_do_post(o, monkeypatch) -> list[str]:
    monkeypatch.setattr(config, "ALVO_PIX", 2900.0)
    monkeypatch.setattr(config, "ALVO_PARCELADO", 3000.0)
    o.publicado = None  # sem data: o teste não depende do dia em que roda
    msgs, _ = regras.gerar_alertas(_EstadoMemoria(), [o], [])
    return msgs


# ---------- REG-1: postagem com vários produtos (preço de outra TV virava o da 55C6K, com 🎯 falso) ----------

def test_reg1_multiproduto_preco_vem_do_bloco_da_55c6k(monkeypatch):
    # casos exatos do verificador: rodada 1 dava 1799 e 2799 (menor valor da mensagem) e alerta 🎯
    o = um_post('Smart TV TCL 55" 55C6K: R$ 3.599', 'Smart TV TCL 43" 43S5K: R$ 1.799')
    assert o.preco == 3599.0
    msgs = _alertas_do_post(o, monkeypatch)
    assert len(msgs) == 1 and "📣" in msgs[0] and "🎯" not in msgs[0] and "R$ 1.799" not in msgs[0]
    o = um_post('55" 55C6K — R$ 3.599 no Pix', '65" 65P7K — R$ 2.799 no Pix')
    assert o.preco == 3599.0
    assert "🎯" not in _alertas_do_post(o, monkeypatch)[0]


def test_reg1_controle_o_alerta_alvo_continua_para_a_55c6k(monkeypatch):
    # o 🎯 ainda sai quando é a própria 55C6K abaixo do alvo (o teste acima não passa por acaso)
    o = um_post('Smart TV TCL 55" 55C6K: R$ 2.799 no Pix', 'Smart TV TCL 43" 43S5K: R$ 1.799')
    assert o.preco == 2799.0
    assert "🎯" in _alertas_do_post(o, monkeypatch)[0]


def test_reg1_outras_formas_de_postagem_com_varios_produtos():
    # outra TV com o tamanho sem aspas (e o preço dela marcado "no Pix"): o valor da linha dela sai
    o = um_post("Smart TV TCL 55C6K: R$ 3.599", "Smart TV TCL 50 P7L: R$ 2.069 no Pix")
    assert o.preco == 3599.0
    # tudo na mesma linha
    o = um_post('Smart TV TCL 55" 55C6K: R$ 3.599 | Smart TV Samsung 43" Crystal: R$ 1.799 no Pix')
    assert o.preco == 3599.0
    # rodada 3: quando o outro produto aparece numa linha SEM preço (o preço dele vem nas linhas de baixo),
    # a postagem inteira sai, como na main — a rodada 2 esperava 3599 aqui; a orientação da rodada 3 aceita
    # rejeitar para nunca arriscar o preço do outro produto
    for linhas in [('Smart TV TCL 43" 43S5K', "R$ 1.799 no Pix", 'Smart TV TCL 55" 55C6K', "R$ 3.599 no Pix"),
                   ("Smart TV TCL 55C6K", "R$ 3.599", "Smart TV Samsung Crystal UHD", "R$ 2.299 no Pix"),
                   ("Smart TV TCL 55C6K", "R$ 3.599", "Smart TV TCL 43S5K", "R$ 1.799 ou 10x de R$ 179,90 sem juros",
                    "Cupom TCL43")]:
        assert telegram_public.parse_canal(canal(*linhas), "canal") == [], linhas


def test_reg1_postagem_de_um_produto_usa_a_mensagem_toda():
    titulo, trecho = bloco_55c6k("Use o cupom SOLTAODESCONTO\nSmart TV TCL 55C6K | CUPOM + PIX\nA partir de R$ 3.349,00")
    assert "55C6K" in titulo and "SOLTAODESCONTO" in trecho and "3.349" in trecho
    o = um_post("Use o cupom SOLTAODESCONTO", "Smart TV TCL 55C6K | CUPOM + PIX", "A partir de R$ 3.349,00")
    assert (o.preco, o.cupom) == (3349.0, "SOLTAODESCONTO")


# ---------- REG-2: parcelado_no_texto pulava a "com juros" e pegava a "sem juros" de outro produto ----------

CB_TOPO_E_PATROCINADO = """por R$ 3.998,99
R$ 3.998,99 em até 11x de R$ 399,83 com juros (1.62% a.m) no cartão de crédito.
por R$ 3.599,09
No Pix com 10% de desconto
Produtos Patrocinados
Smart TV TCL QLED 50 Polegadas 4K HDR10 HDMI Wi-Fi 50P7K
por R$ 3.416,60 ou em até 6x de R$ 569,43 sem juros ou
"""


def test_reg2_parcelado_nao_pula_para_a_parcela_de_outro_produto():
    # caso do verificador: rodada 1 devolvia '6x R$ 569,43 sem juros' (TV patrocinada de R$ 3.416,60)
    assert parcelado_no_texto(CB_TOPO_E_PATROCINADO) is None
    # 1ª parcela sem rótulo (no ML, sem rótulo é com juros): também não pula para a seguinte
    assert parcelado_no_texto("10x de R$ 399,90 ou 12x de R$ 350,00 sem juros") is None
    # 1x não é parcelamento
    assert parcelado_no_texto("1x de R$ 3.599,09 sem juros") is None


def test_reg2_parcelado_sem_juros_explicito_continua():
    assert parcelado_no_texto("ou 10x de R$ 399,90 sem juros") == "10x R$ 399,90 sem juros"
    assert parcelado_no_texto("Em até 12x R$ 312,49 sem juros Ver opções") == "12x R$ 312,49 sem juros"
    assert parcelado_no_texto("10x sem juros de R$ 399,90") == "10x R$ 399,90 sem juros"
    assert parcelado_no_texto("10x R$ 399,90 (s/ juros)") == "10x R$ 399,90 sem juros"


def test_reg2_parcelado_snapshot_casas_bahia():
    arq = SNAP / "casasbahia_produto.txt"
    if not arq.exists():
        pytest.skip("snapshot da Casas Bahia não está nesta máquina")
    assert parcelado_no_texto(arq.read_text(encoding="utf-8")) is None


# ---------- REG-3: "TV + suporte de parede / articulado / kit" voltou a passar ----------

def test_reg3_tv_com_suporte_de_parede_e_barrada():
    for t in ["Smart TV TCL 55C6K com suporte à parede", "Smart TV TCL 55C6K + Suporte a Parede Articulado",
              "Smart TV TCL 55C6K + Kit Suporte Articulado", "Kit Smart TV TCL 55C6K + Suporte de Parede",
              "Smart TV TCL 55C6K e Suporte Articulado para TV", "Suporte a TV TCL 55C6K"]:
        assert motivo_rejeicao(t).startswith(("negativo", "acessório")), t


def test_reg3_suporte_a_recurso_tecnico_continua_aceito():
    for t in ["Smart TV TCL 55C6K com suporte a HDR10+, Wi-Fi e Bluetooth",
              "Smart TV TCL 55C6K QD-Mini LED com suporte ao Dolby Atmos e HDMI 2.1",
              "Smart TV TCL 55C6K suporte a 4K 144Hz",
              '🔥 Smart TV TCL 55" QD-Mini LED 55C6K com suporte a Dolby Vision IQ, HDR10+ e 144Hz']:
        assert motivo_rejeicao(t) == "", t


# ---------- REG-4: "R$ 3.599 por tempo limitado" perdia o preço ----------

def test_reg4_por_depois_do_valor_nao_e_de_por():
    o = um_post("Smart TV TCL 55C6K", "R$ 3.599 por tempo limitado", "ou 10x de R$ 399,90 sem juros")
    assert o.preco == 3599.0 and o.parcelado == "10x R$ 399,90 sem juros"
    assert preco_postagem("R$ 3.599 por tempo limitado") == 3599.0
    # o "De/por" de verdade continua descartando o preço antigo
    assert preco_postagem("R$ 4.199 por R$ 3.599") == 3599.0
    assert preco_postagem("De R$ 4.199 por R$ 3.599 no Pix") == 3599.0
    assert preco_postagem("Caiu de R$ 4.199 para R$ 3.599") == 3599.0


def test_reg4_preco_riscado_e_ignorado():
    html = canal("Smart TV TCL 55C6K", "<s>R$ 4.199</s> R$ 3.599")
    [o] = telegram_public.parse_canal(html, "canal")
    assert o.preco == 3599.0


# ---------- REG-5: janela curta demais e negativos amplos ----------

def test_reg5a_tamanho_ate_3_linhas_do_modelo():
    # caso do verificador: '55"' na linha 1 e 'Modelo C6K' na linha 4 (a rodada 1 descartava)
    o = um_post('Smart TV TCL 55"', "QD-Mini LED 4K", "Google TV 144Hz", "Modelo C6K", "R$ 3.599 no Pix")
    assert o.preco == 3599.0 and "C6K" in o.titulo
    # mensagem só de um produto: o tamanho pode estar em qualquer linha
    o = um_post("Smart TV TCL", "Modelo C6K", "QD-Mini LED", "4K", "144Hz", "Google TV", 'Tela de 55"', "R$ 3.599")
    assert o.preco == 3599.0


def test_reg5a_janela_nao_atravessa_outro_produto():
    # o 55" é da Samsung da linha de cima: não serve de tamanho para o "C6K" sem tamanho
    assert linha_55c6k('Smart TV Samsung 55" Crystal R$ 2.299\nTCL C6K Mini LED\nR$ 3.599') is None
    assert linha_55c6k("Smart TV TCL C6K\nR$ 55,00 de desconto\nR$ 3.599") is None  # "R$ 55" não é tamanho


def test_reg5b_titulos_de_tv_com_controle_display_e_para_tv():
    for t in ['Smart TV TCL 55" QD-Mini LED 4K 55C6K com Controle por Voz', "Smart TV TCL 55C6K QD-Mini LED Display 144Hz",
              'Smart TV TCL 55" 55C6K ideal para TV e games', "Smart TV TCL 55C6K com Controle Remoto",
              "TCL 55C6K c/ comando de voz", "Smart TV TCL 55C6K Google TV Controle Remoto com Voz",
              "TCL 55C6K: controle por voz e 144Hz", "Smart TV TCL 55C6K com suporte a múltiplos formatos HDR"]:
        assert motivo_rejeicao(t) == "", t


def test_reg5b_acessorios_pelo_substantivo_do_produto():
    for t in ["TCL 55C6K Controle Remoto Original", "Controle Remoto Compatível TV TCL 55C6K",
              "Novo Controle Remoto TCL 55C6K", "Suporte para TV TCL 55C6K", "Cabo de força para TV TCL 55C6K",
              "Fita de LED para TV TCL 55C6K", "Display para TV TCL 55C6K", "Para TV TCL 55C6K - Controle",
              "TV Box para TV TCL 55C6K", "Kit 2 Controles para TV TCL 55C6K", "Controle por voz para TV TCL 55C6K"]:
        assert not eh_55c6k(t), t


# ---------- N-F3 (pendente na rodada 1): mínimo do cupom sem marcador de Pix ----------

@pytest.mark.parametrize("cupom", [
    "Cupom TV300 (mín. R$ 2.500)", "compra mínima de R$ 2.500", "em pedidos a partir de R$ 2.500",
    "a partir de R$ 2.500 em compras", "gastando R$ 2.500", "(R$300 OFF > R$2.500)",
])
def test_nf3_minimo_do_cupom_sem_marcador(cupom, monkeypatch):
    # sem "Pix"/"à vista" na linha do preço, a rodada 1 pegava o menor valor (2.500, abaixo do alvo: 🎯 falso)
    o = um_post("Smart TV TCL 55C6K", "R$ 3.599", cupom)
    assert o.preco == 3599.0
    assert "🎯" not in _alertas_do_post(o, monkeypatch)[0]
    # linha do cupom antes do título também não vira preço
    assert um_post(cupom, "Smart TV TCL 55C6K", "R$ 3.599").preco == 3599.0


def test_nf3_vale_o_menor_valor_que_sobra():
    # rodada 3: o verificador da rodada 2 mostrou que "o 1º valor" perde o preço com cupom e o da seta
    # ("R$ 3.199" + "Com o cupom TCL300: R$ 2.899" -> 2899). O menor valor que sobra depois de tirar mínimo do
    # cupom, desconto, parcela e "De" é o preço; o de outro produto já saiu no filtro.bloco_55c6k.
    assert preco_postagem("R$ 3.199\nCom o cupom TCL300: R$ 2.899") == 2899.0
    assert preco_postagem("R$ 4.199 ➡️ R$ 3.599") == 3599.0
    assert preco_postagem("R$ 3.599 no cartão ou R$ 3.419 no Pix") == 3419.0
    assert preco_postagem("Por R$ 3.599 ou R$ 3.419 no Pix") == 3419.0
