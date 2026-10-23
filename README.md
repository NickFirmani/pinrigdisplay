# Pin Rig Display

Minimal Raspberry Pi SPI driver/test for an Elecrow ST7796 display.

## Wiring

| Display | Pi physical pin | BCM/function |
| --- | ---: | --- |
| VCC | 2 | 5 V |
| GND | 6 | Ground |
| CS | 24 | GPIO8 / SPI0 CE0 |
| RESET | 22 | GPIO25 |
| DC/RS | 18 | GPIO24 |
| SDI (MOSI) | 19 | GPIO10 / SPI0 MOSI |
| SCK | 23 | GPIO11 / SPI0 SCLK |
| LED | 17 | 3.3 V |

## Run

The Pi needs SPI enabled and the Debian packages providing `python3-spidev`,
`python3-rpi.gpio`, and `python3-pil`.

```sh
python3 st7796_hello.py
```

The script initializes the controller in 480x320 landscape RGB565 mode and
draws a yellow `hello` centered on a dark background. If long jumper wires make
the default 20 MHz SPI clock unreliable, retry with `--speed 10000000`.
