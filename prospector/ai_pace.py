"""
Keeping a hunt under the model's rate limit
───────────────────────────────────────────
A hunt asks the model about ten things in under a minute: a check of every planned search, the cards in batches, the
company fit read and the readiness read. On a free Groq key that is more tokens a minute than the key is allowed,
and the engine's own retry (one wait of at most 20 seconds) is shorter than the minute Groq counts in. On 22-Nov-2026
the owner saw "Groq is rate-limiting this key" five times in one run, and every card after the third failure was
scored by plain rules.

Three things, in this order:

    pace      before a call, wait until the last minute's estimated tokens leave room for it.
    switch    Groq counts a limit per MODEL, so a call refused on one model is tried on the next model the engine
              knows before anything waits.
    cool off  only when every model refused: one wait of COOL_OFF seconds, then one more pass. After that the call
              raises and the caller says so (the cards it did not read are scored by plain rules, and the owner is
              told).

Each refusal also tightens the pace for the rest of the run: the budget is a guess about someone else's quota, so it
learns. Qt-free; the clock, the sleep and the call are passed in, so a test never waits.
"""
from __future__ import annotations

import time
from collections import deque

PER_MINUTE = 6000               # estimated tokens a minute to stay under, until a refusal says it is too many
FLOOR = 1500                    # the pace never tightens below this
WINDOW = 60.0                   # seconds a rate limit is counted over
COOL_OFF = 25.0                 # seconds to wait when every model refused
MAX_MODELS = 3                  # models tried per pass
SLICE = 0.5                     # a wait is slept in slices this long so Stop is heard


def tokens_of(prompt: str) -> int:
    """A rough token count for a prompt and the answer it will get: about three characters a token, and room for the
    reply. An estimate to pace by, not a bill."""
    return len(prompt or "") // 3 + 500


def is_rate_limit(error: Exception) -> bool:
    return "rate-limit" in str(error).lower() or "rate limit" in str(error).lower()


class Pacer:
    """A rolling one-minute budget of estimated tokens."""

    def __init__(self, per_minute: int = PER_MINUTE, clock=time.monotonic):
        self.per_minute, self.clock = max(FLOOR, int(per_minute)), clock
        self._spent: deque = deque()                # (time, tokens)

    def _trim(self, now: float) -> None:
        while self._spent and now - self._spent[0][0] >= WINDOW:
            self._spent.popleft()

    def wait_needed(self, tokens: int) -> float:
        """Seconds to wait before `tokens` fit in the window; 0 when they fit now. A call bigger than the whole
        budget waits for an empty window and then goes: it can never be paced under a limit it exceeds alone."""
        now = self.clock()
        self._trim(now)
        used = sum(t for _, t in self._spent)
        if used + tokens <= self.per_minute or not self._spent:
            return 0.0
        need, freed = used + tokens - self.per_minute, 0
        for at, t in self._spent:
            freed += t
            if freed >= need:
                return max(0.0, at + WINDOW - now)
        return max(0.0, self._spent[-1][0] + WINDOW - now)

    def spent(self, tokens: int) -> None:
        self._spent.append((self.clock(), int(tokens)))

    def tighten(self) -> None:
        """A model refused: the budget was too generous. Take 40% off, down to FLOOR."""
        self.per_minute = max(FLOOR, int(self.per_minute * 0.6))


def paced(call, models, pacer: Pacer, *, cancelled=None, on_wait=None, sleep=time.sleep):
    """`ask(prompt, purpose, json_mode, temperature)` made of `call(model, prompt, temperature, json_mode) -> text`.

    `models` are tried in order (the first MAX_MODELS). A refusal that is not a rate limit raises at once, with the
    server's own words. `cancelled()` is asked while waiting, and a stopped run raises RuntimeError("Stopped.")."""
    models = list(models)[:MAX_MODELS] or [""]

    def wait(seconds: float, why: str) -> None:
        if seconds <= 0:
            return
        if on_wait:
            on_wait(seconds, why)
        left = seconds
        while left > 0:
            if cancelled and cancelled():
                raise RuntimeError("Stopped.")
            step = min(SLICE, left)
            sleep(step)
            left -= step

    def ask(prompt, purpose="qualify", json_mode=True, temperature=0.2):
        est = tokens_of(prompt)
        wait(pacer.wait_needed(est), "Pacing the AI so it stays under its rate limit")
        last = None
        for round_no in range(2):
            for model in models:
                try:
                    out = call(model, prompt, temperature, json_mode)
                except RuntimeError as e:
                    if not is_rate_limit(e):
                        raise
                    last = e
                    pacer.tighten()
                    continue                        # another model has its own limit
                pacer.spent(est)
                return out
            if round_no == 0:
                wait(COOL_OFF, "The AI is rate-limited on every model; waiting a moment")
        raise last if last is not None else RuntimeError("The AI did not answer.")
    return ask
