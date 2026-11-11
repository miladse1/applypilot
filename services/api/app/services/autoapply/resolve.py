"""Answer one form field from verified information, or report that the user must answer it."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.services.autoapply.applicant import Applicant
from app.services.autoapply.fields import EEO_KEYS, HONEYPOT, YES_NO_KEYS, Field, choose_option, classify, label_key, normalize

log = logging.getLogger(__name__)

CHOICE_KINDS = {"select", "radio", "combobox", "buttons", "listbox"}
TEXT_KINDS = {"text", "textarea", "email", "tel", "url", "number", "date"}


@dataclass
class Resolution:
    value: object  # str for text/choices, bool for a checkbox, Path for a file
    source: str  # profile, saved, approved_answers, your_answer, policy, ai


def _yes_no(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if text.startswith(("yes", "y ", "true")) or text == "y":
        return "Yes"
    if text.startswith(("no", "n ", "false")) or text == "n":
        return "No"
    return None


def _mentions_other_country(label: str, job_country: str | None) -> bool:
    text = label.lower()
    us = bool(re.search(r"united states|\bu\.?s\.?a?\b|america", text))
    canada = "canada" in text
    if us and not canada:
        return job_country != "us"
    if canada and not us:
        return job_country == "us"
    return False


def _fact(key: str, field: Field, applicant: Applicant) -> Resolution | None:
    saved, values = applicant.saved, applicant.values
    if key == "resume" and field.kind == "file":
        return Resolution(applicant.resume_path, "approved_answers")
    if key == "cover_letter":
        if field.kind == "file" and applicant.cover_letter_path:
            return Resolution(applicant.cover_letter_path, "approved_answers")
        if field.kind == "textarea" and applicant.cover_letter_text:
            return Resolution(applicant.cover_letter_text, "approved_answers")
        return None
    if key == "work_authorization":
        if _mentions_other_country(field.label, applicant.job_country):
            return None
        answer = _yes_no(saved.get("work_authorization"))
        return Resolution(answer, "saved") if answer else None
    if key in {"sponsorship", "relocation", "age_18"}:
        answer = _yes_no(saved.get(key))
        return Resolution(answer, "saved") if answer else None
    if key == "previous_employee":
        return Resolution("Yes" if applicant.previously_employed() else "No", "profile")
    if key in EEO_KEYS:
        return Resolution("decline", "policy") if saved.get("voluntary_disclosures") == "decline" else None
    if key == "privacy_consent":
        if saved.get("consent_privacy") != "yes":
            return None
        return Resolution(True if field.kind == "checkbox" else "Yes", "policy")
    if key in {"start_date", "how_heard", "salary"}:
        if field.kind == "date":
            return None
        return Resolution(saved[key], "saved") if saved.get(key) else None
    if key == "phone_type":
        return Resolution("Mobile", "profile")
    if key == "phone_country":
        return Resolution(values.get("country") or "Canada", "profile") if values.get("country") else None
    if key == "why_interested":
        return None  # written for each job by the drafter, using the approved answer as material
    if key in values and values[key]:
        return Resolution(values[key], "profile")
    return None


def _approved_answer(field: Field, applicant: Applicant) -> Resolution | None:
    """A long-form question that matches one of the answers approved for this application."""
    if field.kind not in {"text", "textarea"}:
        return None
    label = normalize(field.label).lower()
    best, score = None, 0.0
    for item in applicant.answers:
        if item.get("sensitive"):
            continue
        ratio = SequenceMatcher(None, label, (item.get("prompt") or "").lower()).ratio()
        if ratio > score:
            best, score = item, ratio
    return Resolution(best["answer"], "approved_answers") if best and score >= 0.72 else None


def _fit(field: Field, resolution: Resolution | None) -> Resolution | None:
    """Turn a value into something this field accepts, or None when it does not fit."""
    if resolution is None:
        return None
    value = resolution.value
    if field.kind == "file":
        return resolution if hasattr(value, "exists") else None
    if field.kind == "checkbox":
        if isinstance(value, bool):
            return resolution
        answer = _yes_no(str(value))
        return Resolution(answer == "Yes", resolution.source) if answer else None
    if field.kind == "checkbox_group" and field.options:
        values = value if isinstance(value, list) else re.split(r"\s*\|\s*|\s*;\s*", str(value))
        chosen = [option for option in dict.fromkeys(choose_option(str(part), field.options) for part in values if str(part).strip()) if option]
        return Resolution(chosen, resolution.source) if chosen else None
    if field.kind in CHOICE_KINDS and field.options:
        option = choose_option(str(value), field.options)
        return Resolution(option, resolution.source) if option else None
    if field.kind in CHOICE_KINDS and field.kind != "combobox":
        return None
    if isinstance(value, (bool,)) or hasattr(value, "exists"):
        return None
    if field.kind in TEXT_KINDS or field.kind == "combobox":
        return resolution
    return None


def _saved_for(key: str, store: dict[str, str]) -> str | None:
    """A saved answer for this wording, or for a near-identical wording of the same question."""
    if store.get(key):
        return store[key]
    best, score = None, 0.0
    for saved_key, value in store.items():
        if not saved_key.startswith("q:") or not value:
            continue
        ratio = SequenceMatcher(None, key, saved_key).ratio()
        if ratio > score:
            best, score = value, ratio
    return best if score >= 0.9 else None


def resolve(field: Field, applicant: Applicant) -> Resolution | None:
    """An answer from verified sources only. Questions this leaves open go to the drafter."""
    if HONEYPOT.search(f"{field.label} {field.name} {field.placeholder}"):
        return None
    key = label_key(field.label)
    # 1. What the user answered for this question, during this run or before.
    for source, store in (("your_answer", applicant.run_answers), ("saved", applicant.saved)):
        value = _saved_for(key, store)
        if value:
            fitted = _fit(field, Resolution(value, source))
            if fitted:
                return fitted
    # 2. Verified facts and saved policy answers for questions we recognise.
    category = classify(field)
    if category:
        fitted = _fit(field, _fact(category, field, applicant))
        if fitted:
            return fitted
        if category in EEO_KEYS | {"privacy_consent"} or (category in YES_NO_KEYS and category != "previous_employee"):
            # Sensitive or policy questions are never guessed.
            return None
    # 3. A short approved answer for this application. Long ones are drafted with it as material.
    return _fit(field, _approved_answer(field, applicant)) if field.kind == "text" else None
