"""Drive one application in one browser tab: look at the page, act, and stop when the user is needed.

The driver is state-driven, so it can stop at any point (sign-in, CAPTCHA, an unknown
question) and continue later from whatever page the tab shows. It never solves CAPTCHAs,
never fills hidden or honeypot fields, and reports `submitted` only when the employer's
confirmation page is on screen after the form was seen.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.services.autoapply.applicant import Applicant
from app.services.autoapply.fields import Field, classify, label_key, normalize
from app.services.autoapply.page import fill_field, page_errors, read_dropdown_options, read_fields
from app.services.autoapply.resolve import resolve

log = logging.getLogger(__name__)

CONFIRM_TEXT = re.compile(
    r"thank(s| you)[ ,!]*(so much )?for (applying|your application|submitting)|application (has been |was )?(successfully )?(submitted|received|sent)|"
    r"we('ve| have) (successfully )?received your application|successfully (submitted|applied)|your application (is|has been) (complete|submitted|on its way)|you('ve| have) (successfully )?applied",
    re.I,
)
CONFIRM_URL = re.compile(r"/(confirmation|thanks|thank-you|thankyou|application-submitted|submitted|success)(/|\?|$)", re.I)
# A bare "Apply" usually opens or scrolls to the form, so it is never treated as the final submit.
SUBMIT_TEXT = re.compile(r"^(submit( (my |your )?application)?|send( my)? application|complete (my )?application|finish( application)?)$", re.I)
NEXT_TEXT = re.compile(r"^(next|continue|save (and|&) continue|save and next|proceed|next step)$", re.I)
APPLY_TEXT = re.compile(r"^(apply( now| here| online| for (this|the) (job|position|role))?|start (your |my )?application|i'?m interested)$", re.I)
VERIFY_TEXT = re.compile(r"verif(y|ication) (code|your (e-?mail|account|identity))|enter the (code|verification)|one[- ]time (pass)?code|check your (e-?mail|inbox)", re.I)
BLOCKED_TEXT = re.compile(r"access denied|unusual (traffic|activity)|request (was |has been )?blocked|you have been blocked|automated (access|queries)|are you a robot", re.I)
# Sign-in pages run by another company (Google, Microsoft, Apple, LinkedIn, single sign-on providers).
# ApplyPilot never types anything there: the user signs in, and the run continues when they are back.
IDENTITY_HOSTS = re.compile(
    r"(^|\.)(accounts\.google\.com|accounts\.youtube\.com|login\.microsoftonline\.com|login\.live\.com|login\.microsoft\.com|appleid\.apple\.com|"
    r"okta\.com|oktapreview\.com|auth0\.com|onelogin\.com|login\.yahoo\.com|secure\.indeed\.com|passportyork\.yorku\.ca)(:\d+)?$",
    re.I,
)
IDENTITY_PATH = re.compile(r"linkedin\.com/(oauth|uas|checkpoint|login)|github\.com/(login|session)|facebook\.com/(login|dialog/oauth)", re.I)
SSO_TEXT = re.compile(r"^(sign (in|up)|log ?in|continue|register) (with|using|via) (google|linkedin|microsoft|apple|indeed|facebook|github|seek)\b", re.I)
SIGN_IN_TEXT = re.compile(r"\b(sign in|signin|log ?in|sign on|create (an |your )?account|welcome back|candidate (home|log ?in|sign ?in))\b", re.I)
# Visible "busy" indicators: forms are not read until they are gone (or a few seconds pass).
BUSY_JS = """() => [...document.querySelectorAll('[aria-busy="true"], [role="progressbar"], [data-automation-id="loadingSpinner"], .spinner, .loading-spinner, .loader')]
    .some((el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; })"""
SIGN_IN_JS = r"""(signInSource) => {
  const signIn = new RegExp(signInSource, 'i');
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const inputs = [...document.querySelectorAll('input, select, textarea')].filter((el) => visible(el) && !['hidden', 'checkbox', 'radio', 'submit', 'button', 'search', 'file'].includes((el.type || '').toLowerCase()) && !/search|keyword/i.test((el.name || '') + (el.id || '') + (el.placeholder || '') + (el.getAttribute('aria-label') || '')));
  const email = inputs.find((el) => el.type === 'email' || /e-?mail|user ?name|login|username/i.test([el.name, el.id, el.autocomplete, el.placeholder, el.getAttribute('aria-label')].join(' ')));
  const heading = [...document.querySelectorAll('h1, h2, h3, legend, [role="heading"]')].filter(visible).map((el) => el.textContent).join(' ') + ' ' + document.title;
  let emailStep = false;
  if (email && inputs.length <= 2) {
    const scope = email.closest('form, [role="dialog"], main, section') || document.body;
    const buttons = [...scope.querySelectorAll('button, input[type="submit"], [role="button"]')].filter(visible).map((el) => (el.innerText || el.value || '').trim());
    emailStep = signIn.test(heading) && buttons.some((text) => /^(continue|next|sign in|log ?in|sign on)$/i.test(text));
  }
  return {inputs: inputs.length, emailStep, signInHeading: signIn.test(heading)};
}"""


@dataclass
class Outcome:
    status: str  # submitted, needs_you, failed, filled (dry run)
    attention: str | None = None
    message: str = ""
    questions: list[dict] = field(default_factory=list)
    confirmation_text: str | None = None
    confirmation_url: str | None = None


def detect_platform(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    if "myworkdayjobs.com" in host or "myworkdaysite.com" in host or ".workday.com" in host:
        return "workday"
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    return "generic"


SUPPORT = {
    "greenhouse": ("full", "Fills and submits Greenhouse forms. No account needed."),
    "lever": ("full", "Fills and submits Lever forms. No account needed."),
    "ashby": ("full", "Fills and submits Ashby forms. No account needed."),
    "workday": ("assisted", "Workday needs you to sign in or create an account once per employer. ApplyPilot then fills each step."),
    "generic": ("assisted", "ApplyPilot opens the page and fills the fields it recognises. You may need to finish some steps."),
}


def start_url(platform: str, url: str) -> str:
    clean = url.split("#")[0]
    if platform == "lever" and not re.search(r"/apply/?$", urlparse(clean).path):
        return clean.rstrip("/") + "/apply"
    if platform == "ashby" and not re.search(r"/application/?$", urlparse(clean).path):
        return clean.rstrip("/") + "/application"
    return clean


class Driver:
    def __init__(self, page, platform: str, applicant: Applicant, *, submit_mode: str = "auto", drafter=None, accounts=None, letter_writer=None, navigator=None, recaller=None, dry_run: bool = False, may_submit=None, on_event=None):
        self.page = page
        self.platform = platform
        self.applicant = applicant
        self.submit_mode = submit_mode
        self.drafter = drafter
        # Signs in (and, if allowed, creates accounts) with the user's saved job-site password.
        self.accounts = accounts
        # Writes a cover letter only when a form requires one, and picks the next step on unfamiliar pages.
        self.letter_writer = letter_writer
        self.navigator = navigator
        # Finds a saved answer to the same question asked in other words (Claude Haiku).
        self.recaller = recaller
        self._recall_tried: set[str] = set()
        self._navigations = 0
        self._error_retries: set[str] = set()
        self._rejected: dict[str, str] = {}
        self._login_attempts: dict[str, int] = {}
        self._created: set[str] = set()
        self.dry_run = dry_run
        self.may_submit = may_submit or (lambda: True)
        self.on_event = on_event or (lambda message: None)
        self.seen_form = False
        self.submit_clicked = False
        self.filled = 0
        self._resume_uploaded = False
        self._waited: set[str] = set()
        # What was entered, by question: label, value, where it came from. Shown at the final review.
        self.filled_log: dict[str, dict] = {}
        self.documents: list[dict] = []
        # Claude's drafts by question key, the ones the user has reviewed, and corrections to retype.
        self.drafts: dict[str, dict] = {}
        self.approved: set[str] = set()
        self.refill: set[str] = set()
        self.final_review_done = False

    def approve(self, keys: list[str], corrected: list[str]) -> None:
        """The user reviewed these answers; corrected ones are typed again from their answers."""
        self.approved |= set(keys)
        self.refill |= set(corrected)
        for key in keys:
            if key in self.drafts:
                self.drafts[key]["status"] = "approved"

    def summary(self) -> list[dict]:
        return list(self.filled_log.values())

    def _log(self, item: Field, value, source: str, label: str | None = None, basis: str = "") -> None:
        shown = ", ".join(value) if isinstance(value, list) else (value.name if hasattr(value, "name") and item.kind == "file" else str(value))
        key = label_key(label or item.label) + (f"#{item.dom_id}" if item.kind == "file" else "")
        self.filled_log[key] = {
            "key": key,
            "kind": item.kind,
            "label": label or normalize(item.label)[:200] or item.kind,
            "value": shown[:600],
            "source": source,
            "basis": basis[:200],
            "page": urlparse(self.page.url).path[-80:],
        }

    # ------------------------------------------------------------------
    # Page state
    # ------------------------------------------------------------------

    def _body_text(self) -> str:
        try:
            return self.page.locator("body").inner_text(timeout=5000)[:20000]
        except Exception:  # noqa: BLE001
            return ""

    BUTTONS = 'button, input[type="submit"], a[role="button"], [data-automation-id="pageFooterNextButton"], [data-automation-id="bottom-navigation-next-button"]'

    def _buttons(self, pattern: re.Pattern) -> list:
        """Visible, enabled buttons whose text matches, read in one pass over the page."""
        try:
            items = self.page.evaluate(
                """(selector) => [...document.querySelectorAll(selector)].map((el, index) => {
                    const r = el.getBoundingClientRect(); const style = getComputedStyle(el);
                    const visible = r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    return {index, visible, enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
                            text: ((el.innerText || el.value || '') + '').replace(/\\s+/g, ' ').trim()};
                })""",
                self.BUTTONS,
            )
        except Exception:  # noqa: BLE001
            return []
        everything = self.page.locator(self.BUTTONS)
        return [everything.nth(item["index"]) for item in items if item["visible"] and item["enabled"] and pattern.match(item["text"])]

    def _snapshot(self) -> str:
        try:
            return self.page.evaluate("() => location.href + '|' + document.querySelectorAll('input,select,textarea,button').length + '|' + (document.body ? document.body.innerText.length : 0)")
        except Exception:  # noqa: BLE001
            return ""

    def _settle(self, before: str, limit_ms: int = 6000) -> None:
        """Wait until the page changes after a click (or the limit passes), then let it finish rendering."""
        waited = 0
        while waited < limit_ms:
            self.page.wait_for_timeout(200)
            waited += 200
            if self._snapshot() != before:
                break
        self.page.wait_for_timeout(500)
        self.wait_until_ready(6000)

    def captcha_on_screen(self) -> bool:
        frames = self.page.locator('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare.com"], iframe[title*="challenge" i]')
        for i in range(min(frames.count(), 10)):
            frame = frames.nth(i)
            try:
                src = frame.get_attribute("src") or ""
                if "size=invisible" in src or frame.evaluate("(el) => !!el.closest('.grecaptcha-badge')"):
                    continue
                box = frame.bounding_box()
                if not box or not frame.is_visible():
                    continue
                # A challenge (picture grid) is large; a visible "I'm not a robot" checkbox is a wide strip.
                if (box["width"] >= 150 and box["height"] >= 150) or ("anchor" in src and box["width"] >= 250 and box["height"] >= 60):
                    if box["y"] < 4000 and box["x"] > -100:
                        return True
            except Exception:  # noqa: BLE001
                continue
        return bool(re.search(r"verify you are human|press (and|&) hold|i'?m not a robot", self._body_text()[:4000], re.I)) and not self.page.locator("form input:visible").count()

    def sign_in_state(self) -> str | None:
        """What kind of sign-in the page shows: identity_provider, password, sso_choice, email_step, or None."""
        url = self.page.url or ""
        if IDENTITY_HOSTS.search(urlparse(url).netloc) or IDENTITY_PATH.search(url):
            return "identity_provider"
        if self.page.locator('input[type="password"]:visible').count() > 0:
            return "password"
        try:
            info = self.page.evaluate(SIGN_IN_JS, SIGN_IN_TEXT.pattern)
        except Exception:  # noqa: BLE001
            return None
        if info["emailStep"] and not self.seen_form:
            return "email_step"  # an email box next to "Continue with Google": the saved email can be used
        if info["inputs"] <= 2 and info["signInHeading"] and self._clickables(SSO_TEXT):
            return "sso_choice"
        return None

    def login_on_screen(self) -> bool:
        return self.sign_in_state() is not None

    def verification_on_screen(self) -> bool:
        return bool(VERIFY_TEXT.search(self._body_text()[:5000])) and self.page.locator("input:visible").count() <= 3

    def form_on_screen(self) -> bool:
        """An application form (not a search box or a sign-in) is visible."""
        try:
            fields = [item for item in read_fields(self.page) if not re.search(r"search|keyword", item.label, re.I)]
        except Exception:  # noqa: BLE001
            return False
        return len([item for item in fields if item.kind != "file"]) >= 2 or any(item.kind == "file" for item in fields)

    def _clickables(self, pattern: re.Pattern) -> list[str]:
        """Text of visible buttons and links that match (sign-in choices are often links or divs)."""
        try:
            texts = self.page.evaluate(
                """() => [...document.querySelectorAll('button, a, [role="button"], input[type="submit"], input[type="button"]')].filter((el) => {
                    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                }).map((el) => ((el.innerText || el.value || el.getAttribute('aria-label') || '') + '').replace(/\\s+/g, ' ').trim()).slice(0, 300)"""
            )
        except Exception:  # noqa: BLE001
            return []
        return [text for text in texts if pattern.match(text)]

    def wait_until_ready(self, limit_ms: int = 8000) -> None:
        """Let the page finish loading: network quiet for a moment and no spinner on screen."""
        try:
            self.page.wait_for_load_state("networkidle", timeout=2500)
        except Exception:  # noqa: BLE001 - some sites never go quiet
            pass
        waited = 0
        while waited < limit_ms:
            try:
                busy = self.page.evaluate(BUSY_JS)
            except Exception:  # noqa: BLE001
                return
            if not busy:
                return
            self.page.wait_for_timeout(300)
            waited += 300

    def adopt_new_tab(self, owned=()) -> bool:
        """Follow a tab this one opened (for example, the form opening in a new tab). Sign-in pop-ups are left alone."""
        try:
            pages = self.page.context.pages
        except Exception:  # noqa: BLE001
            return False
        for candidate in reversed(pages):
            if candidate is self.page or candidate in owned or candidate.is_closed():
                continue
            try:
                opener = candidate.opener()
            except Exception:  # noqa: BLE001
                opener = None
            if opener is not self.page:
                continue
            url = candidate.url or ""
            if not url.startswith("http") or IDENTITY_HOSTS.search(urlparse(url).netloc) or IDENTITY_PATH.search(url):
                continue
            self.page = candidate
            try:
                candidate.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            self.on_event(f"Following the new tab ({urlparse(url).netloc}).")
            return True
        return False

    def confirmation_on_screen(self) -> str | None:
        if not self.seen_form:
            return None
        if self._buttons(SUBMIT_TEXT) or self._buttons(NEXT_TEXT):
            return None
        text = self._body_text()
        match = CONFIRM_TEXT.search(text)
        if match or CONFIRM_URL.search(urlparse(self.page.url).path):
            if match:
                start = max(0, match.start() - 120)
                return re.sub(r"\s+", " ", text[start : match.end() + 240]).strip()
            return re.sub(r"\s+", " ", text[:360]).strip()
        return None

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _enter_application(self) -> bool:
        """Click through from a job posting to the application form. Returns True if it clicked something."""
        page = self.page
        # Career sites often embed the real form (Greenhouse, Lever, Ashby, Workday) in an iframe; open it directly.
        embedded = None
        for frame in page.frames[1:]:
            try:
                if detect_platform(frame.url) != "generic" or frame.locator("input:visible, textarea:visible").count() >= 3:
                    embedded = frame.url
                    break
            except Exception:  # noqa: BLE001
                continue
        if embedded and embedded.startswith("http") and embedded != page.url:
            platform = detect_platform(embedded)
            self.platform = platform if platform != "generic" else self.platform
            self.on_event(f"The form is hosted by {platform.title() if platform != 'generic' else 'another page'}. Opening it directly.")
            page.goto(start_url(self.platform, embedded), wait_until="domcontentloaded", timeout=45000)
            return True
        if self.platform == "workday":
            decline = page.locator('[data-automation-id="legalNoticeDeclineButton"]:visible')
            if decline.count():
                decline.first.click()  # Decline optional cookies; it does not affect applying.
                page.wait_for_timeout(500)
            for automation_id in ("applyManually", "adventureButton"):
                target = page.locator(f'[data-automation-id="{automation_id}"]:visible')
                if target.count():
                    self.on_event("Opening the Workday application.")
                    before = self._snapshot()
                    target.first.click()
                    self._settle(before)
                    return True
            return False
        buttons = self._buttons(APPLY_TEXT)
        if not buttons:
            links = page.locator("a:visible")
            for i in range(min(links.count(), 80)):
                item = links.nth(i)
                try:
                    if APPLY_TEXT.match((item.inner_text(timeout=500) or "").strip()):
                        buttons = [item]
                        break
                except Exception:  # noqa: BLE001
                    continue
        if not buttons:
            return False
        before = len(page.context.pages)
        snapshot = self._snapshot()
        self.on_event("Opening the application form.")
        buttons[0].click()
        self._settle(snapshot)
        if len(page.context.pages) > before:
            self.page = page.context.pages[-1]
            self.page.wait_for_load_state("domcontentloaded")
        return True

    def _upload(self, item: Field, kind: str) -> Field | None:
        """Attach the approved document for this slot. Returns the field if the user must deal with it."""
        if kind == "resume_autofill":
            return None  # "Fill the form from my resume" boxes would overwrite verified answers.
        if kind == "cover_letter" and self.applicant.cover_letter_path is None and item.required and not self.dry_run:
            self._write_letter()
        path = self.applicant.resume_path if kind == "resume" else self.applicant.cover_letter_path if kind == "cover_letter" else None
        if path is None:
            return item if item.required else None
        if item.value == path.name or self.dry_run:
            return None
        if kind == "resume" and self._resume_uploaded and not item.required:
            return None
        if fill_field(self.page, item, path):
            if kind == "resume":
                self._resume_uploaded = True
            self.filled += 1
            self._log(item, path, "approved_document", "Resume" if kind == "resume" else "Cover letter")
            record = {"kind": kind, "file": path.name, "slot": normalize(item.context or item.label)[:120]}
            if kind == "resume":
                record.update({"version_id": self.applicant.resume_version_id, "title": self.applicant.resume_title, "sha256": self.applicant.resume_sha256})
            self.documents = [doc for doc in self.documents if doc.get("slot") != record["slot"]] + [record]
            self.on_event(f"Attached {'your tailored resume' if kind == 'resume' else 'your cover letter'} ({path.name}).")
            return None
        return item

    def _navigate(self, problem: str) -> tuple[bool, str]:
        """Ask the navigator for the next click. Returns (clicked, reason when a person is needed)."""
        if self.navigator is None or self._navigations >= 6:
            return False, ""
        self._navigations += 1
        goal = f"Fill in the application for {self.applicant.job_title or 'this job'} at {self.applicant.company}."
        try:
            action, index, detail = self.navigator(self.page, goal, problem, self._body_text(), self.seen_form)
        except Exception:  # noqa: BLE001 - navigation help is optional
            log.exception("Navigation help failed")
            return False, ""
        if action == "wait":
            self.page.wait_for_timeout(3000)
            return True, ""
        if action != "click" or index is None:
            return False, detail
        before = len(self.page.context.pages)
        snapshot = self._snapshot()
        self.on_event(f"Clicked \u201c{detail}\u201d to continue.")
        self._click(self.page.locator(f'[data-ap-nav="{index}"]').first)
        self._settle(snapshot)
        if len(self.page.context.pages) > before:
            self.page = self.page.context.pages[-1]
            self.page.wait_for_load_state("domcontentloaded")
        return True, ""

    def _fix_rejected(self, errors: list[str]) -> None:
        """The form rejected some answers: forget those drafts so Claude answers again, told what was wrong."""
        message = "; ".join(errors)[:300]
        for item in read_fields(self.page):
            if item.invalid or (item.required and not item.filled):
                key = label_key(item.label)
                self._rejected[key] = message
                if key in self.drafts and self.drafts[key]["status"] in {"drafted", "pending"}:
                    del self.drafts[key]
                self.refill.add(key)
        self.on_event("The form rejected some answers. Trying them again.")

    def _write_letter(self) -> None:
        """This form requires a cover letter: write one now (it is not written in advance, to save AI credit)."""
        if self.letter_writer is None or self.applicant.cover_letter_path is not None:
            return
        self.on_event("This form requires a cover letter, so ApplyPilot is writing one.")
        written = self.letter_writer()
        if written:
            self.applicant.cover_letter_path, self.applicant.cover_letter_text = written

    def _fill_page(self) -> tuple[list[Field], int, list[str]]:
        """Fill the page. Returns (fields the user must answer, number filled, drafted keys awaiting review)."""
        from app.services.autoapply.fields import classify_file

        filled_now = 0
        must_answer: dict[str, Field] = {}
        open_fields: dict[str, Field] = {}
        for _pass in range(3):
            progress = 0
            open_fields = {}
            for item in read_fields(self.page):
                if item.kind == "checkbox" and len(item.options) > 1:
                    item.kind = "checkbox_group"
                key = label_key(item.label)
                if item.kind == "file":
                    problem = self._upload(item, classify_file(item))
                    if problem is not None:
                        must_answer[key + item.dom_id] = problem
                    continue
                if (item.filled and not item.invalid) and key not in self.refill:
                    continue
                if item.kind in {"combobox", "listbox"} and not item.options:
                    item.options = read_dropdown_options(self.page, item)
                result = resolve(item, self.applicant)
                if result is None:
                    if normalize(item.label):
                        open_fields[key] = item
                    continue
                if fill_field(self.page, item, result.value):
                    progress += 1
                    self.refill.discard(key)
                    must_answer.pop(key, None)
                    self._log(item, result.value, result.source)
                elif item.required:
                    must_answer[key] = item
            filled_now += progress
            if not progress:
                break
            self.page.wait_for_timeout(600)

        # Answers you confirmed before, for the same question worded differently.
        if open_fields:
            filled_now += self._recall(open_fields)

        # Questions no verified source answers: Claude drafts them (once per question) for review.
        if open_fields and self.drafter is not None:
            from app.services.autoapply.draft import Draft, needs_user

            new, drafts = [], {}
            for key, item in open_fields.items():
                if key in self.drafts:
                    continue
                item.error = self._rejected.get(key, "")
                category = classify(item)
                if needs_user(item) or (category in self.applicant.values and not self.applicant.values.get(category)):
                    # Personal details and profile facts you have not given are asked, never drafted.
                    drafts[key] = Draft(key, "ask_user", basis="ApplyPilot does not guess personal details.")
                else:
                    new.append(item)
            letters = [item for item in new if classify(item) == "cover_letter" and item.kind == "textarea"]
            for item in letters:
                new.remove(item)
                if item.required:
                    self._write_letter()
                if self.applicant.cover_letter_text:
                    drafts[label_key(item.label)] = Draft(label_key(item.label), "answer", self.applicant.cover_letter_text, basis="Cover letter written for this job")
            if new:
                drafts.update(self.drafter(new, self.applicant))
                # A draft that failed the checks gets one redo, told what was wrong, before anyone is asked.
                redo = [item for item in new if drafts.get(label_key(item.label)) and drafts[label_key(item.label)].action == "answer" and drafts[label_key(item.label)].problems]
                for item in redo:
                    item.error = " ".join(drafts[label_key(item.label)].problems)
                if redo:
                    drafts.update(self.drafter(redo, self.applicant))
            for key, item in open_fields.items():
                if key not in self.drafts and key in drafts:
                    found = drafts[key]
                    self.drafts[key] = {
                        "label": normalize(item.label)[:300], "kind": item.kind, "options": item.options[:60], "category": classify(item),
                        "action": found.action, "answer": found.answer, "basis": found.basis, "problems": found.problems,
                        "required": item.required, "status": "pending",
                    }
                draft = self.drafts.get(key)
                if draft is None:
                    if item.required:
                        must_answer[key] = item
                    continue
                if draft["action"] == "answer" and not draft["problems"] and draft["status"] == "pending":
                    if fill_field(self.page, item, draft["answer"]):
                        filled_now += 1
                        draft["status"] = "drafted"
                        self._log(item, draft["answer"], "claude", basis=draft.get("basis", ""))
                        continue
                if draft["status"] in {"drafted", "approved"}:
                    continue
                if item.required or draft["action"] == "answer":
                    must_answer[key] = item  # Claude asked the user, or its draft did not pass the checks.
        elif open_fields:
            must_answer.update({key: item for key, item in open_fields.items() if item.required})

        # Re-check: fields the user or the page filled in meanwhile are no longer open.
        current = {label_key(item.label): item for item in read_fields(self.page)}
        still = [item for key, item in must_answer.items() if item.kind == "file" or (key in current and (not current[key].filled or current[key].invalid))]
        # Drafted answers are typed and the run moves on; they are all listed at the final review.
        pending: list[str] = []
        return still, filled_now, pending

    def _recall(self, open_fields: dict[str, Field]) -> int:
        """Fill questions you answered before in other words. Removes them from open_fields."""
        from app.services.autoapply.draft import needs_user
        from app.services.autoapply.memory import local_match
        from app.services.autoapply.resolve import Resolution, _fit

        saved = {**self.applicant.saved, **self.applicant.run_answers}
        found: dict[str, str] = {}
        for key, item in open_fields.items():
            if key in self.drafts or key in self._rejected:
                continue
            match = local_match(item.label, saved)
            if match:
                found[key] = match[0]
        # Only questions that would otherwise go to you are worth a model call: the drafter already sees saved answers.
        ask = [
            item for key, item in open_fields.items()
            if key not in found and key not in self.drafts and key not in self._rejected and key not in self._recall_tried
            and (self.drafter is None or needs_user(item) or (classify(item) in self.applicant.values and not self.applicant.values.get(classify(item))))
        ]
        if ask and self.recaller is not None and any(name.startswith("q:") for name in saved):
            self._recall_tried |= {label_key(item.label) for item in ask}
            try:
                found.update({key: value for key, value in self.recaller(ask, saved).items() if key in open_fields})
            except Exception:  # noqa: BLE001 - matching help is optional
                log.exception("Saved-answer matching failed")
        filled = 0
        for key, saved_key in found.items():
            item = open_fields.get(key)
            value = saved.get(saved_key)
            if item is None or not value:
                continue
            fitted = _fit(item, Resolution(value, "saved"))
            if fitted and fill_field(self.page, item, fitted.value):
                self._log(item, fitted.value, "saved", basis=f"Your saved answer to \u201c{saved_key[2:].replace('-', ' ')}\u201d")
                del open_fields[key]
                self.refill.discard(key)
                filled += 1
        return filled

    def _question(self, item: Field) -> dict:
        key = label_key(item.label)
        category = classify(item)
        draft = self.drafts.get(key) or {}
        suggestion = draft.get("answer") if draft.get("action") == "answer" else ""
        if item.kind == "file":
            return {
                "key": key + item.dom_id, "label": normalize(item.context or item.label)[:300] or "Document upload", "kind": "file", "options": [], "category": "document",
                "remember": False, "status": "needs_answer", "draft": "", "basis": "", "problems": ["ApplyPilot has no approved document for this upload. Attach it in the browser window."],
            }
        return {
            "key": key,
            "label": normalize(item.label)[:300] or "(unlabelled field)",
            "kind": item.kind,
            "options": item.options[:60],
            "category": category,
            # Answers to general questions are remembered; answers specific to one employer are not.
            "remember": category not in {"why_interested", "salary", "referral_name"} and item.kind != "textarea",
            "required": item.required,
            "status": "needs_answer",
            "draft": " | ".join(suggestion) if isinstance(suggestion, list) else (suggestion or ""),
            "basis": draft.get("basis", ""),
            "problems": draft.get("problems", []),
        }

    def _review_item(self, key: str) -> dict:
        draft = self.drafts[key]
        answer = draft["answer"]
        return {
            "key": key, "label": draft["label"], "kind": draft["kind"], "options": draft["options"], "category": draft["category"],
            "remember": draft["category"] not in {"why_interested", "salary", "referral_name"} and draft["kind"] != "textarea",
            "required": draft["required"], "status": "drafted", "draft": " | ".join(answer) if isinstance(answer, list) else str(answer),
            "basis": draft["basis"], "problems": [],
        }

    # ------------------------------------------------------------------
    # Telling the user, in the browser window, that ApplyPilot is waiting
    # ------------------------------------------------------------------

    BANNER_ID = "applypilot-waiting-banner"

    def show_banner(self, message: str) -> None:
        """A small note at the bottom of the employer's page. It is local to this tab and never submitted."""
        try:
            self.page.evaluate(
                """([id, message]) => {
                    document.getElementById(id)?.remove();
                    const box = document.createElement('div');
                    box.id = id;
                    box.setAttribute('role', 'status');
                    box.style.cssText = 'position:fixed;left:16px;right:16px;bottom:16px;z-index:2147483647;background:#4338ca;color:#fff;font:14px/1.4 -apple-system,system-ui,sans-serif;padding:12px 16px;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.25)';
                    const text = document.createElement('div');
                    text.textContent = 'ApplyPilot is waiting for you: ' + message;
                    const link = document.createElement('a');
                    link.href = 'http://localhost:3000/applications';
                    link.target = '_blank';
                    link.textContent = 'Open ApplyPilot to continue';
                    link.style.cssText = 'color:#fff;font-weight:600;text-decoration:underline;display:inline-block;margin-top:4px';
                    box.append(text, link);
                    document.body.append(box);
                }""",
                [self.BANNER_ID, message[:300]],
            )
        except Exception:  # noqa: BLE001 - the note is a convenience
            pass

    def hide_banner(self) -> None:
        try:
            self.page.evaluate("(id) => document.getElementById(id)?.remove()", self.BANNER_ID)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Signing in and creating accounts
    # ------------------------------------------------------------------

    def _click(self, locator) -> None:
        try:
            locator.click(timeout=5000)
        except Exception:  # noqa: BLE001 - Workday sometimes covers its buttons with a click-catching layer
            locator.click(timeout=5000, force=True)

    def _wait_for_sign_in(self, seconds: float = 15) -> str:
        """signed_in, verify, error, or still (nothing changed)."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.page.wait_for_timeout(700)
            if VERIFY_TEXT.search(self._body_text()[:4000]):
                return "verify"
            if not self.login_on_screen():
                return "signed_in"
            if page_errors(self.page):
                return "error"
        return "still"

    def _sign_in(self) -> Outcome | None:
        """Try the saved password. Returns None when signed in, or why the user is needed."""
        host = urlparse(self.page.url).netloc
        company = self.applicant.company
        state = self.sign_in_state()
        if state in {"identity_provider", "sso_choice"}:
            # Google, LinkedIn, Microsoft and similar sign-ins are always done by the user.
            return Outcome("needs_you", "login", f"Sign in to {company} in the ApplyPilot browser window (with Google, LinkedIn, or your email, whichever you use there). ApplyPilot continues by itself once you are signed in.")
        credentials = self.accounts.credentials() if self.accounts is not None else None
        if not credentials:
            return Outcome("needs_you", "login", f"Sign in or create your account for {company} in the ApplyPilot browser window. ApplyPilot continues by itself once you are signed in. To have ApplyPilot sign in for you, save your job-site password in Settings.")
        email, password = credentials
        # Count attempts per site and password: never retry a rejected password (sites lock accounts).
        import hashlib

        attempt_key = host + hashlib.sha256(password.encode()).hexdigest()[:12]
        if self._login_attempts.get(attempt_key, 0) >= 1 and host not in self._created:
            return Outcome("needs_you", "login", f"ApplyPilot could not sign in to {company} with your saved password. Sign in yourself in the browser window (ApplyPilot continues by itself), or update the password in Settings.")
        self._login_attempts[attempt_key] = self._login_attempts.get(attempt_key, 0) + 1
        if state == "email_step":
            # Email first, password on the next screen.
            outcome = self._email_step(email)
            if outcome is not None or not self.login_on_screen():
                return outcome
        result = self._workday_sign_in(host, email, password) if self.platform == "workday" else self._generic_sign_in(host, email, password)
        password = None  # noqa: F841 - do not keep the password around longer than needed
        return result

    def _email_step(self, email: str) -> Outcome | None:
        company = self.applicant.company
        field = self.page.locator('input[type="email"]:visible, input[autocomplete="username"]:visible, input[name*="email" i]:visible, input[id*="email" i]:visible, input[name*="user" i]:visible, input[id*="user" i]:visible')
        buttons = self._buttons(re.compile(r"^(continue|next|sign in|log ?in|sign on)$", re.I))
        if not field.count() or not buttons:
            return Outcome("needs_you", "login", f"Sign in to {company} in the browser window. ApplyPilot continues by itself once you are signed in.")
        self.on_event(f"Entering your email on {urlparse(self.page.url).netloc}.")
        self._fill_secret(field.first, email)
        before = self._snapshot()
        self._click(buttons[0])
        self._settle(before, 8000)
        if self.verification_on_screen():
            return Outcome("needs_you", "verification", f"{company} sent you a code or link. Enter it in the browser window; ApplyPilot continues by itself.")
        if self.sign_in_state() in {None, "password"}:
            return None  # on to the password, or the site signed you in
        return Outcome("needs_you", "login", f"Sign in to {company} in the ApplyPilot browser window. ApplyPilot continues by itself once you are signed in.")

    def _fill_secret(self, locator, value: str) -> None:
        locator.fill("")
        locator.fill(value)

    def _workday_sign_in(self, host: str, email: str, password: str) -> Outcome | None:
        page = self.page
        company = self.applicant.company
        ids = lambda name: page.locator(f'[data-automation-id="{name}"]:visible')  # noqa: E731
        if ids("createAccountSubmitButton").count() and ids("signInLink").count() and host not in self._created:
            # Workday opens on "Create Account"; try signing in first.
            before = self._snapshot()
            self._click(ids("signInLink").first)
            self._settle(before, 4000)
        if ids("signInSubmitButton").count() or (ids("password").count() and not ids("verifyPassword").count()):
            self.on_event(f"Signing in to {host} with your saved email.")
            self._fill_secret(ids("email").first, email)
            self._fill_secret(ids("password").first, password)
            button = ids("signInSubmitButton")
            if button.count():
                self._click(button.first)
            else:
                ids("password").first.press("Enter")
            state = self._wait_for_sign_in()
            if state == "signed_in":
                self.accounts.record(host, created=False)
                self.on_event(f"Signed in to {host}.")
                return None
            if state == "verify":
                return Outcome("needs_you", "verification", f"{company}'s Workday asks you to verify your email. Open the email from Workday and click the link, then click Continue here. ApplyPilot will sign in.")
            if not self.accounts.allow_create or host in self._created:
                return Outcome("needs_you", "login", f"Your saved password did not work for {company} (or you have no account there yet). Sign in or create the account in the browser window, or turn on account creation in Settings. ApplyPilot continues by itself once you are in.")
            link = ids("createAccountLink")
            if not link.count():
                return Outcome("needs_you", "login", f"ApplyPilot could not sign in to {company}. Sign in yourself in the browser window; ApplyPilot continues by itself.")
            before = self._snapshot()
            self._click(link.first)
            self._settle(before, 4000)
        if ids("createAccountSubmitButton").count():
            if not self.accounts.allow_create:
                return Outcome("needs_you", "login", f"Create your {company} account in the browser window (or turn on account creation in Settings). ApplyPilot continues by itself once you are in.")
            self.on_event(f"Creating your account on {host}.")
            self._created.add(host)
            self._fill_secret(ids("email").first, email)
            self._fill_secret(ids("password").first, password)
            if ids("verifyPassword").count():
                self._fill_secret(ids("verifyPassword").first, password)
            consent = page.locator('[data-automation-id="createAccountCheckbox"]')
            if consent.count() and not consent.first.is_checked():
                try:
                    consent.first.check(timeout=4000)
                except Exception:  # noqa: BLE001
                    consent.first.evaluate("(el) => (el.closest('label') || el).click()")
            self._click(ids("createAccountSubmitButton").first)
            state = self._wait_for_sign_in()
            if state in {"signed_in", "verify"}:
                self.accounts.record(host, created=True)
            if state == "signed_in":
                self.on_event(f"Created your account on {host} and signed in.")
                return None
            if state == "verify":
                return Outcome("needs_you", "verification", f"ApplyPilot created your {company} account. Workday sent a verification email to {email}: click the link in it, then click Continue here. ApplyPilot will sign in.")
            errors = page_errors(page)
            return Outcome("needs_you", "login", f"ApplyPilot could not create the {company} account" + (f": {'; '.join(errors[:2])}" if errors else ".") + " Finish it in the browser window; ApplyPilot continues by itself.")
        return Outcome("needs_you", "login", f"Sign in to {company} in the browser window. ApplyPilot continues by itself once you are signed in.")

    def _generic_sign_in(self, host: str, email: str, password: str) -> Outcome | None:
        page = self.page
        company = self.applicant.company
        username = page.locator('input[type="email"]:visible, input[autocomplete="username"]:visible, input[name*="email" i]:visible, input[id*="email" i]:visible, input[name*="user" i]:visible')
        secret = page.locator('input[type="password"]:visible')
        if not secret.count():
            return Outcome("needs_you", "login", f"Sign in to {company} in the browser window. ApplyPilot continues by itself once you are signed in.")
        self.on_event(f"Signing in to {host} with your saved email.")
        if username.count():
            self._fill_secret(username.first, email)
        self._fill_secret(secret.first, password)
        buttons = self._buttons(re.compile(r"^(sign in|log in|login|sign on|continue|next|submit)$", re.I))
        if buttons:
            self._click(buttons[0])
        else:
            secret.first.press("Enter")
        state = self._wait_for_sign_in()
        if state == "signed_in":
            self.accounts.record(host, created=False)
            self.on_event(f"Signed in to {host}.")
            return None
        if state == "verify":
            return Outcome("needs_you", "verification", f"{company} wants a verification code or email confirmation. Complete it in the browser window; ApplyPilot continues by itself.")
        return Outcome("needs_you", "login", f"Your saved password did not work for {company}. Sign in yourself in the browser window (ApplyPilot continues by itself), or create the account there.")

    def _wait_for_result(self, seconds: int = 30) -> Outcome | None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.page.wait_for_timeout(1500)
            confirmation = self.confirmation_on_screen()
            if confirmation:
                return Outcome("submitted", confirmation_text=confirmation, confirmation_url=self.page.url)
            if self.captcha_on_screen():
                return Outcome("needs_you", "captcha", "The site is showing a CAPTCHA. Solve it in the ApplyPilot browser window. ApplyPilot continues by itself afterwards.")
            errors = page_errors(self.page)
            if errors and self._buttons(SUBMIT_TEXT):
                return self._errors_outcome(errors)
        return None

    def _errors_outcome(self, errors: list[str]) -> Outcome:
        invalid = [item for item in read_fields(self.page) if item.invalid or (item.required and not item.filled)]
        return Outcome(
            "needs_you",
            "questions",
            "The form reported a problem: " + "; ".join(errors[:3]),
            [self._question(item) for item in invalid[:20]],
        )

    def advance(self, max_steps: int = 25) -> Outcome:
        last_signature, repeats = None, 0
        # Each call may wait again for slow pages (for example, right after the user signs in).
        self._waited = set()
        self.hide_banner()
        for _step in range(max_steps):
            page = self.page
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(300)
            self.wait_until_ready()
            confirmation = self.confirmation_on_screen()
            if confirmation:
                return Outcome("submitted", confirmation_text=confirmation, confirmation_url=page.url)
            if self.captcha_on_screen():
                return Outcome("needs_you", "captcha", "The site is showing a CAPTCHA. Solve it in the ApplyPilot browser window. ApplyPilot continues by itself afterwards.")
            if self.login_on_screen():
                outcome = self._sign_in()
                if outcome is not None:
                    return outcome
                self._waited = set()  # the next page is new: wait for it again
                continue
            body = self._body_text()
            if self.verification_on_screen():
                return Outcome("needs_you", "verification", "The site wants a verification code or email confirmation. Complete it in the browser window; ApplyPilot continues by itself.")
            if BLOCKED_TEXT.search(body[:3000]) and not page.locator("form input:visible").count():
                return Outcome("needs_you", "blocked", "The site blocked automated access. ApplyPilot will not try to get around that. Finish this one yourself in the browser window.")

            fields = [item for item in read_fields(page) if item.kind != "file" or item.label or item.required]
            meaningful = [item for item in fields if item.kind != "file" and not re.search(r"search|keyword", item.label, re.I)]
            if not meaningful and not [item for item in fields if item.kind == "file"]:
                review_page = self.seen_form and (self._buttons(SUBMIT_TEXT) or self._buttons(NEXT_TEXT) or page.locator('[data-automation-id="pageFooterNextButton"]:visible').count())
                wait_key = self._snapshot()
                if not review_page and wait_key not in self._waited:
                    # Single-page apps (Workday especially) render the form a while after the page changes.
                    self._waited.add(wait_key)
                    try:
                        page.wait_for_selector(
                            "input:visible, select:visible, textarea:visible, [data-automation-id='adventureButton']:visible, [data-automation-id='applyManually']:visible, "
                            "[data-automation-id='pageFooterNextButton']:visible, button[type='submit']:visible",
                            timeout=15000,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    continue
                if not review_page:
                    if self._enter_application():
                        continue
                    clicked, reason = self._navigate("No application form is visible on this page yet.")
                    if clicked:
                        continue
                    return Outcome("needs_you", "error", (reason + " " if reason else "") + "ApplyPilot could not find the application form on this page. Open it in the browser window, then click Continue.")
            if not self.seen_form and not self._buttons(SUBMIT_TEXT) and not self._buttons(NEXT_TEXT) and not page.locator('[data-automation-id="pageFooterNextButton"]:visible').count():
                # A careers page with search boxes or a newsletter form, not the application: click Apply first.
                if self._enter_application():
                    continue
            self.seen_form = True

            unresolved, filled_now, pending = self._fill_page()
            self.filled += filled_now
            if filled_now:
                self.on_event(f"Filled {filled_now} field{'s' if filled_now != 1 else ''} on {urlparse(page.url).netloc}.")
            if unresolved or pending:
                items = [self._review_item(key) for key in pending] + [self._question(item) for item in unresolved]
                parts = []
                if pending:
                    parts.append(f"Claude drafted {len(pending)} answer{'s' if len(pending) != 1 else ''} for you to check")
                if unresolved:
                    parts.append(f"{len(unresolved)} question{'s' if len(unresolved) != 1 else ''} need{'s' if len(unresolved) == 1 else ''} your answer")
                return Outcome("needs_you", "review_answers" if pending else "questions", " and ".join(parts) + ". Nothing has been submitted.", items)

            next_buttons = [button for button in self._buttons(NEXT_TEXT)]
            submit_buttons = self._buttons(SUBMIT_TEXT)
            if not next_buttons and not submit_buttons and self.platform != "workday":
                # A form whose final button says something like "Apply": its own submit button.
                own = page.locator('form:has(input:visible, textarea:visible) button[type="submit"]:visible, form:has(input:visible, textarea:visible) input[type="submit"]:visible')
                if own.count() == 1:
                    submit_buttons = [own.first]
            if self.platform == "workday":
                footer = page.locator('[data-automation-id="pageFooterNextButton"]:visible, [data-automation-id="bottom-navigation-next-button"]:visible')
                if footer.count():
                    label = (footer.first.inner_text() or "").strip()
                    (submit_buttons, next_buttons) = ([footer.first], []) if re.match(r"^submit", label, re.I) else ([], [footer.first])
            signature = (page.url, tuple(sorted(label_key(item.label) for item in fields))[:40])
            repeats = repeats + 1 if signature == last_signature else 0
            last_signature = signature
            if repeats >= 1:
                errors = page_errors(page)
                if errors and str(signature) not in self._error_retries:
                    self._error_retries.add(str(signature))
                    self._fix_rejected(errors)
                    last_signature, repeats = None, 0
                    continue
            if repeats >= 2:
                errors = page_errors(page)
                if errors:
                    return self._errors_outcome(errors)
                clicked, reason = self._navigate("Clicking Next did not change the page.")
                if clicked:
                    last_signature, repeats = None, 0
                    continue
                return Outcome("needs_you", "error", (reason + " " if reason else "") + "ApplyPilot is not making progress on this page. Check it in the browser window, then click Continue.")

            if next_buttons and not submit_buttons:
                self.on_event("Going to the next step.")
                before = self._snapshot()
                next_buttons[0].click()
                self._settle(before)
                continue
            if submit_buttons:
                if self.dry_run:
                    return Outcome("filled", message=f"Dry run: filled {self.filled} field(s) and stopped before submitting.")
                if self.submit_mode != "auto" and not self.final_review_done:
                    return Outcome("needs_you", "review", "Everything is filled in. Check the answers below and the page in the browser window, then choose Submit now (or click Submit in the browser).")
                if not self.may_submit():
                    return Outcome("failed", "error", "The approval for this application changed, so ApplyPilot did not submit it.")
                self.on_event("Submitting the application.")
                self.submit_clicked = True
                submit_buttons[0].click()
                result = self._wait_for_result()
                if result:
                    return result
                return Outcome("needs_you", "unconfirmed", "ApplyPilot clicked Submit but did not see a confirmation. Check the browser window or your email. If it went through, mark it as submitted.")
            clicked, reason = self._navigate("The page is filled in, but there is no recognizable Next or Submit button.")
            if clicked:
                continue
            return Outcome("needs_you", "error", (reason + " " if reason else "") + "ApplyPilot could not find a Next or Submit button. Finish this step in the browser window, then click Continue.")
        return Outcome("needs_you", "error", "This application has more steps than expected. Check the browser window, then click Continue.")

    def submit_now(self) -> Outcome:
        """The user reviewed the filled form and asked ApplyPilot to submit it."""
        self.final_review_done = True
        self.submit_mode = "auto"
        self.seen_form = True
        return self.advance()
