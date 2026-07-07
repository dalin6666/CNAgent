from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .._runtime import SimpleTool, ToolUseContext, expand_path, write_text_file


def _new_cell(cell_type: str, source: str, cell_id: str | None = None) -> dict[str, Any]:
    cell = {'cell_type': cell_type, 'id': cell_id or f'cell-{abs(hash(source)) % 10_000_000}', 'metadata': {}, 'source': source.splitlines(keepends=True)}
    if cell_type == 'code':
        cell['execution_count'] = None
        cell['outputs'] = []
    return cell


def _call(notebook_path: str, cell_id: str | None = None, new_source: str = '', cell_type: str | None = None, edit_mode: str = 'replace', toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    resolved = expand_path(notebook_path, toolUseContext.options.cwd if toolUseContext else None)
    path = Path(resolved)
    original_text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else json.dumps({'cells': [], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5})
    notebook = json.loads(original_text)
    cells = notebook.setdefault('cells', [])
    index = next((i for i, cell in enumerate(cells) if cell.get('id') == cell_id), None)
    selected_type = cell_type or (cells[index].get('cell_type') if index is not None else 'code') or 'code'
    if edit_mode == 'insert':
        insert_at = 0 if index is None else index + 1
        cell = _new_cell(selected_type, new_source, cell_id)
        cells.insert(insert_at, cell)
    elif edit_mode == 'delete':
        if index is None:
            raise ValueError('Cannot delete a notebook cell without a valid cell_id.')
        cell = cells.pop(index)
        new_source = ''.join(cell.get('source', []))
        selected_type = cell.get('cell_type', selected_type)
    else:
        if index is None:
            if not cells:
                cell = _new_cell(selected_type, new_source, cell_id)
                cells.append(cell)
                index = 0
            else:
                index = 0
        cells[index]['cell_type'] = selected_type
        cells[index]['source'] = new_source.splitlines(keepends=True)
        cell = cells[index]
        cell.setdefault('id', cell_id or cell.get('id') or f'cell-{index + 1}')
        if selected_type == 'code':
            cell.setdefault('outputs', [])
            cell.setdefault('execution_count', None)
    updated_text = json.dumps(notebook, indent=2, ensure_ascii=False)
    write_text_file(resolved, updated_text)
    return {'data': {'notebook_path': resolved, 'cell_id': cell.get('id'), 'cell_type': selected_type, 'edit_mode': edit_mode, 'new_source': new_source, 'original_file': original_text, 'updated_file': updated_text, 'language': notebook.get('metadata', {}).get('language_info', {}).get('name', 'python')}}


NotebookEditTool = SimpleTool(
    name='NotebookEdit',
    description_text='Edit Jupyter notebook cells in a local .ipynb file.',
    prompt_text='Use `edit_mode` of `replace`, `insert`, or `delete` along with a target `cell_id` when needed.',
    call_handler=_call,
    input_schema={'notebook_path': 'path to notebook', 'cell_id': 'optional cell id', 'new_source': 'cell contents'},
    output_schema={'updated_file': 'serialized notebook after the change'},
    user_facing_name='Notebook Edit',
)
