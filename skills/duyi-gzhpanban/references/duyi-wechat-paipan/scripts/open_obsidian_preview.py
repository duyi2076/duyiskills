#!/usr/bin/env python3
import argparse
import shutil
import subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("markdown_file")
    args = ap.parse_args()
    path = Path(args.markdown_file).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    if shutil.which("open"):
        try:
            subprocess.run(["open", "-a", "Obsidian", str(path)], check=True)
            print(f"Opened in Obsidian: {path}")
            return
        except subprocess.CalledProcessError:
            subprocess.run(["open", str(path)], check=True)
            print(f"Opened with default app: {path}")
            return

    print(path)


if __name__ == "__main__":
    main()

