"""Shared POSIX clock for timestamps crossing the local Unix socket.

Python 3.9's macOS monotonic clock can have a process-specific origin.
Use the kernel CLOCK_MONOTONIC explicitly rather than comparing those origins.
"""
import time


def speech_time():
    return time.clock_gettime(time.CLOCK_MONOTONIC)
