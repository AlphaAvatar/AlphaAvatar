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
import difflib
import importlib.util
import itertools
import os
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import pytest
import yaml
from omegaconf import OmegaConf
from pydantic import BaseModel

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.agents.configs.plugins.foundation.voice_config import TTSConfig
from alphaavatar.agents.runtime.inference import plan_inference_runners
from alphaavatar.host.configs import ConfigSource, resolve_capabilities, validate_application
from alphaavatar.host.configs.template import SECTIONS, render_bundle
from alphaavatar.host.tools.setup.choices import (
    OPENAI_KEY,
    Model,
    Selection,
    Synthesis,
    Transcription,
    bundle_requirements,
    capabilities,
    credentials,
    requirements,
    sections,
    server_key,
    server_problem,
)
from alphaavatar.host.tools.setup.plan import plan_install
from alphaavatar.host.workspace import ApplicationPaths

ROOT = Path(__file__).resolve().parents[3]
SELECTIONS = [
    Selection(voice=voice, vision=vision, local_models=local, env_memory=env, vector_store=store)
    for voice, vision, local, env, store in itertools.product(
        (True, False), (True, False), (True, False), (True, False), ("lancedb", "qdrant")
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


def own_models(url: str, chat: str = "chat", tasks: str = "tasks", embedding: str = "embed"):
    """Every model but ENV memory's from one server of one's own: the loop's, the tasks' and
    the embeddings."""
    task = Model("openai", tasks, url)
    return {
        "loop": Model("openai", chat, url),
        "conversation": task,
        "tool": task,
        "profiler": task,
        "embedding": Model("openai", embedding, url),
    }


def own_speech(url: str, transcription: str = "transcribe", speech: str = "speak", voice="voice"):
    """Speech in and out from one server of one's own with OpenAI's audio API."""
    return {
        "transcription": Transcription("openai_segment", transcription, url),
        "synthesis": Synthesis("openai", speech, voice, server=url),
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
    parts = (selection.voice, selection.vision, selection.local_models, selection.env_memory)
    return "-".join(map(str, (*parts, selection.vector_store)))


@pytest.mark.parametrize("selection", SELECTIONS, ids=label)
def test_each_selection_asks_for_exactly_what_its_bundle_resolves_to(
    selection: Selection, tmp_path: Path
) -> None:
    # A Qdrant URL in the environment moves no vector store a LanceDB selection chose.
    with mock.patch.dict(os.environ, {"QDRANT_URL": "http://qdrant.invalid:6333"}):
        config = compose(selection, tmp_path / "home")
        found = sorted({need.requirement for need in resolve_capabilities(config).needs})
    assert found == list(requirements(selection))
    names = [credential.name for credential in credentials(selection) if credential.required]
    assert ("QDRANT_URL" in names) == (selection.vector_store == "qdrant")


def test_own_servers_take_what_the_installed_providers_send_there(tmp_path: Path) -> None:
    from alphaavatar.plugins.provider.openai.llms.config import OpenAIClientConfig

    models, speech = "http://gpu.invalid:8000/v1", "https://speech.invalid:8001/v1"
    own = Selection(
        **own_models(models, "qwen3-32b", "qwen3-8b", "bge-m3"),
        **own_speech(speech, "whisper-large-v3", "kokoro", "af_heart"),
    )
    config = compose(own, tmp_path / "home")
    models_key, speech_key = server_key(models), server_key(speech)
    avatar, server = config.avatar, {"base_url": models, "api_key_env": models_key}
    loop = avatar.loop.init_config["model"]
    assert (loop["backend"], loop["model"], loop["extra"]) == ("openai", "qwen3-32b", server)
    # The loop's Responses client is pointed at the server; tasks and embeddings go there too.
    assert OpenAIClientConfig.model_validate(loop["extra"]).base_url == models
    tasks = avatar.persona.init_config["profiler"]["provider"]["gateway"]["tasks"]
    task = tasks["persona.profile_delta"]
    assert (task["provider"], task["model"], task["temperature"]) == ("openai", "qwen3-8b", 0.1)
    assert task["extra"] == server
    for section in (avatar.memory, avatar.persona):
        assert section.vdb_config["embedding"] == {
            "provider": "openai",
            "model": "bge-m3",
            "extra": server,
        }
    voice = avatar.voice
    assert (voice.stt.base_url, voice.stt.model) == (speech, "whisper-large-v3")
    assert (voice.tts.base_url, voice.tts.model, voice.tts.speaker) == (
        speech,
        "kokoro",
        "af_heart",
    )
    assert voice.stt.api_key_env == voice.tts.api_key_env == speech_key != models_key
    # The same packages serve them; each server's key is whatever that server expects.
    found = sorted({need.requirement for need in resolve_capabilities(config).needs})
    assert found == list(requirements(own)) == list(requirements(Selection()))
    asked = {credential.name: credential.purpose for credential in credentials(own)}
    assert OPENAI_KEY not in asked
    assert asked[models_key] == (
        f"your server {models}: the conversation model, memory, tool memory, persona profiles, "
        "embeddings; any text if it needs none"
    )
    assert asked[speech_key] == (
        f"your server {speech}: speech recognition, speech synthesis; any text if it needs none"
    )
    # ENV memory stays Gemini's: never a text model on the server.
    assert asked["GOOGLE_API_KEY"] == "ENV memory, from Google"


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
    own: str, tmp_path: Path, owned_addresses: set[object]
) -> None:
    model_server, speech_server = Server(), Server()
    if own == "one server":
        speech_server.close()
        speech_server = model_server
    for server in (model_server, speech_server):
        owned_addresses.add(server.http.server_address[:2])
    try:
        check_keys(own, model_server, speech_server, tmp_path)
    finally:
        for server in {id(model_server): model_server, id(speech_server): speech_server}.values():
            server.close()


def check_keys(own: str, model_server: Server, speech_server: Server, tmp_path: Path) -> None:
    from alphaavatar.agents.avatar.provider.factory import create_embedding_model
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig

    selection = Selection(
        **(own_models(model_server.url) if own != "speech" else {}),
        **(own_speech(speech_server.url) if own != "models" else {}),
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


def test_a_server_of_ones_own_has_one_key_variable_for_its_url_alone() -> None:
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

    models, speech = "http://gpu.invalid:8000/v1", "https://speech.invalid:8001/v1"
    bundle = bundle_of(Selection(**own_models(models), **own_speech(speech)))
    (*parents, place), location = KEYED[where]
    url = speech if parents[0] == "voice" else models

    def moved(base_url: str | None, **changes: str):
        document = copy.deepcopy(bundle)
        parent = document
        for key in parents:
            parent = parent[key]
        # A mapping of its own: setup's YAML aliases the one it wrote to several places.
        parent[place] = {**parent[place], "base_url": base_url, **changes}
        return validated(document, tmp_path / "home")

    moved(url + "/")  # The same URL, however spelled.
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
    assert accepts(lambda: Model("openai", "c", url)) == models
    assert accepts(lambda: Transcription("openai_segment", "t", url)) == speech
    assert accepts(lambda: Synthesis("openai", "s", "v", server=url)) == speech


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


def test_the_catalog_gives_setup_each_plugin_s_storage_namespace(tmp_path: Path) -> None:
    """The module the Linux build records for each implementation, from its wheel's entry
    point, gives the storage namespace its runner keeps data under, for every plugin installed
    here: setup finds the data before the plugin is installed."""
    import zipfile
    from importlib import metadata

    from alphaavatar.agents.runtime.plugin import AvatarModule, resolve_plugin
    from alphaavatar.agents.runtime.plugin.schemas.resolved_plugin import ResolvedPlugin

    spec = importlib.util.spec_from_file_location("catalog", ROOT / "packaging/linux/catalog.py")
    assert spec is not None and spec.loader is not None
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)

    wheel = tmp_path / "alpha_avatar_plugins_memory-1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "alpha_avatar_plugins_memory-1.dist-info/entry_points.txt",
            "[alphaavatar.memory]\ndefault = alphaavatar.plugins.memory.factory:MemoryPlugin\n",
        )
    declared = catalog.plugins(wheel, "alpha-avatar-plugins-memory", {})
    assert declared == {
        "memory": {"default": ("alpha-avatar-plugins-memory", "alphaavatar.plugins.memory.factory")}
    }

    seen = 0
    for module in AvatarModule:
        for entry in metadata.entry_points(group=module.group):
            namespace = resolve_plugin(module, entry.name).namespace
            assert ResolvedPlugin.namespace_of(entry.module) == namespace, entry
            seen += 1
    assert seen > 10


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
    "selection", [*SELECTIONS, Selection(**own_models("http://m.invalid:8000/v1"))], ids=label
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
        "perception/router": lambda body: (
            _drop(body, "init_config", "turn_taking", "enabled"),
            _drop(body, "init_config", "addressing", "semantic", "enabled"),
        ),
        "perception/persona": lambda body: (
            _drop(body, "init_config", "speaker", "enabled"),
            _drop(body, "init_config", "face", "enabled"),
        ),
    },
    # A part switched off creates nothing: a backend nothing installs is not needed for it.
    "off, on a backend nothing installs": {
        "perception/persona": lambda body: body["init_config"]["profiler"].update(
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
    # A task that names its model alone: its kind and backend are the schema's defaults.
    "a task on the schema's defaults": {
        "foundation/loop": lambda body: body["init_config"].update(model={"model": "gpt-4o"})
    },
}


def edited_bundle(home: Path, edit: str) -> ConfigSource:
    """``config init``'s bundle with one of ``PROFILE_EDITS`` made in its profile files."""
    from alphaavatar.host.configs.template import create_bundle

    paths = ApplicationPaths.from_root(home)
    create_bundle(paths, "edited", avatar_id="edited")
    for profile, change in PROFILE_EDITS[edit].items():
        path = paths.configs.profiles_dir / "edited" / "plugins" / f"{profile}.yaml"
        body = yaml.safe_load(path.read_text())
        change(body)
        path.write_text(yaml.safe_dump(body))
    return ConfigSource(paths.configs.bundles_dir / "edited.yaml", "edited", home=paths.root)


@pytest.mark.parametrize("edit", PROFILE_EDITS)
def test_a_bundle_edited_in_its_profiles_plans_what_start_resolves(
    edit: str, tmp_path: Path
) -> None:
    from alphaavatar.host.configs import load_application

    source = edited_bundle(tmp_path / "home", edit)
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
import importlib.abc, json, os, sys
from pathlib import Path


class Bare(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[:2] == ["alphaavatar", "plugins"]:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)


sys.meta_path.insert(0, Bare())
from alphaavatar.host.configs import ConfigSource, load_selections
from alphaavatar.host.service.sessions.factory import check_session_credentials
from alphaavatar.host.tools.setup.choices import bundle_requirements

home, plugins, bundle = Path(sys.argv[1]), json.loads(sys.argv[2]), Path(sys.argv[3])
host, avatar = load_selections(ConfigSource(bundle, bundle.stem, home=home))
needs, unserved = bundle_requirements(host, avatar, plugins)
try:
    check_session_credentials(host.rtc, os.environ)
    credentials = None
except ValueError as error:
    credentials = str(error)
loaded = sorted(name for name in sys.modules if name.startswith("alphaavatar.plugins"))
print(json.dumps({"needs": sorted(needs), "unserved": unserved, "plugins": loaded, "credentials": credentials}))
"""


def bare(home: Path, bundle: Path, plugins: dict, env: dict[str, str] | None = None) -> dict:
    """``BARE`` in a process of its own, with no plugin importable and an environment of
    ``env`` alone: nothing installed or exported here stands in for what is missing. That
    environment drops PYTHONDONTWRITEBYTECODE too, so ``-B`` keeps the checkout unwritten."""
    import json
    import subprocess
    import sys

    argv = [sys.executable, "-B", "-c", BARE, str(home), json.dumps(plugins), str(bundle)]
    environ = {"PATH": os.environ["PATH"], "HOME": str(home)} | (env or {})
    result = subprocess.run(argv, capture_output=True, text=True, check=True, env=environ)
    return json.loads(result.stdout)


def test_a_bare_base_plans_a_bundle_without_importing_any_plugin(tmp_path: Path) -> None:
    """Before setup installs anything, no plugin is there to import: the plan comes from the
    bundle's settings and the catalog alone."""
    from alphaavatar.host.configs.template import create_bundle

    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "reference", avatar_id="reference")
    found = bare(paths.root, paths.configs.bundles_dir / "reference.yaml", installed_plugins())
    assert (found["needs"], found["unserved"], found["plugins"]) == (
        list(requirements(Selection())),
        [],
        [],
    )


def test_a_bare_base_plans_a_task_left_to_the_schemas_defaults(tmp_path: Path) -> None:
    """The loop's task names its model alone: the plan needs the schema's default backend,
    here one the catalog does not serve, so setup names it where it is."""
    source = edited_bundle(tmp_path / "home", "a task on the schema's defaults")
    plugins = installed_plugins()
    del plugins["provider.llm"]["langchain"]
    found = bare(source.home, source.path, plugins)
    assert "loop.init_config.model: provider.llm 'langchain'" in found["unserved"]
    assert found["plugins"] == []


def test_a_bare_base_checks_the_session_transport_credentials_offline(tmp_path: Path) -> None:
    from alphaavatar.host.configs.template import create_bundle

    paths = ApplicationPaths.from_root(tmp_path / "home")
    create_bundle(paths, "reference", avatar_id="reference")
    bundle = paths.configs.bundles_dir / "reference.yaml"
    missing = bare(paths.root, bundle, installed_plugins())
    assert missing["credentials"] == (
        "LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required"
    )
    given = {
        "LIVEKIT_URL": "wss://livekit.invalid",
        "LIVEKIT_API_KEY": "lk-fictional",
        "LIVEKIT_API_SECRET": "lk-fictional-secret",
    }
    assert bare(paths.root, bundle, installed_plugins(), given)["credentials"] is None


SPEECH = "https://speech.invalid:8001/v1"
INSTRUCTIONS = yaml.safe_load(SECTIONS["voice"])["tts"]["instructions"]
CHOSEN = "# Chosen with `alphaavatar setup`.\n"


@pytest.mark.parametrize(
    ("plugin", "model", "voice", "instructions", "speed"),
    [
        ("openai", "gpt-4o-mini-tts", "ash", INSTRUCTIONS, 1.15),
        ("openai", "tts-1", "alloy", None, 1.15),
        ("openai", "tts-1-hd", "alloy", None, 1.15),
        ("voiceai", "voiceai-tts-v1", None, None, 1.0),
    ],
    ids=["gpt-4o-mini-tts", "tts-1", "tts-1-hd", "voiceai"],
)
def test_speech_out_keeps_the_settings_its_implementation_and_model_take(
    plugin: str,
    model: str,
    voice: str | None,
    instructions: str | None,
    speed: float,
    tmp_path: Path,
) -> None:
    """The reference's voice, speed and instructions stay where the implementation and model
    take them; where not, the bundle says so and still loads. A server of one's own running
    tts-1 failed to load here once, holding the reference's instructions."""
    server = SPEECH if plugin == "openai" else None
    selection = Selection(synthesis=Synthesis(plugin, model, voice, server=server))
    tts = compose(selection, tmp_path / "home").avatar.voice.tts
    assert (tts.plugin, tts.model, tts.speaker) == (plugin, model, voice)
    assert (tts.instructions, tts.speed) == (instructions, speed)
    text = sections(selection)["voice"]
    if instructions is None:
        reads = "Voice.ai takes" if plugin == "voiceai" else f"{model} takes"
        assert f"  instructions: null  # {reads} no instructions.\n" in text
    else:
        assert "  instructions: >\n    Speak naturally," in text
    if plugin == "voiceai":
        assert "  speed: 1.0  # Voice.ai takes no speed.\n" in text
        asked = {credential.name: credential.purpose for credential in credentials(selection)}
        assert asked["VOICEAI_API_KEY"] == "speech synthesis, from Voice.ai"


def test_a_setting_speech_out_does_not_take_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Voice.ai speech takes no speed"):
        Synthesis("voiceai", "voiceai-tts-v1", None, speed=1.2)
    assert Selection(synthesis=Synthesis("voiceai", "voiceai-tts-v1", None, speed=1.0)).speed == 1
    with pytest.raises(ValueError, match="needs a voice"):
        Synthesis("openai", "tts-1", None)
    # Instructions written by hand for a model that reads none are refused where they are set.
    bundle = bundle_of(Selection(synthesis=Synthesis("openai", "tts-1", "alloy")))
    bundle["voice"]["tts"]["instructions"] = "Speak slowly."
    with pytest.raises(ValueError, match="does not support instructions"):
        validated(bundle, tmp_path / "home")


def test_env_memory_off_keeps_its_settings_runs_nothing_and_asks_no_google_key(
    tmp_path: Path,
) -> None:
    from alphaavatar.plugins.memory.config import DefaultMemoryConfig

    off = Selection(env_memory=False)
    memory = compose(off, tmp_path / "off").avatar.memory
    environment = DefaultMemoryConfig.model_validate(memory.init_config).model_dump()["environment"]
    task = environment["provider"]["gateway"]["tasks"]["memory.env_delta"]
    assert environment["enabled"] is False  # Not run; kept, to be switched on again.
    assert (task["provider"], task["model"], task["input_adapter"]) == (
        "google",
        "gemini-2.5-flash",
        "langchain_gemini",
    )
    assert "GOOGLE_API_KEY" not in {credential.name for credential in credentials(off)}
    assert requirements(off) == requirements(Selection())  # Shared with the other tasks.
    # Another part on Google asks for the key, for that part alone.
    google = Selection(env_memory=False, profiler=Model("google", "gemini-2.5-pro"))
    asked = {credential.name: credential.purpose for credential in credentials(google)}
    assert asked["GOOGLE_API_KEY"] == "persona profiles, from Google"
    asked = {credential.name: credential.purpose for credential in credentials(Selection())}
    assert asked["GOOGLE_API_KEY"] == "ENV memory, from Google"
    # ENV memory is Gemini's audio and video: no text model or server takes its place.
    for other in (
        Model("openai", "gpt-4o"),
        Model("openai", "qwen3", "http://gpu.invalid:8000/v1"),
    ):
        with pytest.raises(ValueError, match="environment takes google"):
            Selection(environment=other)


def test_each_part_takes_its_own_provider_and_model_and_each_key_is_asked_once(
    tmp_path: Path,
) -> None:
    from alphaavatar.agents.avatar.provider.factory import create_embedding_model, create_llm_model
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig

    server = "http://gpu.invalid:8000/v1"
    selection = Selection(
        loop=Model("openai", "qwen3-32b", server),
        conversation=Model("anthropic", "claude-sonnet-4-5"),
        tool=Model("openrouter", "deepseek/deepseek-chat"),
        profiler=Model("google", "gemini-2.5-pro"),
        embedding=Model("google", "text-embedding-004"),
    )
    config = compose(selection, tmp_path / "home")
    avatar = config.avatar

    def task(section: str, part: str, name: str) -> dict:
        return getattr(avatar, section).init_config[part]["provider"]["gateway"]["tasks"][name]

    tasks = {
        "conversation": task("memory", "conversation", "memory.conversation_delta"),
        "tool": task("memory", "tool", "memory.tool_delta"),
        "profiler": task("persona", "profiler", "persona.profile_delta"),
        "environment": task("memory", "environment", "memory.env_delta"),
    }
    assert {part: (t["provider"], t["model"]) for part, t in tasks.items()} == {
        "conversation": ("anthropic", "claude-sonnet-4-5"),
        "tool": ("openrouter", "deepseek/deepseek-chat"),
        "profiler": ("google", "gemini-2.5-pro"),
        "environment": ("google", "gemini-2.5-flash"),  # Its own: the reference's.
    }
    assert avatar.loop.init_config["model"]["extra"] == {
        "base_url": server,
        "api_key_env": server_key(server),
    }
    for vdb in (avatar.memory.vdb_config, avatar.persona.vdb_config, avatar.tools.mcp.vdb_config):
        assert vdb["embedding"] == {"provider": "google", "model": "text-embedding-004"}
    asked = {credential.name: credential.purpose for credential in credentials(selection)}
    assert asked == {
        server_key(
            server
        ): f"your server {server}: the conversation model; any text if it needs none",
        "ANTHROPIC_API_KEY": "memory, from Anthropic",
        "OPENROUTER_API_KEY": "tool memory, from OpenRouter",
        "GOOGLE_API_KEY": "ENV memory, persona profiles, embeddings, from Google",
        "OPENAI_API_KEY": "speech recognition, speech synthesis, from OpenAI",
        "LIVEKIT_URL": "the LiveKit server sessions use",
        "LIVEKIT_API_KEY": "LiveKit",
        "LIVEKIT_API_SECRET": "LiveKit",
    }
    # One install serves every provider: what start resolves is what setup plans.
    found = sorted({need.requirement for need in resolve_capabilities(config).needs})
    assert found == list(requirements(selection)) == list(requirements(Selection()))
    # Each reads its own key as start provides it; a blank one is none.
    keys = {name: f"{name.lower()}-fictional" for name in asked if not name.startswith("LIVEKIT")}
    embedding = ProviderTaskConfig.model_validate(
        avatar.memory.vdb_config["embedding"] | {"kind": "embedding"}
    )
    with mock.patch.dict(os.environ, keys):
        for part in ("conversation", "tool", "profiler"):
            model = create_llm_model(ProviderTaskConfig.model_validate(tasks[part]))
            model.validate_input()
            asyncio.run(model.aclose())
        embedder = create_embedding_model(embedding)
        assert embedder._model.google_api_key.get_secret_value() == keys["GOOGLE_API_KEY"]
    with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": " \t"}):
        with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
            create_embedding_model(embedding)


def test_a_part_that_reuses_another_s_model_writes_it_out_for_each() -> None:
    chosen = Model("anthropic", "claude-sonnet-4-5")
    texts = sections(Selection(conversation=chosen, tool=chosen, profiler=chosen))
    memory = yaml.safe_load(texts["memory"])["init_config"]
    persona = yaml.safe_load(texts["persona"])["init_config"]
    for settings, part, name in (
        (memory, "conversation", "memory.conversation_delta"),
        (memory, "tool", "memory.tool_delta"),
        (persona, "profiler", "persona.profile_delta"),
    ):
        task = settings[part]["provider"]["gateway"]["tasks"][name]
        assert (task["provider"], task["model"]) == ("anthropic", "claude-sonnet-4-5")
    # On its own lines in each place, never an alias the file would hide it behind.
    assert texts["memory"].count("            provider: anthropic\n") == 2
    assert not any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(texts["memory"]))


def covered(shipped: object, written: object) -> bool:
    """Whether every setting of ``shipped`` is still in ``written``: where a value was a
    mapping, its settings; an empty one may have gained some."""
    if isinstance(shipped, dict) and shipped:
        return isinstance(written, dict) and all(
            key in written and covered(value, written[key]) for key, value in shipped.items()
        )
    return True


CHANGED = {
    "servers and qdrant": Selection(
        local_models=False,
        env_memory=False,
        vector_store="qdrant",
        **own_models("http://gpu.invalid:8000/v1"),
        transcription=Transcription("openai_segment", "whisper-large-v3", SPEECH),
        synthesis=Synthesis("openai", "tts-1", "alloy", 1.2, SPEECH),
    ),
    "all off": Selection(voice=False, vision=False, local_models=False, env_memory=False),
    "voice.ai": Selection(synthesis=Synthesis("voiceai", "voiceai-tts-v1", None)),
}


@pytest.mark.parametrize("name", CHANGED)
def test_a_changed_profile_keeps_every_other_setting_comment_and_blank_line(name: str) -> None:
    from alphaavatar.host.configs.template import _find
    from alphaavatar.host.tools.setup.choices import _changes

    selection = CHANGED[name]
    changes = _changes(selection)
    for section, text in sections(selection).items():
        shipped, body = SECTIONS[section], text.removeprefix(CHOSEN)
        assert text.startswith(CHOSEN)

        # Every comment line and blank line stays, in order; a note ends its own line.
        def kept(t: str) -> list[str]:
            return [line for line in t.splitlines() if not line.strip() or line.lstrip()[0] == "#"]

        assert kept(body) == kept(shipped), section

        # So does each comment at the end of a setting's line, unless a note replaces it.
        def trailing(t: str) -> Counter[str]:
            return Counter(
                line.split("  # ", 1)[1]
                for line in t.splitlines()
                if "  # " in line and line.lstrip()[0] != "#"
            )

        lines, replaced = shipped.splitlines(), Counter()
        for change in changes[section]:
            at = _find(lines, change.path)
            if change.note and at is not None and "  # " in lines[at]:
                replaced[lines[at].split("  # ", 1)[1]] += 1
        assert trailing(shipped) - trailing(body) == replaced, section
        assert covered(yaml.safe_load(shipped), yaml.safe_load(body)), section
        # Two spaces in from its group, as the profiles are written.
        indents = [len(line) - len(line.lstrip(" ")) for line in body.splitlines() if line.strip()]
        assert all(i % 2 == 0 for i in indents) and all(
            b <= a + 2 for a, b in zip(indents, indents[1:], strict=False)
        ), section
        # What changed is only the settings the selection names, the instructions' text with them.
        names = {c.path[-1] for c in changes[section]}
        names |= {k for c in changes[section] if isinstance(c.value, dict) for k in c.value}
        # In the voice profile only the instructions' text sits four spaces in.
        instructions = {line.strip() for line in shipped.splitlines() if line.startswith("    ")}
        for line in difflib.ndiff(shipped.splitlines(), body.splitlines()):
            if line[:2] in ("- ", "+ "):
                setting = line[2:].strip()
                assert setting.split(":")[0] in names or setting in instructions, (section, line)


@pytest.mark.parametrize("chosen", ["speech in", "speech out", "both"])
def test_voice_off_runs_no_speech_whatever_was_chosen_for_it_and_keeps_the_choice(
    chosen: str, tmp_path: Path
) -> None:
    speech: dict[str, object] = {}
    if chosen != "speech out":
        speech["transcription"] = Transcription("openai_realtime", "gpt-realtime-whisper")
    if chosen != "speech in":
        speech["synthesis"] = Synthesis("voiceai", "voiceai-tts-v1", None)
    off, on = Selection(voice=False, **speech), Selection(**speech)
    config = compose(off, tmp_path / "off")
    voice, text = config.avatar.voice, sections(off)["voice"]
    assert (voice.vad.plugin, voice.stt.plugin, voice.tts.plugin) == (None, None, None)
    # What was chosen stays, and says what turns it on.
    stt = speech.get("transcription", Transcription("openai_segment", "gpt-4o-transcribe"))
    tts = speech.get("synthesis", Synthesis("openai", "gpt-4o-mini-tts", "ash"))
    assert (voice.stt.model, voice.tts.model, voice.tts.speaker) == (
        stt.model,
        tts.model,
        tts.speaker,
    )
    for plugin in ("silero", stt.plugin, tts.plugin):
        assert f"  plugin: null  # Voice off; {plugin} turns it on.\n" in text
    # Nothing of speech is planned, asked for or summarized: as voice off with the reference's.
    found = sorted({need.requirement for need in resolve_capabilities(config).needs})
    assert found == list(requirements(off)) == list(requirements(Selection(voice=False)))
    asked = {credential.name: credential.purpose for credential in credentials(off)}
    assert "VOICEAI_API_KEY" not in asked and not [p for p in asked.values() if "speech" in p]
    summary = capabilities(off)
    assert summary[0].startswith("voice off") and not [line for line in summary if "speech" in line]
    # The same choices with voice on run as chosen.
    runs = compose(on, tmp_path / "on")
    assert (runs.avatar.voice.stt.plugin, runs.avatar.voice.tts.plugin) == (stt.plugin, tts.plugin)
    found = sorted({need.requirement for need in resolve_capabilities(runs).needs})
    assert found == list(requirements(on)) == list(requirements(Selection()))
    assert ("VOICEAI_API_KEY" in {c.name for c in credentials(on)}) == (tts.plugin == "voiceai")
    assert [line for line in capabilities(on) if line.startswith("speech out")] == [
        f"speech out: {tts.plugin} {tts.model}"
        + (f", voice {tts.speaker}" if tts.speaker else "")
        + f", speed {on.speed:g}"
        + ("" if TTSConfig.takes_instructions(tts.plugin, tts.model) else ", no instructions")
    ]


def test_a_part_offers_the_reference_s_model_from_its_own_provider_alone() -> None:
    from alphaavatar.host.tools.setup.choices import REFERENCE, default_model

    server = "http://gpu.invalid:8000/v1"
    for part in ("loop", "conversation", "tool", "environment", "profiler", "embedding"):
        reference = REFERENCE[part]
        assert default_model(part, reference.provider) == reference.model
        # Another provider, or a server of one's own, has no model carried over to it.
        assert default_model(part, reference.provider, server) is None
        for other in {"openai", "anthropic", "google", "openrouter"} - {reference.provider}:
            assert default_model(part, other) is None, (part, other)
    assert default_model("transcription", "openai_segment") == "gpt-4o-transcribe"
    assert default_model("transcription", "openai_realtime") is None
    assert default_model("synthesis", "openai") == "gpt-4o-mini-tts"
    assert default_model("synthesis", "voiceai") is None


def test_a_chat_model_can_serve_the_later_chat_parts_that_take_its_provider() -> None:
    from alphaavatar.host.tools.setup.choices import PROVIDERS, REUSE, reusable

    order = ("loop", "conversation", "tool", "profiler")
    # Only earlier chat parts: ENV memory reads audio and video, embeddings are their own kind.
    assert set(REUSE) | {"loop"} == set(order)
    for part, earlier in REUSE.items():
        assert set(earlier) == set(order[: order.index(part)]), part
    server = Model("openai", "qwen3", "http://gpu.invalid:8000/v1")
    for part in REUSE:
        assert reusable(part, server) and reusable(part, Model("anthropic", "claude-sonnet-4-5"))
    assert not reusable("loop", Model("anthropic", "claude-sonnet-4-5"))
    assert not reusable("environment", Model("openai", "gpt-4o"))
    assert PROVIDERS["environment"] == ("google",)


def test_a_speech_server_of_one_s_own_runs_as_openai_s_audio_api() -> None:
    from alphaavatar.host.tools.setup.choices import SPEECH_SERVED

    server = "https://speech.invalid/v1"
    stt = Transcription(SPEECH_SERVED["transcription"], "whisper-large-v3", server)
    tts = Synthesis(SPEECH_SERVED["synthesis"], "kokoro", "af_heart", server=server)
    assert (stt.server, tts.server) == (server, server)
    # Realtime transcription is a WebSocket API of OpenAI's own; Voice.ai is Voice.ai's.
    with pytest.raises(ValueError, match="openai_segment"):
        Transcription("openai_realtime", "gpt-realtime-whisper", server)
    with pytest.raises(ValueError, match="openai"):
        Synthesis("voiceai", "voiceai-tts-v1", None, server=server)
