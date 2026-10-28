"""Owner-authorized, fixed Discord sources and the private reader credential."""

import os

BANNER_CHANNEL_ID = 993219350179876874
DAILY_CHANNEL_ID = 1326659593199423610
IMAGE_SOURCE_CHANNELS = (BANNER_CHANNEL_ID, DAILY_CHANNEL_ID)
SOURCE_CHANNELS = IMAGE_SOURCE_CHANNELS


def reader_token():
    # Keep the previous name only during migration; never log either value.
    return os.getenv("SECONDARY_ACCOUNT_TOKEN", "").strip() or os.getenv("BANNER_READER_TOKEN", "").strip()
