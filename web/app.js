import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(()=>{});

const config = window.SCIMED_CONFIG || {};
const els = {
  backend: document.getElementById('backendStatus'),
  start: document.getElementById('start'),
  refresh: document.getElementById('refresh'),
  specialty: document.getElementById('specialty'),
  questionType: document.getElementById('questionType'),
  revisitDays: document.getElementById('revisitDays'),
  jobs: document.getElementById('jobs'),
  active: document.getElementById('activeCount'),
  qualified: document.getElementById('qualifiedCount'),
  review: document.getElementById('reviewCount'),
};

let supabase = null;
let jobs = [];
let pollTimer = null;

function backendState(kind, title, detail) {
  els.backend.className = `status-card status-${kind}`;
  els.backend.innerHTML = `<b>${escapeHtml(title)}</b><span>${escapeHtml(detail)}</span>`;
}

function deviceToken() {
  const key = 'scimed-review-scout-device-token-v1';
  const existing = localStorage.getItem(key);
  if (existing) return existing;

  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const token = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  localStorage.setItem(key, token);
  return token;
}

async function init() {
  if (!config.supabaseUrl || !config.supabaseAnonKey) {
    backendState('error', 'Backend setup required', 'The Supabase project configuration is missing.');
    return;
  }

  supabase = createClient(config.supabaseUrl, config.supabaseAnonKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
    global: {
      headers: {
        'x-scimed-client-token': deviceToken(),
      },
    },
  });

  try {
    await loadJobs();
    backendState(
      'ok',
      'Cloud queue connected',
      'Jobs continue in the background after you close this browser. Job history belongs to this browser profile.'
    );
    const stale = jobs.find(row => row.status === 'QUEUED' &&
      Date.now() - new Date(row.created_at).getTime() >= 120000);
    if (stale) wakeWorker(stale.id, { silent: true }).catch(() => {});
    els.start.disabled = false;
    els.refresh.disabled = false;
    pollTimer = setInterval(loadJobs, 5000);
  } catch (error) {
    backendState('error', 'Backend connection failed', error.message || String(error));
  }
}

async function startDiscovery() {
  if (!supabase) return;
  els.start.disabled = true;
  const specialty = els.specialty.value;
  const questionType = els.questionType.value;
  if (jobs.some(job => job.specialty === specialty && job.question_type === questionType &&
      ['QUEUED', 'RUNNING'].includes(job.status))) {
    backendState('waiting', 'Discovery already active',
      'A matching job is already queued or running. Refresh the existing job instead of starting a duplicate.');
    els.start.disabled = false;
    return;
  }

  try {
    const { data, error } = await supabase
      .from('discovery_jobs')
      .insert({
        specialty,
        question_type: questionType,
        candidate_count: 20,
        final_options: 3,
        min_verify: 4,
        max_verify: 6,
        limit_per_query: 12,
        revisit_days: Number(els.revisitDays.value),
      })
      .select()
      .single();

    if (error) throw error;
    backendState('waiting', 'Discovery queued', 'Requesting a worker for your saved job.');
    jobs = [data, ...jobs.filter(job => job.id !== data.id)];
    renderJobs();
    await wakeWorker(data.id, { silent: true });
    await loadJobs();
  } catch (error) {
    backendState('error', 'Could not queue discovery', error.message || String(error));
  } finally {
    els.start.disabled = false;
  }
}

async function wakeWorker(jobId, { silent = false } = {}) {
  if (!supabase) return;
  const job = jobs.find(row => row.id === jobId);
  if (!job || job.status !== 'QUEUED') return;

  const button = Array.from(els.jobs.querySelectorAll('[data-wake-job]'))
    .find(item => item.dataset.wakeJob === jobId);
  if (button) button.disabled = true;

  try {
    const { data, error } = await supabase.functions.invoke('wake-discovery-worker', {
      body: { job_id: jobId },
      headers: { 'x-scimed-client-token': deviceToken() },
    });
    if (error) {
      let status = '';
      try {
        const detail = await error.context?.json?.();
        status = detail?.status || '';
      } catch {}
      if (status === 'configuration_required') {
        backendState('waiting', 'One-time dispatch setup needed',
          'Add SCIMED_GITHUB_DISPATCH_TOKEN in Supabase Function Secrets, or run the GitHub workflow manually.');
      } else if (!silent) {
        backendState('waiting', 'Worker dispatch unavailable',
          'The job remains safely queued. Use the GitHub manual workflow link in its card.');
      }
    } else if (data?.status === 'dispatched') {
      backendState('ok', 'Worker requested',
        'GitHub accepted the request to run the worker. Your existing job remains queued until claimed.');
    } else if (data?.status === 'already_requested_or_not_queued') {
      if (!silent) backendState('waiting', 'Worker request already submitted',
        'No duplicate run was requested. Refresh to check whether the worker claimed this job.');
    } else if (!silent) {
      backendState('waiting', 'Worker not dispatched',
        'Use the GitHub workflow link to start the saved job manually.');
    }
  } catch (error) {
    if (!silent) backendState('waiting', 'Could not request worker',
      'The job is still in the queue. Open the manual GitHub workflow link.');
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadJobs() {
  if (!supabase) return;
  const { data, error } = await supabase
    .from('discovery_jobs')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(20);

  if (error) throw error;
  jobs = data || [];
  renderJobs();
}

function safeEvidenceLink(record) {
  const title = escapeHtml(record?.title || record?.record_id || 'Untitled record');
  const source = escapeHtml(record?.source || 'External source');
  try {
    const url = new URL(record?.url || '');
    if (url.protocol !== 'https:') return `${title} (${source})`;
    const host = url.hostname.toLowerCase();
    const allowed = [
      'pubmed.ncbi.nlm.nih.gov', 'europepmc.org', 'www.ebi.ac.uk',
      'doi.org', 'api.openalex.org', 'openalex.org',
      'www.crd.york.ac.uk', 'osf.io', 'clinicaltrials.gov',
      'www.semanticscholar.org', 'www.crossref.org'
    ];
    if (!allowed.includes(host)) return `${title} (${source})`;
    return `<a href="${escapeHtml(url.href)}" target="_blank" rel="noopener noreferrer">${title}</a> (${source})`;
  } catch {
    return `${title} (${source})`;
  }
}

function renderJobs() {
  const active = jobs.filter(job => ['QUEUED', 'RUNNING'].includes(job.status)).length;
  const qualified = jobs.reduce((sum, job) => sum + qualifiedOptions(job).length, 0);
  const needsReview = jobs.filter(job =>
    job.status === 'FAILED' ||
    (job.status === 'COMPLETED' && Number(job.result_json?.package?.selection_policy?.shortfall || 0) > 0)
  ).length;

  els.active.textContent = String(active);
  els.qualified.textContent = String(qualified);
  els.review.textContent = String(needsReview);

  if (!jobs.length) {
    els.jobs.innerHTML = '<p class="empty">No discovery jobs yet.</p>';
    return;
  }

  els.jobs.innerHTML = jobs.map(job => {
    const options = qualifiedOptions(job);
    const progress = Number(job.progress || 0);
    const statusClass = String(job.status || '').toLowerCase();
    const summary = job.result_json?.run_summary || {};
    const statusCounts = summary.status_counts || {};
    const provisional = Number(statusCounts.PROVISIONAL_BACKUP || 0);
    const rejected = Number(statusCounts.REJECTED || 0);
    const checked = Number(summary.verified_candidates || 0);
    const generated = Number(summary.generated_candidates || 0);
    const failovers = Number(summary.ai_failover_count || 0);
    const recentSkipped = Number(summary.recent_topics_skipped_count || 0);
    const recentDetail = Array.isArray(summary.recent_topics_skipped) ? summary.recent_topics_skipped : [];
    const recentHtml = job.status === 'COMPLETED' && recentSkipped
      ? `<details class="score-audit">
          <summary>Recently checked topics skipped: ${recentSkipped}</summary>
          <p class="help">These topics were already evaluated in this browser's recent jobs. Skipping them avoids repeating full source verification. They become eligible again after the selected interval.</p>
          ${recentDetail.map(item => `<article class="score-item">
            <b>${escapeHtml(item.title || '')}</b>
            <p>Previous question: ${escapeHtml(item.matched_previous_title || '')}</p>
            <p>Eligible for another check: ${escapeHtml(item.recheck_after ? new Date(item.recheck_after).toLocaleDateString() : 'unknown')}</p>
          </article>`).join('')}
        </details>` : '';
    const summaryHtml = job.status === 'COMPLETED' && checked
      ? `<div class="job-result-summary">
          <b>Discovery review summary</b>
          <p>Generated ${escapeHtml(generated)} candidates. Checked ${escapeHtml(checked)}.
          Qualified ${escapeHtml(options.length)}. Provisional ${escapeHtml(provisional)}.
          Rejected ${escapeHtml(rejected)}.
          AI fallback calls ${escapeHtml(failovers)}.</p>
          ${provisional && !options.length
            ? '<p>Source verification is incomplete for the provisional topics. They are not confirmed to lack novelty or scientific value.</p>'
            : ''}
          ${!Array.isArray(summary.candidate_audits)
            ? '<p>This earlier run did not save topic-level source failures. Its exact blockers are not recoverable from this report.</p>'
            : ''}
        </div>`
      : '';
    const optionHtml = options.length
      ? `<div class="topic-list">${options.map(option => `
          <article class="topic">
            <div class="topic-head">
              <span class="topic-number">#${escapeHtml(option.option_number)}</span>
              <span class="topic-specialty">${escapeHtml(option.specialty || '')}</span>
            </div>
            <b>${escapeHtml(option.title || '')}</b>
            <p>${escapeHtml(option.review_question || '')}</p>
            <small>${escapeHtml((option.question_type || '').replaceAll('_',' '))}</small>
          </article>
        `).join('')}</div>`
      : '';

    const queuedAgeMinutes = job.status === 'QUEUED'
      ? (Date.now() - new Date(job.created_at).getTime()) / 60000 : 0;
    const workerHelp = job.status === 'QUEUED' && queuedAgeMinutes >= 1
      ? `<div class="worker-help">
          <p>Your job is saved. If the worker has not claimed it, request a direct start.</p>
          <button class="secondary small" data-wake-job="${escapeHtml(job.id)}">Start queued worker now</button>
          <p>One-time direct start requires a secure GitHub dispatch token in Supabase.</p>
          <a class="worker-link" href="https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/workflows/discovery-worker.yml"
             target="_blank" rel="noopener noreferrer">Manual GitHub worker controls</a>
          <p>Fallback: choose Run workflow, main, then Run workflow. Do not create another discovery job.</p>
        </div>` : '';
    const draftCheckpoint = job.result_json?.checkpoint || {};
    const evidenceLeads = Array.isArray(draftCheckpoint.recent_pubmed_cues)
      ? draftCheckpoint.recent_pubmed_cues : [];
    const evidenceHtml = evidenceLeads.length && ['RUNNING', 'FAILED'].includes(job.status)
      ? `<details class="score-audit" ${job.status === 'FAILED' ? 'open' : ''}>
          <summary>Saved PubMed evidence leads (${evidenceLeads.length})</summary>
          <p class="help">Real PubMed records to explore. These are not screened included studies, validated PICO questions or confirmed novel systematic reviews.</p>
          ${evidenceLeads.map(item => `<article class="score-item">
            ${safeEvidenceLink({title:item.title, source:'PubMed', url:item.url, record_id:item.pmid})}
            <p>Publication year: ${escapeHtml(item.year || 'Not available')}</p>
          </article>`).join('')}
        </details>` : '';
    const draftCandidates = Array.isArray(draftCheckpoint.candidates) ? draftCheckpoint.candidates : [];
    const draftHtml = draftCandidates.length && ['RUNNING', 'FAILED'].includes(job.status)
      ? `<details class="score-audit">
          <summary>Saved draft questions (${draftCandidates.length})</summary>
          <p class="help">These AI-generated questions were saved before a later step. None has been verified for novelty, eligibility or published review overlap.</p>
          ${draftCandidates.map(item => `<article class="score-item">
            <b>${escapeHtml(item.title || '')}</b>
            <p>${escapeHtml(item.review_question || '')}</p>
          </article>`).join('')}
        </details>` : '';

    const provisionalOptions = Array.isArray(job.result_json?.package?.provisional_options)
      ? job.result_json.package.provisional_options : [];
    const provisionalHtml = job.status === 'COMPLETED' && provisionalOptions.length
      ? `<details class="score-audit" open>
          <summary>Provisional review topics (${provisionalOptions.length}) - verification required</summary>
          <p class="help">These are research hypotheses, not qualified or novelty-confirmed topics. Source access and eligibility require manual review.</p>
          ${provisionalOptions.map(topic => `<article class="score-item">
            <b>${escapeHtml(topic.title || '')}</b>
            <p>${escapeHtml(topic.review_question || '')}</p>
            <div class="score-data">
              <span>Study candidates: ${escapeHtml(topic.discovered_primary_study_candidates ?? 'N/A')}</span>
              <span>Clinical area: ${escapeHtml(topic.specialty || 'Unknown')}</span>
            </div>
            <details><summary>Found published reviews (verify overlap)</summary>
              ${(topic.published_review_examples || []).map(item => `<p>${safeEvidenceLink(item)}</p>`).join('') || '<p>No review examples preserved</p>'}
            </details>
            <details><summary>Potential study records (not eligibility-screened)</summary>
              ${(topic.primary_study_examples || []).map(item => `<p>${safeEvidenceLink(item)}</p>`).join('') || '<p>No examples preserved</p>'}
            </details>
            <details><summary>Why provisional?</summary>
              <p>${(topic.source_blockers || []).map(escapeHtml).join('; ') || 'Manual source and methods checks remain'}</p>
              <p>To resolve unreviewed registration matches, check
                <a href="https://www.crd.york.ac.uk/PROSPERO/search" target="_blank" rel="noopener noreferrer">official PROSPERO</a>
                and
                <a href="https://osf.io/search/" target="_blank" rel="noopener noreferrer">official OSF Search</a>.
                A partial automated search is not a negative result.</p>
              <p>${(topic.unresolved_checks || []).map(escapeHtml).join('; ')}</p>
              <p>${Object.entries(topic.source_statuses || {}).map(([key,value]) => escapeHtml(key) + ': ' + escapeHtml(value)).join('; ')}</p>
            </details>
          </article>`).join('')}
        </details>` : '';

    const actions = ['QUEUED', 'RUNNING'].includes(job.status)
      ? `<div class="job-actions">
          <button class="secondary small cancel-button" data-cancel-job="${escapeHtml(job.id)}">Cancel job</button>
        </div>`
      : job.status === 'COMPLETED'
        ? `<div class="job-actions">
            <button class="secondary small" data-copy-job="${escapeHtml(job.id)}">${options.length ? 'Copy for ChatGPT' : 'Copy diagnostic report'}</button>
            <button class="secondary small" data-download-job="${escapeHtml(job.id)}">${options.length ? 'Download JSON' : 'Download report JSON'}</button>
          </div>`
        : '';

    const audits = Array.isArray(job.result_json?.run_summary?.candidate_audits)
      ? job.result_json.run_summary.candidate_audits : [];
    const auditHtml = job.status === 'COMPLETED' && audits.length
      ? `<details class="score-audit">
          <summary>Scientific scoring audit (${audits.length} checked topics)</summary>
          <p class="help">Evidence-based discovery proxies, not validated novelty measurements or publication probabilities. Verify original studies before starting a review.</p>
          ${audits.map(audit => {
            const score = audit.scorecard || {};
            const trace = score.scoring_trace || {};
            const failed = (audit.failed_gates || []).map(gate => escapeHtml(gate.name)).join('; ');
            const pending = (audit.pending || []).map(x => escapeHtml(x)).join('; ');
            const blockers = (audit.coverage_blockers || []).map(x => escapeHtml(x)).join('; ');
            const sourceStatus = Object.entries(audit.source_statuses || {})
              .map(([name, status]) => `${escapeHtml(name)}: ${escapeHtml(status)}`).join('; ');
            const diagnostics = (audit.source_diagnostics || []).slice(0, 8).map(item =>
              `${escapeHtml(item.source || '')} [${escapeHtml(item.status || '')}]: ${escapeHtml(item.message || 'no error description')}`
            ).join('; ');
            return `<article class="score-item">
              <b>${escapeHtml(audit.title)}</b>
              <div class="score-data">
                <span>Novelty: ${escapeHtml(trace.novelty_status === 'NOT_ESTIMABLE' ? 'Not estimable' : (score.overall_novelty ?? 'N/A'))} / 5</span>
                <span>Information gain proxy: ${escapeHtml(String(trace.information_gain_status || '').startsWith('NOT_ESTIMABLE') ? 'Not estimable' : (score.new_information_gain ?? 'N/A'))} / 5</span>
                <span>Priority index: ${escapeHtml(score.publication_oriented_score ?? 'N/A')} / 100</span>
                <span>Primary-study candidates: ${escapeHtml(audit.unique_primary_study_candidates ?? 'N/A')}</span>
              </div>
              <small>${escapeHtml(trace.information_gain_status || 'Not estimated')}</small>
              ${failed ? `<p>Failed gates: ${failed}</p>` : ''}
              ${pending ? `<p>Unresolved: ${pending}</p>` : ''}
              ${blockers ? `<p>Source coverage blockers: ${blockers}</p>` : ''}
              ${sourceStatus ? `<p>Source search statuses: ${sourceStatus}</p>` : ''}
              ${diagnostics ? `<details><summary>Source failure details</summary><p>${diagnostics}</p></details>` : ''}
              <details><summary>Methods and score weights</summary>
                <pre>${escapeHtml(JSON.stringify({
                  version: trace.method_version || '',
                  novelty_status: trace.novelty_status || '',
                  information_gain_status: trace.information_gain_status || '',
                  weights: trace.criteria_weights || {},
                  study_date_completeness: trace.primary_date_completeness,
                  latest_matching_review_publication_year: trace.latest_related_review_publication_year,
                  newer_primary_study_candidates: trace.primary_records_newer_than_publication,
                  score_sensitivity_range: trace.sensitivity_score_range || [],
                  source_competitors: trace.overlap_evidence || [],
                  model_only_judgments: trace.model_only_judgments || [],
                  limitations: trace.limitations || []
                }, null, 2))}</pre>
              </details>
            </article>`;
          }).join('')}
        </details>`
      : '';

    const failureHint = job.status === 'FAILED'
      ? /ProviderFailure|429|quota|Free AI request|AI did not return any complete candidate JSON/.test(job.error_text || '')
        ? 'The worker started but the free AI providers did not return usable proposals. Check your OpenRouter allowance and configure the Groq backup. Any preserved PubMed records are shown below. Avoid launching duplicate jobs.'
        : /JSONDecodeError|Unterminated string/.test(job.error_text || '')
          ? 'The model returned incomplete JSON. This is an AI response problem, not proof that no review topics exist.'
          : 'The worker stopped with an error. Expand details for the diagnostic trace.'
      : '';
    const error = job.error_text
      ? `<div class="job-failure-hint">${escapeHtml(failureHint)}</div>
        <details class="error-details"><summary>Error details</summary><pre>${escapeHtml(job.error_text)}</pre></details>`
      : '';

    return `
      <article class="job">
        <div class="job-top">
          <div>
            <b>${escapeHtml(scopeLabel(job))}</b>
            <span class="job-date">${escapeHtml(formatDate(job.created_at))}</span>
          </div>
          <span class="status-pill status-${statusClass}">${escapeHtml(job.status || '')}</span>
        </div>
        <div class="progress"><span style="width:${Math.max(0,Math.min(100,progress))}%"></span></div>
        <div class="job-meta"><span>${progress}%</span><span>${escapeHtml(job.stage || '')}</span></div>
        <p class="job-message">${escapeHtml(job.message || '')}</p>
        ${summaryHtml}
        ${recentHtml}
        ${optionHtml}
        ${draftHtml}
        ${evidenceHtml}
        ${provisionalHtml}
        ${auditHtml}
        ${workerHelp}
        ${actions}
        ${error}
      </article>
    `;
  }).join('');
}

function qualifiedOptions(job) {
  const options = job?.result_json?.package?.options;
  return Array.isArray(options) ? options : [];
}

function scopeLabel(job) {
  const specialty = job.specialty === 'ALL' ? 'All specialties' : job.specialty;
  const question = job.question_type === 'ALL'
    ? 'All question types'
    : String(job.question_type || '').replaceAll('_', ' ');
  return `${specialty} · ${question}`;
}

function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

async function cancelJob(jobId) {
  const job = jobs.find(item => item.id === jobId);
  if (!job || !['QUEUED', 'RUNNING'].includes(job.status)) return;
  if (!window.confirm('Cancel this discovery job? Its progress and unfinished results will not be saved.')) return;

  const cancelButton = Array.from(els.jobs.querySelectorAll('[data-cancel-job]'))
    .find(button => button.dataset.cancelJob === jobId);
  if (cancelButton) cancelButton.disabled = true;
  try {
    const { data, error } = await supabase.rpc('scimed_cancel_job', { p_job_id: jobId });
    if (error) throw error;
    await loadJobs();
    backendState(
      'ok',
      data ? 'Discovery cancelled' : 'Job already stopped',
      data
        ? 'The worker will stop at its next safe checkpoint.'
        : 'The job was already completed, cancelled, or is no longer accessible.'
    );
  } catch (error) {
    backendState('error', 'Could not cancel discovery', error.message || String(error));
    if (cancelButton) cancelButton.disabled = false;
  }
}

function reportPayload(job) {
  const pkg = job?.result_json?.package || {};
  if (Array.isArray(pkg.options) && pkg.options.length) return pkg;
  return {
    report_type: 'SCIMED_DISCOVERY_DIAGNOSTIC',
    job_id: job.id,
    status: job.status,
    specialty: job.specialty,
    question_type: job.question_type,
    summary: job?.result_json?.run_summary || {},
    checkpoint: job?.result_json?.checkpoint || null,
    error_excerpt: (job.error_text || '').slice(-700),
    selection_policy: pkg.selection_policy || {},
    provisional_options: Array.isArray(pkg.provisional_options) ? pkg.provisional_options : [],
    explanation: 'No candidate cleared all mandatory checks. PROVISIONAL_BACKUP does not mean confirmed lack of novelty.',
    missing_detail: Array.isArray(job?.result_json?.run_summary?.candidate_audits)
      ? null
      : 'Older job did not preserve topic-level source audit or candidate titles.'
  };
}

async function copyJob(jobId) {
  const job = jobs.find(item => item.id === jobId);
  if (!job) return;
  await navigator.clipboard.writeText(JSON.stringify(reportPayload(job), null, 2));
  backendState('ok', 'Copied', 'The discovery report is ready to paste into ChatGPT.');
}

function downloadJob(jobId) {
  const job = jobs.find(item => item.id === jobId);
  if (!job) return;
  const payload = reportPayload(job);
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${jobId}_discovery_report.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

els.start.addEventListener('click', startDiscovery);
els.refresh.addEventListener('click', async () => {
  try {
    await loadJobs();
  } catch (error) {
    backendState('error', 'Could not refresh jobs', error.message || String(error));
  }
});
els.jobs.addEventListener('click', event => {
  const wake = event.target.closest('[data-wake-job]');
  if (wake) {
    wakeWorker(wake.dataset.wakeJob);
    return;
  }
  const cancel = event.target.closest('[data-cancel-job]');
  if (cancel) {
    cancelJob(cancel.dataset.cancelJob);
    return;
  }
  const copy = event.target.closest('[data-copy-job]');
  if (copy) copyJob(copy.dataset.copyJob);
  const download = event.target.closest('[data-download-job]');
  if (download) downloadJob(download.dataset.downloadJob);
});
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    loadJobs().catch(error => backendState('error', 'Could not refresh jobs', error.message || String(error)));
  }
});
window.addEventListener('beforeunload', () => {
  if (pollTimer) clearInterval(pollTimer);
});

init();
