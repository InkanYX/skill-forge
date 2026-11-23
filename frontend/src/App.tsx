import AuthGate, { useAuth } from './AuthGate';
import MemberManagement from './MemberManagement';
import ModelSettingsPage from './ModelSettingsPage';
import { useEffect, useState } from 'react';
import ImageCreation from './ImageCreation';
import TemplateLibrary from './TemplateLibrary';
import ProductLibrary from './ProductLibrary';
import ArtworkLibrary from './ArtworkLibrary';
import ImageRevision from './ImageRevision';
import ImageSetStudio from './ImageSetStudio';
import SkillLibrary from './SkillLibrary';
import Workspace from './Workspace';

const pages = [
  { id: 'workspace', href: '#/', title: '我的工作台' },
  { id: 'studio', href: '#/studio', title: '图片创作' },
  { id: 'library', href: '#/library', title: '生成记录' },
  { id: 'products', href: '#/products', title: '产品资料' },
  { id: 'templates', href: '#/templates', title: '创作模板' },
  { id: 'members', href: '#/members', title: '成员管理' },
  { id: 'settings', href: '#/settings', title: '个人模型配置' },
] as const;
function currentRoute() {
  const hash = window.location.hash;
  const [path, query] = hash.split('?');
  if (path === '#/cases') return '#/library?notes=1';
  if (path === '#/sets') {
    const params = new URLSearchParams(query || '');
    if (!params.get('set')) { params.set('mode', 'set'); return `#/studio?${params}`; }
  }
  return hash;
}
function currentPage() {
  const hash = currentRoute().split('?')[0];
  if (hash === '#/members') return 'members';
  if (hash === '#/templates') return 'templates';
  if (hash === '#/products') return 'products';
  if (hash === '#/library') return 'library';
  if (hash === '#/edit') return 'edit';
  if (hash === '#/sets') return 'sets';
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
        <nav aria-label="工作空间导航">{pages.filter(item=>item.id!=='members'||user.role==='admin').map((item) => <a key={item.id} className={`nav-link ${(page === item.id || ((page === 'edit' || page === 'sets') && item.id === 'studio') || (page === 'skills' && item.id === 'templates')) ? 'nav-active' : ''}`} aria-current={(page === item.id || ((page === 'edit' || page === 'sets') && item.id === 'studio') || (page === 'skills' && item.id === 'templates')) ? 'page' : undefined} href={item.href}>{item.title}</a>)}</nav>
        <div className="sidebar-note"><span className="note-label">创作与经验</span><p>从产品素材到可复用的制作经验。</p><small>产品 · 模板 · Skill · 作品</small></div>
      </aside>

      <div className="main-shell">
        <header className="topbar"><span>工作空间 / {page === 'edit' ? '图片创作 / 继续修改' : page === 'sets' ? '图片创作 / 成套制作' : page === 'skills' ? '创作模板 / Skill 管理' : pages.find((item) => item.id === page)?.title}</span><div className="account-controls"><span>{user.display_name}<small>{user.role==='admin'?'管理员':'成员'}</small></span><button type="button" onClick={changePassword}>修改密码</button><button type="button" onClick={logout}>退出</button></div></header>
        <main id="workspace">
          {page === 'members' && <MemberManagement />}
          {page === 'studio' && <ImageCreation route={route} />}
          {page === 'settings' && <ModelSettingsPage />}
          {page === 'templates' && <TemplateLibrary />}
          {page === 'products' && <ProductLibrary />}
          {page === 'library' && <ArtworkLibrary key={route} />}
          {page === 'edit' && <ImageRevision key={route} />}
          {page === 'sets' && <ImageSetStudio key={route} />}
          {page === 'skills' && <SkillLibrary />}
          {page === 'workspace' && <Workspace />}
          <footer className="page-footer">Skill Forge · 图片制作与经验复用<span>图片创作 / 参考图编辑 / 本机开发模式</span></footer>
        </main>
      </div>
    </div>
  );
}
