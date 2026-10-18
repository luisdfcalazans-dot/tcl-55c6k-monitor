"""TVs desligadas a pedido do usuário (17/10/2026, fim da vigia da 65C6K comprada): o modo vigia continua ligado depois
de VIGIA_ATE e nenhuma TV vira candidata a alerta; PS5 e GTA 6 seguem normais."""

from monitor import config


def test_tvs_desligadas_mantem_a_vigia_depois_da_data(monkeypatch):
    monkeypatch.setattr(config, "VIGIA_ATE", "2026-10-17")
    monkeypatch.setattr(config, "TVS_DESLIGADAS", True)
    assert config.modo_vigia("2026-10-18") and config.modo_vigia("2027-01-01")
    assert config.vigia_afeta("55C6K") and config.vigia_afeta("65C6K")
    assert not config.vigia_afeta("PS5_DIGITAL") and not config.vigia_afeta("GTA6_CODE_IN_BOX")


def test_religar_as_tvs_volta_a_regra_da_data(monkeypatch):
    monkeypatch.setattr(config, "VIGIA_ATE", "2026-10-17")
    monkeypatch.setattr(config, "TVS_DESLIGADAS", False)
    assert config.modo_vigia("2026-10-17") and not config.modo_vigia("2026-10-18")
