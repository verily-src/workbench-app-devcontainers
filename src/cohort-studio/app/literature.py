from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LiteratureError(RuntimeError):
    """A literature provider could not return a valid response."""


class PubMedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    query: str = Field(min_length=1, max_length=500)
    limit: StrictInt = Field(default=5, ge=1, le=10)
    api_key: str = Field(default="", max_length=128)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("invalid API key format")
        return value


class BioRxivRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    query: str = Field(min_length=1, max_length=500)
    start_date: date
    end_date: date
    limit: StrictInt = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def exact_iso_date(cls, value: Any) -> Any:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("dates must use YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def valid_window(self) -> "BioRxivRequest":
        days = (self.end_date - self.start_date).days
        if days < 0 or days > 365:
            raise ValueError("date range must be ordered and no longer than 366 days")
        return self


class LiteratureRecord(BaseModel):
    source: str
    title: str
    authors: list[str] = Field(default_factory=list)
    date: str = ""
    doi: str = ""
    pmid: str = ""
    url: str
    abstract: str = ""
    abstract_truncated: bool = False
    provenance: str
    status: str = ""


_TIMEOUT = 8
_BIORXIV_MAX_PAGES = 3
_NCBI_LOCK = threading.Lock()
_NCBI_LAST_CALL = 0.0


def _get(url: str, params: dict[str, str]) -> bytes:
    is_ncbi = "eutils.ncbi.nlm.nih.gov" in url
    target = url if is_ncbi else f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        target,
        data=urllib.parse.urlencode(params).encode() if is_ncbi else None,
        headers={"User-Agent": "CohortStudio/1.0 (literature metadata lookup)"},
        method="POST" if is_ncbi else "GET",
    )
    try:
        if is_ncbi:
            global _NCBI_LAST_CALL
            with _NCBI_LOCK:
                delay = 0.34 - (time.monotonic() - _NCBI_LAST_CALL)
                if delay > 0:
                    time.sleep(delay)
                _NCBI_LAST_CALL = time.monotonic()
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=_TIMEOUT) as response:
            data = response.read(2_000_001)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LiteratureError("Literature provider request failed") from None
    if len(data) > 2_000_000:
        raise LiteratureError("Literature provider response was too large")
    return data


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def search_pubmed(query: str, limit: int = 5, api_key: str = "") -> dict[str, Any]:
    request = PubMedRequest(query=query, limit=limit, api_key=api_key)
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    params = {"db": "pubmed", "term": request.query, "retmode": "json", "retmax": str(request.limit), "sort": "relevance"}
    if request.api_key:
        params["api_key"] = request.api_key
    try:
        payload = json.loads(_get(f"{base}/esearch.fcgi", params))
        total_matches = int(payload["esearchresult"].get("count", 0))
        ids = payload["esearchresult"]["idlist"]
        if not isinstance(ids, list) or not all(re.fullmatch(r"\d{1,12}", str(item)) for item in ids):
            raise ValueError("invalid PMID list")
        ids = ids[:request.limit]
        if not ids:
            return {"articles": [], "coverage": {"query": request.query, "total_matches": total_matches, "ids_fetched": 0, "returned": 0}}
        fetch_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
        if request.api_key:
            fetch_params["api_key"] = request.api_key
        xml_data = _get(f"{base}/efetch.fcgi", fetch_params)
        root = ET.fromstring(xml_data)
    except LiteratureError:
        raise
    except Exception as exc:
        raise LiteratureError("PubMed returned an invalid response") from None

    records = []
    for article in root.findall(".//PubmedArticle"):
        citation = article.find(".//MedlineCitation")
        pmid = _text(citation.find("PMID") if citation is not None else None)
        article_node = citation.find("Article") if citation is not None else None
        if article_node is None or not pmid:
            continue
        authors = []
        for author in article_node.findall(".//AuthorList/Author"):
            name = " ".join(filter(None, (_text(author.find("ForeName")), _text(author.find("LastName")))))
            if not name:
                name = _text(author.find("CollectiveName"))
            if name:
                authors.append(name)
        doi = ""
        for identifier in article.findall(".//ArticleId"):
            if identifier.attrib.get("IdType") == "doi":
                doi = _text(identifier)
                break
        date_node = article_node.find("Journal/JournalIssue/PubDate")
        pubdate = "-".join(filter(None, (_text(date_node.find("Year")) if date_node is not None else "", _text(date_node.find("Month")) if date_node is not None else "", _text(date_node.find("Day")) if date_node is not None else "")))
        abstract = " ".join(filter(None, (_text(x) for x in article_node.findall("Abstract/AbstractText"))))
        records.append(LiteratureRecord(source="PubMed", title=_text(article_node.find("ArticleTitle"))[:400], authors=[name[:100] for name in authors[:10]], date=pubdate[:100], doi=doi[:200], pmid=pmid, url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", abstract=abstract[:3000], abstract_truncated=len(abstract) > 3000, provenance="NCBI PubMed E-utilities: ESearch and EFetch").model_dump())
    return {"articles": records[:request.limit], "coverage": {"query": request.query, "total_matches": total_matches, "ids_fetched": len(ids), "returned": min(len(records), request.limit)}}


def search_biorxiv(query: str, start_date: str, end_date: str, limit: int = 5) -> dict[str, Any]:
    request = BioRxivRequest(query=query, start_date=start_date, end_date=end_date, limit=limit)
    term = request.query.casefold()
    matches: list[dict[str, Any]] = []
    scanned = 0
    total = 0
    base = "https://api.biorxiv.org/details/biorxiv"
    try:
        for page in range(_BIORXIV_MAX_PAGES):
            offset = page * 30
            data = json.loads(_get(f"{base}/{request.start_date.isoformat()}/{request.end_date.isoformat()}/{offset}", {}))
            collection = data.get("collection", [])
            if not isinstance(collection, list):
                raise ValueError("invalid collection")
            total = int(data.get("messages", [{}])[0].get("total", 0))
            for item in collection:
                scanned += 1
                if not isinstance(item, dict):
                    continue
                haystack = " ".join(str(item.get(field, "")) for field in ("title", "abstract", "authors")).casefold()
                if term not in haystack:
                    continue
                doi = str(item.get("doi", ""))
                if not doi or not re.fullmatch(r"10\.1101/[A-Za-z0-9._/-]+", doi):
                    continue
                abstract = str(item.get("abstract", ""))
                matches.append(LiteratureRecord(source="bioRxiv", title=str(item.get("title", ""))[:400], authors=[x.strip()[:100] for x in str(item.get("authors", "")).split(";")[:10] if x.strip()], date=str(item.get("date", ""))[:100], doi=doi, url=f"https://doi.org/{doi}", abstract=abstract[:3000], abstract_truncated=len(abstract) > 3000, provenance=f"bioRxiv details API; date window {request.start_date.isoformat()} to {request.end_date.isoformat()}", status="Preprint; not peer reviewed at posting").model_dump())
                if len(matches) >= request.limit:
                    return {"articles": matches, "coverage": {"start_date": request.start_date.isoformat(), "end_date": request.end_date.isoformat(), "records_scanned": scanned, "total_in_window": total, "truncated": scanned < total}}
            total = int(data.get("messages", [{}])[0].get("total", 0))
            if not collection or offset + 30 >= total:
                break
    except LiteratureError:
        raise
    except Exception as exc:
        raise LiteratureError("bioRxiv returned an invalid response") from None
    return {"articles": matches, "coverage": {"start_date": request.start_date.isoformat(), "end_date": request.end_date.isoformat(), "records_scanned": scanned, "total_in_window": total, "truncated": scanned < total}}
