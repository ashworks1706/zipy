"""The LiteLLM chat client, the embedder, and the LangFuse sink. Nothing here touches a network."""

from dataclasses import dataclass, field
from typing import Any

import litellm
import pytest
from litellm.exceptions import AuthenticationError, BadRequestError, RateLimitError, Timeout
from pydantic import SecretStr

from engine.core.config import ModelRole, Telemetry
from engine.core.doubles import MemoryTrace
from engine.core.types import ChatMessage, ModelError, Speaker, ToolCall
from engine.llm.client import MASK, LiteLlmChat, from_wire, to_wire, wire_name
from engine.llm.embeddings import LiteLlmEmbedder
from engine.llm.tracing import LangfuseTrace

KEY = "sk-super-secret-key"


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction
    type: str = "function"


@dataclass
class FakeMessage:
    content: str | None = None
    tool_calls: list[FakeToolCall] = field(default_factory=list)


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class FakeResponse:
    choices: list[FakeChoice]
    usage: FakeUsage = field(default_factory=FakeUsage)
    _hidden_params: dict[str, Any] = field(default_factory=lambda: {"response_cost": 0.0})


def text_response(text: str, **usage: int) -> FakeResponse:
    return FakeResponse(choices=[FakeChoice(FakeMessage(content=text))], usage=FakeUsage(**usage))


def role(**over: Any) -> ModelRole:
    values: dict[str, Any] = {
        "model": "openrouter/qwen/qwen3-32b",
        "api_key": SecretStr(KEY),
        "temperature": 0.3,
        "max_tokens": 512,
        "timeout_secs": 30.0,
    }
    values.update(over)
    return ModelRole(**values)


class Recorder:
    """Stands in for litellm.acompletion and litellm.aembedding."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result

    @property
    def sent(self) -> dict[str, Any]:
        return self.calls[-1]


def chat(monkeypatch, recorder: Recorder, **over: Any) -> LiteLlmChat:
    monkeypatch.setattr(litellm, "acompletion", recorder)
    return LiteLlmChat(role(**over), MemoryTrace())


SCHEMA = {
    "type": "function",
    "function": {
        "name": "calendar__create_event",
        "description": "Create an event.",
        "parameters": {"type": "object", "properties": {}},
    },
}


# ---------------------------------------------------------------- what goes out


async def test_request_carries_the_role_and_the_messages(monkeypatch, ctx):
    recorder = Recorder(text_response("hi"))
    client = chat(monkeypatch, recorder, api_base="https://proxy.invalid/v1", fallbacks=["b/c"])

    await client.complete(
        ctx,
        [
            ChatMessage(speaker=Speaker.SYSTEM, content="you are Zipy"),
            ChatMessage(speaker=Speaker.USER, content="when is the meeting"),
        ],
        [SCHEMA],
    )

    sent = recorder.sent
    assert sent["model"] == "openrouter/qwen/qwen3-32b"
    assert sent["temperature"] == 0.3
    assert sent["max_tokens"] == 512
    assert sent["timeout"] == 30.0
    assert sent["api_key"] == KEY
    assert sent["api_base"] == "https://proxy.invalid/v1"
    assert sent["fallbacks"] == ["b/c"]
    assert sent["tools"] == [SCHEMA]
    assert sent["tool_choice"] == "auto"
    assert sent["messages"] == [
        {"role": "system", "content": "you are Zipy"},
        {"role": "user", "content": "when is the meeting"},
    ]


async def test_no_tools_sends_no_tool_choice(monkeypatch, ctx):
    recorder = Recorder(text_response("hi"))
    client = chat(monkeypatch, recorder)

    await client.complete(ctx, [ChatMessage(speaker=Speaker.USER, content="hi")], [])

    assert "tools" not in recorder.sent
    assert "tool_choice" not in recorder.sent


async def test_empty_api_key_and_api_base_are_left_out(monkeypatch, ctx):
    recorder = Recorder(text_response("hi"))
    client = chat(monkeypatch, recorder, api_key=SecretStr(""))

    await client.complete(ctx, [ChatMessage(speaker=Speaker.USER, content="hi")], [])

    assert "api_key" not in recorder.sent
    assert "api_base" not in recorder.sent
    assert "fallbacks" not in recorder.sent


def test_assistant_tool_calls_go_out_as_wire_names_and_json_arguments():
    message = ChatMessage(
        speaker=Speaker.ASSISTANT,
        content="",
        tool_calls=(
            ToolCall(id="c1", name="calendar.create_event", arguments={"title": "Exec Board"}),
        ),
    )

    body = to_wire(message)

    assert body["role"] == "assistant"
    assert body["content"] is None
    assert body["tool_calls"] == [
        {
            "id": "c1",
            "type": "function",
            "function": {
                "name": "calendar__create_event",
                "arguments": '{"title": "Exec Board"}',
            },
        }
    ]


def test_tool_message_carries_its_call_id_and_wire_name():
    message = ChatMessage(
        speaker=Speaker.TOOL,
        content="created",
        name="calendar.create_event",
        tool_call_id="c1",
    )

    assert to_wire(message) == {
        "role": "tool",
        "content": "created",
        "tool_call_id": "c1",
        "name": "calendar__create_event",
    }


def test_a_speaker_name_is_reduced_to_the_wire_character_set():
    message = ChatMessage(speaker=Speaker.USER, content="hi", name="Ash W. #1")

    assert to_wire(message)["name"] == "Ash_W___1"


async def test_a_tool_round_trip_keeps_the_call_id_and_the_name(monkeypatch, ctx):
    recorder = Recorder(text_response("done"))
    client = chat(monkeypatch, recorder)
    call = ToolCall(id="c1", name="calendar.create_event", arguments={"title": "Exec"})

    await client.complete(
        ctx,
        [
            ChatMessage(speaker=Speaker.USER, content="book it"),
            ChatMessage(speaker=Speaker.ASSISTANT, content="", tool_calls=(call,)),
            ChatMessage(
                speaker=Speaker.TOOL,
                content="created",
                name=call.name,
                tool_call_id=call.id,
            ),
        ],
        [SCHEMA],
    )

    assistant, tool = recorder.sent["messages"][1], recorder.sent["messages"][2]
    assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["name"] == tool["name"]
    assert "." not in tool["name"]


# ---------------------------------------------------------------- what comes back


async def test_a_plain_answer_becomes_a_completion(monkeypatch, ctx):
    recorder = Recorder(text_response("The meeting is Friday at 4pm."))
    client = chat(monkeypatch, recorder)

    completion = await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    assert completion.text == "The meeting is Friday at 4pm."
    assert completion.tool_calls == ()


async def test_a_null_content_answer_becomes_empty_text(monkeypatch, ctx):
    response = FakeResponse(choices=[FakeChoice(FakeMessage(content=None))])
    client = chat(monkeypatch, Recorder(response))

    completion = await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    assert completion.text == ""


async def test_tool_calls_come_back_under_the_name_the_registry_resolves(monkeypatch, ctx):
    response = FakeResponse(
        choices=[
            FakeChoice(
                FakeMessage(
                    content="",
                    tool_calls=[
                        FakeToolCall(
                            id="call_1",
                            function=FakeFunction(
                                name="calendar__create_event",
                                arguments='{"title": "Exec Board", "hour": 16}',
                            ),
                        ),
                        FakeToolCall(
                            id="call_2",
                            function=FakeFunction(name="drive__search_files", arguments="{}"),
                        ),
                    ],
                )
            )
        ]
    )
    client = chat(monkeypatch, Recorder(response))

    completion = await client.complete(ctx, [ChatMessage(Speaker.USER, "book it")], [SCHEMA])

    assert [call.name for call in completion.tool_calls] == [
        "calendar.create_event",
        "drive.search_files",
    ]
    assert completion.tool_calls[0].id == "call_1"
    assert completion.tool_calls[0].arguments == {"title": "Exec Board", "hour": 16}
    assert completion.tool_calls[1].arguments == {}


async def test_text_and_tool_calls_together_both_survive(monkeypatch, ctx):
    response = FakeResponse(
        choices=[
            FakeChoice(
                FakeMessage(
                    content="Looking that up.",
                    tool_calls=[
                        FakeToolCall(
                            id="call_1",
                            function=FakeFunction(name="calendar__list_events", arguments="{}"),
                        )
                    ],
                )
            )
        ]
    )
    client = chat(monkeypatch, Recorder(response))

    completion = await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [SCHEMA])

    assert completion.text == "Looking that up."
    assert completion.tool_calls[0].name == "calendar.list_events"


async def test_unparsable_arguments_are_not_retryable(monkeypatch, ctx):
    response = FakeResponse(
        choices=[
            FakeChoice(
                FakeMessage(
                    tool_calls=[
                        FakeToolCall(
                            id="call_1",
                            function=FakeFunction(name="calendar__create_event", arguments="{oops"),
                        )
                    ]
                )
            )
        ]
    )
    client = chat(monkeypatch, Recorder(response))

    with pytest.raises(ModelError) as raised:
        await client.complete(ctx, [ChatMessage(Speaker.USER, "book it")], [SCHEMA])

    assert raised.value.retryable is False


async def test_a_response_without_choices_is_a_model_error(monkeypatch, ctx):
    client = chat(monkeypatch, Recorder(FakeResponse(choices=[])))

    with pytest.raises(ModelError) as raised:
        await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    assert raised.value.retryable is False


# ---------------------------------------------------------------- usage and cost


async def test_usage_and_cost_come_back_in_cents(monkeypatch, ctx):
    response = text_response("ok", prompt_tokens=120, completion_tokens=34)
    response._hidden_params = {"response_cost": 0.0123}
    client = chat(monkeypatch, Recorder(response))

    completion = await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    assert completion.usage.prompt_tokens == 120
    assert completion.usage.completion_tokens == 34
    assert completion.usage.cost_cents == pytest.approx(1.23)


async def test_an_unpriced_model_costs_nothing(monkeypatch, ctx):
    def explode(**_: Any) -> float:
        raise ValueError("no pricing for this model")

    monkeypatch.setattr(litellm, "completion_cost", explode)
    response = text_response("ok", prompt_tokens=5, completion_tokens=2)
    response._hidden_params = {}
    client = chat(monkeypatch, Recorder(response))

    completion = await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    assert completion.usage.cost_cents == 0.0
    assert completion.usage.prompt_tokens == 5


# ---------------------------------------------------------------- failures


async def test_a_timeout_is_retryable(monkeypatch, ctx):
    error = Timeout(message="request timed out", model="m", llm_provider="openrouter")
    client = chat(monkeypatch, Recorder(error=error))

    with pytest.raises(ModelError) as raised:
        await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    assert raised.value.retryable is True


async def test_a_rate_limit_is_retryable(monkeypatch, ctx):
    error = RateLimitError(message="slow down", llm_provider="openrouter", model="m")
    client = chat(monkeypatch, Recorder(error=error))

    with pytest.raises(ModelError) as raised:
        await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    assert raised.value.retryable is True


async def test_a_bad_request_is_not_retryable(monkeypatch, ctx):
    error = BadRequestError(message="tool schema rejected", model="m", llm_provider="openrouter")
    client = chat(monkeypatch, Recorder(error=error))

    with pytest.raises(ModelError) as raised:
        await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    assert raised.value.retryable is False
    assert "tool schema rejected" in str(raised.value)


async def test_the_api_key_never_reaches_the_error_or_the_trace(monkeypatch, ctx):
    error = AuthenticationError(
        message=f"Incorrect API key provided: {KEY}", llm_provider="openrouter", model="m"
    )
    recorder = Recorder(error=error)
    monkeypatch.setattr(litellm, "acompletion", recorder)
    trace = MemoryTrace()
    client = LiteLlmChat(role(), trace)

    with pytest.raises(ModelError) as raised:
        await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    assert KEY not in str(raised.value)
    assert MASK in str(raised.value)
    assert KEY not in repr(trace.events)
    assert raised.value.retryable is False


async def test_a_failure_is_traced_once(monkeypatch, ctx):
    error = Timeout(message="timed out", model="m", llm_provider="openrouter")
    recorder = Recorder(error=error)
    monkeypatch.setattr(litellm, "acompletion", recorder)
    trace = MemoryTrace()
    client = LiteLlmChat(role(), trace)

    with pytest.raises(ModelError):
        await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    names = [name for name, _ in trace.events]
    assert names == ["model_error"]
    assert trace.events[0][1]["retryable"] is True


async def test_a_call_is_traced_with_its_tokens_and_cost(monkeypatch, ctx):
    response = text_response("ok", prompt_tokens=7, completion_tokens=3)
    response._hidden_params = {"response_cost": 0.01}
    recorder = Recorder(response)
    monkeypatch.setattr(litellm, "acompletion", recorder)
    trace = MemoryTrace()
    client = LiteLlmChat(role(), trace)

    await client.complete(ctx, [ChatMessage(Speaker.USER, "when")], [])

    name, data = trace.events[0]
    assert name == "generation"
    assert data["model"] == "openrouter/qwen/qwen3-32b"
    assert data["prompt_tokens"] == 7
    assert data["cost_cents"] == pytest.approx(1.0)
    assert data["output"] == "ok"


# ---------------------------------------------------------------- names


def test_a_wire_name_round_trips():
    assert wire_name("calendar.create_event") == "calendar__create_event"
    assert from_wire("calendar__create_event") == "calendar.create_event"


def test_only_the_first_separator_of_a_wire_name_is_the_tool():
    assert from_wire("drive__search__files") == "drive.search__files"


# ---------------------------------------------------------------- embeddings


def embedder(monkeypatch, recorder: Recorder, **over: Any) -> LiteLlmEmbedder:
    monkeypatch.setattr(litellm, "aembedding", recorder)
    values = {"model": "openai/text-embedding-3-small", "dimensions": 3}
    values.update(over)
    return LiteLlmEmbedder(role(**values))


@dataclass
class FakeEmbeddings:
    data: list[dict[str, Any]]


async def test_embedding_sends_the_batch_and_the_dimensions(monkeypatch, ctx):
    recorder = Recorder(
        FakeEmbeddings([{"index": 0, "embedding": [1, 2, 3]}, {"index": 1, "embedding": [4, 5, 6]}])
    )
    embed = embedder(monkeypatch, recorder)

    vectors = await embed.embed(ctx.org_id, ["a", "b"])

    assert recorder.sent["input"] == ["a", "b"]
    assert recorder.sent["dimensions"] == 3
    assert recorder.sent["api_key"] == KEY
    assert vectors == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]


async def test_embeddings_come_back_in_input_order(monkeypatch, ctx):
    recorder = Recorder(
        FakeEmbeddings([{"index": 1, "embedding": [4, 5, 6]}, {"index": 0, "embedding": [1, 2, 3]}])
    )
    embed = embedder(monkeypatch, recorder)

    assert await embed.embed(ctx.org_id, ["a", "b"]) == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]


async def test_an_empty_batch_calls_no_provider(monkeypatch, ctx):
    recorder = Recorder(FakeEmbeddings([]))
    embed = embedder(monkeypatch, recorder)

    assert await embed.embed(ctx.org_id, []) == []
    assert recorder.calls == []


async def test_a_short_embedding_answer_is_a_model_error(monkeypatch, ctx):
    recorder = Recorder(FakeEmbeddings([{"index": 0, "embedding": [1, 2, 3]}]))
    embed = embedder(monkeypatch, recorder)

    with pytest.raises(ModelError) as raised:
        await embed.embed(ctx.org_id, ["a", "b"])

    assert raised.value.retryable is False


async def test_an_embedding_timeout_is_retryable_and_hides_the_key(monkeypatch, ctx):
    error = Timeout(message=f"timed out with {KEY}", model="m", llm_provider="openai")
    embed = embedder(monkeypatch, Recorder(error=error))

    with pytest.raises(ModelError) as raised:
        await embed.embed(ctx.org_id, ["a"])

    assert raised.value.retryable is True
    assert KEY not in str(raised.value)


# ---------------------------------------------------------------- tracing


def test_langfuse_without_keys_records_nothing(ctx):
    sink = LangfuseTrace(Telemetry())

    sink.event(ctx, "generation", {"model": "m"})

    assert sink.enabled is False


def test_langfuse_with_keys_is_enabled(monkeypatch, ctx):
    created: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

        def create_trace_id(self, seed: str) -> str:
            return f"trace-{seed}"

        def create_event(self, **kwargs: Any) -> None:
            created.append(kwargs)

    monkeypatch.setattr("engine.llm.tracing.Langfuse", FakeClient)
    sink = LangfuseTrace(
        Telemetry(
            langfuse_public_key=SecretStr("pk"),
            langfuse_secret_key=SecretStr("sk"),
            langfuse_host="http://langfuse.invalid",
        )
    )

    sink.event(ctx, "reply", {"turns": 2})

    assert sink.enabled is True
    assert created[0]["public_key"] == "pk"
    assert created[1]["trace_context"] == {"trace_id": "trace-req-1"}
    assert created[1]["name"] == "reply"
    assert created[1]["metadata"]["org_id"] == ctx.org_id


def test_a_failing_langfuse_never_fails_a_request(monkeypatch, ctx):
    class Broken:
        def __init__(self, **_: Any) -> None:
            pass

        def create_trace_id(self, seed: str) -> str:
            raise RuntimeError("langfuse is down")

    monkeypatch.setattr("engine.llm.tracing.Langfuse", Broken)
    sink = LangfuseTrace(
        Telemetry(langfuse_public_key=SecretStr("pk"), langfuse_secret_key=SecretStr("sk"))
    )

    sink.event(ctx, "reply", {"turns": 1})


@pytest.mark.parametrize(
    "failure",
    [
        litellm.exceptions.APIConnectionError(
            message="connection reset", llm_provider="openai", model="gpt-4o-mini"
        ),
        litellm.exceptions.InternalServerError(
            message="upstream 500", llm_provider="openai", model="gpt-4o-mini"
        ),
        litellm.exceptions.ServiceUnavailableError(
            message="503", llm_provider="openai", model="gpt-4o-mini"
        ),
    ],
)
async def test_a_transient_provider_failure_is_retryable(monkeypatch, ctx, failure):
    # A dropped connection or a 5xx passes on its own; calling it permanent hides a working model.
    role = ModelRole(model="gpt-4o-mini", api_key=SecretStr("k"))

    async def fail(**_kwargs: object) -> object:
        raise failure

    monkeypatch.setattr(litellm, "acompletion", fail)
    with pytest.raises(ModelError) as raised:
        await LiteLlmChat(role, MemoryTrace()).complete(ctx, [], [])
    assert raised.value.retryable is True
