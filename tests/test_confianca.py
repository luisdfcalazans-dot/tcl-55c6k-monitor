"""Bloqueio de vendedor/anúncio com sinais de fraude (caso Importados Lili, 25/09/2026)."""

from monitor.confianca import motivo_bloqueio
from monitor.models import Oferta

URL_LILI = ("https://www.magazineluiza.com.br/smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-google-"
            "assistente-4-hdmi-2-usb/p/kc3ca4k960/et/elit/")
URL_1P = ("https://www.magazineluiza.com.br/smart-tv-55-tcl-4k-uhd-miniled-55c6k-120hz-google-tv-aipq-google-"
          "assistente-4-hdmi-2-usb/p/240162700/et/elit/")


def test_oferta_real_da_lili_bloqueada():
    # o registro real do latest_cloud de 25/09 20:18
    o = {"loja": "Magazine Luiza", "vendedor": "Importados Lili", "id": "kd12g2e47k-importadoslili", "url": URL_LILI,
         "extra": {"vendedor_id": "importadoslili"}}
    assert motivo_bloqueio(o)


def test_bloqueia_por_qualquer_pista():
    base = dict(fonte="magalu", tipo="loja", loja="Magazine Luiza", titulo="Smart TV 55 TCL 55C6K")
    assert motivo_bloqueio(Oferta(**base, url=URL_1P + "?seller_id=importadoslili", id="x"))       # só a URL
    assert motivo_bloqueio(Oferta(**base, url="u", id="y", vendedor="Importados  Lili"))            # só o nome
    assert motivo_bloqueio(Oferta(**base, url=URL_LILI, id="z", vendedor="Outro"))                  # só o anúncio


def test_nao_bloqueia_vendedor_confiavel_nem_outra_loja():
    base = dict(fonte="magalu", tipo="loja", titulo="Smart TV 55 TCL 55C6K")
    assert motivo_bloqueio(Oferta(**base, loja="Magazine Luiza", url=URL_1P, id="240162800-magazineluiza",
                                  vendedor="Magalu", extra={"vendedor_id": "magazineluiza"})) is None
    assert motivo_bloqueio(Oferta(**base, loja="Amazon", url="https://www.amazon.com.br/dp/B0F7JZMVKF", id="a",
                                  vendedor="Importados Lili")) is None
