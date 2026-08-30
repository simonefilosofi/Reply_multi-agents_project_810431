"""Single construction point for the DeepSeek chat model behind every LLM-backed agent and tool. Pins the model and turns the provider's reasoning mode off, so that temperature is honoured and a run stays reproducible. Schema-constrained answers go through tool calling, which the provider occasionally serialises as malformed JSON on a long free-text field; that answer is unrecoverable but detectable, so the same request is asked again in the provider's JSON mode, whose constrained decoding cannot emit invalid JSON, with the schema carried in the prompt because DeepSeek implements no schema-typed response format. An answer neither path can produce raises rather than travelling on as a None. Consumed wherever an agent needs a schema-constrained answer."""
from __future__ import annotations

import json
from typing import TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, convert_to_messages
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_deepseek import ChatDeepSeek
from pydantic import BaseModel, ValidationError

MODEL = "deepseek-v4-pro"

_MAX_RETRIES = 3
_REQUEST_TIMEOUT_SECONDS = 300.0
_REASONING_DISABLED = {"thinking": {"type": "disabled"}}
_JSON_OBJECT = {"type": "json_object"}
_SCHEMA_INSTRUCTION = (
    "Answer with a single json object and nothing else. It must validate against this JSON "
    "Schema:\n{schema}"
)
_UNUSABLE = "{model} produced no answer matching {schema} through tool calling or JSON mode."

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class EmptyModelResponse(RuntimeError):
    """Raised when neither decoding path yields an answer the schema accepts. A caller that can
    proceed without the answer catches it; anywhere else it stops the run naming its own cause."""


def structured_model(
    schema: type[SchemaT], max_tokens: int | None = None
) -> Runnable[LanguageModelInput, SchemaT]:
    """A chain answering a chat-message list with an instance of schema."""
    model = ChatDeepSeek(
        model=MODEL,
        temperature=0,
        max_tokens=max_tokens,
        max_retries=_MAX_RETRIES,
        timeout=_REQUEST_TIMEOUT_SECONDS,
        extra_body=_REASONING_DISABLED,
    )
    by_tool_call = model.with_structured_output(schema)
    by_json_object = model.bind(response_format=_JSON_OBJECT)
    return RunnableLambda(
        lambda messages: _answer(schema, by_tool_call, by_json_object, messages)
    )


def _answer(
    schema: type[SchemaT],
    by_tool_call: Runnable,
    by_json_object: Runnable,
    messages: LanguageModelInput,
) -> SchemaT:
    try:
        answer = by_tool_call.invoke(messages)
    except (OutputParserException, ValidationError):
        answer = None
    if answer is not None:
        return answer
    try:
        return _from_json_object(schema, by_json_object, messages)
    except (OutputParserException, ValidationError, ValueError) as error:
        raise EmptyModelResponse(
            _UNUSABLE.format(model=MODEL, schema=schema.__name__)
        ) from error


def _from_json_object(
    schema: type[SchemaT], by_json_object: Runnable, messages: LanguageModelInput
) -> SchemaT:
    instruction = SystemMessage(
        _SCHEMA_INSTRUCTION.format(schema=json.dumps(schema.model_json_schema()))
    )
    reply = by_json_object.invoke([*_as_messages(messages), instruction])
    return schema.model_validate_json(reply.text)


def _as_messages(messages: LanguageModelInput) -> list[BaseMessage]:
    if isinstance(messages, PromptValue):
        return messages.to_messages()
    if isinstance(messages, str):
        return [HumanMessage(messages)]
    return convert_to_messages(messages)
