"""The live LLM call requests structured output, with a schema the API accepts."""

import json

from riskops.providers.anthropic_live import AnthropicProvider, api_json_schema
from riskops.rules import evaluate
from tests.test_rules_and_controls import make_intake


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_schema_has_only_supported_keywords_and_closed_objects():
    schema = api_json_schema()
    for node in _walk(schema):
        assert not {"minLength", "maxLength", "minItems", "maxItems", "pattern"} & set(node)
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node.get("properties", {}))


def test_request_carries_output_format():
    seen = {}

    class _Msg:
        stop_reason, usage = "end_turn", None
        content = [type("B", (), {"type": "text", "text": json.dumps({"summary": "x"})})()]

    class _Client:
        def __init__(self):
            self.messages = type("M", (), {"create": lambda _s, **kw: seen.update(kw) or _Msg()})()

    intake = make_intake()
    AnthropicProvider(model="claude-opus-5", client=_Client()).assess(intake, "prompt-v3", evaluate(intake, "rules-v2.1"))
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert seen["max_tokens"] >= 16000
