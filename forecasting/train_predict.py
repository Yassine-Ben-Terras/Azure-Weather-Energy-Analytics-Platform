"""
Baseline one-hour-ahead forecasting job (not a 24-hour horizon).

Reads `marts.fct_demand_weather`, builds simple lagged/calendar features,
trains a gradient-boosted regressor per target (demand, wind, solar), and
writes predictions to `forecasts` with a timestamp and model version.

This is intentionally a baseline -- swap in a real feature store, backtesting,
and model registry as the project matures.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sqlalchemy import text
from platform_common.migrations import migrate
from platform_common.database import warehouse_engine

MODEL_VERSION = "baseline-gbr-v4"
TARGETS = {
    "load_mw": "demand",
    "wind_mw": "wind_generation",
    "solar_mw": "solar_generation",
}
# Below this many usable training rows, skip rather than fit a near-meaningless
# model. Kept low deliberately -- this is a baseline meant to produce *something*
# real early on, not a production-quality forecast yet (see roadmap: revisit
# once weeks of history have accumulated and add the 168h lag back in).
MIN_TRAIN_ROWS = 50


_engine = warehouse_engine


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["zone", "ts"]).copy()
    df["hour"] = df["ts"].dt.hour
    df["dayofweek"] = df["ts"].dt.dayofweek
    df["month"] = df["ts"].dt.month
    # Join timestamps: 24 rows is not 24 hours when observations are missing.
    lag = df[["zone", "ts", *TARGETS]].copy()
    lag["ts"] += pd.Timedelta(hours=24)
    lag = lag.rename(columns={name: f"{name}_lag24" for name in TARGETS})
    df = df.merge(lag, on=["zone", "ts"], how="left", validate="one_to_one")
    return df


def _feature_columns() -> list[str]:
    return [
        "hour", "dayofweek", "month",
        "temperature_2m", "wind_speed_10m", "shortwave_radiation",
        "load_mw_lag24",
        "wind_mw_lag24",
        "solar_mw_lag24",
    ]


def _ensure_forecasts_table(engine):
    migrate(engine)


def main(interval_end: str | None = None) -> None:
    engine = _engine()
    _ensure_forecasts_table(engine)

    with engine.connect() as conn:
        end = datetime.fromisoformat(interval_end) if interval_end else datetime.now(timezone.utc)
        result = conn.execute(text("""select * from marts.fct_demand_weather
            where ts < :end and ts >= :end - make_interval(days => :days)"""),
            {"end": end, "days": int(os.getenv("TRAINING_DAYS", "90"))})
        df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    if df.empty:
        print("[train_predict] no data in mart yet, skipping.")
        return

    df = _build_features(df)
    feature_cols = _feature_columns()

    predictions = []
    predicted_at = datetime.now(timezone.utc)

    for zone, zdf in df.groupby("zone"):
        for target_col, target_name in TARGETS.items():
            train_df = zdf.dropna(subset=feature_cols + [target_col])
            if len(train_df) < MIN_TRAIN_ROWS:
                print(f"[train_predict] not enough rows yet for {zone}/{target_name} "
                      f"({len(train_df)} < {MIN_TRAIN_ROWS}), skipping.")
                continue

            X = train_df[feature_cols]
            y = train_df[target_col]

            model = GradientBoostingRegressor(random_state=42)
            model.fit(X, y)

            latest_row = zdf.dropna(subset=feature_cols).iloc[[-1]]
            next_ts = latest_row["ts"].iloc[0] + pd.Timedelta(hours=1)
            pred_features = latest_row[feature_cols].copy()
            pred_features["hour"] = next_ts.hour
            pred_features["dayofweek"] = next_ts.dayofweek
            pred_features["month"] = next_ts.month
            # Align lag values to the hour being predicted, not the previous row.
            lag_row = zdf[zdf["ts"] == next_ts - pd.Timedelta(hours=24)]
            if lag_row.empty or lag_row[list(TARGETS)].isna().any(axis=None):
                continue
            for col in TARGETS:
                pred_features[f"{col}_lag24"] = lag_row[col].iloc[-1]
            # Weather forecast for target hour when available; no historical future leakage.
            with engine.connect() as conn:
                weather_row = conn.execute(text("""SELECT temperature_2m, wind_speed_10m,
                    shortwave_radiation FROM raw.openmeteo_raw WHERE zone=:zone AND time=:ts
                    ORDER BY loaded_at DESC LIMIT 1"""), {"zone": zone, "ts": next_ts.to_pydatetime()}).mappings().first()
            if weather_row and all(value is not None for value in weather_row.values()):
                for col, value in weather_row.items():
                    pred_features[col] = value
            pred_value = float(model.predict(pred_features)[0])

            predictions.append({
                "zone": zone,
                "ts": next_ts,
                "target": target_name,
                "predicted_value": pred_value,
                "model_version": MODEL_VERSION,
                "predicted_at": predicted_at,
            })

    if not predictions:
        print("[train_predict] no predictions generated.")
        return

    pred_df = pd.DataFrame(predictions)
    with engine.begin() as conn:
        for _, row in pred_df.iterrows():
            conn.execute(text("""
                INSERT INTO forecasts (zone, ts, target, predicted_value, model_version, predicted_at)
                VALUES (:zone, :ts, :target, :predicted_value, :model_version, :predicted_at)
                ON CONFLICT (zone, ts, target, model_version)
                DO UPDATE SET predicted_value = EXCLUDED.predicted_value, predicted_at = EXCLUDED.predicted_at
            """), row.to_dict())

    print(f"[train_predict] wrote {len(pred_df)} predictions.")
    print("PIPELINE_FORECAST_OK")


if __name__ == "__main__":
    main()