"""What a form field asks, and which of its options matches an answer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher


@dataclass
class Field:
    """One question on an application page, as read from the DOM."""

    id: str  # data-ap handle assigned by the page reader
    kind: str  # text, textarea, email, tel, url, number, date, select, radio, checkbox, checkbox_group, file, combobox, buttons, listbox
    label: str
    required: bool = False
    options: list[str] = field(default_factory=list)
    value: str = ""
    name: str = ""
    placeholder: str = ""
    accept: str = ""
    invalid: bool = False
    dom_id: str = ""
    context: str = ""  # text around a file input, such as the "Resume/CV" heading
    maxlength: int | None = None
    error: str = ""  # what the form said about the last answer, when it was rejected

    @property
    def filled(self) -> bool:
        return bool((self.value or "").strip())


# Ordered: the first matching rule wins, so specific rules come before broad ones.
RULES: list[tuple[str, str]] = [
    ("resume", r"\b(resume|résumé|cv)\b"),
    ("cover_letter", r"cover letter"),
    ("eeo_gender", r"\bgender\b|\bsex\b|pronoun"),
    ("eeo_race", r"\brace\b|ethnic|hispanic|latin[oaxe]|indigenous|aboriginal|visible minority|first nations"),
    ("eeo_veteran", r"veteran|military|armed forces"),
    ("eeo_disability", r"disabilit"),
    ("sponsorship", r"sponsor"),
    ("work_authorization", r"(legally |currently )?(authori[sz]ed|eligible|entitled|permitted|able) to work|work (permit|authori[sz]ation|eligibility)|right to work|citizen|permanent resident"),
    ("previous_employee", r"(previously|ever|before|currently|formerly)\b.{0,40}\b(work(ed)?|employ(ed)?|consult(ed)?)\b.{0,40}\b(for|at|with|by)\b|former employee"),
    ("relocation", r"relocat"),
    ("start_date", r"start date|when can you start|available to start|earliest .*start|availability date"),
    ("age_18", r"\b18\b.{0,20}(years|older|age)|age of (majority|18)|legal age"),
    ("salary", r"salary|compensation|pay (rate|expectation)|expected (pay|wage)|hourly rate"),
    ("how_heard", r"how did you (hear|find|learn|come across)|where did you (hear|find|see)|source of (your )?application|referral source"),
    ("referral_name", r"referr(ed|al)( by)?|who referred"),
    ("privacy_consent", r"\bconsent\b|privacy (policy|notice|statement)|terms (and|&) conditions|\bi (agree|acknowledge|certify|confirm|understand)\b|by (checking|submitting)"),
    ("preferred_name", r"preferred (first )?name|name you.{0,10}prefer|nickname"),
    ("first_name", r"(legal |given )?first name|given name|^first$"),
    ("last_name", r"(legal )?last name|family name|surname|^last$"),
    ("full_name", r"^(legal |full )?name$|full (legal )?name|^your name$"),
    ("email", r"e-?mail"),
    ("phone_type", r"(phone )?device type|phone type"),
    ("phone_country", r"(country|phone).{0,6}code"),
    ("phone_extension", r"extension|\bext\b"),
    ("phone", r"phone|mobile|\bcell\b"),
    ("linkedin", r"linked\s?in"),
    ("github", r"git\s?hub"),
    ("website", r"portfolio|personal (web)?site|^website|other website|\burl\b"),
    ("address_line1", r"address( line)? ?1|street( address)?|^address$|mailing address"),
    ("address_line2", r"address( line)? ?2|apartment|suite|unit"),
    ("postal_code", r"postal|zip"),
    ("city", r"^city\b|city/town|\btown\b|^city"),
    ("province", r"province|^state\b|state/province|region"),
    ("country", r"country"),
    ("location", r"location|where (are you|do you) (currently )?(live|located|based|reside)|city,? (and )?(state|province)"),
    ("school", r"school|university|college|institution"),
    ("degree", r"\bdegree\b|level of education|highest education"),
    ("discipline", r"discipline|major|field of study|program of study|area of study"),
    ("graduation", r"graduat|completion date|expected (end|finish)"),
    ("gpa", r"\bgpa\b|grade point"),
    ("current_company", r"current (company|employer)|^company$|^employer$"),
    ("current_title", r"current (title|position|role)|job title"),
    ("why_interested", r"why (are you|do you|would you).{0,40}(interest|want|apply|join)|interest(ed)? in (this|the|our)"),
]

# Fields meant to catch bots. The page reader skips them; the resolver refuses them too.
HONEYPOT = re.compile(r"robot|honeypot|leave (this )?(field )?(blank|empty)|do not (enter|fill|type)|bot field", re.I)

EEO_KEYS = {"eeo_gender", "eeo_race", "eeo_veteran", "eeo_disability"}
YES_NO_KEYS = {"work_authorization", "sponsorship", "relocation", "previous_employee", "age_18"}


def normalize(text: str) -> str:
    text = re.sub(r"[\*✱]+", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def label_key(label: str) -> str:
    """A stable key for remembering the answer to one question wording."""
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(label).lower()).strip("-")
    return f"q:{slug[:76]}"


def classify(field_or_label) -> str | None:
    label = field_or_label.label if isinstance(field_or_label, Field) else field_or_label
    text = normalize(label).lower()
    if isinstance(field_or_label, Field) and field_or_label.kind == "file":
        return classify_file(field_or_label)
    if not text:
        return None
    for key, pattern in RULES:
        if re.search(pattern, text):
            return key
    return None


def classify_file(field: Field) -> str | None:
    """resume, cover_letter, resume_autofill (a "fill the form from your resume" box), or None for other documents."""
    own = normalize(f"{field.label} {field.dom_id} {field.name}").lower()
    around = normalize(field.context).lower()
    for text in (own, around):
        if re.search(r"autofill|auto-fill|parse|apply with|quick apply|import", text):
            return "resume_autofill"
        if re.search(r"cover", text):
            return "cover_letter"
        if re.search(r"transcript|portfolio|writing sample|certificat|reference|other doc|additional", text):
            return None
        if re.search(r"\bresume|résumé|\bcv\b|curriculum", text):
            return "resume"
    # A generic upload box ("Upload a file", "Attach") that is not for another document is the resume slot.
    return "resume" if not around.strip() or re.search(r"upload|attach|choose|browse|drop|file", f"{own} {around}") else None


_DECLINE = re.compile(r"decline|prefer not|don.?t wish|do not wish|not wish to|choose not|rather not|not to (answer|disclose|say|self)|i don.?t want|not specified|no answer", re.I)


def is_decline(option: str) -> bool:
    return bool(_DECLINE.search(option or ""))


def _norm_option(text: str) -> str:
    return re.sub(r"[^a-z0-9+ ]", "", (text or "").lower()).strip()


def choose_option(answer: str, options: list[str]) -> str | None:
    """The option that means `answer`, or None when none clearly does."""
    if not options or answer is None:
        return None
    want = _norm_option(str(answer))
    if not want:
        return None
    cleaned = [(option, _norm_option(option)) for option in options if _norm_option(option) and not re.match(r"^(select|choose|please select|--)", _norm_option(option))]
    for option, norm in cleaned:
        if norm == want:
            return option
    if want in {"yes", "no"}:
        for option, norm in cleaned:
            if re.match(rf"^{want}\b", norm):
                return option
        return None
    if want == "decline":
        return next((option for option, _norm in cleaned if is_decline(option)), None)
    for option, norm in cleaned:
        if norm.startswith(want) or want.startswith(norm) and len(norm) >= 4:
            return option
    containing = [option for option, norm in cleaned if want in norm]
    if len(containing) == 1:
        return containing[0]
    best, score = None, 0.0
    for option, norm in cleaned:
        ratio = SequenceMatcher(None, want, norm).ratio()
        if ratio > score:
            best, score = option, ratio
    return best if score >= 0.85 else None
