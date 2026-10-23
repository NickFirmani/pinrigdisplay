"""Pure Pillow renderers for the built-in display pages."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..models import DisplayRequest


WIDTH = 480
HEIGHT = 320
BACKGROUND = "#070f20"
ON_AIR_REGION = (38, 58, 442, 262)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "DejaVuSansCondensed-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / filename
    return ImageFont.truetype(str(path), size)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, *, maximum: int,
              minimum: int, width: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    for size in range(maximum, minimum - 1, -2):
        font = _font(size, bold=bold)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= width:
            return font
    return _font(minimum, bold=bold)


def _centered_text(draw: ImageDraw.ImageDraw, area: tuple[int, int, int, int],
                   text: str, *, font: ImageFont.ImageFont, fill: str) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    text_width = box[2] - box[0]
    text_height = box[3] - box[1]
    x = area[0] + (area[2] - area[0] - text_width) // 2 - box[0]
    y = area[1] + (area[3] - area[1] - text_height) // 2 - box[1]
    draw.text((x, y), text, font=font, fill=fill)


def _scale_color(color: tuple[int, int, int], level: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(channel * level))) for channel in color)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
          width: int, maximum_lines: int) -> list[str]:
    def split_word(word: str) -> list[str]:
        pieces: list[str] = []
        piece = ""
        for character in word:
            candidate = piece + character
            if piece and draw.textlength(candidate, font=font) > width:
                pieces.append(piece)
                piece = character
            else:
                piece = candidate
        if piece:
            pieces.append(piece)
        return pieces

    logical_lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = [
            piece
            for word in paragraph.split()
            for piece in split_word(word)
        ]
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and draw.textlength(candidate, font=font) > width:
                logical_lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            logical_lines.append(current)

    truncated = len(logical_lines) > maximum_lines
    lines = logical_lines[:maximum_lines]
    if truncated and lines:
        last = lines[-1]
        while last and draw.textlength(f"{last}…", font=font) > width:
            last = last[:-1]
        lines[-1] = f"{last.rstrip()}…"
    return lines


class PageRenderer:
    def __init__(self, logo_path: Path) -> None:
        self.logo_path = logo_path

    def render(self, request: DisplayRequest) -> Image.Image:
        if request.page == "standby":
            return self.standby()
        if request.page == "on_air":
            return self.on_air(0.80)
        if request.page == "message":
            assert request.title is not None and request.body is not None
            return self.message(request.title, request.body)
        raise ValueError(f"unsupported page: {request.page}")

    def standby(self) -> Image.Image:
        canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        with Image.open(self.logo_path) as source:
            logo = source.convert("RGBA")
        logo.thumbnail((368, 288), Image.Resampling.LANCZOS)
        position = ((WIDTH - logo.width) // 2, (HEIGHT - logo.height) // 2)
        canvas.paste(logo, position, logo)
        return canvas

    def message(self, title: str, body: str) -> Image.Image:
        image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((18, 18, 462, 302), radius=18,
                               fill="#0d1c31", outline="#74a29b", width=4)
        draw.rectangle((34, 91, 446, 96), fill="#e7620b")

        title_font = _fit_font(draw, title.upper(), maximum=54, minimum=28,
                               width=400)
        _centered_text(draw, (34, 28, 446, 86), title.upper(),
                       font=title_font, fill="#fff0b5")

        body_font = _font(34)
        lines = _wrap(draw, body, body_font, 390, 4)
        line_height = 43
        total_height = len(lines) * line_height
        y = 111 + max(0, (174 - total_height) // 2)
        for line in lines:
            _centered_text(draw, (38, y, 442, y + line_height), line,
                           font=body_font, fill="#f5f1e8")
            y += line_height
        return image

    def on_air(self, level: float) -> Image.Image:
        image = Image.new("RGB", (WIDTH, HEIGHT), "#100706")
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle((10, 30, 470, 290), radius=34,
                               fill="#35100d", outline="#170706", width=6)
        draw.rounded_rectangle((20, 40, 460, 280), radius=27,
                               fill="#641a12", outline="#a94121", width=5)
        for x in (31, 449):
            for y in (51, 269):
                draw.ellipse((x - 7, y - 7, x + 7, y + 7),
                             fill="#d39254", outline="#3d160e", width=2)

        self._draw_lit_panel(draw, level)
        return image

    def on_air_frames(self, count: int) -> list[Image.Image]:
        if count < 2:
            raise ValueError("animation requires at least two frames")
        frames = []
        for index in range(count):
            phase = 2.0 * math.pi * index / count
            level = 0.72 + 0.28 * ((1.0 - math.cos(phase)) / 2.0)
            frames.append(self.on_air(level).crop(ON_AIR_REGION))
        return frames

    @staticmethod
    def _draw_lit_panel(draw: ImageDraw.ImageDraw, level: float) -> None:
        x0, y0, x1, y1 = ON_AIR_REGION
        face = _scale_color((220, 49, 22), level)
        edge = _scale_color((255, 130, 44), max(0.82, level))
        highlight = _scale_color((255, 176, 72), level)

        draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=18,
                               fill=face, outline=edge, width=6)
        draw.rounded_rectangle((x0 + 10, y0 + 10, x1 - 11, y1 - 11), radius=12,
                               outline=highlight, width=3)

        for x in range(x0 + 28, x1 - 20, 48):
            draw.line((x, y0 + 14, x - 18, y1 - 15),
                      fill=_scale_color((170, 30, 16), level), width=2)

        title_font = _font(103, bold=True)
        shadow_area = (x0 + 2, y0 + 4, x1 + 2, y1 - 24)
        _centered_text(draw, shadow_area, "ON AIR", font=title_font,
                       fill="#77170f")
        _centered_text(draw, (x0, y0, x1, y1 - 28), "ON AIR", font=title_font,
                       fill=_scale_color((255, 244, 204), 0.88 + level * 0.12))

        live_font = _font(19, bold=True)
        _centered_text(draw, (x0, y1 - 42, x1, y1 - 12),
                       "●  LIVE TRANSMISSION  ●", font=live_font,
                       fill=_scale_color((255, 211, 128), level))
