"""Job-local adaptive routing for the configured free-provider routes.

No extra health probes or network services. One attempt per available provider
per logical call (transport may perform its own bounded retries). Never
interpret a transport success as scientific correctness.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass,field,replace
import math
import time

from .models import AIRequest,AIResponse
from .providers import FreeProviderFallback,OpenAICompatibleProvider,ProviderFailure,_looks_like_complete_json

VERSION="ADAPTIVE_FREE_ROUTER_V1"
@dataclass
class RouteState:
    provider: object
    blocked_until: float=0.0
    disabled: bool=False
    consecutive_failures: int=0
    attempts: int=0
    successes: int=0
    failures: Counter=field(default_factory=Counter)

def leaves(config):
    if isinstance(config,FreeProviderFallback):
        yield from leaves(config.primary)
        if config.backup is not None:
            yield from leaves(config.backup)
    else:
        yield config

class AdaptiveFreeRouter:
    def __init__(self,config,*,clock=time.monotonic):
        self.config=config
        self.primary=config.primary
        self.backup=config.backup
        self.name=config.name
        self.model=config.model
        self.clock=clock
        self.states=[RouteState(p) for p in leaves(config)]
        if not self.states:
            raise ValueError("No configured free route")
        self.preferred=0
        self.last_provider=self.states[0].provider.name
        self.total_failover_count=0
        self.provider_switch_count=0
        self.deferred_calls=0
        self.skipped_cooling_routes=0
        self.partial_returns=0
        self._last_serving_index=None
        self._last_error=None

    @classmethod
    def from_env(cls):
        return cls(FreeProviderFallback.from_env())

    @property
    def configured_free_route(self):
        return [s.provider.name for s in self.states]

    @property
    def unavailable_free_providers(self):
        now=self.clock()
        return [s.provider.name for s in self.states if s.disabled or s.blocked_until>now]

    @property
    def failover_count(self):
        return self.total_failover_count

    def _failed(self,state,category,*,retry_after=None,disabled=False,minimum=60):
        state.failures[category]+=1
        state.consecutive_failures+=1
        if disabled:
            state.disabled=True
            return
        # Bounded local exponential cooldown. Explicit provider retry-after
        # is a lower bound, not something to shorten to a local cap.
        duration=min(900,minimum*2**min(4,state.consecutive_failures-1))
        if isinstance(retry_after,(int,float)) and math.isfinite(retry_after) and retry_after>0:
            duration=max(duration,retry_after)
        state.blocked_until=self.clock()+duration

    def _handle(self,state,exc):
        if isinstance(exc,ProviderFailure):
            code=exc.status_code
            category=exc.error_category
            if category in ("content_policy_violation","safety_block"):
                state.failures["POLICY_BLOCK"]+=1
                raise exc
            if code==429 or category=="rate_limit":
                daily=(state.provider.name=="groq-free-backup" and exc.remaining_daily_requests==0)
                self._failed(state,"RATE_LIMIT",retry_after=exc.retry_after_seconds,disabled=daily,minimum=120)
            elif code==402:
                self._failed(state,"CREDIT_LIMIT",disabled=True)
            elif code in (401,404) or (code==400 and category in ("model_not_found","unsupported_parameter")):
                self._failed(state,"CONFIGURATION",disabled=True)
            elif code in (408,500,502,503,504,None):
                self._failed(state,"UPSTREAM_UNAVAILABLE",retry_after=exc.retry_after_seconds)
            elif code==400 and category in ("context_window","json_mode_validation"):
                # A request-specific error need not poison other requests.
                state.failures["REQUEST_FORMAT"]+=1
            else:
                # Unknown authorization, safety, and request errors are
                # not a reason to bypass the provider's rejection.
                state.failures["REQUEST_REJECTED"]+=1
                raise exc
        elif isinstance(exc,RuntimeError) and "returned no visible text" in str(exc).lower():
            if any(x in str(exc).lower() for x in ("content_filter","safety","prohibited_content")):
                state.failures["POLICY_BLOCK"]+=1
                raise exc
            self._failed(state,"EMPTY_RESPONSE")
        else:
            # Do not mask programming errors by trying other providers.
            raise exc

    def complete(self,request:AIRequest)->AIResponse:
        order=[self.preferred]+[i for i in range(len(self.states)) if i!=self.preferred]
        partial=None
        last=None
        tried=0
        for i in order:
            state=self.states[i]
            if state.disabled or state.blocked_until>self.clock():
                self.skipped_cooling_routes+=1
                continue
            if tried:
                self.total_failover_count+=1
            tried+=1
            state.attempts+=1
            # Preserve the previous fallback output budget; a primary
            # request retains the original limit. No paid model added.
            sent=replace(request,max_tokens=min(request.max_tokens,4000)) if i!=0 else request
            try:
                response=state.provider.complete(sent)
            except (ProviderFailure,RuntimeError) as exc:
                self._handle(state,exc)
                last=exc
                self._last_error=exc
                continue
            if not _looks_like_complete_json(response.text):
                self._failed(state,"MALFORMED_JSON")
                partial=partial or response
                last=ProviderFailure(state.provider.name,None,"Incomplete JSON response")
                self._last_error=last
                continue
            state.successes+=1
            state.consecutive_failures=0
            state.blocked_until=0.0
            self.preferred=i
            if self._last_serving_index is not None and self._last_serving_index!=i:
                self.provider_switch_count+=1
            self._last_serving_index=i
            self.last_provider=response.provider
            return response
        if partial is not None:
            # Existing generation parser can recover complete proposals;
            # this is not a successful JSON or scientific assessment.
            self.partial_returns+=1
            return partial
        if tried==0:
            self.deferred_calls+=1
            now=self.clock()
            delays=[s.blocked_until-now for s in self.states if not s.disabled and s.blocked_until>now]
            # Do not sleep or poll all unavailable routes. Report a safe
            # retry-after hint; a later logical call can try after cooldown.
            raise ProviderFailure("adaptive-free-router",429 if delays else 503,
                "No configured route currently available",
                retry_after_seconds=max(1,math.ceil(min(delays))) if delays else None,
                error_category="route_deferred")
        if last is not None:
            raise last
        raise ProviderFailure("adaptive-free-router",503,"No usable route response")

    def routing_snapshot(self):
        now=self.clock()
        known=all(isinstance(s.provider,OpenAICompatibleProvider) for s in self.states)
        return {"version":VERSION,"preferred_provider":self.states[self.preferred].provider.name,
            "provider_attempts":sum(s.attempts for s in self.states),
            "provider_switches":self.provider_switch_count,
            "fallback_attempts":self.total_failover_count,
            "deferred_logical_calls":self.deferred_calls,
            "skipped_unavailable_routes":self.skipped_cooling_routes,
            "partial_responses_returned":self.partial_returns,
            "http_attempts":sum(s.provider.http_attempts for s in self.states) if known else None,
            "http_attempts_known":known,
            "providers":[{"provider":s.provider.name,"attempts":s.attempts,"complete_json_responses":s.successes,
                "failure_categories":dict(s.failures),"disabled_for_job":s.disabled,
                "cooldown_remaining_seconds":max(0,math.ceil(s.blocked_until-now))} for s in self.states]}
