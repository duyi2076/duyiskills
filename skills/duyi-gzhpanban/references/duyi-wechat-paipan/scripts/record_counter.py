#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


DEFAULT_PATH = Path("~/.config/duyi-wechat/counters.json").expanduser()
DEFAULT_TEMPLATE = "这是杜一的第 {next} 篇公开记录"


def load(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def entry(data, name):
    data.setdefault(name, {"current": 0, "template": DEFAULT_TEMPLATE})
    data[name].setdefault("template", DEFAULT_TEMPLATE)
    data[name].setdefault("current", 0)
    return data[name]


def render(e):
    nxt = int(e.get("current", 0)) + 1
    return str(e.get("template", DEFAULT_TEMPLATE)).format(next=nxt, current=e.get("current", 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["next", "commit", "status", "set"])
    ap.add_argument("name")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--template")
    ap.add_argument("--file", default=str(DEFAULT_PATH))
    args = ap.parse_args()

    path = Path(args.file).expanduser()
    data = load(path)
    e = entry(data, args.name)

    if args.command == "next":
        print(render(e))
        return
    if args.command == "status":
        print(json.dumps({args.name: e, "next_text": render(e)}, ensure_ascii=False, indent=2))
        return
    if args.command == "set":
        if args.value is None:
            raise SystemExit("set requires a current count value")
        e["current"] = int(args.value)
        if args.template:
            e["template"] = args.template
        save(path, data)
        print(json.dumps({args.name: e, "next_text": render(e)}, ensure_ascii=False, indent=2))
        return
    if args.command == "commit":
        e["current"] = int(e.get("current", 0)) + 1
        save(path, data)
        print(json.dumps({args.name: e, "committed_text": str(e.get("template", DEFAULT_TEMPLATE)).format(next=e["current"], current=e["current"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

