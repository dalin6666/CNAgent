from __future__ import annotations

import time

from .._runtime import SimpleTool


def _call(duration_seconds: float = 1.0, **_kwargs):
    start = time.time()
    time.sleep(max(0.0, float(duration_seconds)))
    elapsed = time.time() - start
    return {'data': {'sleptSeconds': elapsed}}


SleepTool = SimpleTool(
    name='Sleep',
    description_text='Pause execution for a short amount of time.',
    prompt_text='Use sparingly when a workflow needs a simple delay.',
    call_handler=_call,
    input_schema={'duration_seconds': 'how long to sleep'},
    output_schema={'sleptSeconds': 'actual sleep duration'},
    user_facing_name='Sleep',
)
