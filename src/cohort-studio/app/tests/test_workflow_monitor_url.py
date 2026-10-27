import json
import workflows


def test_context_monitor_url_and_invalid_context(tmp_path,monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path,'home',lambda:tmp_path)
    context=tmp_path/'.workbench'/'context.json';context.parent.mkdir()
    context.write_text(json.dumps({'server':{'name':'dev-stable'},'workspace':{'userFacingId':'bugbash-nextflowonaws'}}))
    monkeypatch.delenv('STUDIO_WORKBENCH_URL',raising=False)
    assert workflows.monitor_base()=='https://workbench-dev.verily.com/workspaces/bugbash-nextflowonaws/workflows/monitor/'
    monkeypatch.setenv('STUDIO_WORKBENCH_URL','https://attacker.example')
    assert workflows.monitor_base() is None
    context.write_text(json.dumps({'server':{'name':'dev-stable'},'workspace':{'userFacingId':'../bad'}}))
    assert workflows.monitor_base() is None
