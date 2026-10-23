import asyncio

import httpx
import pytest
from strands.types.exceptions import ModelThrottledException

from kilta_bridge.chain import (
    AllModelsFailed,
    FallbackModel,
    Link,
    build_chain,
    is_retryable,
    quota_delay,
)
from kilta_bridge.config import Settings

from .fakes import (
    BrokenMidStream,
    FailingModel,
    FailsAfterMessageStart,
    FlakyModel,
    Plan,
    ScriptedModel,
    SlowModel,
)

MESSAGES = [{"role": "user", "content": [{"text": "hello"}]}]


async def run(chain: FallbackModel) -> list[dict]:
    return [event async for event in chain.stream(MESSAGES)]


def ok_model() -> ScriptedModel:
    return ScriptedModel([Plan(say="fine")])


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


async def test_a_429_is_retried_with_backoff_on_the_same_model():
    sleeps = Sleeps()
    flaky = FlakyModel(ok_model(), failures=2, error=ModelThrottledException("429 slow down"))
    chain = FallbackModel(
        [Link("primary", flaky), Link("backup", ok_model())],
        sleep=sleeps,
        base_delay=1.0,
        retries=2,
    )
    await run(chain)
    assert chain.last_used == "primary" and flaky.calls == 3
    assert sleeps.delays == [1.0, 2.0]  # exponential backoff


async def test_a_timeout_that_never_recovers_falls_back_after_the_retries():
    sleeps = Sleeps()
    failing = FailingModel(TimeoutError("timed out"))
    events = []
    chain = FallbackModel(
        [Link("primary", failing), Link("backup", ok_model())],
        sleep=sleeps,
        retries=2,
        base_delay=0.5,
        on_event=events.append,
    )
    await run(chain)
    assert chain.last_used == "backup" and failing.calls == 3
    assert sleeps.delays == [0.5, 1.0]
    assert [e["type"] for e in events] == ["model_retry", "model_retry", "model_fallback"]
    assert events[-1]["next"] == "backup"


async def test_a_non_retryable_error_skips_straight_to_the_next_model():
    sleeps = Sleeps()
    bad_key = FailingModel(ValueError("API key not valid"))
    chain = FallbackModel([Link("primary", bad_key), Link("backup", ok_model())], sleep=sleeps)
    await run(chain)
    assert chain.last_used == "backup" and bad_key.calls == 1 and sleeps.delays == []
    assert chain.attempts[0]["retryable"] is False


async def test_the_chain_walks_every_link_in_order():
    errors = [ValueError("bad key"), TimeoutError("timed out"), RuntimeError("503 UNAVAILABLE")]
    links = [Link(f"m{i}", FailingModel(e)) for i, e in enumerate(errors)]
    links.append(Link("last", ok_model()))
    chain = FallbackModel(links, retries=0, sleep=Sleeps())
    await run(chain)
    assert [a["model"] for a in chain.attempts] == ["m0", "m1", "m2"]
    assert chain.last_used == "last"


async def test_when_every_model_fails_it_says_so():
    chain = FallbackModel(
        [Link("a", FailingModel(ValueError("x"))), Link("b", FailingModel(ValueError("y")))],
        retries=0,
        sleep=Sleeps(),
    )
    with pytest.raises(AllModelsFailed) as raised:
        await run(chain)
    assert [a["model"] for a in raised.value.attempts] == ["a", "b"]


async def test_a_model_that_never_answers_times_out_into_the_fallback():
    chain = FallbackModel(
        [Link("slow", SlowModel()), Link("backup", ok_model())],
        retries=0,
        first_token_timeout=0.05,
        sleep=Sleeps(),
    )
    await run(chain)
    assert chain.last_used == "backup"
    assert "FirstTokenTimeout" in chain.attempts[0]["error"]


async def test_a_failure_after_streaming_started_is_not_hidden():
    chain = FallbackModel(
        [Link("broken", BrokenMidStream()), Link("backup", ok_model())], retries=0, sleep=Sleeps()
    )
    with pytest.raises(RuntimeError, match="mid-stream"):
        await run(chain)


async def test_pacing_spaces_out_calls_to_one_model():
    link = Link("paced", ok_model(), min_interval=0.15)
    chain = FallbackModel([link], retries=0)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await run(chain)
    await run(chain)
    assert loop.time() - start >= 0.14


class WithStatus(Exception):
    def __init__(self, status: int) -> None:
        super().__init__("boom")
        self.status_code = status


@pytest.mark.parametrize(
    "error, expected",
    [
        (ModelThrottledException("slow"), True),
        (TimeoutError(), True),
        (httpx.ReadTimeout("t"), True),
        (httpx.ConnectError("c"), True),
        (WithStatus(429), True),
        (WithStatus(503), True),
        (RuntimeError("503 UNAVAILABLE: high demand"), True),
        (RuntimeError("RESOURCE_EXHAUSTED"), True),
        (WithStatus(400), False),
        (WithStatus(401), False),
        (ValueError("API key not valid"), False),
        (KeyError("model"), False),
    ],
)
def test_which_errors_are_worth_retrying(error, expected):
    assert is_retryable(error) is expected


def test_links_without_credentials_are_left_out_but_ollama_stays_last():
    assert [link.name for link in build_chain(Settings(groq_api_key="q")).links] == [
        "groq:openai/gpt-oss-120b",
        "ollama:qwen3:8b",
    ]
    assert [link.name for link in build_chain(Settings()).links] == ["ollama:qwen3:8b"]


def test_model_ids_and_pacing_come_from_the_environment():
    settings = Settings.from_env(
        {
            "GEMINI_API_KEY": "g",
            "GROQ_API_KEY": "q",
            "KILTA_MODEL_PRIMARY": "gemini-x",
            "KILTA_MODEL_GROQ": "groq-y",
            "KILTA_MODEL_FALLBACK": "gemini-z",
            "KILTA_OLLAMA_MODEL": "llama",
            "KILTA_MODEL_MIN_INTERVAL": "4.5",
        }
    )
    chain = build_chain(settings)
    assert [link.name for link in chain.links] == [
        "gemini:gemini-x",
        "groq:groq-y",
        "gemini:gemini-z",
        "ollama:llama",
    ]
    assert chain.links[0].min_interval == 4.5 and chain.links[-1].min_interval == 0.0


async def test_a_failed_model_is_skipped_during_its_cooldown_then_tried_again():
    now = [100.0]
    failing = FailingModel(TimeoutError("timed out"))
    events = []
    chain = FallbackModel(
        [Link("primary", failing), Link("backup", ok_model())],
        retries=1,
        cooldown=30,
        clock=lambda: now[0],
        sleep=Sleeps(),
        on_event=events.append,
    )
    await run(chain)
    assert failing.calls == 2  # one try, one retry, then the fallback
    await run(chain)
    assert failing.calls == 2  # still cooling down: skipped, no wasted retries
    assert any(e["type"] == "model_skipped" and e["model"] == "primary" for e in events)
    now[0] += 31
    await run(chain)
    assert failing.calls == 4  # the cooldown ended, so it gets another chance


async def test_when_every_model_is_cooling_down_they_are_all_tried_anyway():
    now = [0.0]
    chain = FallbackModel(
        [Link("a", FailingModel(ValueError("x"))), Link("b", FailingModel(ValueError("y")))],
        retries=0,
        cooldown=60,
        clock=lambda: now[0],
        sleep=Sleeps(),
    )
    with pytest.raises(AllModelsFailed):
        await run(chain)
    with pytest.raises(AllModelsFailed) as raised:
        await run(chain)
    assert [a["model"] for a in raised.value.attempts][-2:] == ["a", "b"]


async def test_an_error_after_messagestart_but_before_content_still_falls_back():
    """Gemini announces the message before the request succeeds; a bad key arrives after it."""
    early = FailsAfterMessageStart(ValueError("400 API key not valid"))
    chain = FallbackModel(
        [Link("gemini", early), Link("groq", ok_model())], retries=2, sleep=Sleeps()
    )
    events = await run(chain)
    assert chain.last_used == "groq" and early.calls == 1
    assert sum("messageStart" in e for e in events) == 1  # the caller sees one clean message


async def test_a_retryable_error_after_messagestart_is_retried():
    sleeps = Sleeps()
    flaky = FlakyModel(
        FailsAfterMessageStart(RuntimeError("429 RESOURCE_EXHAUSTED")), 0, RuntimeError("unused")
    )
    chain = FallbackModel(
        [Link("gemini", flaky), Link("groq", ok_model())], retries=1, base_delay=0.5, sleep=sleeps
    )
    await run(chain)
    assert sleeps.delays == [0.5] and chain.last_used == "groq"


class SpentQuota(Exception):
    """Looks like google.genai's ClientError for a spent free-tier daily quota."""

    def __init__(self) -> None:
        super().__init__("429 RESOURCE_EXHAUSTED")
        self.details = {
            "error": {
                "message": "Quota exceeded for metric: generate_content_free_tier_requests, "
                "limit: 20, model: gemini-3.6-flash\nPlease retry in 8h56m12.355977132s."
            }
        }


def throttled_by_daily_quota() -> ModelThrottledException:
    error = ModelThrottledException("You exceeded your current quota")
    error.__cause__ = SpentQuota()
    return error


def test_quota_delay_is_read_from_the_error_chain():
    assert quota_delay(throttled_by_daily_quota()) == pytest.approx(
        8 * 3600 + 56 * 60 + 12.36, 0.01
    )
    assert quota_delay(ModelThrottledException("429 slow down")) is None
    assert quota_delay(RuntimeError("retry in 2s")) is None  # short waits are ordinary retries
    assert quota_delay(RuntimeError("retryDelay: '32254s'")) == 32254
    assert quota_delay(RuntimeError("GenerateRequestsPerDayPerProjectPerModel-FreeTier")) == 3600


async def test_a_spent_daily_quota_is_not_retried_and_the_model_is_skipped_for_hours():
    now = [0.0]
    sleeps = Sleeps()
    spent = FailingModel(throttled_by_daily_quota())
    events = []
    chain = FallbackModel(
        [Link("flash", spent), Link("lite", ok_model())],
        retries=3,
        cooldown=45,
        clock=lambda: now[0],
        sleep=sleeps,
        on_event=events.append,
    )
    await run(chain)
    assert spent.calls == 1 and sleeps.delays == []  # no pointless backoff
    assert chain.attempts[0]["quota_resets_in_s"] > 32000
    now[0] = 3600
    await run(chain)
    assert spent.calls == 1  # an hour later it is still skipped
    assert any(e["type"] == "model_skipped" and e["for_s"] > 10000 for e in events)
    now[0] = 6 * 3600 + 1
    await run(chain)
    assert spent.calls == 2  # the cap lets it be tried again, in case the quota changed


def test_model_only_keeps_a_single_link():
    keys = {"gemini_api_key": "g", "groq_api_key": "q"}
    for role, name in [
        ("primary", "gemini:gemini-3.5-flash-lite"),
        ("groq", "groq:openai/gpt-oss-120b"),
        ("fallback", "gemini:gemini-3.5-flash"),
        ("ollama", "ollama:qwen3:8b"),
    ]:
        chain = build_chain(Settings(model_only=role, **keys))
        assert [link.name for link in chain.links] == [name]


def test_model_only_rejects_a_typo_and_a_missing_key():
    with pytest.raises(ValueError, match="must be one of"):
        build_chain(Settings(model_only="gemini"))
    with pytest.raises(ValueError, match="no API key"):
        build_chain(Settings(model_only="groq"))


def test_the_default_chain_order_is_flash_lite_groq_flash_ollama():
    names = [
        link.name for link in build_chain(Settings(gemini_api_key="g", groq_api_key="q")).links
    ]
    assert names == [
        "gemini:gemini-3.5-flash-lite",
        "groq:openai/gpt-oss-120b",
        "gemini:gemini-3.5-flash",
        "ollama:qwen3:8b",
    ]


async def test_a_turn_budget_is_shared_so_a_slow_link_cannot_starve_the_next():
    from .fakes import SlowModel

    chain = FallbackModel(
        [Link("slow", SlowModel()), Link("good", ok_model())],
        retries=2,
        first_token_timeout=60,
        sleep=Sleeps(),
    )
    chain.begin_turn(budget=4)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await run(chain)
    assert chain.last_used == "good" and loop.time() - start < 4


async def test_a_turn_with_no_time_left_fails_fast():
    chain = FallbackModel([Link("a", ok_model())], clock=lambda: 100.0)
    chain.begin_turn(budget=1)
    chain._clock = lambda: 200.0  # the budget is long gone
    with pytest.raises(AllModelsFailed):
        await run(chain)


async def test_a_link_cancelled_by_the_turn_deadline_is_skipped_next_time():
    now = [0.0]
    chain = FallbackModel(
        [
            Link("slow", __import__("tests.fakes", fromlist=["SlowModel"]).SlowModel()),
            Link("good", ok_model()),
        ],
        retries=0,
        cooldown=30,
        clock=lambda: now[0],
        first_token_timeout=60,
        sleep=Sleeps(),
    )
    task = asyncio.create_task(run(chain))
    await asyncio.sleep(0.05)
    task.cancel()  # what the agent's turn timeout does
    with pytest.raises(asyncio.CancelledError):
        await task
    assert chain.links[0].down_until == 30


def test_a_model_that_was_too_slow_is_skipped_not_asked_again():
    from kilta_bridge.chain import FirstTokenTimeout

    assert is_retryable(FirstTokenTimeout("no response within 20s")) is False
    assert is_retryable(TimeoutError("read timed out")) is True
