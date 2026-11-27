import { useEffect, useRef, useState } from 'react';
import { array, display, label, marketRequest, numeric, object, unwrap, type Data, type MarketQuery, type MarketStudy } from './marketInsightApi';
import { formatTaskTime } from './imageTaskApi';
import { createRequestId } from './requestId';
import './market-insights.css';

const markets:Record<string,string>={US:'美国',UK:'英国',DE:'德国',FR:'法国',IT:'意大利',ES:'西班牙',JP:'日本',CA:'加拿大',AU:'澳大利亚',MX:'墨西哥',BR:'巴西',IN:'印度',AE:'阿联酋'};
const sections=[['overview','市场概况','销量、销售额与新品表现'],['history','需求趋势','近 24 个月的市场变化'],['distribution','价格与门槛','价格、评分与上架时长分布'],['products','商品竞争','头部 10 个商品表现'],['brands','品牌格局','头部 10 个品牌表现']] as const;
const statusNames={queued:'等待采集',running:'正在采集',succeeded:'已保存',failed:'未完成',unknown:'扣费与结果待确认'};

function SourceData({query}:{query:MarketQuery}){
  return <details className="mi-source"><summary>数据来源与原始记录</summary><p>{query.provider==='xiyou'?'西柚洞察':'卖家精灵'} · {query.tool} · 采集于 {formatTaskTime(query.updated_at)}</p><p>查询范围：{JSON.stringify(query.arguments)}。空值表示暂无数据；第三方统计与估算不等于官方全量。</p><pre>{JSON.stringify(query.result,null,2)}</pre></details>;
}

function Metrics({items}:{items:[string,unknown,boolean?][]}){
  return <div className="mi-metrics">{items.map(([name,value,percent])=><div key={name}><span>{name}</span><strong>{display(value,percent)}</strong></div>)}</div>;
}

function Trend({points}:{points:Data[]}){
  const prepared=points.map((p)=>({date:String(p.localDate||p.month||p.dataMonth||p.yearMonth||''),value:numeric(object(p.sales).value??p.totalSales??p.sales)}));
  const valid=prepared.flatMap(p=>p.value===null?[]:[p.value]);
  if(!valid.length)return <p className="mi-muted">来源暂无可绘制的月度销量序列，可展开原始记录核对数据覆盖。</p>;
  const max=Math.max(...valid,1), step=680/Math.max(prepared.length-1,1);
  return <div className="mi-chart"><svg viewBox="0 0 720 190" role="img" aria-label="月度销量趋势"><path d="M20 20V160H710" fill="none" stroke="currentColor" opacity=".15"/>{[0,1,2].map(n=><path key={n} d={`M20 ${35+n*45}H710`} stroke="currentColor" strokeDasharray="3 6" opacity=".08"/>)}{prepared.map((p,i)=>p.value===null?null:<g key={i}>{i>0&&prepared[i-1].value!==null&&<line x1={25+(i-1)*step} y1={155-prepared[i-1].value!/max*125} x2={25+i*step} y2={155-p.value/max*125} stroke="currentColor" strokeWidth="2.5"/>}<circle cx={25+i*step} cy={155-p.value/max*125} r="3" fill="currentColor"><title>{p.date} · {display(p.value)} 件</title></circle></g>)}</svg><div className="mi-chart-range"><span>{prepared[0]?.date}</span><span>月销量 · 悬停查看数值</span><span>{prepared.at(-1)?.date}</span></div><details><summary>查看趋势数据表</summary><table><thead><tr><th>月份</th><th>销量</th></tr></thead><tbody>{prepared.map((p,i)=><tr key={i}><td>{p.date||'未提供'}</td><td>{display(p.value)}</td></tr>)}</tbody></table></details></div>;
}

function SectionResult({query}:{query:MarketQuery}){
  const data=unwrap(query.result);
  if(query.section==='overview')return <><Metrics items={[
    ['样本商品数',data.productCount],['统计销量',data.totalSales],['统计销售额',data.totalRevenue],['平均价格',data.avgPrice],
    ['平均评分',data.avgRating],['新品销量占比',data.newSalesRatio,true],['头部商品集中度',data.competition,true],['头部品牌集中度',data.brandConcentration,true]]}/><p className="mi-muted">样本档位 100；新品默认按 3 个月定义。金额币种：{String(data.currency||'以站点来源为准')}。不将样本规模解释为全市场规模。</p></>;
  if(query.section==='history')return <Trend points={array(data.monthlyList)}/>;
  if(query.section==='distribution')return <div className="mi-distributions">{array(data.metrics).map((metric,index)=>{const names:Record<string,string>={price:'价格分布',ratingValue:'星级分布',ratingsCount:'评分数量门槛',shelfTime:'上架时长'};return <section key={index}><h4>{names[String(metric.metric)]||String(metric.metric)}</h4><div className="mi-table-wrap"><table><thead><tr><th>区间</th><th>商品数</th><th>销量</th><th>销量占比</th></tr></thead><tbody>{array(metric.buckets).map((bucket,i)=><tr key={i}><td>{String(bucket.label||bucket.key||'未命名')}</td><td>{display(bucket.products)}</td><td>{display(bucket.sales)}</td><td>{display(bucket.salesShare,true)}</td></tr>)}</tbody></table></div></section>;})}</div>;
  return <div className="mi-table-wrap"><p className="mi-muted">实际统计期间：{String(data.periodStart||'未提供')} — {String(data.periodEnd||'未提供')} · 归档月 {String(data.dataMonth||'未提供')}</p><table><thead><tr><th>排名</th><th>{query.section==='brands'?'品牌':'商品 / ASIN'}</th><th>销量</th><th>销量份额</th><th>销售额</th><th>均价</th></tr></thead><tbody>{array(data.items).map((item,i)=><tr key={i}><td>{String(item.ranking??i+1)}</td><td>{String(item.brand||item.title||item.asin||'未提供')}{item.asin!=null&&<small>{String(item.asin)}</small>}</td><td>{display(item.sales)}</td><td>{display(item.salesShare,true)}</td><td>{display(item.revenue)}</td><td>{display(item.avgPrice)}</td></tr>)}</tbody></table>{!array(data.items).length&&<p className="mi-muted">当前范围暂无排名数据，不代表没有竞争。</p>}</div>;
}

function XiyouResult({query}:{query:MarketQuery}){
  const data=unwrap(query.result), rows=array(data.list);
  return <div className="mi-categories">{!rows.length&&<p>当前站点和月份没有匹配类目，可调整关键词后重新查询。</p>}{rows.map((item,index)=>{
    const sales=object(item.sales), newer=object(item.newProduct), trend=object(item.salesTrend);
    const season:Record<string,string>={nonseasonal:'非季节性',peak:'旺季',off:'淡季',shoulder:'平季'};
    return <article className="mi-category" key={String(item.categoryId||index)}><header><div><small>{array(item.path).map(x=>label(x.categoryName)).join(' / ')}</small><h3>{label(item.categoryName)}</h3></div><span className="mi-tag">{item.available===false?'深度数据暂不可用':season[String(item.seasonType)]||'季节状态未提供'}</span></header>
      <Metrics items={[["月销量",sales.value],["月销售额",object(item.salesRevenue).value],["销量环比",object(sales.mom).rate,true],["销量同比",object(sales.yoy).rate,true],["活跃父 ASIN",item.activePrimaryAsinCount],["新品销量份额",object(newer.sales).ratio,true]]}/>
      <Trend points={array(trend.trends)}/>
      {!!array(item.topPrimaryAsins).length&&<div className="mi-asins">{array(item.topPrimaryAsins).map((p,i)=>{const src=typeof p.imageUrl==='string'&&/^https:\/\//.test(p.imageUrl)?p.imageUrl:undefined;return <div key={i}>{src&&<img src={src} alt="类目代表商品" loading="lazy" referrerPolicy="no-referrer"/>}<small>{String(p.primaryAsin||'')}</small></div>;})}</div>}
      <p className="mi-muted">代表商品用于识别类目范围，不作为完整销量榜。趋势按来源完整历史展示；上方指标属于所选自然月。</p>
    </article>;
  })}<p className="mi-muted">本页 {rows.length} 个类目 / 共 {String(data.total??'未知')} 个匹配项；未自动翻页。结果顺序不代表销量排名。</p></div>;
}

function QueryRecord({query,onResolve}:{query:MarketQuery;onResolve:(id:string)=>void}){
  return <details className="mi-query-record"><summary><span>{query.provider==='xiyou'?'西柚洞察':'卖家精灵'} · {query.section==='search'?'类目发现':sections.find(x=>x[0]===query.section)?.[1]}</span><span>{statusNames[query.status]} · {formatTaskTime(query.created_at)}</span></summary>
    <p>{query.reused_from?'复用已保存结果 · 本次扣费 0':query.provider==='xiyou'?`本次消耗 ${query.billing?.cost_credits??'待返回'} Credits`:`本次扣费 ${query.billing?.chargedUnits??'未返回'} 次 · 剩余 ${query.billing?.remainingUnits??'未返回'} 次`}</p>
    {query.error&&<p role="alert" className="feedback feedback-warning">{query.error}</p>}
    {query.status==='unknown'&&<button className="button-secondary" onClick={()=>onResolve(query.id)}>已核对服务商状态，解除待确认</button>}
    <SourceData query={query}/></details>;
}

export default function MarketInsights(){
  const [studies,setStudies]=useState<MarketStudy[]>([]),[study,setStudy]=useState<MarketStudy|null>(null);
  const [services,setServices]=useState({sellersprite:false,xiyou:false});
  const [title,setTitle]=useState(''),[market,setMarket]=useState(''),[provider,setProvider]=useState<'sellersprite'|'xiyou'>('sellersprite');
  const [keyword,setKeyword]=useState(''),[month,setMonth]=useState(''),[limit,setLimit]=useState(3);
  const [selected,setSelected]=useState<Data|null>(null),[tab,setTab]=useState('overview'),[notes,setNotes]=useState('');
  const [accepted,setAccepted]=useState(false),[refresh,setRefresh]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [external,setExternal]=useState<MarketQuery[]>([]);
  const activeId=useRef('');
  const pendingSubmit=useRef<{signature:string;request_id:string}|null>(null);
  async function load(id:string){const value=await marketRequest<MarketStudy>('/studies/'+id);if(activeId.current===id)setStudy(value);return value;}
  useEffect(()=>{let live=true;Promise.all([marketRequest<MarketStudy[]>('/studies'),marketRequest<typeof services>('/services')]).then(([items,svc])=>{if(!live)return;setStudies(items);setServices(svc);const id=new URLSearchParams(window.location.hash.split('?')[1]||'').get('study');if(id){activeId.current=id;void load(id).then(v=>{if(live)setNotes(v.notes);}).catch(e=>{if(live)setError(e.message);});}}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;activeId.current='';};},[]);
  const queries=[...(study?.queries||[]),...external.filter(q=>!(study?.queries||[]).some(v=>v.id===q.id))].sort((a,b)=>b.created_at.localeCompare(a.created_at));
  const pending=queries.filter(q=>q.status==='queued'||q.status==='running');
  const pendingKey=pending.map(q=>q.id).join(',');
  useEffect(()=>{if(!pendingKey)return;let live=true;const timer=window.setInterval(()=>{Promise.all(pending.map(q=>marketRequest<MarketQuery>('/queries/'+q.id))).then(rows=>{if(!live)return;setExternal(previous=>[...rows,...previous.filter(q=>!rows.some(v=>v.id===q.id))]);if(activeId.current)void load(activeId.current).catch(e=>{if(live)setError(e.message);});}).catch(e=>{if(live)setError('读取查询进度失败：'+e.message+'。任务保留，可重新进入页面查看。');});},2500);return()=>{live=false;clearInterval(timer);};},[pendingKey]);
  async function act(action:()=>Promise<void>){if(busy)return;setBusy(true);setError('');setNotice('');try{await action();}catch(e){setError(e instanceof Error?e.message:'操作未完成。');}finally{setBusy(false);}}
  async function open(value:MarketStudy){activeId.current=value.id;setStudy(value);setSelected(null);setExternal([]);setNotes(value.notes);setNotice('');setError('');window.history.replaceState(null,'','#/market?study='+value.id);await load(value.id);}
  async function create(){await act(async()=>{const value=await marketRequest<MarketStudy>('/studies','POST',{title,marketplace:market});setStudies(rows=>[value,...rows]);setTitle('');await open(value);setNotice('调研项目已创建，团队成员可共同查看。');});}
  async function submit(section:string){if(!study)return;await act(async()=>{
    const args={provider,section,keyword,month:section==='history'?'':month,category_id:String(selected?.categoryId||''),limit,refresh,accept_cost:accepted};
    const signature=JSON.stringify([study.id,args]);
    if(!pendingSubmit.current||pendingSubmit.current.signature!==signature)pendingSubmit.current={signature,request_id:createRequestId()};
    const query=await marketRequest<MarketQuery>('/studies/'+study.id+'/queries','POST',{...args,request_id:pendingSubmit.current.request_id});
    pendingSubmit.current=null;
    setExternal(rows=>[query,...rows.filter(q=>q.id!==query.id)]);await load(study.id);
    setNotice(query.status==='unknown'?'该范围已有结果待确认，请先核对服务商状态。':query.cache_hit?'已复用现有查询记录，未提交新的业务请求。':'查询已提交；离开页面后仍会继续，返回此项目可查看进度。');
  });}
  async function resolve(id:string){await act(async()=>{const value=await marketRequest<MarketQuery>('/queries/'+id+'/resolve','POST',{});setExternal(rows=>[value,...rows.filter(q=>q.id!==id)]);if(study)await load(study.id);setNotice('原记录已保留；需要重新采集时，请勾选刷新并明确提交。');});}
  const searches=queries.filter(q=>q.provider===provider&&q.section==='search'&&q.status==='succeeded');
  const search=searches[0];
  const categories=search?array(unwrap(search.result).items):[];
  const current=queries.find(q=>q.provider==='sellersprite'&&q.section===tab&&object(q.arguments).categoryId===selected?.categoryId&&q.status==='succeeded'&&
    (tab==='history'||String(q.arguments.currentMonth??q.arguments.dataMonth??'')===month.replace('-','')));
  function exportStudy(){if(!study)return;const url=URL.createObjectURL(new Blob([JSON.stringify({...study,queries},null,2)],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='market-study-'+study.id+'.json';a.click();URL.revokeObjectURL(url);}
  return <div className="mi-page"><header className="mi-hero"><div><p className="eyebrow">MARKET OBSERVATORY / 市场研究</p><h1>从市场信号，<br/><em>看见下一步。</em></h1><p>先圈定市场，再看需求、价格与竞争。每一次查询，都成为团队可复用的研究。</p></div><div className="mi-hero-aside"><span>TEAM INTELLIGENCE</span><strong>{String(studies.length).padStart(2,'0')}</strong><small>个团队调研项目</small><div><i className={services.sellersprite?'is-on':''}/>卖家精灵 · {services.sellersprite?'已配置':'未配置'}</div><div><i className={services.xiyou?'is-on':''}/>西柚洞察 · {services.xiyou?'已配置':'未配置'}</div></div></header>
    {error&&<p className="feedback feedback-warning" role="alert">{error}</p>}{notice&&<p className="mi-notice" role="status">{notice}</p>}
    <div className="mi-workspace"><aside className="mi-projects"><div className="mi-section-heading"><h2>调研项目</h2><span>团队共享</span></div><form onSubmit={e=>{e.preventDefault();void create();}}><label>新建调研<input value={title} maxLength={120} onChange={e=>setTitle(e.target.value)} placeholder="例如：车棚市场研究" required/></label><label>亚马逊站点<select value={market} onChange={e=>setMarket(e.target.value)} required><option value="">请选择站点</option>{Object.entries(markets).map(([k,v])=><option key={k} value={k}>{v} · {k}</option>)}</select></label><button disabled={busy||!title.trim()||!market}>创建项目 <span aria-hidden="true">＋</span></button></form><div className="mi-study-list">{studies.map(v=><button type="button" className={study?.id===v.id?'is-selected':''} key={v.id} disabled={busy} onClick={()=>void act(()=>open(v))}><strong>{v.title}</strong><small>{v.marketplace} · {v.author}</small></button>)}</div>{!studies.length&&<p className="mi-muted">创建第一个项目，保存市场研究的完整过程。</p>}</aside>
    <div className="mi-content">{!study?<section className="mi-empty"><span>01 / DEFINE YOUR MARKET</span><h2>先给研究一个方向</h2><p>在左侧创建项目，选择站点，再搜索你关注的类目。查询由你手动发起，打开页面不会消耗调研额度。</p><div><span>市场规模</span><span>需求趋势</span><span>价格带</span><span>竞争格局</span></div></section>:<>
      <header className="mi-study-heading"><div><span className="mi-tag">{markets[study.marketplace]}站 · 团队共享</span><h2>{study.title}</h2><p>{study.author} 创建 · {formatTaskTime(study.created_at)}</p></div><button type="button" className="button-secondary" onClick={exportStudy}>导出调研记录 ↗</button></header>
      <section className="mi-panel"><div className="mi-section-heading"><h3>01 / 圈定市场</h3><span>选择来源与查询范围</span></div><form onSubmit={e=>{e.preventDefault();void submit('search');}}><div className="mi-search-grid"><label>数据来源<select value={provider} onChange={e=>{setProvider(e.target.value as typeof provider);setAccepted(false);setSelected(null);}}><option value="sellersprite">卖家精灵 · 类目研究</option><option value="xiyou">西柚洞察 · 类目发现</option></select></label><label>{provider==='xiyou'?'关键词或单个 ASIN':'类目关键词'}<input value={keyword} onChange={e=>setKeyword(e.target.value)} maxLength={120} placeholder={provider==='xiyou'?'输入方向；留空可发现类目':'例如：Carports'} required={provider==='sellersprite'}/></label><label>{provider==='xiyou'?'统计月份（必填）':'归档月份（选填）'}<input type="month" value={month} onChange={e=>{setMonth(e.target.value);setAccepted(false);}} required={provider==='xiyou'}/></label>{provider==='xiyou'&&<label>返回类目数<select value={limit} onChange={e=>{setLimit(Number(e.target.value));setAccepted(false);}}>{[1,3,5].map(n=><option key={n} value={n}>{n} 个 · 最多 {n*5} Credits</option>)}</select></label>}</div>
      <div className="mi-cost"><label><input type="checkbox" checked={accepted} onChange={e=>setAccepted(e.target.checked)}/><span>{provider==='xiyou'?`确认查询所选自然月，最多 ${limit*5} Credits；不自动生成额外研报资源。`:'确认每次手动操作最多提交 1 次业务查询；具体扣费以服务商返回为准。'}</span></label><label><input type="checkbox" checked={refresh} onChange={e=>setRefresh(e.target.checked)}/>刷新来源数据（可能重新扣费，保留旧记录）</label></div><button disabled={busy||!accepted||!services[provider]}>{busy?'正在提交…':'搜索类目'} <span aria-hidden="true">→</span></button><small className="mi-muted">相同范围优先复用团队记录；无自动采集。卖家精灵搜索最多 20 项；西柚月份需由你明确选择。</small></form>
      {search&&provider==='sellersprite'&&<div className="mi-category-options">{categories.map((v,i)=><button type="button" key={i} className={selected?.categoryId===v.categoryId?'is-selected':''} onClick={()=>setSelected(v)}><strong>{String(v.name||'未命名类目')}</strong><small>{Array.isArray(v.nodePath)?v.nodePath.join(' / '):String(v.categoryId||'')}</small></button>)}{!categories.length&&<p className="mi-muted">搜索没有返回匹配类目，可调整关键词。</p>}</div>}
      {search&&provider==='xiyou'&&<><XiyouResult query={search}/><SourceData query={search}/></>}
      </section>
      {provider==='sellersprite'&&selected&&<section className="mi-panel"><div className="mi-section-heading"><div><h3>02 / {String(selected.name)}</h3><small>完整节点：{String(selected.categoryId)}</small></div></div><div className="mi-tabs" role="tablist" aria-label="市场研究模块">{sections.map(([id,name])=><button role="tab" aria-selected={tab===id} key={id} onClick={()=>setTab(id)}>{name}</button>)}</div><div className="mi-query-heading"><p>{sections.find(x=>x[0]===tab)?.[2]}<small>{tab==='history'?'返回近24个月，逐月观察需求变化。':month?`请求归档月 ${month}；以来源实际返回周期为准。`:'使用来源最新可用数据，近30天与归档月分别展示。'}</small></p><button type="button" className="button-secondary" disabled={busy||!accepted||!services.sellersprite} onClick={()=>void submit(tab)}>{current?refresh?'刷新本模块':'复用 / 查看记录':'采集本模块'}</button></div>{current?<><SectionResult query={current}/><SourceData query={current}/></>:<p className="mi-module-empty">本模块尚无成功结果。确认额度后点击“采集本模块”，每次只获取当前需要的数据。</p>}</section>}
      <section className="mi-panel"><div className="mi-section-heading"><h3>研究笔记</h3><span>{study.can_edit?'作者与管理员可编辑':'团队可查看'}</span></div><textarea aria-label="研究笔记" rows={4} maxLength={20000} value={notes} disabled={!study.can_edit||busy} onChange={e=>setNotes(e.target.value)} placeholder="记录观察、机会和需要验证的问题。结论请注明来源与统计范围。"/><button type="button" className="button-secondary" disabled={!study.can_edit||busy||notes===study.notes} onClick={()=>void act(async()=>{const v=await marketRequest<MarketStudy>('/studies/'+study.id+'/notes','PUT',{notes});setStudy(old=>old?{...old,...v}:old);setNotice('研究笔记已保存。');})}>保存笔记</button></section>
      <section className="mi-panel"><div className="mi-section-heading"><h3>查询记录与额度</h3><span>{pending.length?'后台采集中 · 可离开页面':'所有版本均保留'}</span></div>{queries.map(q=><QueryRecord query={q} key={q.id} onResolve={id=>void resolve(id)}/>)}{!queries.length&&<p className="mi-muted">还没有查询记录。创建项目和浏览已保存结果不消耗额度。</p>}</section>
    </>}</div></div></div>;
}
