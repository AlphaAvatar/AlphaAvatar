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
"""Check docs/manifest.yaml, links and anchors, and the Roadmap, offline.

The manifest's fields are described in its header, the Roadmap's format in its Format section.
Exit status 1 lists every problem found.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "manifest.yaml"

TYPES = set(
    "overview guide cli reference package plugin example development agent-guide roadmap release"
    " illustration record".split()
)
LANGS = {"en", "zh-CN"}
VISIBILITY = {"public", "internal"}
DOC_STATUS = {"current", "planned", "historical", "illustrative"}
REQUIRED = ("id", "path", "title", "type", "lang", "visibility", "status")
PUBLIC_REQUIRED = ("route", "section", "order", "applies_to")
VERSION = re.compile(r"v\d+\.\d+\.\d+")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")

ITEM_STATUS = {"proposed", "planned", "in-progress", "implemented", "done"}
RELEASE_STATE = {"released", "in-development", "planned", "unscheduled"}
PRIORITY = {"🔸", "🔹", "—"}
ITEM_HEADERS = (
    "| ID | Item | Status | Priority | Date | Notes |",
    "| ID | 事项 | 状态 | 优先级 | 日期 | 说明 |",
)
TIMELINE_HEADERS = ("| Milestone |", "| 里程碑 |")
AREA_HEADERS = ("| Code |", "| 代码 |")
ITEM_ID = re.compile(r"[A-Z]{2,4}-\d{2}")
DATE = re.compile(r"—|\d{4}-\d{2}(-\d{2})?|\d{4}-\d{2}-\d{2} – \d{4}-\d{2}-\d{2}")

FENCE = re.compile(r"^ {0,3}(```|~~~)")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
INLINE_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REF_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")
HTML_ATTR = re.compile(r"\b(?:src|href)=\"([^\"]+)\"")
HTML_ID = re.compile(r"\b(?:id|name)=\"([^\"]+)\"")
CODE_SPAN = re.compile(r"`+[^`]*`+")


def _tracked() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", ".venv", "node_modules", "third_party", "__pycache__"}
        return [
            p.relative_to(ROOT).as_posix()
            for p in ROOT.rglob("*")
            if p.is_file() and not skip & set(p.relative_to(ROOT).parts)
        ]
    return out.splitlines()


def _lines(text: str) -> list[tuple[int, str]]:
    """Lines outside fenced code blocks, with inline code removed."""
    out, fenced = [], False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            out.append((number, CODE_SPAN.sub(" ", line)))
    return out


def _slug_char(category: str) -> bool:
    return category[0] in "LMN" or category == "Pc"


def _slug(heading: str) -> str:
    text = re.sub(r"<[^>]+>", "", heading)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").replace("*", "").lower()
    kept = "".join(ch for ch in text if ch in " -" or _slug_char(unicodedata.category(ch)))
    return kept.replace(" ", "-")


def _anchors(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path not in cache:
        text = path.read_text(encoding="utf-8")
        found = set(HTML_ID.findall(text))
        if path.suffix == ".md":
            counts: dict[str, int] = {}
            fenced = False
            for line in text.splitlines():
                if FENCE.match(line):
                    fenced = not fenced
                    continue
                match = None if fenced else HEADING.match(line)
                if match:
                    slug = _slug(match.group(2))
                    n = counts.get(slug, 0)
                    counts[slug] = n + 1
                    found.add(slug if n == 0 else f"{slug}-{n}")
        cache[path] = found
    return cache[path]


def _check_links(rel: str, problems: list[str], cache: dict[Path, set[str]]) -> None:
    source = ROOT / rel
    for number, line in _lines(source.read_text(encoding="utf-8")):
        targets = INLINE_LINK.findall(line) + HTML_ATTR.findall(line)
        ref = REF_DEF.match(line)
        if ref:
            targets.append(ref.group(1))
        for target in targets:
            if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            path_part, _, fragment = target.partition("#")
            path_part = path_part.split("?", 1)[0]
            dest = (source.parent / path_part).resolve() if path_part else source
            where = f"{rel}:{number}: {target}"
            if not dest.is_relative_to(ROOT):
                problems.append(f"{where}: outside the repository")
            elif not dest.exists():
                problems.append(f"{where}: no such file")
            elif fragment and dest.is_file() and dest.suffix in (".md", ".html"):
                if fragment not in _anchors(dest, cache):
                    problems.append(f"{where}: no such anchor")


"""Manifest"""


def _check_manifest(problems: list[str]) -> dict:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    sections = {s["id"] for s in manifest.get("sections", [])}
    documents, groups = manifest.get("documents", []), manifest.get("groups", [])
    ids, routes, paths = set(), set(), set()

    for doc in documents:
        label = f"manifest: {doc.get('id', doc.get('path'))}"
        missing = [k for k in REQUIRED if k not in doc]
        if doc.get("visibility") == "public":
            missing += [k for k in PUBLIC_REQUIRED if k not in doc]
        if missing:
            problems.append(f"{label}: missing {', '.join(missing)}")
            continue

        allowed_values = {
            "type": TYPES,
            "lang": LANGS,
            "visibility": VISIBILITY,
            "status": DOC_STATUS,
        }
        for key, allowed in allowed_values.items():
            if doc[key] not in allowed:
                problems.append(f"{label}: {key} {doc[key]!r} is not one of {sorted(allowed)}")
        if doc["id"] in ids:
            problems.append(f"{label}: duplicate id")
        if doc["path"] in paths:
            problems.append(f"{label}: duplicate path")
        ids.add(doc["id"])
        paths.add(doc["path"])
        if not (ROOT / doc["path"]).is_file():
            problems.append(f"{label}: {doc['path']} does not exist")

        if doc["visibility"] == "public":
            key = (doc["route"], doc["lang"])
            if key in routes:
                problems.append(f"{label}: route {doc['route']} repeats for {doc['lang']}")
            routes.add(key)
            if doc["section"] not in sections:
                problems.append(f"{label}: unknown section {doc['section']!r}")
            if not isinstance(doc["order"], int):
                problems.append(f"{label}: order must be an integer")
        elif "route" in doc:
            problems.append(f"{label}: internal documents have no route")

        applies = doc.get("applies_to", "snapshot")
        if applies != "snapshot" and not VERSION.fullmatch(str(applies)):
            problems.append(f"{label}: applies_to must be snapshot or vX.Y.Z")
        if doc["type"] == "release":
            release = doc.get("release") or {}
            if release.get("tag") != applies:
                problems.append(f"{label}: release.tag must equal applies_to")
            if not DAY.fullmatch(str(release.get("published", ""))):
                problems.append(f"{label}: release.published must be YYYY-MM-DD")

    by_group: dict[str, set[str]] = {}
    for doc in documents:
        if "translation_group" in doc:
            langs = by_group.setdefault(doc["translation_group"], set())
            if doc["lang"] in langs:
                problems.append(f"manifest: {doc['id']}: two {doc['lang']} files in its group")
            langs.add(doc["lang"])

    tracked = _tracked()
    for rel in tracked:
        if not (rel.endswith(".md") or rel.startswith("docs/")) or rel == "docs/manifest.yaml":
            continue
        if rel not in paths and not any(fnmatch.fnmatch(rel, g["pattern"]) for g in groups):
            problems.append(f"manifest: {rel} is neither listed nor grouped")
    return manifest


"""Roadmap"""


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table_kind(header: str) -> str:
    if header.strip() in ITEM_HEADERS:
        return "items"
    if header.startswith(TIMELINE_HEADERS):
        return "timeline"
    return "areas" if header.startswith(AREA_HEADERS) else "other"


def _parse_roadmap(rel: str, problems: list[str]) -> tuple[list[tuple], dict[str, tuple]]:
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    timeline, items, areas = [], {}, set()
    anchors = [m.group(1) for line in lines if (m := re.match(r'<a id="([^"]+)"></a>$', line))]
    table = milestone = None

    for number, line in enumerate(lines, 1):
        anchor = re.match(r'<a id="([^"]+)"></a>$', line)
        if anchor and number < len(lines) and lines[number].startswith("### "):
            milestone = anchor.group(1)
        if not line.startswith("|"):
            table = None
            continue
        if table is None:
            table = _table_kind(line)
            continue
        if set(line) <= set("|-: "):
            continue

        cells, where = _cells(line), f"{rel}:{number}"
        if table == "timeline":
            match = re.fullmatch(r"\[`([^`]+)`\]\(#([^)]+)\)", cells[0])
            if not match or match.group(1) != match.group(2):
                problems.append(f"{where}: milestone cell must link to its own anchor")
                continue
            timeline.append((match.group(1), cells[1], cells[3], cells[4], cells[5]))
            if cells[3] not in RELEASE_STATE:
                problems.append(f"{where}: release state {cells[3]!r}")
            if not DATE.fullmatch(cells[4]):
                problems.append(f"{where}: date {cells[4]!r}")
        elif table == "areas":
            areas.add(cells[0].strip("`"))
        elif table == "items":
            item_id = cells[0].strip("`")
            if not ITEM_ID.fullmatch(item_id):
                problems.append(f"{where}: item ID {cells[0]!r}")
            if item_id in items:
                problems.append(f"{where}: {item_id} repeats")
            if milestone is None:
                problems.append(f"{where}: {item_id} is outside a milestone")
            if cells[2] not in ITEM_STATUS:
                problems.append(f"{where}: {item_id} status {cells[2]!r}")
            if cells[3] not in PRIORITY:
                problems.append(f"{where}: {item_id} priority {cells[3]!r}")
            if not DATE.fullmatch(cells[4]):
                problems.append(f"{where}: {item_id} date {cells[4]!r}")
            items[item_id] = (milestone, cells[2], cells[3], cells[4], cells[5], where)

    milestones = {m[0]: m for m in timeline}
    for name in milestones:
        if name not in anchors:
            problems.append(f"{rel}: milestone {name} has no section")
    for item_id, (milestone, status, _, _, notes, where) in items.items():
        if item_id.split("-")[0] not in areas:
            problems.append(f"{where}: {item_id} has no area in the Areas table")
        if milestone not in milestones:
            problems.append(f"{where}: {item_id} is in {milestone}, not in the Timeline")
        elif milestones[milestone][2] == "released" and status != "done":
            problems.append(f"{where}: {item_id} in released {milestone} is {status}")
        for ref in re.findall(r"\b[A-Z]{2,4}-\d{2}\b", notes):
            if ref.split("-")[0] in areas and ref not in items:
                problems.append(f"{where}: {item_id} refers to unknown {ref}")
    return timeline, items


def _check_releases(rel: str, timeline: list[tuple], manifest: dict, problems: list[str]) -> None:
    """A released version matches its release notes entry; other milestones link none."""
    releases = {d.get("applies_to"): d for d in manifest["documents"] if d["type"] == "release"}
    for milestone, version, state, date, notes in timeline:
        where = f"{rel}: Timeline {milestone}"
        links = re.findall(r"\]\(([^)#\s]+\.md)\)", notes)
        if not VERSION.fullmatch(milestone):
            # earlier summarizes several versions, backlog is none: no single release notes.
            if links:
                problems.append(f"{where}: links release notes")
            continue

        if version != milestone:
            problems.append(f"{where}: version {version!r}")
        if state != "released":
            if date != "—" or links:
                problems.append(f"{where}: {state}, yet has a release date or release notes")
            continue

        entry = releases.get(milestone)
        if entry is None:
            problems.append(f"{where}: no release notes entry in the manifest")
            continue
        release = entry.get("release") or {}
        if release.get("tag") != version:
            problems.append(f"{where}: manifest release.tag {release.get('tag')!r}")
        if str(release.get("published")) != date:
            problems.append(f"{where}: released {date}, manifest {release.get('published')}")
        paths = {((ROOT / rel).parent / link).resolve() for link in links}
        if paths != {(ROOT / entry["path"]).resolve()}:
            linked = sorted(p.relative_to(ROOT).as_posix() for p in paths if p.is_relative_to(ROOT))
            problems.append(f"{where}: release notes link {linked}, manifest {entry['path']}")


def _check_roadmaps(manifest: dict, problems: list[str]) -> None:
    roadmaps = [d["path"] for d in manifest["documents"] if d["type"] == "roadmap"]
    parsed = {rel: _parse_roadmap(rel, problems) for rel in roadmaps}
    for rel, (timeline, _) in parsed.items():
        _check_releases(rel, timeline, manifest, problems)
    if len(parsed) < 2:
        return

    (first, (timeline, items)), *others = parsed.items()
    for rel, (other_timeline, other_items) in others:
        if [(m[0], m[2], m[3]) for m in other_timeline] != [(m[0], m[2], m[3]) for m in timeline]:
            problems.append(f"{rel}: Timeline differs from {first}")
        for item_id in items.keys() ^ other_items.keys():
            problems.append(f"{rel}: {item_id} is in only one of it and {first}")
        for item_id in items.keys() & other_items.keys():
            if items[item_id][:4] != other_items[item_id][:4]:
                problems.append(
                    f"{rel}: {item_id} milestone, status, priority or date differs from {first}"
                )


def main() -> int:
    problems: list[str] = []
    manifest = _check_manifest(problems)

    cache: dict[Path, set[str]] = {}
    for doc in manifest.get("documents", []):
        if doc.get("path", "").endswith(".md") and (ROOT / doc["path"]).is_file():
            _check_links(doc["path"], problems, cache)
    _check_roadmaps(manifest, problems)

    for problem in problems:
        print(problem, file=sys.stderr)
    documents = len(manifest.get("documents", []))
    print(f"docs: {documents} documents, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
