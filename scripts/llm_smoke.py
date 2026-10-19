"""One chat call and one embedding against the real gateway (manual check for M2).

Usage: python scripts/llm_smoke.py   (reads GC_* settings / .env)
"""

from __future__ import annotations

import sys

from pydantic import BaseModel

from genie_copilot.config import get_settings
from genie_copilot.db.models import LLMCall
from genie_copilot.llm.base import LLMError
from genie_copilot.llm.client import GatewayLLMClient


class SmokeAnswer(BaseModel):
    ok: bool
    word: str


def print_call(call: LLMCall) -> None:
    print(
        f"  {call.purpose:<6} model={call.model} status={call.status} "
        f"latency={call.latency_ms}ms tokens={call.input_tokens}/{call.output_tokens} "
        f"cost={call.cost_usd}" + (f" error={call.error}" if call.error else "")
    )


def main() -> int:
    settings = get_settings()
    print(f"gateway={settings.llm_base_url} token_url={settings.token_url}")
    client = GatewayLLMClient(settings, call_log=print_call)
    try:
        answer = client.complete_json(
            purpose="smoke",
            prompt_name="smoke",
            variables={"word": "genie"},
            schema=SmokeAnswer,
        )
        print(f"chat ok: {answer.model_dump()}")
        vectors = client.embed(["hello genie"])
        print(f"embedding ok: dim={len(vectors[0])}")
    except LLMError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
