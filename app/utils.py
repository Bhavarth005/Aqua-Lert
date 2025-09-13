import joblib
import numpy as np

# Load trained models and label encoder
leak_detection_model = joblib.load("app/models/rf_detection.pkl")
leak_localization_model = joblib.load("app/models/rf_localization.pkl")
local_label_encoder = joblib.load("app/models/local_label_encoder.pkl")


def run_leak_detection(features: np.ndarray) -> int:
    """
    Run leak detection model.
    Returns:
        0 -> No leak
        1 -> Leak detected
    """
    pred = leak_detection_model.predict(features)
    return int(pred[0])


def run_leak_localization(features: np.ndarray):
    loc_pred_enc = leak_localization_model.predict(features)
    leak_pair_str = local_label_encoder.inverse_transform(loc_pred_enc)[0]  # e.g. "2.0_4.0"
    
    # Split and safely cast to int (handles "2" or "2.0")
    parts = leak_pair_str.split("_")
    leak_from = int(float(parts[0]))
    leak_to = int(float(parts[1]))
    
    return leak_from, leak_to


def analyze_sensors(features: np.ndarray) -> dict:
    """
    Run full pipeline: detection first, then localization if needed.
    Args:
        features: numpy array shaped (1, n_features) -> sensor readings
    Returns:
        dict with detection result and (optional) localization
    """
    result = {"leak_detected": False}

    det = run_leak_detection(features)
    if det == 1:  # Leak detected
        result["leak_detected"] = True
        leak_from, leak_to = run_leak_localization(features)
        result["leak_from"] = leak_from
        result["leak_to"] = leak_to

    return result
