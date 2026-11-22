import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(()=>{});

const config = window.SCIMED_CONFIG || {};
const els = {
  backend: document.getElementById('backendStatus'),
  start: document.getElementById('start'),
  refresh: document.getElementById('refresh'),
  specialty: document.getElementById('specialty'),
  questionType: document.getElementById('questionType'),
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

  try {
    const { data, error } = await supabase
      .from('discovery_jobs')
      .insert({
        specialty,
        question_type: questionType,
        candidate_count: 12,
        final_options: 3,
        min_verify: 3,
        max_verify: 10,
        limit_per_query: 20,
      })
      .select()
      .single();

    if (error) throw error;
    backendState('ok', 'Discovery queued', 'The background worker will pick up this job. You may close the browser.');
    jobs = [data, ...jobs.filter(job => job.id !== data.id)];
    renderJobs();
    await loadJobs();
  } catch (error) {
    backendState('error', 'Could not queue discovery', error.message || String(error));
  } finally {
    els.start.disabled = false;
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

    const actions = ['QUEUED', 'RUNNING'].includes(job.status)
      ? `<div class="job-actions">
          <button class="secondary small cancel-button" data-cancel-job="${escapeHtml(job.id)}">Cancel job</button>
        </div>`
      : job.status === 'COMPLETED'
        ? `<div class="job-actions">
            <button class="secondary small" data-copy-job="${escapeHtml(job.id)}">Copy for ChatGPT</button>
            <button class="secondary small" data-download-job="${escapeHtml(job.id)}">Download JSON</button>
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
            return `<article class="score-item">
              <b>${escapeHtml(audit.title)}</b>
              <div class="score-data">
                <span>Novelty: ${escapeHtml(score.overall_novelty ?? 'N/A')} / 5</span>
                <span>Information gain proxy: ${escapeHtml(score.new_information_gain ?? 'N/A')} / 5</span>
                <span>Priority index: ${escapeHtml(score.publication_oriented_score ?? 'N/A')} / 100</span>
                <span>Primary-study candidates: ${escapeHtml(audit.unique_primary_study_candidates ?? 'N/A')}</span>
              </div>
              <small>${escapeHtml(trace.information_gain_status || 'Not estimated')}</small>
              ${failed ? `<p>Failed gates: ${failed}</p>` : ''}
              ${pending ? `<p>Unresolved: ${pending}</p>` : ''}
              <details><summary>Methods and score weights</summary>
                <pre>${escapeHtml(JSON.stringify({
                  version: trace.method_version || '',
                  weights: trace.criteria_weights || {},
                  study_date_completeness: trace.primary_date_completeness,
                  score_sensitivity_range: trace.sensitivity_score_range || [],
                  limitations: trace.limitations || []
                }, null, 2))}</pre>
              </details>
            </article>`;
          }).join('')}
        </details>`
      : '';

    const error = job.error_text
      ? `<details class="error-details"><summary>Error details</summary><pre>${escapeHtml(job.error_text)}</pre></details>`
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
        ${optionHtml}
        ${auditHtml}
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

async function copyJob(jobId) {
  const job = jobs.find(item => item.id === jobId);
  const pkg = job?.result_json?.package;
  if (!pkg) return;
  await navigator.clipboard.writeText(JSON.stringify(pkg, null, 2));
  backendState('ok', 'Copied', 'The qualified-topic package is ready to paste into ChatGPT.');
}

function downloadJob(jobId) {
  const job = jobs.find(item => item.id === jobId);
  const pkg = job?.result_json?.package;
  if (!pkg) return;
  const blob = new Blob([JSON.stringify(pkg, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${jobId}_review_topics.json`;
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
