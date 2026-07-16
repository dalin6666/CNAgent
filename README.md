# CNAgent

CNAgent 是一个基于 Python 的 Agent Runtime 项目，提供统一的模型调用、上下文管理、工具调用和权限控制能力。目前支持两种使用方式：

- CLI：在终端中进行交互式多轮对话。
- Web：通过浏览器登录后使用聊天页面。

## 环境要求

- Python 3.10 或更高版本（推荐 Python 3.12）。
- 一个 OpenAI 兼容模型服务的 API Key；也可以使用内置的 `mock` Provider 做本地无 Key 运行。

## 安装

以下命令均在项目根目录执行（即包含 `requirements.txt` 的目录）：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

如果 PowerShell 禁止激活脚本，可以直接使用虚拟环境中的 Python：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 配置

Web 会自动读取项目根目录的 `.env` 文件。首次配置时复制示例文件：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

编辑 `.env`，至少设置一个不少于 32 个字符的 `SESSION_SECRET`。可以用下面的命令生成随机值，然后将输出复制到 `.env`：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

默认使用 DeepSeek：

```dotenv
SESSION_SECRET=请替换为随机字符串
AGENT_PROVIDER=deepseek
AGENT_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=你的-api-key
```

也支持以下 Provider：

| Provider | 必填 Key | 默认模型 |
| --- | --- | --- |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
| `openai` | `OPENAI_API_KEY` | `gpt-4.1-mini` |
| `qwen` | `DASHSCOPE_API_KEY` | `qwen-plus` |
| `mock` | 无 | 内置模拟模型 |

Provider 的完整配置和可选的 Base URL 见 [AGENT_PROVIDER_SETUP.md](AGENT_PROVIDER_SETUP.md)。

> CLI 不会自动加载 `.env`。使用 CLI 时，请在当前 PowerShell 会话中设置对应的环境变量，或先将变量导入到当前会话。

## 运行方式一：CLI

### 使用真实模型

在当前 PowerShell 会话中设置 Provider 和 API Key：

```powershell
$env:AGENT_PROVIDER = "deepseek"
$env:DEEPSEEK_API_KEY = "你的-api-key"
$env:AGENT_MODEL = "deepseek-v4-flash"
python examples\run_cli_agent.py
```

也可以通过参数覆盖 Provider、模型和工作目录：

```powershell
python examples\run_cli_agent.py `
  --provider deepseek `
  --model deepseek-v4-flash `
  --workdir .
```

### 不使用 API Key 本地运行

```powershell
python examples\run_cli_agent.py --provider mock
```

进入 CLI 后，输入问题即可对话。内置命令如下：

```text
/help       显示帮助
/new        开始新会话
/status     查看会话和 Token 用量
/verbose    切换详细运行事件
/exit       退出
```

### CLI 参数

```text
--provider   mock、openai、deepseek 或 qwen
--model      覆盖默认模型名称
--workdir    暴露给 Runtime 工具的工作目录
--verbose    显示更详细的 Runtime 事件和工具参数
```

## 运行方式二：Web

Web 版本使用 FastAPI、Uvicorn 和 SQLite，默认监听 `127.0.0.1:8000`。

### 1. 配置环境变量

确认 `.env` 中已经设置：

```dotenv
SESSION_SECRET=不少于32个字符的随机字符串
DATABASE_URL=sqlite:///./cnagent.db
AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的-api-key
```

如果只想验证页面和登录流程，不调用真实模型，可以将 Provider 改为：

```dotenv
AGENT_PROVIDER=mock
```

### 2. 创建登录用户

首次启动前执行：

```powershell
python scripts\create_user.py admin
```

根据提示输入至少 8 位密码。用户名已存在时，脚本会退出并保留原用户。

### 3. 启动 Web 服务

```powershell
python -m uvicorn web.app:app --reload --host 127.0.0.1 --port 8000
```

启动后打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)，使用刚创建的账号登录。

健康检查地址：

```text
http://127.0.0.1:8000/health
```

返回 `{"status":"ok"}` 即表示 Web 服务已启动。

### 4. 停止服务

在运行 Uvicorn 的终端按 `Ctrl+C`。

### Web 运行说明

- 开发环境使用 `--reload`，代码变更后会自动重启；生产环境不建议使用该参数。
- Web 只开放 `read` 和 `lookup` 工具组，CLI 默认开放完整工具组。
- 生产环境应使用新的随机 `SESSION_SECRET`，并通过 HTTPS 配置安全 Cookie。
- 默认数据库文件为项目根目录的 `cnagent.db`，可通过 `DATABASE_URL` 替换为其他 SQLAlchemy 数据库地址。

## 常见问题

### `SESSION_SECRET must be set...`

Web 启动时未读取到有效的 `SESSION_SECRET`。请确认 `.env` 位于项目根目录，且值长度至少为 32 个字符。

### `deepseek requires DEEPSEEK_API_KEY`

当前 Provider 需要 API Key。请在 `.env`（Web）或当前 PowerShell 会话（CLI）中设置对应变量；只做本地页面验证时可改用 `AGENT_PROVIDER=mock`。

### 登录后聊天返回 503

通常是模型 Provider 配置缺失或 API Key 无效。检查 `.env` 中的 Provider、模型和 API Key，并重启 Uvicorn。

## 运行测试

```powershell
python -m pytest -q
```

## 相关文档

- [Agent Provider 配置](AGENT_PROVIDER_SETUP.md)
- [Runtime 架构](AGENT_RUNTIME_ARCHITECTURE.md)
- [Runtime 工具目录](AGENT_RUNTIME_TOOL_CATALOG.md)
- [登录功能要求](docs/LOGIN_REQUIREMENTS.md)
- [Agent Runtime 包说明](agent_runtime/README.md)
