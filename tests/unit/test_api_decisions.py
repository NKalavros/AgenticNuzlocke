"""Actor choices and transport failures exercise the real HTTP serialization."""

import json

import httpx
import pytest

from nuzlocke.agents.jev_policy import accepts
from nuzlocke.llm.base import ProviderError
from nuzlocke.llm.decisions import APIDecisionProvider, DecisionError
from nuzlocke.llm.openai_provider import OpenAICompatibleProvider, OpenAIResponsesProvider

QUESTIONS = {
    "action": {"type": "choice", "criteria": {"fight": "attack", "run": "flee"}},
    "objective_done": {"type": "noul", "question": "is the objective done?"},
}


def client(answer, *, responses=False, capture=None, status=200):
    def handle(request):
        body = json.loads(request.content)
        if capture is not None:
            capture.append((request.url.path, body))
        payload = {
            "choices": [{"message": {"content": json.dumps(answer)}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 12},
        }
        if responses:
            payload = {
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(answer)}],
                    },
                ],
                "usage": {"total_tokens": 12},
            }
        return httpx.Response(status, json=payload)

    cls = OpenAIResponsesProvider if responses else OpenAICompatibleProvider
    return APIDecisionProvider(
        cls(
            base_url="https://example.test/v1",
            model="test",
            api_key="test-key",
            transport=httpx.MockTransport(handle),
            max_retries=1,
            structured_output="json_schema",
        )
    )


@pytest.mark.parametrize("responses", [True, False])
def test_choice_is_legal_without_synthetic_probabilities(responses):
    requests = []
    actor = client(
        {"action": "fight", "abstain": False, "objective_done": False},
        responses=responses,
        capture=requests,
    )
    try:
        result = actor.decide(state={"hp": 10}, questions=QUESTIONS, allowed={"fight"})
    finally:
        actor.close()
    assert accepts(result, 0.99)
    assert result.probabilities == {} and result.confidence == 0
    assert result.usage == {"total_tokens": 12}
    path, body = requests[0]
    assert path == ("/v1/responses" if responses else "/v1/chat/completions")
    schema = (
        body["text"]["format"]["schema"]
        if responses
        else body["response_format"]["json_schema"]["schema"]
    )
    assert schema["properties"]["action"]["enum"] == ["fight", None]
    assert "plan_stale" not in schema["properties"]


def test_abstention_does_not_pass_gate():
    actor = client({"action": None, "abstain": True, "objective_done": False})
    result = actor.decide(state={}, questions=QUESTIONS)
    assert result.abstain and not accepts(result, 0)
    actor.close()


@pytest.mark.parametrize(
    "answer",
    [
        {"action": "hack", "abstain": False, "objective_done": False},
        {"action": "fight", "abstain": True, "objective_done": False},
        {"action": "fight", "abstain": False, "objective_done": 0.9},
        {"action": "fight", "abstain": False},
        {
            "action": "fight",
            "abstain": False,
            "objective_done": False,
            "probabilities": {"fight": 1},
        },
    ],
)
def test_malformed_choice_rejected(answer):
    actor = client(answer)
    with pytest.raises(DecisionError):
        actor.decide(state={}, questions=QUESTIONS)
    actor.close()


def test_auth_failure_propagates_to_pause_handler():
    actor = client({}, status=401)
    with pytest.raises(ProviderError, match="HTTP 401"):
        actor.decide(state={}, questions=QUESTIONS)
    actor.close()


def test_retry_is_bounded_and_does_not_expose_remote_body():
    waits = []
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            429, headers={"retry-after": "200"}, json={"error": "secret-sentinel"}
        )

    api = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        model="test",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        sleep=waits.append,
        max_retries=2,
    )
    with pytest.raises(ProviderError) as err:
        api.structured(system="x", user="y", schema={})
    assert len(calls) == 2 and waits == [8]
    assert "secret-sentinel" not in str(err.value)
    api.close()
