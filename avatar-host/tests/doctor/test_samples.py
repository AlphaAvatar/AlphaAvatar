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
"""Doctor's recordings in its package, as its own loader reads them.

CI also reads them from the built Host wheel alone (``scripts/doctor_samples.py check
--installed``): this checks the source tree the wheel is built from.
"""

from __future__ import annotations

from importlib import resources

from alphaavatar.host.doctor import samples


def test_each_spoken_task_ships_a_short_16_khz_mono_recording() -> None:
    folder = resources.files(samples.__package__).joinpath("samples")
    for task in (samples.VOICE_VISION, samples.VOICE):
        assert folder.joinpath(f"{task.speech}.wav").is_file(), task.speech
        speech = samples.speech(task.speech)  # 16 kHz mono PCM16, or it refuses.
        assert 0.5 < speech.voiced_end_sec <= speech.duration_sec <= 10, task.speech
