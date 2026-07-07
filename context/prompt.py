from __future__ import annotations

NO_TOOLS_PREAMBLE = """CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or any other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be rejected and will waste your only turn.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.
"""

NO_TOOLS_TRAILER = (
    "\n\nREMINDER: Do NOT call any tools. Respond with plain text only - "
    "an <analysis> block followed by a <summary> block."
)

BASE_ANALYSIS_INSTRUCTION = """Before providing the final summary, wrap your working notes in <analysis> tags.

In your analysis:
1. Walk the conversation chronologically.
2. Capture user intent, code decisions, file edits, tool results, and any mistakes or retries.
3. Be precise about recent work and pending tasks.
"""

BASE_COMPACT_PROMPT = f"""Your task is to create a detailed summary of the conversation so far.

{BASE_ANALYSIS_INSTRUCTION}

Your summary should include:
1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections
4. Errors and Fixes
5. Problem Solving
6. All User Messages
7. Pending Tasks
8. Current Work
9. Optional Next Step
"""

PARTIAL_COMPACT_PROMPT = f"""Your task is to create a detailed summary of the recent portion of the conversation only.

{BASE_ANALYSIS_INSTRUCTION}

Your summary should include:
1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections
4. Errors and Fixes
5. Problem Solving
6. All User Messages
7. Pending Tasks
8. Current Work
9. Optional Next Step
"""


def get_compact_prompt(custom_instructions: str | None = None) -> str:
    prompt = NO_TOOLS_PREAMBLE + BASE_COMPACT_PROMPT
    if custom_instructions and custom_instructions.strip():
        prompt += f"\n\nAdditional Instructions:\n{custom_instructions.strip()}"
    return prompt + NO_TOOLS_TRAILER


def get_partial_compact_prompt(custom_instructions: str | None = None) -> str:
    prompt = NO_TOOLS_PREAMBLE + PARTIAL_COMPACT_PROMPT
    if custom_instructions and custom_instructions.strip():
        prompt += f"\n\nAdditional Instructions:\n{custom_instructions.strip()}"
    return prompt + NO_TOOLS_TRAILER


def format_compact_summary(summary: str) -> str:
    formatted = summary
    start = formatted.find("<analysis>")
    end = formatted.find("</analysis>")
    if start != -1 and end != -1 and end > start:
        formatted = formatted[:start] + formatted[end + len("</analysis>") :]
    summary_start = formatted.find("<summary>")
    summary_end = formatted.find("</summary>")
    if summary_start != -1 and summary_end != -1 and summary_end > summary_start:
        inner = formatted[
            summary_start + len("<summary>") : summary_end
        ].strip()
        formatted = f"Summary:\n{inner}"
    return "\n\n".join(part.strip() for part in formatted.split("\n\n") if part.strip())


def get_compact_user_summary_message(
    summary: str,
    *,
    suppress_follow_up_questions: bool = True,
    transcript_path: str | None = None,
    recent_messages_preserved: bool = False,
) -> str:
    formatted = format_compact_summary(summary)
    message = (
        "This session is continuing from earlier context that was compacted.\n\n"
        f"{formatted}"
    )
    if transcript_path:
        message += (
            "\n\nIf you need exact earlier details, read the archived transcript at: "
            f"{transcript_path}"
        )
    if recent_messages_preserved:
        message += "\n\nRecent messages are preserved verbatim."
    if suppress_follow_up_questions:
        message += (
            "\n\nContinue directly from where the work left off. Do not acknowledge "
            "the summary and do not ask the user to restate the task."
        )
    return message
