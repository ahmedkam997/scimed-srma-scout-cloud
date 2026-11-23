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
  // Use the owner's low-privilege browser token and Supabase RLS instead
  // of a privileged service_role credential. Only a queued dispatch timestamp
  // is mutable, and the DB trigger restores all other fields.
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY") || "";
  if (!apiUrl || !anonKey) return reply(503, { status: "server_configuration_required" });
  const githubToken = Deno.env.get("SCIMED_GITHUB_DISPATCH_TOKEN") || "";
  if (!githubToken) return reply(503, {
    status: "configuration_required",
    message: "Add SCIMED_GITHUB_DISPATCH_TOKEN to Supabase Edge Function Secrets to enable immediate start.",
    manual_url: MANUAL_URL,
  });

  let reserved = false;
  try {
    const res = await fetch((apiUrl.endsWith("/") ? apiUrl.slice(0, -1) : apiUrl) + "/rest/v1/rpc/scimed_request_dispatch", {
      method: "POST",
      headers: {
        apikey: anonKey,
        Authorization: "Bearer " + anonKey,
        "x-scimed-client-token": token,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ p_job_id: requestedId }),
      signal: AbortSignal.timeout(12000),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const code = String(body?.code || "");
      return reply(502, {
        status: "queue_unavailable",
        db_http: res.status,
        db_code: /^[A-Za-z0-9_]{1,20}$/.test(code) ? code : "unknown",
      });
    }
    reserved = await res.json() === true;
  } catch {
    return reply(503, { status: "queue_unavailable" });
  }

  if (!reserved) return reply(202, {
    status: "already_requested_or_not_queued",
    message: "This job was already submitted recently, started, or is no longer queued.",
  });

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
    if (![200, 201, 204].includes(response.status)) {
      // Do not return GitHub's raw response, which may contain private details.
      const error = await response.json().catch(() => ({}));
      const message = String(error?.message || "").toLowerCase();
      const reason = message.includes("resource not accessible")
        ? "insufficient_token_permissions"
        : message.includes("bad credentials")
          ? "invalid_github_token"
          : response.status === 403
            ? "github_actions_permission_or_owner_restriction"
            : "github_rejected_dispatch";
      // Database enforces a two-minute cooldown before the next attempt.
      return reply(502, {
        status: "github_dispatch_failed",
        github_status: response.status,
        github_reason: reason,
        required_permission: "Actions: Read and write on ahmedkam997/scimed-srma-scout-cloud",
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
