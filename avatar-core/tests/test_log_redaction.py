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
"""Log redaction of the values of environment variables: those named as secrets, and those an
upper layer names, here and in processes started from here."""

from __future__ import annotations

import os
import subprocess
import sys
from unittest import mock

from alphaavatar.core.log import format_error
from alphaavatar.core.log.events import safe_fields
from alphaavatar.core.log.records import HIDDEN_ENV, Redactor, hide_variables

# Fictional values; the first's name says it is a secret, the others' do not.
VALUES = {
    "OPENAI_API_KEY": "sk-openai-fictional-0042",
    "ALPHAAVATAR_SERVER_KEY_0123456789AB": "sk-own-fictional-0042",
    "GITHUB_PAT": "pat-fictional-0042",
    "MODEL_AUTH": "auth-fictional-0042",
}
NAMED = ("ALPHAAVATAR_SERVER_KEY_0123456789AB", "GITHUB_PAT", "MODEL_AUTH")


def _texts(redact: Redactor) -> list[str]:
    """A plain line, an exception's text and a structured field, each holding every value."""
    held = " ".join(VALUES.values())
    try:
        raise RuntimeError(f"upstream refused {held}")
    except RuntimeError as error:
        # Its message as a log line quotes it; the error's own lines name only its type and place.
        failure = f"tool call failed: {error}\n{format_error(error, details=True)}"
    fields = safe_fields({"reason": f"keys {held} refused", "model": "gpt-test"}, redact)
    line = redact(f"request to https://gpu.invalid:8000/v1 with {held} failed")
    return [line, redact(failure), *(f"{key}={value}" for key, value in fields.items())]


def test_the_values_of_variables_an_upper_layer_names_are_hidden_with_the_rest() -> None:
    with mock.patch.dict(os.environ, VALUES):
        os.environ.pop(HIDDEN_ENV, None)
        unnamed = " ".join(_texts(Redactor()))
        assert [name for name, value in VALUES.items() if value in unnamed] == list(NAMED)
        hide_variables([*NAMED, "not a variable"])
        assert os.environ[HIDDEN_ENV] == ",".join(sorted(NAMED))
        hidden = _texts(Redactor())
        assert not [value for value in VALUES.values() if value in " ".join(hidden)]
        # What the diagnostic says stays: the server, the failure, the other fields.
        assert hidden[0] == (
            "request to https://gpu.invalid:8000/v1 with "
            + " ".join(["[redacted]"] * len(VALUES))
            + " failed"
        )
        assert "tool call failed: upstream refused [redacted]" in hidden[1]
        assert "error: RuntimeError" in hidden[1]
        assert "model=gpt-test" in hidden

        # A process started from here hides them too; naming them again changes nothing.
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from alphaavatar.core.log.records import Redactor; "
                "print(Redactor()(sys.argv[1]))",
                " ".join(VALUES.values()),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert child.stdout.split() == ["[redacted]"] * len(VALUES)
        before = dict(os.environ)
        hide_variables(NAMED[:1])
        assert dict(os.environ) == before
