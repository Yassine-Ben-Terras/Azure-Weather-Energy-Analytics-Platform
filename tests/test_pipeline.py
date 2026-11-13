import json
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
from azure.core.exceptions import ResourceModifiedError
from sqlalchemy import text

from ingestion import load_to_warehouse as loader
from ingestion.state import get_client
from forecasting.train_predict import _build_features
from platform_common.database import database_url, warehouse_engine


class BlobTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = warehouse_engine()
        loader._ensure_tables(cls.engine)
        cls.container = os.environ["AZURE_STORAGE_CONTAINER"]
        cls.client = get_client().get_container_client(cls.container)

    def setUp(self):
        self.name = f"openmeteo/FR/2040-01-01/test-{uuid.uuid4()}.json"

    def tearDown(self):
        self.client.delete_blob(self.name)
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM raw.openmeteo_raw WHERE source_blob=:name"), {"name": self.name})
            conn.execute(text("DELETE FROM raw.entsoe_raw WHERE source_blob=:name"), {"name": self.name})
            conn.execute(text("DELETE FROM raw.ingestion_objects WHERE name=:name"), {"name": self.name})

    def upload(self, temperature):
        self.client.upload_blob(self.name, json.dumps({"hourly": {
            "time": ["2040-01-01T00:00"], "temperature_2m": [temperature],
            "wind_speed_10m": [4], "shortwave_radiation": [0],
        }}).encode(), overwrite=True)
        return self.client.get_blob_client(self.name).get_blob_properties()

    def load(self, blob):
        with self.engine.begin() as conn:
            return loader.load_blob(conn, self.client, self.container, blob)

    def values(self):
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT temperature_2m FROM raw.openmeteo_raw WHERE source_blob=:name"),
                                {"name": self.name}).scalars().all()

    def test_same_name_new_version_and_retry(self):
        blob = self.upload(5)
        self.assertTrue(self.load(blob))
        self.assertFalse(self.load(blob))
        self.assertTrue(self.load(self.upload(12)))
        self.assertEqual(self.values(), [12])

    def test_crash_rolls_back_data_and_receipt(self):
        old = self.upload(5)
        self.load(old)
        changed = self.upload(9)
        insert = loader._insert_rows

        def crash_after_insert(*args):
            insert(*args)
            raise RuntimeError("simulated crash before receipt")

        with patch.object(loader, "_insert_rows", side_effect=crash_after_insert):
            with self.assertRaises(RuntimeError):
                self.load(changed)
        self.assertEqual(self.values(), [5])
        with self.engine.connect() as conn:
            etag = conn.execute(text("SELECT etag FROM raw.ingestion_objects WHERE name=:name"),
                                {"name": self.name}).scalar()
        self.assertEqual(etag, old.etag)
        self.assertTrue(self.load(changed))
        self.assertEqual(self.values(), [9])

    def test_replaced_between_listing_and_download(self):
        old = self.upload(3)
        self.upload(4)
        with self.assertRaises(ResourceModifiedError):
            self.load(old)
        self.assertEqual(self.values(), [])

    def test_concurrent_loaders_are_serialized(self):
        self.upload(7)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(loader.run) for _ in range(2)]
            for future in futures:
                future.result(timeout=30)
        self.assertEqual(self.values(), [7])

    def test_unavailable_price_preserves_rows_then_accepts_republication(self):
        self.name = f"entsoe/ES/{uuid.uuid4()}/day_ahead_price_20400101T0000_20400102T0000.xml"

        def publish(content):
            self.client.upload_blob(self.name, content, overwrite=True)
            return self.client.get_blob_client(self.name).get_blob_properties()

        def price_xml(value):
            return (f"<Publication_MarketDocument><TimeSeries><Period><timeInterval>"
                    f"<start>2040-01-01T00:00Z</start></timeInterval><resolution>PT1H</resolution>"
                    f"<Point><position>1</position><price.amount>{value}</price.amount></Point>"
                    f"</Period></TimeSeries></Publication_MarketDocument>").encode()

        original = publish(price_xml(100))
        self.assertTrue(self.load(original))
        missing = publish(b'<Acknowledgement_MarketDocument xmlns="urn:test"><Reason>'
                          b'<code>999</code><text>No matching data found for Data item ENERGY_PRICES</text>'
                          b'</Reason></Acknowledgement_MarketDocument>')
        self.assertFalse(self.load(missing))
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT price FROM raw.entsoe_raw WHERE source_blob=:n"),
                                          {"n": self.name}).scalars().all(), [100])
            self.assertEqual(conn.execute(text("SELECT etag FROM raw.ingestion_objects WHERE name=:n"),
                                          {"n": self.name}).scalar(), original.etag)
        self.assertTrue(self.load(publish(price_xml(120))))
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT price FROM raw.entsoe_raw WHERE source_blob=:n"),
                                          {"n": self.name}).scalars().all(), [120])


class ConfigurationTests(unittest.TestCase):
    def test_optional_prices_do_not_block_required_source_freshness(self):
        from ingestion import quality
        end = datetime(2040, 1, 2, tzinfo=timezone.utc)
        with patch.object(quality, "warehouse_engine") as engine:
            conn = engine.return_value.connect.return_value.__enter__.return_value
            conn.execute.side_effect = lambda statement, params: MagicMock(
                scalar=lambda: None if params.get("kind") == "day_ahead_price" else end
            )
            with self.assertLogs(quality.logger, level="WARNING") as logs:
                quality.check_freshness(end.isoformat())
            self.assertEqual(len(logs.records), 3)

    def test_missing_required_sources_still_fail_freshness(self):
        from ingestion import quality
        end = datetime(2040, 1, 2, tzinfo=timezone.utc)
        for missing in ("load", "generation", "weather"):
            with self.subTest(missing=missing), patch.object(quality, "warehouse_engine") as engine:
                conn = engine.return_value.connect.return_value.__enter__.return_value
                conn.execute.side_effect = lambda statement, params: MagicMock(
                    scalar=lambda: None if params.get("kind", "weather") == missing else end
                )
                with self.assertRaisesRegex(ValueError, "Stale or missing"):
                    quality.check_freshness(end.isoformat())

    def test_only_explicit_known_publication_gaps_are_recognized(self):
        acknowledgement = (b'<Acknowledgement_MarketDocument><Reason><code>999</code>'
                           b'<text>No matching data found for Data item ENERGY_PRICES</text>'
                           b'</Reason></Acknowledgement_MarketDocument>')
        self.assertTrue(loader._unavailable_entsoe_document(acknowledgement, "day_ahead_price"))
        for kind in ("load", "generation"):
            self.assertFalse(loader._unavailable_entsoe_document(acknowledgement, kind))
        generation = acknowledgement.replace(b"ENERGY_PRICES", b"AGGREGATED_GENERATION_PER_TYPE_R3")
        self.assertTrue(loader._unavailable_entsoe_document(generation, "generation"))
        self.assertFalse(loader._unavailable_entsoe_document(generation, "day_ahead_price"))
        demand = acknowledgement.replace(b"ENERGY_PRICES", b"ACTUAL_TOTAL_LOAD_R3")
        self.assertTrue(loader._unavailable_entsoe_document(demand, "load"))
        self.assertFalse(loader._unavailable_entsoe_document(demand, "generation"))
        self.assertFalse(loader._unavailable_entsoe_document(
            acknowledgement.replace(b"No matching data found for Data item ENERGY_PRICES", b"Invalid security token"),
            "day_ahead_price"))
        self.assertFalse(loader._unavailable_entsoe_document(b"<Acknowledgement_MarketDocument/>", "day_ahead_price"))

    def test_stale_required_sources_still_block_forecasting(self):
        from ingestion import quality
        end = datetime(2040, 1, 2, tzinfo=timezone.utc)
        for stale in ("load", "generation", "weather"):
            with self.subTest(stale=stale), patch.object(quality, "warehouse_engine") as engine:
                conn = engine.return_value.connect.return_value.__enter__.return_value
                conn.execute.side_effect = lambda statement, params: MagicMock(
                    scalar=lambda: end - timedelta(hours=25 if params.get("kind", "weather") == stale else 1)
                )
                with self.assertRaisesRegex(ValueError, "Stale or missing " + stale):
                    quality.check_freshness(end.isoformat())

    def test_invalid_response_cannot_erase_previous_data(self):
        with self.assertRaises(ValueError):
            loader._parse_entsoe_xml(b"<Acknowledgement_MarketDocument/>", "load", "FR")
        with self.assertRaises(ValueError):
            loader._parse_openmeteo_json(json.dumps({"hourly": {
                "time": [], "temperature_2m": [], "wind_speed_10m": [], "shortwave_radiation": []
            }}).encode(), "FR")

    def test_resolution_must_be_known(self):
        self.assertEqual(loader._resolution_to_minutes("PT15M"), 15)
        self.assertEqual(loader._resolution_to_minutes("PT1H"), 60)
        with self.assertRaises(ValueError):
            loader._resolution_to_minutes("unexpected")

    def test_reserved_password_characters(self):
        url = database_url()
        self.assertEqual(url.password, os.environ["WAREHOUSE_PASSWORD"])
        with warehouse_engine().connect() as conn:
            self.assertEqual(conn.execute(text("SELECT 1")).scalar(), 1)

    def test_lag_uses_time_not_row_count(self):
        timestamps = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC").delete(5)
        frame = pd.DataFrame({"zone": "FR", "ts": timestamps,
                              "load_mw": range(49), "wind_mw": range(49), "solar_mw": range(49)})
        featured = _build_features(frame)
        missing = featured.loc[featured.ts == pd.Timestamp("2026-01-02T05:00Z"), "load_mw_lag24"].iloc[0]
        self.assertTrue(pd.isna(missing))
        value = featured.loc[featured.ts == pd.Timestamp("2026-01-02T06:00Z"), "load_mw_lag24"].iloc[0]
        self.assertEqual(value, 5)

    def test_reader_cannot_write_or_read_raw(self):
        from sqlalchemy import create_engine
        engine = create_engine(database_url().set(username="api_reader", password=os.environ["API_DB_PASSWORD"]))
        with engine.connect() as conn:
            conn.execute(text("SELECT * FROM public.forecasts LIMIT 1"))
        for statement in ("DELETE FROM public.forecasts", "SELECT * FROM raw.openmeteo_raw"):
            with engine.connect() as conn:
                with self.assertRaises(Exception):
                    conn.execute(text(statement))


if __name__ == "__main__":
    unittest.main()
