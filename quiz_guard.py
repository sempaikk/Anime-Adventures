"""Small, bounded cooldowns for private UI requests and lobby creation."""

from collections import OrderedDict
import time


class Cooldowns:
    def __init__(self, *, clock=None, capacity=4096):
        self.clock = clock or time.monotonic
        self.capacity = capacity
        self.entries = OrderedDict()

    def allow(self, key, seconds):
        now = self.clock()
        if self.entries.get(key, 0) > now:
            return False
        self.entries[key] = now + seconds
        self.entries.move_to_end(key)
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)
        return True

    def clear(self):
        self.entries.clear()
