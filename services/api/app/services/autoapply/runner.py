"""The background worker that owns the ApplyPilot browser window.

One thread drives a visible Chrome window with its own profile (so employer sign-ins are
kept between runs). Runs are processed one at a time, each in its own tab. When a run
needs the user, its tab stays open and the worker moves on to the next run; sign-ins and
CAPTCHAs are noticed automatically once the user has dealt with them.
"""

from __future__ import annotations

import logging
import platform as host_platform
import queue
import subprocess
import threading
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Application, ApplyRun, User
from app.services.applications import valid_approval
from app.services.autoapply import records
from app.services.autoapply.applicant import application_dir, build_applicant
from app.services.autoapply.driver import Driver, Outcome, start_url
from app.services.jsonutil import dumps, loads

log = logging.getLogger(__name__)

AUTO_RESUME = {"login", "captcha", "verification"}
WATCH_FOR_CONFIRMATION = {"review", "unconfirmed", "captcha", "questions", "error"}
IDLE_CLOSE_SECONDS = 600


def notify_mac(title: str, message: str) -> None:
    """A macOS banner so the user notices when ApplyPilot needs them. Silently skipped elsewhere."""
    if host_platform.system() != "Darwin":
        return
    script = f'display notification {dumps(message[:180])} with title {dumps(title[:60])}'
    try:
        # Fixed program and arguments; the user-visible text is JSON-escaped into the AppleScript string.
        subprocess.Popen(["/usr/bin/osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    except OSError:
        pass


class Runner:
    def __init__(self):
        self.commands: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.drivers: dict[str, Driver] = {}
        self.waiting: dict[str, str] = {}  # run id -> what it waits for
        self.paused_at: dict[str, str] = {}  # run id -> page snapshot when it paused
        self.last_seen: dict[str, str] = {}  # run id -> page snapshot at the previous watch
        self.captures = None  # job capture sessions (app.services.capture), created on first use
        self.context = None
        self.status = "idle"

    # ------------------------------------------------------------------
    # Called from API threads
    # ------------------------------------------------------------------

    def ensure_running(self) -> None:
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._main, name="applypilot-autoapply", daemon=True)
                self.thread.start()

    def send(self, action: str, run_id: str | None = None, payload: dict | None = None) -> None:
        self.ensure_running()
        self.commands.put((action, run_id, payload or {}))

    def stop(self, timeout: float = 10) -> None:
        """Close the browser and end the worker thread (used at shutdown and by tests)."""
        if self.thread is not None and self.thread.is_alive():
            self.commands.put(("stop", None, {}))
            self.thread.join(timeout)

    def attached(self, run_id: str) -> bool:
        return run_id in self.drivers

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _main(self) -> None:
        from playwright.sync_api import sync_playwright

        self.status = "running"
        try:
            with sync_playwright() as playwright:
                self.playwright = playwright
                idle_since = time.monotonic()
                last_watch = 0.0
                while True:
                    try:
                        action, run_id, payload = self.commands.get(timeout=1.5)
                    except queue.Empty:
                        action = None
                    if action == "stop":
                        self._close_browser()
                        self.drivers.clear()
                        self.waiting.clear()
                        self.captures = None
                        return
                    try:
                        if action:
                            self._command(action, run_id, payload)
                            idle_since = time.monotonic()
                        if time.monotonic() - last_watch > 3:
                            self._watch()
                            last_watch = time.monotonic()
                        next_run = self._next_queued()
                        if next_run:
                            self._begin(next_run)
                            idle_since = time.monotonic()
                        elif not self.drivers and not (self.captures and self.captures.active()) and self.context is not None and time.monotonic() - idle_since > IDLE_CLOSE_SECONDS:
                            self._close_browser()
                    except Exception:  # noqa: BLE001 - a busy database or one bad step must not stop every run
                        log.exception("Application runner step failed; continuing")
                        time.sleep(2)
        except Exception:  # noqa: BLE001 - never take the API down
            log.exception("The application runner stopped")
            with SessionLocal() as db:
                for run_id in list(self.drivers):
                    run = db.get(ApplyRun, run_id)
                    if run and run.status in records.ACTIVE:
                        records.stop(db, run, "interrupted", "The ApplyPilot browser stopped unexpectedly.")
                db.commit()
            self.drivers.clear()
            self.waiting.clear()
            self.context = None
        finally:
            self.status = "idle"

    def _browser(self):
        if self.context is not None:
            try:
                self.context.pages  # noqa: B018 - raises if the window was closed
                return self.context
            except Exception:  # noqa: BLE001
                self.context = None
        settings = get_settings()
        profile = settings.storage_path / "browser-profile"
        profile.mkdir(parents=True, exist_ok=True)
        options = {"headless": settings.autoapply_headless, "viewport": None, "accept_downloads": False}
        try:
            self.context = self.playwright.chromium.launch_persistent_context(str(profile), channel="chrome", **options)
        except Exception:  # noqa: BLE001 - fall back to Playwright's own Chromium if Chrome is missing
            self.context = self.playwright.chromium.launch_persistent_context(str(profile), **options)
        self.context.on("close", lambda _ctx: self._browser_closed())
        return self.context

    def _browser_closed(self) -> None:
        self.context = None

    def _close_browser(self) -> None:
        try:
            if self.context is not None:
                self.context.close()
        except Exception:  # noqa: BLE001
            pass
        self.context = None

    def _next_queued(self) -> str | None:
        with SessionLocal() as db:
            return db.scalar(select(ApplyRun.id).where(ApplyRun.status == "queued").order_by(ApplyRun.created_at).limit(1))

    def _applicant(self, db, run: ApplyRun):
        application = db.get(Application, run.application_id)
        user = db.get(User, run.user_id)
        return build_applicant(db, user, application, loads(run.answers_json, {}))

    def _letter_writer(self, run_id: str):
        """Writes a cover letter during the run, only when a form requires one."""

        def write():
            from app.models import CoverLetter, JobPosting, ResumeVersion
            from app.services.ai import ai_scope
            from app.services.autoapply.applicant import _render_letter, application_dir
            from app.services.writing import write_cover_letter

            with SessionLocal() as db:
                run = db.get(ApplyRun, run_id)
                application = db.get(Application, run.application_id)
                user = db.get(User, run.user_id)
                posting = db.get(JobPosting, application.job_posting_id)
                version = db.get(ResumeVersion, application.resume_version_id)
                document = loads(version.content_json, {}).get("document") or {}
                with ai_scope(user.id, "cover_letter"):
                    body, _info = write_cover_letter(user.profile, posting, document, "professional")
                letter = CoverLetter(user_id=user.id, job_posting_id=posting.id, tone="professional", body=body)
                db.add(letter)
                db.flush()
                # Keep the current approval valid: the letter is part of this run and shown at the final review.
                approval = valid_approval(db, application)
                application.cover_letter_id = letter.id
                if approval is not None:
                    approval.cover_letter_id = letter.id
                records.event(run, "Wrote a cover letter because this form requires one.")
                db.commit()
                return _render_letter(user, body, application_dir(application.id)), body

        return write

    def _drafter(self, run_id: str):
        from app.services.autoapply.draft import claude_drafter

        return claude_drafter(get_settings())

    def _approval_ok(self, run_id: str) -> bool:
        with SessionLocal() as db:
            run = db.get(ApplyRun, run_id)
            application = db.get(Application, run.application_id) if run else None
            if application is None or application.status != "submitting":
                return False
            approval = valid_approval(db, application)
            return approval is not None

    def _event(self, run_id: str, message: str) -> None:
        with SessionLocal() as db:
            run = db.get(ApplyRun, run_id)
            if run:
                records.event(run, message)
                db.commit()

    def _begin(self, run_id: str) -> None:
        with SessionLocal() as db:
            run = db.get(ApplyRun, run_id)
            if run is None or run.status != "queued":
                return
            reason = records.start(db, run)
            if reason:
                run.status = "failed"
                run.message = reason
                run.finished_at = records.now()
                db.commit()
                return
            from app.models import JobPosting

            application = db.get(Application, run.application_id)
            posting = db.get(JobPosting, application.job_posting_id)
            url = start_url(run.platform, posting.application_url)
            from app.services.autoapply.applicant import WrongResume

            try:
                applicant = self._applicant(db, run)
            except WrongResume as exc:
                records.stop(db, run, "interrupted", str(exc))
                db.commit()
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("Could not prepare documents")
                records.stop(db, run, "interrupted", f"ApplyPilot could not prepare your documents: {exc.__class__.__name__}.")
                db.commit()
                return
            submit_mode, platform, user_id = run.submit_mode, run.platform, run.user_id
            db.commit()
        try:
            page = self._browser().new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:  # noqa: BLE001
            self._finish_outcome(run_id, Outcome("needs_you", "error", f"The application page did not open ({exc.__class__.__name__}). Check your connection, then click Continue."))
            return
        from app.services.autoapply.accounts import Accounts

        from app.services.autoapply.memory import ai_recaller
        from app.services.autoapply.navigate import ai_navigator

        driver = Driver(
            page, platform, applicant, submit_mode=submit_mode, drafter=self._drafter(run_id), accounts=Accounts(user_id),
            letter_writer=self._letter_writer(run_id), navigator=ai_navigator(get_settings()), recaller=ai_recaller(get_settings()),
            may_submit=lambda: self._approval_ok(run_id), on_event=lambda message: self._event(run_id, message),
        )
        driver.user_id = user_id
        self.drivers[run_id] = driver
        self._step(run_id, driver.advance)

    def _step(self, run_id: str, action) -> None:
        from app.services.ai import ai_scope

        driver = self.drivers.get(run_id)
        if driver is None:
            return
        self.waiting.pop(run_id, None)
        with SessionLocal() as db:
            run = db.get(ApplyRun, run_id)
            if run and run.status == "needs_you":
                run.status = "running"
                run.attention = None
                db.commit()
        try:
            with ai_scope(getattr(driver, "user_id", None), "application_answers"):
                outcome = action()
        except Exception as exc:  # noqa: BLE001 - the page changed under us or the tab closed
            log.exception("Application step failed")
            if driver.page.is_closed():
                self._end(run_id, "interrupted", "The browser tab was closed.")
                return
            outcome = Outcome("needs_you", "error", f"Something on the page did not work as expected ({exc.__class__.__name__}). Check the browser window, then click Continue.")
        self._finish_outcome(run_id, outcome)

    def _finish_outcome(self, run_id: str, outcome: Outcome) -> None:
        driver = self.drivers.get(run_id)
        with SessionLocal() as db:
            run = db.get(ApplyRun, run_id)
            if run is None:
                return
            if driver is not None:
                run.filled_count = driver.filled
                run.filled_json = dumps(driver.summary())
                run.documents_json = dumps(driver.documents)
                run.submit_clicked = run.submit_clicked or driver.submit_clicked
                run.page_url = driver.page.url[:1000] if not driver.page.is_closed() else run.page_url
            if outcome.status == "submitted":
                screenshot = None
                try:
                    path = application_dir(run.application_id) / f"confirmation-{run.id[:8]}.png"
                    driver.page.screenshot(path=str(path), full_page=True)
                    screenshot = str(path)
                except Exception:  # noqa: BLE001
                    pass
                records.finish_submitted(db, run, outcome.confirmation_text or "", outcome.confirmation_url or "", screenshot)
                db.commit()
                self._release(run_id, close=True)
                return
            if outcome.status == "failed":
                records.finish_failed(db, run, outcome.message)
                db.commit()
                self._release(run_id, close=False)
                return
            run.status = "needs_you"
            run.attention = outcome.attention
            run.message = outcome.message
            run.questions_json = dumps(outcome.questions)
            records.event(run, outcome.message)
            application = db.get(Application, run.application_id)
            title = None
            if application is not None:
                from app.models import JobPosting

                posting = db.get(JobPosting, application.job_posting_id)
                title = f"{posting.title} at {posting.company}" if posting else None
            db.commit()
        self.waiting[run_id] = outcome.attention or "error"
        try:
            self.paused_at[run_id] = driver._snapshot() if driver is not None else ""
        except Exception:  # noqa: BLE001
            self.paused_at[run_id] = ""
        try:
            if driver is not None and not driver.page.is_closed():
                driver.page.bring_to_front()
                if outcome.attention not in {"login", "captcha"}:
                    # Sign-ins and CAPTCHAs are done in the page itself; everything else is answered in ApplyPilot.
                    driver.show_banner(outcome.message)
        except Exception:  # noqa: BLE001
            pass
        if outcome.attention not in {"review"}:
            notify_mac("ApplyPilot needs you", f"{title or 'An application'}: {outcome.message}")

    def _release(self, run_id: str, close: bool) -> None:
        driver = self.drivers.pop(run_id, None)
        self.waiting.pop(run_id, None)
        self.paused_at.pop(run_id, None)
        self.last_seen.pop(run_id, None)
        if driver and close:
            try:
                driver.page.close()
            except Exception:  # noqa: BLE001
                pass

    def _end(self, run_id: str, status: str, message: str, close: bool = False) -> None:
        with SessionLocal() as db:
            run = db.get(ApplyRun, run_id)
            if run and run.status not in records.FINAL:
                records.stop(db, run, status, message)
                db.commit()
        self._release(run_id, close=close)

    def _owned_pages(self, run_id: str | None = None) -> list:
        pages = [driver.page for other, driver in self.drivers.items() if other != run_id]
        if self.captures is not None:
            pages += self.captures.pages()
        return pages

    def _watch(self) -> None:
        """Notice when the user has signed in, solved a CAPTCHA, verified, opened the form, or submitted by hand."""
        if self.captures is not None:
            self.captures.watch()
        for run_id, waiting_for in list(self.waiting.items()):
            driver = self.drivers.get(run_id)
            if driver is None:
                self.waiting.pop(run_id, None)
                continue
            try:
                followed = driver.adopt_new_tab(owned=self._owned_pages(run_id))
                if driver.page.is_closed():
                    # The tab closed (for example a sign-in pop-up flow): carry on in the tab it came from, if any.
                    opener = None
                    try:
                        opener = driver.page.opener()
                    except Exception:  # noqa: BLE001
                        opener = None
                    if opener is not None and not opener.is_closed():
                        driver.page = opener
                    else:
                        self._end(run_id, "interrupted", "The browser tab was closed.")
                        continue
                if followed and waiting_for in {"login", "error", "verification"}:
                    self._event(run_id, "The application opened in a new tab. Continuing there.")
                    self._step(run_id, driver.advance)
                    continue
                if waiting_for in WATCH_FOR_CONFIRMATION:
                    confirmation = driver.confirmation_on_screen()
                    if confirmation:
                        self._finish_outcome(run_id, Outcome("submitted", confirmation_text=confirmation, confirmation_url=driver.page.url))
                        continue
                snapshot = driver._snapshot()
                steady = snapshot == self.last_seen.get(run_id)
                self.last_seen[run_id] = snapshot
                moved = snapshot.split("|")[0] != (self.paused_at.get(run_id) or "").split("|")[0]
                if waiting_for == "login" and steady and not driver.login_on_screen():
                    self._event(run_id, "You signed in. Continuing.")
                    self._step(run_id, driver.advance)
                elif waiting_for == "captcha" and not driver.captcha_on_screen():
                    self._event(run_id, "The CAPTCHA is done. Continuing.")
                    self._step(run_id, driver.advance)
                elif waiting_for == "verification" and steady and moved and not driver.verification_on_screen() and not driver.login_on_screen():
                    self._event(run_id, "Verification done. Continuing.")
                    self._step(run_id, driver.advance)
                elif waiting_for == "error" and steady and moved and not driver.login_on_screen() and driver.form_on_screen():
                    # You opened the application yourself: carry on from there.
                    self._event(run_id, "You opened the next page. Continuing.")
                    self._step(run_id, driver.advance)
            except Exception:  # noqa: BLE001
                log.debug("Watch check failed", exc_info=True)

    def capture_status(self, user_id: str) -> dict:
        return self.captures.status(user_id) if self.captures is not None else {"active": False}

    def _command(self, action: str, run_id: str | None, payload: dict) -> None:
        driver = self.drivers.get(run_id) if run_id else None
        if action == "wake":
            return
        if action.startswith("capture_"):
            from app.services.capture import CaptureManager

            if self.captures is None:
                self.captures = CaptureManager(self)
            user_id = payload["user_id"]
            if action == "capture_start":
                self.captures.start(user_id, payload["portal"], payload.get("url"), payload.get("term"))
            elif action == "capture_read_list":
                self.captures.read_list(user_id, payload.get("term"))
            elif action == "capture_stop":
                self.captures.stop(user_id)
            return
        if action == "show":
            if driver is not None:
                try:
                    driver.page.bring_to_front()
                except Exception:  # noqa: BLE001
                    pass
            return
        if action in {"cancel", "handoff"}:
            status = "cancelled" if action == "cancel" else "handed_off"
            message = "Cancelled. Nothing was sent." if action == "cancel" else "You are finishing this one in the browser window. Mark it as submitted when you are done."
            if action == "cancel" and driver is not None and driver.submit_clicked:
                message = "Cancelled after ApplyPilot clicked Submit. Check whether it went through."
            self._end(run_id, status, message, close=(action == "cancel"))
            return
        if driver is None:
            # The tab is gone (for example after a restart): start this run again from the beginning.
            if action in {"continue", "submit_now"}:
                with SessionLocal() as db:
                    run = db.get(ApplyRun, run_id)
                    if run and run.status == "needs_you":
                        run.status = "queued"
                        db.commit()
            return
        if action == "continue":
            from app.services.autoapply.applicant import WrongResume

            with SessionLocal() as db:
                run = db.get(ApplyRun, run_id)
                try:
                    applicant = self._applicant(db, run)
                except WrongResume as exc:
                    self._end(run_id, "interrupted", str(exc))
                    return
            if driver._resume_uploaded and applicant.resume_content_sha256 != driver.applicant.resume_content_sha256:
                # The resume changed after it was attached; never submit with an outdated file on the form.
                self._end(run_id, "interrupted", "Your resume changed after it was attached. Approve the application again and restart so the new version is uploaded.", close=True)
                return
            # Keep the record of the file actually attached to this form.
            applicant.resume_path, applicant.resume_sha256 = driver.applicant.resume_path, driver.applicant.resume_sha256
            driver.applicant = applicant
            driver.approve(payload.get("approved") or [], payload.get("corrected") or [])
            from app.services.autoapply.accounts import Accounts

            driver.accounts = Accounts(run.user_id)  # picks up a password saved since the run started
            self._step(run_id, driver.advance)
        elif action == "submit_now":
            self._step(run_id, driver.submit_now)


RUNNER = Runner()
