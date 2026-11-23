export async function apiFetch(input:RequestInfo|URL,init?:RequestInit){
  const response=await fetch(input,init);
  if(response.status===401)window.dispatchEvent(new Event('sf:unauthorized'));
  return response;
}
