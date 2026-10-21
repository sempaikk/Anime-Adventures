"""Monotonic time budgets that can be frozen without losing remaining time."""

from __future__ import annotations

import time


class PausableTimer:
    def __init__(self, duration: float, clock=None):
        if duration <= 0:
            raise ValueError("A duração precisa ser positiva.")
        self.clock = clock or time.monotonic
        self._deadline = self.clock() + duration
        self._frozen = None

    @property
    def paused(self):
        return self._frozen is not None

    @property
    def remaining(self):
        if self.paused:
            return self._frozen
        return max(0.0, self._deadline - self.clock())

    @property
    def deadline(self):
        return None if self.paused else self._deadline

    def pause(self):
        remaining = self.remaining
        if self.paused or remaining <= 0:
            return False
        self._frozen = remaining
        return True

    def resume(self):
        if not self.paused:
            return False
        self._deadline = self.clock() + self._frozen
        self._frozen = None
        return True
