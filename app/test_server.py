import joblib

# Load models and encoder
leak_detection_model = joblib.load("models/rf_detection.pkl")
leak_localization_model = joblib.load("models/rf_localization.pkl")
local_label_encoder = joblib.load("models/local_label_encoder.pkl")

# Fake sensor readings (example)
sample_data = [[0.2, 0.8, 1.1, 0.5]]

print("=== Leak Detection Test ===")
det_pred = leak_detection_model.predict(sample_data)
print("Leak Detection Prediction:", det_pred)


print("\n=== Leak Localization Test ===")
loc_pred = leak_localization_model.predict(sample_data)
print("Leak Localization Encoded Prediction:", loc_pred)

# Decode back to original pair
loc_label = local_label_encoder.inverse_transform(loc_pred)
leak_from, leak_to = loc_label[0].split("_")
print(f"Leak from sensor {leak_from} to sensor {leak_to}")

