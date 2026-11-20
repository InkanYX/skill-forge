import { useEffect, useRef, useState } from 'react';
import { fetchHealth, fetchStorage, type HealthResponse, type StorageStatus } from './api';
import ModelSettings from './ModelSettings';
import ImageStudio from './ImageStudio';
import TemplateLibrary from './TemplateLibrary';
import CaseLibrary from './CaseLibrary';

type Connection =
  | { state: 'loading' }
  | { state: 'online'; health: HealthResponse }
  | { state: 'offline'; message: string };

const pages = [
  { id: 'workspace', href: '#/', title: '我的工作台' },
  { id: 'studio', href: '#/studio', title: '图片创作' },
  { id: 'templates', href: '#/templates', title: '创作模板' },
  { id: 'cases', href: '#/cases', title: '案例库' },
  { id: 'settings', href: '#/settings', title: '个人模型配置' },
] as const;
function currentPage() {
  const hash = window.location.hash.split('?')[0];
  if (hash === '#/templates') return 'templates';
  if (hash === '#/cases') return 'cases';
  return hash === '#/studio' || hash === '#image-studio-heading' ? 'studio'
    : hash === '#/settings' || hash === '#model-settings-heading' ? 'settings' : 'workspace';
}

export default function App() {
  const [page, setPage] = useState(currentPage);
  const [connection, setConnection] = useState<Connection>({ state: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [storage, setStorage] = useState<StorageStatus>();
  const [storageError, setStorageError] = useState('');
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const navigate = () => { setPage(currentPage()); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    controllerRef.current = controller;
    let active = true;
    let timedOut = false;
    setConnection({ state: 'loading' });
    setStorage(undefined); setStorageError('');
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 8000);
    fetchHealth(controller.signal)
      .then((health) => { if (active) setConnection({ state: 'online', health }); })
      .catch((error: unknown) => {
        if (!active) return;
        setConnection({ state: 'offline', message: timedOut ? '连接超时，请检查后端是否启动。' :
          error instanceof Error ? error.message : '暂时无法连接后端' });
      })
      .finally(() => window.clearTimeout(timeout));
    const storageController = new AbortController();
    const storageTimeout = window.setTimeout(() => storageController.abort(), 8000);
    fetchStorage(storageController.signal).then((value) => { if (active) setStorage(value); })
      .catch(() => { if (active) setStorageError('无法读取状态，请检查后端是否已更新'); })
      .finally(() => window.clearTimeout(storageTimeout));
    return () => { active = false; window.clearTimeout(timeout); window.clearTimeout(storageTimeout); controller.abort(); storageController.abort(); };
  }, [attempt]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#/" aria-label="Skill Forge 首页">
          <span className="brand-icon">SF</span><span>Skill Forge<small>电商图片工作台</small></span>
        </a>
        <div className="workspace-label">个人工作空间</div>
        <nav aria-label="工作空间导航">{pages.map((item) => <a key={item.id} className={`nav-link ${page === item.id ? 'nav-active' : ''}`} aria-current={page === item.id ? 'page' : undefined} href={item.href}>{item.title}</a>)}</nav>
        <div className="sidebar-note"><span className="note-label">开发阶段 · 03</span><p>从产品素材到可复用的制作经验。</p><small>数据库持久化已接入</small></div>
      </aside>

      <div className="main-shell">
        <header className="topbar"><span>工作空间 / {pages.find((item) => item.id === page)?.title}</span><span className="environment">本机开发环境</span></header>
        <main id="workspace">
          {page === 'studio' && <ImageStudio />}
          {page === 'settings' && <ModelSettings />}
          {page === 'templates' && <TemplateLibrary />}
          {page === 'cases' && <CaseLibrary />}
          {page === 'workspace' && <>
          <div className="page-heading"><div><p className="eyebrow">YOUR CREATIVE WORKSPACE</p><h1>把每一次制作，变成下一次的经验。</h1><p className="subtitle">围绕车棚、凉棚产品，逐步建立素材、模板、图片与案例的完整联系。</p></div><span className="version-badge">v0.1.0</span></div>

          <div className="workspace-shortcuts"><a className="button-primary" href="#/studio">开始图片创作</a><a className="button-secondary" href="#/settings">管理模型配置</a></div>

          <section className="connection-card" aria-labelledby="connection-heading">
            <div className="connection-top"><div><span className="section-label">工程连通检查</span><h2 id="connection-heading">你的工作台已就位</h2></div><span className={`status status-${connection.state}`} role="status">{connection.state === 'loading' ? '正在连接后端' : connection.state === 'online' ? '后端连接正常' : '后端未连接'}</span></div>
            <p className="connection-description">服务存活与数据库就绪状态分别检查。模型密钥始终加密保存，数据库不可用时不会自动切回文件存储。</p>
            <div className="service-grid">
              <div><span>前端应用</span><strong>React + TypeScript</strong><small>浏览器页面已加载</small></div>
              <div><span>业务接口</span><strong>Python + FastAPI</strong><small>{connection.state === 'online' ? `${connection.health.service} · ${connection.health.version}` : connection.state === 'loading' ? '等待健康检查响应…' : '请确认 8000 端口上的服务已启动'}</small></div>
              <div><span>配置存储</span><strong>{storage ? storage.storage === 'postgresql' ? storage.status === 'ready' ? 'PostgreSQL · 已连接' : 'PostgreSQL · 未就绪' : '本机文件存储' : storageError ? '检查失败' : '正在检查…'}</strong><small>{storage?.message || storageError || '读取存储状态'}</small></div>
            </div>
            <div className="connection-footer"><p aria-live="polite">{connection.state === 'online' ? `后端响应时间：${new Date(connection.health.timestamp).toLocaleString('zh-CN')}` : connection.state === 'offline' ? connection.message : '正在请求 /api/health'}</p><button type="button" disabled={connection.state === 'loading'} onClick={() => { controllerRef.current?.abort(); setAttempt((value) => value + 1); }}>重新检查</button></div>
          </section>

          <section className="next-section" aria-labelledby="next-heading"><div className="section-heading"><h2 id="next-heading">接下来，一步步跑通制作流程</h2><span>后续开发内容</span></div><div className="roadmap">
            <article><span className="step-icon">素材</span><h3>建立产品资料</h3><p>关联 SKU、实拍与尺寸，让每次制作都有准确的产品依据。</p><span className="planned">待实现</span></article>
            <article><span className="step-icon">模板</span><h3>沉淀生图方法</h3><p>配置提示词、自然语言 Skill 和参考案例，复用有效经验。</p><a className="button-secondary" href="#/templates">管理创作模板</a></article>
            <article><span className="step-icon">作品</span><h3>完成制作与交付</h3><p>生成、比较、修改和导出图片，保留完整制作记录。</p><span className="planned">待实现</span></article>
          </div></section>
          </>}
          <footer className="page-footer">Skill Forge · 图片制作与经验复用<span>图片创作 / 参考图编辑 / 本机开发模式</span></footer>
        </main>
      </div>
    </div>
  );
}
