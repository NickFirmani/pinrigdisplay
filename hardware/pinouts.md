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


| Pico physical pin | Elecrow pin # |
| ----------------- | ------------- |
| 20                | 14            |
| 21                | 13            |
| 21                | 9             |
| 22                | 3             |
| 24                | 10            |
| 24                | 7             |
| 25                | 12            |
| 25                | 6             |
| 26                | 5             |
| 27                | 4             |
| 29                | 11            |
| 36                | 8             |
| 38                | 2             |
| 40                | 1             |


| Pico physical pin | Elecrow pin # |
| ----------------- | ------------- |
| 40                | 1             |
| 38                | 2             |
| 36                | 8             |
| 29                | 11            |
| 27                | 4             |
| 26                | 5             |
| 25                | 6             |
| 25                | 12            |
| 24                | 7             |
| 24                | 10            |
| 22                | 3             |
| 21                | 9             |
| 21                | 13            |
| 20                | 14            |

### Shared solder connections

Only 11 unique connections are needed between the two boards.

| Pico pin  | Solder to Elecrow pins |
| --------- | ---------------------- |
| GP18 (24) | 7 + 10 — SPI clock     |
| GP19 (25) | 6 + 12 — MOSI          |
| GP16 (21) | 9 + 13 — MISO          |

Join these at the display or with short Y-splices. Each controller has its own chip select (`GP17` for LCD, `GP22` for touch).

### Firmware pin constants

```

#define TFT_MISO  16
#define TFT_MOSI  19
#define TFT_SCLK  18
#define TFT_CS    17
#define TFT_DC    20
#define TFT_RST   21

#define TOUCH_CS  22
#define TOUCH_IRQ 15

```

These are GPIO numbers, not physical pin numbers.

Original wiring reference: [display connector image](img.png).
