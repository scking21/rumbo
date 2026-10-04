/** Lossless JSON boundary for Python-compatible deterministic evidence.
 * JSON integer/float type and arbitrary-size integers survive parse/replay.
 * No eval, prototype assignment, duplicate keys, or nonfinite numbers.
 */
export class FloatValue { constructor(value) { this.value = value; Object.freeze(this); } }
function floatText(value) {
  if (!Number.isFinite(value)) throw new Error('Nonfinite JSON number');
  if (Object.is(value, -0)) return '-0.0';
  if (value === 0) return '0.0';
  const [mantissa, exponentText] = value.toExponential().split('e');
  const exponent = Number(exponentText);
  if (exponent < -4 || exponent >= 16) return mantissa+'e'+(exponent<0?'-':'+')+String(Math.abs(exponent)).padStart(2,'0');
  const sign=mantissa.startsWith('-')?'-':'';
  const digits=mantissa.replace('-','').replace('.',''),point=exponent+1;
  const decimal=point<=0?'0.'+'0'.repeat(-point)+digits:point>=digits.length?digits+'0'.repeat(point-digits.length)+'.0':digits.slice(0,point)+'.'+digits.slice(point);
  return sign+decimal;
}
function quote(value) {
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, ch=>'\\u'+ch.charCodeAt(0).toString(16).padStart(4,'0'));
}
function compareUnicode(a,b) {
  const aa=Array.from(a,c=>c.codePointAt(0)),bb=Array.from(b,c=>c.codePointAt(0));
  for(let i=0;i<Math.min(aa.length,bb.length);i++)if(aa[i]!==bb[i])return aa[i]-bb[i];
  return aa.length-bb.length;
}
function scalarString(value) {
  for(const char of value){const point=char.codePointAt(0);if(point>=0xd800&&point<=0xdfff)return false;}
  return true;
}
export function canonical(value, depth=0) {
  if(depth>128)throw new Error('JSON nesting exceeds limit');
  if(value===null)return 'null';
  if(value instanceof FloatValue)return floatText(value.value);
  if(typeof value==='bigint')return value.toString();
  if(typeof value==='number') {
    if(!Number.isFinite(value))throw new Error('Nonfinite JSON number');
    if(Number.isInteger(value))return BigInt(value).toString();
    return floatText(value);
  }
  if(typeof value==='string')return quote(value);
  if(typeof value==='boolean')return String(value);
  if(Array.isArray(value))return '['+value.map(v=>canonical(v,depth+1)).join(',')+']';
  if(value&&typeof value==='object')return '{'+Object.keys(value).sort(compareUnicode).map(k=>quote(k)+':'+canonical(value[k],depth+1)).join(',')+'}';
  throw new Error('Use finite JSON-compatible values');
}
export function clone(value) { return parseJSON(canonical(value),128); }
export function parseJSON(raw, maxDepth=64, options={}) {
  if(typeof raw!=='string')throw new Error('JSON input must be text');
  let i=0;
  const space=()=>{while(/[\x20\t\r\n]/.test(raw[i]??'x'))i++;};
  function value(depth) {
    space(); if(depth>maxDepth)throw new Error('JSON nesting exceeds limit');
    const ch=raw[i];
    if(ch==='"') {
      const start=i++; let escaped=false;
      while(i<raw.length){const c=raw[i++];if(!escaped&&c==='"'){const text=JSON.parse(raw.slice(start,i));if(options.scalarStrings&&!scalarString(text))throw new Error('JSON strings must be Unicode scalars');return text;}if(!escaped&&c==='\\')escaped=true;else escaped=false;}
      throw new Error('Unterminated string');
    }
    if(ch==='['||ch==='{') {
      if(depth>=maxDepth)throw new Error('JSON nesting exceeds limit');
      i++;space();const out=ch==='['?[]:Object.create(null),end=ch==='['?']':'}';
      if(raw[i]===end){i++;return out;}
      while(true){
        if(ch==='[')out.push(value(depth+1));
        else {if(raw[i]!=='"')throw new Error('Expected key');const key=value(depth+1);if(Object.hasOwn(out,key)&&!options.duplicates)throw new Error('Duplicate object key');space();if(raw[i++]!==':')throw new Error('Expected colon');out[key]=value(depth+1);}
        space();if(raw[i]===end){i++;return out;}if(raw[i++]!==',')throw new Error('Expected comma');space();
      }
    }
    for(const [literal,v] of [['true',true],['false',false],['null',null]])if(raw.startsWith(literal,i)){i+=literal.length;return v;}
    if(options.nonfinite)for(const [literal,v] of [['NaN',NaN],['Infinity',Infinity],['-Infinity',-Infinity]])if(raw.startsWith(literal,i)){i+=literal.length;return new FloatValue(v);}
    const match=raw.slice(i).match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/);
    if(!match)throw new Error('Invalid JSON');
    const token=match[0];i+=token.length;
    if(/[.eE]/.test(token)){const v=Number(token);if(!Number.isFinite(v)&&!options.nonfinite)throw new Error('Nonfinite JSON');return new FloatValue(v);}
    if(options.maxIntegerDigits&&token.replace(/^-/,'').length>options.maxIntegerDigits)throw new Error('JSON integer exceeds digit limit');
    const big=BigInt(token);return big>=BigInt(Number.MIN_SAFE_INTEGER)&&big<=BigInt(Number.MAX_SAFE_INTEGER)?Number(big):big;
  }
  const result=value(0);space();if(i!==raw.length)throw new Error('Trailing JSON input');return result;
}
export const utf8 = value => new TextEncoder().encode(value);
export async function sha256(value) {
  const bytes=typeof value==='string'?utf8(value):value;
  const hash=await crypto.subtle.digest('SHA-256',bytes);
  return Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,'0')).join('');
}

/** Match canonical artifact JSON encoding detection with strict scalar decoding. */
export function decodeJSONBytes(bytes) {
  const starts = prefix => prefix.every((value,index)=>bytes[index]===value);
  let encoding='utf8',start=0;
  if(starts([0,0,254,255])){encoding='utf32be';start=4;}
  else if(starts([255,254,0,0])){encoding='utf32le';start=4;}
  else if(starts([254,255])){encoding='utf16be';start=2;}
  else if(starts([255,254])){encoding='utf16le';start=2;}
  else if(starts([239,187,191]))start=3;
  else if(bytes.length>=4){
    if(!bytes[0])encoding=bytes[1]?'utf16be':'utf32be';
    else if(!bytes[1])encoding=bytes[2]||bytes[3]?'utf16le':'utf32le';
  }else if(bytes.length===2){
    if(!bytes[0])encoding='utf16be';else if(!bytes[1])encoding='utf16le';
  }
  if(encoding==='utf8')return new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes.subarray(start));
  const width=encoding.startsWith('utf16')?2:4,little=encoding.endsWith('le');
  if((bytes.length-start)%width)throw new Error('Incomplete JSON character encoding');
  const chars=[];
  for(let i=start;i<bytes.length;i+=width){
    let value=0;
    for(let j=0;j<width;j++)value=value*256+bytes[i+(little?width-1-j:j)];
    if(value>0x10ffff||(width===4&&value>=0xd800&&value<=0xdfff))throw new Error('Invalid JSON character encoding');
    chars.push(String.fromCodePoint(value));
  }
  const text=chars.join('');if(!scalarString(text))throw new Error('Invalid JSON character encoding');return text;
}
