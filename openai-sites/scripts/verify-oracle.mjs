import {readFileSync,existsSync} from 'node:fs';import {createHash} from 'node:crypto';
const vendored=readFileSync('tests/oracle_core.py');
if(existsSync('../rumbo/core.py')&&!vendored.equals(readFileSync('../rumbo/core.py')))throw new Error('Canonical Python engine changed: refresh and review hosted parity before release');
console.log('Canonical Python test oracle SHA-256 '+createHash('sha256').update(vendored).digest('hex'));
