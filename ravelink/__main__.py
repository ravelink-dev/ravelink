"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys

import ravelink


parser = argparse.ArgumentParser(prog="ravelink")
parser.add_argument("--version", action="store_true", help="Show Ravelink and runtime debug information.")

args = parser.parse_args()


def get_debug_info() -> None:
    python_info = "\n".join(sys.version.split("\n"))
    try:
        java_version = subprocess.check_output(["java", "-version"], stderr=subprocess.STDOUT)
        java = f'\n{" " * 8}- '.join(v for v in java_version.decode().splitlines() if v)
    except Exception:
        java = "Version Not Found"

    info = f"""
    Ravelink: {ravelink.__display_version__}

    Python:
        - {python_info}
    System:
        - {platform.platform()}
    Java:
        - {java}
    """

    print(info)


if args.version:
    get_debug_info()
