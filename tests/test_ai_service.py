"""Unit tests for the AI assistant service layer (no network access needed)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from flask import Flask

from app.services.ai import (
    DISCLAIMER,
    SYSTEM_PROMPT,
    AIError,
    AnthropicProvider,
    FallbackProvider,
    LegalAssistant,
    Topic,
    build_assistant,
    get_assistant,
)


def user(text: str) -> dict[str, str]:
    return {"role": "user", "content": text}


def assistant(text: str) -> dict[str, str]:
    return {"role": "assistant", "content": text}


class TestFallbackProvider:
    provider: FallbackProvider

    def setup_method(self) -> None:
        self.provider = FallbackProvider()

    def test_greeting(self) -> None:
        reply = self.provider.complete(SYSTEM_PROMPT, [user("Hello!")])
        assert "virtual assistant" in reply

    def test_empty_history_greets(self) -> None:
        assert "Hello" in self.provider.complete(SYSTEM_PROMPT, [])

    def test_thanks(self) -> None:
        reply = self.provider.complete(SYSTEM_PROMPT, [user("Thanks a lot")])
        assert "welcome" in reply.lower()

    @pytest.mark.parametrize("text, expected", [
        ("My landlord won't return my deposit", "tenancy"),
        ("I was fired by my employer yesterday", "employment"),
        ("We are getting a divorce and have two children", "family"),
        ("They breached our signed contract", "contract"),
        ("My father passed away without a will", "wills"),
        ("Dispute with my neighbour over a boundary fence", "property"),
        ("I was arrested by the police last night", "criminal"),
        ("I want to register a trademark for my startup", "business"),
        ("My visa expires next month", "immigration"),
        ("I slipped and was injured at the supermarket", "injury"),
        ("How much does a consultation cost?", "consultation"),
    ])
    def test_topic_matching(self, text: str, expected: str) -> None:
        topic = self.provider.match_topic(text)
        assert topic is not None and topic.name == expected

    def test_no_match_returns_none(self) -> None:
        assert self.provider.match_topic("xyzzy plugh") is None

    def test_unknown_topic_asks_for_more(self) -> None:
        reply = self.provider.complete(SYSTEM_PROMPT, [user("xyzzy plugh")])
        assert "tell me a bit more" in reply.lower()
        assert DISCLAIMER in reply

    def test_first_reply_has_disclaimer_then_omitted(self) -> None:
        first = self.provider.complete(SYSTEM_PROMPT, [user("landlord deposit")])
        assert DISCLAIMER in first
        second = self.provider.complete(
            SYSTEM_PROMPT,
            [user("landlord deposit"), assistant(first), user("he also won't fix the rent issue")],
        )
        assert DISCLAIMER not in second
        assert "follow" not in second.lower() or "Is this about" in second

    def test_follow_up_question_included(self) -> None:
        reply = self.provider.complete(SYSTEM_PROMPT, [user("I want to write a will")])
        assert reply.rstrip().endswith("?") or "?" in reply

    def test_best_scoring_topic_wins(self) -> None:
        # Two employment keywords vs one tenancy keyword.
        topic = self.provider.match_topic("my employer wants me to pay rent for my uniform "
                                          "and says I will be dismissed otherwise")
        assert topic is not None and topic.name == "employment"

    def test_custom_topics(self) -> None:
        provider = FallbackProvider(topics=[Topic("pets", ["dog"], "Dogs are great.")])
        assert provider.complete("", [user("my dog bit someone")]).startswith("Dogs are great.")
        assert provider.match_topic("cat") is None


class TestLegalAssistant:
    def test_sanitise_history_drops_invalid_and_merges(self) -> None:
        history = [
            assistant("I should be dropped as leading assistant turn"),
            user("one"),
            user("two"),
            {"role": "system", "content": "ignored"},
            {"role": "assistant", "content": "   "},
            assistant("reply"),
        ]
        cleaned = LegalAssistant.sanitise_history(history)
        assert cleaned == [user("one\n\ntwo"), assistant("reply")]

    def test_reply_requires_user_message(self) -> None:
        with pytest.raises(ValueError):
            LegalAssistant(FallbackProvider()).reply([assistant("hi")])

    def test_history_limit_applied(self) -> None:
        captured: dict[str, Any] = {}

        class Spy:
            name = "spy"

            def complete(self, system: str, messages: list[dict[str, str]]) -> str:
                captured["messages"] = messages
                captured["system"] = system
                return "ok"

        bot = LegalAssistant(Spy(), history_limit=4, system_prompt="SYS")
        history = []
        for i in range(10):
            history.append(user(f"u{i}"))
            history.append(assistant(f"a{i}"))
        history.append(user("final"))
        assert bot.reply(history) == "ok"
        msgs = captured["messages"]
        assert len(msgs) <= 4
        assert msgs[0]["role"] == "user"
        assert msgs[-1]["content"] == "final"
        assert captured["system"] == "SYS"

    def test_provider_name(self) -> None:
        assert LegalAssistant(FallbackProvider()).provider_name == "fallback"


class FakeAnthropicClient:
    """Mimics the subset of the anthropic SDK we use."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = self
        self._response = response
        self._error = error

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


class TestAnthropicProvider:
    def test_complete_joins_text_blocks(self) -> None:
        response = SimpleNamespace(content=[
            SimpleNamespace(type="text", text="Part one."),
            SimpleNamespace(type="tool_use", text="ignored"),
            SimpleNamespace(type="text", text="Part two."),
        ])
        fake = FakeAnthropicClient(response=response)
        provider = AnthropicProvider("key", "model-x", max_tokens=123, client=fake)
        result = provider.complete("SYS", [user("hi")])
        assert result == "Part one.\nPart two."
        call = fake.calls[0]
        assert call["model"] == "model-x"
        assert call["max_tokens"] == 123
        assert call["system"] == "SYS"
        assert call["messages"] == [user("hi")]

    def test_empty_response_raises(self) -> None:
        fake = FakeAnthropicClient(response=SimpleNamespace(content=[]))
        provider = AnthropicProvider("key", "m", client=fake)
        with pytest.raises(AIError):
            provider.complete("SYS", [user("hi")])

    def test_sdk_error_wrapped(self) -> None:
        fake = FakeAnthropicClient(error=RuntimeError("boom"))
        provider = AnthropicProvider("key", "m", client=fake)
        with pytest.raises(AIError, match="boom"):
            provider.complete("SYS", [user("hi")])

    def test_name(self) -> None:
        assert AnthropicProvider("k", "m", client=FakeAnthropicClient()).name == "anthropic"


class TestBuildAssistant:
    def test_fallback_when_no_key(self) -> None:
        bot = build_assistant({"AI_PROVIDER": "auto", "ANTHROPIC_API_KEY": None})
        assert bot.provider_name == "fallback"

    def test_explicit_fallback_ignores_key(self) -> None:
        bot = build_assistant({"AI_PROVIDER": "fallback", "ANTHROPIC_API_KEY": "sk-x"})
        assert bot.provider_name == "fallback"

    def test_anthropic_requires_key(self) -> None:
        with pytest.raises(AIError):
            build_assistant({"AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": None})

    def test_auto_with_key_uses_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created: dict[str, str] = {}

        class FakeModule:
            class Anthropic:  # pylint: disable=too-few-public-methods
                def __init__(self, api_key: str) -> None:
                    created["api_key"] = api_key

        monkeypatch.setitem(__import__("sys").modules, "anthropic", FakeModule)
        bot = build_assistant({"AI_PROVIDER": "auto", "ANTHROPIC_API_KEY": "sk-test",
                               "ANTHROPIC_MODEL": "claude-x", "AI_MAX_TOKENS": "55",
                               "AI_HISTORY_LIMIT": 7})
        assert bot.provider_name == "anthropic"
        assert created["api_key"] == "sk-test"
        assert isinstance(bot.provider, AnthropicProvider)
        assert bot.provider.model == "claude-x"
        assert bot.provider.max_tokens == 55
        assert bot.history_limit == 7

    def test_get_assistant_cached_on_app(self, app: Flask) -> None:
        first = get_assistant()
        second = get_assistant()
        assert first is second
        assert first.provider_name == "fallback"
