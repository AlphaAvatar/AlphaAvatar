# Copyright 2026 AlphaAvatar project
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
"""Load the native code a setup environment's own packages hold, as this machine runs it.

    <environment>/bin/python -I -m alphaavatar.host.setup.probe

For each shared library a package installed into the environment (not the base) holds, the
outermost regular package around it is imported; a top-level extension module is imported
itself. A library the platform cannot load fails here, before the environment is switched to,
not when a session first uses it. Exit status 1 lists each failure.
"""

from __future__ import annotations

import importlib
import sys
import sysconfig
from importlib import metadata
from pathlib import Path


def modules(site: Path) -> list[str]:
    found = set()
    for distribution in metadata.distributions(path=[str(site)]):
        for file in distribution.files or ():
            parts = Path(file).parts
            if not (file.name.endswith(".so") or ".so." in file.name):
                continue
            if len(parts) == 1:
                found.add(parts[0].split(".")[0])  # A top-level extension module.
                continue
            for depth in range(1, len(parts)):
                if (site.joinpath(*parts[:depth]) / "__init__.py").is_file():
                    found.add(".".join(parts[:depth]))
                    break
    return sorted(found)


def main() -> int:
    site = Path(sysconfig.get_paths()["purelib"])
    failures = []
    for name in modules(site):
        try:
            importlib.import_module(name)
        except Exception as error:
            failures.append(f"{name}: {type(error).__name__}: {error}")
    for line in failures:
        print(line, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
