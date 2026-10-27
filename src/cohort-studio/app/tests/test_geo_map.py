import duckdb
import pandas as pd
from sqlalchemy import text
import datasets
import database
import main
from playwright.sync_api import expect
from tests.test_e2e import app_url

POINTS = pd.DataFrame({'longitude': [-79.38, 0.0, 181.0, 2.0, None],
                       'latitude': [43.65, 0.0, 5.0, 91.0, 8.0]})
CHART = {'kind': 'map', 'x': 'longitude', 'y': 'latitude'}


def check(dataset_id):
    result = datasets.query(dataset_id, [], [CHART], 0, 20)['charts'][0]
    assert result['kind'] == 'map'
    assert sorted(result['data']) == [[-79.38, 43.65], [0.0, 0.0]]


def test_map_loaded_data_rejects_invalid_coordinates():
    opened = datasets.open_dataset(POINTS, 'memory')
    try: check(opened['dataset_id'])
    finally: datasets.close_dataset(opened['dataset_id'])


def test_map_duckdb_filters_invalid_coordinates(tmp_path):
    path = str(tmp_path / 'geo.duckdb')
    con = duckdb.connect(path)
    con.register('frame', POINTS)
    con.execute('CREATE TABLE data AS SELECT * FROM frame')
    con.close()
    opened = datasets.open_dataset(POINTS, 'disk', disk_source={'path': path, 'table': 'data', 'columns': list(POINTS.columns), 'rows': len(POINTS)})
    try: check(opened['dataset_id'])
    finally: datasets.close_dataset(opened['dataset_id'])


def test_map_postgres_filters_invalid_coordinates(engine, monkeypatch):
    monkeypatch.setattr(database, 'get_engine_for_resource', lambda rid: engine)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE public.geo_map_test (longitude double precision, latitude double precision)'))
        conn.execute(text('INSERT INTO public.geo_map_test VALUES (-79.38,43.65),(0,0),(181,5),(2,91),(NULL,8)'))
    opened = main._open_source({'kind': 'aurora', 'resource_id': 'omopdb', 'schema': 'public', 'table': 'geo_map_test'})
    try: check(opened['dataset_id'])
    finally:
        datasets.close_dataset(opened['dataset_id'])
        with engine.begin() as conn: conn.execute(text('DROP TABLE public.geo_map_test'))


def test_map_chart_renders_in_browser(page, app_url, tmp_path):
    fixture = tmp_path / 'locations.csv'
    fixture.write_text('longitude,latitude\n' + ''.join(f'{-100 + i},{-40 + i * 0.5}\n' for i in range(100)))
    page.goto(app_url)
    page.locator('input[type="file"]').set_input_files(fixture)
    expect(page.get_by_text('of 100 rows')).to_be_visible(timeout=15000)
    page.locator('select[name="kind"]').select_option('map')
    page.locator('select[name="x"]').select_option('longitude')
    page.locator('select[name="y"]').select_option('latitude')
    with page.expect_response('**/maps/world.geojson') as response:
        page.get_by_role('button', name='Add', exact=True).click()
    assert response.value.status == 200
    card = page.locator('.chart-grid .chart-card').filter(has_text='longitude × latitude')
    expect(card).to_be_visible(timeout=15000)
    expect(card.get_by_text('Longitude and latitude; up to 2,000 valid points.')).to_be_visible()
    expect(card.get_by_role('alert')).to_have_count(0)
    card.screenshot(path='/private/tmp/cohort-map-chart.png')
    with page.expect_download(timeout=30000) as download:
        page.get_by_role('button', name='Export PDF').click()
    output = tmp_path / 'map.pdf'
    download.value.save_as(output)
    assert output.stat().st_size > 10000
