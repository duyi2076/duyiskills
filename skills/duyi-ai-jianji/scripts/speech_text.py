#!/usr/bin/env python3
"""Shared permanent speech-cleanup and caption-boundary rules."""

from __future__ import annotations

import re
from typing import Any


HARD_FILLER_CHARACTERS = frozenset("嗯啊呃额哦噢诶唉")
STRIPPABLE = " \t\r\n，。！？；：、,.!?;:…“”‘’\"'"
FORBIDDEN_UNIT_STARTS = frozenset(
    {
        "的",
        "得",
        "地",
        "了",
        "着",
        "过",
        "吗",
        "呢",
        "吧",
        "呀",
        "和",
        "与",
        "及",
        "或",
    }
)
FORBIDDEN_UNIT_ENDS = frozenset(
    {
        "把",
        "被",
        "在",
        "对",
        "给",
        "向",
        "从",
        "为",
        "和",
        "与",
        "及",
        "或",
    }
)


def normalized_token(value: Any) -> str:
    return str(value or "").strip(STRIPPABLE)


def is_hard_filler(value: Any) -> bool:
    token = normalized_token(value)
    return bool(token) and all(character in HARD_FILLER_CHARACTERS for character in token)


def contains_hard_filler_character(value: Any) -> bool:
    token = normalized_token(value)
    return any(character in HARD_FILLER_CHARACTERS for character in token)


def has_embedded_hard_filler(value: Any) -> bool:
    return contains_hard_filler_character(value) and not is_hard_filler(value)


def approved_embedded_semantic_word_ids(
    review: Any,
    *,
    transcript_sha256: str,
) -> set[str]:
    if review is None:
        return set()
    if not isinstance(review, dict) or review.get("schema_version") != 1:
        raise ValueError("embedded filler review must use schema_version 1")
    if review.get("transcript_sha256") != transcript_sha256:
        raise ValueError("embedded filler review does not match the current transcript")
    decisions = review.get("decisions")
    if not isinstance(decisions, dict):
        raise ValueError("embedded filler review decisions must be an object keyed by word id")
    approved: set[str] = set()
    for word_id, decision in decisions.items():
        if not isinstance(decision, dict):
            raise ValueError(f"embedded filler decision {word_id!r} must be an object")
        if (
            decision.get("decision") == "semantic_word"
            and decision.get("approved") is True
            and str(decision.get("reason") or "").strip()
        ):
            approved.add(str(word_id))
    return approved


def display_width(text: str) -> float:
    return sum(0.55 if ord(character) < 128 else 1.0 for character in text)


def join_word_text(words: list[dict[str, Any]], field: str = "text") -> str:
    result = ""
    previous = ""
    ascii_word = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.#_-]*$")
    latin_word = re.compile(r"^[A-Za-z][A-Za-z0-9+.#_-]*$")
    for word in words:
        token = str(word.get(field, ""))
        if not token:
            continue
        if result:
            both_ascii = bool(ascii_word.match(previous) and ascii_word.match(token))
            latin_boundary = bool(
                (latin_word.match(previous) and not ascii_word.match(token))
                or (latin_word.match(token) and not ascii_word.match(previous))
            )
            if both_ascii or latin_boundary:
                result += " "
        result += token
        previous = token
    return result


def unit_boundary_errors(words: list[dict[str, Any]]) -> list[str]:
    if not words:
        return ["empty"]
    first = normalized_token(words[0].get("text"))
    last = normalized_token(words[-1].get("text"))
    errors: list[str] = []
    if first in FORBIDDEN_UNIT_STARTS:
        errors.append("forbidden_start")
    if last in FORBIDDEN_UNIT_ENDS:
        errors.append("forbidden_end")
    return errors
