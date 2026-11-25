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
"""What a configuration that does not load or check says, the same for every command.

`config check`, Doctor, setup and `start` describe such a failure through here: each setting at
fault by its path, the variable or package it needs, why, and what fixes it, with the command
for the bundle it came from; a file gets no command setup cannot run. Only fixed text, setting
paths and validated names are shown, never a value as written, a validation message or an
exception's own text: any of them may hold a credential.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from .bundles import ConfigReferenceError, format_failure

if TYPE_CHECKING:
    from .bundles import ConfigSource

# Keys and paths as they are shown; any other spelling, which data might hold, is not.
_KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_:-]{0,63}")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:\[\]-]{0,255}")
_INDEX = re.compile(r"\[(\d+)\]")  # OmegaConf's a.b[0], as a path says it: a.b.0.
_PROBE = "__alphaavatar_credential__"  # Where a credential's call is evaluated, beside its header.
_SET = "set them in the environment or in the .env file ENV_FILE names (default .env)"


@dataclass(frozen=True, slots=True)
class Problem:
    """One setting at fault: its path, what is wrong, the package that would serve it or the
    variable it reads, and what fixes it, where known. ``line`` is all of it on one line; a
    narrow terminal shows the parts apart."""

    line: str
    location: str
    problem: str
    package: str | None = None
    action: str | None = None
    variable: str | None = None


class ConfigProblems(ConfigReferenceError):
    """Settings at fault, each a ``Problem``, under a heading that says what to do."""

    def __init__(self, heading: str, items: tuple[Problem, ...]) -> None:
        super().__init__(heading + ":" + "".join(f"\n      {item.line}" for item in items))
        self.items = items


class MissingVariables(ConfigProblems):
    """Variables the configuration reads that hold no value, by the setting that reads each;
    with the other fields validation refused alongside them, by path alone."""


def path(*parts: object) -> str:
    """A setting's path, from the keys leading to it; a key no setting could be named is ``?``."""
    return ".".join(str(part) if _KEY.fullmatch(str(part)) else "?" for part in parts) or "<root>"


def setup_installs(source: ConfigSource | None) -> str:
    """How a report says that setup installs a package: with the command for the bundle, the
    configuration setup takes; for a file, which it does not take, no command."""
    if source is None:
        return "`alphaavatar setup <bundle>` installs it"
    if source.bundle is not None:
        return f"`alphaavatar setup {source.bundle}` installs it"
    return "setup installs it for a bundle, not a file"


def _variable(location: str, name: str, *, credential: bool, default: bool = False) -> Problem:
    # Never "<setting>: ...": after a setting such as Authorization, the log boundary would take
    # what follows for its value and hide it, the variable's name with it.
    state = "is empty" if os.environ.get(name) is not None else "is not set"
    problem = f"reads {'the credential ' if credential else ''}{name}, which {state}"
    if not credential:  # An ordinary one is an interpolation's: a default would stand for it.
        problem += f", and ${{oc.env:{name}}} has no default"
    elif default and state == "is not set":  # Its default stands in, holding none.
        problem += ", and its default is empty"
    return Problem(f"{location} {problem}", location, problem, variable=name)


def _missing(items: list[Problem]) -> MissingVariables:
    others = any(item.variable is None for item in items)
    heading = "Variables the configuration reads hold no value"
    heading += ", and other fields are not valid" if others else ""
    return MissingVariables(f"{heading}; {_SET}", tuple(items))


def missing_variables(error: Exception) -> MissingVariables | None:
    """A validation error's variables that hold no value (``MissingVariable``), each at the
    setting that reads it, such as an MCP server's header; None when it has none. Other fields
    it refused are named alongside, by path alone, as validation located them."""
    from alphaavatar.agents.utils.env_utils import MissingVariable

    rows = error.errors(include_url=False, include_input=False)
    causes = [(row.get("ctx") or {}).get("error") for row in rows]
    if not any(isinstance(cause, MissingVariable) for cause in causes):
        return None
    items = []
    for row, cause in zip(rows, causes, strict=True):
        if isinstance(cause, MissingVariable):
            # Placeholders resolve as credentials: unset, empty or blank is none.
            items.append(_variable(path(*row["loc"], *cause.location), cause.name, credential=True))
        else:
            location = path(*row["loc"])
            items.append(Problem(f"{location} is not valid", location, "is not valid"))
    return _missing(items)


def _strings(value: Any, keys: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, (*keys, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, (*keys, str(index)))
    elif isinstance(value, str):
        yield keys, value


def _creates_mcp(data: Any) -> bool:
    """Whether ``data`` creates MCP, as ``MCPConfig`` decides it; settings it refuses create
    none here, and validation names them."""
    from pydantic import ValidationError

    from alphaavatar.agents.configs.plugins.tools.tools_config import MCPConfig

    tools = data.get("tools") if isinstance(data, dict) else None
    mcp = tools.get("mcp") if isinstance(tools, dict) else None
    switches = (
        {k: mcp[k] for k in ("enabled", "plugin") if k in mcp} if isinstance(mcp, dict) else {}
    )
    try:
        return MCPConfig.model_validate(switches).creates
    except ValidationError:
        return False


def _sends(config: Any, keys: tuple[str, ...], call: str) -> bool | None:
    """Whether ``call``, evaluated by OmegaConf beside the header at ``keys``, nested defaults
    and all, holds a value: not empty, blank or null; None when it does not evaluate."""
    from omegaconf.errors import OmegaConfBaseException

    node = config
    for key in keys[:-1]:
        node = node[key]
    node[_PROBE] = call
    try:
        value = node[_PROBE]
    except OmegaConfBaseException:
        return None
    finally:
        del node[_PROBE]
    return value is not None and bool(str(value).strip())


def _unset(written: Any, *, ordinary: bool, creates: bool) -> list[Problem]:
    """Each ``${oc.env:NAME}`` that ``written`` reads to no value, at its setting, as OmegaConf
    parses and evaluates it. In an MCP server's ``Authorization``, where MCP is created
    (``creates``), a credential: each outermost call evaluated as it is sent, once filled, and
    refused empty, blank or null; one that does not evaluate, only if unset with no default.
    With ``ordinary``, any other call without a default whose variable is unset: empty is a
    value, and a call whose default reads an unset one fails as that one does."""
    from omegaconf import OmegaConf

    from .credentials import authorizations, env_calls

    sent = {keys for keys, _ in authorizations(written)} if creates else set()
    config = OmegaConf.create(written) if sent else None
    items: dict[tuple[str, str], Problem] = {}
    for keys, value in _strings(written):
        at = path(*keys)
        for name, call, default, top in env_calls(value):
            if keys in sent and top:
                held = _sends(config, keys, call)
                if held is False or (held is None and not default and name not in os.environ):
                    found = _variable(at, name, credential=True, default=default)
                    items.setdefault((at, name), found)
            elif ordinary and not default and name not in os.environ:
                items.setdefault((at, name), _variable(at, name, credential=keys in sent))
    return list(items.values())


def unset_credentials(written: Any, data: Any) -> MissingVariables | None:
    """The credentials a configuration, as ``written``, interpolates in an MCP server's
    ``Authorization`` that hold no value, where it creates MCP once interpolated (``data``):
    empty or blank interpolates, as ``Bearer ``, but sends none. Each at its setting, as a
    ``<NAME>`` placeholder is; None when every one holds one."""
    items = _unset(written, ordinary=False, creates=_creates_mcp(data))
    return _missing(items) if items else None


def unresolved(written: Any, error: Exception) -> Exception:
    """Why a composed configuration, as ``written``, did not interpolate: each ``${oc.env:NAME}``
    without a default whose variable holds no value (``_unset``), at its setting, and the setting
    whose interpolation failed where it is another; else the file or an override is not valid."""
    items = _unset(written, ordinary=True, creates=_creates_mcp(written))
    key = getattr(error, "full_key", None)
    location = _INDEX.sub(r".\1", key) if isinstance(key, str) else ""
    if _PATH.fullmatch(location) and all(item.location != location for item in items):
        problem = "holds an interpolation that cannot be resolved"
        items.append(Problem(f"{location} {problem}", location, problem))
    if any(item.variable is not None for item in items):
        return _missing(items)
    if items:
        return ConfigProblems("An interpolation cannot be resolved; fix what it reads", (*items,))
    return ValueError("Invalid YAML, configuration override, or interpolation")


def next_step(error: BaseException, source: ConfigSource | None = None) -> str:
    """What to do about a configuration that did not load or check, as every command says it."""
    from .capabilities import MissingCapabilities, offered

    if isinstance(error, MissingVariables):
        names = list(dict.fromkeys(item.variable for item in error.items if item.variable))
        step = f"Set {', '.join(names)} in the environment or in the .env file ENV_FILE names"
        others = any(item.variable is None for item in error.items)
        return f"{step} (default .env)" + (", and fix the other fields" if others else "")
    if isinstance(error, MissingCapabilities):
        if offered() is None:
            install = "Install the named packages into this Python environment"
        elif source is not None and source.bundle is not None:
            install = f"Run `alphaavatar setup {source.bundle}` for what it installs"
        else:
            install = "Setup installs for a bundle, not a file: use a bundle for what it installs"
        return install + ", or change the settings that select the rest"
    if isinstance(error, ModuleNotFoundError) and error.name:
        return f"Install the package that provides the Python module {error.name!r}"
    return "Fix the reported field or reference, then check again"


def describe_error(error: BaseException, source: ConfigSource | None = None) -> dict[str, Any]:
    """Structured failure metadata: the type, the settings at fault, the bounded diagnostic and
    the next step; each problem with its parts, for a tool to show as it likes."""
    from alphaavatar.core.log import error_fields
    from alphaavatar.core.log.records import Redactor

    items = error.items if isinstance(error, ConfigProblems) else ()
    redact = Redactor()  # As the diagnostic text: environment secrets never pass.
    problems = [
        {k: redact(v, limit=None) if isinstance(v, str) else v for k, v in asdict(item).items()}
        for item in items
    ]
    fields = [problem["location"] for problem in problems] or list(error_fields(error))
    return {
        "type": type(error).__name__,
        "fields": fields,
        "diagnostic": format_failure(error),
        "problems": problems,
        "action": redact(next_step(error, source), limit=None),  # It may name the bundle.
    }
