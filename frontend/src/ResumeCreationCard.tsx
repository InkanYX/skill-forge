import { useEffect, useState } from 'react';
import { useAuth } from './AuthGate';
import { projectRequest, type Project } from './creationProjectApi';
import { readResume, rememberCreation, type ResumePoint } from './resumeCreation';
import { apiFetch } from './apiFetch';

function progress(project: Project) {
  if (project.kind === 'product') return project.busy ? '正在分析产品资料' : project.analysis_confirmed ? '产品卖点已确认，可继续策划' : project.documents.analysis ? '卖点待确认' : '等待分析产品资料';
  if (project.images.length) {
    const done = project.images.filter(image => image.status === 'succeeded').length;
    const pending = project.images.filter(image => ['queued', 'running'].includes(image.status)).length;
    const failed = project.images.filter(image => ['failed', 'unknown', 'cancelled'].includes(image.status)).length;
    return `已生成 ${done} / ${project.images.length} 张${pending ? ` · ${pending} 张处理中` : ''}${failed ? ` · ${failed} 张需关注` : ''}`;
  }
  if (project.busy) return 'AI 正在处理，点击查看进度';
  if (project.documents.prompts?.confirmed_at) return '提示词已确认，等待制作图片';
  if (project.documents.prompts) return '提示词待确认';
  if (project.documents.brief?.confirmed_at) return '图需已确认，继续编写提示词';
  return project.documents.brief ? '图需待确认' : '等待编写图需';
}

export default function ResumeCreationCard() {
  const { user } = useAuth();
  const [point, setPoint] = useState<ResumePoint | null>(() => readResume(user.id));
  const [detail, setDetail] = useState('');
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let active = true; const controller = new AbortController();
    let timer: number;
    async function load() {
      try {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]);
        let saved = readResume(user.id);
        if (!saved) {
          const projects = await projectRequest<Project[]>('', 'GET', undefined, signal);
          const project = projects.filter(p => p.can_edit && (p.busy || (p.kind === 'product' ? !p.analysis_confirmed : !p.images.length || p.images.some(image => image.status !== 'succeeded'))))
            .sort((a, b) => Number(b.busy) - Number(a.busy) || b.updated_at.localeCompare(a.updated_at))[0];
          if (project && active) {
            const page = project.kind === 'product' ? 'products' : project.images.length || project.stage === 'images' ? 'studio' : 'planning';
            rememberCreation(user.id, `#/${page}?project=${project.id}`, project.title);
            saved = readResume(user.id);
          }
        }
        if (!active) return;
        setPoint(saved);
        const id = new URLSearchParams(saved?.route.split('?')[1]).get('project');
        if (id) {
          // Keep the original saved stage while showing fresh task status.
          const response = await apiFetch('/api/creation-projects/' + encodeURIComponent(id), { signal, cache: 'no-store' });
          if (!active) return;
          if (response.status === 404 || response.status === 403) { setMissing(true); setDetail('该记录已删除或当前账号无权访问，可从方案列表选择其他创作。'); return; }
          if (!response.ok) throw new Error();
          const project = await response.json() as Project;
          if (active) { setPoint(saved ? { ...saved, title: project.title } : null); setDetail(progress(project)); setMissing(false); }
        } else setDetail('打开原任务，查看生成进度和已保存结果');
      } catch { if (active) setDetail('暂时无法更新进度，仍可打开上次保存的位置'); }
      finally { if (active) timer = window.setTimeout(load, 15000); }
    }
    void load();
    return () => { active = false; controller.abort(); window.clearTimeout(timer); };
  }, [user.id]);
  return <section className="resume-creation" aria-label="继续上次创作">
    <div className="resume-copy"><span className="resume-kicker">继续上次创作</span><h2>{point?.title || '从这里接着做'}</h2><p>{point ? `${point.label} · ${detail || '正在读取进度…'}` : '打开产品或策划方案后，这里会记住你的位置。'}</p><small>保留已保存内容和已提交任务；未保存的输入和未上传文件请先保存。</small></div>
    <div className="resume-actions">{point && !missing ? <><a className="button-primary" href={point.route}>继续创作 →</a><small>上次打开：{new Date(point.updatedAt).toLocaleString('zh-CN')}</small></> : <a className="button-secondary" href="#/planning">查看策划方案</a>}</div>
  </section>;
}
