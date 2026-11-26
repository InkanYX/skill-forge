// Only navigation preferences belong here; never store forms, materials or model credentials.
const prefix='skill-forge:view:v1:';
const memory=new Map<string,unknown>();
export function readView<T>(user:string,key:string,fallback:T):T{
  const storageKey=prefix+encodeURIComponent(user)+':'+key;
  try{const raw=sessionStorage.getItem(storageKey);if(raw!==null)return JSON.parse(raw) as T;}catch{/* Storage can be unavailable. */}
  return (memory.get(storageKey) as T|undefined)??fallback;
}
export function writeView(user:string,key:string,value:unknown){
  const storageKey=prefix+encodeURIComponent(user)+':'+key;
  memory.set(storageKey,value);
  try{sessionStorage.setItem(storageKey,JSON.stringify(value));}catch{/* Keep session memory usable. */}
}
