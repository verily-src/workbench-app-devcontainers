import json, math, subprocess, sys
from pathlib import Path
path=str(Path(__file__).with_name('cohort_polars.py'))
results=[]
for engine in ['duckdb','polars','polars','duckdb','duckdb','polars']:
    p=subprocess.run([sys.executable,path,engine],check=True,text=True,capture_output=True)
    results.append(json.loads(p.stdout))
a=next(r for r in results if r['engine']=='duckdb'); b=next(r for r in results if r['engine']=='polars')
assert a['sample']==b['sample'], 'sample mismatch'
assert len(a['groups'])==len(b['groups'])
for x,y in zip(a['groups'],b['groups']):
    for key in x:
        assert math.isclose(x[key],y[key],rel_tol=1e-10,abs_tol=1e-10) if key=='mean_measurement' else x[key]==y[key], (key,x,y)
print(json.dumps({'data':'2 million deterministic synthetic rows','same_sample':a['sample']==b['sample'],'group_count':len(a['groups']),'groups':a['groups'],'duckdb_schema':a['schema'],'polars_schema':b['schema'],'runs':[{'engine':r['engine'],'version':r['version'],'elapsed_s':r['elapsed_s'],'max_rss_mib':round(r['max_rss_bytes']/1024/1024,1)} for r in results]},indent=2))
