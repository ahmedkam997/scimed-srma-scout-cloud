"""One tiny completion per configured current free provider; never log keys or response text."""
from pathlib import Path
import json,time
from scimed_scout.ai.adaptive_router import AdaptiveFreeRouter
from scimed_scout.ai.models import AIRequest
from scimed_scout.ai.providers import ProviderFailure
def main():
    rows=[]
    try:router=AdaptiveFreeRouter.from_env()
    except (RuntimeError,ValueError):
        router=None
    if router:
        for state in router.states:
            provider=state.provider;start=time.monotonic()
            row={"provider":provider.name,"model":provider.model,"remaining_quota_known":False}
            try:
                response=provider.complete(AIRequest("Return exactly one small JSON object.","Return only {\"ok\":true}",temperature=0,max_tokens=250))
                try:valid=json.loads(response.text)=={"ok":True}
                except (ValueError,TypeError):valid=False
                row["status"]="JSON_OK" if valid else "INVALID_JSON"
            except ProviderFailure as e:
                row.update(status="PROVIDER_UNAVAILABLE",http_status=e.status_code,error_category=e.error_category,retry_after_seconds=e.retry_after_seconds,remaining_daily_requests=e.remaining_daily_requests,remaining_quota_known=e.remaining_daily_requests is not None)
            except Exception as e:row.update(status="PROVIDER_UNAVAILABLE",error_type=type(e).__name__)
            row["elapsed_seconds"]=round(time.monotonic()-start,2);rows.append(row)
    out={"status":"PROBED" if rows else "NOT_CONFIGURED","providers":rows,"scientific_validity_verified":False}
    Path("provider-health.json").write_text(json.dumps(out,indent=2)+"\n");print(json.dumps(out),flush=True)
if __name__=="__main__":main()
