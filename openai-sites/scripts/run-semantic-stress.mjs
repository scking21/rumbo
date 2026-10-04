import assert from 'node:assert/strict';
/** Pure fixtures + canonical local Python; never starts hosted runtimes. */
import {writeFileSync,mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {canonical} from '../worker/codec.js';
import {compare,generate,oracle,actual} from '../tests/semantic-stress-support.mjs';
const options={seeds:64,steps:64,start:0x6d2b79f5,report:'evidence/semantic-stress.json'};
for(let i=2;i<process.argv.length;i+=2){const key=process.argv[i].replace(/^--/,'');if(!Object.hasOwn(options,key))throw Error('Unknown option '+key);options[key]=key==='report'?process.argv[i+1]:Number(process.argv[i+1])}
if(!Number.isInteger(options.seeds)||options.seeds<1||options.seeds>1024||!Number.isInteger(options.steps)||options.steps<0||options.steps>1000)throw Error('Use 1..1024 seeds and 0..1000 random steps');
const report={scope:'Pure in-memory Sites engine + canonical Python subprocesses; no runtime, browser, network, service or credentials',options,seeds:[],scenarios:0,operations:0,actions:{},errors:{},statuses:{},mismatches:[]},start=performance.now();
for(let i=0;i<options.seeds;i++){const seed=(options.start+Math.imul(i,0x9e3779b9))>>>0,scenario=generate(seed,options.steps),result=await compare(scenario.steps);assert.ok(result.results[scenario.acceptedAt].ok?.tasks.every(t=>t.status==='accepted'),'generated initial workflow must complete before randomized disruption');report.seeds.push(seed);report.scenarios++;report.operations+=scenario.steps.length;
 for(const category of ['actions','errors','statuses'])for(const [k,v] of Object.entries(result.counts[category]))report[category][k]=(report[category][k]??0)+v;
 if(result.mismatch>=0){const before=scenario.steps.slice(0,result.mismatch+1);let minimal=before,chunk=Math.ceil(before.length/2);while(chunk>=1){let removed=false;for(let j=0;j<minimal.length;j+=chunk){const candidate=minimal.slice(0,j).concat(minimal.slice(j+chunk));if(!candidate.length)continue;const reduction=await compare(candidate,{invariants:false});if(reduction.mismatch>=0){minimal=candidate.slice(0,reduction.mismatch+1);removed=true;break}}if(!removed)chunk=Math.floor(chunk/2)}
  report.mismatches.push({seed,step:result.mismatch,originalLength:before.length,minimal,actual:(await actual(minimal,{invariants:false})).results,expected:oracle(minimal,true)});console.error('MISMATCH',seed,result.mismatch,'minimal steps',minimal.length);break}
 if((i+1)%16===0)console.log('Verified',i+1,'seeds;',report.operations,'operations');}
report.elapsed_seconds=Number(((performance.now()-start)/1000).toFixed(3));report.passed=!report.mismatches.length;mkdirSync(dirname(options.report),{recursive:true});writeFileSync(options.report,canonical(report)+'\n');console.log(JSON.stringify({report:options.report,scenarios:report.scenarios,operations:report.operations,passed:report.passed,seconds:report.elapsed_seconds,actions:report.actions,errors:report.errors}));if(!report.passed)process.exitCode=1;
