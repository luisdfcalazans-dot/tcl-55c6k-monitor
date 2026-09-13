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
]


def test_aceita():
    for t in ACEITA:
        assert eh_55c6k(t), t


def test_rejeita():
    for t in REJEITA:
        assert not eh_55c6k(t), t
