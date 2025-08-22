#!/usr/bin/env python3
import datetime
import os
import pathlib
import re
import sys

OWNER = os.getenv("COPYRIGHT_OWNER", "AlphaAvatar project")
YEAR = os.getenv("COPYRIGHT_YEAR", str(datetime.date.today().year))
TEMPLATE_FILE = os.getenv("COPYRIGHT_TEMPLATE_FILE", "").strip()
ENCODING_RE = re.compile(r"^#.*coding[:=]\s*([-\w.]+)")
APACHE_MARKER = "Licensed under the Apache License, Version 2.0"
DEFAULT_HEADER = f"""# Copyright {YEAR} {OWNER}
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""


def load_header() -> str:
    if TEMPLATE_FILE:
        try:
            txt = pathlib.Path(TEMPLATE_FILE).read_text(encoding="utf-8").rstrip("\n")
            return txt + "\n"
        except Exception:
            pass
    return DEFAULT_HEADER


def process(path: str) -> bool:
    p = pathlib.Path(path)
    if p.suffix != ".py" or not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return False

    lines = text.splitlines()
    head = "\n".join(lines[:30])

    if APACHE_MARKER in head:
        return False

    pos = 0
    if lines and lines[0].startswith("#!"):
        pos = 1
    if pos < len(lines) and ENCODING_RE.match(lines[pos] if lines[pos:] else ""):
        pos += 1

    header = load_header().rstrip("\n")
    if text and not text.endswith("\n"):
        lines.append("")

    new_text = "\n".join(lines[:pos] + [header] + lines[pos:]) + "\n"

    if new_text != (text if text.endswith("\n") else text + "\n"):
        p.write_text(new_text, encoding="utf-8", newline="\n")
        print(f"inserted license header: {path}")
        return True
    return False


def main(paths):
    changed = False
    for path in paths:
        if process(path):
            changed = True
    if changed:
        print("Files were modified. Please 'git add' and commit again.")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
