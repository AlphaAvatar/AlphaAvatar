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
"""Check docs/manifest.yaml, links, anchors and emphasis, the Roadmap and the CLI output pages,
offline.

The manifest's fields are described in its header, the Roadmap's format in its Format section.
Exit status 1 lists every problem found.
"""

from __future__ import annotations

import fnmatch
import json
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
PUBLIC_REQUIRED = ("route", "group", "order", "applies_to")
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
# A Roadmap milestone's summary bullet, and the longest it may be in each language.
SUMMARY = re.compile(r"- \*\*(?:Summary:\*\*|摘要\*\*：) ?(.*)")
SUMMARY_LENGTH = {"en": 240, "zh-CN": 120}


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


def _headings(text: str) -> list[tuple[int, str]]:
    """Markdown headings outside fenced code blocks: level and text."""
    found, fenced = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        match = None if fenced else HEADING.match(line)
        if match:
            found.append((len(match.group(1)), match.group(2)))
    return found


def _anchors(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path not in cache:
        text = path.read_text(encoding="utf-8")
        found = set(HTML_ID.findall(text))
        if path.suffix == ".md":
            counts: dict[str, int] = {}
            for _, heading in _headings(text):
                slug = _slug(heading)
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


def _punctuation(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "PS"


def _check_emphasis(rel: str, problems: list[str]) -> None:
    """A `**` that cannot close the bold text it opened, by CommonMark's flanking rules, is shown
    as two asterisks: for example `**发布：**planned`, whose second run follows punctuation and
    comes right before a letter. Each paragraph is checked as a whole, code spans as letters."""
    block: list[tuple[int, str]] = []
    for number, line in [*_prose_lines(ROOT / rel), (0, "")]:
        if line.strip():
            block.append((number, line))
            continue
        text = "\n".join(part for _, part in block)
        opened: list[int] = []  # Where each open run is.
        for match in re.finditer(r"(?<![*\\])\*\*(?!\*)", text):
            before = text[match.start() - 1] if match.start() else " "
            after = text[match.end()] if match.end() < len(text) else " "
            left = not after.isspace() and (
                not _punctuation(after) or before.isspace() or _punctuation(before)
            )
            right = not before.isspace() and (
                not _punctuation(before) or after.isspace() or _punctuation(after)
            )
            if right and opened:
                opened.pop()
            elif left:
                opened.append(match.start())
        for start in opened:
            line = block[text.count("\n", 0, start)][0]
            problems.append(f"{rel}:{line}: `**` opens bold text that never closes")
        block = []


def _prose_lines(path: Path) -> list[tuple[int, str]]:
    """Lines outside fenced code blocks, each code span turned into letters."""
    out, fenced = [], False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            out.append((number, CODE_SPAN.sub(lambda m: "x" * len(m.group()), line)))
    return out


"""Manifest"""


def _texts(value: object, required: bool) -> str | None:
    """What is wrong with a title or summary: one string, or one per language."""
    if value is None:
        return "missing" if required else None
    if isinstance(value, dict):
        good = set(value) == LANGS and all(isinstance(v, str) and v for v in value.values())
        return None if good else f"must give {sorted(LANGS)}"
    return None if isinstance(value, str) and value else "must be text"


def _check_sections(manifest: dict, problems: list[str]) -> dict[str, str | None]:
    """The sections and their groups, one level of subgroups at most: each group's parent group,
    None for a section's own."""
    groups_of: dict[str, str | None] = {}
    if manifest.get("schema") != 2:
        problems.append("manifest: schema must be 2")
    sections = manifest.get("sections") or []
    if not sections:
        problems.append("manifest: no sections")
    for section in sections:
        where = f"manifest: section {section.get('id')}"
        for key in ("title", "summary"):
            if wrong := _texts(section.get(key), True):
                problems.append(f"{where}: {key} {wrong}")
        if not section.get("groups"):
            problems.append(f"{where}: no groups")
        for group in section.get("groups") or []:
            for sub in [group, *group.get("groups", [])]:
                gid = sub.get("id")
                if gid in groups_of:
                    problems.append(f"manifest: group {gid} repeats")
                groups_of[gid] = None if sub is group else group.get("id")
                for key, required in (("title", True), ("summary", False)):
                    if wrong := _texts(sub.get(key), required):
                        problems.append(f"manifest: group {gid}: {key} {wrong}")
                if sub is not group and sub.get("groups"):
                    problems.append(f"manifest: group {gid}: groups go one level deep")
    return groups_of


def _check_manifest(problems: list[str]) -> dict:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    groups_of = _check_sections(manifest, problems)
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
            if doc["group"] not in groups_of:
                problems.append(f"{label}: unknown group {doc['group']!r}")
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

    by_version: dict[str, list[dict]] = {}
    for doc in documents:
        if doc.get("type") == "release" and "applies_to" in doc:
            by_version.setdefault(str(doc["applies_to"]), []).append(doc)
    for version, entries in sorted(by_version.items()):
        release = [doc.get("release") or {} for doc in entries]
        for key in ("tag", "published"):
            values = sorted({str(r.get(key)) for r in release})
            if len(values) > 1:
                problems.append(f"manifest: {version} release notes differ in {key}: {values}")
        langs = [doc.get("lang") for doc in entries]
        for lang in sorted({lang for lang in langs if langs.count(lang) > 1}):
            problems.append(f"manifest: {version} has two {lang} release notes")

    by_group: dict[str, list[dict]] = {}
    for doc in documents:
        if "translation_group" in doc:
            members = by_group.setdefault(doc["translation_group"], [])
            if doc["lang"] in {m["lang"] for m in members}:
                problems.append(f"manifest: {doc['id']}: two {doc['lang']} files in its group")
            members.append(doc)

    # Translations keep their source's headings in order, so an anchor names the same place in
    # every language of a document.
    for group, members in sorted(by_group.items()):
        files = [ROOT / m["path"] for m in members if m["path"].endswith(".md")]
        levels = {
            f.relative_to(ROOT).as_posix(): [level for level, _ in _headings(f.read_text("utf-8"))]
            for f in files
            if f.is_file()
        }
        if len({tuple(v) for v in levels.values()}) > 1:
            problems.append(f"manifest: {group}: heading levels differ between {sorted(levels)}")

    listed = {d["group"] for d in documents if d.get("visibility") == "public" and "group" in d}
    for group in groups_of:
        children = [g for g, p in groups_of.items() if p == group]
        if group not in listed and not listed & set(children):
            problems.append(f"manifest: group {group} lists no public document")

    tracked = _tracked()
    for rel in tracked:
        if not (rel.endswith(".md") or rel.startswith("docs/")) or rel == "docs/manifest.yaml":
            continue
        if not (ROOT / rel).is_file():  # Removed in the working tree.
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
    timeline, items, areas, summaries = [], {}, set(), {}
    anchors = [m.group(1) for line in lines if (m := re.match(r'<a id="([^"]+)"></a>$', line))]
    table = milestone = None

    for number, line in enumerate(lines, 1):
        anchor = re.match(r'<a id="([^"]+)"></a>$', line)
        if anchor and number < len(lines) and lines[number].startswith("### "):
            milestone = anchor.group(1)
        if (summary := SUMMARY.fullmatch(line)) and milestone is not None:
            if milestone in summaries:
                problems.append(f"{rel}:{number}: {milestone} has a second summary")
            summaries[milestone] = summary.group(1).strip()
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
    lang = "zh-CN" if rel.endswith("-zh.md") else "en"
    for milestone, summary in summaries.items():
        if not summary:
            problems.append(f"{rel}: {milestone} summary is empty")
        elif len(summary) > SUMMARY_LENGTH[lang]:
            problems.append(f"{rel}: {milestone} summary is longer than {SUMMARY_LENGTH[lang]}")
    return timeline, items, set(summaries)


def _check_releases(
    roadmap: dict, timeline: list[tuple], manifest: dict, problems: list[str]
) -> None:
    """A released version links release notes of that version, in the Roadmap's language when
    they exist, else in one that does; other milestones link none."""
    rel = roadmap["path"]
    entries = [d for d in manifest["documents"] if d["type"] == "release"]
    by_path = {(ROOT / d["path"]).resolve(): d for d in entries}
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

        own = [d for d in entries if d.get("applies_to") == milestone]
        if not own:
            problems.append(f"{where}: no release notes entry in the manifest")
            continue
        if not links:
            problems.append(f"{where}: links no release notes")
        same_lang = sorted(d["path"] for d in own if d["lang"] == roadmap["lang"])
        for link in links:
            entry = by_path.get(((ROOT / rel).parent / link).resolve())
            if entry is None or entry.get("applies_to") != milestone:
                found = "nothing in the manifest" if entry is None else entry["applies_to"]
                problems.append(f"{where}: link {link} is {found}, not {milestone} release notes")
                continue
            release = entry.get("release") or {}
            if release.get("tag") != version:
                problems.append(f"{where}: {entry['path']} release.tag {release.get('tag')!r}")
            if str(release.get("published")) != date:
                problems.append(
                    f"{where}: released {date}, {entry['path']} {release.get('published')}"
                )
            if same_lang and entry["path"] not in same_lang:
                problems.append(f"{where}: links {entry['path']}, not its own language {same_lang}")


def _check_roadmaps(manifest: dict, problems: list[str]) -> None:
    roadmaps = [d for d in manifest["documents"] if d["type"] == "roadmap"]
    parsed = {d["path"]: _parse_roadmap(d["path"], problems) for d in roadmaps}
    for roadmap in roadmaps:
        _check_releases(roadmap, parsed[roadmap["path"]][0], manifest, problems)
    if len(parsed) < 2:
        return

    (first, (timeline, items, summaries)), *others = parsed.items()
    for rel, (other_timeline, other_items, other_summaries) in others:
        for milestone in sorted(summaries ^ other_summaries):
            problems.append(f"{rel}: {milestone} has a summary in only one of it and {first}")
        if [(m[0], m[2], m[3]) for m in other_timeline] != [(m[0], m[2], m[3]) for m in timeline]:
            problems.append(f"{rel}: Timeline differs from {first}")
        for item_id in items.keys() ^ other_items.keys():
            problems.append(f"{rel}: {item_id} is in only one of it and {first}")
        for item_id in items.keys() & other_items.keys():
            if items[item_id][:4] != other_items[item_id][:4]:
                problems.append(
                    f"{rel}: {item_id} milestone, status, priority or date differs from {first}"
                )


def _check_cli_pages(problems: list[str]) -> None:
    """The CLI output pages are what cli_preview.py makes of their one data file."""
    from cli_preview import page

    data_path = ROOT / "docs" / "cli" / "cli-output.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    langs = {text["lang"] for text in data["pages"]}
    incomplete = [
        f"docs/cli/cli-output.json: {panel['name']} {key} per {sorted(langs)}"
        for panel in data["panels"]
        for key in ("title", *(("label",) if "label" in panel else ()))
        if set(panel[key]) != langs
    ]
    problems.extend(incomplete)
    if incomplete:
        return
    for text in data["pages"]:
        path = data_path.parent / text["file"]
        if not path.is_file() or path.read_text(encoding="utf-8") != page(data, text["lang"]):
            problems.append(
                f"docs/cli/{text['file']}: not generated from cli-output.json; "
                "run scripts/docs/cli_preview.py html docs/cli/cli-output.json"
            )


def main() -> int:
    problems: list[str] = []
    manifest = _check_manifest(problems)

    cache: dict[Path, set[str]] = {}
    for doc in manifest.get("documents", []):
        if doc.get("path", "").endswith(".md") and (ROOT / doc["path"]).is_file():
            _check_links(doc["path"], problems, cache)
            _check_emphasis(doc["path"], problems)
    _check_roadmaps(manifest, problems)
    _check_cli_pages(problems)

    for problem in problems:
        print(problem, file=sys.stderr)
    documents = len(manifest.get("documents", []))
    print(f"docs: {documents} documents, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
