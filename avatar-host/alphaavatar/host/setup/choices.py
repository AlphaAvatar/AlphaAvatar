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
"""What `alphaavatar setup` offers, independent of how a platform delivers it.

A selection becomes the sections of a bundle, the requirements its capabilities need, and the
credentials its backends read. Any device, the Linux CLI or an App, chooses with these; only
installing the requirements is the platform's own. The requirements are what
``resolve_capabilities`` finds for the configuration once installed: the tests hold the two
to the same answer for every selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from alphaavatar.agents.runtime.plugin import plugin_requirement
from alphaavatar.agents.utils.vdb.config import vdb_requirement

VectorStore = Literal["lancedb", "qdrant"]


@dataclass(frozen=True, slots=True)
class Selection:
    voice: bool = True  # Speech in and out; speech segments come from on-device VAD.
    vision: bool = True  # Camera frames reach the loop's model.
    local_models: bool = True  # Turn taking, addressing, face and speaker models on-device.
    vector_store: VectorStore = "lancedb"  # Memory and persona vectors: workspace or Qdrant.


# The reference bundle, as `config init` writes it; and every inference remote except the
# voice activity detection speech input needs.
PRESETS = {"default": Selection(), "remote": Selection(local_models=False)}


@dataclass(frozen=True, slots=True)
class Credential:
    name: str
    purpose: str
    secret: bool = True
    required: bool = True


def requirements(selection: Selection) -> tuple[str, ...]:
    """The packages the selection's capabilities need, as PEP 508 requirements."""
    host = "alpha-avatar-host[livekit]"  # Sessions reach devices through LiveKit.
    needed = [
        host,
        plugin_requirement("loop"),
        plugin_requirement("context"),
        # The loop's model; the memory and persona tasks and embeddings, by the default backend.
        plugin_requirement("provider", "openai"),
        plugin_requirement("provider", "langchain"),
        plugin_requirement("status"),
        plugin_requirement("router"),
        plugin_requirement("memory"),
        plugin_requirement("persona"),
        vdb_requirement(selection.vector_store),
    ]
    if selection.voice:
        needed += [plugin_requirement("voice"), plugin_requirement("voice", "silero")]
    if selection.voice and selection.local_models:
        needed += [
            plugin_requirement("router", "semantic"),
            plugin_requirement("router", "turn-taking"),
            plugin_requirement("persona", "speaker"),
        ]
    if selection.local_models:
        needed.append(plugin_requirement("persona", "face"))
    return tuple(sorted(needed))


def credentials(selection: Selection) -> tuple[Credential, ...]:
    found = [
        Credential("OPENAI_API_KEY", "the model, speech, embeddings and memory/persona tasks"),
        Credential("LIVEKIT_URL", "the LiveKit server sessions use", secret=False),
        Credential("LIVEKIT_API_KEY", "LiveKit"),
        Credential("LIVEKIT_API_SECRET", "LiveKit"),
    ]
    if selection.vector_store == "qdrant":
        found += [
            Credential("QDRANT_URL", "your Qdrant server", secret=False),
            Credential("QDRANT_API_KEY", "your Qdrant server, if it asks for one", required=False),
        ]
    return tuple(found)


def capabilities(selection: Selection) -> tuple[str, ...]:
    """What the selection does, in words."""
    store = {"lancedb": "LanceDB in the Avatar workspace", "qdrant": "your Qdrant server"}
    found = ["sessions through LiveKit; model, speech and embeddings from OpenAI"]
    if selection.voice:
        found.append("voice: speech in and out, voice activity detected on this machine")
    found.append("vision: camera frames reach the model" if selection.vision else "vision off")
    if selection.local_models:
        local = "turn taking, addressing, speaker and face recognition"
        if not selection.voice:
            local = "face recognition"
        found.append(f"models on this machine: {local}")
    else:
        found.append("no other models on this machine")
    found.append(f"memory and persona: vectors in {store[selection.vector_store]}")
    return tuple(found)


def sections(selection: Selection) -> dict[str, str]:
    """The bodies of the template sections the selection changes, as profile texts."""
    import yaml

    from alphaavatar.host.configs.template import SECTIONS

    changed: dict[str, Any] = {}

    def edit(section: str, *path: str, value: Any) -> None:
        body = changed.setdefault(section, yaml.safe_load(SECTIONS[section]))
        for key in path[:-1]:
            body = body.setdefault(key, {})
        body[path[-1]] = value

    if not selection.voice:
        for part in ("vad", "stt", "tts"):
            changed.setdefault("voice", {})[part] = {"plugin": None}
    if not selection.vision:
        edit("vision", "enabled", value=False)
    if not (selection.voice and selection.local_models):
        edit("router", "init_config", "addressing", "semantic", "enabled", value=False)
        edit("router", "init_config", "turn_taking", "enabled", value=False)
        edit("persona", "init_config", "speaker", "enabled", value=False)
    if not selection.local_models:
        # Visual addressing reads the faces persona finds.
        edit("router", "init_config", "addressing", "visual", "enabled", value=False)
        edit("persona", "init_config", "face", "enabled", value=False)
    for section in ("memory", "persona"):
        if selection.vector_store == "qdrant":
            # Resolved from the environment, or the stored credentials, when the bundle loads.
            edit(section, "vdb_config", "url", value="${oc.env:QDRANT_URL}")
            edit(section, "vdb_config", "api_key", value="${oc.env:QDRANT_API_KEY,null}")
        else:
            # Explicitly none: a QDRANT_URL in the environment does not move the vectors.
            edit(section, "vdb_config", "url", value=None)
    return {
        section: "# Chosen with `alphaavatar setup`.\n"
        + yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
        for section, body in changed.items()
    }
