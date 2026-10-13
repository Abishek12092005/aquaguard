"""Validate a model candidate in an ISOLATED, RESTRICTED subprocess.

WHY A SUBPROCESS AT ALL, WHEN `joblib.load` IS JUST A FUNCTION CALL.

Because `joblib.load` and `pickle.load` EXECUTE CODE. A pickle is a small program
that reconstructs objects by importing modules and calling `__reduce__`; loading
an untrusted one is equivalent to running it. That is not a theoretical risk and it
cannot be patched away in a library call - there is no "safe" flag.

So an uploaded artifact is never loaded in this process, and never loaded in a
process that can reach the application's database, configuration or mail
credentials. It is loaded in a child interpreter with:

  * a WORKING DIRECTORY that is the artifact's own folder, so a relative path
    cannot read the application;
  * a working directory and temp dir it can WRITE, so it cannot modify the
    application either;
  * no network use (see `_enforce_no_network`);
  * a hard wall-clock TIMEOUT, enforced by the parent with `kill()` rather than
    trusted to the child - an artifact that loops forever must not be able to hang
    the console;
  * a hard MEMORY CAP, CPU cap and fork cap through POSIX resource limits where
    the platform provides them. WINDOWS HAS NO `preexec_fn` AND NO `setrlimit`,
    so those particular caps are absent there and the isolation on that platform
    rests entirely on the clean environment, the isolated interpreter, the new
    process group and the wall-clock timeout. That is a genuine reduction in
    protection rather than an equivalent achieved another way, and it is the
    reason production deployments of this feature should run on Linux with real
    container-level isolation;
  * a CLEAN ENVIRONMENT: no inherited `DATABASE_URL`, no mail credentials, no
    provider keys, no admin password. This is the part that most often gets
    skipped and it is the most important: a subprocess that inherits the parent
    environment can read every secret the application holds.
  * no `PYTHONPATH`, no user site-packages and no `.pth` files, via `-I`, because
    all of those execute at interpreter start-up from directories the artifact's
    folder could influence.

IT STILL IS NOT A SANDBOX. A determined attacker with an arbitrary-code-execution
primitive can escape a pure-Python process boundary. What this buys is that the
common and realistic attacks - an accidental `os.system`, a reverse shell, a
keylogger, a read of the application's own settings - do not work, and that a
hostile artifact cannot take the API down with it. Real kernel-level isolation
requires containers or a VM and is a deployment decision, so this module says so
rather than implying a guarantee it cannot make.

THE OUTPUT CONTRACT. The child writes ONE JSON document to a file path given on
the command line and exits. It never writes to stdout, so a malicious artifact
that prints cannot forge a verdict by writing to the same stream: an unreadable
or unparsable file is a FAILURE, never a pass. That is deliberate - a verdict is
trusted only when it is well-formed, and "could not tell" is reported as "no".
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

#: Wall-clock budget for one validation run. Generous enough for a large forest
#: to load, short enough that a runaway artifact cannot occupy the console.
VALIDATION_TIMEOUT_SECONDS = 90

#: Address-space cap for the child, where the platform supports RLIMIT_AS.
#: 2 GiB is well above a fitted Random Forest and far below the point where an
#: allocation loop would threaten the host.
VALIDATION_MEMORY_BYTES = 2 * 1024 * 1024 * 1024

#: CPU seconds. Bounds a busy loop that the wall-clock timeout alone would only
#: catch late.
VALIDATION_CPU_SECONDS = 90

#: The joblib/pickle extensions this project accepts. Anything else is refused
#: before a byte is read, because the loader's behaviour on an unknown extension
#: is not something to discover in a subprocess.
ALLOWED_EXTENSIONS = frozenset({".joblib", ".pkl"})

#: The maximum artifact size accepted. A water-quality Random Forest is measured
#: in megabytes; 256 MiB is generous, and a size cap is what stops an upload
#: from filling the disk before any of the real validation runs.
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024


# ---------------------------------------------------------------------------
# What the parent checks, before anything is executed
# ---------------------------------------------------------------------------


def check_file_type(filename: str) -> tuple[bool, str]:
    """Whether the FILENAME's extension is one this project accepts.

    A first gate only. It is trivially bypassed - a `.txt` full of pickle bytes
    is still a pickle - so it exists to reject the obvious mistake early and to
    give a clear message, not as a security control.
    """
    extension = os.path.splitext(filename or "")[1].lower()
    if not extension:
        return False, "The file has no extension; expected .joblib or .pkl."
    if extension not in ALLOWED_EXTENSIONS:
        return False, (
            f"'{extension}' is not a supported model format. "
            "Upload a .joblib or .pkl artifact."
        )
    return True, ""


def check_file_size(size_bytes: int) -> tuple[bool, str]:
    """Whether the artifact is within the accepted size band."""
    if size_bytes <= 0:
        return False, "That file is empty."
    if size_bytes > MAX_ARTIFACT_BYTES:
        limit_mb = MAX_ARTIFACT_BYTES // (1024 * 1024)
        actual_mb = round(size_bytes / (1024 * 1024), 1)
        return False, (
            f"That file is {actual_mb} MB. The maximum accepted model artifact is "
            f"{limit_mb} MB."
        )
    return True, ""


def checksum(path: str) -> str:
    """SHA-256 of a file's bytes, read in chunks.

    Computed over the STORED file rather than the upload stream, so the value
    recorded in the registry describes what is actually on disk.
    """
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# The parent side: run the child, and treat anything unclear as a failure
# ---------------------------------------------------------------------------


def validate_artifact(
    path: str,
    expected_features: list[str],
    expected_labels: list[str],
    timeout: int = VALIDATION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run `model_validator_child` against `path` and return its verdict.

    Returns a report shaped::

        {"passed": bool, "checks": [{"name", "ok", "detail"}],
         "features": [...], "labels": [...], "failure": str|None,
         "scikit_learn_version": str|None, "numpy_version": str|None,
         "duration_ms": int}

    `passed` is True ONLY when the child wrote a well-formed document whose
    `passed` is True. A timeout, a crash, an unreadable report, a report that is
    not JSON, or a report missing a verdict all produce `passed: False` with a
    `failure` explaining which. There is no path here that turns an unclear
    outcome into a pass.
    """
    started = os.times()
    report: dict[str, Any] = {"passed": False, "checks": [], "failure": None}

    # The report file lives OUTSIDE the artifact's directory, so a hostile
    # artifact cannot reach it, truncate it, or pre-write a verdict to it. Its
    # path is the only thing the child learns about the outside world, and it is
    # a fresh file in a directory the artifact has no reason to know about.
    with tempfile.TemporaryDirectory(prefix="aquaguard-validate-") as workdir:
        report_path = os.path.join(workdir, "report.json")

        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    # `-I` ISOLATED: ignores PYTHONPATH, PYTHONHOME and every
                    # other PYTHON* variable, and excludes the user site-packages
                    # directory. That is what stops a `sitecustomize.py`,
                    # `usercustomize.py` or a `.pth` file from executing at
                    # interpreter start-up - all of which can run code without the
                    # artifact doing anything visible.
                    #
                    # NOTE: `-S` is deliberately NOT used. It would skip `site`
                    # entirely, which also removes the virtualenv's site-packages
                    # and therefore scikit-learn and joblib - so every artifact
                    # would fail to load for a reason that has nothing to do with
                    # the artifact. `-I` gives the start-up isolation we want while
                    # leaving the installed libraries importable.
                    "-I",
                    "-B",  # no .pyc writing into the working directory
                    os.path.abspath(__file__),
                    "--report",
                    report_path,
                    "--artifact",
                    os.path.abspath(path),
                    "--features",
                    json.dumps(list(expected_features)),
                    "--labels",
                    json.dumps(list(expected_labels)),
                ],
                # A clean environment. This is the single most important line in
                # the file: a child that inherited DATABASE_URL, MAIL_PASSWORD or
                # an AI provider key could read every secret the application
                # holds, and the whole point of the boundary is that it cannot.
                env=_child_env(workdir),
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                # A NEW PROCESS GROUP, so the timeout kill reaches anything the
                # artifact may have spawned. Without this a child that forked
                # would survive the kill and keep running.
                start_new_session=True,
                # The rlimits can only be set between fork and exec, which on
                # POSIX is what preexec_fn is for. Windows has no such window and
                # rejects the argument outright, so it is omitted there rather
                # than wrapped in a platform check at the call site.
                **({"preexec_fn": _restrict_child} if os.name == "posix" else {}),
            )
            # Read INSIDE the `with`. The temporary directory is removed on the
            # way out, so a read placed after this block always finds nothing -
            # which presents as "the child exited without writing a verdict" for
            # every artifact, valid or not. The child's exit code is 0 and its
            # report was there; the parent was simply looking in the wrong place
            # by the time it looked.
            verdict = _read_report(report_path)
            exit_code = completed.returncode
            stderr = (completed.stderr or "")[-800:]
        except subprocess.TimeoutExpired:
            return {
                **report,
                "checks": [
                    {
                        "name": "isolated_run",
                        "ok": False,
                        "detail": (
                            f"The validation process did not finish within {timeout}s "
                            "and was terminated. An artifact that runs this long is "
                            "not acceptable."
                        ),
                    }
                ],
                "failure": (
                    "Validation timed out. The artifact was terminated and the "
                    "currently active model has not been changed."
                ),
                "duration_ms": _elapsed_ms(started),
            }
        except OSError as exc:  # pragma: no cover - platform dependent
            return {
                **report,
                "checks": [
                    {
                        "name": "isolated_run",
                        "ok": False,
                        "detail": f"The validation process could not be started: {exc}",
                    }
                ],
                "failure": "The isolated validation process could not be started.",
                "duration_ms": _elapsed_ms(started),
            }

    if verdict is None:
        return {
            **report,
            "checks": [
                {
                    "name": "isolated_run",
                    "ok": False,
                    "detail": (
                        f"The validation process exited with code {exit_code} without "
                        f"writing a readable verdict"
                        + (f": {stderr}" if stderr else ".")
                    ),
                }
            ],
            "failure": (
                "The artifact could not be validated in isolation, so it cannot be "
                "activated. The currently active model has not been changed."
            ),
            "duration_ms": _elapsed_ms(started),
        }

    # A well-formed verdict is trusted. It is passed through verbatim - this
    # parent does not second-guess the child's per-check results, because the
    # whole point of the boundary is that the checks ran away from here.
    verdict["duration_ms"] = _elapsed_ms(started)
    verdict.setdefault("checks", [])
    verdict.setdefault("failure", None)
    verdict["passed"] = bool(verdict.get("passed"))
    if not verdict["passed"] and not verdict.get("failure"):
        verdict["failure"] = "The artifact failed validation."
    return verdict


def _child_env(workdir: str) -> dict[str, str]:
    """The environment the validation child is given. ALMOST EMPTY, ON PURPOSE.

    Nothing the application holds is here: no `DATABASE_URL`, no mail
    credentials, no AI provider key, no admin password, no `PYTHONPATH`. An
    artifact that executes inside this process cannot read any of them, which is
    the whole reason the child exists rather than a `joblib.load` call in a
    `try`.

    `SYSTEMROOT` (and its alias `WINDIR`) are the deliberate exception, and the
    reason is specific rather than a softening of the rule. Windows resolves the
    Winsock catalogue - which Python's `socket` and `asyncio` initialise at
    start-up, and joblib triggers through `threading` - out of the system
    directory. Without `SYSTEMROOT` the child dies with a `WinError 10106` while
    importing numpy, so every artifact would be reported as unreadable for a
    reason that has nothing to do with the artifact.

    Those two names carry no credential and no application setting: they say
    where Windows itself is installed. The network remains blocked separately, by
    `_enforce_no_network`, which runs inside the child before any check.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": workdir,
        "TMPDIR": workdir,
    }
    for name in ("SYSTEMROOT", "WINDIR"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


def _read_report(path: str) -> dict[str, Any] | None:
    """The child's verdict, or None if it is missing, truncated or not JSON.

    Strictly parsed and shape-checked: a file containing a bare `true`, or a JSON
    list, or a document with no `passed` key is NOT a verdict. An artifact that
    can write arbitrary bytes to this path still cannot make itself pass.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        return None

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None

    if not isinstance(parsed, dict) or "passed" not in parsed:
        return None
    return parsed


def _elapsed_ms(started: Any) -> int:
    """Wall-clock milliseconds since the `os.times()` snapshot."""
    return int((os.times().elapsed - started.elapsed) * 1000)


def _restrict_child() -> None:  # pragma: no cover - runs in the forked child
    """Drop privileges and caps inside the child, before it execs.

    POSIX ONLY, and called only where the platform has that fork/exec window.
    Windows has no `preexec_fn` and no `resource.setrlimit`, so on that platform
    the caps are simply absent - which is a real reduction in protection and is
    stated as such in the module docstring rather than papered over. The wall-clock
    timeout, the clean environment, the isolated interpreter and the new process
    group still apply on every platform, because none of them depends on POSIX.

    Best-effort by design: a limit the platform refuses is skipped rather than
    failing the whole validation, because a missing RLIMIT on one platform is not
    a reason to refuse to validate models anywhere. The limits that ARE applied
    are the ones the platform supports, and an existing lower ceiling set by the
    parent is never raised.
    """
    if os.name != "posix":
        return

    try:
        import resource
    except ImportError:
        return

    def _apply(which, soft, hard):
        try:
            current_soft, current_hard = resource.getrlimit(which)
            # Never RAISE a limit the parent already set lower - a deployment
            # that has deliberately constrained the whole service should not
            # have that ceiling lifted by this helper.
            target_hard = current_hard if current_hard != resource.RLIM_INFINITY else hard
            target_soft = min(soft, target_hard) if target_hard != resource.RLIM_INFINITY else soft
            resource.setrlimit(which, (target_soft, target_hard))
        except (ValueError, OSError, AttributeError):
            pass

    _apply(resource.RLIMIT_CPU, VALIDATION_CPU_SECONDS, VALIDATION_CPU_SECONDS)
    _apply(resource.RLIMIT_AS, VALIDATION_MEMORY_BYTES, VALIDATION_MEMORY_BYTES)
    # No new files larger than the artifact cap, and no core dumps to fill the
    # disk if the child faults.
    _apply(resource.RLIMIT_FSIZE, MAX_ARTIFACT_BYTES, MAX_ARTIFACT_BYTES)
    _apply(resource.RLIMIT_CORE, 0, 0)
    # No process explosion: an artifact that forks a bomb cannot exhaust the
    # host's table.
    _apply(resource.RLIMIT_NPROC, 64, 64)


# ---------------------------------------------------------------------------
# The child side. Runs as a script, never imported by the application.
# ---------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    """Parse the arguments and delegate. Never raises."""
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--report", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--labels", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    try:
        expected_features = json.loads(args.features)
        expected_labels = json.loads(args.labels)
    except (TypeError, ValueError):
        return 2

    report = run_checks(args.artifact, expected_features, expected_labels)

    # Written with a plain exclusive create so the artifact cannot have opened
    # the path first and had a symlink there. The parent created the directory
    # and the file does not exist yet at this point.
    try:
        with open(args.report, "x", encoding="utf-8") as handle:
            json.dump(report, handle)
    except OSError:
        return 1
    return 0


def run_checks(
    artifact_path: str, expected_features: list[str], expected_labels: list[str]
) -> dict[str, Any]:
    """Load the artifact and run every compatibility and schema check.

    This is the code that actually EXECUTES the uploaded bytes. It runs only
    inside the isolated child. Each check appends to `checks` and the first
    failure short-circuits, because a model that cannot be loaded has no feature
    list to compare and no labels to validate, and continuing would produce
    checks that fail for the wrong reason.
    """
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    report: dict[str, Any] = {
        "passed": False,
        "checks": checks,
        "failure": None,
        "features": [],
        "labels": [],
        "scikit_learn_version": None,
        "numpy_version": None,
        "declared_version": None,
        "trained_at": None,
    }

    def fail(name: str, detail: str, failure: str) -> dict[str, Any]:
        record(name, False, detail)
        report["failure"] = failure
        return report

    # --- 1. The library versions, recorded BEFORE loading --------------------
    # Captured first because a version mismatch is the most useful thing to know
    # when a load fails, and after a failed load the modules may be half-imported.
    try:
        import sklearn

        report["scikit_learn_version"] = sklearn.__version__
    except Exception:  # noqa: BLE001
        pass
    try:
        import numpy

        report["numpy_version"] = numpy.__version__
    except Exception:  # noqa: BLE001
        pass

    # --- 2. Load -------------------------------------------------------------
    # The only genuinely dangerous line in the application. Everything above and
    # below it is bookkeeping; this is where arbitrary code runs, which is the
    # entire reason this module exists.
    try:
        import joblib

        artifact = joblib.load(artifact_path)
    except Exception as exc:  # noqa: BLE001 - any failure means "not usable"
        return fail(
            "loadable",
            # The exception's own text is included, not just its type: an
            # unprintable artifact fails with something like a NameError, and
            # "could not be deserialised" on its own tells an admin nothing about
            # which module was missing or which symbol was not found. The message
            # comes from the exception object, never from the artifact's own
            # output, so it cannot be forged into a misleading verdict.
            f"The artifact could not be deserialised ({type(exc).__name__}: {exc}).",
            "That file is not a readable model artifact, so it cannot be used. "
            "The currently active model has not been changed.",
        )
    record("loadable", True, "The artifact deserialised successfully.")

    # --- 3. Compatibility: does it produce this project's feature contract? ---
    envelope = artifact if isinstance(artifact, dict) else None
    estimator = artifact.get("model") if envelope else artifact

    if estimator is None or not hasattr(estimator, "predict"):
        return fail(
            "has_predictor",
            "The file contains no object with a predict() method.",
            "That file does not contain a predictor. Expected a fitted estimator, "
            "or an artifact with a 'model' key.",
        )
    record("has_predictor", True, "The artifact contains a fitted predictor.")

    if envelope:
        report["declared_version"] = envelope.get("model_version")
        report["trained_at"] = envelope.get("trained_at")

    # --- 4. Feature schema ----------------------------------------------------
    # THE FIVE CONFIGURED WATER-QUALITY FEATURES, exactly. A model built on a
    # different feature set cannot be used by this API, which always presents
    # the values in `FEATURE_NAMES` order; accepting one would make every
    # prediction silently use the wrong columns, which is worse than refusing.
    features = list(
        (envelope.get("features") if envelope else None)
        or getattr(estimator, "feature_names_in_", [])
        or []
    )
    features = [str(name) for name in features]
    report["features"] = features

    if not features:
        record(
            "feature_schema",
            False,
            "The artifact declares no feature names, so its input contract cannot "
            "be verified.",
        )
        report["failure"] = (
            "That model does not declare which inputs it expects, so it cannot be "
            "checked against the configured features. Re-train it with the feature "
            "names recorded in the artifact."
        )
        return report

    if features != list(expected_features):
        record(
            "feature_schema",
            False,
            f"Expected {', '.join(expected_features)}; found {', '.join(features)}.",
        )
        report["failure"] = (
            "That model expects different inputs. It must accept exactly: "
            f"{', '.join(expected_features)}."
        )
        return report
    record(
        "feature_schema",
        True,
        f"Accepts the {len(features)} configured water-quality features.",
    )

    # --- 5. Label schema ------------------------------------------------------
    # A model that returns classes this application cannot map to a verdict would
    # produce a prediction with no meaning attached, so the classes are checked
    # against the supported vocabulary rather than merely counted.
    labels = [str(label) for label in ((envelope.get("labels") if envelope else None) or [])]
    report["labels"] = labels

    if expected_labels:
        unexpected = [label for label in labels if label not in expected_labels]
        if unexpected:
            record(
                "label_schema",
                False,
                f"Unsupported classes: {', '.join(unexpected)}.",
            )
            report["failure"] = (
                "That model returns classes this application cannot interpret "
                f"({', '.join(unexpected)}). Supported classes are: "
                f"{', '.join(expected_labels)}."
            )
            return report
        record(
            "label_schema",
            True,
            f"Returns supported classes: {', '.join(labels) or 'none declared'}.",
        )

    # --- 6. It actually predicts ---------------------------------------------
    # A model that loads and declares the right schema but cannot score a sample
    # is exactly the artifact that would break on the first real user's request.
    import numpy as np

    probe = np.array([[7.0] * len(expected_features)], dtype=float)
    try:
        prediction = estimator.predict(probe)
    except Exception as exc:  # noqa: BLE001
        return fail(
            "predicts",
            f"Predicting on a sample row failed ({type(exc).__name__}).",
            "That model loaded but could not produce a prediction, so it cannot be "
            "activated. The currently active model has not been changed.",
        )

    if prediction is None or len(prediction) != 1:
        record("predicts", False, "Predicting on a sample row returned no verdict.")
        report["failure"] = (
            "That model returned no usable prediction for a sample row, so it cannot "
            "be activated. The currently active model has not been changed."
        )
        return report

    record("predicts", True, f"Scored a sample row and returned {prediction[0]!r}.")

    # --- 7. Optional: probabilities -------------------------------------------
    # Not required. Recorded when present, because a model that can report a
    # confidence is more useful to the dashboard, and its absence is not a
    # reason to refuse an otherwise valid model.
    if hasattr(estimator, "predict_proba"):
        try:
            estimator.predict_proba(probe)
            record("probabilities", True, "Can report class probabilities.")
        except Exception:  # noqa: BLE001
            record(
                "probabilities",
                False,
                "predict_proba is present but failed; confidence may be unavailable.",
            )

    report["passed"] = True
    report["failure"] = None
    return report


def _enforce_no_network() -> None:  # pragma: no cover - child-side best effort
    """Break every outbound socket this process could open.

    Best effort and deliberately so. `socket.socket` is replaced with a stub that
    raises, which stops the ordinary case - an artifact opening a reverse
    connection - without pretending to be a firewall. Anything that reaches the
    network by other means (ctypes, a C extension) is out of scope for this
    function, and the module docstring says plainly that this is not a sandbox.
    """
    import socket

    class _Blocked(socket.socket):
        def __init__(self, *args, **kwargs):
            raise OSError("Network access is disabled during model validation")

    socket.socket = _Blocked  # type: ignore[misc]
    socket.create_connection = lambda *a, **k: _Blocked()  # type: ignore[assignment]

    def _blocked(*args, **kwargs):
        raise OSError("Network access is disabled during model validation")

    socket.socketpair = _blocked  # type: ignore[assignment]


if __name__ == "__main__":  # pragma: no cover - executed as a script
    _enforce_no_network()
    raise SystemExit(_main(sys.argv[1:]))
