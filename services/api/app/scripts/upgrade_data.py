"""Bring data from earlier ApplyPilot versions up to date.

    python -m app.scripts.upgrade_data            # apply
    python -m app.scripts.upgrade_data --dry-run  # report only

What it does (all additive; nothing the user typed is deleted):
- adds missing tables and columns;
- classifies stored job postings by role, level, and location, and re-reads their requirements;
- re-reads each stored resume file with the layout parser;
- for resumes that were already saved to a profile, rebuilds the resume-derived
  parts of that profile from the new reading (skills, roles, schools, and projects
  the user added or confirmed are kept);
- creates a default saved search from onboarding preferences.
Back up the database first. The script refuses to run without --i-have-a-backup
unless --dry-run is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal, engine
from app.core.schema import ensure_schema
from app.models import JobPosting, OriginalResume, User
from app.services.job_sync import backfill_classification, reanalyze, refresh_matches
from app.services.jsonutil import loads
from app.services.profile_ops import approve_extraction, get_profile
from app.services.resume_import import extract_resume
from app.services.search_profiles import default_profile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--i-have-a-backup", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.i_have_a_backup:
        print("Back up the database, then run again with --i-have-a-backup (or use --dry-run).")
        return 2
    added = ensure_schema(engine)
    print(f"Schema: {len(added)} column(s) added.")
    db = SessionLocal()
    try:
        print(f"Classified {backfill_classification(db)} stored posting(s).")
        active = db.scalars(select(JobPosting).where(JobPosting.is_active.is_(True))).all()
        for posting in active:
            reanalyze(db, posting)
        print(f"Re-read requirements for {len(active)} active posting(s).")
        for user in db.scalars(select(User)).all():
            profile = get_profile(db, user)
            before = (len(profile.experiences), len(profile.projects), len(profile.profile_skills))
            search = default_profile(db, user)
            resumes = db.scalars(select(OriginalResume).where(OriginalResume.user_id == user.id).order_by(OriginalResume.created_at)).all()
            approved = [row for row in resumes if row.approved_at]
            for resume in resumes:
                path = Path(resume.storage_path)
                if not path.exists():
                    print(f"  {user.email}: {resume.filename} has no stored file, skipped.")
                    continue
                parsed = extract_resume(resume, path)
                print(
                    f"  {user.email}: re-read {resume.filename}: {len(parsed['experience'])} roles, {len(parsed['education'])} schools, "
                    f"{len(parsed['projects'])} projects, {len(parsed['skills'])} skills."
                )
            if approved:
                latest = max(approved, key=lambda row: row.approved_at)
                approve_extraction(db, user, loads(latest.extracted_json, {}), latest.raw_text)
                for row in resumes:
                    row.is_primary = row.id == latest.id
                db.flush()
                db.expire(profile)
                profile = get_profile(db, user)
                after = (len(profile.experiences), len(profile.projects), len(profile.profile_skills))
                print(f"  {user.email}: profile rebuilt from {latest.filename}. Roles {before[0]}→{after[0]}, projects {before[1]}→{after[1]}, skills {before[2]}→{after[2]}.")
            print(f"  {user.email}: default search “{search.name}”.")
            refresh_matches(db, user)
        if args.dry_run:
            db.rollback()
            print("Dry run: nothing was saved.")
        else:
            db.commit()
            print("Saved.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
