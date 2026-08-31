"""Pins what happens when a decoding attempt is cut off before it produces a parseable answer.
A run over trasferimentiPersonale died in the Unified agent because the model reached its output
limit mid-object and the provider raised LengthFinishReasonError, which neither decoding path
caught: the whole pipeline aborted over one oversized reply. A truncated answer is the same
situation as an unparseable one - this attempt yielded nothing usable - so it belongs with the
failures the second path is there to absorb, and a caller that can proceed without the answer
should still see EmptyModelResponse rather than a provider exception."""
from __future__ import annotations

import pytest
from openai import ContentFilterFinishReasonError, LengthFinishReasonError
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from utils.llm import EmptyModelResponse, _answer


class Answer(BaseModel):
    verdict: str


class Raises:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def invoke(self, messages):
        raise self.error


class Returns:
    def __init__(self, value) -> None:
        self.value = value
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return self.value


def truncated(finish_reason: str = "length") -> ChatCompletion:
    return ChatCompletion(
        id="x", model="m", object="chat.completion", created=0,
        choices=[{"index": 0, "finish_reason": finish_reason,
                  "message": {"role": "assistant", "content": '{"verdict":'}}],
    )


class Reply:
    def __init__(self, text: str) -> None:
        self.text = text


def test_a_truncated_tool_call_falls_through_to_json_mode():
    by_tool_call = Raises(LengthFinishReasonError(completion=truncated()))
    by_json_object = Returns(Reply('{"verdict": "ok"}'))

    answer = _answer(Answer, by_tool_call, by_json_object, [("human", "go")])

    assert answer.verdict == "ok"
    assert by_json_object.calls == 1


def test_a_content_filtered_tool_call_falls_through_to_json_mode():
    by_tool_call = Raises(ContentFilterFinishReasonError())
    by_json_object = Returns(Reply('{"verdict": "ok"}'))

    answer = _answer(Answer, by_tool_call, by_json_object, [("human", "go")])

    assert answer.verdict == "ok"


def test_a_truncation_on_both_paths_raises_the_recoverable_error():
    by_tool_call = Raises(LengthFinishReasonError(completion=truncated()))
    by_json_object = Raises(LengthFinishReasonError(completion=truncated()))

    with pytest.raises(EmptyModelResponse):
        _answer(Answer, by_tool_call, by_json_object, [("human", "go")])


def test_an_unrelated_provider_error_is_not_swallowed():
    by_tool_call = Raises(RuntimeError("connection reset"))
    by_json_object = Returns(Reply('{"verdict": "ok"}'))

    with pytest.raises(RuntimeError):
        _answer(Answer, by_tool_call, by_json_object, [("human", "go")])
