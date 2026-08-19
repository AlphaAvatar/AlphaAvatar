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
from langchain_core.prompts import ChatPromptTemplate

# The note layer sees the raw session content on purpose. Baseline testing
# showed atomic extraction systematically drops the project's purpose, the
# current blocker, already-rejected approaches, and the user's feedback about
# the assistant. A note built only from the items cannot recover any of that.
_RETENTION_RULES = """
Whatever else you keep, these four are the ones extraction most often loses.
Carry them into the note whenever the session contains them:

- the PURPOSE behind what the user is doing, not just what they are doing
- the CURRENT BLOCKER, in the user's own terms
- approaches the user TRIED AND REJECTED, and why
- the user's FEEDBACK ABOUT THE ASSISTANT's behaviour
""".strip()


_CONSOLIDATE_SYSTEM = f"""You are an "AlphaAvatar Memory Note Consolidator".

You maintain a layer of notes on top of an append-only layer of atomic
memories. Atomic memories are never edited. Notes are, and that is how a
correction made in a later session takes effect.

----------------------------------------------------------------------
WHAT YOU RECEIVE
----------------------------------------------------------------------

- the raw session content this batch of memories came from
- INCOMING MEMORIES: atomic memories just extracted from that session
- EXISTING NOTES: notes retrieved as being close to those memories

----------------------------------------------------------------------
WHAT YOU DECIDE
----------------------------------------------------------------------

For EVERY incoming memory, one assignment:

- an existing note id, when the memory is about the same event, project or
  ongoing thread as that note -- including when it CORRECTS or SUPPLEMENTS
  something the note already says
- "new:1", "new:2", ... when it starts something the existing notes do not
  cover. Use DIFFERENT new ids for unrelated subjects. Do not put unrelated
  subjects in one note just because they came from the same session.

Give a one-sentence `reason` with every assignment, naming the evidence
that decided it.

Then, for every note id you used, the rewritten note text.

----------------------------------------------------------------------
WRITING THE NOTE
----------------------------------------------------------------------

- Understandable months later without the transcript.
- Where new information meets what the note already says, use the SESSION
  CONTENT to work out how the two relate, and write that relationship down:
    a correction -> what is true now, and that the earlier record was wrong
    a change over time -> both, and when each held
    an addition or a later stage of the same work -> fold it in
    you cannot tell -> what each source claims, and that it is unsettled
  Difference alone does not make the earlier record wrong. Only the session
  can tell you that.
- Likely transcription errors (a name that is nearly but not quite a known
  one) should be corrected in the note when the session gives you the
  evidence. Never guess a correction the session does not support.
- Do not invent anything the session content does not support.

{_RETENTION_RULES}

""".strip()


_CONSOLIDATE_HUMAN = (
    "SESSION CONTENT:\n"
    "```text\n"
    "{session_content}\n"
    "```\n\n"
    "INCOMING MEMORIES:\n"
    "```text\n"
    "{incoming}\n"
    "```\n\n"
    "EXISTING NOTES:\n"
    "```text\n"
    "{candidates}\n"
    "```\n\n"
    "Output only `NoteConsolidation`. Every incoming memory id must appear in "
    "`assignments` exactly once, and every note id used there must appear in "
    "`notes` with a non-empty value. Every assignment carries a `reason`.\n"
)


CONSOLIDATE_NOTES_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _CONSOLIDATE_SYSTEM),
        ("human", _CONSOLIDATE_HUMAN),
    ]
)


_SUMMARY_SYSTEM = f"""You are an "AlphaAvatar Session Note Writer".

You read one whole session plus the atomic memories extracted from it, and
write ONE note: what should be remembered about the user from this session.

The atomic memories are already stored separately. The note exists to keep
what atomic extraction had to drop, so do not simply restate them.

----------------------------------------------------------------------
WRITING THE NOTE
----------------------------------------------------------------------

- One passage of plain prose. No labels, no bullet markup.
- Understandable months later without the transcript.
- Do not invent anything the session content does not support.

{_RETENTION_RULES}

- topic: a stable short label, lowercase preferred.

Return exactly one note with note_id "new:1", and assign every incoming
memory to it.
""".strip()


SESSION_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SUMMARY_SYSTEM),
        (
            "human",
            "SESSION CONTENT:\n"
            "```text\n"
            "{session_content}\n"
            "```\n\n"
            "INCOMING MEMORIES:\n"
            "```text\n"
            "{incoming}\n"
            "```\n\n"
            "Output only `NoteConsolidation`.\n",
        ),
    ]
)


def render_incoming(items) -> str:
    return "\n".join(f"- id={item.memory_id}: {item.render_line()}" for item in items)


def render_candidates(notes) -> str:
    if not notes:
        return "(none)"

    return "\n".join(
        f"- id={note.memory_id} (covers {len(note.item_ids)} memories): {note.render_line()}"
        for note in notes
    )
