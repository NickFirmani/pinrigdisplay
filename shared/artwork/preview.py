"""Render deterministic UI scenarios without SPI: python -m shared.artwork.preview."""
import argparse
from pathlib import Path
from PIL import Image
from .layout import COMPACT_SIGN_HEIGHT, HEIGHT, WIDTH
from .pages import PageRenderer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    pages = PageRenderer()
    sheet = Image.new('RGB', (2 * WIDTH, 4 * HEIGHT))
    for row, state in enumerate(('on_air', 'camera_active', 'camera_inactive', 'unknown')):
        for col, message in enumerate((None, {'title': 'PLAYER READY', 'body': 'Please approach the machine. Good luck!'})):
            height = COMPACT_SIGN_HEIGHT if message else HEIGHT
            frame = pages.compose(state, message, 'Waiting for a current host command', height, 0)
            sheet.paste(frame, (col * WIDTH, row * HEIGHT))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output)


if __name__ == '__main__':
    main()
