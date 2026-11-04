import db


def test_new_s3_folder_regenerates_aws_profiles(monkeypatch):
    calls = []
    monkeypatch.setattr(db.cloud_cli, "run", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(db, "warm_connection_string", lambda _rid: None)
    monkeypatch.setattr(db, "_warm_catalogs", lambda: None)
    monkeypatch.setattr(db, "_aws_configured", False)
    monkeypatch.setattr(db, "_aws_profile_ids", set())
    monkeypatch.setattr(db, "_resource_cache", None)
    resources = [{"id": "patient-data", "resourceType": "AWS_S3_STORAGE_FOLDER"},
                 {"id": "omop", "resourceType": "AWS_AURORA_DATABASE"}]
    monkeypatch.setattr(db, "_fetch_resources", lambda: list(resources))

    db._refresh_resource_cache()                       # startup
    assert calls == [["wb", "workspace", "configure-aws"]]

    db._refresh_resource_cache()                       # nothing new
    assert len(calls) == 1

    resources.append({"id": "nextflow_outputs", "resourceType": "AWS_S3_STORAGE_FOLDER"})
    db._refresh_resource_cache()                       # folder created after startup
    assert len(calls) == 2
    assert {"patient-data", "nextflow_outputs"} <= db._aws_profile_ids

    db._refresh_resource_cache()
    assert len(calls) == 2
