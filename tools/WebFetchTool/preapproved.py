from __future__ import annotations

PREAPPROVED_HOSTS = {'docs.python.org', 'developer.mozilla.org', 'platform.openai.com'}


def isPreapprovedHost(hostname: str, path: str = '') -> bool:
    del path
    return hostname in PREAPPROVED_HOSTS
