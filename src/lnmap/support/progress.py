"""Progress-reporting callbacks passed to LinkMapper.index()."""

import sys

PROGRESS_INTERVAL = 1000


def loud_logger(count: int) -> None:
    if count % PROGRESS_INTERVAL == 0:
        print(f"\rScanning: {count:,} items processed...", file=sys.stderr, end="")


def quiet_logger(count: int) -> None:
    pass
