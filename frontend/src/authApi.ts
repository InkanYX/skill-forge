export interface User { id:string;username:string;display_name:string;role:'admin'|'member';is_active:boolean;must_change_password:boolean;created_at:string }
export async function authRequest<T>(path:string,body?:unknown,method='POST'):Promise<T>{
  const response=await fetch(`/api/${path}`,{cache:'no-store',signal:AbortSignal.timeout(15000),...(body!==undefined?{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:Array.isArray(value.detail)?value.detail.map((item:{msg:string})=>item.msg.replace(/^Value error,\s*/, '')).join('；'):'请求失败，请重试。');return value;
}
