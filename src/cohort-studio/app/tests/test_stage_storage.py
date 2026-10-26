import datetime
from decimal import Decimal
import uuid

import duckdb
import pandas as pd

import disk_data


def test_staging_uses_database_types_even_with_empty_preview_and_null_first_batch(engine, monkeypatch):
    table = "eval_types_" + uuid.uuid4().hex[:10]
    monkeypatch.setattr(disk_data.db, "get_engine_for_resource", lambda _: engine)
    monkeypatch.setattr(disk_data, "_BATCH_ROWS", 1)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{table}" (ordinal integer, day date, '
            'stamp timestamptz, large_id bigint, amount numeric(30,8), exact_amount numeric, payload jsonb)')
        conn.exec_driver_sql(f'INSERT INTO public."{table}" VALUES '
            "(1, NULL, NULL, NULL, NULL, NULL, NULL), "
            "(2, '2024-02-29', '2024-02-29 12:34:56+00', 9007199254740993, "
            "1234567890123456789012.12345678, 1234567890123456789012345678901234567890.123456789, '{\"a\":1}')")
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    names = ["ordinal", "day", "stamp", "large_id", "amount", "exact_amount", "payload"]
    live = {"resource_id": "omopdb", "sql": f'SELECT * FROM public."{table}" ORDER BY ordinal',
            "columns": {name: name for name in names}, "params": {}}
    try:
        rows, _ = disk_data.stage_live(con, live, {"df": pd.DataFrame(columns=names)}, "staged", 0)
        assert rows == 2
        output = con.execute("SELECT ordinal, day, stamp::VARCHAR, large_id, amount, exact_amount, payload FROM staged ORDER BY ordinal").fetchall()
        assert output[0] == (1, None, None, None, None, None, None)
        assert output[1][1] == datetime.date(2024, 2, 29)
        assert output[1][2] == "2024-02-29 12:34:56+00"
        assert output[1][3] == 9007199254740993
        assert output[1][4] == Decimal("1234567890123456789012.12345678")
        assert output[1][5] == "1234567890123456789012345678901234567890.123456789"
        assert output[1][6] == '{"a": 1}'
    finally:
        con.close()
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{table}"')
