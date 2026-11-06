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
"""What setup offers: each selection asks for exactly what its bundle needs once installed."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import itertools
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import pytest
import yaml
from omegaconf import OmegaConf
from pydantic import BaseModel

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.agents.runtime.inference import plan_inference_runners
from alphaavatar.host.configs import ConfigSource, resolve_capabilities, validate_application
from alphaavatar.host.configs.template import render_bundle
from alphaavatar.host.setup.choices import (
    OPENAI_KEY,
    Models,
    Selection,
    Speech,
    bundle_requirements,
    credentials,
    requirements,
    sections,
    server_key,
    server_problem,
)
from alphaavatar.host.setup.plan import plan_install
from alphaavatar.host.workspace import ApplicationPaths

ROOT = Path(__file__).resolve().parents[3]
SELECTIONS = [
    Selection(*values)
    for values in itertools.product(
        (True, False), (True, False), (True, False), ("lancedb", "qdrant")
    )
]
# Models and the libraries that run them, besides Silero's ONNX Runtime; and CUDA.
LOCAL = {
    "insightface",
    "llama-cpp-python",
    "onnx",
    "safetensors",
    "scikit-image",
    "scipy",
    "tokenizers",
    "torch",
    "torchaudio",
    "transformers",
}


def bundle_of(selection: Selection) -> dict:
    texts = render_bundle("chosen", "chosen", sections=sections(selection))
    bundle = yaml.safe_load(texts["bundles/chosen.yaml"])
    for section, reference in bundle.pop("profiles").items():
        bundle[section] = yaml.safe_load(texts[f"profiles/{reference}.yaml"])
    return bundle


def validated(bundle: dict, home: Path):
    resolved = OmegaConf.to_container(OmegaConf.create(bundle), resolve=True)
    return validate_application(resolved, paths=ApplicationPaths.from_root(home))


def compose(selection: Selection, home: Path):
    return validated(bundle_of(selection), home)


def label(selection: Selection) -> str:
    parts = (selection.voice, selection.vision, selection.local_models, selection.vector_store)
    return "-".join(map(str, parts))


@pytest.mark.parametrize("selection", SELECTIONS, ids=label)
def test_each_selection_asks_for_exactly_what_its_bundle_resolves_to(
    selection: Selection, tmp_path: Path
) -> None:
    # An endpoint in the environment moves no vector store a LanceDB selection chose.
    with mock.patch.dict(os.environ, {"QDRANT_URL": "http://qdrant.invalid:6333"}):
        config = compose(selection, tmp_path / "home")
        found = sorted({need.requirement for need in resolve_capabilities(config).needs})
    assert found == list(requirements(selection))
    names = [credential.name for credential in credentials(selection) if credential.required]
    assert ("QDRANT_URL" in names) == (selection.vector_store == "qdrant")


def test_own_servers_take_what_the_installed_providers_send_there(tmp_path: Path) -> None:
    from alphaavatar.plugins.provider.openai.llms.config import OpenAIClientConfig

    models = Models("http://gpu.invalid:8000/v1", "qwen3-32b", "qwen3-8b", "bge-m3")
    speech = Speech("https://speech.invalid:8001/v1", "whisper-large-v3", "kokoro", "af_heart")
    own = Selection(models=models, speech=speech)
    config = compose(own, tmp_path / "home")
    models_key, speech_key = server_key(models.url), server_key(speech.url)
    avatar, server = config.avatar, {"base_url": models.url, "api_key_env": models_key}
    loop = avatar.loop.init_config["model"]
    assert (loop["backend"], loop["model"], loop["extra"]) == ("openai", "qwen3-32b", server)
    # The loop's Responses client is pointed at the server; tasks and embeddings go there too.
    assert OpenAIClientConfig.model_validate(loop["extra"]).base_url == models.url
    tasks = avatar.persona.init_config["profiler"]["provider"]["gateway"]["tasks"]
    assert tasks["persona.profile_delta"] == {
        "provider": "openai",
        "model": "qwen3-8b",
        "temperature": 0.1,
        "extra": server,
    }
    for section in (avatar.memory, avatar.persona):
        assert section.vdb_config["embedding"] == {
            "provider": "openai",
            "model": "bge-m3",
            "extra": server,
        }
    voice = avatar.voice
    assert (voice.stt.base_url, voice.stt.model) == (speech.url, "whisper-large-v3")
    assert (voice.tts.base_url, voice.tts.model, voice.tts.speaker) == (
        speech.url,
        "kokoro",
        "af_heart",
    )
    assert voice.stt.api_key_env == voice.tts.api_key_env == speech_key != models_key
    # The same packages serve them; each server's key is whatever that server expects.
    found = sorted({need.requirement for need in resolve_capabilities(config).needs})
    assert found == list(requirements(own)) == list(requirements(Selection()))
    asked = {credential.name: credential.purpose for credential in credentials(own)}
    assert OPENAI_KEY not in asked
    assert asked[models_key] == f"your server {models.url}; any text if it needs none"
    assert asked[speech_key] == f"your server {speech.url}; any text if it needs none"


class Server:
    """A server of one's own: it refuses every request, keeping the key each one carried."""

    def __init__(self) -> None:
        keys = self.keys = []

        class Refuse(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                keys.append(self.headers.get("Authorization"))
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = b'{"error": {"message": "refused", "type": "invalid_request_error"}}'
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

            def log_message(self, *args: object) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Refuse)
        self.url = f"http://127.0.0.1:{self.http.server_port}/v1"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.http.shutdown()
        self.http.server_close()


async def _request_each(avatar, models: bool, speech: bool) -> None:
    """One request from each backend the session would point at a server of one's own."""
    from alphaavatar.agents.avatar.provider.enums import ModelRole
    from alphaavatar.agents.avatar.provider.factory import create_llm_model
    from alphaavatar.agents.avatar.provider.schemas import (
        ModelInput,
        ModelInputMessage,
        ModelRequest,
        ModelTextPart,
    )
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig
    from alphaavatar.core.media import AudioFrame

    class Answer(BaseModel):
        text: str

    said = ModelInput((ModelInputMessage("m", ModelRole.USER, (ModelTextPart("Hello"),)),))
    attempts = []
    if models:
        loop = create_llm_model(ProviderTaskConfig.model_validate(avatar.loop.init_config["model"]))
        tasks = avatar.persona.init_config["profiler"]["provider"]["gateway"]["tasks"]
        task = create_llm_model(ProviderTaskConfig.model_validate(tasks["persona.profile_delta"]))

        async def responses() -> None:
            async with loop.stream(ModelRequest(said)) as events:
                async for _ in events:
                    pass

        attempts += [responses(), task.ainvoke_structured(said, output_schema=Answer)]
    if speech:
        stt, tts = avatar.voice.stt.get_plugin(), avatar.voice.tts.get_plugin()

        async def transcription() -> None:
            async with stt.stream(source_id="probe") as stream:
                stream.push_frame(AudioFrame(16000, 1, 8000, bytes(16000)), segment_id="s")
                stream.commit_segment("s")
                stream.end_input()
                async for _ in stream:
                    pass

        async def synthesis() -> None:
            async for _ in tts.synthesize("Hello."):
                pass

        attempts += [transcription(), synthesis()]
    for attempt in attempts:
        try:
            await asyncio.wait_for(attempt, 30)
        except Exception:
            pass  # Refused: what matters is the key the request carried.
    if speech:
        await tts.aclose()


@pytest.mark.parametrize("own", ["models", "speech", "both", "one server"])
def test_each_server_of_ones_own_receives_its_own_key_and_never_openais(
    own: str, tmp_path: Path, owned_endpoints: set[object]
) -> None:
    model_server, speech_server = Server(), Server()
    if own == "one server":
        speech_server.close()
        speech_server = model_server
    for server in (model_server, speech_server):
        owned_endpoints.add(server.http.server_address[:2])
    try:
        check_keys(own, model_server, speech_server, tmp_path)
    finally:
        for server in {id(model_server): model_server, id(speech_server): speech_server}.values():
            server.close()


def check_keys(own: str, model_server: Server, speech_server: Server, tmp_path: Path) -> None:
    from alphaavatar.agents.avatar.provider.factory import create_embedding_model
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig

    models = Models(model_server.url, "chat", "tasks", "embed")
    speech = Speech(speech_server.url, "transcribe", "speak", "voice")
    selection = Selection(
        models=models if own != "speech" else None, speech=speech if own != "models" else None
    )
    MODELS_KEY, SPEECH_KEY = server_key(model_server.url), server_key(speech_server.url)
    keys = {OPENAI_KEY: "sk-openai-fictional", MODELS_KEY: "models-fictional"}
    if SPEECH_KEY != MODELS_KEY:
        keys[SPEECH_KEY] = "speech-fictional"
    names = {credential.name for credential in credentials(selection)}
    proxies = dict.fromkeys(("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy"), "")
    with mock.patch.dict(os.environ, keys | proxies):
        avatar = compose(selection, tmp_path / "home").avatar
        asyncio.run(_request_each(avatar, own != "speech", own != "models"))
        embedding = avatar.memory.vdb_config["embedding"]
        embedder = create_embedding_model(
            ProviderTaskConfig.model_validate(embedding | {"kind": "embedding"})
        )
    model_key = f"Bearer {keys[MODELS_KEY]}"
    if own == "one server":
        assert len(model_server.keys) == 4 and set(model_server.keys) == {model_key}
        assert SPEECH_KEY == MODELS_KEY and names >= {MODELS_KEY} and OPENAI_KEY not in names
    if own in ("models", "both"):
        # The loop's Responses request and a task's, each with the model server's key.
        assert len(model_server.keys) == 2 and set(model_server.keys) == {model_key}
        assert embedder._model.openai_api_key.get_secret_value() == keys[MODELS_KEY]
    if own in ("speech", "both"):
        # A transcription and a synthesis, each with the speech server's key.
        assert len(speech_server.keys) == 2
        assert set(speech_server.keys) == {f"Bearer {keys[SPEECH_KEY]}"}
    # What goes to OpenAI reads OpenAI's key, and it is asked for only then.
    assert (OPENAI_KEY in names) == (own in ("models", "speech"))
    if own == "speech":
        assert "api_key_env" not in avatar.loop.init_config["model"].get("extra", {})
        assert embedder._model.openai_api_key.get_secret_value() == keys[OPENAI_KEY]
    if own == "models":
        assert avatar.voice.stt.api_key_env is avatar.voice.tts.api_key_env is None


def test_a_server_of_ones_own_has_one_key_variable_for_its_endpoint_alone() -> None:
    same = (
        "http://gpu.invalid:8000/v1",
        "http://GPU.invalid:8000/v1/",
        "http://gpu.invalid:8000/v1/",
    )
    assert len({server_key(url) for url in same}) == 1
    # Another port, path, scheme or host is another server: never the same variable.
    others = (
        "http://gpu.invalid:8000/v1",
        "http://gpu.invalid:8001/v1",
        "http://gpu.invalid:8000/v2",
        "https://gpu.invalid:8000/v1",
        "http://cpu.invalid:8000/v1",
    )
    assert len({server_key(url) for url in others}) == len(others)
    assert server_key("https://gpu.invalid/v1") == server_key("https://gpu.invalid:443/v1")


# Each place setup names a server's key variable beside the URL it is sent to, and the
# location validation gives when they disagree. Persona checks its own settings as it plans
# its runners, from its init_config.
TASK = ("provider", "gateway", "tasks")
KEYED = {
    "loop": (("loop", "init_config", "model", "extra"), "loop.init_config.model"),
    "memory task": (
        ("memory", "init_config", "conversation", *TASK, "memory.conversation_delta", "extra"),
        "memory.init_config.conversation.provider.gateway.tasks.memory.conversation_delta",
    ),
    "persona task": (
        ("persona", "init_config", "profiler", *TASK, "persona.profile_delta", "extra"),
        "profiler.provider.gateway.tasks.persona.profile_delta",
    ),
    "memory embeddings": (("memory", "vdb_config", "embedding", "extra"), "memory"),
    "persona embeddings": (("persona", "vdb_config", "embedding", "extra"), "persona"),
    "transcription": (("voice", "stt"), "voice.stt"),
    "synthesis": (("voice", "tts"), "voice.tts"),
}


@pytest.mark.parametrize("where", KEYED)
def test_a_key_variable_named_after_a_server_is_sent_to_that_server_alone(
    where: str, tmp_path: Path
) -> None:
    """A bundle made for one server, its base_url alone moved: validation, before any client
    exists, refuses the variable for the URL in effect. A variable of one's own may go anywhere."""
    from pydantic import ValidationError

    from alphaavatar.core.log.diagnostics import error_fields

    models = Models("http://gpu.invalid:8000/v1", "chat", "tasks", "embed")
    speech = Speech("https://speech.invalid:8001/v1", "transcribe", "speak", "voice")
    bundle = bundle_of(Selection(models=models, speech=speech))
    (*parents, place), location = KEYED[where]
    url = speech.url if parents[0] == "voice" else models.url

    def moved(base_url: str | None, **changes: str):
        document = copy.deepcopy(bundle)
        parent = document
        for key in parents:
            parent = parent[key]
        # A mapping of its own: setup's YAML aliases the one it wrote to several places.
        parent[place] = {**parent[place], "base_url": base_url, **changes}
        return validated(document, tmp_path / "home")

    moved(url + "/")  # The same endpoint, however spelled.
    moved(url.replace(".invalid", ".INVALID"))
    # Another port, another path, or none: the backend's own default URL.
    for other in (url.replace(":800", ":900"), url.replace("/v1", "/v2"), None):
        with pytest.raises((ValidationError, RuntimeError)) as refused:
            moved(other)
        error = refused.value
        error = error if isinstance(error, ValidationError) else error.__cause__
        assert "holds the key of the server it is named after" in str(error)
        assert error_fields(error) == (location,)
        if other is not None:
            moved(other, api_key_env="MY_SERVER_KEY")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/v1",
        "http://localhost:8000/v1",
        "http://[::1]:8000/v1",
        "https://gpu.invalid/v1",
        "http://gpu.invalid:8000/v1",
        "https://user:pw@gpu.invalid/v1",
        "https://gpu.invalid/v1?key=1",
        "https://gpu.invalid/v1#x",
        "ftp://gpu.invalid/v1",
        "gpu.invalid:8000/v1",
        "https://@gpu.invalid/v1",
        "https://:@gpu.invalid/v1",
        "https://gpu.invalid:99999/v1",
        "https://gpu.invalid:0/v1",
        "https://gpu.invalid:port/v1",
        "http://localhost:65535/v1",
    ],
)
def test_a_server_url_is_taken_where_the_backends_it_serves_take_it(url: str) -> None:
    """The wizard's rule is the backends' own: refused before setup enables anything."""
    from alphaavatar.plugins.provider.openai.llms.config import OpenAIClientConfig
    from alphaavatar.plugins.voice.tts.openai import OpenAITTS

    def accepts(build) -> bool:
        try:
            build()
        except ValueError:
            return False
        return True

    models = accepts(lambda: OpenAIClientConfig(base_url=url))
    speech = accepts(lambda: OpenAITTS(model="m", speaker="s", api_key="k", base_url=url))
    assert (server_problem(url, speech=False) is None) == models
    assert (server_problem(url, speech=True) is None) == speech
    assert accepts(lambda: Models(url, "c", "t", "e")) == models
    assert accepts(lambda: Speech(url, "t", "s", "v")) == speech


def test_the_reference_keeps_vision_and_plans_its_runners_with_or_without_local_models(
    tmp_path: Path,
) -> None:
    reference = compose(Selection(), tmp_path / "reference")
    remote = compose(Selection(local_models=False), tmp_path / "remote")
    assert reference.avatar.vision.enabled and remote.avatar.vision.enabled
    assert len(plan_inference_runners(reference.avatar)) == 8
    # With no model on this machine, the voice activity detection speech segments come from.
    assert sorted(plan_inference_runners(remote.avatar)) == [
        "alphaavatar.memory.vdb.lancedb",
        "alphaavatar.persona.vdb.lancedb",
        "alphaavatar.voice.vad.silero",
    ]


def test_remote_inference_plans_no_local_model_nor_its_accelerators() -> None:
    """From uv.lock through the Linux build's own catalog logic to setup's plan."""
    spec = importlib.util.spec_from_file_location("catalog", ROOT / "packaging/linux/catalog.py")
    assert spec is not None and spec.loader is not None
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    keys = catalog.requirement_keys(catalog.Lock(ROOT), ROOT)
    names = sorted({name for closure in keys.values() for name in closure})
    artifact = {"version": "0", "sha256": "0" * 64, "size": 1, "url": None}
    document = {
        "format": 1,
        "version": "0",
        "platform": catalog.PLATFORM,
        "base": sorted({*catalog.base_names(ROOT), *catalog.BASE_MEMBERS}),
        "requirements": {key: sorted(closure) for key, closure in keys.items()},
        "distributions": {name: artifact | {"file": f"{name}.whl"} for name in names},
    }

    def planned(selection: Selection) -> set[str]:
        plan = plan_install(document, requirements(selection), base="base")
        return {item.name for item in plan.artifacts}

    default, remote = planned(Selection()), planned(Selection(local_models=False))
    silent = planned(Selection(voice=False, local_models=False))
    assert LOCAL <= default and "onnxruntime" in default
    assert not LOCAL & remote and "onnxruntime" in remote  # Silero VAD only.
    assert not LOCAL & silent and "onnxruntime" not in silent
    for plan in (default, remote, silent):
        # No CUDA library, and only the headless OpenCV.
        assert not {n for n in plan if n.startswith("nvidia-") or n in ("triton", "opencv-python")}
        assert not plan & set(document["base"])


def installed_plugins() -> dict[str, dict[str, str]]:
    """What installs each implementation, as the Linux build's catalog records it."""
    from importlib import metadata

    from alphaavatar.agents.runtime.plugin import AvatarModule
    from alphaavatar.host.configs.capabilities import with_extra

    found: dict[str, dict[str, str]] = {}
    for module in AvatarModule:
        for entry in metadata.entry_points(group=module.group):
            found.setdefault(module.value, {})[entry.name] = with_extra(entry.dist.name, entry.name)
    return found


# A bundle as config init writes it, then edited a switch or a backend at a time.
EDITS = {
    "as written": (),
    "no face": ("persona.init_config.face.enabled=false",),
    "no speaker": ("persona.init_config.speaker.enabled=false",),
    "no turn taking": ("router.init_config.turn_taking.enabled=false",),
    "no semantic addressing": ("router.init_config.addressing.semantic.enabled=false",),
    "no speech in": ("voice.stt.plugin=null",),
    "no voice": ("voice.vad.plugin=null", "voice.stt.plugin=null", "voice.tts.plugin=null"),
    "qdrant": ("memory.vdb_config.url=http://q.invalid:6333",),
    "the loop by langchain": ("loop.init_config.model.backend=langchain",),
    "environment memory": (
        "memory.init_config.environment.enabled=true",
        "memory.init_config.environment.provider.task=memory.env_delta",
    ),
}


@pytest.mark.parametrize(
    "selection",
    [*SELECTIONS, Selection(models=Models("http://m.invalid:8000/v1", "c", "t", "e"))],
    ids=label,
)
def test_an_existing_bundle_plans_what_its_selection_does(
    selection: Selection, tmp_path: Path
) -> None:
    with mock.patch.dict(os.environ, {"QDRANT_URL": "http://qdrant.invalid:6333"}):
        config = compose(selection, tmp_path / "home")
    needs, unserved = bundle_requirements(config.host, config.avatar, installed_plugins())
    assert unserved == () and sorted(needs) == list(requirements(selection))


@pytest.mark.parametrize("edit", EDITS)
def test_an_edited_bundle_plans_what_start_resolves_once_installed(
    edit: str, tmp_path: Path
) -> None:
    """Planned from the settings alone, as a bare base must; resolved as start resolves them."""
    from alphaavatar.host.configs import load_application
    from alphaavatar.host.configs.template import create_bundle

    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "edited", avatar_id="edited")
    source = ConfigSource(paths.configs.bundles_dir / "edited.yaml", "edited", home=paths.root)
    config = load_application(source, EDITS[edit])
    needs, unserved = bundle_requirements(config.host, config.avatar, installed_plugins())
    resolved = {need.requirement for need in resolve_capabilities(config).needs}
    assert unserved == () and set(needs) == resolved


def _drop(body: dict, *path: str) -> None:
    for key in path[:-1]:
        body = body[key]
    del body[path[-1]]


# Edits made in the profiles themselves, by profile: what overrides cannot write.
PROFILE_EDITS = {
    # A switch left out takes its default, on: its runner still starts.
    "switches left out": {
        "router": lambda body: (
            _drop(body, "init_config", "turn_taking", "enabled"),
            _drop(body, "init_config", "addressing", "semantic", "enabled"),
        ),
        "persona": lambda body: (
            _drop(body, "init_config", "speaker", "enabled"),
            _drop(body, "init_config", "face", "enabled"),
        ),
    },
    # A part switched off creates nothing: a backend nothing installs is not needed for it.
    "off, on a backend nothing installs": {
        "persona": lambda body: body["init_config"]["profiler"].update(
            enabled=False,
            provider={
                "gateway": {
                    "tasks": {
                        "persona.profile_delta": {
                            "backend": "nowhere",
                            "provider": "openai",
                            "model": "m",
                        }
                    }
                }
            },
        )
    },
}


@pytest.mark.parametrize("edit", PROFILE_EDITS)
def test_a_bundle_edited_in_its_profiles_plans_what_start_resolves(
    edit: str, tmp_path: Path
) -> None:
    from alphaavatar.host.configs import load_application
    from alphaavatar.host.configs.template import create_bundle

    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "edited", avatar_id="edited")
    for profile, change in PROFILE_EDITS[edit].items():
        path = paths.configs.profiles_dir / "edited" / "plugins" / "perception" / f"{profile}.yaml"
        body = yaml.safe_load(path.read_text())
        change(body)
        path.write_text(yaml.safe_dump(body))
    source = ConfigSource(paths.configs.bundles_dir / "edited.yaml", "edited", home=paths.root)
    config = load_application(source)
    needs, unserved = bundle_requirements(config.host, config.avatar, installed_plugins())
    resolved = {need.requirement for need in resolve_capabilities(config).needs}
    assert unserved == () and set(needs) == resolved


def test_what_setup_does_not_install_is_named_by_the_setting_that_selects_it(
    tmp_path: Path,
) -> None:
    from alphaavatar.host.configs import load_application
    from alphaavatar.host.configs.template import create_bundle

    plugins = installed_plugins()
    del plugins["tools.rag"]  # A plugin the catalog has nothing for.
    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "rag", avatar_id="rag")
    source = ConfigSource(paths.configs.bundles_dir / "rag.yaml", "rag", home=paths.root)
    config = load_application(source, ["tools.rag.plugin=default"])
    _, unserved = bundle_requirements(config.host, config.avatar, plugins)
    assert unserved == ("tools.rag.plugin: tools.rag 'default'",)


BARE = """
import importlib.abc, json, sys
from pathlib import Path


class Bare(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[:2] == ["alphaavatar", "plugins"]:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)


sys.meta_path.insert(0, Bare())
from alphaavatar.host.configs import ConfigSource, load_selections
from alphaavatar.host.setup.choices import bundle_requirements

home, plugins, bundle = Path(sys.argv[1]), json.loads(sys.argv[2]), Path(sys.argv[3])
needs, unserved = bundle_requirements(
    *load_selections(ConfigSource(bundle, "reference", home=home)), plugins
)
loaded = sorted(name for name in sys.modules if name.startswith("alphaavatar.plugins"))
print(json.dumps({"needs": sorted(needs), "unserved": unserved, "plugins": loaded}))
"""


def test_a_bare_base_plans_a_bundle_without_importing_any_plugin(tmp_path: Path) -> None:
    """Before setup installs anything, no plugin is there to import: the plan comes from the
    bundle's settings and the catalog alone."""
    import json
    import subprocess
    import sys

    from alphaavatar.host.configs.template import create_bundle

    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "reference", avatar_id="reference")
    bundle = paths.configs.bundles_dir / "reference.yaml"
    argv = [
        sys.executable,
        "-c",
        BARE,
        str(paths.root),
        json.dumps(installed_plugins()),
        str(bundle),
    ]
    found = json.loads(subprocess.run(argv, capture_output=True, text=True, check=True).stdout)
    assert found == {"needs": list(requirements(Selection())), "unserved": [], "plugins": []}
