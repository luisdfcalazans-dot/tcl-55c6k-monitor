"""Travas de segurança: sacola do usuário, segredos em log."""

from monitor import config, notificar
from monitor.carrinho import Magalu


def test_log_nunca_mostra_o_token(monkeypatch):
    token = "1234567890:AAFakeTokenForTestsOnly_abcdefghijk"
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", token)
    erro = f"HTTPSConnectionPool(host='api.telegram.org'): Max retries exceeded with url: /bot{token}/sendMessage"
    limpo = notificar._sem_segredo(erro)
    assert token not in limpo and "<token>" in limpo


def test_log_tira_token_mesmo_sem_config(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    s = notificar._sem_segredo("url: /bot9999999999:AAAAAAAAAAAAAAAAAAAAAAAAAAAA/sendMessage")
    assert "AAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in s


def test_sacola_so_e_mexida_quando_so_tem_a_tv():
    tv = {"id": "240162700", "titulo": 'Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz Google TV'}
    tv2 = {"id": "eecab9199g", "titulo": "Smart TV C6K 55 Polegadas 4K 144 HZ QLED Mini Led TCL"}
    outro = {"id": "abc123", "titulo": "Air Fryer Mondial 4L"}
    assert Magalu._so_tvs([tv]) is True
    assert Magalu._so_tvs([tv, tv2]) is True
    assert Magalu._so_tvs([tv, outro]) is False, "com outro produto na sacola, não se mexe"
    assert Magalu._so_tvs(None) is False, "sacola ilegível: não se mexe"
    assert Magalu._so_tvs([]) is True
