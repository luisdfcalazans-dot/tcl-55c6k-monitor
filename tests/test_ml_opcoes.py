"""Mercado Livre: cada opção do buy box vira uma oferta (a mais barata não pode sumir)."""

from pathlib import Path
from unittest import mock

import pytest

from monitor.sources import playwright_sources as ps

SNAP = Path(r"C:\Users\luisd\AppData\Local\Temp\claude\C--Users-luisd-OneDrive--rea-de-Trabalho-promos\8294b9c9-bb7f-4112-99fd-4c7e3e9f239b\scratchpad\snapshots")


@pytest.mark.skipif(not (SNAP / "mercadolivre_produto.html").exists(), reason="snapshot local de 18/09")
def test_emite_as_duas_opcoes_do_buybox(tmp_path, monkeypatch):
    html = (SNAP / "mercadolivre_produto.html").read_text(encoding="utf-8")
    texto = (SNAP / "mercadolivre_produto.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(ps, "MARCA_BLOQUEIO_ML", tmp_path / "ml_bloqueado_em")
    with mock.patch.object(ps, "_abrir", return_value=(html, texto, [])):
        ofertas, _ = ps.MercadoLivre().coletar()
    por_id = {o.id: o for o in ofertas}
    assert set(por_id) == {"MLB5417889802", "MLB7574364080"}, por_id.keys()
    melhor = por_id["MLB5417889802"]        # "Melhor preço", selecionada no snapshot
    assert (melhor.preco, melhor.preco_pix) == (3599.0, 3491.03)
    assert melhor.extra["opcao_ml"] == "BEST_PRICE"
    parc = por_id["MLB7574364080"]          # "Parcelamento sem juros"
    assert parc.preco == 3749.0 and parc.preco_pix is None
    assert parc.parcelado == "10x R$ 374,90 sem juros"
    assert parc.vendedor and "magalu" in parc.vendedor.lower()
    assert min(o.melhor_preco for o in ofertas) == 3491.03


def test_sem_buybox_devolve_a_oferta_original():
    from monitor.models import Oferta

    o = Oferta(fonte="mercadolivre", tipo="loja", loja="Mercado Livre", titulo="TCL 55C6K", url="u", id="MLB48808732", preco=3599.0)
    assert ps.MercadoLivre._por_opcao(o, "<html></html>", {}) == [o]
