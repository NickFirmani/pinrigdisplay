"""Pure Pillow renderers for the built-in display pages."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont



WIDTH = 480
HEIGHT = 320
BACKGROUND = "#070f20"
ON_AIR_REGION = (38, 58, 442, 262)


def _luminance(color: tuple[int, int, int]) -> float:
    channels=[v/255 for v in color]
    linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in channels]
    return sum(v*w for v,w in zip(linear,(.2126,.7152,.0722)))


def _camera_stripe(face: tuple[int, int, int], level: float) -> tuple[int, int, int]:
    """Match ON AIR's luminance contrast while retaining the camera face hue."""
    reference_face=_scale_color((220,49,22),level)
    reference_stripe=_scale_color((170,30,16),level)
    contrast=(_luminance(reference_face)+.05)/(_luminance(reference_stripe)+.05)
    target=max(0.,(_luminance(face)+.05)/contrast-.05)
    low,high=0.,1.
    for _ in range(16):
        middle=(low+high)/2
        if _luminance(_scale_color(face,middle))<target:low=middle
        else:high=middle
    return _scale_color(face,(low+high)/2)


@lru_cache(maxsize=64)
def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "DejaVuSansCondensed-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / filename
    fallback = 'Arial Bold.ttf' if bold else 'Arial.ttf'
    for candidate in (str(path), filename, str(Path('/Library/Fonts') / fallback), str(Path('/System/Library/Fonts/Supplemental') / fallback)):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    raise OSError('Install DejaVu Sans fonts for display rendering')


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
    def __init__(self, logo_path: Path | None = None) -> None:
        self.logo_path = logo_path if logo_path is not None else Path(__file__).with_name('assets') / 'logo.png'
        self._unknown_image: Image.Image | None = None

    def compose(self, state: str, message: dict | None, diagnostic: str,
                sign_height: int = 320, seconds: float = 0.) -> Image.Image:
        """Fit the entire sign proportionally above a fixed-size plain-text card."""
        if state == 'unknown':
            sign = self.unknown_status()
        else:
            period = {'on_air': 4, 'camera_active': 3, 'camera_inactive': 6}.get(state, 6)
            level = .78 + .22 * (1 - math.cos(seconds * 2 * math.pi / period)) / 2
            if state == 'on_air':
                sign = self.on_air(level)
            else:
                sign = self.camera_status(active=state == 'camera_active', level=level)
        canvas = Image.new('RGB', (WIDTH, HEIGHT), BACKGROUND)
        sign.thumbnail((WIDTH, sign_height), Image.Resampling.LANCZOS)
        canvas.paste(sign, ((WIDTH - sign.width) // 2, (sign_height - sign.height) // 2))
        if sign_height < HEIGHT:
            title = (message or {}).get('title', '')
            body = (message or {}).get('body', '')
            card = Image.new('RGB', (WIDTH, 132), '#0d1c31')
            draw = ImageDraw.Draw(card)
            draw.line((12, 1, 468, 1), fill='#74a29b', width=3)
            for y, text, size, lines in ((10, title, 24, 1), (45, body, 22, 3)):
                font = _font(size, bold=y == 10)
                for line in _wrap(draw, text, font, 452, lines):
                    draw.text((14, y), line, font=font, fill='#f5f1e8')
                    y += 26
            canvas.paste(card, (0, sign_height))
        return canvas

    def unknown_status(self) -> Image.Image:
        """Show a static LCP logo and status caption, without a message card."""
        if self._unknown_image is None:
            canvas = Image.new('RGB', (WIDTH, HEIGHT), BACKGROUND)
            with Image.open(self.logo_path) as source:
                logo = source.convert('RGBA')
            logo.thumbnail((400, 258), Image.Resampling.LANCZOS)
            canvas.paste(logo, ((WIDTH - logo.width) // 2, 12), logo)
            _centered_text(ImageDraw.Draw(canvas), (12, 280, 468, 312),
                           'Stream Status Unknown', font=_font(20), fill='#f5f1e8')
            self._unknown_image = canvas
        return self._unknown_image.copy()

    def on_air(self, level: float, stripe_phase: int = 0, background_level: float | None = None) -> Image.Image:
        image = self._sign_housing(background="#100706", housing="#35100d",
                                   rim="#641a12", trim="#a94121", outline="#170706")
        draw = ImageDraw.Draw(image)

        self._draw_lit_panel(draw, level, stripe_phase, background_level)
        return image

    @staticmethod
    def _sign_housing(*, background: str, housing: str, rim: str,
                      trim: str, outline: str) -> Image.Image:
        image = Image.new("RGB", (WIDTH, HEIGHT), background)
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle((10, 30, 470, 290), radius=34,
                               fill=housing, outline=outline, width=6)
        draw.rounded_rectangle((20, 40, 460, 280), radius=27,
                               fill=rim, outline=trim, width=5)
        for x in (31, 449):
            for y in (51, 269):
                draw.ellipse((x - 7, y - 7, x + 7, y + 7),
                             fill="#d39254", outline="#3d160e", width=2)

        return image

    def camera_status(self, *, active: bool, level: float = 1., stripe_phase: int = 0) -> Image.Image:
        """Render a steady camera sign in the same housing as ON AIR."""
        if active:
            image = self._sign_housing(background="#100c06", housing="#35250d",
                                       rim="#644312", trim="#a97821", outline="#100c06")
            face, edge, highlight = "#b97812", "#ffc04c", "#ffda88"
            stripe, shadow, text = "#986010", "#66400a", "#fff4cc"
            title, subtitle = "ACTIVE", "NOT ON AIR"
        else:
            image = self._sign_housing(background="#090d12", housing="#1e2833",
                                       rim="#344250", trim="#6b7d8f", outline="#090d12")
            face, edge, highlight = "#344657", "#829aaf", "#a2b5c5"
            stripe, shadow, text = "#2c3b4a", "#18222e", "#e5edf2"
            title, subtitle = "INACTIVE", ""

        draw = ImageDraw.Draw(image)
        from PIL import ImageColor
        face = _scale_color(ImageColor.getrgb(face), level)
        self._panel_background(draw, face=face, edge=edge, highlight=highlight,
                               stripe=_camera_stripe(face,level), stripe_phase=stripe_phase)
        x0, y0, x1, y1 = ON_AIR_REGION
        if active:
            _centered_text(draw, (x0, y0 + 16, x1, y0 + 48), "CAMERA",
                           font=_font(28, bold=True), fill=text)
        title_font = _fit_font(draw, title, maximum=86, minimum=40,
                               width=x1 - x0 - 36)
        title_top = y0 + 44 if active else y0
        title_bottom = y1 - 50 if active else y1
        _centered_text(draw, (x0 + 2, title_top + 4, x1 + 2, title_bottom + 4), title,
                       font=title_font, fill=shadow)
        _centered_text(draw, (x0, title_top, x1, title_bottom), title,
                       font=title_font, fill=text)
        if subtitle:
            _centered_text(draw, (x0, y1 - 44, x1, y1 - 12), subtitle,
                           font=_font(23, bold=True), fill=text)
        return image

    @staticmethod
    def _draw_lit_panel(draw: ImageDraw.ImageDraw, level: float, stripe_phase: int = 0, background_level: float | None = None) -> None:
        x0, y0, x1, y1 = ON_AIR_REGION
        face_level = level if background_level is None else background_level
        face = _scale_color((220, 49, 22), face_level)
        edge = _scale_color((255, 130, 44), max(0.82, level))
        highlight = _scale_color((255, 176, 72), level)

        PageRenderer._panel_background(
            draw, face=face, edge=edge, highlight=highlight,
            stripe=_scale_color((170, 30, 16), face_level),
            stripe_phase=stripe_phase,
        )

        title_font = _font(103, bold=True)
        shadow_area = (x0 + 2, y0 + 4, x1 + 2, y1 - 24)
        _centered_text(draw, shadow_area, "ON AIR", font=title_font,
                       fill="#77170f")
        _centered_text(draw, (x0, y0, x1, y1 - 28), "ON AIR", font=title_font,
                       fill=(255, 244, 204))

        live_font = _font(19, bold=True)
        _centered_text(draw, (x0, y1 - 42, x1, y1 - 12),
                       "●  LIVE TRANSMISSION  ●", font=live_font,
                       fill=(255, 211, 128))

    @staticmethod
    def _panel_background(draw: ImageDraw.ImageDraw, *,
                          face: str | tuple[int, int, int],
                          edge: str | tuple[int, int, int],
                          highlight: str | tuple[int, int, int],
                          stripe: str | tuple[int, int, int], stripe_phase: int = 0) -> None:
        x0, y0, x1, y1 = ON_AIR_REGION
        draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=18,
                               fill=face, outline=edge, width=6)
        draw.rounded_rectangle((x0 + 10, y0 + 10, x1 - 11, y1 - 11), radius=12,
                               outline=highlight, width=3)
        for x in range(x0 - 48 + (stripe_phase % 4)*12, x1 + 48, 48):
            # Clip moving marks inside the panel, away from its fixed trim.
            for y in range(y0 + 14, y1 - 14):
                px = x - round(18*(y-y0-14)/(y1-y0-29))
                if x0+14 <= px < x1-14:
                    draw.line((px,y,px+1,y),fill=stripe)
