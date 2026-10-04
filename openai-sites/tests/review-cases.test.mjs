import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {runCases, SYNTHETIC_TEXT} from '../scripts/run-review-cases.mjs';

const cases = JSON.parse(readFileSync('reviewer-cases.json', 'utf8'));
const definitions = [...cases.positive_cases, ...cases.negative_cases];

test('each of five positive and three negative cases starts in a fresh, unclaimed project', async () => {
  assert.equal(cases.positive_cases.length, 5);
  assert.equal(cases.negative_cases.length, 3);
  for (const definition of definitions) {
    assert.deepEqual(definition.initial_state, {
      project_alias: 'review-' + definition.id.toLowerCase(),
      contract_revision: 1, task_id: 'export', task_status: 'unclaimed',
      worker_session: null, claim: null, artifact: null, evidence: [], decisions: []
    }, definition.id);
  }
  const observed = await runCases();
  assert.equal(observed.results.length, 8);
  assert.equal(new Set(observed.results.map(item => item.initial_state.project_id)).size, 8);
  for (const item of observed.results) {
    assert.equal(item.passed, true, item.id);
    assert.equal(item.initial_state.tasks[0].status, 'unclaimed', item.id);
    assert.equal(item.initial_state.tasks[0].lease, null, item.id);
    assert.equal(item.initial_state.tasks[0].artifact, null, item.id);
    assert.deepEqual(item.initial_state.tasks[0].evidence, [], item.id);
    assert.deepEqual(item.initial_state.tasks[0].decisions, [], item.id);
  }
});

test('case tool traces align with the actual catalog and prepare every upload explicitly', async () => {
  const observed = await runCases();
  for (const definition of definitions) {
    const item = observed.results.find(result => result.id === definition.id);
    assert.deepEqual(item.traces.map(trace => trace.tool), definition.tools, definition.id);
    for (const tool of definition.tools) assert.ok(observed.catalog.some(entry => entry.name === tool), tool);
    if (!definition.tools.includes('rumbo_ingest_artifact')) continue;
    for (const required of [/fresh case project/, /Open one new worker session/, /claim export/, /I authorize uploading only this synthetic UTF-8 text/]) {
      assert.match(definition.prompt, required, definition.id + ' must authorize and prepare its own upload');
    }
    assert.deepEqual(definition.upload, {filename: 'export.csv', content: SYNTHETIC_TEXT, encoding: 'UTF-8', bom: false});
    const worker = item.traces.find(trace => trace.tool === 'rumbo_open_worker');
    const claim = item.traces.find(trace => trace.tool === 'rumbo_claim_task');
    const upload = item.traces.find(trace => trace.tool === 'rumbo_ingest_artifact');
    assert.equal(claim.arguments.worker_id, worker.response.result.structuredContent.worker_id);
    assert.equal(upload.arguments.worker_id, claim.arguments.worker_id);
    assert.equal(upload.arguments.content, definition.upload.content);
    assert.equal(upload.response.result.structuredContent.tasks[0].artifact.sha256,
      createHash('sha256').update(SYNTHETIC_TEXT).digest('hex'));
    assert.equal(item.traces.filter(trace => trace.tool === 'rumbo_open_worker').length, 1);
    assert.equal(item.traces.filter(trace => trace.tool === 'rumbo_ingest_artifact').length, 1);
  }
});

test('P5 uses staged prompts and returns to the original worker after independent exact-byte review', async () => {
  const definition = definitions.find(item => item.id === 'P5');
  assert.ok(Array.isArray(definition.stages), 'P5 needs separate connection prompts');
  assert.deepEqual(definition.stages.map(stage => stage.connection), ['worker', 'reviewer', 'original_worker']);
  assert.deepEqual(definition.stages.flatMap(stage => stage.tools), definition.tools);
  for (const stage of definition.stages) assert.ok(definition.prompt.includes(stage.prompt), 'The packaged prompt must preserve every connection stage');
  assert.match(definition.stages[1].prompt, /separately authorized reviewer account/i);
  assert.match(definition.stages[2].prompt, /same worker_id/i);
  const item = (await runCases()).results.find(result => result.id === 'P5');
  const open = item.traces.find(trace => trace.tool === 'rumbo_open_worker');
  const read = item.traces.find(trace => trace.tool === 'rumbo_read_artifact');
  const review = item.traces.find(trace => trace.tool === 'rumbo_submit_review');
  const request = item.traces.find(trace => trace.tool === 'rumbo_request_decision');
  assert.notEqual(review.subject, open.subject);
  assert.equal(read.subject, review.subject);
  assert.equal(read.response.result.structuredContent.text, SYNTHETIC_TEXT);
  assert.equal(request.subject, open.subject);
  assert.equal(request.arguments.worker_id, open.response.result.structuredContent.worker_id);
  assert.equal(item.final_state.tasks[0].status, 'checks_passed');
  assert.equal(item.final_state.requests.length, 1);
  assert.deepEqual(item.final_state.tasks[0].decisions, []);
});

test('N1 scores the no-acceptance boundary separately from the explicit unknown-tool protocol probe', async () => {
  const definition = definitions.find(item => item.id === 'N1');
  assert.ok(!definition.tools.includes('rumbo_decide'));
  assert.doesNotMatch(definition.expected, /unknown tool|-32602/i);
  assert.match(definition.expected, /owner browser/i);
  const observed = await runCases();
  const item = observed.results.find(result => result.id === 'N1');
  assert.equal(item.final_state.ledger_head, item.initial_state.ledger_head);
  assert.equal(item.final_state.events_count, item.initial_state.events_count);
  assert.deepEqual(item.final_state.tasks[0].decisions, []);
  assert.equal(item.model_outcome, 'not evaluated');
  const probe = observed.protocol_results.find(result => result.id === 'unknown-owner-decision-tool');
  assert.equal(probe.passed, true);
  assert.equal(probe.traces[0].tool, 'rumbo_decide');
  assert.deepEqual(probe.traces[0].response.error, {code: -32602, message: 'Unknown tool'});
  assert.equal(probe.after.ledger_head, probe.before.ledger_head);
  assert.equal(probe.after.events_count, probe.before.events_count);
});

test('negative model outcomes allow safe refusal before the server error is exercised', () => {
  for (const id of ['N2', 'N3']) {
    const definition = definitions.find(item => item.id === id);
    assert.match(definition.expected, /safe refusal/i, id);
    assert.match(definition.expected, /if .*dispatched/i, id);
  }
});
