from monitor.filtro import eh_55c6k

ACEITA = [
    'Smart TV 55" TCL 4K UHD MiniLED 55C6K 120Hz',
    "Smart TV TCL 55 Polegadas QLED Mini LED 4K C6K WiFi Bluetooth Google TV 4 HDMI 144Hz HDR10+ 55C6K",
    "Smart TV 4K TCL QD-Mini LED 55” Polegadas com HDMI 2.1, Dolby Vision IQ, Subwoofer, 144Hz VRR e Wi-Fi - 55C6K",
    "Smart TV 55 TCL 55C6K 4K QDMini Led 144Hz Sistema Operacional Google TV",
    "Smart TV TCL 55 AI, 4K UHD, QLED Mini LED, Android TV - 55C6K",
    "Smart TV Mini LED 55\" TCL 4K 55C6K",
    "TV TCL 55 C6K por R$ 2.899 no Pix com cupom",
    "Smart TV TCL 55C6K/65C6K QD-Mini LED (loja oficial)",
    # "suporte a" é recurso da TV, não o acessório (postagem no estilo do Canaltech)
    '🔥 Smart TV TCL 55" QD-Mini LED 55C6K com suporte a Dolby Vision IQ, HDR10+ e 144Hz',
    "Smart TV TCL 55C6K com suporte a HDR10+, Wi-Fi e Bluetooth",
    # controle remoto, display e "para TV" dentro do título da própria TV
    'Smart TV TCL 55" QD-Mini LED 4K 55C6K com Controle por Voz',
    "Smart TV TCL 55C6K com Controle Remoto",
    "Smart TV TCL 55C6K QD-Mini LED Display 144Hz",
    'Smart TV TCL 55" 55C6K ideal para TV e games',
]
REJEITA = [
    "Smart TV TCL 65 Polegadas QLED Mini LED 4K C6K WiFi 65C6K",
    "Smart TV TCL 75 Polegadas QLED Mini LED 4K C6K 75C6K",
    "Combo Smart TV TCL 55 QLED Mini LED 4K C6K WiFi 144Hz 55C6K e Soundbar TCL Subwoofer 2.1 S55H",
    "Combo Smart TV TCL 55 QLED Mini LED 4K C6K WiFi 144Hz 55C6K e Smart TV TCL 32 HD QLED S5K",
    'Smart TV QLED 50" TCL 4K P7K',
    "Smart TV TCL 55 Polegadas QLED 4K C655 WiFi Bluetooth Google TV 55C655",
    "Smart TV TCL 55 Polegadas QLED 4K P8K WiFi 55P8K",
    "Suporte de parede para TV TCL 55C6K",
    "Smart TV TCL 55C6K usada com defeito",
    "Smart Tv 4k Uhd Led 58 Philips Pug7019",
    # acessórios e peças com "55C6K" no título (caso real do Magalu: controle de R$ 149,99)
    "Controle comando de voz para tv tcl 55c6k 65c6k 75c6k 85c6k 98c6k",
    "Controle comando de voz para tv tcl 55c6k",
    "Barra de LED para TV TCL 55C6K",
    "Placa principal TCL 55C6K",
    "Fonte de alimentação TV TCL 55C6K",
    "Tela display painel TCL 55C6K",
    "Suporte a TV TCL 55C6K",
    "Smart TV TCL 55C6K com suporte de parede",
    # TV + suporte/kit: combo, não a TV sozinha
    "Smart TV TCL 55C6K com suporte à parede",
    "Smart TV TCL 55C6K + Suporte a Parede Articulado",
    "Smart TV TCL 55C6K + Kit Suporte Articulado",
    # acessório reconhecido pelo substantivo do produto, mesmo com o modelo antes
    "TCL 55C6K Controle Remoto Original",
    "Controle Remoto Compatível TV TCL 55C6K",
    "Display para TV TCL 55C6K",
    # produto que não é novo
    "Smart TV TCL 55C6K Reembalado",
    "Smart TV TCL 55C6K Mostruário",
    "Smart TV TCL 55C6K Recertificado",
    "Smart TV TCL 55C6K com avaria na embalagem",
    # anúncio de vários tamanhos, mesmo citando 55C6K
    "Smart TV TCL 65C6K 55C6K 75C6K Mini LED",
    "Smart TV TCL 55C6K/65C6K/75C6K",
    "Smart TV TCL 55C6K 65C6K",
]


def test_aceita():
    for t in ACEITA:
        assert eh_55c6k(t), t


def test_rejeita():
    for t in REJEITA:
        assert not eh_55c6k(t), t
