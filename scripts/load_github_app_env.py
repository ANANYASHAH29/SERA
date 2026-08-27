"""Loads .env.github_app (written by register_github_app.py) into the
current process's environment, then execs uvicorn. Needed because the
private key is multi-line PEM, which a plain `export KEY=value` line
can't hold -- register_github_app.py writes it as a `KEY<<'EOF' ... EOF`
block instead, so it needs a parser that understands that, not a
standard one-line-per-var .env loader.

Usage:
    python scripts/load_github_app_env.py -- uvicorn sera.api.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env.github_app"


def load_env_file(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line:
            key, _, _ = line.partition("<<")
            key = key.strip()
            i += 1
            value_lines = []
            while i < len(lines) and lines[i].strip() != "EOF":
                value_lines.append(lines[i])
                i += 1
            os.environ[key] = "\n".join(value_lines)
            i += 1  # skip the closing EOF
        elif "=" in line and line.strip():
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip()
            i += 1
        else:
            i += 1


def main():
    if not ENV_PATH.exists():
        print(f"{ENV_PATH} not found -- run scripts/register_github_app.py first", file=sys.stderr)
        sys.exit(1)
    load_env_file(ENV_PATH)

    if "--" not in sys.argv:
        print("usage: python scripts/load_github_app_env.py -- <command> [args...]", file=sys.stderr)
        sys.exit(1)
    command = sys.argv[sys.argv.index("--") + 1 :]

    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
