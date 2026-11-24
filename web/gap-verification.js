/* Research Gap Verification: source-linked manual adjudication, local-only.
 * No inferred review eligibility, no server mutation, and no automatic GO.
 */
(function () {
  'use strict';
  const PREFIX = 'scimed-gap-verification-v1:';
  let cloudEvents = []; // Browser-scoped rows fetched through Supabase RLS.
  const ALLOWED = new Set([
    'UNREVIEWED', 'NEEDS_FULL_TEXT', 'POTENTIAL_OVERLAP',
    'DOCUMENTED_OVERLAP', 'DOCUMENTED_NON_OVERLAP',
  ]);
  const LABELS = {
    UNREVIEWED: 'Not yet assessed',
    NEEDS_FULL_TEXT: 'Full text / protocol needed',
    POTENTIAL_OVERLAP: 'Potential PICO overlap, unconfirmed',
    DOCUMENTED_OVERLAP: 'Overlap documented manually',
    DOCUMENTED_NON_OVERLAP: 'Non-overlap documented manually',
  };
  const COMMON = new Set('a an and for from in into of on or patient patients adult adults the with without study studies review systematic meta analysis effect effects outcomes clinical treatment therapy comparison evaluation'.split(' '));

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g,
      char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  }
  function tokens(value) {
    return new Set((String(Array.isArray(value) ? value.join(' ') : value || '')
      .toLowerCase().match(/[a-z0-9]+/g) || [])
      .filter(x => x.length > 2 && !COMMON.has(x)));
  }
  function overlap(words, text) {
    if (!words.size) return 0;
    const found = tokens(text);
    return [...words].filter(x => found.has(x)).length / words.size;
  }
  function recordKey(record) {
    const raw = String(record.doi || record.record_id || record.url || record.title || '').trim().toLowerCase();
    return (record.kind || 'review') + '|' + raw;
  }
  function normalizedRecord(record, kind, audited) {
    return {
      kind,
      title: String(record.title || 'Untitled bibliographic record'),
      source: String(record.source || 'Unknown'),
      record_id: String(record.record_id || ''),
      url: String(record.url || ''),
      doi: String(record.doi || ''),
      year: record.year ?? null,
      last_search_date_if_documented: String(record.last_search_date_if_documented || ''),
      overlap_assessment: record.overlap_assessment || null,
      source_status: audited ? 'PREVIOUS_SEMANTIC_CUE' : 'UNASSESSED_BIBLIOGRAPHIC_LEAD',
    };
  }
  function qOf(topic) {
    return topic?.research_dossier?.scientific_question || topic || {};
  }
  function evidenceOf(topic) {
    const dossier = topic?.research_dossier || {};
    const screening = dossier.verification_and_quality?.competing_review_screening || {};
    const records = new Map();
    const add = (input, kind, audited) => {
      for (const raw of Array.isArray(input) ? input : []) {
        if (!raw || typeof raw !== 'object') continue;
        const record = normalizedRecord(raw, kind, audited);
        const key = recordKey(record);
        const prior = records.get(key);
        // Keep the richer full dossier entry if the backlog repeats it.
        if (!prior || (audited && prior.source_status !== 'PREVIOUS_SEMANTIC_CUE')) {
          records.set(key, record);
        }
      }
    };
    add(dossier.published_review_evidence || topic?.published_review_examples, 'review', true);
    add(dossier.registration_evidence || topic?.registration_examples, 'registration', true);
    add(screening.unassessed_review_queue, 'review', false);
    add(screening.unassessed_registration_queue, 'registration', false);
    const q = qOf(topic);
    const concepts = [
      [0.50, tokens(q.intervention_exposure_index_test)],
      [0.25, tokens(q.population)],
      [0.15, tokens(q.comparator_reference)],
      [0.10, tokens(q.outcomes)],
    ];
    const result = [...records.values()].map(record => {
      const words = [record.title, record.source_abstract_excerpt].filter(Boolean).join(' ');
      const relevance = concepts.reduce((score, item) => score + item[0] * overlap(item[1], words), 0);
      const documented = record.overlap_assessment?.overall_overlap;
      return {
        ...record,
        key: recordKey(record),
        // Used strictly for ordering; not a clinical overlap probability.
        priority: relevance + (['HIGH', 'ESSENTIALLY_IDENTICAL'].includes(documented) ? 0.12 : 0),
      };
    }).sort((a,b) => b.priority - a.priority || a.title.localeCompare(b.title));
    return result;
  }

  function storageKey(job, topic) {
    return PREFIX + String(job?.id || '') + ':' + String(topic?.candidate_id || '');
  }
  function readLocal(job, topic) {
    try {
      const data = JSON.parse(localStorage.getItem(storageKey(job, topic)) || '{}');
      return {
        decisions: data && typeof data.decisions === 'object' && !Array.isArray(data.decisions)
          ? data.decisions : {},
        history: Array.isArray(data?.history) ? data.history : [],
      };
    } catch {
      return {decisions: {}, history: []};
    }
  }
  function setCloudEvents(rows) {
    cloudEvents = Array.isArray(rows) ? rows.filter(item =>
      item && typeof item.job_id === 'string' && typeof item.candidate_id === 'string'
    ).map(item => ({...item})) : [];
  }
  function cloudAsEvent(row) {
    return {
      id: row.id,
      record_key: row.record_key,
      record_type: row.record_type,
      title_at_adjudication: row.title_at_adjudication,
      source: row.source,
      decision: row.decision,
      evidence_url: row.evidence_url,
      documented_last_search_date: row.documented_last_search_date,
      rationale: row.rationale,
      reviewer: 'Possessor of this browser device token (not an authenticated identity)',
      recorded_at_utc: row.created_at,
      cloud_synced: true,
      scope: 'USER_DOCUMENTED_CLOUD_FINDING_NO_AUTOMATIC_CLEARANCE',
    };
  }
  function read(job, topic) {
    const local = readLocal(job, topic);
    const remote = cloudEvents.filter(item =>
      item.job_id === job?.id && item.candidate_id === topic?.candidate_id
    ).map(cloudAsEvent);
    const deduped = new Map();
    for (const item of [...remote, ...local.history]) {
      const key = item.id || [
        item.record_key, item.recorded_at_utc, item.decision, item.evidence_url,
      ].join('|');
      // A locally synced copy with the same id is the same source finding.
      const existing = deduped.get(key);
      if (!existing || (!existing.cloud_synced && item.cloud_synced)) deduped.set(key, item);
    }
    const history = [...deduped.values()].sort((a,b) =>
      String(a.recorded_at_utc || '').localeCompare(String(b.recorded_at_utc || ''))
      || String(a.id || '').localeCompare(String(b.id || ''))
    );
    const decisions = {};
    for (const item of history) if (item.record_key) decisions[item.record_key] = item;
    return {decisions, history};
  }
  function assignPendingIds(job, topic) {
    const local = readLocal(job, topic);
    let changed = false;
    for (const item of local.history) {
      if (!item.id) {
        item.id = crypto.randomUUID();
        changed = true;
      }
    }
    if (changed) {
      localStorage.setItem(storageKey(job, topic), JSON.stringify(local));
    }
    return local.history.filter(item => !item.cloud_synced);
  }
  function markCloudSynced(job, topic, eventId) {
    const data = readLocal(job, topic);
    for (const event of data.history) {
      if (event.id === eventId) event.cloud_synced = true;
    }
    localStorage.setItem(storageKey(job, topic), JSON.stringify(data));
  }
  function validEvidenceUrl(value) {
    try {
      const u = new URL(String(value || ''));
      return u.protocol === 'https:' && Boolean(u.hostname) &&
        !u.username && !u.password && u.href.length < 1500;
    } catch {
      return false;
    }
  }
  function saveDecision(job, topic, record, fields) {
    if (!record || !record.key) return {ok:false, error:'Source record not found.'};
    const decision = String(fields?.decision || '');
    const rationale = String(fields?.rationale || '').trim();
    const evidenceUrl = String(fields?.evidence_url || '').trim();
    const searchDate = String(fields?.search_date || '').trim();
    if (!ALLOWED.has(decision) || decision === 'UNREVIEWED') {
      return {ok:false, error:'Select a manual verification status.'};
    }
    if (rationale.length < 15 || rationale.length > 1800) {
      return {ok:false, error:'Explain the evidence in 15–1800 characters.'};
    }
    if (!validEvidenceUrl(evidenceUrl)) {
      return {ok:false, error:'Provide an HTTPS source URL supporting your decision.'};
    }
    if (searchDate && (record.kind !== 'review' ||
        !/^\d{4}-\d{2}-\d{2}$/.test(searchDate) ||
        Number.isNaN(Date.parse(searchDate)) || searchDate > new Date().toISOString().slice(0,10))) {
      return {ok:false, error:'The review search date must be a documented past YYYY-MM-DD date.'};
    }
    const data = readLocal(job, topic);
    const stamped = {
      id: crypto.randomUUID(),
      cloud_synced: false,
      record_key: record.key,
      record_type: record.kind,
      title_at_adjudication: record.title,
      source: record.source,
      decision,
      evidence_url: evidenceUrl,
      documented_last_search_date: searchDate || null,
      rationale,
      reviewer: 'User of this browser (identity not authenticated)',
      recorded_at_utc: new Date().toISOString(),
      scope: 'MANUAL_LOCAL_REVIEW_ONLY_NO_AUTOMATIC_CLEARANCE',
    };
    data.decisions[record.key] = stamped;
    data.history.push(stamped);
    try {
      localStorage.setItem(storageKey(job, topic), JSON.stringify(data));
    } catch {
      return {ok:false, error:'Browser storage unavailable. Export existing records or free storage; nothing was saved.'};
    }
    return {ok:true, data:stamped};
  }

  function href(record) {
    const uri = String(record.url || record.doi && 'https://doi.org/' + record.doi || '');
    if (!validEvidenceUrl(uri)) return esc(record.title);
    try {
      const u = new URL(uri);
      const good = [
        'pubmed.ncbi.nlm.nih.gov','europepmc.org','www.ebi.ac.uk',
        'doi.org','www.crd.york.ac.uk','osf.io','openalex.org',
        'www.semanticscholar.org','clinicaltrials.gov','www.crossref.org',
      ].includes(u.hostname);
      return good ? '<a href="' + esc(u.href) + '" rel="noopener noreferrer" target="_blank">' +
        esc(record.title) + '</a>' : esc(record.title);
    } catch {
      return esc(record.title);
    }
  }
  function render(job, topic) {
    if (!topic?.candidate_id || !job?.id) return '';
    const records = evidenceOf(topic);
    const saved = read(job, topic);
    const q = qOf(topic);
    const dossier = topic.research_dossier || {};
    const quality = dossier.verification_and_quality || {};
    const check = quality.competing_review_screening || {};
    const sources = quality.source_statuses || topic.coverage?.source_statuses || {};
    const pending = quality.pending_verifications || topic.unresolved_checks || [];
    const sourceIssues = Object.entries(sources).filter(([,v]) =>
      ['PARTIAL', 'ACCESS_FAILED', 'NOT_SEARCHED'].includes(v));
    const decisions = Object.keys(saved.decisions).length;
    const itemsHtml = (kind, label) => {
      const items = records.filter(x => x.kind === kind);
      const shown = items.slice(0, 14);
      return '<details class="gap-queue"><summary>' + esc(label) + ' (' + items.length +
        ' records; ' + Math.max(0, items.length - shown.length) + ' more in export)</summary>' +
        '<p class="help">Ordered by PICO-term matches in citations, not proven overlap. Every record remains scientifically unresolved until independently checked.</p>' +
        shown.map(record => {
          const index = records.indexOf(record);
          const prior = saved.decisions[record.key] || {};
          const opts = Object.entries(LABELS).map(([value,title]) =>
            '<option value="' + esc(value) + '"' +
            ((prior.decision || 'UNREVIEWED') === value ? ' selected' : '') +
            '>' + esc(title) + '</option>').join('');
          return '<details class="gap-record" data-gap-record="' + index + '">' +
            '<summary>' + esc(record.title) +
            (prior.decision ? ' | ' + esc(LABELS[prior.decision] || prior.decision) : '') + '</summary>' +
            '<p>' + href(record) + '</p>' +
            '<p class="help">' + esc(record.source) +
            (record.year ? ' · ' + esc(record.year) : '') +
            ' · ' + esc(record.source_status) +
            ' · Citation relevance rank only</p>' +
            (record.last_search_date_if_documented ?
              '<p class="help">Previously captured review search date: ' +
              esc(record.last_search_date_if_documented) + ' (recheck full text)</p>' : '') +
            '<label>Manual finding<select data-gap-field="decision">' + opts + '</select></label>' +
            '<label>Evidence URL (required)<input data-gap-field="evidence_url" type="url" inputmode="url" maxlength="1400" placeholder="https://..." value="' +
              esc(prior.evidence_url || '') + '"></label>' +
            (kind === 'review' ? '<label>Actual last search date, if documented (optional)<input data-gap-field="search_date" type="date" value="' +
              esc(prior.documented_last_search_date || '') + '"></label>' : '') +
            '<label>Source-backed reasoning (required)<textarea data-gap-field="rationale" maxlength="1800" rows="3" placeholder="Explain where the source confirms PICO overlap, review type, or outstanding uncertainty.">' +
              esc(prior.rationale || '') + '</textarea></label>' +
            '<button type="button" class="secondary small" data-gap-save="' + index + '" data-gap-job="' +
              esc(job.id) + '" data-gap-topic="' + esc(topic.candidate_id) +
              '">Save manual evidence record</button><p class="gap-message" aria-live="polite"></p>' +
          '</details>';
        }).join('') + '</details>';
    };
    return '<details class="gap-review" data-gap-key="' + esc(job.id + ':' + topic.candidate_id) + '">' +
      '<summary>Research Gap Verification · ' + decisions + ' saved manual finding(s)</summary>' +
      '<p class="help">Evidence review workbench. This never changes a source status, scientific gate or QUALIFIED decision automatically.</p>' +
      '<p class="help">Notes are saved locally first and synchronized with your private Supabase job when connected. The browser device token controls access, not an authenticated account. Export JSON backups; sharing across a different device is not available yet.</p>' +
      '<p><b>Question:</b> ' + esc(q.review_question || topic.title) + '</p>' +
      '<div class="gap-counts"><span>Reviews: ' + esc(check.published_review_records_discovered ?? 'unknown') + '</span>' +
      '<span>Review backlog: ' + esc(check.unassessed_published_review_count ?? 'unknown') + '</span>' +
      '<span>Registrations: ' + esc(check.registration_records_discovered ?? 'unknown') + '</span>' +
      '<span>Registry backlog: ' + esc(check.unassessed_registration_count ?? 'unknown') + '</span></div>' +
      '<p class="help">Unresolved source checks: ' + esc(sourceIssues.map(([source,s]) => source + ': ' + s).join('; ') || 'None flagged in the saved report') + '</p>' +
      '<details class="gap-queue"><summary>Scientific blockers (' + esc(pending.length) + ')</summary>' +
      pending.map(x => '<p>' + esc(x) + '</p>').join('') +
      (!pending.length ? '<p>None recorded in this export. This is not proof of eligibility.</p>' : '') + '</details>' +
      itemsHtml('review','Competing published reviews') +
      itemsHtml('registration','PROSPERO and OSF registrations') +
      '<p class="help">Review dates, true PICO overlap, trial-family independence and extractable outcomes require documented verification. Marking a citation here does not resolve full search coverage or qualify a topic.</p>' +
      '<button type="button" class="secondary small" data-gap-reassess="' + esc(job.id) +
      '" data-gap-topic="' + esc(topic.candidate_id) + '">Re-evaluate saved evidence (no new searches)</button>' +
      '<button type="button" class="secondary small" data-gap-export="' + esc(job.id) +
      '" data-gap-topic="' + esc(topic.candidate_id) + '">Export verification ledger (.json)</button>' +
      '<div class="gap-reassessment" aria-live="polite"></div>' +
      '</details>';
  }
  function reassess(job, topic) {
    // Deliberately a cached diagnostic, never a scientific or registry gate.
    const records = evidenceOf(topic);
    const latest = read(job, topic).decisions;
    const quality = topic?.research_dossier?.verification_and_quality || {};
    const sources = quality.source_statuses || topic.source_statuses || {};
    const screening = quality.competing_review_screening || {};
    const sourceIssues = Object.entries(sources)
      .filter(([,status]) => ['PARTIAL','ACCESS_FAILED','NOT_SEARCHED','UNKNOWN'].includes(status))
      .map(([source,status]) => ({source,status}));
    if (!Object.keys(sources).length) {
      sourceIssues.push({source:'Saved source audit',status:'UNKNOWN'});
    }
    const sourceBlockers = Array.isArray(quality.source_blockers)
      ? quality.source_blockers : [];
    const declaredReviewCount = screening.published_review_records_discovered == null
      ? NaN : Number(screening.published_review_records_discovered);
    const declaredRegistrationCount = screening.registration_records_discovered == null
      ? NaN : Number(screening.registration_records_discovered);
    const discovered = {
      review: records.filter(row => row.kind === 'review').length,
      registration: records.filter(row => row.kind === 'registration').length,
    };
    const expected = {
      review: Number.isFinite(declaredReviewCount) && declaredReviewCount >= 0
        ? Math.max(discovered.review,declaredReviewCount) : null,
      registration: Number.isFinite(declaredRegistrationCount) && declaredRegistrationCount >= 0
        ? Math.max(discovered.registration,declaredRegistrationCount) : null,
    };
    // Source-confirmed similarity and primary-study eligibility cannot be
    // reconstructed from user's standalone judgments.
    const closed = records.filter(row =>
      ['DOCUMENTED_OVERLAP','DOCUMENTED_NON_OVERLAP'].includes(latest[row.key]?.decision)
    );
    const unresolvedRows = records.filter(row =>
      !['DOCUMENTED_OVERLAP','DOCUMENTED_NON_OVERLAP'].includes(latest[row.key]?.decision)
    );
    const unresolved = {
      review: expected.review === null ? null
        : Math.max(0,expected.review - closed.filter(row=>row.kind === 'review').length),
      registration: expected.registration === null ? null
        : Math.max(0,expected.registration - closed.filter(row=>row.kind === 'registration').length),
    };
    const unresolvedCountKnown = unresolved.review !== null && unresolved.registration !== null;
    const overlappingReviewWithoutSearchDate = closed.some(row =>
      row.kind === 'review'
      && latest[row.key]?.decision === 'DOCUMENTED_OVERLAP'
      && !latest[row.key]?.documented_last_search_date
    );
    const status = sourceIssues.length || sourceBlockers.length
      ? 'SOURCE_COVERAGE_INCOMPLETE'
      : !unresolvedCountKnown || unresolved.review > 0 || unresolved.registration > 0
        || !!screening.queue_truncated || overlappingReviewWithoutSearchDate
        ? 'COMPETITOR_SCREENING_INCOMPLETE'
        : 'READY_FOR_INDEPENDENT_STUDY_AUDIT_NOT_QUALIFIED';
    return {
      schema:'SCIMED_GAP_CACHED_REASSESSMENT_V1',
      evaluated_at_utc:new Date().toISOString(),
      job_id:String(job?.id||''),
      candidate_id:String(topic?.candidate_id||''),
      status,
      source_issues:sourceIssues,
      original_source_blockers_preserved:sourceBlockers,
      overlapping_review_missing_search_date:overlappingReviewWithoutSearchDate,
      records_in_export:discovered,
      original_discovered_records:expected,
      manually_closed_citations:closed.length,
      unresolved_citations:unresolved,
      unresolved_citations_in_export:unresolvedRows.length,
      queue_truncated:!!screening.queue_truncated,
      full_text_eligible_independent_studies:'NOT_VERIFIED',
      extractable_outcomes:'NOT_VERIFIED',
      search_queries_reexecuted:false,
      scientific_qualification_changed:false,
      original_qualification_status:topic?.research_dossier?.qualification_label ||
        topic?.qualification_status || 'UNRESOLVED',
      qualification_decision:'UNRESOLVED_PENDING_INDEPENDENT_VERIFICATION',
      note:'Manual source-link records do not replace full registry coverage, original review text, study-family checks or a methods audit.',
    };
  }
  function reassessmentHtml(result) {
    const labels = {
      SOURCE_COVERAGE_INCOMPLETE:'Incomplete registry/database coverage',
      COMPETITOR_SCREENING_INCOMPLETE:'Competing review/protocol screening incomplete',
      READY_FOR_INDEPENDENT_STUDY_AUDIT_NOT_QUALIFIED:'Competitors documented; independent study audit still required',
    };
    const remaining = result.unresolved_citations;
    return '<article class="gap-result"><b>Cached verification: ' + esc(labels[result.status]) +
      '</b><p>Missing/partial sources: ' + esc(result.source_issues.map(x=>x.source+' ('+x.status+')').join(', ') || 'none flagged') +
      '</p><p>Unresolved review citations: ' + esc(remaining.review ?? 'unknown') +
      '; unresolved registrations: ' + esc(remaining.registration ?? 'unknown') +
      '.</p><p>Original source blockers: ' + esc(result.original_source_blockers_preserved.length) +
      '. Human citation notes never clear incomplete automated search coverage.</p>' +
      '<p>Full-text eligibility, independent populations and extractable outcomes: NOT VERIFIED.</p>' +
      '<p>No new source queries were run. Original scientific qualification was not changed.</p></article>';
  }
  function exportLedger(job, topic) {
    const dossier = topic?.research_dossier || {};
    const saved = read(job, topic);
    return {
      schema: 'SCIMED_RESEARCH_GAP_VERIFICATION_V1',
      created_utc: new Date().toISOString(),
      job_id: String(job?.id || ''),
      candidate_id: String(topic?.candidate_id || ''),
      title: String(topic?.title || ''),
      original_status: String(topic?.qualification_status || dossier.qualification_label || 'UNRESOLVED'),
      qualification_automatically_modified: false,
      manual_review_does_not_override_gates: true,
      browser_local_storage_only: false,
      cloud_sync_scope: 'DEVICE_TOKEN_SCOPED; LOCAL_OFFLINE_NOTES_MAY_REMAIN_UNSYNCED',
      scientific_question: qOf(topic),
      saved_source_statuses: dossier.verification_and_quality?.source_statuses || {},
      unresolved_scientific_checks: dossier.verification_and_quality?.pending_verifications ||
        topic.unresolved_checks || [],
      competing_review_counts: dossier.verification_and_quality?.competing_review_screening || {},
      source_search_audit: dossier.evidence_search_audit || [],
      bibliographic_candidates_ordered_for_manual_review: evidenceOf(topic),
      manual_decisions_latest: saved.decisions,
      append_only_local_adjudication_history: saved.history,
      history_is_not_cryptographically_immutable_or_authenticated: true,
      cached_reassessment: reassess(job,topic),
      required_next_actions: dossier.next_actions || [
        'Resolve incomplete database and registry searches with provenance.',
        'Verify published-review PICO overlap and actual last literature search dates.',
        'Verify independent eligible original studies and extractable outcomes.',
        'Make a separately documented protocol GO / REFINE / NO-GO decision.',
      ],
    };
  }
  window.SCIMED_GAP = {
    render, evidenceOf, read, saveDecision, exportLedger, reassess,
    reassessmentHtml, setCloudEvents, assignPendingIds, markCloudSynced,
    recordKey, validEvidenceUrl,
  };
})();
