#!/usr/bin/env python3
"""Interactively send synthetic Twitch chat through PinRig's stream chat path."""

import argparse
import json
from pathlib import Path
import select
import sys
import threading
import time
import termios
import tty
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.net import request_json
from stream.chat import Chat
from stream.overview import load_config


def send(chat: Chat, user_id: str, name: str, body: str) -> None:
    chat.receive(uuid4().hex, user_id, name, body)


def send_scenario(chat: Chat, scenario: int) -> None:
    if scenario == 1:
        send(chat, "alice-id", "Alice", "Nice shot!")
    elif scenario == 2:
        for body in ("Great game", "That was close", "One more!"):
            send(chat, "alice-id", "Alice", body)
    elif scenario == 3:
        send(chat, "alice-id", "Alice", "First message")
        send(chat, "alice-id", "Alice", "Another from Alice")
        send(chat, "bob-id", "Bob", "Go team!")


def poll_rig(rig: dict, chat: Chat, status: dict, stop: threading.Event) -> None:
    url = rig["url"].rstrip("/") + "/api/status"
    while not stop.is_set():
        try:
            value = request_json(url)
            report = value.get("chat", {}) if isinstance(value, dict) else {}
            if not isinstance(report, dict):
                report = {}
            chat.report(rig["id"], report)
            status[rig["id"]] = "healthy" if report.get("healthy") is True else "unavailable"
        except (OSError, ValueError) as error:
            chat.report(rig["id"], {})
            status[rig["id"]] = f"unreachable ({error})"
        stop.wait(2)


def show_menu(chat: Chat, rigs: list[dict], selected: int, live: bool, mode: str,
              status: dict) -> None:
    rig = rigs[selected]
    enabled = chat.targets[rig["id"]].enabled
    outcome = chat.outcome(rig["id"]) or "no delivery yet"
    print(f"\nTwitch simulator — {mode}; channel: {'LIVE' if live else 'OFFLINE'}")
    print(f"  target: {rig['id']} ({'enabled' if enabled else 'muted'}), display: {status.get(rig['id'], 'checking')}")
    print(f"  last delivery: {outcome}")
    print("  1  send one chat message")
    print("  2  send three messages from one chatter (one card)")
    print("  3  send two chatters (separate cards)")
    print("  l  toggle simulated stream live/offline")
    print("  n  select next rig     t  toggle selected rig")
    print("  a  toggle automatic chat     m  manual mode")
    print("  q  quit")
    print("Key: ", end="", flush=True)


def run_console(chat: Chat, rigs: list[dict], stop: threading.Event,
                status: dict, interval: float) -> None:
    if not sys.stdin.isatty():
        raise RuntimeError("interactive simulator needs a terminal")
    original = termios.tcgetattr(sys.stdin.fileno())
    selected, live, mode, auto_scenario = 0, True, "manual", 0
    next_auto = time.monotonic() + interval
    try:
        tty.setcbreak(sys.stdin.fileno())
        show_menu(chat, rigs, selected, live, mode, status)
        while not stop.is_set():
            now = time.monotonic()
            if mode == "auto" and now >= next_auto:
                auto_scenario = auto_scenario % 3 + 1
                send_scenario(chat, auto_scenario)
                next_auto = now + interval
                show_menu(chat, rigs, selected, live, mode, status)
            ready, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not ready:
                continue
            key = sys.stdin.read(1).lower()
            if key == "q":
                return
            if key == "a":
                mode = "manual" if mode == "auto" else "auto"
                next_auto = time.monotonic() + interval
            elif key == "m":
                mode = "manual"
            elif key == "l":
                mode = "manual"
                live = not live
                chat.channel(True, live)
            elif key == "n":
                mode = "manual"
                selected = (selected + 1) % len(rigs)
            elif key == "t":
                mode = "manual"
                rig_id = rigs[selected]["id"]
                chat.enable(rig_id, not chat.targets[rig_id].enabled)
            elif key in "123":
                mode = "manual"
                send_scenario(chat, int(key))
            else:
                continue
            show_menu(chat, rigs, selected, live, mode, status)
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path.home() / "stream-config.json",
                        help="Stream PC JSON config (default: ~/stream-config.json)")
    parser.add_argument("--interval", type=float, default=8.0,
                        help="seconds between auto scenarios (default: 8)")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("interval must be greater than zero")
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as error:
        parser.error(f"cannot load stream config: {error}")

    rigs = config["rigs"]
    chat = Chat(rigs)
    chat.channel(True, True)
    stop = threading.Event()
    status = {rig["id"]: "checking" for rig in rigs}
    workers = [threading.Thread(target=poll_rig, args=(rig, chat, status, stop), daemon=True)
               for rig in rigs]
    workers += [threading.Thread(target=chat.run_rig, args=(rig, stop), daemon=True)
                for rig in rigs]
    for worker in workers:
        worker.start()
    print("Synthetic chat is marked live and enabled for each configured rig.")
    print("This sends to the configured rig APIs; it does not connect to Twitch.")
    try:
        run_console(chat, rigs, stop, status, args.interval)
    except KeyboardInterrupt:
        print("\nStopping Twitch simulator")
    except RuntimeError as error:
        parser.error(str(error))
    finally:
        stop.set()
        for worker in workers:
            worker.join()


if __name__ == "__main__":
    main()
