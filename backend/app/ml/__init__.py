"""Machine learning package.

Responsibilities, kept strictly separated so training and serving cannot drift:

    preprocessing.py  raw dict -> validated feature DataFrame (canonical order)
    model_loader.py   resolve, load and cache the serialized model artifact
    predictor.py      run inference, produce class + confidence + risk level
    train.py          offline training entrypoint (Random Forest Classifier)
    evaluate.py       hold-out metrics and feature importances

The backend never trains on import — training is an explicit offline step that
writes an artifact into `ml/models/`, which `model_loader` then serves.
"""

from app.ml.model_loader import get_model, get_model_metadata, is_model_available
from app.ml.predictor import predict

__all__ = [
    "get_model",
    "get_model_metadata",
    "is_model_available",
    "predict",
]
