import { useEffect, useState } from 'react';
import { projectRequest, materialUrl, type Material, type Project, type RankedSellingPoint, type ResearchSettings, type ResearchReport } from './creationProjectApi';
import { formatTaskTime } from './imageTaskApi';

const defaults:ResearchSettings={enabled:false,marketplace:'US',own_asin:'',competitor_asins:[],reviews_per_asin:40};
const markets:Record<string,string>={US:'美国',UK:'英国',DE:'德国',FR:'法国',IT:'意大利',ES:'西班牙',JP:'日本',CA:'加拿大',AU:'澳大利亚',MX:'墨西哥',BR:'巴西',IN:'印度',AE:'阿联酋'};
const priorityNames={P1:'核心展示',P2:'支撑说服',P3:'补充信息',VERIFY:'待验证机会'};
const sentimentNames={positive:'正向认可',negative:'负向痛点',neutral:'中性提及',mixed:'褒贬并存'};

export function AnalysisProgress({project,disabled,onResume}:{project:Project;disabled:boolean;onResume:()=>void}){
  const pipeline=project.analysis_pipeline;
  if(!pipeline)return null;
  const phases=[['materials','提炼资料卖点'],['research','获取市场资料'],['reviews','分批分析评论'],['ranking','汇总展示优先级']] as const;
  const position=pipeline.phase==='completed'||pipeline.phase==='saving'?4:phases.findIndex(([key])=>key===pipeline.phase);
  const completed=pipeline.status==='completed';
  return <section className="analysis-pipeline" aria-label="产品分析进度" aria-live="polite">
    <header><strong>{completed?'产品与市场分析已完成':pipeline.status==='failed'?'分析暂未完成，已保存进度':'正在分阶段分析产品'}</strong><span>{pipeline.completed_batches} / {pipeline.total_batches} 批评论</span></header>
    <ol>{phases.map(([key,label],index)=><li key={key} className={index<position||completed?'is-done':index===position?'is-current':''}><span>{index<position||completed?'✓':index+1}</span>{label}</li>)}</ol>
    {!completed&&<p>{pipeline.phase==='materials'?'先读取产品原件，保存真实卖点，再分析市场评论。':'资料卖点已保存；已完成评论批次会保留，后续失败可继续，无需从头分析。'}</p>}
    {!project.busy&&pipeline.can_resume&&<div className="guided-actions"><button type="button" className="button-secondary" disabled={disabled} onClick={onResume}>继续未完成分析</button><small>沿用原分析要求和已完成结果；若修改了资料、技能、模型或卖点，请开始新一轮分析。</small></div>}
  </section>;
}

export function SellingPointMetrics({point}:{point:RankedSellingPoint}){
  const metrics=point.review_metrics;
  if(!metrics||metrics.status==='unannotated') return <p className="selling-point-reason">尚未统计逐卖点评论提及。重新分析可使用已有调研快照；无需刷新 MCP。</p>;
  return <div className="selling-point-metrics" aria-label={point.title+'评论关注度'}>
    <p>{metrics.status==='complete'?'已核对全部有效样本':'部分核对 · 数量为已确认提及，暂不自动按数量重排'} · 同一评论对该卖点只计一次</p>
    <div className="review-metrics-grid">{(['all','own','competitor'] as const).map(role=>{const group=metrics.groups[role];return <section key={role}><small>{role==='all'?'全部样本':role==='own'?'自家商品':'竞品'}</small><strong>{group.mentions}<span> / {group.sample_count} 条</span></strong><p>{metrics.status==='complete'&&group.mention_rate!==null?`样本提及率 ${(group.mention_rate*100).toFixed(1)}%`:`已核对 ${group.reviewed_count} / ${group.sample_count} 条`}</p><div>正向 {group.positive} · 负向 {group.negative}<br/>中性 {group.neutral} · 褒贬并存 {group.mixed}</div></section>;})}</div>
    <small>评价倾向针对该卖点判断，与星级不同。好差评分层采样，以上不是全体买家占比；不同组请结合样本数比较。</small>
    {!!metrics.own_negative_review_ids.length&&<p className="research-warning">自家商品有 {metrics.own_negative_review_ids.length} 条负向或褒贬并存提及，请对照产品资料核实是否与拟宣传优势矛盾。</p>}
  </div>;
}

export function ProductResearch({project,locked,onSave,onDirty,refresh,onRefresh}:{project:Project;locked:boolean;onSave:(settings:ResearchSettings)=>Promise<unknown>;onDirty:(dirty:boolean)=>void;refresh:boolean;onRefresh:(value:boolean)=>void}){
  const saved=project.research_settings||defaults;
  const [enabled,setEnabled]=useState(saved.enabled);const [market,setMarket]=useState(saved.marketplace);
  const [own,setOwn]=useState(saved.own_asin);const [competitors,setCompetitors]=useState(saved.competitor_asins.join('\n'));
  const [count,setCount]=useState(saved.reviews_per_asin);const [configured,setConfigured]=useState<boolean|null>(null);const [serviceError,setServiceError]=useState('');
  const signature=JSON.stringify(saved);
  useEffect(()=>{setEnabled(saved.enabled);setMarket(saved.marketplace);setOwn(saved.own_asin);setCompetitors(saved.competitor_asins.join('\n'));setCount(saved.reviews_per_asin);},[project.id,signature]);
  useEffect(()=>{let active=true;projectRequest<{configured:boolean}>('/research-service').then(value=>{if(active)setConfigured(value.configured);}).catch(()=>{if(active)setServiceError('公共调研服务状态暂时无法读取，请刷新页面。');});return()=>{active=false;};},[]);
  const asins=Array.from(new Set(competitors.trim().split(/[\s,，;；]+/).filter(Boolean).map(value=>value.toUpperCase())));
  const settings:ResearchSettings={enabled,marketplace:market,own_asin:own.trim().toUpperCase(),competitor_asins:asins,reviews_per_asin:count};
  const dirty=JSON.stringify(settings)!==signature;
  useEffect(()=>{onDirty(dirty);return()=>onDirty(false);},[dirty,onDirty]);
  const total=new Set([settings.own_asin,...asins].filter(Boolean)).size;
  const invalidAsin=[settings.own_asin,...asins].filter(Boolean).some(value=>!/^B[A-Z0-9]{9}$/.test(value));
  const validation=invalidAsin?'请输入以 B 开头的 10 位 ASIN。':total>5?'自家与竞品合计最多 5 个 ASIN。':total*count>200?'评论总量上限为 200 条，请减少 ASIN 或每个商品的评论数。':enabled&&!total?'请至少填写一个自家或竞品 ASIN。':'';
  const progress=project.executions.slice().reverse().find(value=>['queued','running'].includes(value.status))?.output.research_progress;
  const report=project.market_research;
  return <section className="guided-card product-research" aria-labelledby="product-research-title">
    <header><div><p className="eyebrow">MARKET INTELLIGENCE</p><h3 id="product-research-title">让卖点回应真实买家需求</h3></div><span className={'research-service-badge'+(configured?' is-connected':'')}>{configured===null?serviceError?'服务状态暂不可用':'读取服务状态…':configured?'团队公共 MCP 已配置':'公共 MCP 尚未配置'}</span></header>
    <p>将产品资料与竞品、评论交叉分析。市场需求帮助决定先展示什么，产品事实仍以你的资料为准。</p>
    {serviceError&&<p className="feedback feedback-warning" role="alert">{serviceError}</p>}
    <fieldset disabled={locked}><label className="research-toggle"><input type="checkbox" checked={enabled} onChange={event=>setEnabled(event.target.checked)}/><span><strong>结合卖家精灵市场调研</strong><small>关闭后只分析上传资料；启用后，在下方提交产品分析时执行调研。</small></span></label>
    {enabled&&<div className="research-settings"><div className="guided-form-grid"><label>亚马逊站点<select value={market} onChange={event=>setMarket(event.target.value)}>{Object.entries(markets).map(([key,label])=><option value={key} key={key}>{label} · {key}</option>)}</select></label><label>自家 ASIN（选填）<input value={own} maxLength={10} onChange={event=>setOwn(event.target.value)} placeholder="B0…" autoCapitalize="characters"/></label></div>
      <label>竞品 ASIN<textarea rows={3} value={competitors} maxLength={150} onChange={event=>setCompetitors(event.target.value)} placeholder="每行一个 ASIN，也可用逗号分隔。自家与竞品合计最多 5 个。"/></label>
      <div className="guided-form-grid"><label>每个商品最多读取评论<select value={count} onChange={event=>setCount(Number(event.target.value))}>{[10,20,40,60,100].map(value=><option value={value} key={value}>{value} 条 · 好评与差评各约一半</option>)}</select></label><div className="research-budget"><strong>{total*count}<small> 条评论上限</small></strong><span>{total} 个商品 · 最多 {total?1+total*3:0} 次数据查询</span><small>包含商品信息、五点描述及两组评论。实际额度以服务商为准。</small></div></div>
      <p className="research-scope-note">评论为父体维度，可能涉及不同子款。按好差评分层采样，不能据此推算全体买家的占比。</p>
    </div>}
    {validation&&<p className="feedback feedback-warning" role="alert">{validation}</p>}
    <div className="guided-actions"><button type="button" className="button-secondary" disabled={!dirty||!!validation} onClick={()=>void onSave(settings)}>保存调研设置</button><small>{dirty?'设置有修改，保存后再提交产品分析。':'设置已保存 · 相同范围优先复用已获取资料'}</small></div></fieldset>
    {report&&<div className="research-snapshot-strip"><div><strong>{report.status==='ready'?'调研资料已就绪':'调研资料部分完成'}</strong><span>{report.settings.marketplace} · {report.review_count} 条去重评论 · {formatTaskTime(report.created_at)}</span></div><span>{report.cache_hit?'最近一次分析复用了缓存':'已保存调研快照'}</span></div>}
    {enabled&&report&&<label className="research-refresh"><input type="checkbox" checked={refresh} disabled={locked||dirty} onChange={event=>onRefresh(event.target.checked)}/><span>下次分析刷新调研资料，重新调用并消耗额度。若此前结果待确认，请先向服务商核对，刷新可能重复计费。</span></label>}
    {report?.connection_error&&<p className="feedback feedback-warning" role="alert">{report.connection_error.message} {report.connection_error.elapsed_seconds!=null&&`耗时 ${report.connection_error.elapsed_seconds} 秒。`}{report.connection_error.business_query_started?'已开始业务查询，请查看各项来源记录。':'本轮尚未开始商品或评论查询；修复连接后直接重新分析，无需勾选刷新。'}</p>}
    {progress&&<div className="research-progress" role="status"><span className="upload-spinner"/><span>市场调研 {progress.completed} / {progress.total} · {progress.current||'资料已收集，正在分析卖点'}</span><progress value={progress.completed} max={progress.total} aria-label="市场调研进度"/></div>}
  </section>;
}

export function ResearchEvidence({report}:{report:ResearchReport}){
  return <details className="research-evidence"><summary>调研来源与样本 · {report.review_count} 条评论 · {report.settings.marketplace}</summary>
    <p>采集于 {formatTaskTime(report.created_at)}；该快照随本版分析保留，后续刷新不会改写本版依据。</p>
    {Array.from(new Set(report.warnings)).map(warning=><p className="research-warning" key={warning}>{warning}</p>)}
    <div className="research-source-list">{report.sources.map(source=><details key={source.id}><summary>{String(source.arguments.asin||'批量商品信息')} · {source.tool==='asin.detail'?'商品资料':source.tool==='asin.content.list'?'五点描述':source.id.endsWith('critical')?'差评与使用痛点':'好评与认可点'} · {source.status==='succeeded'?'已获取':source.status==='unknown'?'结果待确认':'未完成'}</summary>{source.error&&<p>{source.error}</p>}{source.data!=null&&<details><summary>原始来源记录</summary><pre>{JSON.stringify(source.data,null,2)}</pre></details>}</details>)}</div>
    <details><summary>浏览全部有效评论</summary>{report.reviews.map(review=><article className="research-review" key={review.id}><small>{review.role==='own'?'自家商品':'竞品'} · {review.asin} · {review.star??'未知'} 星 · {review.date||'日期未提供'}{review.variant?' · '+review.variant:''}</small><strong>{review.title}</strong><p>{review.text}</p><small>引用 ID：{review.id}</small></article>)}</details>
  </details>;
}

export function rankedPointsText(points:RankedSellingPoint[]){
  return points.filter(point=>point.priority!=='VERIFY').map((point,index)=>`${index+1}. [${point.priority}] ${point.title}\n买家需求：${point.buyer_need}\n产品依据：${point.product_evidence}\n展示建议：${point.display_suggestion}${point.expression_limits?'\n表达限制：'+point.expression_limits:''}`).join('\n\n');
}

export function SellingPointRanking({points,report,locked,onChange,materials,projectId}:{points:RankedSellingPoint[];report?:ResearchReport;locked:boolean;onChange:(points:RankedSellingPoint[])=>void;materials:Material[];projectId:string}){
  const reviews=new Map(report?.reviews.map(review=>[review.id,review])||[]);
  function move(index:number,delta:number){const next=[...points];[next[index],next[index+delta]]=[next[index+delta],next[index]];onChange(next);}
  return <div className="selling-point-ranking"><div className="research-ranking-heading"><div><p className="eyebrow">EVIDENCE → PRIORITY → VISUAL</p><h4>卖点展示优先级</h4></div><small>可调整级别与顺序；保存并确认后传给图片策划。</small></div>
    <p className="research-scope-note">先由产品资料确定真实卖点，再按评论样本关注度辅助排序；同等关注度结合痛点、购买决策与差异化。资料不足的机会保留待验证，最终以你确认的排序为准。</p>
    {points.map((point,index)=>{const cited=point.review_ids.flatMap(id=>reviews.has(id)?[reviews.get(id)!]:[]);const hasEvidence=!!point.product_evidence.trim()&&(point.material_ids.length>0||point.uses_product_description);
      return <article className={'selling-point-card priority-'+point.priority.toLowerCase()} key={point.id}><header><span className="selling-point-number">{String(index+1).padStart(2,'0')}</span><div><span className="selling-point-priority">{point.priority==='VERIFY'?'待验证':point.priority} · {priorityNames[point.priority]}</span><h4>{point.title}</h4></div><div className="selling-point-actions"><select aria-label={point.title+'优先级'} value={point.priority} disabled={locked} onChange={event=>onChange(points.map((value,i)=>i===index?{...value,priority:event.target.value as RankedSellingPoint['priority']}:value))}>{Object.entries(priorityNames).map(([key,label])=><option key={key} value={key} disabled={key!=='VERIFY'&&!hasEvidence}>{key==='VERIFY'?'待验证':key} · {label}</option>)}</select><button type="button" aria-label={'上移'+point.title} disabled={locked||index===0} onClick={()=>move(index,-1)}>↑</button><button type="button" aria-label={'下移'+point.title} disabled={locked||index===points.length-1} onClick={()=>move(index,1)}>↓</button></div></header>
      <div className="selling-point-body"><div><small>买家为什么在意</small><p>{point.buyer_need||'本次未提供评论需求依据'}</p></div><div><small>这款产品如何回应</small><p>{point.product_evidence||'尚缺产品资料支持，先核实再表达。'}</p></div><div><small>建议如何展示</small><p>{point.display_suggestion||'确认卖点后在图片策划中安排。'}</p></div></div>
      <SellingPointMetrics point={point}/>
      {!!point.review_mentions?.length&&<details className="selling-point-evidence"><summary>查看逐条提及与评价倾向</summary>{point.review_mentions.map(mention=>{const review=reviews.get(mention.review_id);return <blockquote className="research-review" key={mention.review_id}><small>{sentimentNames[mention.sentiment]} · {review?.role==='own'?'自家':'竞品'} · {review?.asin} · {review?.star??'未知'} 星</small><p>{mention.quote}</p><small>引用 ID：{mention.review_id}</small></blockquote>;})}</details>}
      {point.reason&&<p className="selling-point-reason">排序理由：{point.reason}</p>}{point.expression_limits&&<p className="research-warning">表达边界：{point.expression_limits}</p>}
      <details className="selling-point-evidence"><summary>查看依据 · 引用 {cited.length} / {report?.review_count||0} 条有效样本 · {point.material_ids.length} 份产品资料</summary><p>产品资料：{point.material_ids.length?point.material_ids.map(id=><a key={id} href={materialUrl(projectId,id)} target="_blank" rel="noreferrer">{materials.find(item=>item.id===id)?.name||'查看原件'}　</a>):point.uses_product_description?'用户提供的产品说明':'尚未关联资料'}</p>{cited.length?cited.map(review=><blockquote className="research-review" key={review.id}><small>{review.role==='own'?'自家':'竞品'} · {review.asin} · {review.star??'未知'} 星 · {review.date}</small><strong>{review.title}</strong><p>{review.text}</p></blockquote>):<p>没有可追溯的评论引用，不代表已获得买家验证。</p>}</details>
    </article>;})}
  </div>;
}
