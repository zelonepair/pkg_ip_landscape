"""OpenRouter-powered coating classification."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Iterable, Optional, Tuple

import requests

from . import config, utils


def _truncate(text: Optional[str], max_chars: int) -> str:
    if not text:
        return ""
    return text[:max_chars]


def build_classification_prompt(record: dict) -> list:
    description_excerpt = _truncate(record.get("description"), 1200)
    first_claim_excerpt = _truncate(record.get("first_claim"), 800)

    content = (
        "Classify the coating chemistry for the following patent. "
        "Respond with a compact JSON object containing only the key "
        "'coating_type' using one of the allowed categories, and an optional "
        "'confidence' number between 0 and 1.\n\n"
        f"Allowed categories: {', '.join(config.COATING_CHOICES)}\n\n"
        f"Publication number: {record.get('publication_number')}\n"
        f"Publication date: {record.get('publication_date')}\n"
        f"Title: {record.get('title')}\n"
        f"Abstract: {record.get('abstract')}\n"
        f"Assignee: {record.get('assignee')}\n"
        f"CPC Codes: {', '.join(record.get('cpc_codes') or [])}\n"
        f"Description excerpt: {description_excerpt}\n"
        f"First claim excerpt: {first_claim_excerpt}\n"
    )

    return [
        {
            "role": "system",
            "content": "You are a materials scientist specialised in can coating chemistries.",
        },
        {"role": "user", "content": content},
    ]


def call_openrouter(
    api_key: str,
    model: str,
    payload: dict,
    timeout: float,
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    referer = os.getenv(config.ENV_OPENROUTER_APP_URL)
    if referer:
        headers["HTTP-Referer"] = referer
    title = os.getenv(config.ENV_OPENROUTER_TITLE, "Patent Coating Classification")
    headers["X-Title"] = title

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        timeout=timeout,
        json={
            "model": model,
            **payload,
        },
    )
    response.raise_for_status()
    return response.json()


def classify_record(
    record: dict,
    api_key: str,
    model: str,
    timeout: float,
    max_retries: int,
) -> Tuple[Optional[str], Optional[float]]:
    messages = build_classification_prompt(record)
    payload = {
        "messages": messages,
        "temperature": 0.0,
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = call_openrouter(
                api_key=api_key,
                model=model,
                payload=payload,
                timeout=timeout,
            )
            choices = response.get("choices")
            if not choices:
                raise ValueError("No choices returned from OpenRouter response.")
            message = choices[0].get("message", {})
            content = (message.get("content") or "").strip()
            if not content:
                raise ValueError("Empty content in LLM response.")
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as err:  # pragma: no cover - difficult to hit in practice
                raise ValueError(f"Failed to parse JSON from response: {content}") from err
            coating_type = parsed.get("coating_type")
            confidence = parsed.get("confidence")
            if coating_type and coating_type not in config.COATING_CHOICES:
                logging.warning(
                    "Received coating_type '%s' outside expected choices.",
                    coating_type,
                )
            return coating_type, float(confidence) if confidence is not None else None
        except requests.HTTPError as exc:
            logging.error("OpenRouter HTTP error (attempt %s/%s): %s", attempt, max_retries, exc)
        except Exception as exc:  # noqa: BLE001
            logging.error("OpenRouter error (attempt %s/%s): %s", attempt, max_retries, exc)
        if attempt < max_retries:
            time.sleep(2 ** attempt * 0.5)
    return None, None


def classify_records(
    records: list,
    api_key: str,
    model: str,
    timeout: float,
    max_retries: int,
    delay: float,
    include_era: bool,
) -> None:
    total = len(records)
    for index, record in enumerate(records, start=1):
        logging.info(
            "Classifying coating type (%s/%s): %s",
            index,
            total,
            record.get("publication_number"),
        )
        coating_type, confidence = classify_record(
            record=record,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
        )
        record["coating_type"] = coating_type
        record["classification_confidence"] = confidence
        if include_era:
            record["era"] = utils.determine_era(record.get("publication_year"), coating_type)
        if index != total and delay > 0:
            time.sleep(delay)
