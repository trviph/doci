"""Deployment entrypoints — thin commands that import doci and run a process.

Each module is one deployment type (e.g. ``api``); add more (workers, one-off
jobs) here as siblings, all sharing the ``doci`` library.
"""
