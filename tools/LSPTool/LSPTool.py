from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .._runtime import SimpleTool, ToolUseContext, expand_path


def _python_symbols(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    symbols: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append({'name': node.name, 'kind': type(node).__name__, 'line': getattr(node, 'lineno', None)})
    return sorted(symbols, key=lambda item: (item['line'] or 0, item['name']))


def _generic_symbols(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding='utf-8', errors='replace')
    symbols: list[dict[str, Any]] = []
    pattern = re.compile(r'^(?:def|class|function|export\s+function|export\s+class|export\s+const)\s+([A-Za-z_][A-Za-z0-9_]*)', re.M)
    for match in pattern.finditer(text):
        line = text[: match.start()].count('\n') + 1
        symbols.append({'name': match.group(1), 'kind': 'symbol', 'line': line})
    return symbols


def _call(path: str, symbol: str | None = None, operation: str = 'symbols', toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    resolved = expand_path(path, toolUseContext.options.cwd if toolUseContext else None)
    target = Path(resolved)
    if not target.exists():
        raise FileNotFoundError(resolved)
    symbols = _python_symbols(target) if target.suffix == '.py' else _generic_symbols(target)
    result = symbols if operation == 'symbols' else [item for item in symbols if symbol and item['name'] == symbol]
    return {'data': {'path': resolved, 'operation': operation, 'symbols': result}}


LSPTool = SimpleTool(
    name='LSP',
    description_text='Lightweight language-aware symbol lookup for local files.',
    prompt_text='Use `operation="symbols"` to list symbols, or pass `symbol` to locate a specific one.',
    call_handler=_call,
    input_schema={'path': 'file path', 'symbol': 'optional symbol name', 'operation': 'symbols or lookup'},
    output_schema={'symbols': 'matching symbol records'},
    user_facing_name='LSP',
)
