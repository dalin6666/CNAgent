from __future__ import annotations

import asyncio
import contextlib
import difflib
import fnmatch
import html
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Awaitable, Callable


def ensure_directory(path: str | os.PathLike[str]) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


PACKAGE_ROOT = Path(__file__).resolve().parent
STATE_ROOT = ensure_directory(PACKAGE_ROOT / '.state')
TASK_OUTPUT_ROOT = ensure_directory(STATE_ROOT / 'task_outputs')
WORKTREE_ROOT = ensure_directory(STATE_ROOT / 'worktrees')
CONFIG_FILE = STATE_ROOT / 'config.json'
SETTINGS_FILE = STATE_ROOT / 'settings.json'
CRON_FILE = STATE_ROOT / 'cron_tasks.json'
REMOTE_TRIGGER_FILE = STATE_ROOT / 'remote_triggers.json'
GIT_TRACKING_FILE = STATE_ROOT / 'git_operations.json'


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if cleaned:
            self.parts.append(cleaned)

    def get_text(self) -> str:
        return '\n'.join(self.parts)


@dataclass
class AbortController:
    _aborted: bool = False

    def abort(self) -> None:
        self._aborted = True

    @property
    def signal(self) -> 'AbortController':
        return self

    @property
    def aborted(self) -> bool:
        return self._aborted


def default_tool_permission_context() -> dict[str, Any]:
    return {
        'mode': 'default',
        'prePlanMode': None,
        'additionalWorkingDirectories': {},
    }


@dataclass
class AppState:
    config: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    todos: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    teams: dict[str, dict[str, Any]] = field(default_factory=dict)
    mailboxes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    mcp_resources: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    mcp_auth: dict[str, Any] = field(default_factory=dict)
    mcp_handlers: dict[str, Callable[..., Any]] = field(default_factory=dict)
    cron_tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    worktrees: dict[str, dict[str, Any]] = field(default_factory=dict)
    remote_triggers: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    plan_mode: bool = False
    tool_permission_context: dict[str, Any] = field(
        default_factory=default_tool_permission_context
    )
    allowed_channels: list[str] = field(default_factory=list)
    repl_bridge_enabled: bool = False
    repl_bridge_outbound_only: bool = False
    has_exited_plan_mode: bool = False
    needs_plan_mode_exit_attachment: bool = False
    needs_auto_mode_exit_attachment: bool = False


_GLOBAL_APP_STATE: AppState | None = None


def now_ms() -> int:
    return int(time.time() * 1000)


def create_id(prefix: str = '') -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: Path, payload: Any) -> None:
    ensure_directory(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def get_global_app_state() -> AppState:
    global _GLOBAL_APP_STATE
    if _GLOBAL_APP_STATE is None:
        config = _load_json(CONFIG_FILE, {})
        settings = _load_json(SETTINGS_FILE, {})
        _GLOBAL_APP_STATE = AppState(
            config=config,
            settings=settings,
            cron_tasks=_load_json(CRON_FILE, {}),
            remote_triggers=_load_json(REMOTE_TRIGGER_FILE, {}),
        )
        legacy_permission_context = config.get('toolPermissionContext')
        if isinstance(legacy_permission_context, dict):
            _GLOBAL_APP_STATE.tool_permission_context.update(legacy_permission_context)
        _GLOBAL_APP_STATE.repl_bridge_enabled = bool(
            config.get('remoteControlAtStartup', False)
        )
    return _GLOBAL_APP_STATE


@dataclass
class ToolUseOptions:
    tools: list[Any] = field(default_factory=list)
    cwd: str = field(default_factory=lambda: str(Path.cwd()))
    query_source: str | None = None
    debug: bool = False
    verbose: bool = False


@dataclass
class ToolUseContext:
    options: ToolUseOptions = field(default_factory=ToolUseOptions)
    app_state: AppState = field(default_factory=get_global_app_state)
    messages: list[dict[str, Any]] = field(default_factory=list)
    abort_controller: AbortController = field(default_factory=AbortController)
    agent_id: str | None = None
    read_file_state: dict[str, dict[str, Any]] = field(default_factory=dict)

    def getAppState(self) -> AppState:
        return self.app_state

    def setAppState(self, updater: Callable[[AppState], AppState | None]) -> AppState:
        updated = updater(self.app_state)
        if updated is not None:
            self.app_state = updated
        return self.app_state


async def maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
        return await value
    return value


@dataclass
class SimpleTool:
    name: str
    description_text: str | Callable[..., Any] = ''
    prompt_text: str | Callable[..., Any] = ''
    # 执行Tool调用的函数
    call_handler: Callable[..., Any] | None = None 
    aliases: tuple[str, ...] = ()
    search_hint: str = ''
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    strict: bool = False
    user_facing_name: str | Callable[[dict[str, Any] | None], str] | None = None

    async def description(self, input_data: dict[str, Any] | None = None) -> str:
        if callable(self.description_text):
            return str(await maybe_await(self.description_text(input_data)))
        return str(self.description_text)

    async def prompt(self, *args: Any, **kwargs: Any) -> str:
        if callable(self.prompt_text):
            return str(await maybe_await(self.prompt_text(*args, **kwargs)))
        return str(self.prompt_text)

    async def call(self, *args: Any, toolUseContext: ToolUseContext | None = None, **kwargs: Any) -> Any:
        if self.call_handler is None:
            raise NotImplementedError(f'{self.name} does not implement call().')
        context = toolUseContext or ToolUseContext()
        if args and isinstance(args[0], dict) and not kwargs:
            kwargs = dict(args[0])
        kwargs.setdefault('toolUseContext', context)
        return await maybe_await(self.call_handler(**kwargs))

    def userFacingName(self, input_data: dict[str, Any] | None = None) -> str:
        if callable(self.user_facing_name):
            return self.user_facing_name(input_data)
        if isinstance(self.user_facing_name, str) and self.user_facing_name:
            return self.user_facing_name
        return self.name


@contextlib.contextmanager
def pushd(path: str | os.PathLike[str] | None):
    if path is None:
        yield
        return
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def expand_path(path: str, cwd: str | None = None) -> str:
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)
    base = cwd or os.getcwd()
    return os.path.abspath(os.path.join(base, expanded))


def to_relative_path(path: str, cwd: str | None = None) -> str:
    base = Path(cwd or os.getcwd()).resolve()
    target = Path(path).resolve()
    try:
        return str(target.relative_to(base))
    except ValueError:
        return str(target)


def diff_text(path: str, old: str, new: str) -> str:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    return '\n'.join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f'{path} (before)',
            tofile=f'{path} (after)',
            lineterm='',
        )
    )


def read_text_file(path: str) -> str:
    return Path(path).read_text(encoding='utf-8', errors='replace')


def write_text_file(path: str, content: str) -> None:
    target = Path(path)
    ensure_directory(target.parent)
    target.write_text(content, encoding='utf-8')


def read_text_slice(path: str, offset: int | None = None, limit: int | None = None) -> dict[str, Any]:
    text = read_text_file(path)
    lines = text.splitlines()
    start = max(offset or 0, 0)
    end = None if limit in (None, 0) else start + max(limit, 0)
    selected = lines[start:end]
    numbered = '\n'.join(f'{index + 1}\t{line}' for index, line in enumerate(selected, start=start))
    truncated = end is not None and end < len(lines)
    return {
        'content': numbered,
        'rawContent': text,
        'totalLines': len(lines),
        'returnedLines': len(selected),
        'offset': start,
        'limit': limit,
        'truncated': truncated,
    }


def list_files(base: str) -> list[Path]:
    target = Path(base)
    if target.is_file():
        return [target]
    skip_dirs = {'.git', '.hg', '.svn', '.jj', '.sl', 'node_modules', '.state', '__pycache__'}
    files: list[Path] = []
    for current_root, dirs, filenames in os.walk(target):
        dirs[:] = [name for name in dirs if name not in skip_dirs and not name.startswith('.venv')]
        root_path = Path(current_root)
        for filename in filenames:
            files.append(root_path / filename)
    return files


def simple_glob(pattern: str, base: str, limit: int = 100) -> dict[str, Any]:
    base_path = Path(base)
    results: list[str] = []
    iterable = list_files(str(base_path))
    for file_path in iterable:
        relative = to_relative_path(str(file_path), str(base_path if base_path.is_dir() else base_path.parent))
        if fnmatch.fnmatch(file_path.name, pattern) or fnmatch.fnmatch(relative, pattern):
            results.append(relative)
            if len(results) >= limit:
                break
    truncated = len(results) >= limit and len(iterable) > len(results)
    return {'filenames': results, 'numFiles': len(results), 'truncated': truncated}


def simple_grep(pattern: str, path: str, glob_pattern: str | None = None, output_mode: str = 'files_with_matches', before: int = 0, after: int = 0, line_numbers: bool = True, ignore_case: bool = False, head_limit: int | None = 250, offset: int = 0, multiline: bool = False) -> dict[str, Any]:
    flags = re.MULTILINE
    if ignore_case:
        flags |= re.IGNORECASE
    if multiline:
        flags |= re.DOTALL
    regex = re.compile(pattern, flags)
    target = expand_path(path)
    base = Path(target)
    files = [base] if base.is_file() else list_files(target)
    entries: list[Any] = []
    filenames: list[str] = []
    for file_path in files:
        relative = to_relative_path(str(file_path), target if base.is_dir() else str(base.parent))
        if glob_pattern and not (fnmatch.fnmatch(file_path.name, glob_pattern) or fnmatch.fnmatch(relative, glob_pattern)):
            continue
        try:
            text = read_text_file(str(file_path))
        except OSError:
            continue
        if output_mode == 'files_with_matches':
            if regex.search(text):
                filenames.append(relative)
        elif output_mode == 'count':
            count = len(regex.findall(text))
            if count:
                entries.append({'file': relative, 'count': count})
                filenames.append(relative)
        else:
            lines = text.splitlines()
            matched_indexes = [idx for idx, line in enumerate(lines) if regex.search(line)]
            if not matched_indexes and multiline and regex.search(text):
                entries.append(f'{relative}:1:{regex.search(text).group(0)}')
                filenames.append(relative)
            for idx in matched_indexes:
                start = max(0, idx - before)
                end = min(len(lines), idx + after + 1)
                for line_index in range(start, end):
                    prefix = f'{relative}:{line_index + 1}:' if line_numbers else f'{relative}:'
                    entries.append(prefix + lines[line_index])
                filenames.append(relative)
    unique_filenames = list(dict.fromkeys(filenames))
    items: list[Any] = unique_filenames if output_mode == 'files_with_matches' else entries
    sliced = items[offset:] if offset else list(items)
    applied_limit = None
    if head_limit not in (None, 0) and len(sliced) > head_limit:
        sliced = sliced[:head_limit]
        applied_limit = head_limit
    result: dict[str, Any] = {
        'mode': output_mode,
        'filenames': unique_filenames,
        'numFiles': len(unique_filenames),
        'appliedLimit': applied_limit,
        'appliedOffset': offset or None,
    }
    if output_mode == 'count':
        result['counts'] = sliced
        result['numMatches'] = sum(item['count'] for item in entries)
    elif output_mode == 'content':
        result['content'] = '\n'.join(sliced)
        result['numLines'] = len(entries)
    else:
        result['filenames'] = sliced
    return result


def run_subprocess(command: str, cwd: str | None = None, timeout_ms: int = 30000, shell_type: str = 'shell', env: dict[str, str] | None = None) -> dict[str, Any]:
    start = now_ms()
    full_env = os.environ.copy()
    if env:
        full_env.update({str(key): str(value) for key, value in env.items()})
    if shell_type == 'powershell':
        executable = shutil.which('pwsh') or shutil.which('powershell') or 'powershell'
        argv = [executable, '-NoProfile', '-Command', command]
        shell = False
    elif shell_type == 'bash' and shutil.which('bash'):
        argv = [shutil.which('bash') or 'bash', '-lc', command]
        shell = False
    else:
        argv = command
        shell = True
    try:
        completed = subprocess.run(argv, cwd=cwd, env=full_env, shell=shell, capture_output=True, text=True, timeout=max(timeout_ms / 1000, 0.001))
        return {'command': command, 'cwd': cwd or os.getcwd(), 'code': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr, 'durationMs': now_ms() - start, 'timedOut': False}
    except subprocess.TimeoutExpired as exc:
        return {'command': command, 'cwd': cwd or os.getcwd(), 'code': -1, 'stdout': exc.stdout or '', 'stderr': exc.stderr or '', 'durationMs': now_ms() - start, 'timedOut': True}


def html_to_text(markup: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(markup)
    return parser.get_text()


def fetch_url_text(url: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={'User-Agent': 'python-port-tools/1.0'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        content_type = response.headers.get('Content-Type', 'text/plain')
        charset = response.headers.get_content_charset() or 'utf-8'
        text = body.decode(charset, errors='replace')
        normalized = html_to_text(text) if 'html' in content_type else text
        return {'url': response.geturl(), 'code': getattr(response, 'status', 200), 'codeText': getattr(response, 'reason', 'OK'), 'bytes': len(body), 'contentType': content_type, 'text': normalized, 'rawText': text}


def duckduckgo_search(query: str, allowed_domains: list[str] | None = None, blocked_domains: list[str] | None = None, max_results: int = 8) -> list[dict[str, str]]:
    encoded = urllib.parse.urlencode({'q': query})
    request = urllib.request.Request(f'https://html.duckduckgo.com/html/?{encoded}', headers={'User-Agent': 'python-port-tools/1.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        markup = response.read().decode('utf-8', errors='replace')
    patterns = [re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S), re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)]
    hits: list[dict[str, str]] = []
    for pattern in patterns:
        for href, title_html in pattern.findall(markup):
            parsed_href = html.unescape(href)
            if 'uddg=' in parsed_href:
                parsed_href = urllib.parse.unquote(parsed_href.split('uddg=', 1)[1].split('&', 1)[0])
            title = re.sub(r'<[^>]+>', '', title_html)
            title = html.unescape(title).strip()
            if not parsed_href.startswith('http'):
                continue
            host = urllib.parse.urlparse(parsed_href).hostname or ''
            if allowed_domains and not any(host.endswith(domain) for domain in allowed_domains):
                continue
            if blocked_domains and any(host.endswith(domain) for domain in blocked_domains):
                continue
            hits.append({'title': title or parsed_href, 'url': parsed_href})
            if len(hits) >= max_results:
                return hits
        if hits:
            break
    return hits


def summarize_input(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    preferred_keys = ['file_path', 'path', 'pattern', 'query', 'url', 'subject', 'setting', 'task_id', 'team_name', 'name', 'skill_name', 'command', 'description']
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)):
            parts.append(f'{key}={value}')
        if len(parts) >= 3:
            break
    return ', '.join(parts) if parts else None


def persist_config(app_state: AppState) -> None:
    _save_json(CONFIG_FILE, app_state.config)


def persist_settings(app_state: AppState) -> None:
    _save_json(SETTINGS_FILE, app_state.settings)


def persist_cron_tasks(app_state: AppState) -> None:
    _save_json(CRON_FILE, app_state.cron_tasks)


def persist_remote_triggers(app_state: AppState) -> None:
    _save_json(REMOTE_TRIGGER_FILE, app_state.remote_triggers)


def get_task_output_path(task_id: str) -> str:
    return str(TASK_OUTPUT_ROOT / f'{task_id}.txt')


def append_task_output(task_id: str, text: str) -> str:
    path = Path(get_task_output_path(task_id))
    ensure_directory(path.parent)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(text)
    return str(path)


def discover_tool_names() -> list[str]:
    names: list[str] = []
    for child in PACKAGE_ROOT.iterdir():
        if child.name.startswith('_') or child.name == '.state':
            continue
        if child.is_dir() and (child / '__init__.py').exists():
            names.append(child.name)
    return sorted(set(names))


def record_git_operation(operation: dict[str, Any]) -> dict[str, Any]:
    operations = _load_json(GIT_TRACKING_FILE, [])
    operations.append(operation)
    _save_json(GIT_TRACKING_FILE, operations)
    return operation


def list_git_operations() -> list[dict[str, Any]]:
    return _load_json(GIT_TRACKING_FILE, [])
