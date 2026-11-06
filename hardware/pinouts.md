## Raspberry Pi Pico 2 W → Elecrow 4" ST7796S + XPT2046 Touch

Complete soldering pinout using SPI0, with LCD and touchscreen sharing the SPI bus.

| Elecrow pin # | Signal     | Pico 2 W GPIO | Pico physical pin | Elecrow pin # |
| ------------- | ---------- | ------------- | ----------------- | ------------- |
| 1             | VCC        | VBUS (5V USB) | 40                | 1             |
| 2             | GND        | GND           | 38                | 2             |
| 3             | CS         | GP17          | 22                | 3             |
| 4             | RESET      | GP21          | 27                | 4             |
| 5             | DC/RS      | GP20          | 26                | 5             |
| 6             | SDI (MOSI) | GP19          | 25                | 6             |
| 7             | SCK        | GP18          | 24                | 7             |
| 8             | LED        | 3V3(OUT)      | 36                | 8             |
| 9             | SDO (MISO) | GP16          | 21                | 9             |
| 10            | T_CLK      | GP18 (shared) | 24                | 10            |
| 11            | T_CS       | GP22          | 29                | 11            |
| 12            | T_DIN      | GP19 (shared) | 25                | 12            |
| 13            | T_DO       | GP16 (shared) | 21                | 13            |
| 14            | T_IRQ      | GP15          | 20                | 14            |


### Shared solder connections

Only 11 unique connections are needed between the two boards.

| Pico pin  | Solder to Elecrow pins |
| --------- | ---------------------- |
| GP18 (24) | 7 + 10 — SPI clock     |
| GP19 (25) | 6 + 12 — MOSI          |
| GP16 (21) | 9 + 13 — MISO          |

Join these at the display or with short Y-splices. Each controller has its own chip select (`GP17` for LCD, `GP22` for touch).

Pico GP numbers are GPIO identifiers, not physical pins or Linux BCM numbers.

Connector reference: [display connector image](img.png).
