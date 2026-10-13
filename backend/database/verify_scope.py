"""Verifies PROMPT 13's configurable admin geographic scope.

Runs against its own throwaway SQLite database, because the shared MySQL test
database is missing columns added by earlier prompts and repairing it needs a
MySQL root credential this session does not hold.

Covers, against real code paths:
  1. OFF / STATE / COUNTRY modes persist, with provenance (req 4);
  2. the chosen area must RESOLVE - nonsense is refused, not stored (req 2/3/6);
  3. the CANONICAL spelling is stored, not the admin's typing (req 6);
  4. every attempt, refused ones included, is audited (req 12);
  5. scope survives a restart / re-read (acceptance criteria);
  6. an unplaceable point is AMBIGUOUS, not "outside the area" (req 8);
  7. a verified out-of-scope place is denied (req 7);
  8. narrowing scope HIDES but never DELETES history (req 10).

    python database/verify_scope.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(tempfile.gettempdir()) / f"scope_{uuid.uuid4().hex[:8]}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

RESULTS: list[bool] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append(bool(condition))
    mark = "PASS" if condition else "FAIL"
    print(f"{mark}  {label}" + (f"  -> {detail}" if detail else ""))


def main() -> int:
    app = create_app("testing")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}

    with app.app_context():
        db.drop_all()
        db.create_all()

        from app.models import AdminSettings, LocationScopeAudit, WaterPrediction
        from app.services import admin_service
        from app.services.location_service import within_scope
        from app.utils.errors import ValidationError

        # A stand-in for the real resolver: it answers for REAL geography and
        # returns the canonical spelling, exactly as `resolve_state` /
        # `resolve_country` do against live map data.
        CANONICAL_STATE = {
            "tamilnadu": {"state": "Tamil Nadu", "country": "India"},
            "tn": {"state": "Tamil Nadu", "country": "India"},
            "kerala": {"state": "Kerala", "country": "India"},
        }
        CANONICAL_COUNTRY = {
            "india": "India",
            "in": "India",
            "unitedstatesofamerica": "United States of America",
        }

        def fake_resolve_state(query, country=None):
            key = "".join((query or "").split()).casefold()
            return dict(CANONICAL_STATE[key]) if key in CANONICAL_STATE else None

        def fake_resolve_country(query):
            key = "".join((query or "").split()).casefold()
            name = CANONICAL_COUNTRY.get(key)
            return {"name": name, "country_code": None} if name else None

        from app.services import country_service

        country_service.resolve_state = fake_resolve_state
        country_service.resolve_country = fake_resolve_country

        # --- Default: OFF ------------------------------------------------
        scope = admin_service.get_location_scope()
        check("default scope is off", scope["mode"] is None)
        check("default scope has no provenance", scope["updated_by"] is None)

        # --- 1/3: a COUNTRY scope stores the CANONICAL name --------------
        scope = admin_service.update_location_scope("country", None, "in")
        check("country scope saves", scope["mode"] == "country")
        check(
            "canonical country name stored, not the typed text",
            scope["country"] == "India",
            scope["country"],
        )
        check("provenance recorded (req 4)", bool(scope["updated_by"]), str(scope["updated_by"]))
        check("provenance time recorded (req 4)", scope["updated_at"] is not None)

        # --- 2: a STATE scope -------------------------------------------
        scope = admin_service.update_location_scope("state", "Tamil Nadu", "India")
        check("state scope saves", scope["mode"] == "state")
        check("canonical state stored", scope["state"] == "Tamil Nadu")
        check("state scope keeps its country", scope["country"] == "India")

        # --- 2/3/6: text that resolves to NOTHING is refused -------------
        for label, mode, st, ctry in (
            ("unresolvable state", "state", "Tamil Nadd", "India"),
            ("unresolvable country", "country", None, "Atlantis"),
            ("state in the wrong country", "state", "Kerala", "France"),
        ):
            before = admin_service.get_location_scope()
            try:
                admin_service.update_location_scope(mode, st, ctry)
                check(f"{label} is refused", False, "it was accepted")
            except ValidationError as exc:
                check(f"{label} is refused", True)
            after = admin_service.get_location_scope()
            check(
                f"{label} leaves the scope unchanged",
                after["mode"] == before["mode"]
                and after["state"] == before["state"]
                and after["country"] == before["country"],
            )

        # A half-configured scope is refused too.
        for label, mode, st, ctry in (
            ("state mode with no state", "state", "", "India"),
            ("country mode with no country", "country", None, ""),
        ):
            try:
                admin_service.update_location_scope(mode, st, ctry)
                check(f"{label} is refused", False, "it was accepted")
            except ValidationError:
                check(f"{label} is refused", True)

        # --- 12: refusals are audited -------------------------------------
        rows = db.session.query(LocationScopeAudit).all()
        refused = [r for r in rows if not r.success]
        check("refused attempts are audited (req 12)", len(refused) >= 4, f"{len(refused)} refused")
        check(
            "a refusal records what was attempted",
            any(r.new_state == "Tamil Nadd" for r in refused),
        )
        check(
            "a refusal records the console identity",
            all(r.actor for r in rows),
        )
        check("audit rows are newest-first readable", len(admin_service.list_location_scope_audits()) == len(rows))

        # --- Acceptance: the scope SURVIVES a fresh read --------------------
        reloaded = AdminSettings.query.first()
        check(
            "scope persists in the database row",
            reloaded.location_scope_mode == "state"
            and reloaded.location_scope_state == "Tamil Nadu",
        )

        # --- 6/7/8: enforcement -------------------------------------------
        admin_service.update_location_scope("state", "Tamil Nadu", "India")

        verdict = within_scope({"state": "Tamil Nadu", "country": "India"}, "Tamil Nadu", "India")
        check("a place in scope is allowed", verdict["allowed"] is True)

        verdict = within_scope({"state": "Kerala", "country": "India"}, "Tamil Nadu", "India")
        check("a place in another state is refused", verdict["allowed"] is False)
        check(
            "and is NOT ambiguous - we know where it is (req 8)",
            verdict.get("ambiguous") is False,
        )

        # REQ 8: a pin we could not place must NOT be called out-of-scope.
        verdict = within_scope({"country": "India"}, "Tamil Nadu", "India")
        check("an unplaceable point is refused", verdict["allowed"] is False)
        check(
            "an unplaceable point is AMBIGUOUS, not out-of-scope (req 8)",
            verdict.get("ambiguous") is True,
            str(verdict.get("reason"))[:60],
        )
        check(
            "the ambiguous message does not assert a boundary",
            "outside" not in (verdict.get("reason") or "").lower(),
        )

        # Case and whitespace must not defeat the comparison.
        verdict = within_scope({"state": "  tamil nadu  "}, "Tamil Nadu", None)
        check("matching ignores case and whitespace", verdict["allowed"] is True)
        verdict = within_scope({"state": "Tamil Nadu Extra"}, "Tamil Nadu", None)
        check("matching is whole-value, not a substring", verdict["allowed"] is False)

        # --- 10: narrowing HIDES history, never DELETES it -------------------
        # The scope is CLEARED first so the baseline below is genuinely
        # unrestricted. Without this the "scope off shows every prediction"
        # check would be measuring the Tamil Nadu scope still in force from the
        # enforcement section above, and would pass or fail for the wrong reason.
        admin_service.update_location_scope(None, None, None)

        owner_id = db.session.query(WaterPrediction).first()
        owner_id = owner_id.user_id if owner_id else None
        if owner_id is None:
            from app.models import User
            from app.extensions import bcrypt

            owner = User(
                name="Scope Owner",
                email=f"scope_{uuid.uuid4().hex[:8]}@example.test",
                password_hash=bcrypt.generate_password_hash("SecurePass123").decode(),
                role="user",
            )
            db.session.add(owner)
            db.session.commit()
            owner_id = owner.id

        for state_name in ("Tamil Nadu", "Kerala", None):
            db.session.add(WaterPrediction(
                user_id=owner_id, ph=7.0, turbidity=1.0, tds=100.0,
                temperature=25.0, dissolved_oxygen=6.0, prediction="safe",
                confidence=0.9, location_state=state_name,
                location_country="India" if state_name else None,
            ))
        db.session.commit()
        total_before = db.session.query(WaterPrediction).count()
        check("three predictions stored", total_before >= 3, f"{total_before}")

        from app.services import report_service

        # NOTE ON THE BASELINE. `list_reports` INNER JOINs `users`, so a
        # prediction whose owner row is absent is excluded by the JOIN, not by
        # anything to do with the scope. The baseline is therefore the count the
        # LIST reports with the scope off, not the raw table count - comparing
        # against the raw count would fail for a reason that has nothing to do
        # with what this script is testing.
        items, meta = report_service.list_reports(per_page=100)
        baseline = meta["total"]
        check("scope off shows every visible prediction", baseline > 0, f"{baseline}")

        # And the baseline must equal the joined row count with no scope applied,
        # which is the same number the scope-off list reported above.
        from sqlalchemy import func as _func, select as _select
        from app.models import User as _User

        joined = db.session.execute(
            _select(_func.count())
            .select_from(WaterPrediction.__table__)
            .join(_User.__table__, WaterPrediction.user_id == _User.id)
        ).scalar_one()
        check(
            "the scope-off list matches the joined row count",
            baseline == joined,
            f"list={baseline} joined={joined}",
        )

        admin_service.update_location_scope("state", "Tamil Nadu", "India")
        items, meta = report_service.list_reports(per_page=100)
        states = {i.get("location_state") for i in items}
        check(
            "out-of-scope rows are hidden from the console",
            "Kerala" not in states,
            str(sorted(x for x in states if x)),
        )
        check("in-scope rows remain visible", "Tamil Nadu" in states)
        check(
            "a row with NO location stays visible (req 9: manual path)",
            None in states or any(i.get("location_state") is None for i in items),
        )

        total_after = db.session.query(WaterPrediction).count()
        check(
            "NOTHING WAS DELETED (req 10)",
            total_after == total_before,
            f"{total_after} vs {total_before}",
        )

        # The chips must count the same rows the list shows.
        summary = report_service.category_summary()
        check(
            "chips count the same rows the list shows (req 10)",
            summary["all"] == meta["total"],
            f"chips={summary['all']} list={meta['total']}",
        )

        # Clearing the scope restores full visibility.
        admin_service.update_location_scope(None, None, None)
        _, meta = report_service.list_reports(per_page=100)
        check(
            "clearing the scope restores every row",
            meta["total"] == baseline,
            f"{meta['total']}/{baseline}",
        )
        check(
            "clearing is audited",
            any(r.new_mode is None and r.success for r in
                db.session.query(LocationScopeAudit).all()),
        )

        db.session.remove()
        db.drop_all()

    DB_PATH.unlink(missing_ok=True)
    passed = sum(1 for r in RESULTS if r)
    print(f"\n{passed}/{len(RESULTS)} checks passed.")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())