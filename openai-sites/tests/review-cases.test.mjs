import test from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';import {runCases} from '../scripts/run-review-cases.mjs';
test('five positive and three negative cases execute against the actual hosted catalog',async()=>{
 const cases=JSON.parse(readFileSync('reviewer-cases.json','utf8'));assert.equal(cases.positive_cases.length,5);assert.equal(cases.negative_cases.length,3);const observed=await runCases();assert.equal(observed.results.length,8);
 for(const item of observed.results)assert.equal(item.passed,true,item.id);for(const definition of cases.positive_cases)for(const tool of definition.tools)assert.ok(observed.catalog.some(t=>t.name===tool),tool);
});
