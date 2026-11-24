"""The OSF Trove and registration v2 index may disagree.

A title-filter result must never disappear merely because Trove's Boolean
metadata search returned zero. Neither index proves full novelty clearance.
"""
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.sources.osf import OSFRegistrationsSource


def test_live_osf_index_disagreement_retains_registered_citations():
    calls=[]
    def load(url):
        calls.append(url)
        if "share.osf.io" in url:
            return {
                "data":{
                    "attributes":{"totalResultCount":0},
                    "relationships":{"searchResultPage":{"data":[],"links":{}}},
                },
                "included":[],
            }
        assert "api.osf.io/v2/registrations" in url
        return {
            "meta":{"version":"2.0"},
            "links":{},
            "data":[{
                "id":f"ab{i}23",
                "attributes":{
                    "title":f"Left atrial appendage occlusion in renal disease review {i}",
                    "description":"Public systematic review registration metadata",
                    "date_registered":"2026-11-01T00:00:00",
                },
                "links":{"html":f"https://osf.io/ab{i}23/"},
            } for i in range(5)]
        }

    source=OSFRegistrationsSource(JsonHttpClient(loader=load,retries=0))
    result=source.search('"left atrial appendage occlusion" AND "dialysis"',limit=12)
    assert result.status==SourceStatus.PARTIAL
    assert result.total_count==5
    assert len(result.records)==5
    assert all(r.record_id.startswith("ab") for r in result.records)
    assert all(r.metadata["registry_search"]=="OSF v2 title-only fallback" for r in result.records)
    assert "Index disagreement" in result.message
    assert "Citations retained" in result.message
    assert len(calls)==2


def test_osf_v2_index_disagreement_is_not_a_false_absence():
    def load(url):
        if "share.osf.io" in url:
            return {
                "data":{
                    "attributes":{"totalResultCount":0},
                    "relationships":{"searchResultPage":{"data":[],"links":{}}},
                },
                "included":[],
            }
        return {
            "meta":{"version":"2.0"},
            "links":{},
            "data":[{
                "id":"xyz123",
                "attributes":{"title":"Review title"},
            }],
        }
    res=OSFRegistrationsSource(JsonHttpClient(loader=load,retries=0)).search(
        '"renal replacement" AND "dialysis"')
    assert res.status == SourceStatus.PARTIAL
    assert res.status != SourceStatus.SEARCHED_NEGATIVE
    assert res.records[0].record_id=="xyz123"
