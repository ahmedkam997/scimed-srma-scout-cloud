// Dispatch a queued SciMed discovery through a server-side GitHub credential.
// Authentication: Supabase gateway JWT + 256-bit browser token, SHA-256 verified
// against the stored job owner hash. NEVER expose GitHub PAT in web/config.js.
const ALLOWED_ORIGIN = "https://ahmedkam997.github.io";
const GITHUB_REPO = "ahmedkam997/scimed-srma-scout-cloud";
const MANUAL_URL = "https://github.com/" + GITHUB_REPO + "/actions/workflows/discovery-worker.yml";
const HEADERS = {
  "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
  "Access-Control-Allow-Headers": "authorization, apikey, x-client-info, content-type, x-scimed-client-token",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Content-Type": "application/json",
  "Cache-Control": "no-store",
};
function reply(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), { status, headers: HEADERS });
}
function isUuid(value: unknown): value is string {
  return typeof value === "string" &&
    /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value);
}
async function hashToken(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, "0")).join("");
}
Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: HEADERS });
  if (req.method !== "POST") return reply(405, { status: "method_not_allowed" });
  const origin = req.headers.get("origin");
  if (origin && origin !== ALLOWED_ORIGIN) return reply(403, { status: "invalid_origin" });
  const token = req.headers.get("x-scimed-client-token") || "";
  if (!/^[a-f0-9]{64}$/i.test(token)) return reply(403, { status: "invalid_session" });
  let body: unknown;
  try { body = await req.json(); } catch { return reply(400, { status: "invalid_request" }); }
  const requestedId = typeof body === "object" && body !== null && "job_id" in body
    ? (body as { job_id: unknown }).job_id : null;
  if (!isUuid(requestedId)) return reply(400, { status: "invalid_job_id" });

  const apiUrl = Deno.env.get("SUPABASE_URL") || "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!apiUrl || !serviceKey) return reply(503, { status: "server_configuration_required" });
  const githubToken = Deno.env.get("SCIMED_GITHUB_DISPATCH_TOKEN") || "";
  if (!githubToken) return reply(503, {
    status: "configuration_required",
    message: "Add SCIMED_GITHUB_DISPATCH_TOKEN to Supabase Edge Function Secrets to enable immediate start.",
    manual_url: MANUAL_URL,
  });

  const ownerHash = await hashToken(token);
  const now = new Date();
  const cutoff = new Date(now.getTime() - 120000).toISOString();
  const query = new URLSearchParams({
    id: "eq." + requestedId,
    client_token_hash: "eq." + ownerHash,
    status: "eq.QUEUED",
    or: "(dispatch_requested_at.is.null,dispatch_requested_at.lt." + cutoff + ")",
    select: "id,status,dispatch_requested_at",
  });
  const endpoint = apiUrl.replace(/\/$/, "") + "/rest/v1/discovery_jobs?" + query.toString();
  const dbHeaders = {
    apikey: serviceKey,
    Authorization: "Bearer " + serviceKey,
    "Content-Type": "application/json",
    Prefer: "return=representation",
  };
  const marker = now.toISOString();
  let claimed: unknown;
  try {
    const res = await fetch(endpoint, {
      method: "PATCH", headers: dbHeaders,
      body: JSON.stringify({ dispatch_requested_at: marker }),
      signal: AbortSignal.timeout(12000),
    });
    if (!res.ok) return reply(502, { status: "queue_unavailable" });
    claimed = await res.json();
  } catch {
    return reply(503, { status: "queue_unavailable" });
  }
  if (!Array.isArray(claimed) || claimed.length !== 1) {
    // Existing, already-running, or not-owned jobs all return a harmless response.
    return reply(202, {
      status: "already_requested_or_not_queued",
      message: "This job was already submitted recently, started, or is no longer queued.",
    });
  }

  try {
    const response = await fetch(
      "https://api.github.com/repos/" + GITHUB_REPO + "/actions/workflows/discovery-worker.yml/dispatches",
      {
        method: "POST",
        headers: {
          Authorization: "Bearer " + githubToken,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
        signal: AbortSignal.timeout(12000),
      }
    );
    if (response.status !== 204) {
      // GitHub did not accept the dispatch; permit a new attempt.
      await fetch(endpoint.replace(/&or=[^&]*/, "") + "&dispatch_requested_at=eq." + encodeURIComponent(marker), {
        method: "PATCH", headers: dbHeaders, body: JSON.stringify({ dispatch_requested_at: null }),
      }).catch(() => {});
      return reply(502, {
        status: "github_dispatch_failed",
        github_status: response.status,
        manual_url: MANUAL_URL,
      });
    }
    return reply(202, {
      status: "dispatched",
      message: "GitHub accepted the worker request. The queued job will be claimed by the next runner.",
    });
  } catch {
    return reply(503, { status: "github_unavailable", manual_url: MANUAL_URL });
  }
});
