"""One bounded ADK classification turn with a zero-network scripted CI adapter.

Like the restaurant agent, this uses LlmAgent, Runner and BaseLlm. The durable
reservation lives in CustomerService.prepare; this module has no SQL or business
tools. A model may advise, but only the existing deterministic refund policy acts.
"""

import asyncio
import json
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.run_config import RunConfig
from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.oauth2.credentials import Credentials
from opentelemetry.trace import Span

from delivery.adk_offline import OfflineCustomerModel as OfflineCustomerModel
from delivery.config import Settings
from delivery.customer_service import (
    MAX_OUTPUT,
    RESERVED_TOKENS,
    SYSTEM,
    Advice,
    complaint_prompt,
)
from delivery.telemetry import mark_error, record_model_usage, start_span, trace_span


def create_customer_model(config: Settings) -> BaseLlm:
    """Select only the explicit provider; never fall through to paid inference."""
    if config.llm_provider == "offline":
        return OfflineCustomerModel()
    options: dict[str, Any] = {
        "http_options": types.HttpOptions(
            timeout=15000, retry_options=types.HttpRetryOptions(attempts=1)
        )
    }
    if config.llm_provider == "vertex":
        credentials = None
        if config.google_credentials_json:
            credentials = Credentials.from_authorized_user_info(
                json.loads(config.google_credentials_json),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        options.update(
            vertexai=True,
            project=config.google_cloud_project,
            location=config.google_cloud_location,
            credentials=credentials,
        )
    elif config.llm_provider == "gemini":
        options.update(vertexai=False, api_key=config.gemini_api_key)
    else:
        raise ValueError("LLM provider is disabled or unsupported")
    return Gemini(
        model=config.llm_model,
        api_version="v1" if config.llm_provider == "vertex" else None,
        client_kwargs=options,
        retry_options=types.HttpRetryOptions(attempts=1),
    )


class CustomerAdviceTurn:
    """One reserved model call, without tools, history, retries or follow-up turns."""

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.calls = 0
        self.advice: Advice | None = None
        self.usage: types.GenerateContentResponseUsageMetadata | None = None
        self.model_span: Span | None = None

    def before_model(self, callback_context: CallbackContext, llm_request: LlmRequest) -> None:
        del callback_context
        if self.calls:
            raise PermissionError("A customer reservation permits exactly one model call")
        if llm_request.tools_dict or llm_request.config.tools:
            raise PermissionError("Customer classification cannot invoke tools")
        # Bound the complete ADK prompt/config, not just complaint text. Counting
        # UTF-8 bytes conservatively accommodates schema and instruction overhead.
        config_body = llm_request.config.model_dump(
            mode="json", exclude_none=True, exclude={"response_schema"}
        )
        config_body["response_schema"] = Advice.model_json_schema()
        body = json.dumps(
            {
                "contents": [
                    content.model_dump(mode="json", exclude_none=True)
                    for content in llm_request.contents
                ],
                "config": config_body,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        if len(body) > RESERVED_TOKENS - MAX_OUTPUT:
            raise ValueError("ADK request exceeds its existing input token reservation")
        self.calls += 1
        self.model_span = start_span(
            "agent.model",
            {
                "delivery.agent": "customer_service",
                "gen_ai.system": self.config.llm_provider,
                "gen_ai.request.model": "offline"
                if self.config.llm_provider == "offline"
                else self.config.llm_model,
            },
        )

    def after_model(self, callback_context: CallbackContext, llm_response: LlmResponse) -> None:
        if llm_response.partial:
            return
        try:
            if self.model_span is not None:
                offline = self.config.llm_provider == "offline"
                record_model_usage(
                    self.model_span,
                    llm_response.usage_metadata,
                    0.0 if offline else self.config.llm_input_usd_per_million,
                    0.0 if offline else self.config.llm_output_usd_per_million,
                )
            self._after_model(callback_context, llm_response)
            if self.model_span is not None:
                self.model_span.set_attribute("delivery.success", True)
        except BaseException as exc:
            if self.model_span is not None:
                mark_error(self.model_span, exc)
            raise
        finally:
            if self.model_span is not None:
                self.model_span.end()
                self.model_span = None

    def _after_model(self, callback_context: CallbackContext, llm_response: LlmResponse) -> None:
        del callback_context
        if llm_response.partial:
            return
        if self.advice is not None:
            raise PermissionError("A customer reservation permits exactly one model response")
        if llm_response.error_code or not llm_response.content:
            raise ValueError("Customer model did not return an advice response")
        parts = llm_response.content.parts or []
        if any(part.function_call for part in parts):
            raise PermissionError("Customer classification cannot invoke tools")
        text = "".join(part.text or "" for part in parts if not part.thought)
        self.advice = Advice.model_validate_json(text)
        self.usage = llm_response.usage_metadata

    def build(self, model: BaseLlm) -> LlmAgent:
        return LlmAgent(
            name="customer_service",
            model=model,
            instruction=SYSTEM,
            output_schema=Advice,
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
            before_model_callback=self.before_model,
            after_model_callback=self.after_model,
            generate_content_config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=MAX_OUTPUT,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

    async def run(self, model: BaseLlm, complaint: dict[str, Any]) -> tuple[Advice, int, float]:
        with trace_span(
            "agent.customer_service", attributes={"delivery.agent": "customer_service"}
        ):
            try:
                return await self._run(model, complaint)
            except BaseException as exc:
                if self.model_span is not None:
                    mark_error(self.model_span, exc)
                raise
            finally:
                if self.model_span is not None:
                    self.model_span.end()
                    self.model_span = None

    async def _run(self, model: BaseLlm, complaint: dict[str, Any]) -> tuple[Advice, int, float]:
        service = InMemorySessionService()
        session = await service.create_session(app_name="bakiano_customer", user_id="customer")
        runner = Runner(
            app_name="bakiano_customer", agent=self.build(model), session_service=service
        )
        # Capture the per-loop client here so it can be closed on success, timeout,
        # schema rejection and cancellation, without creating a client at cleanup.
        client = model.api_client if isinstance(model, Gemini) else None
        try:
            async for _ in runner.run_async(
                user_id="customer",
                session_id=session.id,
                new_message=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=complaint_prompt(complaint["text"], complaint["order_status"])
                        )
                    ],
                ),
                run_config=RunConfig(max_llm_calls=1),
            ):
                pass
        finally:
            try:
                await runner.close()
            finally:
                if client is not None:
                    try:
                        await client.aio.aclose()
                    finally:
                        client.close()
        if self.advice is None:
            raise ValueError("Customer model did not return validated advice")
        usage = self.usage
        input_tokens = (usage.prompt_token_count or 0) if usage else RESERVED_TOKENS - MAX_OUTPUT
        output_tokens = (usage.candidates_token_count or 0) if usage else MAX_OUTPUT
        thoughts = (usage.thoughts_token_count or 0) if usage else 0
        cost = (
            input_tokens * self.config.llm_input_usd_per_million
            + (output_tokens + thoughts) * self.config.llm_output_usd_per_million
        ) / 1_000_000
        return self.advice, input_tokens + output_tokens + thoughts, cost


async def run_customer_advice(
    config: Settings, complaint: dict[str, Any]
) -> tuple[Advice, int, float]:
    """Execute after the caller has durably reserved its single paid request."""
    return await asyncio.wait_for(
        CustomerAdviceTurn(config).run(create_customer_model(config), complaint), timeout=15
    )
