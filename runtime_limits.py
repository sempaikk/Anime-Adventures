"""Small, shared limits. Persisted timestamps use UTC; operation timers are monotonic."""

import os

SOURCE_TIMEOUT = 25
DOWNLOAD_TIMEOUT = 30
RECEIVE_TIMEOUT = 65
DELIVERY_TIMEOUT = 40
SOURCE_FRESHNESS = 120
INCIDENT_STABILITY = 120
RECEIVE_QUEUE = 64


def quota(name, default, minimum=64):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        raise ValueError(name + ' must contain a whole number of MiB.') from None
    if value < minimum or value > 1024 * 1024:
        raise ValueError(name + ' is outside the supported hosting limits.')
    return value * 1024 * 1024
