import AuthGate, { useAuth } from './AuthGate';
import MemberManagement from './MemberManagement';
import ModelSettingsPage from './ModelSettingsPage';
import { useEffect, useRef, useState } from 'react';
import ImageCreation from './ImageCreation';
import { ProductAnalysisPage, PlanningPage } from './WorkflowPages';
import ArtworkLibrary from './ArtworkLibrary';
import ImageRevision from './ImageRevision';
import SkillLibrary from './SkillLibrary';
import Workspace from './Workspace';
import WorkflowCases from './WorkflowCases';
import ExperienceLibrary from './ExperienceLibrary';
import TeamSharing from './TeamSharing';
import { CreationSkillProvider } from './CreationSkillContext';
import { rememberCreation } from './resumeCreation';
import { useStudioMotion } from './useStudioMotion';
import { saveWorkspaceScroll, useWorkspaceScroll } from './useWorkspaceView';

const pages = [
  { id: 'workspace', href: '#/', title: '我的工作台' },
  { id: 'products', href: '#/products', title: '产品资料' },
  { id: 'planning', href: '#/planning', title: '全部图片策划' },
  { id: 'studio', href: '#/studio', title: '图片创作' },
  { id: 'library', href: '#/library', title: '生成记录' },
  { id: 'showcases', href: '#/showcases', title: '完整案例' },
  { id: 'learning', href: '#/learning', title: '作图经验' },
  { id: 'team', href: '#/team', title: '团队共享' },
  { id: 'skills', href: '#/skills', title: '技能库' },
  { id: 'members', href: '#/members', title: '成员管理' },
  { id: 'settings', href: '#/settings', title: '个人模型配置' },
] as const;
const navigationGroups = [
  { title: '创作空间', ids: ['workspace', 'products', 'planning', 'studio', 'library'] },
  { title: '团队与积累', ids: ['showcases', 'learning', 'team', 'skills'] },
  { title: '设置', ids: ['settings', 'members'] },
];
const navigationIcons: Record<string, string> = {
  workspace: 'M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z',
  products: 'M12 3 3 8l9 5 9-5-9-5Zm-9 5v9l9 5 9-5V8M12 13v9M7.5 5.5l9 5',
  planning: 'M8 5H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-3M9 3h6v4H9ZM8 12h8M8 16h5',
  studio: 'm15 3 6 6M4 20l4-1L21 6l-3-3L5 16l-1 4ZM4 4v4M2 6h4M17 16v6M14 19h6',
  library: 'M4 3h16v14H4ZM1 7v14h15M7 13l4-4 3 3 2-2 4 4M8 6h.01',
  showcases: 'M4 4h16v16H4ZM4 10h16M10 10v10',
  learning: 'M12 5c-3-2-7-2-10 0v15c3-2 7-2 10 0 3-2 7-2 10 0V5c-3-2-7-2-10 0ZM12 5v15',
  team: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  skills: 'm12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3 3-6Z',
  settings: 'M4 7h16M4 17h16M9 4v6M15 14v6',
  members: 'M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM2 21v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2M20 8v6M17 11h6',
};
function NavigationIcon({ name }: { name: string }) {
  return <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={navigationIcons[name]} /></svg>;
}
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
  if (hash === '#/learning') return 'learning';
  if (hash === '#/team') return 'team';
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
  const previousRoute=useRef(route);
  useWorkspaceScroll(user.id,route);
  useStudioMotion(route);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    if (!menuOpen) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setMenuOpen(false); document.getElementById('navigation-toggle')?.focus(); }
    };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [menuOpen]);
  useEffect(() => { rememberCreation(user.id, route); }, [user.id, route]);
  useEffect(() => {
    const navigate = () => {
      const route = currentRoute();
      if(previousRoute.current!==route)saveWorkspaceScroll(user.id,previousRoute.current);
      previousRoute.current=route;
      if (route !== window.location.hash) window.history.replaceState(null, '', route);
      setPage(currentPage()); setRoute(route); setMenuOpen(false);
    };
    navigate();
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, [user.id]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace" onClick={event => { event.preventDefault(); document.getElementById('workspace')?.focus(); }}>跳到主要内容</a>
      <aside className={`sidebar ${menuOpen ? 'navigation-open' : ''}`}>
        <div className="sidebar-brand-row">
        <a className="brand" href="#/" aria-label="Skill Forge 首页">
          <span className="brand-icon">SF</span><span>Skill Forge<small>电商图片工作台</small></span>
        </a>
        <button id="navigation-toggle" className="navigation-toggle" type="button" aria-label={menuOpen ? '收起导航' : '展开导航'} aria-expanded={menuOpen} aria-controls="workspace-navigation" onClick={() => setMenuOpen(open => !open)}><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d={menuOpen ? 'm6 6 12 12M6 18 18 6' : 'M4 6h16M4 12h16M4 18h16'} /></svg></button>
        </div>
        <nav id="workspace-navigation" aria-label="工作空间导航">{navigationGroups.map(group => <div className="navigation-group" key={group.title}><div className="navigation-label">{group.title}</div>{pages.filter(item => group.ids.includes(item.id) && (item.id !== 'members' || user.role === 'admin')).map(item => { const active = page === item.id || (page === 'edit' && item.id === 'studio'); return <a key={item.id} className={`nav-link ${active ? 'nav-active' : ''}`} aria-current={active ? 'page' : undefined} href={item.href} onClick={() => setMenuOpen(false)}><NavigationIcon name={item.id} /><span>{item.title}</span>{active && <span className="nav-active-dot" />}</a>; })}</div>)}</nav>
        <div className="sidebar-note"><span className="note-label">MAKE SOMETHING GREAT</span><p>让每一次创作，<br />成为下一次的灵感。</p><a href="#/team">探索团队作品 <span aria-hidden="true">↗</span></a></div>
      </aside>

      <div className="main-shell">
        <header className="topbar"><div className="breadcrumb"><span>工作空间</span><span aria-hidden="true">/</span><strong>{page === 'edit' ? '图片创作 · 继续修改' : pages.find((item) => item.id === page)?.title}</strong></div><div className="account-controls"><span className="account-avatar" aria-hidden="true">{(user.display_name || user.username).slice(0, 1)}</span><span className="account-name">{user.display_name}<small>{user.role==='admin'?'管理员':'成员'}</small></span><button type="button" onClick={changePassword}>修改密码</button><button type="button" onClick={logout}>退出</button></div></header>
        <main id="workspace" tabIndex={-1}>
          {page === 'members' && <MemberManagement />}
          {page === 'studio' && <CreationSkillProvider><ImageCreation route={route} /></CreationSkillProvider>}
          {page === 'settings' && <ModelSettingsPage />}
          {page === 'planning' && <CreationSkillProvider key={route}><PlanningPage route={route} /></CreationSkillProvider>}
          {page === 'products' && <CreationSkillProvider key={route}><ProductAnalysisPage route={route} /></CreationSkillProvider>}
          {page === 'library' && <ArtworkLibrary key={route} />}
          {page === 'showcases' && <WorkflowCases key={route} route={route} />}
          {page === 'learning' && <ExperienceLibrary />}
          {page === 'team' && <TeamSharing key={route} route={route} />}
          {page === 'edit' && <CreationSkillProvider key={route}><ImageRevision /></CreationSkillProvider>}
          {page === 'skills' && <SkillLibrary />}
          {page === 'workspace' && <Workspace />}
          <footer className="page-footer">Skill Forge · 图片制作与经验复用<span>制作规范 / 图片创作 / 团队经验</span></footer>
        </main>
      </div>
    </div>
  );
}
