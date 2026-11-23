import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync('web/app.js', 'utf8');
const start = source.indexOf('const LEGACY_CHATGPT_TOPIC_PROMPT =');
const end = source.indexOf('async function copyJob(', start);
assert.ok(start >= 0 && end > start, 'Portable topic transfer helpers must exist');
const { findTransferTopic, topicTransferText, topicFileName } = runInNewContext(
  source.slice(start, end) + '\n({ findTransferTopic, topicTransferText, topicFileName });',
  {}
);

const verified = {
  candidate_id: 'TOPIC-ONE',
  title: 'Ketone monoester during endurance exercise',
  research_dossier: {
    candidate_id: 'TOPIC-ONE',
    title: 'Ketone monoester during endurance exercise',
    qualification_label: 'PROVISIONAL_NEEDS_VERIFICATION',
    scientific_question: {
      population: 'Endurance athletes',
      intervention_exposure_index_test: 'Ketone monoester',
      comparator_reference: 'Placebo',
      outcomes: ['Troponin I']
    },
    evidence_search_audit: [{
      database: 'PROSPERO', status: 'PARTIAL',
      query_used: 'ketone monoester athletes'
    }],
    published_review_evidence: [{
      title: 'Old competing review', doi: '10.1234/old', year: 2019
    }],
    eligible_independent_studies_confirmed: null,
  }
};

test('A single provisional idea exports its complete dossier and ChatGPT prompt', () => {
  const job = {
    id: 'JOB-1',
    result_json: {
      package: {
        options: [], provisional_options: [verified],
        topic_review_prompt: 'Audit PICO, PROSPERO and OSF. Output GO or UNRESOLVED.'
      },
      run_summary: { candidate_audits: [] }
    }
  };
  const topic = findTransferTopic(job, 'TOPIC-ONE');
  assert.equal(topic.candidate_id, 'TOPIC-ONE');
  const content = topicTransferText(job, topic);
  assert.ok(content.includes('\n## Instructions for ChatGPT\n'));
  assert.ok(content.includes('Output GO or UNRESOLVED'));
  assert.ok(content.includes('10.1234/old'));
  assert.ok(content.includes('PROSPERO'));
  assert.ok(content.includes('PARTIAL'));
  assert.ok(content.includes('PROVISIONAL_NEEDS_VERIFICATION'));
  assert.ok(content.includes('\n```json\n'));
  assert.ok(content.includes('\n```\n'));
});

test('A pre-upgrade completed job exports available detail and explicitly notes what is missing', () => {
  const topic = {
    candidate_id: 'OLD-1',
    title: 'Existing clinical idea',
    population: 'Adult patients',
    source_blockers: ['OSF was unavailable'],
    provisional_only: true
  };
  const job = {
    id: 'OLD-JOB',
    result_json: {
      package: { options: [], provisional_options: [topic] },
      run_summary: { candidate_audits: [{candidate_id: 'OLD-1', status: 'PROVISIONAL_BACKUP'}] }
    }
  };
  const content = topicTransferText(job, findTransferTopic(job, 'OLD-1'));
  assert.ok(content.includes('historical_export_limitation'));
  assert.ok(content.includes('OSF was unavailable'));
  assert.ok(content.includes('Never invent DOIs'));
  assert.ok(content.includes('PROVISIONAL'));
});

test('An interrupted job also exposes its saved draft in the topic transfer', () => {
  const draft = {
    candidate_id: 'DRAFT1', title: 'Draft safety review',
    review_question: 'Does new intervention cause harm?',
    qualification_status: 'AI_DRAFT_NOT_SOURCE_VERIFIED'
  };
  const job = {
    id: 'INTERRUPTED',
    result_json: { checkpoint: { candidates: [draft] }, package: {} }
  };
  assert.equal(findTransferTopic(job, 'DRAFT1').title, 'Draft safety review');
  assert.ok(topicTransferText(job, draft).includes('AI_DRAFT_NOT_SOURCE_VERIFIED'));
});

test('Topic download filename excludes dangerous characters', () => {
  const filename = topicFileName({
    title: '../Invalid: <file> / name?',
    candidate_id: 'abc/def'
  });
  assert.ok(filename.endsWith('.md'));
  assert.ok(!filename.includes('/'));
  assert.ok(!filename.includes('<'));
  assert.ok(filename.startsWith('SciMed_'));
});
