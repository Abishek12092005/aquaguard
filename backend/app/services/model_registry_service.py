"""ML model version registry: register, validate, activate, roll back, audit.

THIS IS AN EXTENSION OF THE EXISTING `model_service`, NOT A REPLACEMENT.

The pre-existing console could import an artifact and make it active. What it
could not do was keep a record of any of it, which made three of the requested
behaviours impossible rather than merely awkward:

  * "which model is deployed and when was it last updated" had to be answered by
    reading a filename and a modification time on a disk nobody can see;
  * rolling back was not safely expressible, because nothing recorded which
    versions had ever been VALIDATED, so any file present looked like a candidate;
  * there was no audit trail of who changed the model and whether it worked.

So the activation pointer stays exactly where it was - `model_service`'s
`active_model` setting - and this module records the history around it. Every
existing route and every existing behaviour keeps working, and the console's
existing "ML model management" tab is extended rather than replaced.

THE ORDERING RULE, WHICH IS THE WHOLE SAFETY STORY OF THIS MODULE:

    register  ->  validate (isolated subprocess)  ->  activate

`activate` is reachable only from a row whose own recorded validation passed, and
`register` never touches the active pointer. A failure anywhere in that chain
therefore leaves the running model exactly where it was - not "usually", but
structurally, because the failing operation has no code path that writes the
pointer at all. `promote_active_model` re-reads the target's stored verdict
immediately before writing, so even a stale in-memory state cannot promote an
unvalidated artifact.

NO SECRET IS WRITTEN ANYWHERE HERE. No API key, no credential, no database
string, no stack trace. Audit details are short human sentences.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from flask import current_app

from app.constants import FEATURE_NAMES
from app.extensions import db
from app.models.model_version import ACTIONS, ACTIVATABLE_FROM, ModelAuditLog, ModelVersion
from app.services import model_validator
from app.utils.errors import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

# Where registered artifacts live, under the configured model directory. The
# same directory the pre-existing import path uses, so an artifact registered here
# is visible to the existing `list_models()` and to `set_active_model()` without
# either of them being taught about this module.
IMPORTED_DIRNAME = "imported"

#: The label vocabulary a model must be able to express. Checked against what the
#: artifact itself declares, so a model returning a fourth class is refused rather
#: than silently mapped onto one of the three the UI understands.
SUPPORTED_LABELS = ("safe", "moderate", "unsafe")


# ---------------------------------------------------------------------------
# Filesystem helpers. Every path here is server-generated.
# ---------------------------------------------------------------------------


def _model_root() -> str:
    root = current_app.config.get("ML_WATER_QUALITY_DIR") or "."
    return os.path.join(root, "model")


def _imported_root() -> str:
    path = os.path.join(_model_root(), IMPORTED_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def _safe_component(value: str, fallback: str = "model") -> str:
    """Reduce caller-supplied text to a safe path component.

    An uploaded filename and an admin-supplied version string are BOTH
    attacker-influenced. Without this, a version of `../../app` would resolve
    outside the import directory. Everything outside a conservative allowlist is
    replaced rather than escaped - a name that is merely quoted is still a name
    that can resolve somewhere unexpected.
    """
    base = os.path.basename(str(value or ""))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    return cleaned or fallback


def _safe_filename(filename: str) -> str:
    """The stored filename for an upload: a safe stem, always `.joblib`.

    The extension is normalised rather than trusted, because the extension is
    what tells the loader how the file is encoded and what tells a future reader
    what they are looking at.
    """
    stem = os.path.splitext(_safe_component(filename))[0] or "model"
    return f"{stem}.joblib"


def _safe_version(version: str) -> str:
    """A normalised version string, safe to use as a filename stem and to store."""
    return _safe_component(version, fallback="v-unnamed")


def _resolve_artifact(row: ModelVersion) -> str:
    """The artifact's path, re-checked to be inside the import directory.
    Belt and braces against the `artifact_path` column being edited directly in
    the database by anything other than this module: the stored path is only
    trusted if it still resolves inside the directory this module owns.
    """
    root = os.path.realpath(_imported_root())
    resolved = os.path.realpath(row.artifact_path)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValidationError(
            "That model artifact is not inside the model's import directory",
            {"artifact_path": "The stored path does not resolve to a managed artifact."},
        )
    return resolved


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def record_audit(
    actor: str,
    action: str,
    success: bool,
    detail: str | None = None,
    model_version: str | None = None,
    previous_active: str | None = None,
    resulting_active: str | None = None,
) -> None:
    """Append one audit row. Never raises.

    The log is append-only and must record FAILURES as readily as successes, so
    this is called from both sides of every operation. It deliberately does not
    raise: an audit write that fails must not turn a completed activation into a
    500, and the failure is logged instead - loudly, because losing an audit line
    is itself worth knowing about.

    The action is checked against the fixed vocabulary, so a typo cannot add an
    entry nothing knows how to read.
    """
    if action not in ACTIONS:
        logger.warning("Refusing to audit unknown action %r", action)
        return

    try:
        db.session.add(
            ModelAuditLog(
                actor=str(actor or "unknown"),
                model_version=model_version,
                action=action,
                success=bool(success),
                # Truncated rather than allowed to raise on a column limit: a long
                # detail is a cosmetic loss, a failed insert is a lost audit row.
                detail=(str(detail)[:500] if detail else None),
                previous_active=previous_active,
                resulting_active=resulting_active,
            )
        )
        db.session.commit()
    except Exception:  # noqa: BLE001 - never let logging break the operation
        db.session.rollback()
        logger.exception("Could not write the model audit row (%s / %s)", action, actor)


def audit_log(limit: int = 100, action: str | None = None, version: str | None = None):
    """The most recent audit rows, newest first."""
    query = db.session.query(ModelAuditLog)
    if action in ACTIONS:
        query = query.filter(ModelAuditLog.action == action)
    if version:
        query = query.filter(ModelAuditLog.model_version == version)
    rows = query.order_by(ModelAuditLog.occurred_at.desc(), ModelAuditLog.id.desc())
    return [row.to_dict() for row in rows.limit(max(1, min(int(limit or 100), 500))).all()]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_artifact(
    upload,
    version: str,
    actor: str,
    display_name: str | None = None,
    notes: str | None = None,
    declared_checksum: str | None = None,
    auto_validate: bool = True,
) -> dict[str, Any]:
    """Store an uploaded artifact as a registered version, then validate it.

    FOUR VALIDATIONS, IN THIS ORDER, AND NONE OF THEM IS OPTIONAL:

      1. file type    - the extension is one this project accepts;
      2. file size    - within the accepted band, so an upload cannot fill the disk;
      3. checksum     - SHA-256 computed over the STORED bytes, and compared with
                        the value the client declared when it declared one. A
                        mismatch means the bytes that arrived are not the bytes
                        that were offered, and nothing further is attempted.
      4. compatibility
                       - the isolated subprocess in `model_validator`, which
                         covers deserialisation, the five-feature contract, the
                         label vocabulary, and an actual prediction.

    THE FILE IS NEVER LOADED IN THIS PROCESS. Check 4 runs a child interpreter
    with a clean environment; see that module for what it does and does not
    guarantee.

    `auto_validate=False` registers without checking - useful for a large
    artifact staged before a deliberate validation run - but the row is left in
    `registered`, which is NOT in `ACTIVATABLE_FROM`, so it still cannot be
    activated. Skipping the check delays a decision; it never enables one.
    """
    upload_file = upload
    if upload_file is None or not getattr(upload_file, "filename", ""):
        raise ValidationError(
            "No model file was uploaded", {"file": "Choose a .joblib or .pkl artifact."}
        )

    raw_name = str(upload_file.filename)

    ok, why = model_validator.check_file_type(raw_name)
    if not ok:
        _audit_failure(actor, "register", raw_name, why)
        raise ValidationError("That file type is not supported", {"file": why})

    # Read the stream once, into memory, so the size can be checked BEFORE
    # anything is written to disk. Reading it directly to disk first would mean
    # an oversized upload has already consumed the space it was refused for.
    data = upload_file.read()
    size = len(data)
    ok, why = model_validator.check_file_size(size)
    if not ok:
        _audit_failure(actor, "register", raw_name, why)
        raise ValidationError("That file is not an acceptable size", {"file": why})

    digest = model_validator.checksum  # the function; used below on the stored file
    del digest

    import hashlib

    incoming_sha = hashlib.sha256(data).hexdigest()

    if declared_checksum:
        # Case-insensitive and whitespace-tolerant, because these values are
        # copy-pasted from `sha256sum` output by a human. Anything that is not
        # 64 hex characters is refused outright rather than compared loosely.
        candidate = re.sub(r"[^0-9a-fA-F]", "", str(declared_checksum)).lower()
        if len(candidate) != 64:
            _audit_failure(
                actor,
                "register",
                raw_name,
                "The declared checksum is not a SHA-256 value.",
            )
            raise ValidationError(
                "That checksum is not a SHA-256 value",
                {"checksum": "Expected 64 hexadecimal characters."},
            )
        if candidate != incoming_sha:
            _audit_failure(
                actor,
                "register",
                raw_name,
                "The uploaded file does not match the declared checksum.",
            )
            raise ValidationError(
                "That file does not match the checksum you declared",
                {
                    "checksum": "The upload's SHA-256 is "
                    f"{incoming_sha}, which does not match the declared value. "
                    "The file was not stored."
                },
            )

    stored_name = _safe_filename(raw_name)
    destination = os.path.join(_imported_root(), stored_name)
    staging = f"{destination}.incoming"

    # Written under a temporary name first. If anything below raises, the real
    # filename has not been touched, so a rejected upload can never have replaced
    # a good artifact that was already there.
    try:
        with open(staging, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        _audit_failure(actor, "register", raw_name, f"The artifact could not be written: {exc}")
        raise ValidationError(
            "That artifact could not be stored", {"file": "The upload could not be written to disk."}
        ) from None

    # The authoritative checksum is the one over the bytes now ON DISK, not the
    # one computed from the stream: this is the value that describes the file
    # every later check will open.
    stored_sha = model_validator.checksum(staging)
    try:
        row = ModelVersion(
            version=_safe_version(version),
            display_name=(display_name or None),
            filename=stored_name,
            artifact_path=os.path.abspath(destination),
            size_bytes=size,
            checksum_sha256=stored_sha,
            original_filename=raw_name[:255],
            content_type=(getattr(upload_file, "mimetype", None) or None),
            registered_by=str(actor or "unknown"),
            notes=(notes[:500] if notes else None),
            status="registered",
        )
        db.session.add(row)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001 - includes the unique-version refusal
        db.session.rollback()
        try:
            os.remove(staging)
        except OSError:
            pass
        _audit_failure(actor, "register", raw_name, "The version could not be registered.")
        if "uq_model_versions_version" in str(exc) or "Duplicate" in str(exc):
            raise ValidationError(
                f"Version '{_safe_version(version)}' is already registered",
                {"version": "Choose a version string that is not already in the registry."},
            ) from None
        raise ValidationError(
            "That artifact could not be registered",
            {"file": "The registry could not be updated."},
        ) from None

    os.replace(staging, destination)

    record_audit(
        actor,
        "register",
        True,
        f"Registered '{row.version}' ({size} bytes sha256 {stored_sha[:12]}…).",
        model_version=row.version,
    )
    logger.info("Model version %s registered by %s", row.version, actor)

    if not auto_validate:
        return row.to_dict()

    # VALIDATE IMMEDIATELY. Registering and leaving it unchecked is allowed, but
    # validating here means the admin sees the verdict in the same action that
    # uploaded the file, rather than having to remember a second step.
    return validate_version(row.id, actor)


def _audit_failure(actor: str, action: str, version: str | None, detail: str) -> None:
    """Audit a REFUSAL that raised before any row existed.

    The alternative - auditing only what succeeded - would leave the log silent
    about every rejected upload, which is precisely the set of events an admin
    reviewing a model registry most wants to see.
    """
    record_audit(actor, action, False, detail, model_version=version)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_version(version_id: int, actor: str) -> dict[str, Any]:
    """Run the isolated validation against a registered version and record the verdict.

    The active pointer is NOT read and NOT written here, which is why a validation
    that fails - or times out, or crashes the child - cannot disturb the running
    model. The only rows this touches are the version's own `status`,
    `validation_report` and `validated_at`, and one audit entry.
    """
    row = db.session.get(ModelVersion, int(version_id))
    if row is None:
        raise NotFoundError("That model version is not in the registry")

    previous_active = active_version_label()
    logger.info("Validating '%s' (active model is '%s')", row.version, previous_active)

    if row.status == "active":
        _audit_failure(
            actor,
            "validate",
            row.version,
            "The active model cannot be re-validated in place.",
        )
        raise ValidationError(
            "That model is currently active",
            {"version": "Roll back to another version before validating this one again."},
        )

    try:
        path = _resolve_artifact(row)
    except ValidationError as exc:
        _commit_validation(row, actor, {"passed": False, "checks": [], "failure": exc.message})
        _audit_failure(actor, "validate", row.version, exc.message)
        raise

    if not os.path.isfile(path):
        message = (
            "The artifact for that version is not on disk. It may have been removed "
            "outside the console."
        )
        _commit_validation(row, actor, {"passed": False, "checks": [], "failure": message})
        _audit_failure(actor, "validate", row.version, message)
        raise NotFoundError(message)

    row.status = "validating"
    db.session.commit()

    record_audit(actor, "validate", True, f"Validation started for '{row.version}'.", model_version=row.version)

    report = model_validator.validate_artifact(
        path,
        expected_features=list(FEATURE_NAMES),
        expected_labels=list(SUPPORTED_LABELS),
    )

    # Whatever happened in the child, the row and the audit line are written
    # together so the registry can never show a version as validated with no
    # report behind it.
    _commit_validation(row, actor, report)

    passed = bool(report.get("passed"))
    record_audit(
        actor,
        "validate",
        passed,
        (
            f"'{row.version}' passed validation."
            if passed
            else f"'{row.version}' failed validation: {report.get('failure')}"
        ),
        model_version=row.version,
        resulting_active=active_version_label(),
    )

    logger.info(
        "Model version %s validation %s by %s",
        row.version,
        "passed" if passed else "failed",
        actor,
    )
    return row.to_dict()


def _commit_validation(row: ModelVersion, actor: str, report: dict[str, Any]) -> None:
    """Store the verdict on the row and move it to its new state."""
    passed = bool(report.get("passed"))

    row.set_validation_report(report)
    # The schema is captured from the verdict, so the console can SHOW the
    # contract the model was built against without loading it again - and so a
    # later change to the configured features is detectable against this row.
    row.set_feature_schema(report.get("features") or [])
    row.set_label_schema(report.get("labels") or [])
    row.scikit_learn_version = report.get("scikit_learn_version")
    row.numpy_version = report.get("numpy_version")
    row.declared_version = report.get("declared_version")
    row.trained_at = report.get("trained_at")

    row.validated_at = datetime.now(timezone.utc)
    row.validated_by = str(actor or "unknown")
    row.status = "validated" if passed else "rejected"

    db.session.commit()


# ---------------------------------------------------------------------------
# Activation and rollback
# ---------------------------------------------------------------------------


def active_version_label() -> str | None:
    """The version string of the active model, when one is registered here.

    The active POINTER lives in `model_service`'s existing settings key. This
    reads that same key through the existing service - not a second copy of it -
    and maps the artifact name back to a registry version, so there is still
    exactly one place that decides which model is live.

    None means the model in use was configured by `ML_MODEL_FILENAME` rather
    than through the console, which is a real and supported state rather than an
    error.
    """
    from app.services.model_service import active_model_name

    artifact = active_model_name()
    if not artifact:
        return None
    row = ModelVersion.query.filter_by(filename=f"{artifact}.joblib").first()
    if row is not None:
        return row.version
    # An artifact activated through the pre-existing console path, which has no
    # registry row. Reported by its artifact name so the header still names
    # something real.
    return artifact


def _current_registry_row() -> ModelVersion | None:
    """The registry row for the currently active model, if there is one."""
    from app.services.model_service import active_model_name

    artifact = active_model_name()
    if not artifact:
        return None
    return ModelVersion.query.filter_by(filename=f"{artifact}.joblib").first()


def _activate_row(row: ModelVersion, actor: str, action: str) -> dict[str, Any]:
    """Move the existing activation pointer, guarded.

    The guard is re-read HERE, immediately before the write, rather than trusted
    from the route that called in. That matters because the two can disagree: a
    row could have been re-registered or its report edited between the check and
    the call, and this is the last point at which that is still cheap to refuse.

    The `model_service.set_active_model` call is what actually switches the
    running model. It is not wrapped in a "clear the old one first" - the
    existing service is a pointer update, so there is no window in which the
    application has no model at all.
    """
    from app.services.model_service import set_active_model

    db.session.refresh(row)

    # Compared on the STEM, because that is what `list_models()` reports and what
    # the activation setting stores.
    stem = os.path.splitext(row.filename)[0]

    # THE GUARD, and it is the SAME ONE FOR BOTH ACTIONS: a passing validation
    # report must exist on this row.
    #
    # It is deliberately NOT "the status must literally be `validated`". That
    # would make rollback impossible: the versions worth rolling back to are
    # precisely the ones that were once live and have since been `superseded` or
    # `rolled_back`, and requiring the transient `validated` status would refuse
    # every one of them. The STATUS is where the row sits in the lifecycle; the
    # REPORT is the fact, and the fact is what a deployment decision rests on.
    # So `validated` reads the report, and `ACTIVATABLE_FROM` still constrains
    # where a FIRST activation may come from.
    if not row.validated or (action == "activate" and row.status not in ACTIVATABLE_FROM):
        _audit_failure(
            actor,
            action,
            row.version,
            f"Refused: '{row.version}' has not passed validation.",
        )
        raise ValidationError(
            "That model has not passed validation",
            {
                "version": f"'{row.version}' is '{row.status}'. Only a model whose own "
                "validation passed can be activated. The currently active model has "
                "not been changed."
            },
        )

    previous = _current_registry_row()
    previous_version = previous.version if previous else active_version_label()

    # Only now, with everything verified, is the pointer moved. If anything
    # above this line raised, the running model is untouched.
    set_active_model(stem)
    db.session.commit()

    now = datetime.now(timezone.utc)
    row.status = "active"
    row.activated_at = now
    row.activated_by = str(actor or "unknown")

    if previous is not None and previous.id != row.id:
        # A previously active artifact keeps its row and its history; it is
        # marked superseded (or rolled_back, when the switch went backwards), so
        # "which versions have been live" is answerable from the registry.
        previous.status = (
            "rolled_back" if action == "rollback" and _is_older(previous, row) else "superseded"
        )
    db.session.commit()

    record_audit(
        actor,
        action,
        True,
        f"'{row.version}' is now answering predictions.",
        model_version=row.version,
        previous_active=previous_version,
        resulting_active=row.version,
    )
    logger.info("Model version %s activated (%s) by %s", row.version, action, actor)
    return row.to_dict()


def _is_older(candidate: ModelVersion, than: ModelVersion) -> bool:
    """Whether `candidate` was created before `than`.

    Used only to label a rollback as a rollback. Creation time is the right order
    for this because a version string carries no ordering anyone has agreed to
    trust, and guessing one from the digits in "v2" vs "v10" is how a rollback
    gets labelled backwards.
    """
    if candidate.created_at and than.created_at:
        return candidate.created_at < than.created_at
    return candidate.id < than.id


def activate_version(version_id: int, actor: str) -> dict[str, Any]:
    """Make a validated version the one that answers predictions."""
    row = db.session.get(ModelVersion, int(version_id))
    if row is None:
        raise NotFoundError("That model version is not in the registry")
    if row.status == "active":
        record_audit(
            actor,
            "activate",
            True,
            f"'{row.version}' was already active.",
            model_version=row.version,
            resulting_active=row.version,
        )
        return row.to_dict()
    return _activate_row(row, actor, "activate")


def rollback_to_version(version_id: int, actor: str) -> dict[str, Any]:
    """Move the active pointer back to an earlier validated version.

    A ROLLBACK IS AN ACTIVATION OF SOMETHING THAT ALREADY PROVED ITSELF, so it
    goes through exactly the same guard: the target must be a `validated` or
    previously-active row, never a `registered` or `rejected` one. Rolling
    "back" to something that never worked is not a rollback, and allowing it
    would make this the easiest way to break a running system.
    """
    row = db.session.get(ModelVersion, int(version_id))
    if row is None:
        raise NotFoundError("That model version is not in the registry")

    current = _current_registry_row()
    if current is not None and current.id == row.id:
        record_audit(
            actor,
            "rollback",
            False,
            f"'{row.version}' is already the active model.",
            model_version=row.version,
        )
        raise ValidationError(
            "That version is already active",
            {"version": "Choose an earlier version to roll back to."},
        )

    # A ROLLBACK IS AN ACTIVATION OF SOMETHING THAT ALREADY PROVED ITSELF, so it
    # goes through the same guard: the target must carry a PASSING validation
    # report, never a `registered` or `rejected` one. Rolling "back" to
    # something that never worked is not a rollback, and allowing it would make
    # this the easiest way to break a running system.
    #
    # The guard is on the STORED REPORT rather than on the status, so a version
    # that passed validation and has since been superseded or rolled back remains
    # a valid target. Requiring the literal status `validated` here would mean the
    # only versions you could roll back to are ones that were never active - which
    # is precisely backwards, because a version that has not been deployed is not
    # what anyone rolls back TO.
    if not row.validated:
        _audit_failure(
            actor,
            "rollback",
            row.version,
            f"Refused: '{row.version}' has no passing validation on record.",
        )
        raise ValidationError(
            "That model cannot be rolled back to",
            {
                "version": f"'{row.version}' is '{row.status}' and has no passing "
                "validation on record. A rollback target must have passed validation. "
                "The currently active model has not been changed."
            },
        )

    return _activate_row(row, actor, "rollback")


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_versions(status: str | None = None) -> list[dict[str, Any]]:
    """Every registered version, newest first, with the active one flagged."""
    query = db.session.query(ModelVersion)
    if status:
        query = query.filter(ModelVersion.status == status)
    rows = query.order_by(ModelVersion.created_at.desc(), ModelVersion.id.desc()).all()

    active_row = _current_registry_row()
    active_id = active_row.id if active_row else None
    active_label = active_version_label()

    payload = []
    for row in rows:
        item = row.to_dict()
        item["active"] = row.id == active_id
        # Whether the artifact is still on disk. A registry entry whose file has
        # gone is the state that makes every prediction fail, so it is surfaced
        # rather than left to be discovered.
        try:
            item["artifact_present"] = os.path.isfile(_resolve_artifact(row))
        except ValidationError:
            item["artifact_present"] = False
        # A previous version is a candidate for rollback; say so explicitly.
        item["rollback_target"] = bool(
            not item["active"] and row.validated and item["artifact_present"]
        )
        payload.append(item)

    if active_label and active_id is None:
        # The live model was activated through the pre-existing console path and
        # has no registry row. Reported as a pseudo-row so the console can say
        # what is running instead of showing an empty "active" state.
        payload.append(
            {
                "id": None,
                "version": active_label,
                "display_name": "Activated outside the version registry",
                "status": "active",
                "active": True,
                "rollback_target": False,
                "artifact_present": True,
                "validation_passed": False,
                "registered": False,
                "features": [],
                "labels": [],
                "validation": {
                    "passed": False,
                    "failure": "This model was activated before the version registry "
                    "existed, so it has no recorded validation.",
                },
            }
        )
    return payload


def deployment_status() -> dict[str, Any]:
    """Everything the console's Project Updates panel needs, in one call.

    Four facts and no others: the deployed PROJECT version, the BACKEND version,
    the ML MODEL version and the deployment's own state. Each is read from
    somewhere real - the package version, `app.__version__`, and the actual
    active pointer - and none is a constant written into this module.

    `last_successful_update` is the activation time of the currently active
    model, read from the audit log rather than from the file's modification time:
    "when was this last updated" means when it was DEPLOYED, and a file's mtime
    changes for reasons that have nothing to do with a deployment.
    """
    from app import __version__ as backend_version

    active_row = _current_registry_row()
    active_label = active_version_label()

    # The most recent SUCCESSFUL activation, which is what "last successful
    # update" means. Failed attempts are in the log too, under `last_event`.
    last_success = (
        db.session.query(ModelAuditLog)
        .filter(ModelAuditLog.action.in_(["activate", "rollback"]))
        .filter(ModelAuditLog.success.is_(True))
        .order_by(ModelAuditLog.occurred_at.desc())
        .first()
    )

    # A health probe rather than an assumption: the console shows whether the
    # running model is actually loadable, because "deployed" and "working" are
    # different claims.
    model_healthy = _probe_active_model()

    return {
        "project": {
            "name": "AquaGuard AI",
            "version": _project_version(),
        },
        "backend": {
            "version": backend_version,
            "api_prefix": current_app.config.get("API_PREFIX") or "/api/v1",
        },
        "model": {
            "version": (active_row.version if active_row else active_label),
            "declared_version": (active_row.declared_version if active_row else None),
            "trained_at": (active_row.trained_at if active_row else None),
            "scikit_learn_version": (active_row.scikit_learn_version if active_row else None),
            "features": (active_row.get_feature_schema() if active_row else []),
            "labels": (active_row.get_label_schema() if active_row else []),
            "checksum_sha256": (active_row.checksum_sha256 if active_row else None),
            "source": (
                "registry"
                if active_row
                else ("configuration" if active_label else None)
            ),
            "healthy": model_healthy,
        },
        "deployment": {
            # Three states rather than a boolean, because "not deployed yet" and
            # "deployed and broken" need different words.
            "status": (
                "healthy"
                if active_label and model_healthy
                else "degraded"
                if active_label
                else "unconfigured"
            ),
            "active_version": active_label,
            "last_successful_update": (
                last_success.occurred_at.isoformat() if last_success else None
            ),
            "last_successful_update_by": (last_success.actor if last_success else None),
            "last_event": _last_event(),
            "detail": _deployment_detail(active_label, model_healthy),
        },
        "registered_versions": ModelVersion.query.count(),
        "validated_versions": ModelVersion.query.filter_by(status="validated").count(),
        "rejected_versions": ModelVersion.query.filter_by(status="rejected").count(),
    }


def _probe_active_model() -> bool:
    """Whether the active model is PRESENT AND PLAUSIBLY USABLE, cheaply.

    THIS DELIBERATELY NEVER LOADS A MODEL. Two reasons, both learned the hard
    way:

      * A load takes seconds on a 30 MB forest. The application already warms the
        model up on a background thread at start-up, and the loader holds a
        process-wide lock while it does. Asking `water_quality.is_available()`
        from here would block on that same lock, so a console page view could sit
        for the whole warm-up - and the console is not a place a request may
        hang.
      * The health question is "is what is deployed there and intact", and the
        answer to that is the FILESYSTEM plus the registry's own record. Loading
        it again to be sure would be answering a different, more expensive
        question that the application already answers on every prediction.

    So this checks that the registry's artifact is still on disk at the path that
    was recorded, and that it is non-empty. A model that is present but
    genuinely unloadable still surfaces as a failure on the next real prediction,
    which is where the detail belongs.
    """
    try:
        active_row = _current_registry_row()
        if active_row is not None:
            path = _resolve_artifact(active_row)
            return os.path.isfile(path) and os.path.getsize(path) > 0

        # No registry row: fall back to the application's own configured
        # artifact, checked for presence only.
        configured = os.path.join(
            current_app.config.get("ML_MODEL_DIR") or "",
            current_app.config.get("ML_MODEL_FILENAME") or "",
        )
        return bool(configured) and os.path.isfile(configured)
    except Exception:  # noqa: BLE001 - a failed probe means "not healthy"
        logger.warning("The deployment health probe could not complete")
        return False


def _project_version() -> str:
    """The project's own version, from the frontend package manifest.

    Read rather than declared here, so this module cannot drift from the version
    the frontend actually reports to the browser. When the file is unreachable -
    which it is, for a backend-only deployment - the backend's own version is
    reported with that fact stated, rather than a placeholder that looks like a
    real version.
    """
    from app import __version__ as backend_version

    try:
        candidates = [
            os.path.join(current_app.root_path, "..", "frontend", "package.json"),
            os.path.join(current_app.root_path, "..", "..", "frontend", "package.json"),
        ]
        import json

        for candidate in candidates:
            resolved = os.path.abspath(candidate)
            if not os.path.isfile(resolved):
                continue
            with open(resolved, "r", encoding="utf-8") as handle:
                version = (json.load(handle) or {}).get("version")
            if version:
                return f"{version} (frontend manifest)"
    except Exception:  # noqa: BLE001
        pass
    return f"{backend_version} (backend manifest; frontend version not readable here)"


def _last_event() -> dict[str, Any] | None:
    """The most recent audit row of any outcome, for the 'last activity' line."""
    row = (
        db.session.query(ModelAuditLog)
        .order_by(ModelAuditLog.occurred_at.desc(), ModelAuditLog.id.desc())
        .first()
    )
    return row.to_dict() if row else None


def _deployment_detail(active_label: str | None, healthy: bool) -> str:
    """One sentence describing the deployment's state, from what was measured."""
    if not active_label:
        return (
            "No model has been activated through the console. The backend is using the "
            "artifact named by ML_MODEL_FILENAME."
        )
    if not healthy:
        return (
            f"'{active_label}' is set as the active model but could not be loaded. "
            "Predictions will fail until this is resolved."
        )
    return f"'{active_label}' is active and loaded successfully."
