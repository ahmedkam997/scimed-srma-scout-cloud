from __future__ import annotations

import os

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class PubMedSource:
    name = "PubMed"
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def __init__(self, http: JsonHttpClient | None = None, *, sort: str = "pub_date"):
        if sort not in ("pub_date","relevance","mixed"):
            raise ValueError("Unsupported PubMed sort")
        self.sort=sort
        self.api_key = os.getenv("NCBI_API_KEY", "").strip()
        self.email = os.getenv("SCIMED_CONTACT_EMAIL", "").strip()
        self.http = http or JsonHttpClient(
            service="ncbi", min_interval=0.45 if not self.api_key else 0.15,
            retry_rate_limit=True, retries=2, delay=1.0,
        )

    def _params(self, params: dict) -> dict:
        return {**params, "api_key": self.api_key or None,
                "email": self.email or None, "tool": "scimed_review_scout"}

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        if self.sort == "mixed":
            return self._mixed_search(query,limit)
        try:
            data = self.http.get_json(self.base + "esearch.fcgi", self._params({
                "db": "pubmed", "term": query, "retmode": "json", "retmax": max(0, limit), "sort": self.sort
            }))
            block = data.get("esearchresult") or {}
            if "count" not in block:
                return SearchResult(self.name, query, SourceStatus.PARTIAL, message="PubMed response missing count")
            warning = block.get("warninglist") or {}
            invalid_query = bool(block.get("errorlist") or data.get("error") or data.get("ERROR") or (isinstance(warning,dict) and warning.get("quotedphrasesnotfound")))
            total = int(block["count"])
            ids = [str(x) for x in block.get("idlist", [])]
            if total < 0 or len(ids) != len(set(ids)) or len(ids) > total or (total == 0 and ids):
                return SearchResult(self.name, query, SourceStatus.PARTIAL, total_count=total, message="PubMed inconsistent count or IDs")
            if total == 0:
                return SearchResult(self.name, query, SourceStatus.PARTIAL if invalid_query else SourceStatus.SEARCHED_NEGATIVE, total_count=0, message="PubMed query translation warning/error; zero not verified" if invalid_query else "")

            summary_rows = {}
            if ids:
                try:
                    summary = self.http.get_json(self.base + "esummary.fcgi", self._params({
                        "db": "pubmed",
                        "id": ",".join(ids),
                        "retmode": "json",
                    }))
                    result = summary.get("result") or {}
                    summary_rows = {
                        pmid: row for pmid, row in result.items()
                        if pmid != "uids" and isinstance(row, dict)
                    }
                except Exception:
                    summary_rows = {}

            records: list[SearchRecord] = []
            for pmid in ids:
                row = summary_rows.get(pmid, {})
                title = str(row.get("title") or "")
                pubdate = str(row.get("pubdate") or "")
                year = int(pubdate[:4]) if len(pubdate) >= 4 and pubdate[:4].isdigit() else None
                article_ids = row.get("articleids") or []
                doi = ""
                if isinstance(article_ids, list):
                    for item in article_ids:
                        if isinstance(item, dict) and str(item.get("idtype") or "").lower() == "doi":
                            doi = str(item.get("value") or "")
                            break
                records.append(
                    SearchRecord(
                        self.name,
                        pmid,
                        title=title,
                        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        year=year,
                        doi=doi,
                        metadata=row,
                    )
                )
            status = SourceStatus.SEARCHED_POSITIVE if not invalid_query and records and len(records)==min(total,max(0,limit)) and all(r.title.strip() for r in records) else SourceStatus.PARTIAL
            return SearchResult(self.name, query, status, records, total, message=f"PubMed sort={self.sort}; bounded sample; eligibility not established; query_warning_or_error={invalid_query}")
        except Exception as exc:
            message = str(exc)
            if self.api_key:
                message = message.replace(self.api_key, "[SECRET_REDACTED]")
            if self.email:
                message = message.replace(self.email, "[CONTACT_REDACTED]")
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=message)

    def _mixed_search(self, query: str, limit: int) -> SearchResult:
        """Two official sorts; bounded total slots, never infer absence from one arm.
        
        Preserve one third of slots for current literature. Do not fill overlap
        with extra requests: actual unique yield and per-arm coverage are audited.
        """
        import json
        from dataclasses import replace
        limit=max(0,int(limit))
        if limit<2:
            single=PubMedSource(http=self.http,sort="pub_date")
            single.api_key=self.api_key;single.email=self.email
            return single.search(query,limit=limit)
        recent=max(1,limit//3)
        arms=(("relevance",limit-recent),("pub_date",recent))
        results=[];records={};audit=[]
        for sort,cap in arms:
            client=PubMedSource(http=self.http,sort=sort)
            client.api_key=self.api_key;client.email=self.email
            r=client.search(query,limit=cap)
            results.append(r)
            audit.append({"sort":sort,"slots":cap,"status":r.status.value,"reported":r.total_count,"retrieved":len(r.records)})
            for rank,record in enumerate(r.records,1):
                old=records.get(record.record_id)
                meta=dict(old.metadata if old else record.metadata)
                ranks=dict(meta.get("scimed_pubmed_ranks") or {})
                ranks[sort]=rank;meta["scimed_pubmed_ranks"]=ranks
                records[record.record_id]=replace(old or record,metadata=meta)
        totals=[r.total_count for r in results if r.total_count is not None]
        consistent=len(totals)==2 and len(set(totals))==1
        definitive=all(r.status in (SourceStatus.SEARCHED_POSITIVE,SourceStatus.SEARCHED_NEGATIVE) for r in results)
        if consistent and definitive and totals[0]==0 and not records:
            status=SourceStatus.SEARCHED_NEGATIVE
        elif consistent and definitive and records and all(r.title.strip() for r in records.values()):
            status=SourceStatus.SEARCHED_POSITIVE
        elif not records and all(r.status==SourceStatus.ACCESS_FAILED for r in results):
            status=SourceStatus.ACCESS_FAILED
        else:status=SourceStatus.PARTIAL
        msg="PUBMED_MIXED_V1 "+json.dumps({"arms":audit,"unique":len(records),"overlap":sum(len(r.records) for r in results)-len(records),"count_consistent":consistent,"record_budget":limit,"eligibility_verified":False},sort_keys=True)
        return SearchResult(self.name,query,status,list(records.values()),max(totals) if totals else None,msg)
