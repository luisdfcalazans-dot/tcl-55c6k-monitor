"""SSD NVMe M.2 1TB para o notebook (pedido de 14/11/2026): qualquer marca, Gen3 ou Gen4, meta Pix R$ 700.

O classificador aceita só o SSD NVMe/PCIe/M.2 de 1TB; recusa SATA, externo/portátil, case/adaptador, outra capacidade
(ou várias no título), kit com mais de uma unidade e usado. Título de console com "SSD 1TB" continua sendo o console.
"""

from __future__ import annotations

import pytest

from monitor import produtos

ACEITOS = [
    ("SSD Kingston NV3 1TB M.2 2280 NVMe PCIe 4.0 Leitura 6000MB/s - SNV3S/1000G", "4"),
    ("SSD WD Blue SN580 1TB M.2 NVMe PCIe Gen4 x4 - WDS100T3B0E", "4"),
    ("SSD Samsung 990 EVO Plus 1TB PCIe 4.0 x4 / 5.0 x2 NVMe M.2", "4"),
    ("SSD Crucial P3 1TB 3D NAND NVMe PCIe M.2 - CT1000P3SSD8", None),
    ("SSD Lexar NM620 1TB M.2 2280 PCIe Gen3x4 NVMe", "3"),
    ("SSD M.2 NVMe 1TB Kingston NV2 PCIe 4.0 Notebook", "4"),
    ("Ssd Nvme M2 1tb Netac Nv3000 Pcie 3.0 Leitura 3100mb/s", "3"),
    ("SSD 1000GB Adata Legend 860 M.2 2280 NVMe PCIe Gen4", "4"),
    ("SSD Kingston Fury Renegade 1TB NVMe com dissipador para PS5", None),   # SSD para PS5 também serve: é o SSD
    ("SSD genérico 1TB NVMe M.2 2280 alta velocidade", None),                 # qualquer marca (decisão de 14/11)
]

RECUSADOS = [
    "SSD Kingston A400 1TB SATA III 2.5 polegadas",
    "SSD M.2 SATA 1TB Kingston KC600",
    "SSD Externo Portátil Samsung T7 1TB USB 3.2",
    "SSD Portable Sandisk 1TB USB-C",
    "SSD Kingston NV3 2TB M.2 NVMe PCIe 4.0",
    "SSD WD Black SN770 500GB NVMe M.2",
    "SSD NVMe M.2 512GB 1TB 2TB Kingston (escolha a capacidade)",
    "SSD Samsung 990 Pro 1TB NVMe usado poucas horas",
    "Case Gaveta para SSD M.2 NVMe 1TB USB-C",
    "Adaptador SSD M.2 NVMe para PCIe x4 1TB",
    "Kit 2 SSD Kingston NV3 1TB NVMe",
    "SSD Samsung 990 Pro 2TB com dissipador PS5",
    "SSD Kingston 1TB",   # sem NVMe/PCIe/M.2: pode ser SATA
]

CONSOLES = [
    ("Console Sony PlayStation 5 com Leitor de Discos SSD 1TB Controle sem fio DualSense 2 Jogos Branco", "PS5_DISCO"),
    ("Console PlayStation 5 Slim 1TB SSD com Leitor de Disco - Sony", "PS5_DISCO"),
    ("Console Sony PlayStation 5 SSD 825GB Controle sem fio DualSense 2 Jogos Digitais Edição Digital", "PS5_DIGITAL"),
]


@pytest.mark.parametrize("titulo,geracao", ACEITOS)
def test_ssd_aceito(titulo, geracao):
    c = produtos.classifica(titulo)
    assert c.produto == "SSD_NVME_1TB", (titulo, c.motivo)
    assert c.detalhes.get("geracao") == geracao


@pytest.mark.parametrize("titulo", RECUSADOS)
def test_ssd_recusado(titulo):
    c = produtos.classifica(titulo)
    assert c.produto is None, (titulo, c)
    assert c.motivo.startswith(("acessório", "estado")), c.motivo


@pytest.mark.parametrize("titulo,esperado", CONSOLES)
def test_console_com_ssd_continua_console(titulo, esperado):
    assert produtos.classifica(titulo).produto == esperado


def test_painel_mostra_o_ssd(tmp_path):
    """A seção do SSD sai do catálogo (sem nada fixo no painel): resumo com a meta e a pílula na vitrine."""
    import test_painel as tp

    ssd = tp.oferta("kabum", "KaBuM!", 459.9, 413.91, oid="SNV3S1000G")
    ssd.update(modelo="SSD_NVME_1TB", titulo="SSD Kingston NV3 1TB M.2 NVMe PCIe 4.0")
    cloud = tp.latest("cloud", tp.CLOUD_AT, [*tp.ofertas_cloud_hoje(), ssd], tp.MIN_MAGALU)
    cloud["produtos"] = produtos.para_painel()
    out = tp.roda_painel(tmp_path, cloud, tp.latest("pc", tp.PC_AT, tp.ofertas_pc_hoje(), tp.MIN_AMAZON))
    fam = {f["sec"]: f for f in out["vm"]["familias"]}
    assert list(fam)[:2] == ["PS5", "GTA6"] and fam["SSD"]["titulo"] == "SSD"
    (linha,) = fam["SSD"]["resumo"]
    assert linha["meta"]["v"] == tp.brl(700.0) and linha["melhor"]["v"] == tp.brl(413.91)
    assert linha["dist"] == {"v": tp.brl(700.0 - 413.91) + " abaixo", "ok": True}
    assert "SSD_NVME_1TB" in [it["id"] for it in out["vm"]["vitrine"]]
    assert "Netshoes" not in out["tabela"] and "SNV3S1000G" not in out["tabela"]   # a TV continua sem o SSD


def _cupom(loja, codigo, titulo, regra=""):
    from monitor.models import Cupom

    return Cupom("promobit", loja, codigo, titulo, "https://c", codigo, regra=regra)


@pytest.mark.parametrize("loja,codigo,titulo,ok", [
    # o alvo do SSD é hardware/informática/armazenamento (as regras de jogos recusavam "ssd" e "informática")
    ("KaBuM!", "INFO10", "10% OFF em Informática na KaBuM!", True),
    ("KaBuM!", "SSD50", "R$ 50 OFF em SSD", True),
    # qualquer marca: a loja oficial de uma marca não barra o cupom de SSD (no PS5 barraria)...
    ("Amazon", "KINGSTON15", "15% OFF em SSD na Loja Oficial Kingston", True),
    # ...mas sem dizer a categoria não vale: a Kingston também vende memória e pendrive
    ("Amazon", "KINGSTON15", "15% OFF na Loja Oficial Kingston", False),
    ("Mercado Livre", "TUDO10", "10% OFF em todo o site", True),
    ("KaBuM!", "PS5100", "R$ 100 OFF no PS5", False),                     # outro produto
    ("KaBuM!", "GAMES10", "10% OFF em Games, exceto Informática", False),
    ("Netshoes", "CAMISETA20", "20% OFF em Camisetas", False),
])
def test_cupom_do_ssd(loja, codigo, titulo, ok):
    from monitor import regras

    assert regras.cupom_compativel(_cupom(loja, codigo, titulo), 450.0, "SSD_NVME_1TB")[0] is ok


def test_cupom_de_ssd_continua_fora_do_ps5():
    from monitor import regras

    ok, motivo = regras.cupom_compativel(_cupom("KaBuM!", "SSD50", "R$ 50 OFF em SSD"), 3800.0, "PS5_DIGITAL")
    assert not ok, motivo


def test_catalogo_do_ssd():
    p = produtos.produto("SSD_NVME_1TB")
    assert (p.familia, p.secao, p.alvo_pix, p.alvo_parcelado) == ("SSD", "SSD", 700.0, 750.0)
    assert produtos.preco_plausivel("SSD_NVME_1TB", 450.0) and not produtos.preco_plausivel("SSD_NVME_1TB", 40.0)
    # as fontes mistas buscam o SSD (com ou sem as TVs desligadas)
    assert "ssd nvme 1tb" in produtos.termos("promobit")
    assert "ssd nvme 1tb" in produtos.termos("promobit", familias=[f for f in produtos.FAMILIAS if f != "TV"])
