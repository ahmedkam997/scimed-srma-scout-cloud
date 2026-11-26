from .supabase import DiscoveryJob, SupabaseJobStore

__all__ = ["DiscoveryJob", "SupabaseJobStore", "process_job", "run_once"]

def __getattr__(name):
    if name in ("process_job","run_once"):
        from . import worker
        return getattr(worker,name)
    raise AttributeError(name)
