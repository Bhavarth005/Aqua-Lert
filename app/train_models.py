import pandas as pd
import numpy as np
import os
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, classification_report
from sklearn.preprocessing import LabelEncoder
import joblib

# ==============================
# Step 1: Load dataset
# ==============================
df = pd.read_csv("dataset.csv")

# ==============================
# Step 2: Preprocessing
# ==============================

# Convert leak_flag: "None" or NaN -> 0, "1.0" -> 1
df["leak_flag_bin"] = df["leak_flag"].apply(lambda x: 0 if (pd.isna(x) or str(x) == "None") else 1)

# Safe converter for leak_from / leak_to
def convert_sensor_id(val):
    if pd.isna(val) or str(val) == "None":
        return np.nan
    try:
        return int(float(val))
    except ValueError:
        return np.nan

df["leak_from_id"] = df["leak_from"].apply(convert_sensor_id)
df["leak_to_id"] = df["leak_to"].apply(convert_sensor_id)

# ==============================
# Step 3: Train/Test split for detection
# ==============================
X = df[["sensor_1", "sensor_2", "sensor_3", "sensor_4"]].values
y = df["leak_flag_bin"].values

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42
)

# ==============================
# Step 4: Train Leak Detection Model
# ==============================
rf_detection = RandomForestClassifier(
    n_estimators=200, random_state=42, class_weight="balanced"
)
rf_detection.fit(X_train, y_train)

# Evaluate detection
y_pred = rf_detection.predict(X_test)
print("\n=== Leak Detection Model ===")
print(f"Accuracy: {accuracy_score(y_test, y_pred):.4f}")
print(f"Precision: {precision_score(y_test, y_pred):.4f}")
print(f"Recall: {recall_score(y_test, y_pred):.4f}")
print(f"F1: {f1_score(y_test, y_pred):.4f}")
print("Confusion Matrix:\n", confusion_matrix(y_test, y_pred))
print("Classification Report:\n", classification_report(y_test, y_pred))

# ==============================
# Step 5: Train Leak Localization Model
# ==============================
# Use only rows where leak_flag = 1
df_leaks = df[df["leak_flag_bin"] == 1].copy()

# Combine leak_from and leak_to into one label
df_leaks["leak_pair"] = df_leaks.apply(
    lambda row: f"{row['leak_from_id']}_{row['leak_to_id']}", axis=1
)

X_loc = df_leaks[["sensor_1", "sensor_2", "sensor_3", "sensor_4"]].values
y_loc = df_leaks["leak_pair"].values

# Encode leak_pair labels
le = LabelEncoder()
y_loc_enc = le.fit_transform(y_loc)

X_loc_train, X_loc_test, y_loc_train, y_loc_test = train_test_split(
    X_loc, y_loc_enc, test_size=0.2, stratify=y_loc_enc, random_state=42
)

rf_localization = RandomForestClassifier(
    n_estimators=200, random_state=42, class_weight="balanced"
)
rf_localization.fit(X_loc_train, y_loc_train)

# Evaluate localization
y_loc_pred = rf_localization.predict(X_loc_test)
print("\n=== Leak Localization Model ===")
print(f"Accuracy: {accuracy_score(y_loc_test, y_loc_pred):.4f}")
print("Classification Report:\n", classification_report(y_loc_test, y_loc_pred))

# ==============================
# Step 6: Save models and encoder
# ==============================
os.makedirs("models", exist_ok=True)
joblib.dump(rf_detection, "models/rf_detection.pkl")
joblib.dump(rf_localization, "models/rf_localization.pkl")
joblib.dump(le, "models/local_label_encoder.pkl")

print("\nModels saved in ./models/")
