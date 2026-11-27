import type { ShotDesign } from './creationProjectApi';

const styles:Record<string,string>={immersive:'沉浸场景',editorial:'品牌杂志',cinematic:'电影叙事',technical:'科技解析',minimal:'极简高端',informative:'高信息说明'};
const fields:{key:Exclude<keyof ShotDesign,'style'>;label:string}[]=[{key:'composition',label:'构图与占比'},{key:'camera',label:'镜头与机位'},{key:'depth',label:'空间 / 证据层次'},{key:'lighting',label:'光线与材质'},{key:'typography',label:'文字布局与阅读路径'},{key:'rationale',label:'风格执行与逐张变化'}];
export default function ShotDesignPanel({design,onChange,style='immersive'}:{design?:ShotDesign;onChange?:(value:ShotDesign)=>void;style?:string}){
  if(!design&&!onChange)return null;
  const value=design||{style:styles[style]?style:'immersive',composition:'',camera:'',depth:'',lighting:'',typography:'',rationale:''};
  return <section className="shot-design-panel"><header><small>DESIGN CONTRACT</small><h4>逐张设计方案</h4><p>这些决定会写入实际提示词，确认后再生图。文字检查不等于成图验收。</p></header>{onChange?<><label>执行风格<select value={value.style} onChange={event=>onChange({...value,style:event.target.value})}>{Object.entries(styles).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label><div className="guided-form-grid">{fields.map(field=><label key={field.key}>{field.label}<textarea aria-label={field.label} rows={3} maxLength={field.key==='camera'||field.key==='depth'||field.key==='lighting'?800:field.key==='rationale'?1000:1200} value={value[field.key]} onChange={event=>onChange({...value,[field.key]:event.target.value})}/></label>)}</div></>:<><span className="design-style-badge">{styles[value.style]||value.style}</span><dl className="brief-reading-grid">{fields.map(field=><div key={field.key}><dt>{field.label}</dt><dd>{value[field.key]}</dd></div>)}</dl></>}</section>;
}
