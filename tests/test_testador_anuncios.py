"""Testador de cupons percorrendo TODOS os anúncios, do mais barato ao mais caro (pedido do usuário, 19/09):

  "faça uma varredura em todos os anuncios e faça os teste de cupons dando prioridade ao mais barato e troque
   de anuncio se não funcionar nos mais baratos"

Tudo com carrinho falso (nenhum navegador, nenhum perfil de loja). A identidade dos anúncios é a real
(monitor.carrinho.Magalu / MercadoLivre / Amazon); só as operações de carrinho são falsas.
"""

import importlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from monitor import config
from monitor.carrinho import Amazon, CarrinhoOcupado, Magalu, MercadoLivre, ResultadoCupom
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

FIXO = datetime(2026, 9, 19, 15, 10, tzinfo=TZ_BR)
TV = 'Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz Google TV AiPQ Google Assistente 4 HDMI 2 USB'


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def oferta_magalu(pid: str, seller: str, vendedor: str, pix: float, cartao: float | None = None,
                  titulo: str = TV, com_seller_na_url: bool = True, **kw) -> dict:
    """Oferta do Magalu no formato do contrato (uma por anúncio+vendedor)."""
    url = f"https://www.magazineluiza.com.br/smart-tv-55-tcl/p/{pid}/et/elit/"
    if com_seller_na_url:
        url += f"?seller_id={seller}"
    cartao = cartao or round(pix + 180, 2)
    d = {"fonte": "magalu", "tipo": "loja", "loja": "Magazine Luiza", "titulo": titulo, "url": url,
         "id": f"{pid}-{seller}", "vendedor": vendedor, "preco": cartao, "preco_pix": pix, "ativo": True,
         "melhor_preco": min(pix, cartao), "extra": {"anuncio": pid, "vendedor_id": seller}}
    d.update(kw)
    return d


A = oferta_magalu("240162700", "magazineluiza", "Magalu", 3561.55)            # 1P, o mais barato
B = oferta_magalu("kc7h6f4k4b", "lojascolombooficial", "Lojas Colombo Oficial", 3937.15)
C = oferta_magalu("eecab9199g", "leonfer", "Leonfer", 4859.91)
KA, KB, KC = "240162700-magazineluiza", "kc7h6f4k4b-lojascolombooficial", "eecab9199g-leonfer"


class PaginaNula:
    url = ""

    def wait_for_timeout(self, ms):
        pass

    def screenshot(self, **k):
        pass


class CarrinhoFalsoMagalu(Magalu):
    """Identidade real do Magalu, carrinho falso. `aceita`: {(chave do anúncio, código): desconto}."""

    def __init__(self, pasta, aceita=None, nao_entra=(), ocupado=False, precos=None):
        self.pasta = pasta
        self.aceita = dict(aceita or {})
        self.nao_entra = set(nao_entra)
        self.ocupado = ocupado
        self.precos = precos or {KA: 3561.55, KB: 3937.15, KC: 4859.91}
        self.eventos: list[tuple] = []
        self.no_carrinho = None
        self.alvos: list[dict] = []

    def perfil(self):
        return self.pasta

    def garantir_item(self, page, url, alvo=None):
        chave = (alvo or {}).get("chave")
        self.alvos.append(alvo)
        self.eventos.append(("garantir", chave))
        if self.ocupado:
            raise CarrinhoOcupado("a sacola do Magalu tem produtos que não são a TV; não mexo nela")
        if chave in self.nao_entra:
            return False
        self.no_carrinho = chave
        return True

    def _res(self, codigo: str, desconto: float = 0.0) -> ResultadoCupom:
        pix = self.precos[self.no_carrinho]
        return ResultadoCupom(codigo=codigo, aceito=bool(desconto), produtos=pix, frete=0.0, desconto=desconto or None,
                              total_pix=round(pix - desconto, 2), total_cartao=round(pix + 180 - desconto, 2),
                              parcelado="10x R$ 374,90 sem juros")

    def ler_totais(self, page):
        return self._res("")

    def aplicar(self, page, codigo):
        self.eventos.append(("aplicar", self.no_carrinho, codigo))
        d = self.aceita.get((self.no_carrinho, codigo))
        if d:
            return self._res(codigo, d)
        r = self._res(codigo)
        r.mensagem = "Este cupom não se aplica para este pedido"
        return r

    def remover(self, page):
        self.eventos.append(("remover", self.no_carrinho))

    def tem_cupom_aplicado(self, page, base):
        return False


@pytest.fixture
def amb(tmp_path, monkeypatch):
    """Pasta de dados falsa, relógio fixo e navegador falso."""
    dados = tmp_path / "data"
    dados.mkdir()
    monkeypatch.setattr(config, "DIR_DADOS", dados)
    monkeypatch.setattr(tc, "agora", lambda: FIXO)
    monkeypatch.setattr(tc, "agora_iso", lambda: _iso(FIXO))
    monkeypatch.delenv("CUPONS_EXTRA", raising=False)
    monkeypatch.setattr(tc, "AVISOS_CARRINHO", [])

    @contextmanager
    def sessao(loja, visivel):
        yield PaginaNula()

    monkeypatch.setattr(tc, "_sessao", sessao)

    class Amb:
        pasta = tmp_path

        def latest(self, modo="cloud", ofertas=(), codigos=(), loja="Magazine Luiza"):
            d = {"modo": modo, "ofertas_loja": list(ofertas),
                 "cupons": [{"loja": loja, "codigo": c, "fonte": "promobit"} for c in codigos], "posts": []}
            (dados / f"latest_{modo}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

        def rodar(self, loja, estado=None, loja_id="magalu", codigos=None, forcar=False):
            monkeypatch.setattr(tc, "LOJAS", {loja_id: loja})
            estado = estado if estado is not None else {}
            aceitos = tc.testar_loja(loja_id, codigos, forcar, False, False, estado)
            return aceitos, estado

    return Amb()


def _rec(status: str, quando: datetime, vendedor: str = "Magalu", **kw) -> dict:
    return {"testado_em": _iso(quando), "status": status, "aceito": status == "aceito", "mensagem": "",
            "vendedor": vendedor, **kw}


def _aplicados(loja) -> list[tuple]:
    return [e[1:] for e in loja.eventos if e[0] == "aplicar"]


def _garantidos(loja) -> list:
    return [e[1] for e in loja.eventos if e[0] == "garantir"]


# ------------------------------------------------------------------------------------------------
# 1. lista de anúncios: todos, do mais barato ao mais caro, sem teto fixo
# ------------------------------------------------------------------------------------------------

def test_todos_os_anuncios_do_mais_barato_ao_mais_caro(amb):
    D = oferta_magalu("ab1686263c", "camara", "camara", 5100.0)
    E = oferta_magalu("ch3bg8ac9d", "lojatclsemp", "Loja TCL Semp", 4500.0)
    tv65 = oferta_magalu("240162600", "magazineluiza", "Magalu", 2999.0,
                         titulo='Smart TV 65" TCL 4K UHD MiniLED 65C6K 120Hz Google TV')
    controle = oferta_magalu("zz1", "x", "X", 99.0, titulo="Controle remoto para TV TCL 55C6K")
    inativo = oferta_magalu("kb7d86eh39", "fastshop", "Fast Shop", 2991.60, ativo=False)
    zoom = {"fonte": "zoom", "tipo": "loja", "loja": "Magazine Luiza", "titulo": TV, "ativo": True,
            "url": "https://www.zoom.com.br/tv/smart-tv-mini-led-55-tcl-4k-55c6k?highlightedItemId=1", "id": "1",
            "preco": 3000.0, "melhor_preco": 3000.0}
    amb.latest("cloud", [C, B, tv65, controle, inativo, zoom, D])
    # a mesma chave nas duas coletas: fica a leitura mais barata
    amb.latest("pc", [dict(A, preco_pix=3600.0, melhor_preco=3600.0), A, E])
    loja = CarrinhoFalsoMagalu(amb.pasta)
    _, anuncios = tc.codigos_conhecidos(loja)
    assert [a.chave for a in anuncios] == [KA, KB, "ch3bg8ac9d-lojatclsemp", KC, "ab1686263c-camara"]
    assert anuncios[0].preco == 3561.55 and anuncios[0].vendedor_id == "magazineluiza"
    assert len(anuncios) == 5, "sem o teto antigo de 3 anúncios"


def test_formato_de_hoje_do_latest_tambem_serve(amb):
    # latest_cloud.json de 19/09: id do JSON (240162800) diferente do /p/ da URL (240162700), sem seller_id
    hoje = {"fonte": "magalu", "tipo": "loja", "loja": "Magazine Luiza", "id": "240162800-magazineluiza",
            "url": "https://www.magazineluiza.com.br/smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-"
                   "google-assistente-4-hdmi-2-usb/p/240162700/et/elit/",
            "vendedor": "Magalu", "preco": 3749.0, "preco_pix": 3561.55, "ativo": True, "melhor_preco": 3561.55,
            "extra": {"preco_de": 4199.0, "1p": True}, "titulo": TV}
    amb.latest("cloud", [hoje])
    _, anuncios = tc.codigos_conhecidos(CarrinhoFalsoMagalu(amb.pasta))
    a = anuncios[0]
    assert (a.chave, a.vendedor_id, a.produto) == (KA, "magazineluiza", "240162700")


# ------------------------------------------------------------------------------------------------
# 2. fila calculada antes de mexer no carrinho; anúncio sem pendência não é tocado
# ------------------------------------------------------------------------------------------------

def test_anuncio_sem_cupom_pendente_nao_mexe_no_carrinho(amb):
    amb.latest("cloud", [A, B], codigos=["TOMA30", "LU100"])
    uma_hora = FIXO - timedelta(hours=1)
    estado = {"magalu": {"cupons": {f"TOMA30@{KA}": _rec("recusado", uma_hora),
                                    f"LU100@{KA}": _rec("recusado", uma_hora)}}}
    loja = CarrinhoFalsoMagalu(amb.pasta)
    amb.rodar(loja, estado)
    assert _garantidos(loja)[0] == KB, "o 1P (mais barato) não tinha nada pendente: não é aberto para teste"
    assert _aplicados(loja) == [(KB, "TOMA30"), (KB, "LU100")]
    # revisão de 19/09: no fim o carrinho volta para o 1P (o mais barato de todos, mesmo sem ter sido aberto)
    assert _garantidos(loja) == [KB, KA] and loja.no_carrinho == KA


def test_nada_pendente_em_lugar_nenhum_nao_abre_carrinho(amb):
    amb.latest("cloud", [A, B], codigos=["TOMA30"])
    uma_hora = FIXO - timedelta(hours=1)
    estado = {"magalu": {"cupons": {f"TOMA30@{KA}": _rec("recusado", uma_hora),
                                    f"TOMA30@{KB}": _rec("recusado", uma_hora, "Lojas Colombo Oficial")}}}
    loja = CarrinhoFalsoMagalu(amb.pasta)
    aceitos, _ = amb.rodar(loja, estado)
    assert loja.eventos == [] and aceitos == []


# ------------------------------------------------------------------------------------------------
# 3. aceito no mais barato não vai para o mais caro; recusado passa para o próximo
# ------------------------------------------------------------------------------------------------

def test_aceito_no_mais_barato_nao_e_retestado_e_recusado_troca_de_anuncio(amb):
    amb.latest("cloud", [B, A], codigos=["DESCONTA100", "TOMA30"])
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KA, "DESCONTA100"): 100.0})
    aceitos, estado = amb.rodar(loja)
    testes = _aplicados(loja)
    # 1P primeiro (mais barato); no Colombo só o que não funcionou no 1P
    assert testes[:2] == [(KA, "DESCONTA100"), (KA, "TOMA30")]
    assert (KB, "TOMA30") in testes and (KB, "DESCONTA100") not in testes[:3]
    assert _garantidos(loja)[:2] == [KA, KB]
    cup = estado["magalu"]["cupons"]
    assert cup[f"DESCONTA100@{KA}"]["status"] == "aceito"
    assert cup[f"TOMA30@{KA}"]["status"] == "recusado" and cup[f"TOMA30@{KB}"]["status"] == "recusado"
    assert f"DESCONTA100@{KB}" not in cup
    assert [(r.codigo, r.extra["anuncio"]) for r in aceitos] == [("DESCONTA100", KA)]
    # passo final: o carrinho volta para o anúncio do melhor cupom, com ele aplicado
    assert loja.eventos[-2:] == [("garantir", KA), ("aplicar", KA, "DESCONTA100")]
    assert aceitos[0].extra["no_carrinho"] is True


def test_aceite_de_mais_cedo_no_mais_barato_tambem_vale_e_o_carrinho_volta_para_ele(amb):
    amb.latest("cloud", [A, B], codigos=["DESCONTA100", "TOMA30"])
    cedo = FIXO.replace(hour=12, minute=3)
    estado = {"magalu": {"cupons": {
        f"DESCONTA100@{KA}": _rec("aceito", cedo, total_pix=3461.55, total_cartao=3641.55, frete=0.0, desconto=100.0,
                                  tv_pix=3461.55, quantidade=1)}}}
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KA, "DESCONTA100"): 100.0})
    aceitos, estado = amb.rodar(loja, estado)
    assert _aplicados(loja)[:2] == [(KA, "TOMA30"), (KB, "TOMA30")], "DESCONTA100 não vai para o Colombo"
    # o teste no Colombo deixou o Colombo no carrinho: o passo final devolve o 1P com o cupom de mais cedo
    assert loja.eventos[-2:] == [("garantir", KA), ("aplicar", KA, "DESCONTA100")]
    assert aceitos == [], "nada novo nesta rodada: sem mensagem"


def test_cupom_recusado_no_mais_barato_ha_tempo_ainda_e_testado_no_proximo(amb):
    amb.latest("cloud", [A, B], codigos=["LU250"])
    estado = {"magalu": {"cupons": {f"LU250@{KA}": _rec("recusado", FIXO - timedelta(hours=3))}}}
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KB, "LU250"): 250.0})
    aceitos, _ = amb.rodar(loja, estado)
    assert _aplicados(loja)[0] == (KB, "LU250")
    assert [(r.codigo, r.extra["anuncio"], r.extra["vendedor"]) for r in aceitos] == \
        [("LU250", KB, "Lojas Colombo Oficial")]


def test_cupom_de_horario_aceito_no_mais_barato_nao_vai_para_os_outros(amb):
    amb.latest("cloud", [A, B], codigos=["DIADOCLIENTE14H", "TOMA30"])
    estado = {"magalu": {"cupons": {f"DIADOCLIENTE14H@{KA}": _rec("aceito", FIXO.replace(hour=14, minute=20),
                                                                   total_pix=3311.55, frete=0.0)}}}
    loja = CarrinhoFalsoMagalu(amb.pasta)
    amb.rodar(loja, estado)
    assert _aplicados(loja) == [(KA, "TOMA30"), (KB, "TOMA30")], \
        "às 15h o 14H não é testado no Colombo (ou vale e o 1P ganha, ou a janela passou)"
    # e não é reaplicado no passo final fora da hora dele: o carrinho só volta para o 1P, sem cupom
    assert _garantidos(loja) == [KA, KB, KA]
    assert loja.eventos[-1] == ("garantir", KA)


def test_cupom_de_antes_sai_do_carrinho_antes_de_medir(amb):
    amb.latest("cloud", [A], codigos=["TOMA30"])

    class ComCupomDeAntes(CarrinhoFalsoMagalu):
        def tem_cupom_aplicado(self, page, base):
            return not any(e[0] == "remover" for e in self.eventos)

    loja = ComCupomDeAntes(amb.pasta)
    amb.rodar(loja)
    assert loja.eventos[:3] == [("garantir", KA), ("remover", KA), ("aplicar", KA, "TOMA30")]


def test_forcar_ignora_o_estado_mas_nao_repete_o_que_foi_aceito_no_mais_barato_agora(amb):
    amb.latest("cloud", [A, B], codigos=["DESCONTA100"])
    cedo = FIXO.replace(hour=9)
    estado = {"magalu": {"cupons": {f"DESCONTA100@{KA}": _rec("aceito", cedo, total_pix=3461.55),
                                    f"DESCONTA100@{KB}": _rec("recusado", cedo, "Lojas Colombo Oficial")}}}
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KA, "DESCONTA100"): 100.0})
    amb.rodar(loja, estado, forcar=True)
    assert _aplicados(loja)[:1] == [(KA, "DESCONTA100")]
    assert (KB, "DESCONTA100") not in _aplicados(loja)


# ------------------------------------------------------------------------------------------------
# 4. limites: orçamento de testes da rodada e anúncios por loja; falha num anúncio passa para o próximo
# ------------------------------------------------------------------------------------------------

def test_orcamento_de_testes_da_rodada(amb, monkeypatch):
    monkeypatch.setattr(tc, "MAX_APLICACOES_POR_RODADA", 3)
    amb.latest("cloud", [A, B], codigos=["C1X", "C2X", "C3X", "C4X", "C5X"])
    loja = CarrinhoFalsoMagalu(amb.pasta)
    amb.rodar(loja)
    assert _aplicados(loja) == [(KA, "C1X"), (KA, "C2X"), (KA, "C3X")]
    assert _garantidos(loja) == [KA], "sem orçamento, nem abre o próximo anúncio"


def test_limite_de_anuncios_por_loja(amb):
    amb.latest("cloud", [A, B, C], codigos=["TOMA30"])
    loja = CarrinhoFalsoMagalu(amb.pasta)
    loja.max_anuncios = 2
    amb.rodar(loja)
    assert _garantidos(loja) == [KA, KB, KA], "o 3º anúncio fica para a próxima; no fim o carrinho volta ao 1P"
    assert CarrinhoFalsoMagalu.max_anuncios == 4 and MercadoLivre.max_anuncios == 3


def test_anuncio_que_nao_entrou_no_carrinho_passa_para_o_proximo(amb):
    amb.latest("cloud", [A, B], codigos=["TOMA30"])
    loja = CarrinhoFalsoMagalu(amb.pasta, nao_entra={KA})
    _, estado = amb.rodar(loja)
    assert _garantidos(loja) == [KA, KB]
    assert _aplicados(loja) == [(KB, "TOMA30")]
    assert f"TOMA30@{KA}" not in estado["magalu"]["cupons"], "sem teste no 1P: continua pendente lá"


def test_carrinho_com_outro_produto_para_a_loja_na_rodada(amb):
    amb.latest("cloud", [A, B], codigos=["TOMA30"])
    loja = CarrinhoFalsoMagalu(amb.pasta, ocupado=True)
    aceitos, estado = amb.rodar(loja)
    assert loja.eventos == [("garantir", KA)], "não tenta os outros anúncios nem o passo final"
    assert aceitos == [] and estado["magalu"]["cupons"] == {}
    assert "pausa_ate" not in estado["magalu"], "não é antirrobô: sem pausa"


# ------------------------------------------------------------------------------------------------
# 4b. fim da rodada: o carrinho nunca fica num anúncio mais caro só porque foi o último testado
# ------------------------------------------------------------------------------------------------

def test_sem_cupom_que_funcione_o_carrinho_volta_para_o_mais_barato(amb):
    # caso real de 19/09 13h: DIADOCLIENTE18H volta à fila a cada hora nova, nos dois anúncios
    amb.latest("cloud", [A, B], codigos=["DIADOCLIENTE18H"])
    uma_hora = FIXO - timedelta(hours=1)
    estado = {"magalu": {"cupons": {f"DIADOCLIENTE18H@{KA}": _rec("recusado", uma_hora),
                                    f"DIADOCLIENTE18H@{KB}": _rec("recusado", uma_hora, "Lojas Colombo Oficial")}}}
    loja = CarrinhoFalsoMagalu(amb.pasta)
    aceitos, _ = amb.rodar(loja, estado)
    assert _aplicados(loja) == [(KA, "DIADOCLIENTE18H"), (KB, "DIADOCLIENTE18H")]
    assert _garantidos(loja) == [KA, KB, KA] and loja.eventos[-1] == ("garantir", KA)
    assert loja.no_carrinho == KA and aceitos == []


def test_cupom_que_nao_compensa_no_mais_caro_nao_fica_no_carrinho(amb):
    # LU250 funciona no Colombo (3.937,15 - 250 = 3.687,15), mas o 1P sem cupom custa 3.561,55
    amb.latest("cloud", [A, B], codigos=["LU250"])
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KB, "LU250"): 250.0})
    aceitos, _ = amb.rodar(loja)
    assert loja.eventos[-1] == ("garantir", KA), "o carrinho volta para o mais barato, sem cupom"
    assert [(r.codigo, r.extra["anuncio"]) for r in aceitos] == [("LU250", KB)], "o aceite ainda vai na mensagem"
    assert "no_carrinho" not in aceitos[0].extra
    assert "ficou aplicado" not in tc.msg_melhor([("Magazine Luiza", r) for r in aceitos])


def test_cupom_que_compensa_no_mais_caro_fica_no_carrinho(amb):
    amb.latest("cloud", [A, B], codigos=["COLOMBO500"])
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KB, "COLOMBO500"): 500.0})  # 3.437,15 < 3.561,55
    aceitos, _ = amb.rodar(loja)
    assert loja.eventos[-2:] == [("garantir", KB), ("aplicar", KB, "COLOMBO500")]
    assert aceitos[0].extra["no_carrinho"] is True


def test_anuncio_mais_caro_que_nao_entrou_o_carrinho_e_conferido_no_fim(amb):
    # a troca pelo Colombo falhou no meio (o carrinho pode ter ficado vazio): no fim, garante o 1P de novo
    amb.latest("cloud", [A, B], codigos=["TOMA30"])
    loja = CarrinhoFalsoMagalu(amb.pasta, nao_entra={KB})
    amb.rodar(loja)
    assert _garantidos(loja) == [KA, KB, KA]


def test_so_o_mais_barato_visitado_nao_mexe_de_novo_no_fim(amb):
    amb.latest("cloud", [A, B], codigos=["TOMA30"])
    estado = {"magalu": {"cupons": {f"TOMA30@{KB}": _rec("recusado", FIXO - timedelta(hours=1), "Lojas Colombo Oficial")}}}
    loja = CarrinhoFalsoMagalu(amb.pasta)
    amb.rodar(loja, estado)
    assert _garantidos(loja) == [KA]


def test_carrinho_ocupado_ao_voltar_nao_quebra_a_rodada(amb):
    amb.latest("cloud", [A, B], codigos=["TOMA30"])

    class OcupaNoFim(CarrinhoFalsoMagalu):
        def garantir_item(self, page, url, alvo=None):
            if len(self.alvos) == 2:  # 3ª chamada: a volta para o 1P
                self.alvos.append(alvo)
                raise CarrinhoOcupado("a pessoa pôs outro produto na sacola no meio da rodada")
            return super().garantir_item(page, url, alvo)

    loja = OcupaNoFim(amb.pasta)
    aceitos, estado = amb.rodar(loja)
    assert len(loja.alvos) == 3 and aceitos == [] and "pausa_ate" not in estado["magalu"]


def test_alvo_passado_ao_carrinho_tem_vendedor_e_chave(amb):
    amb.latest("cloud", [B], codigos=["TOMA30"])
    loja = CarrinhoFalsoMagalu(amb.pasta)
    amb.rodar(loja)
    alvo = loja.alvos[0]
    assert (alvo["chave"], alvo["vendedor"], alvo["vendedor_id"]) == (KB, "Lojas Colombo Oficial", "lojascolombooficial")


# ------------------------------------------------------------------------------------------------
# 4c. revisão de 19/09: o fim da rodada volta ao anúncio mais barato de TODOS, não só dos visitados
# ------------------------------------------------------------------------------------------------

def test_so_o_mais_caro_pendente_o_carrinho_volta_ao_mais_barato(amb):
    # 1P recusado há 1 h (não volta à fila); Colombo recusado há 25 h (volta): só o Colombo é visitado
    amb.latest("cloud", [A, B], codigos=["CUPOMX"])
    estado = {"magalu": {"cupons": {
        f"CUPOMX@{KA}": _rec("recusado", FIXO - timedelta(hours=1)),
        f"CUPOMX@{KB}": _rec("recusado", FIXO - timedelta(hours=25), vendedor="Lojas Colombo Oficial"),
    }}}
    loja = CarrinhoFalsoMagalu(amb.pasta)
    loja.no_carrinho = KA  # a sacola da pessoa estava com o 1P (o mais barato)
    aceitos, _ = amb.rodar(loja, estado)
    assert _aplicados(loja) == [(KB, "CUPOMX")]
    assert _garantidos(loja) == [KB, KA], "no fim volta para o 1P, que nem foi aberto nesta rodada"
    assert loja.no_carrinho == KA and aceitos == []


def test_erro_do_robo_no_mais_caro_o_carrinho_volta_ao_mais_barato(amb):
    amb.latest("cloud", [A, B], codigos=["CUPOMX"])
    estado = {"magalu": {"cupons": {
        f"CUPOMX@{KA}": _rec("recusado", FIXO - timedelta(hours=2)),
        f"CUPOMX@{KB}": _rec("erro", FIXO - timedelta(hours=2), vendedor="Lojas Colombo Oficial"),
    }}}
    loja = CarrinhoFalsoMagalu(amb.pasta)
    loja.no_carrinho = KA
    amb.rodar(loja, estado)
    assert loja.no_carrinho == KA and _garantidos(loja) == [KB, KA]


def test_troca_que_esvazia_a_sacola_e_falha_volta_ao_mais_barato(amb):
    # a troca pelo Colombo esvaziou a sacola e depois falhou (página com outro vendedor, por exemplo)
    amb.latest("cloud", [A, B], codigos=["CUPOMX"])
    estado = {"magalu": {"cupons": {f"CUPOMX@{KA}": _rec("recusado", FIXO - timedelta(hours=1))}}}

    class EsvaziaEFalha(CarrinhoFalsoMagalu):
        def garantir_item(self, page, url, alvo=None):
            if (alvo or {}).get("chave") == KB:
                self.eventos.append(("garantir", KB))
                self.no_carrinho = None
                return False
            return super().garantir_item(page, url, alvo)

    loja = EsvaziaEFalha(amb.pasta)
    loja.no_carrinho = KA
    amb.rodar(loja, estado)
    assert _aplicados(loja) == [] and _garantidos(loja) == [KB, KA]
    assert loja.no_carrinho == KA, "a sacola não termina vazia"


def test_mais_barato_nao_volta_entao_tenta_o_proximo(amb):
    # no fim, o 1P não entra (sumiu o vendedor, por exemplo): o carrinho fica com o próximo mais barato
    amb.latest("cloud", [A, B, C], codigos=["CUPOMX"])
    estado = {"magalu": {"cupons": {f"CUPOMX@{KA}": _rec("recusado", FIXO - timedelta(hours=1)),
                                    f"CUPOMX@{KB}": _rec("recusado", FIXO - timedelta(hours=1), "Lojas Colombo Oficial")}}}

    class UmPNaoVolta(CarrinhoFalsoMagalu):
        def garantir_item(self, page, url, alvo=None):
            if (alvo or {}).get("chave") == KA:
                self.eventos.append(("garantir", KA))
                self.no_carrinho = None  # esvaziou e não conseguiu pôr o 1P
                return False
            return super().garantir_item(page, url, alvo)

    loja = UmPNaoVolta(amb.pasta)
    amb.rodar(loja, estado)
    assert _aplicados(loja) == [(KC, "CUPOMX")]
    assert _garantidos(loja) == [KC, KA, KB], "tenta o 1P e, sem ele, o Colombo (nunca o Leonfer, mais caro)"
    assert loja.no_carrinho == KB


def test_o_mais_barato_do_fim_e_o_da_ordem_da_coleta(amb):
    # a ordem do fim é a mesma do percurso (preço coletado); a leitura do carrinho, que pode incluir frete não
    # lido, só entra na comparação com o cupom
    amb.latest("cloud", [A, B], codigos=["CUPOMX"])
    estado = {"magalu": {"cupons": {f"CUPOMX@{KB}": _rec("recusado", FIXO - timedelta(hours=1), "Lojas Colombo Oficial")}}}
    loja = CarrinhoFalsoMagalu(amb.pasta, precos={KA: 3999.0, KB: 3937.15, KC: 4859.91})
    amb.rodar(loja, estado)
    assert _garantidos(loja) == [KA] and loja.no_carrinho == KA


def test_timeout_no_meio_da_troca_ainda_faz_o_passo_final(amb):
    amb.latest("cloud", [A, B], codigos=["DESCONTA100", "TOMA30"])

    class Timeout(CarrinhoFalsoMagalu):
        def garantir_item(self, page, url, alvo=None):
            if (alvo or {}).get("chave") == KB:
                self.eventos.append(("garantir", KB))
                self.no_carrinho = None  # esvaziou a sacola e o goto da página do Colombo estourou
                raise TimeoutError("Timeout 60000ms exceeded (page.goto)")
            return super().garantir_item(page, url, alvo)

    loja = Timeout(amb.pasta, aceita={(KA, "DESCONTA100"): 100.0})
    aceitos, estado = amb.rodar(loja)
    assert loja.eventos[-2:] == [("garantir", KA), ("aplicar", KA, "DESCONTA100")]
    assert loja.no_carrinho == KA
    assert [(r.codigo, r.extra["anuncio"]) for r in aceitos] == [("DESCONTA100", KA)], "o aceite não se perde"
    assert aceitos[0].extra["no_carrinho"] is True
    assert "pausa_ate" not in estado["magalu"], "falha do robô não é antirrobô: sem pausa"


def test_cupom_que_nao_reaplica_no_mais_caro_volta_ao_mais_barato(amb):
    # COLOMBO500 deixa o Colombo mais barato (3.437,15), mas no passo final a loja recusa o cupom:
    # sem ele o Colombo custa 3.937,15 e o carrinho tem de voltar para o 1P (3.561,55)
    amb.latest("cloud", [A, B], codigos=["COLOMBO500"])

    class SoUmaVez(CarrinhoFalsoMagalu):
        def aplicar(self, page, codigo):
            r = super().aplicar(page, codigo)
            if r.aceito:
                self.aceita.pop((KB, "COLOMBO500"), None)  # o cupom acabou depois do teste
            return r

    loja = SoUmaVez(amb.pasta, aceita={(KB, "COLOMBO500"): 500.0})
    aceitos, _ = amb.rodar(loja)
    assert loja.eventos[-3:] == [("garantir", KB), ("aplicar", KB, "COLOMBO500"), ("garantir", KA)]
    assert loja.no_carrinho == KA
    assert aceitos[0].extra["no_carrinho"] is False


def test_carrinho_ocupado_no_passo_final_nao_tenta_outro_anuncio(amb):
    amb.latest("cloud", [A, B], codigos=["CUPOMX"])
    estado = {"magalu": {"cupons": {f"CUPOMX@{KA}": _rec("recusado", FIXO - timedelta(hours=1))}}}

    class OcupaNoFim(CarrinhoFalsoMagalu):
        def garantir_item(self, page, url, alvo=None):
            if (alvo or {}).get("chave") == KA:
                self.eventos.append(("garantir", KA))
                raise CarrinhoOcupado("a pessoa pôs outro produto na sacola")
            return super().garantir_item(page, url, alvo)

    loja = OcupaNoFim(amb.pasta)
    amb.rodar(loja, estado)
    assert _garantidos(loja) == [KB, KA], "carrinho com outro produto: para de mexer"


def test_loja_fora_do_ar_no_passo_final_pausa(amb):
    from monitor.carrinho import LojaIndisponivel

    amb.latest("cloud", [A, B], codigos=["CUPOMX"])
    estado = {"magalu": {"cupons": {f"CUPOMX@{KA}": _rec("recusado", FIXO - timedelta(hours=1))}}}

    class ForaNoFim(CarrinhoFalsoMagalu):
        def garantir_item(self, page, url, alvo=None):
            if (alvo or {}).get("chave") == KA:
                self.eventos.append(("garantir", KA))
                raise LojaIndisponivel("o Magalu não carregou a sacola")
            return super().garantir_item(page, url, alvo)

    loja = ForaNoFim(amb.pasta)
    _, estado = amb.rodar(loja, estado)
    assert _garantidos(loja) == [KB, KA] and "pausa_ate" in estado["magalu"]


# ------------------------------------------------------------------------------------------------
# 4c. a sacola da pessoa nunca termina vazia sem aviso (revisão de 19/09, item M1)
# ------------------------------------------------------------------------------------------------

class CarrinhoQueEsvazia(CarrinhoFalsoMagalu):
    """garantir_item esvazia a sacola ANTES de tentar pôr o anúncio (é o que o Magalu e o ML fazem:
    esvaziar/_tirar_outras_tvs e só depois adicionar) e a adição falha em `nao_entra`."""

    def garantir_item(self, page, url, alvo=None):
        chave = (alvo or {}).get("chave")
        self.alvos.append(alvo)
        self.eventos.append(("garantir", chave))
        if chave in self.nao_entra:
            self.no_carrinho = None      # esvaziou a sacola e não conseguiu pôr o anúncio pedido
            return False
        self.no_carrinho = chave
        return True


def test_todos_os_anuncios_falham_no_percurso_o_fim_ainda_tenta_recolocar_a_tv(amb):
    # caso do revisor: a pessoa tinha o 1P na sacola; nenhum anúncio entra e a sacola fica vazia
    amb.latest("cloud", [A, B, C])
    loja = CarrinhoQueEsvazia(amb.pasta, nao_entra={KA, KB, KC})
    loja.no_carrinho = KA
    amb.rodar(loja, codigos=["CUPOM1"])
    tentativas = _garantidos(loja)
    assert tentativas[:3] == [KA, KB, KC], "o percurso tentou os três"
    assert len(tentativas) > 3, "o passo final ainda tem de tentar recolocar a TV"
    assert tentativas[3] == KA, "recomeça pelo mais barato, mesmo tendo falhado antes"


def test_todos_falham_e_a_sacola_fica_vazia_avisa_no_telegram(amb):
    amb.latest("cloud", [A, B, C])
    loja = CarrinhoQueEsvazia(amb.pasta, nao_entra={KA, KB, KC})
    loja.no_carrinho = KA
    amb.rodar(loja, codigos=["CUPOM1"])
    assert loja.no_carrinho is None, "o teste falso nunca deixa a TV entrar"
    (aviso,) = tc.AVISOS_CARRINHO
    assert "Magazine Luiza" in aviso and "vazia" in aviso.lower()


def test_recolocacao_no_fim_funciona_no_segundo_anuncio(amb):
    # o 1P não entra mais (vendedor sumiu), mas o Colombo entra: a sacola não fica vazia nem há aviso
    amb.latest("cloud", [A, B, C])
    loja = CarrinhoQueEsvazia(amb.pasta, nao_entra={KA})
    loja.no_carrinho = KA
    amb.rodar(loja, codigos=["CUPOM1"])
    assert loja.no_carrinho == KB and tc.AVISOS_CARRINHO == []


def test_recolocacao_insiste_ate_o_terceiro_quando_todos_falharam_no_percurso(amb):
    # KA e KB falham sempre; KC só falha no percurso (a loja engasgou) e volta a aceitar no fim
    amb.latest("cloud", [A, B, C])

    class KCVoltaNoFim(CarrinhoQueEsvazia):
        def garantir_item(self, page, url, alvo=None):
            if (alvo or {}).get("chave") == KC and len(self.eventos) >= 3:
                self.nao_entra.discard(KC)
            return super().garantir_item(page, url, alvo)

    loja = KCVoltaNoFim(amb.pasta, nao_entra={KA, KB, KC})
    loja.no_carrinho = KA
    amb.rodar(loja, codigos=["CUPOM1"])
    assert loja.no_carrinho == KC, "insiste até o 3º anúncio para a sacola não ficar vazia"
    assert tc.AVISOS_CARRINHO == []


def test_sacola_ocupada_no_fim_nao_vira_aviso_de_sacola_vazia(amb):
    # CarrinhoOcupado = a sacola tem OUTRO produto da pessoa, logo não está vazia: nada a avisar
    amb.latest("cloud", [A, B], codigos=["CUPOMX"])
    estado = {"magalu": {"cupons": {f"CUPOMX@{KA}": _rec("recusado", FIXO - timedelta(hours=1))}}}

    class OcupaNoFim(CarrinhoFalsoMagalu):
        def garantir_item(self, page, url, alvo=None):
            if (alvo or {}).get("chave") == KA:
                self.eventos.append(("garantir", KA))
                raise CarrinhoOcupado("a pessoa pôs outro produto na sacola")
            return super().garantir_item(page, url, alvo)

    amb.rodar(OcupaNoFim(amb.pasta), estado)
    assert tc.AVISOS_CARRINHO == []


def test_aviso_de_sacola_vazia_vai_na_mensagem_mesmo_sem_cupom_aceito(amb, monkeypatch):
    amb.latest("cloud", [A], codigos=["CUPOM1"])
    loja = CarrinhoQueEsvazia(amb.pasta, nao_entra={KA})
    loja.no_carrinho = KA
    monkeypatch.setattr(tc, "LOJAS", {"magalu": loja})
    monkeypatch.setattr(tc, "carrega_estado", lambda: {})
    monkeypatch.setattr(tc, "salva_estado", lambda d: None)
    enviadas: list[str] = []
    monkeypatch.setattr(tc.notificar, "enviar", lambda m, **k: enviadas.append(m) or True)
    tc.executar(["magalu"], ["CUPOM1"], False, False, True)
    assert len(enviadas) == 1 and "vazia" in enviadas[0].lower()


# ------------------------------------------------------------------------------------------------
# 4d. mensagem: cupom que não deixa a TV mais barata que o anúncio mais barato sem cupom
# ------------------------------------------------------------------------------------------------

def test_cupom_no_mais_caro_que_nao_vence_o_mais_barato_nao_vira_melhor_preco(amb):
    # LU250 no Colombo: 3.687,15 no Pix; o 1P sem cupom custa 3.561,55 (e o cartão também ganha)
    amb.latest("cloud", [A, B], codigos=["LU250"])
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KB, "LU250"): 250.0})
    aceitos, _ = amb.rodar(loja)
    assert [r.codigo for r in aceitos] == ["LU250"]
    assert aceitos[0].extra["pior_a_vista"] is True and aceitos[0].extra["pior_parcelado"] is True
    assert tc.msg_melhor([("Magazine Luiza", r) for r in aceitos]) == ""


def test_cupom_no_mais_caro_que_so_vence_no_parcelado(amb):
    # Colombo sem desconto de Pix: cartão 3.700 com cupom < cartão do 1P (3.741,55), Pix pior que o do 1P
    Bsem = oferta_magalu("kc7h6f4k4b", "lojascolombooficial", "Lojas Colombo Oficial", 3800.0, cartao=3800.0)
    amb.latest("cloud", [A, Bsem], codigos=["CUPOM100"])

    class ColomboSemPix(CarrinhoFalsoMagalu):
        def _res(self, codigo, desconto=0.0):
            r = super()._res(codigo, desconto)
            if self.no_carrinho == KB:
                r.total_pix = r.total_cartao = round(3800.0 - desconto, 2)
                r.produtos = 3800.0
            return r

    loja = ColomboSemPix(amb.pasta, aceita={(KB, "CUPOM100"): 100.0}, precos={KA: 3561.55, KB: 3800.0})
    aceitos, _ = amb.rodar(loja)
    r = aceitos[0]
    assert r.extra["pior_a_vista"] is True and r.extra["pior_parcelado"] is False
    msg = tc.msg_melhor([("Magazine Luiza", x) for x in aceitos])
    assert "Melhor à vista" not in msg
    assert "<b>Melhor parcelado</b>: R$ 3.700,00" in msg and "Lojas Colombo Oficial" in msg


def test_msg_sem_marcas_continua_como_antes():
    r = ResultadoCupom(codigo="LU100", aceito=True, produtos=3599.0, frete=0.0, total_pix=3399.0, total_cartao=3499.0,
                       parcelado="10x R$ 349,90 sem juros")
    msg = tc.msg_melhor([("Magazine Luiza", r)])
    assert msg.startswith("✅ <b>Cupom funcionou</b>") and "Melhor à vista</b>: R$ 3.399,00" in msg
    assert "Melhor parcelado</b>: R$ 3.499,00" in msg


# ------------------------------------------------------------------------------------------------
# 5. estado por anúncio: chaves novas, chaves antigas aceitas, preços por anúncio
# ------------------------------------------------------------------------------------------------

ANTIGA_1P = "stente-4-hdmi-2-usb/p/240162700/et/elit/"       # como está em docs/data/cupons_carrinho.json
ANTIGA_COLOMBO = "d-android-tv-55c6k/p/kc7h6f4k4b/et/elit/"


def test_chaves_antigas_do_estado_valem_para_o_mesmo_anuncio(amb):
    amb.latest("cloud", [A, B], codigos=["LU100", "TOMA30"])
    duas_horas = FIXO - timedelta(hours=2)
    estado = {"magalu": {"cupons": {
        f"LU100@{ANTIGA_1P}": _rec("recusado", duas_horas, "Magalu"),
        f"TOMA30@{ANTIGA_1P}": _rec("aceito", FIXO.replace(hour=12, minute=3), "Magalu", total_pix=3531.55),
        f"LU100@{ANTIGA_COLOMBO}": _rec("recusado", duas_horas, "Lojas Colombo Oficial"),
        f"TOMA30@{ANTIGA_COLOMBO}": _rec("aceito", FIXO.replace(hour=12, minute=6), "Lojas Colombo Oficial",
                                         total_pix=3907.15),
    }}}
    loja = CarrinhoFalsoMagalu(amb.pasta)
    amb.rodar(loja, estado)
    assert loja.eventos == [], "nada é retestado só porque a chave mudou"


def test_chave_antiga_de_outro_vendedor_no_mesmo_produto_nao_vale():
    loja = Magalu()
    a = tc.anuncio_da_oferta(loja, oferta_magalu("240162700", "lojascolombooficial", "Lojas Colombo Oficial", 3900.0))
    testados = {f"LU100@{ANTIGA_1P}": _rec("recusado", FIXO, "Magalu")}
    assert tc.registro_do_cupom(testados, "LU100", a) is None
    b = tc.anuncio_da_oferta(loja, A)
    assert tc.registro_do_cupom(testados, "LU100", b)["status"] == "recusado"
    # a chave nova tem prioridade sobre a antiga
    testados[f"LU100@{KA}"] = _rec("erro", FIXO)
    assert tc.registro_do_cupom(testados, "LU100", b)["status"] == "erro"


def test_chave_antiga_do_ml_pelo_item():
    ml = MercadoLivre()
    o = {"loja": "Mercado Livre", "tipo": "loja", "ativo": True, "titulo": "Smart Tv Tcl 55 Polegadas 55c6k",
         "url": "https://www.mercadolivre.com.br/smart-tv/p/MLB48808732?pdp_filters=item_id%3AMLB7574364080",
         "id": "MLB7574364080", "vendedor": "Magalu", "preco": 3749.0, "melhor_preco": 3749.0}
    a = tc.anuncio_da_oferta(ml, o)
    assert a.chave == "MLB7574364080"
    testados = {"TECH1909@v-4-hdmi-144hz-hdr10-55c6k/p/MLB48808732#MLB7574364080": _rec("recusado", FIXO),
                "PROMOHOJE@v-4-hdmi-144hz-hdr10-55c6k/p/MLB48808732#MLB5417889802": _rec("recusado", FIXO)}
    assert tc.registro_do_cupom(testados, "TECH1909", a)["status"] == "recusado"
    assert tc.registro_do_cupom(testados, "PROMOHOJE", a) is None, "registro de outro item do catálogo"


def test_precos_gravados_por_anuncio(amb):
    amb.latest("cloud", [A, B, C], codigos=["TOMA30"])
    estado = {"magalu": {"cupons": {f"TOMA30@{KC}": _rec("recusado", FIXO - timedelta(hours=1), "Leonfer")},
                         "precos": {"Magalu": {"tv_pix": 3311.55},       # formato antigo (por vendedor): sai
                                    KC: {"tv_pix": 4859.91, "lido_em": "2026-09-19T10:00:00-03:00"}}}}
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KB, "TOMA30"): 30.0})
    _, estado = amb.rodar(loja, estado)
    precos = estado["magalu"]["precos"]
    assert set(precos) == {KA, KB, KC}
    assert precos[KA]["tv_pix"] == 3561.55 and precos[KA]["cupom"] == "(sem cupom)"
    assert precos[KB]["tv_pix"] == 3907.15 and precos[KB]["cupom"] == "TOMA30"
    assert precos[KC]["lido_em"] == "2026-09-19T10:00:00-03:00", "anúncio não visitado fica como estava"


# ------------------------------------------------------------------------------------------------
# 6. mensagem com vários anúncios
# ------------------------------------------------------------------------------------------------

def test_msg_melhor_entre_anuncios_mostra_o_vendedor(amb):
    amb.latest("cloud", [A, B], codigos=["DESCONTA100", "LU250"])
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KA, "DESCONTA100"): 100.0, (KB, "LU250"): 250.0})
    aceitos, _ = amb.rodar(loja)
    msg = tc.msg_melhor([("Magazine Luiza", r) for r in aceitos])
    assert "Melhor à vista</b>: R$ 3.461,55 na Magazine Luiza (vendido por Magalu) com <code>DESCONTA100</code>" in msg
    assert "Magazine Luiza (vendido por Lojas Colombo Oficial): R$ 3.687,15 (LU250)" in msg
    assert "ficou aplicado no carrinho da Magazine Luiza" in msg


def test_msg_compara_com_o_aceite_de_mais_cedo(amb):
    amb.latest("cloud", [A, B], codigos=["DESCONTA100", "TOMA30"])
    cedo = FIXO.replace(hour=12, minute=3)
    estado = {"magalu": {"cupons": {
        f"DESCONTA100@{KA}": _rec("aceito", cedo, total_pix=3461.55, total_cartao=3641.55, frete=0.0,
                                  quantidade=1)}}}
    loja = CarrinhoFalsoMagalu(amb.pasta, aceita={(KB, "TOMA30"): 30.0, (KA, "DESCONTA100"): 100.0})
    aceitos, _ = amb.rodar(loja, estado)
    assert [r.codigo for r in aceitos] == ["TOMA30", "DESCONTA100"]
    msg = tc.msg_melhor([("Magazine Luiza", r) for r in aceitos])
    assert "<code>DESCONTA100</code> (aceito mais cedo, hoje)" in msg
    assert "ficou aplicado no carrinho da Magazine Luiza" in msg


# ------------------------------------------------------------------------------------------------
# 7. Amazon: só leitura, uma página por vendedor
# ------------------------------------------------------------------------------------------------

class LeitorFalsoAmazon(Amazon):
    def __init__(self, pasta, precos, nao_confere=()):
        self.pasta, self.precos, self.nao_confere = pasta, precos, set(nao_confere)
        self.eventos: list[tuple] = []
        self.atual = None

    def perfil(self):
        return self.pasta

    def garantir_item(self, page, url, alvo=None):
        self.eventos.append(("abrir", alvo["chave"], url))
        self.atual = alvo["chave"]
        return alvo["chave"] not in self.nao_confere

    def ler_totais(self, page):
        pix, cartao = self.precos[self.atual]
        return ResultadoCupom(codigo="", aceito=False, total_pix=pix, total_cartao=cartao, produtos=cartao, frete=0.0)

    def cupom_da_pagina(self, page):
        return None

    def aplicar(self, page, codigo):  # pragma: no cover - não pode ser chamado
        raise AssertionError("a Amazon é só leitura")


def _oferta_amazon(seller: str, vendedor: str, pix: float, cartao: float) -> dict:
    return {"fonte": "amazon", "tipo": "loja", "loja": "Amazon", "ativo": True,
            "titulo": "Smart TV TCL 55 Polegadas QLED Mini LED 4K C6K WiFi Bluetooth Google TV 55C6K",
            "url": f"https://www.amazon.com.br/dp/B0F7JZMVKF?smid={seller}", "id": f"B0F7JZMVKF-{seller}",
            "vendedor": vendedor, "preco": cartao, "preco_pix": pix, "melhor_preco": min(pix, cartao),
            "extra": {"anuncio": "B0F7JZMVKF", "vendedor_id": seller}}


def test_amazon_le_cada_vendedor_sem_carrinho(amb):
    ofertas = [_oferta_amazon("A2COLOMBO01", "Lojas Colombo", 4184.88, 4184.88),
               _oferta_amazon("ACUNARZFR75ET", "Magalu.", 3374.10, 3749.0),
               _oferta_amazon("A3LEONFER01", "Leonfer", 5849.90, 5849.90),
               _oferta_amazon("A4OUTRO0001", "Outro", 5999.0, 5999.0)]
    amb.latest("pc", ofertas, codigos=["CARTAOAMZ15"], loja="Amazon")
    precos = {f"B0F7JZMVKF-{o['extra']['vendedor_id']}": (o["preco_pix"], o["preco"]) for o in ofertas}
    loja = LeitorFalsoAmazon(amb.pasta, precos, nao_confere={"B0F7JZMVKF-A3LEONFER01"})
    aceitos, estado = amb.rodar(loja, loja_id="amazon")
    abertos = [e[1] for e in loja.eventos]
    assert abertos == ["B0F7JZMVKF-ACUNARZFR75ET", "B0F7JZMVKF-A2COLOMBO01", "B0F7JZMVKF-A3LEONFER01"], \
        "do mais barato ao mais caro, até o limite de 3 páginas"
    assert "smid=ACUNARZFR75ET" in loja.eventos[0][2]
    precos_lidos = estado["amazon"]["precos"]
    assert set(precos_lidos) == {"B0F7JZMVKF-ACUNARZFR75ET", "B0F7JZMVKF-A2COLOMBO01"}, \
        "a página que mostrou outro vendedor não grava preço"
    assert precos_lidos["B0F7JZMVKF-ACUNARZFR75ET"]["tv_pix"] == 3374.10
    assert aceitos == [] and estado["amazon"]["cupons"] == {}


# ------------------------------------------------------------------------------------------------
# 4e. bases de preço: Pix se compara com Pix, cartão com cartão (revisão de 19/09, item B1)
# ------------------------------------------------------------------------------------------------

class CarrinhoSemPixNoResumo(CarrinhoFalsoMagalu):
    """Carrinho que NÃO mostra o preço do Pix, como o do Mercado Livre.

    Lá o resumo só traz o total no cartão e ler_totais copia esse número para total_pix (o desconto do Pix
    só aparece no pagamento), então `tv_pix` da leitura é, na verdade, um preço de CARTÃO. `precos` aqui são
    os totais no cartão. Sem linha de parcelado no resumo.
    """

    def _res(self, codigo: str, desconto: float = 0.0) -> ResultadoCupom:
        cartao = round(self.precos[self.no_carrinho] - desconto, 2)
        return ResultadoCupom(codigo=codigo, aceito=bool(desconto), produtos=cartao, frete=0.0,
                              desconto=desconto or None, total_pix=cartao, total_cartao=cartao,
                              pix_real=False, parcelado=None)


# 1P: Pix 3.491,03 e cartão 3.599,00 (o mais barato nas duas bases, e o robô NÃO abre este anúncio)
A_PIX = oferta_magalu("240162700", "magazineluiza", "Magalu", 3491.03, cartao=3599.00)
# Colombo: sem desconto de Pix, 3.749,00 nas duas bases; é o único com cupom pendente
B_CART = oferta_magalu("kc7h6f4k4b", "lojascolombooficial", "Lojas Colombo Oficial", 3749.00, cartao=3749.00)


def _so_o_mais_caro_pendente(amb, aceita):
    """Rodada em que só o anúncio mais caro tem cupom para testar (o 1P foi recusado há 1 h)."""
    amb.latest("cloud", [A_PIX, B_CART], codigos=["MLBAIXA200"])
    estado = {"magalu": {"cupons": {f"MLBAIXA200@{KA}": _rec("recusado", FIXO - timedelta(hours=1))}}}
    loja = CarrinhoSemPixNoResumo(amb.pasta, aceita=aceita, precos={KA: 3599.00, KB: 3749.00})
    return amb.rodar(loja, estado)


def test_cupom_que_e_o_melhor_no_cartao_nao_e_comparado_com_o_pix_de_outro_anuncio(amb):
    # 3.549,00 no cartão bate o cartão mais barato sem cupom (1P, 3.599,00); o Pix do 1P (3.491,03) é de
    # OUTRA base e não pode marcar este cupom como "não compensa" (senão a mensagem some).
    aceitos, _ = _so_o_mais_caro_pendente(amb, {(KB, "MLBAIXA200"): 200.0})
    r = aceitos[0]
    assert (r.codigo, r.tv_cartao) == ("MLBAIXA200", 3549.00)
    assert r.extra["pior_a_vista"] is False, "leitura sem Pix de verdade não se compara com o Pix coletado"
    assert r.extra["pior_parcelado"] is False, "3.549,00 é o melhor preço no cartão"
    assert "3.549,00" in tc.msg_melhor([("Magazine Luiza", r) for r in aceitos])


def test_referencia_sem_cupom_nao_mistura_cartao_lido_com_pix_coletado(amb):
    p = tc.Percurso(inicio=FIXO)
    anuncios = [tc.anuncio_da_oferta(CarrinhoSemPixNoResumo(amb.pasta), o) for o in (A_PIX, B_CART)]
    # o Colombo foi aberto: a leitura traz 3.749,00 no cartão e um "Pix" que é o mesmo cartão
    p.sem_cupom[KB] = ResultadoCupom(codigo="(sem cupom)", aceito=False, frete=0.0,
                                     total_pix=3749.00, total_cartao=3749.00, pix_real=False)
    ref_vista, ref_cartao = tc.referencia_sem_cupom(p, anuncios)
    assert ref_vista == 3491.03, "à vista: só preços de Pix de verdade (o do 1P, coletado)"
    assert ref_cartao == 3599.00, "cartão: o menor entre a leitura do Colombo e o cartão coletado do 1P"


def test_cupom_pior_que_o_cartao_mais_barato_continua_marcado(amb):
    # com 50 de desconto o Colombo fica em 3.699,00 no cartão, pior que os 3.599,00 do 1P: segue marcado
    aceitos, _ = _so_o_mais_caro_pendente(amb, {(KB, "MLBAIXA200"): 50.0})
    r = aceitos[0]
    assert r.tv_cartao == 3699.00 and r.extra["pior_parcelado"] is True
    assert tc.msg_melhor([("Magazine Luiza", r) for r in aceitos]) == "", "não é o melhor em base nenhuma"
