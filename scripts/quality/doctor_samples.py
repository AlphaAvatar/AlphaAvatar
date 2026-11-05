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
"""Doctor's fixed speech samples: made offline with FFmpeg's flite voice, read back by Doctor.

    uv run python scripts/quality/doctor_samples.py make [--ffmpeg PATH]
    python -I scripts/quality/doctor_samples.py check [--installed]

``make`` needs an FFmpeg built with libflite (Debian's and Ubuntu's are: ``ffmpeg -filters``
lists ``flite``). Each recording says its task's prompt, word for word, in flite's kal voice,
resampled to 16 kHz mono PCM16 with bit-exact output and no metadata, so one FFmpeg and flite
make the same files; nothing is downloaded. ``check`` reads each recording through Doctor's
own loader and prints what it found; ``--installed`` also requires that Doctor read them from
the installed wheel, not a source tree, as a clean environment with only the Host wheel does.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path


def _tasks():
    from alphaavatar.host.doctor import samples

    return samples, [task for task in (samples.VOICE_VISION, samples.VOICE) if task.speech]


def make(ffmpeg: str) -> None:
    samples, tasks = _tasks()
    target = Path(samples.__file__).parent / "samples"
    target.mkdir(exist_ok=True)
    for task in tasks:
        with tempfile.TemporaryDirectory() as scratch:
            text = Path(scratch) / "prompt.txt"
            text.write_text(task.prompt, encoding="utf-8")
            subprocess.run(
                [
                    ffmpeg,
                    *("-nostdin", "-hide_banner", "-loglevel", "error", "-y"),
                    *("-f", "lavfi", "-i", f"flite=textfile='{text}':voice=kal"),
                    *("-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le"),
                    *("-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact"),
                    str(target / f"{task.speech}.wav"),
                ],
                check=True,
            )
    check(installed=False)


def check(*, installed: bool) -> None:
    from importlib import resources

    samples, tasks = _tasks()
    location = Path(str(resources.files(samples.__package__).joinpath("samples")))
    if installed and Path(sysconfig.get_paths()["purelib"]) not in location.parents:
        sys.exit(f"Doctor reads its samples from {location}, not from the installed wheel")
    for task in tasks:
        speech = samples.speech(task.speech)
        print(
            f"{task.speech}: {speech.duration_sec:.2f} s, voiced to {speech.voiced_end_sec:.2f} s,"
            f" 16 kHz mono PCM16; says {task.prompt!r}"
        )
        if not 0.5 < speech.voiced_end_sec <= speech.duration_sec <= 10:
            sys.exit(f"{task.speech} is not a short spoken question")
    print(f"read through Doctor from {location}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    made = commands.add_parser("make", help="Generate the recordings into Doctor's package")
    made.add_argument("--ffmpeg", default="ffmpeg", help="An FFmpeg built with libflite")
    checked = commands.add_parser("check", help="Read the recordings back through Doctor")
    checked.add_argument("--installed", action="store_true", help="Require the installed wheel")
    args = parser.parse_args()
    if args.command == "make":
        make(args.ffmpeg)
    else:
        check(installed=args.installed)


if __name__ == "__main__":
    main()
