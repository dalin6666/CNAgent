from __future__ import annotations

import re
from typing import Any

from .._runtime import ToolUseContext
from .prompt import (
    ASK_USER_QUESTION_TOOL_CHIP_WIDTH,
    ASK_USER_QUESTION_TOOL_NAME,
    ASK_USER_QUESTION_TOOL_PROMPT,
    DESCRIPTION,
    PREVIEW_FEATURE_PROMPT,
)

"""
用户定义问题-normalize结构标准化-validate合法性验证-展示给用户-返回answer
-转化成llm文本
"""

# 校验preview字段是否合法html
def _validate_html_preview(preview: str | None) -> str | None:
    if preview is None:
        return None
    if re.search(r"<\s*(html|body|!doctype)\b", preview, flags=re.IGNORECASE):
        return (
            "preview must be an HTML fragment, not a full document "
            "(no <html>, <body>, or <!DOCTYPE>)"
        )
    if re.search(r"<\s*(script|style)\b", preview, flags=re.IGNORECASE):
        return "preview must not contain <script> or <style> tags."
    if not re.search(r"<[a-z][^>]*>", preview, flags=re.IGNORECASE):
        return 'preview must contain HTML when preview format is "html".'
    return None


def _normalize_option(option: dict[str, Any], question_text: str) -> dict[str, Any]:
    label = str(option.get("label", "")).strip() # 获取字段，转成str,去掉首尾空格
    description = str(option.get("description", "")).strip()
    preview = option.get("preview")
    if not label: # 若为""
        raise ValueError(f'Question "{question_text}" contains an option without a label.')
    if not description:
        raise ValueError(f'Option "{label}" in question "{question_text}" is missing a description.')
    normalized = {"label": label, "description": description}
    if preview is not None:
        normalized["preview"] = str(preview)
    return normalized


def _normalize_question(raw_question: dict[str, Any], index: int) -> dict[str, Any]:
    question_text = str(raw_question.get("question", "")).strip()
    header = str(raw_question.get("header", "")).strip()
    if not question_text:
        raise ValueError(f"Question #{index} is missing question text.")
    if not header:
        raise ValueError(f'Question "{question_text}" is missing a header.')
    if len(header) > ASK_USER_QUESTION_TOOL_CHIP_WIDTH:
        raise ValueError(
            f'Header "{header}" exceeds {ASK_USER_QUESTION_TOOL_CHIP_WIDTH} characters.'
        )
    options = raw_question.get("options")
    if not isinstance(options, list):
        raise ValueError(f'Question "{question_text}" must define an options list.')
    if not 2 <= len(options) <= 4:
        raise ValueError(f'Question "{question_text}" must have between 2 and 4 options.')
    normalized_options = [_normalize_option(dict(option), question_text) for option in options]
    labels = [option["label"] for option in normalized_options]
    if len(labels) != len(set(labels)):
        raise ValueError(f'Question "{question_text}" contains duplicate option labels.')
    return {
        "question": question_text,
        "header": header,
        "options": normalized_options,
        "multiSelect": bool(raw_question.get("multiSelect", False)),
    }


def _normalize_questions(
    questions: list[dict[str, Any]] | None,
    question: str | None = None,
) -> list[dict[str, Any]]:
    raw_items: list[dict[str, Any]]
    if questions is not None:
        raw_items = [dict(item) for item in questions]
    elif question is not None:
        raw_items = [
            {
                "question": question,
                "header": "Question",
                "options": [
                    {"label": "Yes", "description": "Proceed with this option."},
                    {"label": "No", "description": "Do not proceed with this option."},
                ],
            }
        ]
    else:
        raw_items = []
    if not 1 <= len(raw_items) <= 4:
        raise ValueError("AskUserQuestionTool requires between 1 and 4 questions.")
    normalized = [_normalize_question(item, idx) for idx, item in enumerate(raw_items, start=1)]
    texts = [item["question"] for item in normalized]
    if len(texts) != len(set(texts)):
        raise ValueError("Question texts must be unique.")
    return normalized


class PythonAskUserQuestionTool:
    name = ASK_USER_QUESTION_TOOL_NAME
    search_hint = "prompt the user with a multiple-choice question"
    max_result_size_chars = 100_000
    should_defer = True
    input_schema = {
        "questions": "1-4 question definitions",
        "answers": "optional collected answers keyed by question text",
        "annotations": "optional annotations keyed by question text",
        "metadata": "optional tracking metadata",
    }
    output_schema = {
        "questions": "normalized questions",
        "answers": "answers keyed by question text",
        "annotations": "optional annotations keyed by question text",
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return DESCRIPTION

    async def prompt(self, preview_format: str | None = None, **_kwargs: Any) -> str:
        if preview_format in PREVIEW_FEATURE_PROMPT:
            return f"{ASK_USER_QUESTION_TOOL_PROMPT}\n\n{PREVIEW_FEATURE_PROMPT[preview_format]}"
        return ASK_USER_QUESTION_TOOL_PROMPT

    def userFacingName(self, _input_data: dict[str, Any] | None = None) -> str:
        return ""

    def isEnabled(self) -> bool:
        return True

    def isConcurrencySafe(self) -> bool:
        return True

    def isReadOnly(self) -> bool:
        return True

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        questions = input_data.get("questions") or []
        if isinstance(questions, list):
            return " | ".join(
                str(item.get("question", "")).strip() if isinstance(item, dict) else str(item)
                for item in questions
            )
        return ""

    def requiresUserInteraction(self) -> bool:
        return True

    async def validateInput(self, input_data: dict[str, Any]) -> dict[str, Any]:
        try:
            normalized = _normalize_questions(
                input_data.get("questions"),
                input_data.get("question"),
            )
        except ValueError as exc:
            return {"result": False, "message": str(exc), "errorCode": 1}
        preview_format = (
            input_data.get("preview_format")
            or input_data.get("metadata", {}).get("preview_format")
            or "markdown"
        )
        if preview_format == "html":
            for question in normalized:
                for option in question["options"]:
                    err = _validate_html_preview(option.get("preview"))
                    if err:
                        return {
                            "result": False,
                            "message": (
                                f'Option "{option["label"]}" in question '
                                f'"{question["question"]}": {err}'
                            ),
                            "errorCode": 1,
                        }
        return {"result": True}

    async def checkPermissions(
        self,
        input_data: dict[str, Any],
        _context: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        return {
            "behavior": "ask",
            "message": "Answer questions?",
            "updatedInput": input_data,
        }

    async def call(
        self,
        *args: Any,
        question: str | None = None,
        questions: list[dict[str, Any]] | None = None,
        answers: dict[str, str] | None = None,
        annotations: dict[str, Any] | None = None,
        toolUseContext: ToolUseContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if args and isinstance(args[0], dict):
            payload = dict(args[0])
            question = payload.get("question", question)
            questions = payload.get("questions", questions)
            answers = payload.get("answers", answers)
            annotations = payload.get("annotations", annotations)
        del toolUseContext
        normalized_questions = _normalize_questions(questions, question)
        payload: dict[str, Any] = {
            "questions": normalized_questions,
            "answers": dict(answers or {}),
        }
        if annotations:
            payload["annotations"] = dict(annotations)
        return {"data": payload}

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        answers = output.get("answers", {})
        annotations = output.get("annotations", {})
        parts: list[str] = []
        for question_text, answer in answers.items():
            extras: list[str] = [f'"{question_text}"="{answer}"']
            annotation = annotations.get(question_text, {}) if isinstance(annotations, dict) else {}
            if annotation.get("preview"):
                extras.append(f'selected preview:\n{annotation["preview"]}')
            if annotation.get("notes"):
                extras.append(f'user notes: {annotation["notes"]}')
            parts.append(" ".join(extras))
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": (
                "User has answered your questions: "
                + ", ".join(parts)
                + ". You can now continue with the user's answers in mind."
            ),
        }


AskUserQuestionTool = PythonAskUserQuestionTool()

__all__ = ["AskUserQuestionTool", "PythonAskUserQuestionTool"]
