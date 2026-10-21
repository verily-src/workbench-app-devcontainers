import uuid

import pytest
from sqlalchemy import text

import live_query
import query_cache


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    query_cache.cache.clear()
    monkeypatch.setenv("STUDIO_QUERY_CACHE_TTL", "30")
    yield
    query_cache.cache.clear()


def _source(engine, monkeypatch, rows):
    name = f"cache_{uuid.uuid4().hex[:10]}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{name}" (id integer, label text)')
        for row in rows:
            conn.exec_driver_sql(f'INSERT INTO public."{name}" VALUES (%s, %s)', row)
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    return name, {"resource_id": "cache-test", "sql":
                  f'SELECT id, label FROM public."{name}"',
                  "columns": {"id": "id", "label": "label"}}


def _query(source, **kwargs):
    return live_query.query(source, [], [], page=0, page_size=20, **kwargs)


def test_live_query_cache_hit_refresh_and_post_refresh_hit(engine, monkeypatch):
    name, source = _source(engine, monkeypatch, [(1, "old")])
    try:
        first = _query(source)
        assert first["rows"]["data"] == [[1, "old"]]
        assert first["cache"]["hit"] is False
        assert first["cache"]["ttl_seconds"] == 30

        second = _query(source)
        assert second["rows"]["data"] == [[1, "old"]]
        assert second["cache"]["hit"] is True
        second["rows"]["data"][0][1] = "mutated"
        assert _query(source)["rows"]["data"] == [[1, "old"]]

        with engine.begin() as conn:
            conn.exec_driver_sql(f'UPDATE public."{name}" SET label = %s', ("new",))
        refreshed = _query(source, refresh=True)
        assert refreshed["rows"]["data"] == [[1, "new"]]
        assert refreshed["cache"]["hit"] is False
        after = _query(source)
        assert after["rows"]["data"] == [[1, "new"]]
        assert after["cache"]["hit"] is True
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{name}"')


def test_failed_live_query_is_not_cached(engine, monkeypatch):
    name, source = _source(engine, monkeypatch, [(1, "bad"), (2, "2")])
    source["sql"] = f'SELECT id, label::integer AS label FROM public."{name}"'
    try:
        with pytest.raises(Exception):
            _query(source)
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DELETE FROM public."{name}" WHERE id = 1')
        success = _query(source)
        assert success["rows"]["data"] == [[2, 2]]
        assert success["cache"]["hit"] is False
        assert _query(source)["cache"]["hit"] is True
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{name}"')


def test_oversized_live_result_is_not_cached(engine, monkeypatch):
    name = f"cache_{uuid.uuid4().hex[:10]}"
    payload = "x" * 5000
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{name}" (id integer, label text)')
        conn.execute(text(
            f'INSERT INTO public."{name}" SELECT n, :label FROM generate_series(1, 1000) n'),
            {"label": payload})
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    source = {"resource_id": "cache-test",
              "sql": f'SELECT id, label FROM public."{name}"',
              "columns": {"id": "id", "label": "label"}}
    try:
        first = live_query.query(source, [], [], page=0, page_size=1000)
        assert first["cache"]["hit"] is False
        with engine.begin() as conn:
            conn.exec_driver_sql(f'UPDATE public."{name}" SET label = %s', ("updated",))
        second = live_query.query(source, [], [], page=0, page_size=1000)
        assert second["cache"]["hit"] is False
        assert second["rows"]["data"][0][1] == "updated"
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{name}"')
