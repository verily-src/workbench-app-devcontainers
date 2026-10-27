from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_create_sql_dataset_without_preview(page,app_url):
    opened=[]; previews=[]
    def ok(route,body): route.fulfill(status=200,content_type='application/json',json=body)
    page.route('**/api/datasources',lambda r:ok(r,{'ready':True,'sources':[{'kind':'aurora','id':'db','label':'Database'}],'catalogs_pending':False}))
    page.route('**/api/workflows**',lambda r:ok(r,{'available':False,'jobs':[],'running_count':0}))
    page.route('**/api/views/all',lambda r:ok(r,{'views':[],'unavailable':[]}))
    def preview(route): previews.append(True);ok(route,{})
    page.route('**/api/sql/preview',preview)
    def source(route):
        ref=route.request.post_data_json['source_ref']; opened.append(ref)
        ok(route,{'dataset_id':'sql-open','source':'query','rows':1,'source_ref':ref,'query_scope':'database','columns':[{'name':'person_id','dtype':'int64','filter_kind':'none'}]})
    def source_job(route):
        ref=route.request.post_data_json['source_ref']; opened.append(ref)
        ok(route,{'job_id':'open','status':'complete','result':{'dataset_id':'sql-open','source':'query','rows':1,'source_ref':ref,'query_scope':'database','columns':[{'name':'person_id','dtype':'int64','filter_kind':'none'}]}})
    page.route('**/api/data-jobs/open',source_job)
    page.route('**/api/datasets/sql-open/query',lambda r:ok(r,{'total':1,'filtered':1,'scope':'database','charts':[],'rows':{'page':0,'page_size':50,'columns':['person_id'],'data':[[1]]}}))
    page.goto(app_url)
    page.get_by_role('button',name='Join tables').click()
    page.get_by_role('button',name='SQL',exact=True).click()
    page.get_by_label('SQL source name').fill('My people')
    page.get_by_label('SQL query').fill('SELECT person_id FROM public.people')
    page.get_by_role('button',name='Create dataset').click()
    expect(page.locator('.tab.active')).to_contain_text('My people',timeout=15000)
    assert opened==[{'kind':'sql','resource_id':'db','sql':'SELECT person_id FROM public.people','name':'My people'}]
    assert previews==[]
