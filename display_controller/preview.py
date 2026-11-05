"""Render deterministic UI scenarios without SPI: python -m display_controller.preview."""
import argparse
from pathlib import Path
from PIL import Image
from .display.pages import PageRenderer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    pages = PageRenderer()
    sheet = Image.new('RGB', (960, 1280))
    for row, state in enumerate(('on_air', 'camera_active', 'camera_inactive', 'unknown')):
        for col, message in enumerate((None, {'title': 'PLAYER READY', 'body': 'Please approach the machine. Good luck!'})):
            height = 188 if message and state != 'unknown' else 320
            frame = pages.compose(state, message, 'Waiting for a current host command', height, 0)
            sheet.paste(frame, (col*480, row*320))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output)


if __name__ == '__main__':
    main()
