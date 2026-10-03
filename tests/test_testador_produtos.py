"""Testador de cupons com o PS5 e o GTA 6 (pedido do usuário em 03/10/2026).

03/10: "o testador de cupons PODE usar os carrinhos para PS5/GTA 6 (mesmas regras: só o produto monitorado, 1 unidade,
nunca mexe no resto, nunca finaliza)". O carrinho termina a rodada com UM item de cada produto PRINCIPAL (PS5 Digital,
PS5 com leitor, PS5 Pro, GTA 6 Code in Box; e as TVs fora do modo vigia). Kit/pacote/gift card (os CAMINHOS) só são
testados quando são o caminho mais barato para um principal e nunca ficam no carrinho. Cada cupom é medido com o
produto sozinho no carrinho. Modo vigia (TV comprada): as TVs ficam fora do testador; o PS5 e o GTA 6 seguem.

Tudo com páginas e carrinhos falsos (nenhum navegador de verdade, nenhum perfil de loja).
"""

import json
import re
import sys

import pytest

from monitor import config, produtos
from monitor.carrinho import (
    CAMINHOS, PRINCIPAIS, Amazon, CarrinhoOcupado, Magalu, MercadoLivre, ResultadoCupom, eh_do_modelo, eh_servico,
    modelo_da_linha, produto_do_titulo, titulo_confere,
)
from test_carrinho import MAGALU_1P, PaginaMagalu, PaginaML, _Loc
from test_testador_anuncios import (  # noqa: F401 - ambiente do testador (dados, relógio, sessão falsa)
    FIXO, A, KA, _iso, _rec, amb, oferta_magalu, tc,
)

PS5D = "Console PlayStation 5 Edição Digital 825GB 1 Controle Branco Sony"
PS5D_2J = "Console Sony PlayStation 5 SSD 825GB Controle sem fio DualSense 2 Jogos Digitais Edição Digital"
PS5DISCO = "PlayStation 5 Slim Disk 1TB 1 Controle Branco Sony"
PS5PRO = "Console PlayStation 5 Pro Sony SSD 2TB Branco"
GTA = "Jogo Grand Theft Auto VI (GTA 6) PS5 - Code in Box Pré-venda - Lançamento 19/11"
KIT = "Console PlayStation 5 Digital Edição Limitada Wolverine"
CONTROLE = "Controle DualSense PS5 Branco"


def _oferta(pid, pix, cartao, titulo, produto, seller="magazineluiza", vendedor="Magalu", **kw):
    return oferta_magalu(pid, seller, vendedor, pix, cartao=cartao, titulo=titulo, modelo=produto, **kw)


O_PS5D = _oferta("240604800", 4231.0, 4549.0, PS5D, "PS5_DIGITAL")
O_PS5D2 = _oferta("240590700", 4277.0, 4599.0, PS5D_2J, "PS5_DIGITAL")
O_DISCO = _oferta("240609000", 4691.08, 5099.0, PS5DISCO, "PS5_DISCO")
O_GTA = _oferta("241923300", 418.41, 449.90, GTA, "GTA6_CODE_IN_BOX", cupom="GTA60")
O_GTA["extra"].update(entrega_prevista="2026-11-16", cep_referencia=True)
O_KIT = _oferta("kitwolv001", 4100.0, 4400.0, KIT, "PS5_KIT")
K_PS5D, K_PS5D2 = "240604800-magazineluiza", "240590700-magazineluiza"
K_DISCO, K_GTA, K_KIT = "240609000-magazineluiza", "241923300-magazineluiza", "kitwolv001-magazineluiza"
PRODUTO_DA_CHAVE = {KA: "55C6K", K_PS5D: "PS5_DIGITAL", K_PS5D2: "PS5_DIGITAL", K_DISCO: "PS5_DISCO",
                    K_GTA: "GTA6_CODE_IN_BOX", K_KIT: "PS5_KIT"}
PRECOS = {KA: 3561.55, K_PS5D: 4231.0, K_PS5D2: 4277.0, K_DISCO: 4691.08, K_GTA: 418.41, K_KIT: 4100.0}

CUPONS = [
    {"loja": "Magazine Luiza", "codigo": "GAMES10", "fonte": "pelando", "titulo": "10% OFF em Games e Consoles"},
    {"loja": "Magazine Luiza", "codigo": "MODA20", "fonte": "pelando", "titulo": "20% OFF em Moda e Acessórios"},
    {"loja": "Magazine Luiza", "codigo": "TVS200", "fonte": "pelando", "titulo": "R$ 200 OFF em Smart TVs"},
]


def _latest(amb, ofertas, cupons=CUPONS, posts=()):
    d = {"modo": "cloud", "ofertas_loja": list(ofertas), "cupons": list(cupons), "posts": list(posts)}
    (config.DIR_DADOS / "latest_cloud.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def vigia(monkeypatch):
    """Modo vigia (TV comprada em 03/10): as TVs fora do testador."""
    monkeypatch.setattr(tc, "_DESLIGADOS", frozenset(produtos.TVS))


class CarrinhoProdutos(Magalu):
    """Identidade real do Magalu; carrinho falso com as chaves dos anúncios (como o CarrinhoDoisModelos das TVs).

    garantir_item isola o anúncio: tira o resto só se o resto é restaurável (alvo['restauraveis']) ou caminho
    (alvo['descartaveis']), senão CarrinhoOcupado; garantir_itens deixa os pedidos, tira o anúncio errado de um produto
    pedido e o caminho, e mantém o resto. `aceita`: {(chave, código): desconto} medido com o produto sozinho."""

    def __init__(self, pasta, carrinho=(), aceita=None, nao_entra=(), entregas=None):
        self.pasta = pasta
        self.carrinho = list(carrinho)
        self.aceita = dict(aceita or {})
        self.nao_entra = set(nao_entra)
        self.entregas = dict(entregas or {})   # chave -> data de entrega que o carrinho mostra com ela sozinha
        self.eventos: list[tuple] = []
        self.alvos: list[dict] = []

    def perfil(self):
        return self.pasta

    def ler_entrega(self, page):
        return self.entregas.get(self.carrinho[0]) if len(self.carrinho) == 1 else None

    def _tira(self, chaves):
        for c in list(chaves):
            self.carrinho.remove(c)
            self._tirou(PRODUTO_DA_CHAVE.get(c))

    def garantir_item(self, page, url, alvo=None):
        chave = alvo["chave"]
        self.alvos.append(alvo)
        self.eventos.append(("garantir", chave))
        if self.carrinho == [chave]:
            return True
        livres = set(alvo.get("restauraveis") or ()) | set(alvo.get("descartaveis") or ()) | {alvo["modelo"]}
        sem_volta = {PRODUTO_DA_CHAVE[c] for c in self.carrinho} - livres
        if sem_volta:
            raise CarrinhoOcupado(f"tem {sem_volta} e não sei devolver")
        if chave in self.nao_entra:
            return False
        self._tira(self.carrinho)
        self.carrinho = [chave]
        return True

    def garantir_itens(self, page, alvos):
        chaves = [a["chave"] for a in alvos]
        self.alvos.extend(alvos)
        self.eventos.append(("garantir_itens", tuple(chaves)))
        pedidos = {a["modelo"] for a in alvos}
        descartaveis = set().union(*(set(a.get("descartaveis") or ()) for a in alvos))
        ok = [c for c in chaves if c not in self.nao_entra]
        self._tira([c for c in self.carrinho if c not in ok and PRODUTO_DA_CHAVE[c] in pedidos | descartaveis])
        for c in ok:
            if c not in self.carrinho:
                self.carrinho.append(c)
        return set(ok)

    def _res(self, codigo, desconto=0.0):
        soma = sum(PRECOS[c] for c in self.carrinho)
        return ResultadoCupom(codigo=codigo, aceito=bool(desconto), produtos=soma, frete=0.0, desconto=desconto or None,
                              total_pix=round(soma - desconto, 2), total_cartao=round(soma * 1.075 - desconto, 2),
                              parcelado="10x R$ 454,90 sem juros", quantidade=max(1, len(self.carrinho)))

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


def _rodar(amb, loja, estado=None):
    return amb.rodar(loja, estado)


# ------------------------------------------------------------------------------------------------
# 1. qual produto é qual: título, id, catálogo; caminho só pelo id; serviço nunca
# ------------------------------------------------------------------------------------------------

def test_produto_do_titulo_reconhece_os_principais_e_nada_mais():
    assert produto_do_titulo(PS5D) == "PS5_DIGITAL" and produto_do_titulo(PS5DISCO) == "PS5_DISCO"
    assert produto_do_titulo(PS5PRO) == "PS5_PRO" and produto_do_titulo(GTA) == "GTA6_CODE_IN_BOX"
    assert produto_do_titulo('Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz Google TV') == "55C6K", "as TVs como sempre"
    # linha do carrinho do ML: o título numa linha, o resto (vendedor, preço, botões) nas outras
    assert produto_do_titulo(PS5D + "\nVendido por PlayStation\nR$ 4.369\nExcluir\nSalvar") == "PS5_DIGITAL"
    for t in (CONTROLE, "Jogo Marvel's Spider-Man 2 PS5", "Air Fryer Mondial 4L", "Gift Card PlayStation R$ 100",
              KIT, "Pacote GTA VI + PS5 Slim Digital Astro Bot GT7", "Console PS5 Slim Digital Usado"):
        assert produto_do_titulo(t) is None, t
    assert produto_do_titulo(PS5D + "\n" + GTA) is None, "dois produtos no mesmo bloco: na dúvida, nenhum"
    assert eh_servico("Garantia Estendida 12 meses - Console PS5")
    assert modelo_da_linha("Garantia Estendida 12 meses - Console PS5") is None, "serviço com o nome do PS5 não é o PS5"
    assert not eh_servico(PS5D + "\nGarantia de 12 meses")


def test_titulo_da_pagina_confere_o_produto_com_o_id():
    assert titulo_confere(GTA, "GTA6_CODE_IN_BOX", "Magazine Luiza", "241923300")
    assert not titulo_confere(PS5D, "GTA6_CODE_IN_BOX", "Magazine Luiza")
    # o título do pacote com 2 jogos digitais: o id do anúncio (catálogo) diz que é o PS5 Digital
    assert titulo_confere(PS5D_2J, "PS5_DIGITAL", "Magazine Luiza", "240590700")
    assert eh_do_modelo(KIT, "PS5_KIT") and not eh_do_modelo(KIT, "PS5_DIGITAL")
    assert titulo_confere('Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz', "55C6K"), "a TV como sempre"


def test_principais_e_caminhos():
    assert PRINCIPAIS == ("55C6K", "65C6K", "PS5_DIGITAL", "PS5_DISCO", "PS5_PRO", "GTA6_CODE_IN_BOX")
    assert set(CAMINHOS) == {"PS5_DIGITAL_GTA6", "PS5_DISCO_GTA6", "PS5_KIT", "GIFT_CARD_PSN"}


# ------------------------------------------------------------------------------------------------
# 2. anúncios da coleta: produto, meta da oferta, entrega do GTA, caminho com o equivalente
# ------------------------------------------------------------------------------------------------

def test_anuncios_por_produto_com_meta_e_entrega(amb):
    _latest(amb, [O_GTA, O_PS5D2, O_DISCO, O_PS5D, A])
    _, anuncios = tc.codigos_conhecidos(CarrinhoProdutos(amb.pasta))
    grupos = tc.por_modelo(anuncios)
    assert list(grupos) == ["55C6K", "PS5_DIGITAL", "PS5_DISCO", "GTA6_CODE_IN_BOX"], "TVs primeiro, depois o catálogo"
    assert [a.chave for a in grupos["PS5_DIGITAL"]] == [K_PS5D, K_PS5D2], "do mais barato ao mais caro"
    ps5 = grupos["PS5_DIGITAL"][0]
    assert (ps5.alvo_pix, ps5.alvo_parcelado) == (3550.0, 3700.0)
    gta = grupos["GTA6_CODE_IN_BOX"][0]
    assert (gta.alvo_pix, gta.alvo_parcelado) == (345.0, 370.0) and "chega a tempo" in gta.entrega
    ctx = tc.contexto_do_carrinho(anuncios, "Magazine Luiza")
    assert ctx["ids_modelo"]["241923300"] == "GTA6_CODE_IN_BOX" and ctx["ids_modelo"]["240604800"] == "PS5_DIGITAL"
    assert set(ctx["descartaveis"]) == set(CAMINHOS)
    alvo = gta.alvo((), ctx)
    assert alvo["modelo"] == "GTA6_CODE_IN_BOX" and set(alvo["descartaveis"]) == set(CAMINHOS)


def test_anuncio_que_nao_e_o_produto_nao_vai_ao_carrinho(amb):
    controle = _oferta("ctrl000001", 399.0, 449.0, CONTROLE, "PS5_DIGITAL")       # título de acessório
    usado = _oferta("usado00001", 2999.0, 3199.0, PS5D + " Usado", "PS5_DIGITAL")
    barato_demais = _oferta("x000000001", 999.0, 1099.0, PS5D, "PS5_DIGITAL")   # fora da faixa do produto
    leitor = _oferta("leitor0001", 290.0, 320.0, "Leitor de Disco para PS5 Slim Digital e Pro", "LEITOR_PS5")
    _latest(amb, [O_PS5D, controle, usado, barato_demais, leitor])
    _, anuncios = tc.codigos_conhecidos(CarrinhoProdutos(amb.pasta))
    assert [a.chave for a in anuncios] == [K_PS5D], "acessório, usado, preço impossível e produto fora do carrinho: não"


def test_kit_entra_so_quando_e_o_caminho_mais_barato(amb):
    _latest(amb, [O_PS5D, O_KIT])
    _, anuncios = tc.codigos_conhecidos(CarrinhoProdutos(amb.pasta))
    kit = next(a for a in anuncios if a.chave == K_KIT)
    assert (kit.modelo, kit.caminho, kit.equivalente) == ("PS5_KIT", "PS5_DIGITAL", 3900.0), "4.100 - R$ 200 da edição"
    assert [a.chave for a in tc.por_modelo(anuncios)["PS5_DIGITAL"]] == [K_KIT, K_PS5D], "caminho mais barato primeiro"
    caro = _oferta("kitwolv001", 4500.0, 4800.0, KIT, "PS5_KIT")
    _latest(amb, [O_PS5D, caro])
    _, anuncios = tc.codigos_conhecidos(CarrinhoProdutos(amb.pasta))
    grupos = tc.por_modelo(anuncios)
    assert [a.chave for a in grupos["PS5_DIGITAL"]] == [K_PS5D], "equivale a 4.300 > 4.231: não é caminho"
    assert [a.chave for a in tc.caminhos_fora(anuncios, grupos)] == [K_KIT]
    _latest(amb, [O_KIT])
    _, anuncios = tc.codigos_conhecidos(CarrinhoProdutos(amb.pasta))
    assert tc.por_modelo(anuncios) == {}, "sem anúncio do principal na loja: o caminho não é testado"


def test_gift_card_so_de_loja_oficial_e_vira_caminho_do_gta():
    ml = MercadoLivre()
    url = "https://produto.mercadolivre.com.br/MLB-50200776-gift-card-playstation-r-100-_JM"
    base = {"fonte": "mercadolivre", "tipo": "loja", "loja": "Mercado Livre", "titulo": "Gift Card PlayStation R$ 100",
            "url": url, "id": "MLB50200776", "preco": 85.0, "ativo": True, "modelo": "GIFT_CARD_PSN",
            "extra": {"item_id": "MLB50200776"}}
    assert tc.anuncio_da_oferta(ml, dict(base, vendedor="Loja Qualquer")) is None, "gift card fora da loja oficial: não"
    oficial = dict(base, vendedor="PlayStation", extra={"item_id": "MLB50200776", "vendedor_id": "1047493289"})
    a = tc.anuncio_da_oferta(ml, oficial)
    assert (a.caminho, a.equivalente) == ("GTA6_CODE_IN_BOX", round(449.90 * 85 / 100, 2)), "GTA 6 digital com ele"
    assert (a.alvo_pix, a.alvo_parcelado) == (85.0, 85.0), "meta do gift card: 15% de desconto sobre o valor de face"


def test_modo_vigia_tira_as_tvs_do_testador(amb, vigia):
    _latest(amb, [A, O_PS5D])
    _, anuncios = tc.codigos_conhecidos(CarrinhoProdutos(amb.pasta))
    assert [a.chave for a in anuncios] == [K_PS5D], "a TV comprada fica fora; o PS5 segue"


# ------------------------------------------------------------------------------------------------
# 3. cupons por produto
# ------------------------------------------------------------------------------------------------

def test_cupom_por_produto():
    loja_lista = lambda titulo: [{"tipo": "loja", "cupom": {"loja": "Magazine Luiza", "codigo": "X", "titulo": titulo}}]
    assert tc.compat_do_cupom(loja_lista("10% OFF em Games e Consoles"), "PS5_DIGITAL") == "sim"
    assert tc.compat_do_cupom(loja_lista("20% OFF em Moda e Acessórios"), "PS5_DIGITAL") == "nao"
    assert tc.compat_do_cupom(loja_lista("R$ 200 OFF em Smart TVs"), "PS5_PRO") == "nao", "cupom de TV"
    assert tc.compat_do_cupom(loja_lista("R$ 60 OFF no GTA 6"), "GTA6_CODE_IN_BOX") == "sim"
    assert tc.compat_do_cupom(loja_lista("R$ 60 OFF no GTA 6"), "PS5_DIGITAL") == "nao", "cupom só do jogo"
    # sem a categoria escrita: dúvida (vai depois dos que a regra aceita)
    assert tc.compat_do_cupom(loja_lista("R$ 100 OFF em produtos selecionados"), "PS5_DIGITAL") == "talvez"
    # TVs: como sempre, todo cupom da loja
    assert tc.compat_do_cupom(loja_lista("20% OFF em Moda e Acessórios"), "55C6K") == "sim"
    # cupom da página do anúncio: só o produto dele (o GTA60 do GTA 6 não vai para o PS5 nem para a TV)
    pagina = [{"tipo": "pagina", "produto": "GTA6_CODE_IN_BOX"}]
    assert [tc.compat_do_cupom(pagina, p) for p in ("GTA6_CODE_IN_BOX", "PS5_DIGITAL", "55C6K")] == ["sim", "nao", "nao"]
    # cupom de postagem do PS5: os produtos da mesma família
    post = [{"tipo": "post", "produto": "PS5_DIGITAL"}]
    assert [tc.compat_do_cupom(post, p) for p in ("PS5_PRO", "GTA6_CODE_IN_BOX", "55C6K")] == ["sim", "nao", "nao"]
    assert tc.compat_do_cupom([{"tipo": "post", "produto": None}], "55C6K") == "sim", "postagem antiga: da TV"
    assert tc.compat_do_cupom(None, "PS5_DIGITAL") == "sim", "--codigos: em todos"
    assert tc.compat_do_cupom([{"tipo": "manual"}], "GTA6_CODE_IN_BOX") == "sim", "CUPONS_EXTRA: em todos"


def test_fila_do_produto_poe_a_duvida_depois():
    notas = {("A1", "PS5_DIGITAL"): "talvez", ("B2", "PS5_DIGITAL"): "sim", ("C3", "PS5_DIGITAL"): "nao"}
    assert tc.fila_do_produto(["A1", "B2", "C3"], "PS5_DIGITAL", lambda c, p: notas[(c, p)]) == ["B2", "A1"]
    assert tc.fila_do_produto(["A1", "B2"], "PS5_DIGITAL") == ["A1", "B2"], "sem a regra: todos, na ordem"


# ------------------------------------------------------------------------------------------------
# 4. rodada do testador com o PS5 e o GTA 6 (carrinho falso)
# ------------------------------------------------------------------------------------------------

def test_rodada_com_ps5_e_gta_durante_a_vigia(amb, vigia):
    _latest(amb, [A, O_PS5D, O_PS5D2, O_GTA])
    loja = CarrinhoProdutos(amb.pasta, aceita={(K_PS5D, "GAMES10"): 423.1, (K_GTA, "GTA60"): 60.0})
    aceitos, estado = _rodar(amb, loja)
    # cada cupom só no produto em que vale; o aceito no anúncio mais barato não vai para o mais caro
    assert _aplicados(loja)[:2] == [(K_PS5D, "GAMES10"), (K_GTA, "GTA60")]
    assert KA not in [e[1] for e in loja.eventos if e[0] == "garantir"], "a TV (vigia) não é tocada"
    # fim: um item de cada produto principal e o cupom do pedido (o de maior economia)
    assert loja.eventos[-2] == ("garantir_itens", (K_PS5D, K_GTA))
    assert loja.eventos[-1][0] == "aplicar" and sorted(loja.eventos[-1][1]) == sorted([K_PS5D, K_GTA]) and \
        loja.eventos[-1][2] == "GAMES10"
    assert sorted(loja.carrinho) == sorted([K_PS5D, K_GTA]) and tc.AVISOS_CARRINHO == []
    por = {r.codigo: r for r in aceitos}
    assert por["GAMES10"].extra["no_carrinho"] is True and por["GAMES10"].extra["pedido_so_tvs"] is False
    assert por["GTA60"].extra["cupom_do_pedido"] == "GAMES10"
    cup = estado["magalu"]["cupons"]
    assert cup[f"GTA60@{K_GTA}"]["modelo"] == "GTA6_CODE_IN_BOX" and estado["magalu"]["precos"][K_PS5D]["modelo"] == \
        "PS5_DIGITAL"
    assert not any(k.startswith(("MODA20@", "TVS200@")) for k in cup), "cupom de outra coisa não é testado"
    msg = tc.msg_melhor([("Magazine Luiza", r) for r in aceitos])
    assert "🎮 <b>PS5 Slim Digital</b>" in msg and "🎮 <b>GTA 6 PS5 Code in Box</b>" in msg
    assert msg.index("PS5 Slim Digital") < msg.index("GTA 6 PS5 Code in Box")
    assert "<b>Melhor à vista</b>: R$ 3.807,90" in msg and "<b>Melhor à vista</b>: R$ 358,41" in msg
    assert "Alvo: Pix R$ 3.550,00 · parcelado R$ 3.700,00 — R$ 257,90 acima da meta (7%)" in msg
    assert "Alvo: Pix R$ 345,00 · parcelado R$ 370,00 (chega até 18/11)" in msg
    assert "📦 Entrega: previsão 16/11 (prazo aproximado, CEP de referência) — chega a tempo ✅" in msg
    assert "com 1 unidade de cada produto" in msg and "para o GTA 6 PS5 Code in Box sozinho, o cupom é" in msg
    assert "TV" not in msg.replace("TVS200", "")


def test_tv_no_carrinho_durante_a_vigia_nao_e_tocada(amb, vigia):
    _latest(amb, [A, O_PS5D])
    loja = CarrinhoProdutos(amb.pasta, carrinho=[KA])
    aceitos, estado = _rodar(amb, loja)
    assert loja.eventos == [("garantir", K_PS5D)], "o carrinho tem a TV e ela não é do testador agora"
    assert loja.carrinho == [KA] and aceitos == [] and tc.AVISOS_CARRINHO == []


def test_isolar_o_produto_tira_os_outros_e_o_fim_devolve(amb):
    # só o PS5 tem cupom pendente: o GTA sai para medir e volta no passo final
    _latest(amb, [O_PS5D, O_GTA], cupons=CUPONS[:1])
    estado = {"magalu": {"cupons": {f"GTA60@{K_GTA}": _rec("recusado", FIXO.replace(hour=14))}}}
    loja = CarrinhoProdutos(amb.pasta, carrinho=[K_PS5D, K_GTA])
    _rodar(amb, loja, estado)
    assert [e for e in loja.eventos if e[0] == "aplicar"] == [("aplicar", (K_PS5D,), "GAMES10")]
    assert loja.eventos[-1] == ("garantir_itens", (K_PS5D, K_GTA))
    assert sorted(loja.carrinho) == sorted([K_PS5D, K_GTA]) and tc.AVISOS_CARRINHO == []


def test_produto_que_nao_volta_avisa_com_o_nome_dele(amb):
    _latest(amb, [O_PS5D, O_GTA], cupons=CUPONS[:1])
    estado = {"magalu": {"cupons": {f"GTA60@{K_GTA}": _rec("recusado", FIXO.replace(hour=14))}}}
    loja = CarrinhoProdutos(amb.pasta, carrinho=[K_PS5D, K_GTA], nao_entra={K_GTA})
    _rodar(amb, loja, estado)
    assert loja.carrinho == [K_PS5D]
    (aviso,) = tc.AVISOS_CARRINHO
    assert "o <b>GTA 6 PS5 Code in Box</b>" in aviso and "não consegui devolver" in aviso and "vazia" not in aviso
    assert set(estado["magalu"]["tvs_fora"]) == {"GTA6_CODE_IN_BOX"}, "volta na próxima rodada"


def test_kit_mais_barato_e_testado_mas_nao_fica_no_carrinho(amb):
    _latest(amb, [O_PS5D, O_KIT], cupons=CUPONS[:1])
    loja = CarrinhoProdutos(amb.pasta, aceita={(K_KIT, "GAMES10"): 410.0, (K_PS5D, "GAMES10"): 423.1})
    aceitos, _ = _rodar(amb, loja)
    # o kit primeiro (caminho mais barato); o aceite nele não tira o cupom do PS5 Digital
    assert _aplicados(loja)[:2] == [(K_KIT, "GAMES10"), (K_PS5D, "GAMES10")]
    assert loja.carrinho == [K_PS5D], "o kit nunca fica no carrinho"
    assert all(a.get("descartaveis") for a in loja.alvos), "o adaptador sabe que o kit sai sem volta"
    msg = tc.msg_melhor([("Magazine Luiza", r) for r in aceitos])
    assert msg.startswith("🎯 <b>META ATINGIDA</b>"), "o kit a 3.690 está abaixo da meta dele (3.550 + 200)"
    assert "🧩 Caminho mais barato: PS5 edição especial / kit por R$ 3.690,00" in msg
    assert "equivale a R$ 3.490,00 no PS5 Digital); não fica no carrinho" in msg
    assert "<b>Melhor à vista</b>: R$ 3.807,90" in msg, "o melhor do PS5 Digital em si continua sendo o do anúncio"


def test_entrega_lida_no_carrinho_vale_no_lugar_da_estimativa(amb):
    # o carrinho logado (endereço da conta) diz 25/11: chega DEPOIS do lançamento; a meta cai para R$ 300 / 320
    _latest(amb, [O_GTA], cupons=[])
    loja = CarrinhoProdutos(amb.pasta, aceita={(K_GTA, "GTA60"): 60.0}, entregas={K_GTA: "2026-11-25"})
    aceitos, _ = _rodar(amb, loja)
    (r,) = [x for x in aceitos if x.codigo == "GTA60"]
    assert (r.extra["alvo_pix"], r.extra["alvo_parcelado"]) == (300.0, 320.0)
    msg = tc.msg_melhor([("Magazine Luiza", r)])
    assert "📦 Entrega (lida no carrinho, no seu endereço): previsão 25/11 — ⚠️ chega DEPOIS do lançamento" in msg
    assert "Alvo: Pix R$ 300,00 · parcelado R$ 320,00 (chega depois de 18/11)" in msg
    assert "CEP" not in msg


@pytest.mark.parametrize("texto,data", [
    ("Chega entre 16 e 18 de novembro", "2026-11-18"),
    ("Receba até 18/11", "2026-11-18"),
    ("Entrega GRÁTIS Segunda-feira, 16 de Novembro\nOu entrega mais rápida sábado, 14 de nov.", "2026-11-16"),
    ("Previsão de entrega: 30/11/2026", "2026-11-30"),
    ("Jogo GTA 6 - Pré-venda - Lançamento 19/11\nFrete grátis", None),       # lançamento não é entrega
    ("Devolução grátis até 30/10\nChega amanhã", None),                          # devolução não é entrega
    ("Entrega em até 5 dias úteis", None),
    ("Chega dia 18/11/2025", None),                                               # data velha
])
def test_entrega_no_texto(texto, data):
    from datetime import date

    from monitor.carrinho import entrega_no_texto

    assert entrega_no_texto(texto, date(2026, 10, 3)) == data


def test_caminho_so_e_do_robo_quando_ele_mesmo_o_pos(amb):
    _latest(amb, [O_PS5D, O_KIT])
    _, anuncios = tc.codigos_conhecidos(CarrinhoProdutos(amb.pasta))
    ctx = tc.contexto_do_carrinho(anuncios, "Magazine Luiza")
    assert "kitwolv001" not in ctx["ids_modelo"], "o kit que a pessoa pôs no carrinho dela não é reconhecido"
    postos = {K_KIT: {"id": "kitwolv001", "modelo": "PS5_KIT", "desde": _iso(FIXO)}}
    assert tc.contexto_do_carrinho(anuncios, "Magazine Luiza", postos)["ids_modelo"]["kitwolv001"] == "PS5_KIT"
    # o gift card do catálogo (ids por loja) também não: só os principais saem do catálogo
    assert "MLB50200776" not in tc.contexto_do_carrinho([], "Mercado Livre")["ids_modelo"]
    assert tc.contexto_do_carrinho([], "Mercado Livre")["ids_modelo"]["MLB4214670787"] == "PS5_DIGITAL"


def test_registro_do_caminho_posto_sai_quando_ele_sai_do_carrinho(amb):
    _latest(amb, [O_PS5D, O_KIT], cupons=CUPONS[:1])
    loja = CarrinhoProdutos(amb.pasta, aceita={(K_KIT, "GAMES10"): 410.0})
    _, estado = _rodar(amb, loja)
    assert loja.carrinho == [K_PS5D] and "caminhos_postos" not in estado["magalu"]
    kit_no_alvo = [a for a in loja.alvos if a["chave"] == K_KIT]
    assert kit_no_alvo and kit_no_alvo[0]["ids_modelo"]["kitwolv001"] == "PS5_KIT", "o adaptador reconhece a linha"


def test_caminho_que_ficou_numa_rodada_anterior_sai_na_seguinte(amb):
    # rodada anterior: o kit entrou para medir um cupom e o passo final não o tirou; agora nada pendente
    _latest(amb, [O_PS5D, {k: v for k, v in O_GTA.items() if k != "cupom"}], cupons=[])
    estado = {"magalu": {"cupons": {}, "caminhos_postos": {
        K_KIT: {"id": "kitwolv001", "modelo": "PS5_KIT", "desde": _iso(FIXO.replace(hour=13))}}}}
    loja = CarrinhoProdutos(amb.pasta, carrinho=[K_KIT])
    _rodar(amb, loja, estado)
    assert loja.eventos == [("garantir_itens", (K_PS5D, K_GTA))] and sorted(loja.carrinho) == sorted([K_PS5D, K_GTA])
    assert "caminhos_postos" not in estado["magalu"]
    assert loja.alvos[0]["ids_modelo"]["kitwolv001"] == "PS5_KIT"


def test_kit_que_nao_e_o_caminho_mais_barato_nao_e_testado(amb, capsys):
    caro = _oferta("kitwolv001", 4500.0, 4800.0, KIT, "PS5_KIT")
    _latest(amb, [O_PS5D, caro], cupons=CUPONS[:1])
    loja = CarrinhoProdutos(amb.pasta)
    _rodar(amb, loja)
    assert [e for e in loja.eventos if e[0] == "garantir"] == [("garantir", K_PS5D)]
    assert "não testo (não é o caminho mais barato" in capsys.readouterr().out


def test_orcamento_de_testes_dividido_entre_os_produtos(amb, monkeypatch):
    monkeypatch.setattr(tc, "MAX_APLICACOES_POR_RODADA", 3)
    cupons = [{"loja": "Magazine Luiza", "codigo": c, "fonte": "manual"} for c in ("C1X", "C2X", "C3X")]
    _latest(amb, [O_PS5D, O_DISCO, O_GTA], cupons=[])
    monkeypatch.setenv("CUPONS_EXTRA", ",".join(c["codigo"] for c in cupons))
    loja = CarrinhoProdutos(amb.pasta)
    _rodar(amb, loja)
    testes = _aplicados(loja)
    assert len(testes) == 3 and {c for c, _ in testes} == {K_PS5D, K_DISCO, K_GTA}, "cada produto tem a sua parte"


# ------------------------------------------------------------------------------------------------
# 5. Magalu com o adaptador REAL sobre a sacola falsa
# ------------------------------------------------------------------------------------------------

PRODUTOS_MAGALU = {"240604800": {"titulo": PS5D, "vendedores": [MAGALU_1P]},
                   "241923300": {"titulo": GTA, "vendedores": [MAGALU_1P]},
                   "kitwolv001": {"titulo": KIT, "vendedores": [MAGALU_1P]},
                   "240162700": {"titulo": 'Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz', "vendedores": [MAGALU_1P]}}
URL_PS5 = "https://www.magazineluiza.com.br/console-ps5/p/240604800/et/elit/"
URL_GTA = "https://www.magazineluiza.com.br/jogo-gta-6/p/241923300/et/elit/"
IDS = {"240604800": "PS5_DIGITAL", "241923300": "GTA6_CODE_IN_BOX", "kitwolv001": "PS5_KIT"}


class SacolaProdutos(PaginaMagalu):
    """PaginaMagalu com o PS5, o GTA 6 e o kit. O "Excluir" tira o 1º item; a confirmação do diálogo não tira outro."""

    def __init__(self, itens, **k):
        super().__init__(itens, produtos=dict(PRODUTOS_MAGALU), **k)

    def get_by_role(self, role, name=None, **k):
        if "sacola" in self.url and name is not None and name.pattern != r"^excluir$":
            return _Loc(0)
        return super().get_by_role(role, name, **k)


def _item(pid, qtd=1):
    return {"id": pid, "quantity": qtd, "name": PRODUTOS_MAGALU[pid]["titulo"], "seller": MAGALU_1P}


def _alvo(url, modelo, restauraveis=("PS5_DIGITAL", "GTA6_CODE_IN_BOX"), chave=None):
    pid = re.search(r"/p/([^/]+)", url).group(1)
    return {"chave": chave or f"{pid}-magazineluiza", "url": url, "vendedor": "Magalu", "vendedor_id": "magazineluiza",
            "modelo": modelo, "ids_modelo": dict(IDS), "restauraveis": list(restauraveis),
            "descartaveis": sorted(CAMINHOS)}


def _sacola(p):
    return [(i["id"], i["quantity"]) for i in p.itens]


def test_magalu_isola_o_ps5_tirando_o_gta_que_sabe_devolver():
    m = Magalu()
    m.comecar_rodada()
    p = SacolaProdutos([_item("240604800"), _item("241923300")])
    assert m.garantir_item(p, URL_PS5, _alvo(URL_PS5, "PS5_DIGITAL")) is True
    assert _sacola(p) == [("240604800", 1)] and p.cliques == ["Excluir", "Excluir", "Adicionar"]
    assert sorted(m.removidos) == ["GTA6_CODE_IN_BOX", "PS5_DIGITAL"]


def test_magalu_nao_tira_o_gta_sem_anuncio_para_devolver():
    p = SacolaProdutos([_item("240604800"), _item("241923300")])
    with pytest.raises(CarrinhoOcupado, match="GTA6_CODE_IN_BOX"):
        Magalu().garantir_item(p, URL_PS5, _alvo(URL_PS5, "PS5_DIGITAL", restauraveis=["PS5_DIGITAL"]))
    assert p.cliques == [] and len(p.itens) == 2


def test_magalu_kit_que_o_robo_pos_sai_sem_volta():
    m = Magalu()
    m.comecar_rodada()
    p = SacolaProdutos([_item("kitwolv001")])
    assert m.garantir_item(p, URL_PS5, _alvo(URL_PS5, "PS5_DIGITAL", restauraveis=["PS5_DIGITAL"])) is True
    assert _sacola(p) == [("240604800", 1)]
    # o mesmo kit SEM ser um anúncio conhecido (a pessoa pôs; o título sozinho não diz que é do robô): não mexe
    p2 = SacolaProdutos([_item("kitwolv001")])
    alvo = _alvo(URL_PS5, "PS5_DIGITAL")
    alvo["ids_modelo"] = {"240604800": "PS5_DIGITAL"}
    with pytest.raises(CarrinhoOcupado):
        Magalu().garantir_item(p2, URL_PS5, alvo)
    assert p2.cliques == []


def test_magalu_com_acessorio_na_sacola_nao_mexe():
    p = SacolaProdutos([_item("240604800"), {"id": "ctrl1", "quantity": 1, "name": CONTROLE, "seller": MAGALU_1P}])
    with pytest.raises(CarrinhoOcupado):
        Magalu().garantir_item(p, URL_GTA, _alvo(URL_GTA, "GTA6_CODE_IN_BOX"))
    assert p.cliques == []


def test_magalu_passo_final_tira_o_kit_e_deixa_um_de_cada_produto():
    m = Magalu()
    m.comecar_rodada()
    p = SacolaProdutos([_item("kitwolv001"), _item("240604800")])
    feitos = m.garantir_itens(p, [_alvo(URL_PS5, "PS5_DIGITAL"), _alvo(URL_GTA, "GTA6_CODE_IN_BOX")])
    assert feitos == {"240604800-magazineluiza", "241923300-magazineluiza"}
    assert sorted(_sacola(p)) == [("240604800", 1), ("241923300", 1)], "o kit saiu; 1 unidade de cada principal"
    assert m.sobrou_caminho is False


def test_magalu_passo_final_so_poe_o_que_falta():
    m = Magalu()
    m.comecar_rodada()
    p = SacolaProdutos([_item("240604800")])
    assert m.garantir_itens(p, [_alvo(URL_PS5, "PS5_DIGITAL"), _alvo(URL_GTA, "GTA6_CODE_IN_BOX")]) == \
        {"240604800-magazineluiza", "241923300-magazineluiza"}
    assert p.cliques == ["Adicionar"] and m.remocoes == 0


def test_magalu_pagina_que_nao_e_o_produto_nao_adiciona():
    m = Magalu()
    p = SacolaProdutos([])
    p.produtos["241923300"] = {"titulo": PS5D, "vendedores": [MAGALU_1P]}   # a página do "GTA" mostra o PS5
    assert m.garantir_item(p, URL_GTA, _alvo(URL_GTA, "GTA6_CODE_IN_BOX")) is False
    assert p.itens == [] and "Adicionar" not in p.cliques


# ------------------------------------------------------------------------------------------------
# 6. Mercado Livre com o adaptador REAL sobre páginas falsas
# ------------------------------------------------------------------------------------------------

ML_PS5, ML_GIFT, ML_PRO = "MLB4214670787", "MLB50200776", "MLB9000000077"
TITULOS_ML = {ML_PS5: "PS5 Slim Digital - Pacote Astro Bot e GT7", ML_GIFT: "Gift Card PlayStation R$ 100",
              ML_PRO: PS5PRO}
PRECOS_ML = {ML_PS5: 4369, ML_GIFT: 85, ML_PRO: 6999}
IDS_ML = {ML_PS5: "PS5_DIGITAL", ML_GIFT: "GIFT_CARD_PSN", ML_PRO: "PS5_PRO"}


def _url_ml(item):
    return f"https://produto.mercadolivre.com.br/MLB-{item[3:]}-produto-_JM"


class PaginaMLProdutos(PaginaML):
    """Carrinho do ML e as páginas de anúncio (fora de catálogo) do PS5, do PS5 Pro e do gift card."""

    def content(self):
        m = re.search(r"MLB-(\d+)", self.url)
        if not m:
            return super().content()
        item = "MLB" + m.group(1)
        return (f'<h1 class="ui-pdp-title">{TITULOS_ML[item]}</h1>'
                f'<script>{{"itemId":"{item}","localItemPrice":{PRECOS_ML[item]}}}</script>')

    def _adicionar(self):
        self.cliques.append("adicionar")
        item = self._item_da_url()
        self.carrinho.append({"id": item, "preco": PRECOS_ML[item], "qtd": 1, "titulo": TITULOS_ML[item]})


def _linha(item):
    return {"id": item, "preco": PRECOS_ML[item], "qtd": 1, "titulo": TITULOS_ML[item]}


def _alvo_ml(item, **kw):
    return {"chave": item, "item_id": item, "url": _url_ml(item), "modelo": IDS_ML[item], "catalogo": "",
            "ids_modelo": dict(IDS_ML), "restauraveis": ["PS5_DIGITAL", "PS5_PRO"], "descartaveis": sorted(CAMINHOS),
            **kw}


def test_ml_reconhece_as_linhas_pelo_id_pelo_catalogo_e_pelo_titulo():
    linhas = [
        {"links": [_url_ml(ML_PS5)], "texto": "", "excluir": True},                                # id conhecido
        {"links": ["https://www.mercadolivre.com.br/p/MLB57081243"], "texto": "", "excluir": True},  # catálogo do PS5
        {"links": ["https://produto.mercadolivre.com.br/MLB-1234567890-x"], "texto": PS5PRO + "\nExcluir"},  # título
        {"links": [_url_ml(ML_GIFT)], "texto": TITULOS_ML[ML_GIFT], "excluir": True},              # caminho pelo id
        {"links": ["https://produto.mercadolivre.com.br/MLB-5555555555-x"], "texto": "Gift Card PlayStation R$ 50"},
        {"links": ["https://produto.mercadolivre.com.br/MLB-6666666666-x"], "texto": CONTROLE + "\nExcluir"},
    ]
    cl = MercadoLivre.classificar_linhas(linhas, ML_PS5, "", (), "PS5_DIGITAL", dict(IDS_ML))
    assert [(c["tv"], c["modelo"]) for c in cl] == [
        (True, "PS5_DIGITAL"), (True, "PS5_DIGITAL"), (True, "PS5_PRO"), (True, "GIFT_CARD_PSN"), (False, None),
        (False, None)], "gift card só pelo id de um anúncio conhecido; acessório nunca"


def test_ml_passo_final_tira_o_gift_card_e_poe_o_ps5():
    ml = MercadoLivre()
    ml.comecar_rodada()
    p = PaginaMLProdutos([_linha(ML_GIFT)])
    assert ml.garantir_itens(p, [_alvo_ml(ML_PS5)]) == {ML_PS5}
    assert [(l["id"], l["qtd"]) for l in p.carrinho] == [(ML_PS5, 1)]
    assert p.cliques == ["excluir", "adicionar"] and ml.removidos == ["GIFT_CARD_PSN"] and not ml.sobrou_caminho


def test_ml_isola_o_ps5_tirando_o_pro_que_sabe_devolver():
    ml = MercadoLivre()
    ml.comecar_rodada()
    p = PaginaMLProdutos([_linha(ML_PRO)])
    assert ml.garantir_item(p, _url_ml(ML_PS5), _alvo_ml(ML_PS5)) is True
    assert [(l["id"], l["qtd"]) for l in p.carrinho] == [(ML_PS5, 1)] and ml.removidos == ["PS5_PRO"]
    p2 = PaginaMLProdutos([_linha(ML_PRO)])
    with pytest.raises(CarrinhoOcupado, match="PS5_PRO"):
        MercadoLivre().garantir_item(p2, _url_ml(ML_PS5), _alvo_ml(ML_PS5, restauraveis=["PS5_DIGITAL"]))
    assert p2.cliques == []


# ------------------------------------------------------------------------------------------------
# 7. Amazon (só leitura): as páginas da rodada repartidas entre os produtos
# ------------------------------------------------------------------------------------------------

class AmazonFalsa(Amazon):
    def __init__(self, pasta):
        self.pasta = pasta
        self.lidos: list[str] = []

    def perfil(self):
        return self.pasta

    def garantir_item(self, page, url, alvo=None):
        self.lidos.append(alvo["chave"])
        return True

    def ler_totais(self, page):
        return ResultadoCupom(codigo="", aceito=False, total_pix=4000.0, total_cartao=4300.0, pix_real=True)

    def cupom_da_pagina(self, page):
        return None


def test_amazon_reparte_as_paginas_entre_os_produtos(amb):
    def oferta_amz(asin, preco, titulo, produto):
        return {"fonte": "amazon", "tipo": "loja", "loja": "Amazon", "titulo": titulo, "ativo": True,
                "url": f"https://www.amazon.com.br/dp/{asin}?smid=A1ZZFT5FULY4LN", "id": f"{asin}-A1ZZFT5FULY4LN",
                "vendedor": "Amazon.com.br", "preco": preco, "melhor_preco": preco, "modelo": produto,
                "extra": {"vendedor_id": "A1ZZFT5FULY4LN"}}

    ofertas = [oferta_amz(f"B0PS5D000{k}", 4000.0 + k, PS5D, "PS5_DIGITAL") for k in range(3)]
    ofertas += [oferta_amz(f"B0DISCO00{k}", 4600.0 + k, PS5DISCO, "PS5_DISCO") for k in range(3)]
    ofertas += [oferta_amz(f"B0GTA6000{k}", 418.0 + k, GTA, "GTA6_CODE_IN_BOX") for k in range(3)]
    _latest(amb, ofertas, cupons=[])
    loja = AmazonFalsa(amb.pasta)
    amb.rodar(loja, loja_id="amazon")
    assert len(loja.lidos) == 6, "no máximo 6 páginas da Amazon por rodada (503 depois de umas 4 seguidas)"
    assert {k.split("-")[0][:7] for k in loja.lidos} == {"B0PS5D0", "B0DISCO", "B0GTA60"}, "2 de cada produto"


# ------------------------------------------------------------------------------------------------
# 8. modo vigia no main(): as TVs fora, o PS5 e o GTA 6 seguem
# ------------------------------------------------------------------------------------------------

def test_main_em_modo_vigia_desliga_so_as_tvs(monkeypatch):
    chamadas = []
    monkeypatch.setattr(tc, "executar", lambda *a: chamadas.append(a) or 0)
    monkeypatch.setattr(config, "VIGIA_ATE", "2099-12-31")
    monkeypatch.setattr(sys, "argv", ["testar_cupons.py", "--no-notify"])
    assert tc.main() == 0
    assert chamadas and tuple(chamadas[-1][-1]) == tuple(produtos.TVS), "o testador roda, sem as TVs"
    monkeypatch.setattr(sys, "argv", ["testar_cupons.py", "--forcar", "--no-notify"])
    tc.main()
    assert tuple(chamadas[-1][-1]) == (), "--forcar: pedido explícito, com as TVs"
    monkeypatch.setattr(config, "VIGIA_ATE", "")
    monkeypatch.setattr(sys, "argv", ["testar_cupons.py", "--no-notify"])
    tc.main()
    assert tuple(chamadas[-1][-1]) == (), "fora da vigia: tudo"


# ------------------------------------------------------------------------------------------------
# 9. mensagem por produto
# ------------------------------------------------------------------------------------------------

def _res(codigo, pix, cartao, modelo, **extra):
    return ResultadoCupom(codigo=codigo, aceito=True, produtos=cartao, frete=0.0, total_pix=pix, total_cartao=cartao,
                          parcelado="10x R$ 40,00 sem juros", extra={"modelo": modelo, **extra})


def test_msg_do_gta_com_entrega_e_meta_da_oferta():
    tarde = "📦 Entrega: previsão 30/11 (estimativa da pesquisa de 03/10) — ⚠️ chega DEPOIS do lançamento (19/11)"
    r = _res("GTA6", 296.0, 296.0, "GTA6_CODE_IN_BOX", alvo_pix=300.0, alvo_parcelado=320.0,
             nota_alvo="chega depois de 18/11", entrega=tarde)
    msg = tc.msg_melhor([("Netshoes", r)])
    assert msg.startswith("🎯 <b>META ATINGIDA</b>") and "🎯 <b>GTA 6 PS5 Code in Box</b>" in msg
    assert tarde in msg and "Alvo: Pix R$ 300,00 · parcelado R$ 320,00 (chega depois de 18/11)" in msg
    assert "R$ 4,00 abaixo da meta ✅" in msg


def test_msg_so_frete_do_produto_fala_do_produto():
    r = ResultadoCupom(codigo="FRETE0", aceito=False, frete=0.0, total_pix=4231.0, total_cartao=4549.0,
                       extra={"modelo": "PS5_DIGITAL", "so_frete": True, "antes_frete": 30.0})
    msg = tc.msg_melhor([("Magazine Luiza", r)])
    assert "o PS5 Digital continua R$ 4.231,00 (não é desconto no produto)" in msg and "a TV" not in msg
