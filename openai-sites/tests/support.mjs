import {DatabaseSync} from 'node:sqlite';
import {readFileSync,readdirSync} from 'node:fs';
import {Storage} from '../worker/storage.js';
class D1 {
 constructor(db){this.db=db;}
 prepare(sql){const db=this.db;let args=[];return {bind(...values){args=values;return this;},async all(){return {results:db.prepare(sql).all(...args)};},async first(){return db.prepare(sql).get(...args)??null;},async run(){const result=db.prepare(sql).run(...args);return {success:true,meta:{changes:Number(result.changes)}};}};}
 async batch(statements){this.db.exec('BEGIN IMMEDIATE');try{const out=[];for(const s of statements)out.push(await s.run());this.db.exec('COMMIT');return out;}catch(e){this.db.exec('ROLLBACK');throw e;}}
}
export function fixture(){
 const db=new DatabaseSync(':memory:');for(const name of readdirSync('drizzle').filter(n=>/^\d+.*\.sql$/.test(n)).sort())db.exec(readFileSync('drizzle/'+name,'utf8'));const objects=new Map();
 const bucket={async get(key){if(!objects.has(key))return null;const b=objects.get(key);return {async arrayBuffer(){return b.slice().buffer;}};},async put(key,value,options){if(options?.onlyIf?.etagDoesNotMatch==='*'&&objects.has(key))return null;objects.set(key,new Uint8Array(value).slice());return {};}};
 return {db,objects,env:{DB:new D1(db),ARTIFACTS:bucket},storage:new Storage({DB:new D1(db),ARTIFACTS:bucket})};
}
