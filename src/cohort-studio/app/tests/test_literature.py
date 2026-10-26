import json
from io import BytesIO

import pytest
from pydantic import ValidationError

import literature


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_pubmed_search_maps_metadata_and_api_key(monkeypatch):
    calls = []
    xml = b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Example study</ArticleTitle><AuthorList><Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author></AuthorList><Journal><JournalIssue><PubDate><Year>2024</Year><Month>Jan</Month></PubDate></JournalIssue></Journal><Abstract><AbstractText>Abstract text.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/example</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''

    class Opener:
        def open(self, url, timeout):
            calls.append((url.full_url, url.data, timeout))
            if "esearch" in url.full_url:
                return Response(json.dumps({"esearchresult": {"count": "12", "idlist": ["123"]}}).encode())
            return Response(xml)

    def fake(*handlers):
        return Opener()

    monkeypatch.setattr(literature.urllib.request, "build_opener", fake)
    result = literature.search_pubmed("  lung cancer ", api_key="secret123")
    assert result["articles"][0]["pmid"] == "123"
    assert result["articles"][0]["authors"] == ["Ada Lovelace"]
    assert result["articles"][0]["abstract"] == "Abstract text."
    assert "secret123" in calls[0][1].decode()
    assert "secret123" in calls[1][1].decode()
    assert all("secret123" not in call[0] for call in calls)
    assert result["coverage"] == {"query": "lung cancer", "total_matches": 12, "ids_fetched": 1, "returned": 1}
    assert all(timeout == 8 for _, _, timeout in calls)


def test_pubmed_limits_and_rejects_bad_input(monkeypatch):
    with pytest.raises(ValidationError):
        literature.search_pubmed(" ")
    with pytest.raises(ValidationError):
        literature.search_pubmed("cancer", limit=21)
    with pytest.raises(ValidationError) as error:
        literature.search_pubmed("cancer", api_key="secret&term=bad")
    assert "secret&term=bad" not in str(error.value)


def test_pubmed_provider_failure_does_not_expose_key(monkeypatch):
    class FailingOpener:
        def open(self, url, timeout):
            raise OSError(url.full_url)
    monkeypatch.setattr(literature.urllib.request, "build_opener", lambda *args: FailingOpener())
    with pytest.raises(literature.LiteratureError) as error:
        literature.search_pubmed("cancer", api_key="secret123")
    assert "secret123" not in str(error.value)


def test_biorxiv_filters_only_metadata_in_bounded_window(monkeypatch):
    calls = []
    class Opener:
        def open(self, url, timeout):
            calls.append(url.full_url)
            return Response(json.dumps({"messages": [{"total": 2}], "collection": [
                {"doi": "10.1101/abc.1", "title": "Cancer marker", "authors": "A; B", "date": "2024-02-01", "abstract": "Relevant abstract"},
                {"doi": "10.1101/abc.2", "title": "Other", "authors": "C", "date": "2024-02-01", "abstract": "No match"}
            ]}).encode())
    def fake(*args):
        return Opener()
    monkeypatch.setattr(literature.urllib.request, "build_opener", fake)
    results = literature.search_biorxiv("cancer", "2024-02-01", "2024-02-28")
    assert len(results["articles"]) == 1
    assert results["articles"][0]["authors"] == ["A", "B"]
    assert results["articles"][0]["status"].startswith("Preprint")
    assert "date window 2024-02-01 to 2024-02-28" in results["articles"][0]["provenance"]
    assert len(calls) == 1
    assert results["coverage"] == {"start_date": "2024-02-01", "end_date": "2024-02-28", "records_scanned": 2, "total_in_window": 2, "truncated": False}


def test_biorxiv_validates_date_window_and_limit():
    with pytest.raises(ValidationError):
        literature.search_biorxiv("x", "2024-02-02", "2024-02-01")
    with pytest.raises(ValidationError):
        literature.search_biorxiv("x", "not-a-date", "2024-02-01")
    with pytest.raises(ValidationError):
        literature.search_biorxiv("x", "2024-01-01", "2025-01-02")
    with pytest.raises(ValidationError):
        literature.search_biorxiv("x", "2024-01-01", "2024-01-02", limit=0)
