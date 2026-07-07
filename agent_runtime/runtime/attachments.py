from __future__ import annotations

from pathlib import Path

from ..config import RuntimeConfig
from ..schemas import Attachment, FileSnapshot, Message, SessionState


class AttachmentManager:
    def build_messages(
        self,
        *,
        attachments: list[Attachment],
        watched_paths: list[str],
        session: SessionState,
        config: RuntimeConfig,
    ) -> list[Message]:
        injected: list[Message] = []

        if config.enable_attachment_injection:
            for attachment in attachments:
                injected.append(self._attachment_message(attachment, config))

        change_lines: list[str] = []
        for path in watched_paths[: config.max_file_change_items]:
            snapshot = FileSnapshot.from_path(path)
            previous = session.file_snapshots.get(path)
            if snapshot is None:
                continue
            session.file_snapshots[path] = snapshot
            if previous is None:
                continue
            if previous.mtime_ns != snapshot.mtime_ns or previous.size != snapshot.size:
                change_lines.append(
                    f"- {path} changed (size {previous.size}->{snapshot.size})"
                )

        if change_lines:
            injected.append(
                Message(
                    role="system",
                    content="Detected file changes since the last run:\n" + "\n".join(change_lines),
                    metadata={"source": "file_change_injection"},
                )
            )

        return injected

    def _attachment_message(self, attachment: Attachment, config: RuntimeConfig) -> Message:
        path = Path(attachment.path).resolve()
        content = ""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = "[binary or unreadable attachment]"
        content = content[: config.max_attachment_chars]
        description = attachment.description or "No description"
        return Message(
            role="system",
            content=(
                f"Attachment injected.\nPath: {path}\nDescription: {description}\n"
                f"Preview:\n{content}"
            ),
            metadata={"source": "attachment", "path": str(path)},
        )
