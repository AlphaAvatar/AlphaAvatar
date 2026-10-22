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
    """Prepare the renderer frontend separately from the realtime Host process."""
    configured = os.getenv("AIRI_REPO_DIR")
    repo = (
        Path(configured).expanduser()
        if configured
        else Path(__file__).resolve().parents[4] / "third_party" / "airi"
    )
    repo = repo.resolve()
    if not (repo / "package.json").is_file() or not (repo / "pnpm-lock.yaml").is_file():
        raise SystemExit("AIRI checkout is missing; initialize the submodule or set AIRI_REPO_DIR")

    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise SystemExit("Install the pnpm version declared by the AIRI checkout first")

    env = os.environ.copy()
    env["npm_config_onnxruntime_node_install_cuda"] = "skip"
    subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=repo, env=env, check=True)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    print(f"AIRI dependencies installed in {repo}")
    print("Serve this trusted frontend separately, or configure an existing frontend_url:")
    print("pnpm --filter @proj-airi/stage-web dev --host 127.0.0.1 --port 5173 --strictPort")
    print("Run the command from the AIRI checkout, not the AlphaAvatar workspace root.")


if __name__ == "__main__":
    main()
