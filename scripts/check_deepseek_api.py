from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("AGENT_MODEL", "deepseek-v4-flash")

    print("has_key:", bool(api_key), "key_len:", len(api_key or ""))
    print("base_url:", base_url)
    print("model:", model)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
        "max_tokens": 64,
    }

    with httpx.Client(timeout=30) as client:
        models_response = client.get(f"{base_url}/models", headers=headers)
        print("models_status:", models_response.status_code)
        if not models_response.is_success:
            print("models_error:", models_response.text[:500])

        chat_response = client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        print("chat_status:", chat_response.status_code)
        if chat_response.is_success:
            body = chat_response.json()
            choice = (body.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            print("chat_ok:", bool(body.get("choices")))
            print("reply_preview:", str(message.get("content", ""))[:120])
            return 0

        print("chat_error:", chat_response.text[:1000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
