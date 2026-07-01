# llm_inspector

`llm_inspector` is a zero-config, local observability dashboard for LLM API calls. It monkey-patches the OpenAI, Anthropic, and Google Generative AI SDKs to capture every request and response — model, latency, token counts, cost, prompt, completion — into a local SQLite database with no code changes beyond a two-line setup. A built-in web dashboard lets you browse traces, filter by provider/model/status, replay any call with a different model or edited prompt, diff responses across versions, and run multi-model comparisons side by side.

## Installation

```bash
git clone https://github.com/your-username/llm_inspector.git
cd llm_inspector
pip install -e .
```

Copy `.env.example` to `.env` and add your API keys:

```bash
OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
```

## Usage

Add two lines to the top of any script that uses an LLM SDK:

```python
import llm_inspector
llm_inspector.auto()   # patches SDKs + starts background writer

# everything below is unchanged — llm_inspector captures it automatically
import openai
client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
)
```

`auto()` is **idempotent** — safe to call multiple times, from any import order.

## Configuration

You can configure `llm_inspector` using either environment variables or by explicitly passing credentials in your code.

### Pattern 1: Environment Variables (Default)
Set environment variables directly or place them in a `.env` file in your project root:
```bash
OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
```

### Pattern 2: Explicit Programmatic Config
For environments where environment variables aren't preferred (e.g. CI/CD, container orchestrators, or code-injected secrets), configure the API keys explicitly:
```python
import llm_inspector

llm_inspector.configure(
    openai_api_key="sk-...",
    deepseek_api_key="sk-...",
    anthropic_api_key="sk-ant-...",
    gemini_api_key="AIza...",
)
llm_inspector.auto()
```

> [!NOTE]
> `configure()` only affects prompt replay execution and the dashboard's provider availability checks. It does not affect active trace capture, which automatically inherits the configuration of the SDK clients you initialize in your application code.

## Dashboard

```bash
llm-inspector ui        # opens http://localhost:8765
```

## CLI Commands

| Command | Description |
|---|---|
| `llm-inspector ui` | Start the local dashboard server (default port 8765) |
| `llm-inspector list` | Print the last N traces to stdout |
| `llm-inspector show <id>` | Print full detail for a single trace |
| `llm-inspector clear` | Delete all traces from the local database |

## Provider Support

| Provider | Status |
|---|---|
| **OpenAI** (and any OpenAI-compatible endpoint) | ✅ Fully tested |
| **DeepSeek** (via OpenAI SDK with custom base URL) | ✅ Fully tested |
| **OpenAI-Compatible Providers** | ✅ Automatically detected via base_url (Note: As of June 27, 2026, historical pre-fix traces captured before this update will remain mislabeled as 'openai') |
| **Anthropic** | ⚠️ Patch implemented, not yet verified against a live successful call |
| **Google Gemini** | ✅ Fully tested |

> Anthropic patches follow the same interception pattern as OpenAI but have not been validated end-to-end with a real API response. If you test them, check that `response_json` and token counts are populated correctly in the dashboard.

## Data

Traces are stored in `llm_inspector_data/traces.db` (SQLite) relative to the working directory where the server or your script is started. This directory is created automatically on first use.

Synthetic/demo data used in tests is always tagged 'demo'. To identify or exclude it at any time:
`SELECT * FROM traces WHERE tags LIKE '%demo%';`

To reset: `llm-inspector clear` or `rm llm_inspector_data/traces.db`.

## Tests

```bash
# No API key required — uses synthetic events
python tests/test_pipeline.py

# Requires DEEPSEEK_API_KEY (or exits cleanly with a skip message)
python tests/test_openai_patch.py
python tests/test_import_order.py
python tests/test_multi_provider.py

# Docker volume-persistence smoke test
docker build -f docker/Dockerfile -t llm_inspector .
bash docker/docker_test.sh
```
