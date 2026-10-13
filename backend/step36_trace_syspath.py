"""STEP 36 - trace exactly WHO puts the real ml/ on sys.path.

The sandbox test set ML_WATER_QUALITY_DIR correctly, yet `import predict`
resolved to the real ml/predict.py. Either the real root was inserted before the
sandbox root, or `predict` was already in sys.modules from an earlier import. Both
are found by inspecting the interpreter state directly.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REAL_ML = os.path.join(os.path.dirname(HERE), "ml")


def report(label):
    print(f"\n=== {label} ===")
    print("predict in sys.modules :", "predict" in sys.modules)
    if "predict" in sys.modules:
        print("  predict.__file__     :", sys.modules["predict"].__file__)
    print("sys.path entries containing 'ml':")
    for entry in sys.path:
        if entry and os.path.basename(entry.rstrip("\\/")) == "ml":
            print("   ", entry)
    if "predict" in sys.modules and sys.modules["predict"].__file__:
        print("  MODEL_DIR of loaded  :", sys.modules["predict"].MODEL_DIR)


report("before importing app")

sandbox_root = tempfile.mkdtemp(prefix="aquaguard_trace_")
sandbox_ml = os.path.join(sandbox_root, "ml")
shutil.copytree(
    REAL_ML, sandbox_ml,
    ignore=shutil.ignore_patterns("__pycache__", "*.joblib", "subsets", "datasets"),
)
os.environ["ML_WATER_QUALITY_DIR"] = sandbox_ml

from app import create_app  # noqa: E402

report("after `from app import create_app` (no app created yet)")

app = create_app("testing")
report("after create_app (warm-up has run)")

print("\n--- does the sandbox root appear in sys.path at all? ---")
print("sandbox root        :", sandbox_ml)
print("present in sys.path :", sandbox_ml in sys.path)
print("real root in path   :", REAL_ML in sys.path)

shutil.rmtree(sandbox_root, ignore_errors=True)