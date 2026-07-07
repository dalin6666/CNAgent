# Real Provider Setup

This runtime can now call real models through an OpenAI-compatible Chat Completions API.

## Supported Provider Presets

- `openai_provider_config(...)`
- `deepseek_provider_config(...)`
- `qwen_provider_config(...)`

## Environment Variables

### OpenAI / GPT

- `AGENT_PROVIDER=openai`
- `OPENAI_API_KEY=...`
- `AGENT_MODEL=gpt-4.1-mini`
- Optional: `OPENAI_BASE_URL=https://api.openai.com/v1`

### DeepSeek

- `AGENT_PROVIDER=deepseek`
- `DEEPSEEK_API_KEY=...`
- `AGENT_MODEL=deepseek-v4-flash`
- Optional: `DEEPSEEK_BASE_URL=https://api.deepseek.com`

### Qwen

- `AGENT_PROVIDER=qwen`
- `DASHSCOPE_API_KEY=...`
- `AGENT_MODEL=qwen-plus`
- Optional:
  `QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`

## Example

```powershell
$env:AGENT_PROVIDER = "deepseek"
$env:DEEPSEEK_API_KEY = "sk-..."
$env:AGENT_MODEL = "deepseek-v4-flash"
python examples\run_api_agent.py
```

## Notes

- All three presets use the same runtime and the same tool calling path.
- The provider implementation lives in `agent_runtime/providers/openai_compatible.py`.
- `Qwen` is configured to disable streaming when tools are present, because its OpenAI-compatible interface may require non-stream tool calling for compatibility.
