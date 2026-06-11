"""Brier pipeline: ingestion -> transcription -> extraction -> resolution -> scoring.

Skeleton package. Every module exposes typed interfaces and stubs that raise
NotImplementedError, each tagged with the TASKS.md task that implements it.
External dependencies (YouTube, LLM, transcription, prices, storage) always sit
behind small interfaces with fixture-backed fakes — mock-first is the standing
convention for every later phase, not just the skeleton.
"""
