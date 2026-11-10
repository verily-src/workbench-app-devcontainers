"""Cloud Storage from inside the sandbox: read, write, list and delete objects by gs:// URL.

    import wbstorage
    text = wbstorage.read_text("gs://bucket/folder/file.csv")
    wbstorage.write_text("gs://bucket/results/summary.md", "# Results\\n")
    for name in wbstorage.list_objects("gs://bucket/folder/"): ...
    wbstorage.delete("gs://bucket/results/old.txt")

Why not google.cloud.storage: that client addresses an object as /o/<name> with the slashes in
the name percent-encoded, and OpenShell's proxy (0.1.4) drops such a request without an answer,
so every object in a folder fails. These functions use the XML-style URLs, in which the object
name follows the bucket with its slashes as they are, and the JSON listing endpoint, which puts
the prefix in the query string. The same Application Default Credentials, the same rules.
"""
from urllib.parse import quote

HOST = "https://storage.googleapis.com"
_session = None


def split(url):
    """("bucket", "path/in/bucket") from gs://bucket/path/in/bucket. The path may be empty."""
    if not isinstance(url, str) or not url.startswith("gs://"):
        raise ValueError(f"not a gs:// URL: {url!r}")
    bucket, _, name = url[len("gs://"):].partition("/")
    if not bucket:
        raise ValueError(f"no bucket in {url!r}")
    return bucket, name


def object_url(url):
    """The XML-style URL of an object: literal slashes in the name, everything else encoded."""
    bucket, name = split(url)
    if not name:
        raise ValueError(f"no object name in {url!r}")
    return f"{HOST}/{bucket}/{quote(name, safe='/')}"


def _http():
    global _session
    if _session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default()
        _session = AuthorizedSession(credentials)
    return _session


def _check(response, what):
    if response.status_code >= 300:
        raise RuntimeError(f"{what}: HTTP {response.status_code} {response.text[:300]}")
    return response


def read_bytes(url):
    return _check(_http().get(object_url(url), timeout=120), f"read {url}").content


def read_text(url, encoding="utf-8"):
    return read_bytes(url).decode(encoding)


def write_bytes(url, data, content_type="application/octet-stream"):
    """Writes (creates or replaces) one object. Only in buckets the policy lets you write to."""
    _check(_http().put(object_url(url), data=data, headers={"Content-Type": content_type}, timeout=300), f"write {url}")


def write_text(url, text, content_type="text/plain; charset=utf-8"):
    write_bytes(url, text.encode("utf-8"), content_type)


def delete(url):
    _check(_http().delete(object_url(url), timeout=60), f"delete {url}")


def list_objects(url):
    """The gs:// URLs of the objects under a prefix (gs://bucket/ lists the whole bucket)."""
    bucket, prefix = split(url)
    found, token = [], None
    while True:
        params = {"prefix": prefix, "maxResults": 1000}
        if token:
            params["pageToken"] = token
        page = _check(_http().get(f"{HOST}/storage/v1/b/{bucket}/o", params=params, timeout=120),
                      f"list {url}").json()
        found += [f"gs://{bucket}/{item['name']}" for item in page.get("items", [])]
        token = page.get("nextPageToken")
        if not token:
            return found
