# Copyright 2025 AlphaAvatar project
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
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """
    Install AIRI frontend dependencies:
    - Check if the AIRI repository directory exists
    - Check if pnpm/npm is available
    - Execute the dependency installation command in the AIRI repository
    """
    from .runner import AIRI_REPO_DIR

    repo_dir: Path = AIRI_REPO_DIR

    if not repo_dir.exists():
        print(f"[AIRI] repo directory not found: {repo_dir}", file=sys.stderr)
        sys.exit(1)

    package_json = repo_dir / "package.json"
    if not package_json.exists():
        print(f"[AIRI] package.json not found in {repo_dir}", file=sys.stderr)
        sys.exit(1)

    # 优先用 pnpm，没有的话退回 npm
    pnpm_path = shutil.which("pnpm")
    npm_path = shutil.which("npm")

    if pnpm_path is None and npm_path is None:
        print("[AIRI] Neither pnpm nor npm found in PATH.", file=sys.stderr)
        sys.exit(1)

    if pnpm_path is not None:
        cmd = [pnpm_path, "install"]
        tool_name = "pnpm"
    else:
        cmd = [npm_path, "install"]
        tool_name = "npm"

    print(f"[AIRI] Install dependencies using {tool_name}...")
    print(f"[AIRI] Repository directory: {repo_dir}")

    env = os.environ.copy()
    env["npm_config_onnxruntime_node_install_cuda"] = "skip"

    try:
        subprocess.check_call(cmd, cwd=str(repo_dir), env=env)
    except subprocess.CalledProcessError as e:
        print(f"[AIRI] Dependency installation failed (exit code {e.returncode})", file=sys.stderr)
        sys.exit(e.returncode)

    print(
        "[AIRI] Dependencies installed. You can now run the service and have AiriProcess start the dev server."
    )


if __name__ == "__main__":
    main()
