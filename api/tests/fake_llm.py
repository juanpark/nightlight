"""A scripted stand-in for Gemini, so turn tests run without network or cost."""

from typing import AsyncGenerator, ClassVar

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class FakeLlm(BaseLlm):
    """Plays a fixed script: read the Pi, propose rotate_logs (unless continuation), then answer in text."""

    model: str = "fake-model"
    log: ClassVar[list] = []
    behavior: ClassVar = None  # optional async generator fn(llm_request, stream) replacing the default script

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["fake-model"]

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        tools = sorted(llm_request.tools_dict)
        FakeLlm.log.append({"tools": tools, "contents": len(llm_request.contents),
                            "text": " ".join(p.text or "" for c in llm_request.contents for p in (c.parts or []))})
        if FakeLlm.behavior:
            async for r in FakeLlm.behavior(llm_request, stream):
                yield r
            return
        done = [p.function_response.name for c in llm_request.contents for p in (c.parts or [])
                if p.function_response]
        usage = types.GenerateContentResponseUsageMetadata(prompt_token_count=1000, candidates_token_count=40,
                                                           thoughts_token_count=60, total_token_count=1100)
        if not tools:  # the follow-up after an approval has no tools: it just narrates the update
            text = "Done. The Pi is fine now."
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]), partial=False,
                              usage_metadata=usage, turn_complete=True)
            return
        if "get_device" not in done:
            part = types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"}))
        elif "rotate_logs" in tools and "rotate_logs" not in done:
            part = types.Part(function_call=types.FunctionCall(name="rotate_logs", args={"device_id": "pi-1"}))
        else:
            text = "Your Pi's disk is nearly full of old logs." if "rotate_logs" in tools else "Done. The Pi is fine now."
            if stream:
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text[:10])]), partial=True)
            part = types.Part(text=text)
        yield LlmResponse(content=types.Content(role="model", parts=[part]), partial=False, usage_metadata=usage,
                          turn_complete=True)


def reply(*chunks, usage=True):
    """Behavior helper: stream text chunks, then the aggregated final response."""
    async def gen(llm_request, stream):
        for ch in chunks:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=ch)]), partial=True)
        u = types.GenerateContentResponseUsageMetadata(prompt_token_count=500, candidates_token_count=20,
                                                       total_token_count=520) if usage else None
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="".join(chunks))]),
                          partial=False, usage_metadata=u, turn_complete=True)
    return gen
