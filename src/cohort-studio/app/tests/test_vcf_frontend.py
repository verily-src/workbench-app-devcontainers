from playwright.sync_api import expect
from tests.test_e2e import app_url
from tests.ui_helpers import load_table


def test_vcf_source_displays_scope_and_unverified_reference(page, app_url):
    def fulfill(route, value, status=200):
        route.fulfill(status=status, content_type='application/json', json=value)
    page.route('**/api/datasources', lambda r: fulfill(r, {'ready': True, 'sources': [{'kind':'s3','id':'lake','label':'lake · S3'}], 'catalogs_pending':False}))
    page.route('**/api/tables?**', lambda r: fulfill(r, [{'name':'genetics.vcf.gz','detail':'file'}]))
    page.route('**/api/workflows**', lambda r: fulfill(r, {'available':False,'jobs':[],'running_count':0}))
    page.route('**/api/views/all', lambda r: fulfill(r, {'views':[],'unavailable':[]}))
    opened = {'dataset_id':'vcf-1','source':'lake / genetics.vcf.gz','rows':2, 'columns':[], 'query_scope':'loaded',
              'source_info': {'format':'vcf','reference':'GRCh38','sample_count':2,'calls':2,
                'source_resource_id':'lake','source_path':'genetics.vcf.gz','object_version':None,'object_etag':'etag',
                'note':'VCF 4.2–4.5: unphased diploid GT-only biallelic SNPs. Missing allele counts are null; genotype retains ./.. QUAL and INFO are not retained.'}}
    page.route('**/api/data-jobs/open', lambda r: fulfill(r, {'job_id':'open-1','status':'complete','result':opened}))
    page.route('**/api/datasets/vcf-1/query', lambda r: fulfill(r, {'total':2,'filtered':2,'charts':[],
        'rows':{'page':0,'page_size':50,'columns':[],'data':[[],[]]},'scope':'loaded','sampled':False}))
    page.goto(app_url)
    load_table(page, "s3:lake", "genetics.vcf.gz")
    expect(page.get_by_text('Reference header (not verified): GRCh38 · 2 samples · 2 calls')).to_be_visible(timeout=15000)
    expect(page.get_by_text('VCF 4.2–4.5: unphased diploid GT-only biallelic SNPs. Missing allele counts are null; genotype retains ./.. QUAL and INFO are not retained.')).to_be_visible()
