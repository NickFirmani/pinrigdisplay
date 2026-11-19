"""Install a built display release over USB from a macOS or Linux workstation."""
import argparse
from pathlib import Path
import subprocess

from rig.display_host.delivery import SerialDelivery
from rig.display_host.service import Host
from rig.server.firmware_install import FirmwareInstaller


def usb_port(value: str) -> str:
    """Require an explicit local serial device path."""
    path = Path(value)
    if Path('/dev') not in path.parents or not path.is_char_device():
        raise argparse.ArgumentTypeError('select a connected Pico serial device under /dev')
    return str(path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True, help='built display release directory')
    parser.add_argument('--port', type=usb_port, required=True,
                        help='Pico USB serial path from mpremote connect list')
    args = parser.parse_args(argv)
    try:
        import serial
    except ModuleNotFoundError:
        parser.exit(1, 'install-display: install mpremote and pyserial in this Python environment\n')

    host = Host(SerialDelivery(lambda: serial.Serial(
        args.port, 115200, timeout=.1, write_timeout=1, exclusive=True)))
    try:
        result = FirmwareInstaller(host, args.port).install(
            args.bundle.resolve(), lambda phase: print(phase, flush=True))
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'install-display: {error}\n')
    finally:
        host.close()

    print(f"Installed {result['release']}. Display is healthy and reports "
          f"{result['displayed_state']}.")


if __name__ == '__main__':
    main()
