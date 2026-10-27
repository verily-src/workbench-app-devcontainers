from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_open_summary_recipe_and_save_again(page, app_url):
    calls, saves = [], []
    def ok(route, data): route.fulfill(status=200, content_type='application/json', json=data)
    source = {'kind':'aurora','resource_id':'db1','table':'people'}
    page.route('**/api/datasources', lambda r: ok(r, {'ready':True,'sources':[{'kind':'aurora','id':'db1','label':'Database'}], 'catalogs_pending':False}))
    page.route('**/api/workflows**', lambda r: ok(r, {'available':False,'jobs':[], 'running_count':0}))
    page.route('**/api/views/all', lambda r: ok(r, {'views':[{'name':'summary','kind':'aurora','resource_id':'db1','store_label':'Database','materialized_sources':0}],'unavailable':[]}))
    page.route('**/api/views/one?**', lambda r: ok(r, {'version':2,'active':0,'datasets':[{'source':source,'title':'people','filters':[{'column':'tissue','kind':'categorical','values':['liver']}],'charts':[],'group_summary':{'group_by':['tissue'],'measure':'value'}}]}))
    columns=[{'name':'tissue','dtype':'object','filter_kind':'categorical'}, {'name':'value','dtype':'float64','filter_kind':'range'}]
    page.route('**/api/data-jobs/open', lambda r: ok(r, {'job_id':'open','status':'complete','result':{'dataset_id':'summary-test','source':'people','rows':2,'columns':columns,'source_ref':source,'query_scope':'database'}}))
    page.route('**/api/datasets/summary-test/query', lambda r: ok(r, {'total':3,'filtered':2,'scope':'database','charts':[], 'rows':{'page':0,'page_size':50,'columns':['tissue','value'],'data':[]}}))
    def summarize(route):
        calls.append(route.request.post_data_json)
        ok(route, {'columns':['tissue','Rows','Numeric values','Sum','Mean','Minimum','Maximum'],'rows':[['liver',2,2,4,2,1,3]],'total_groups':1,'input_rows':2,'page':0,'page_size':50,'scope':'database','sampled':False})
    page.route('**/api/datasets/summary-test/summary', summarize)
    def save(route):
        saves.append(route.request.post_data_json)
        ok(route, {'name':'copy'})
    page.route('**/api/views', save)
    page.goto(app_url)
    page.get_by_role('button',name='summary',exact=True).click(timeout=15000)
    panel=page.get_by_role('region',name='Group summary')
    expect(panel.get_by_role('status')).to_contain_text('2 filtered rows · 1 group',timeout=15000)
    assert calls[0]['group_by']==['tissue'] and calls[0]['measure']=='value'
    assert calls[0]['filters'][0]['values']==['liver']
    page.get_by_label('Saved view name').fill('copy')
    page.locator('.view-save').get_by_role('button',name='Save',exact=True).click()
    expect(page.get_by_text('Saved 1 tab(s) to Database.')).to_be_visible()
    assert saves[0]['datasets'][0]['group_summary']=={'group_by':['tissue'],'measure':'value'}
