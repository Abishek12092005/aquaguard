"""End-to-end check of the model version registry (Prompt 7).

Runs against a real application context and real artifacts, because the things
worth proving here are all about what happens to the RUNNING model when something
goes wrong - and that cannot be shown by a mocked test.

The order matters and mirrors the acceptance criteria: register and validate a
GOOD model, activate it, then register BAD ones and prove the active model did
not move.

**THE DATABASE ISOLATION IS SET UP BEFORE `create_app()`, NOT AFTER.** The
engine is created inside `create_app`, so assigning
`app.config["SQLALCHEMY_DATABASE_URI"]` afterwards has no effect at all - the app
would still be talking to the real deployment's database while the test believed
it was using a temporary one. That is not a hypothetical: an earlier draft of this
file did exactly that and wrote its rows to the live database. The only reliable
way to redirect the connection is the environment variable `get_config()` reads,
which is what this file does, and the temporary database's path is asserted
below before anything is written.
"""

import os
import tempfile

# MUST be set before `from app import create_app` is ever called: the database URI
# is resolved while the app is built, not after.
_TMPDIR = tempfile.mkdtemp(prefix="aquaguard-registry-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'test.db')}"
os.environ["ML_WATER_QUALITY_DIR"] = _TMPDIR
# A console credential the test never uses - it drives the services directly, not
# through HTTP, so no admin login is performed or needed.
os.environ["SECRET_KEY"] = "registry-check-only-key-not-a-real-secret-0123456789"

import joblib  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402

from app import create_app  # noqa: E402
from app.constants import FEATURE_NAMES  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.model_version import ModelVersion  # noqa: E402

app = create_app()

# The engine is created inside `create_app`, so it can only be inspected from
# within an application context - which is where the assertion below runs, before
# `db.create_all()` and before anything is written.

with app.app_context():
    # THE ASSERTION THAT MATTERS MOST IN THIS FILE. If the engine is pointed
    # anywhere other than the temporary file, this raises before a single row is
    # written.
    bound = str(db.engine.url)
    assert _TMPDIR in bound, f"refusing to run: engine is bound to {bound}, not the temp DB"
    print("engine bound to the temporary database:", bound)

    db.create_all()

    from app.services import model_registry_service as registry

    # ---------------------------------------------------------------- artefacts
    def good_model(features=None):
        rng = np.random.default_rng(7)
        X = rng.normal(7.0, 1.0, size=(60, 5))
        y = rng.integers(0, 3, size=60)
        clf = RandomForestClassifier(n_estimators=5, random_state=0).fit(X, y)
        return {
            "model": clf,
            "features": list(features or FEATURE_NAMES),
            "labels": ["safe", "moderate", "unsafe"],
            "model_version": "rf-test-1.0",
            "trained_at": "2026-04-01",
        }

    good_path = os.path.join(_TMPDIR, "good.joblib")
    joblib.dump(good_model(), good_path)

    # A model built against the WRONG feature set.
    wrong_features = list(FEATURE_NAMES) + ["hardness"]
    wrong_path = os.path.join(_TMPDIR, "wrong.joblib")
    joblib.dump(good_model(wrong_features), wrong_path)

    # Not a model at all.
    junk_path = os.path.join(_TMPDIR, "junk.joblib")
    with open(junk_path, "wb") as handle:
        handle.write(b"this is not a joblib artifact at all")

    def fake_upload(path, filename=None):
        class _Upload:
            def __init__(self):
                self.filename = filename or os.path.basename(path)
                self.mimetype = "application/octet-stream"
                self._data = open(path, "rb").read()

            def read(self):
                return self._data

        return _Upload()

    results = {}

    # ---------------------------------------------------------- 1. register good
    print("== 1. register a valid model ==")
    row = registry.register_artifact(
        fake_upload(good_path, "water-quality-rf.joblib"),
        version="v1.0.0",
        actor="admin@test",
        notes="First registered version",
    )
    results["good_id"] = row["id"]
    print("  status          :", row["status"])
    print("  validation      :", row["validation_passed"])
    print("  features        :", row["features"])
    print("  checksum        :", row["checksum_sha256"][:16], "…")
    assert row["validation_passed"], "a well-formed model should pass"
    assert row["status"] == "validated"

    # --------------------------------------------------------- 2. activate good
    print("\n== 2. activate it ==")
    registry.activate_version(row["id"], "admin@test")
    status = registry.deployment_status()
    print("  active version  :", status["model"]["version"])
    print("  deployment      :", status["deployment"]["status"])
    print("  last successful :", status["deployment"]["last_successful_update"])
    assert status["model"]["version"] == "v1.0.0"

    # ------------------------------------- 3. register a BROKEN model (the key test)
    print("\n== 3. register a model with the wrong feature set ==")
    before = registry.deployment_status()["deployment"]["active_version"]
    broken = registry.register_artifact(
        fake_upload(wrong_path, "broken-features.joblib"),
        version="v2.0.0-broken",
        actor="admin@test",
    )
    print("  status          :", broken["status"])
    print("  validation      :", broken["validation_passed"])
    print("  failure         :", broken["validation"]["failure"])
    after = registry.deployment_status()["deployment"]["active_version"]
    print("  active BEFORE   :", before)
    print("  active AFTER    :", after)
    assert not broken["validation_passed"], "wrong features must be refused"
    assert broken["status"] == "rejected"
    assert after == before, "a failed validation must NOT change the active model"

    # ------------------------------------------ 4. refuse to activate a rejected model
    print("\n== 4. try to activate the rejected model ==")
    try:
        registry.activate_version(broken["id"], "admin@test")
        print("  ERROR: it was allowed (should not be)")
        raise SystemExit(1)
    except Exception as exc:
        print("  refused         :", str(exc)[:110])
    assert registry.deployment_status()["deployment"]["active_version"] == "v1.0.0"

    # ------------------------------------------------------- 5. register junk file
    print("\n== 5. register a file that is not a model ==")
    junk = registry.register_artifact(
        fake_upload(junk_path, "not-a-model.joblib"),
        version="v3.0.0-junk",
        actor="admin@test",
    )
    print("  status          :", junk["status"])
    print("  failure         :", junk["validation"]["failure"])
    assert not junk["validation_passed"]
    assert registry.deployment_status()["deployment"]["active_version"] == "v1.0.0"

    # ------------------------------------------------------- 6. checksum mismatch
    print("\n== 6. register with a WRONG declared checksum ==")
    try:
        registry.register_artifact(
            fake_upload(good_path, "mismatch.joblib"),
            version="v4.0.0",
            actor="admin@test",
            declared_checksum="0" * 64,
        )
        print("  ERROR: accepted a file that did not match its declared checksum")
        raise SystemExit(1)
    except Exception as exc:
        print("  refused         :", str(exc)[:110])
    assert registry.deployment_status()["deployment"]["active_version"] == "v1.0.0"

    # --------------------------------------------------------- 7. file type / size
    print("\n== 7. refuse an unsupported file type ==")
    try:
        registry.register_artifact(
            fake_upload(good_path, "model.exe"), version="v5", actor="admin@test"
        )
        print("  ERROR: accepted an unsupported extension")
        raise SystemExit(1)
    except Exception as exc:
        print("  refused         :", str(exc)[:110])

    # ----------------------------------------------------------- 8. rollback works
    print("\n== 8. register a second good model, then roll back to the first ==")
    second = registry.register_artifact(
        fake_upload(good_path, "water-quality-rf-2.joblib"),
        version="v1.1.0",
        actor="admin@test",
        notes="Retrained on the new dataset",
    )
    print("  v1.1.0 status   :", second["status"])
    assert second["validation_passed"]

    registry.activate_version(second["id"], "admin@test")
    print("  active now      :", registry.deployment_status()["deployment"]["active_version"])

    # Roll back to the version that was live before.
    registry.rollback_to_version(row["id"], "admin@test")
    after_rollback = registry.deployment_status()
    print("  after rollback  :", after_rollback["deployment"]["active_version"])
    assert after_rollback["deployment"]["active_version"] == "v1.0.0", "rollback did not take"
    print("  v1.1.0 state    :", ModelVersion.query.get(second["id"]).status)

    # A ROLLBACK TO SOMETHING THAT NEVER WORKED MUST BE REFUSED.
    print("\n== 8b. try to roll back to a model that failed validation ==")
    try:
        registry.rollback_to_version(broken["id"], "admin@test")
        print("  ERROR: allowed a rollback to a rejected model")
        raise SystemExit(1)
    except Exception as exc:
        print("  refused         :", str(exc)[:110])
    assert registry.deployment_status()["deployment"]["active_version"] == "v1.0.0"
    listed = registry.list_versions()
    for item in listed:
        print(
            f"  {item['version']:<16} {item['status']:<11} "
            f"active={item.get('active')} rollback_target={item.get('rollback_target')}"
        )
    assert any(v["version"] == "v1.0.0" and v["active"] for v in listed)
    # Every version that is NOT active and not rejected is offered as a rollback
    # target, and nothing rejected ever is.
    assert any(v["version"] == "v1.1.0" and v["rollback_target"] for v in listed)
    assert not any(v["rollback_target"] for v in listed if v["status"] == "rejected")

    # ------------------------------------------------------------- 9. audit trail
    print("\n== 9. audit log ==")
    entries = registry.audit_log(limit=50)
    print(f"  {len(entries)} entries recorded")
    for entry in entries:
        flag = "ok  " if entry["success"] else "FAIL"
        print(
            f"  [{flag}] {entry['action']:<10} {str(entry['model_version']):<16} "
            f"{(entry['detail'] or '')[:60]}"
        )
    actions = {entry["action"] for entry in entries}
    # The failures are the point: a rejected upload and a refused activation must
    # both be on the record.
    assert {"register", "validate", "activate"} <= actions, actions
    assert any(not entry["success"] for entry in entries), "failures must be audited"
    assert any(entry["action"] == "register" and not entry["success"] for entry in entries)
    print("\nALL REGISTRY CHECKS PASSED")

with app.app_context():
    db.session.remove()
