from playwright.sync_api import expect
from tests.test_e2e import app_url
from tests.ui_helpers import menu


def test_explicit_mapping_confirmation_and_download(page, app_url):
    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type='application/json', json=body)
    page.route('**/api/datasources', lambda r: fulfill(r, {'ready':True,'sources':[{'kind':'s3','id':'lake','label':'lake · S3'}],'catalogs_pending':False}))
    page.route('**/api/tables?**', lambda r: fulfill(r, [{'name':'g.vcf.gz','detail':'file'}]))
    page.route('**/api/workflows**', lambda r: fulfill(r, {'available':False,'jobs':[],'running_count':0}))
    page.route('**/api/views/all', lambda r: fulfill(r, {'views':[],'unavailable':[]}))
    names=['sample_id','variant_id','chromosome','position','reference_allele','alternate_allele','alternate_allele_count']
    opened={'dataset_id':'vcf-1','source':'lake / g.vcf.gz','rows':1,'query_scope':'loaded',
            'columns':[{'name':n,'filter_kind':'none','dtype':'text'} for n in names],
            'source_info':{'format':'vcf','reference':'GRCh38','sample_count':1,'calls':1,
                           'source_resource_id':'lake','source_path':'g.vcf.gz','object_version':None,
                           'object_etag':'etag','note':'GT only'}}
    page.route('**/api/data-jobs/open', lambda r: fulfill(r, {'job_id':'open-1','status':'complete','result':opened}))
    page.route('**/api/datasets/vcf-1/query', lambda r: fulfill(r, {'total':1,'filtered':1,'charts':[],
        'rows':{'page':0,'page_size':50,'columns':names,'data':[['S1','rs1','1',10,'A','G',1]]},
        'scope':'loaded','sampled':False}))
    requests=[]
    def export(route):
        requests.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/zip', body=b'PKtest')
    page.route('**/api/datasets/vcf-1/export/plink2', export)
    page.goto(app_url)
    page.get_by_label('Source type').select_option('s3')
    page.get_by_label('Datasource').select_option('s3:lake')
    page.get_by_label('Table').select_option('g.vcf.gz')
    page.get_by_role('button',name='Load file').click()
    menu(page, 'Export options').get_by_role('button', name='Export PLINK 2').click()
    section=page.get_by_role('region',name='PLINK 2 export')
    button=section.get_by_role('button',name='Download PLINK 2 zip')
    expect(button).to_be_disabled()
    section.get_by_label('Reference build').fill('GRCh38')
    expect(section.get_by_label('REF allele')).to_be_disabled()
    expect(button).to_be_disabled()
    section.get_by_label('VCF FILTER policy').select_option('pass_only')
    section.get_by_role('checkbox').check()
    expect(button).to_be_enabled()
    with page.expect_download() as info: button.click()
    assert info.value.suggested_filename == 'cohort.plink2.zip'
    assert info.value.path().read_bytes() == b'PKtest'
    assert requests[0]['mapping']['alternate_allele_count']=='alternate_allele_count'
    assert requests[0]['mapping']['genotype_encoding']=='unphased_diploid_alt_hardcall'
    assert requests[0]['mapping']['reference_build']=='GRCh38'
    assert requests[0]['confirm_hardcalls'] is True
    assert requests[0]['vcf_filter_policy'] == 'pass_only'
