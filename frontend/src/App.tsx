import AuthGate, { useAuth } from './AuthGate';
import MemberManagement from './MemberManagement';
import ModelSettingsPage from './ModelSettingsPage';
import { useEffect, useState } from 'react';
import ImageCreation from './ImageCreation';
import { ProductAnalysisPage, PlanningPage } from './WorkflowPages';
import ArtworkLibrary from './ArtworkLibrary';
import ImageRevision from './ImageRevision';
import SkillLibrary from './SkillLibrary';
import Workspace from './Workspace';
import WorkflowCases from './WorkflowCases';
import { CreationSkillProvider } from './CreationSkillContext';

const pages = [
  { id: 'workspace', href: '#/', title: '我的工作台' },
  { id: 'products', href: '#/products', title: '产品分析' },
  { id: 'planning', href: '#/planning', title: '图片策划' },
  { id: 'studio', href: '#/studio', title: '图片创作' },
  { id: 'library', href: '#/library', title: '生成记录' },
  { id: 'showcases', href: '#/showcases', title: '完整案例' },
  { id: 'skills', href: '#/skills', title: '技能库' },
  { id: 'members', href: '#/members', title: '成员管理' },
  { id: 'settings', href: '#/settings', title: '个人模型配置' },
] as const;
function currentRoute() {
  const hash = window.location.hash;
  const [path, query] = hash.split('?');
  if (path === '#/cases') return '#/library?notes=1';
  if (path === '#/templates') return '#/planning?view=templates';
  if (path === '#/agent') {
    const params = new URLSearchParams(query || '');
    params.set('mode', 'skill');
    return `#/studio?${params}`;
  }
  if (path === '#/sets') {
    const params = new URLSearchParams(query || '');
    return params.get('set') ? '#/library?task=' + encodeURIComponent(params.get('set')!) : '#/planning?new=1';
  }
  return hash;
}
function currentPage() {
  const hash = currentRoute().split('?')[0];
  if (hash === '#/members') return 'members';
  if (hash === '#/planning') return 'planning';
  if (hash === '#/products') return 'products';
  if (hash === '#/library') return 'library';
  if (hash === '#/showcases') return 'showcases';
  if (hash === '#/edit') return 'edit';
  if (hash === '#/skills') return 'skills';
  return hash === '#/studio' || hash === '#image-studio-heading' ? 'studio'
    : hash === '#/settings' || hash === '#model-settings-heading' ? 'settings' : 'workspace';
}

export default function App(){return <AuthGate><WorkspaceApp /></AuthGate>;}
function WorkspaceApp() {
  const {user,logout,changePassword}=useAuth();
  const [page, setPage] = useState(currentPage);
  const [route, setRoute] = useState(currentRoute);
  useEffect(() => {
    const navigate = () => {
      const route = currentRoute();
      if (route !== window.location.hash) window.history.replaceState(null, '', route);
      setPage(currentPage()); setRoute(route); window.scrollTo(0, 0);
    };
    navigate();
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#/" aria-label="Skill Forge 首页">
          <span className="brand-icon">SF</span><span>Skill Forge<small>电商图片工作台</small></span>
        </a>
        <div className="workspace-label">团队工作空间</div>
        <nav aria-label="工作空间导航">{pages.filter(item=>item.id!=='members'||user.role==='admin').map((item) => { const active = page === item.id || (page === 'edit' && item.id === 'studio'); return <a key={item.id} className={`nav-link ${active ? 'nav-active' : ''}`} aria-current={active ? 'page' : undefined} href={item.href}>{item.title}</a>; })}</nav>
        <div className="sidebar-note"><span className="note-label">创作与经验</span><p>从产品素材到可复用的制作经验。</p><small>产品 · 模板 · Skill · 作品</small></div>
      </aside>

      <div className="main-shell">
        <header className="topbar"><span>工作空间 / {page === 'edit' ? '图片创作 / 继续修改' : pages.find((item) => item.id === page)?.title}</span><div className="account-controls"><span>{user.display_name}<small>{user.role==='admin'?'管理员':'成员'}</small></span><button type="button" onClick={changePassword}>修改密码</button><button type="button" onClick={logout}>退出</button></div></header>
        <main id="workspace">
          {page === 'members' && <MemberManagement />}
          {page === 'studio' && <CreationSkillProvider><ImageCreation route={route} /></CreationSkillProvider>}
          {page === 'settings' && <ModelSettingsPage />}
          {page === 'planning' && <CreationSkillProvider key={route}><PlanningPage route={route} /></CreationSkillProvider>}
          {page === 'products' && <CreationSkillProvider key={route}><ProductAnalysisPage route={route} /></CreationSkillProvider>}
          {page === 'library' && <ArtworkLibrary key={route} />}
          {page === 'showcases' && <WorkflowCases key={route} route={route} />}
          {page === 'edit' && <CreationSkillProvider key={route}><ImageRevision /></CreationSkillProvider>}
          {page === 'skills' && <SkillLibrary />}
          {page === 'workspace' && <Workspace />}
          <footer className="page-footer">Skill Forge · 图片制作与经验复用<span>制作规范 / 图片创作 / 团队经验</span></footer>
        </main>
      </div>
    </div>
  );
}
