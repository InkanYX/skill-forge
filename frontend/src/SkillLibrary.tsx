import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useAuth } from './AuthGate';
import { formatTaskTime } from './imageTaskApi';
import {
  activateVersion, confirmPackage, choosePackageEntry, fileUrl, forkPackage, importTextSkill, listFiles, listPackages, listVersions,
  readFile, readResource, uploadPackage,
  type ImportPreview, type SkillFile, type SkillPackage, type SkillText, type SkillVersion,
} from './skillPackageApi';

const kindLabels: Record<string, string> = {
  entry: '入口', reference: '规范', template: '模板', asset: '素材', license: '许可',
  script: '脚本（只存档）', execution: '执行说明', other: '其他',
};

function bytes(value: number) {
  return value > 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`;
}

const versionLabel = (value: string) => value === '0.0.0' ? '未标注' : value;

function sourceLabel(source: string, full = false) {
  if (source === 'builtin') return full ? '应用内置' : '内置';
  if (source === 'forked') return full ? '复制副本' : '副本';
  if (source === 'text') return full ? '文本技能' : '文本';
  return '导入';
}

function scopeLabel(item: SkillPackage, userId: string) {
  if (item.source === 'builtin') return '内置 · 全局';
  if (item.owner_id && item.owner_id === userId) return '个人 · 仅自己';
  return '个人 · 其他成员';
}

export default function SkillLibrary() {
  const { user } = useAuth();
  const importDialog = useRef<HTMLDialogElement>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [items, setItems] = useState<SkillPackage[]>([]);
  const [selected, setSelected] = useState<SkillPackage>();
  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const [viewing, setViewing] = useState<SkillVersion>();
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [resources, setResources] = useState<SkillFile[]>([]);
  const [file, setFile] = useState<SkillText>();
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [preview, setPreview] = useState<ImportPreview>();
  const [archive, setArchive] = useState<File>();
  const [folder, setFolder] = useState<File[]>([]);
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<Record<string, {name: string; description: string}>>({});
  const [importing, setImporting] = useState(false);
  const [format, setFormat] = useState<'zip' | 'folder' | 'text'>('zip');
  const [textName, setTextName] = useState('');
  const [textDescription, setTextDescription] = useState('');
  const [textContent, setTextContent] = useState('');
  const [entryPath, setEntryPath] = useState('');

  async function load(preferId?: string) {
    setLoading(true);
    try {
      const value = await listPackages();
      setItems(value);
      const next = value.find(item => item.id === (preferId || selected?.id)) || value[0];
      setSelected(next);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '技能库读取失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => {
    const dialog = importDialog.current;
    if (!dialog) return;
    if (importOpen) {
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [importOpen]);
  useEffect(() => {
    if (!selected) { setVersions([]); setFiles([]); setResources([]); setViewing(undefined); setFile(undefined); return; }
    let active = true;
    setFile(undefined);
    setViewing(selected.current_version || undefined);
    Promise.all([listVersions(selected.id), selected.current_version ? listFiles(selected.id, selected.current_version.id) : Promise.resolve(undefined)])
      .then(([value, detail]) => {
        if (!active) return;
        setVersions(value);
        setFiles(detail?.files || []);
        setResources(detail?.resources || []);
      })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : '技能详情读取失败'); });
    return () => { active = false; };
  }, [selected]);

  async function viewVersion(item: SkillVersion) {
    if (!selected) return;
    setBusy(true); setFile(undefined); setViewing(item);
    try { const detail = await listFiles(selected.id, item.id); setFiles(detail.files); setResources(detail.resources || []); setNotice(`正在查看版本 ${item.version_label} 的文件。`); }
    catch (err) { setError(err instanceof Error ? err.message : '版本文件读取失败'); }
    finally { setBusy(false); }
  }

  async function openFile(item: SkillFile) {
    if (!selected || !viewing || !item.is_text) return;
    setBusy(true);
    try { setFile(await readFile(selected.id, viewing.id, item.path)); }
    catch (err) { setError(err instanceof Error ? err.message : '文件读取失败'); }
    finally { setBusy(false); }
  }

  async function activate(item: SkillVersion) {
    if (!selected || !window.confirm(`启用版本 ${item.version_label}？只有新任务会使用该版本，历史任务保持不变。`)) return;
    setBusy(true);
    try {
      const value = await activateVersion(selected.id, item.id);
      setNotice(`已启用版本 ${item.version_label}。新任务将使用此版本，历史任务与旧版本不受影响。`);
      await load(value.id);
    } catch (err) { setError(err instanceof Error ? err.message : '启用失败'); }
    finally { setBusy(false); }
  }

  async function fork() {
    if (!selected) return;
    setBusy(true);
    try {
      const value = await forkPackage(selected.id);
      setNotice(`已复制为「${value.name}」。副本是独立的只读技能包，可继续导入新版本。`);
      await load(value.id);
    } catch (err) { setError(err instanceof Error ? err.message : '复制失败'); }
    finally { setBusy(false); }
  }

  function pickArchive(value?: File) { setArchive(value); setFolder([]); setPreview(undefined); setError(''); setEntryPath(''); }
  function pickFolder(list: FileList | null) {
    setFolder(list ? Array.from(list) : []);
    setArchive(undefined); setPreview(undefined); setError(''); setEntryPath('');
  }

  function pickFormat(value: 'zip' | 'folder' | 'text') {
    if (value === format) return;
    setFormat(value);
    setArchive(undefined); setFolder([]); setPreview(undefined); setError(''); setEntryPath('');
  }

  async function readTextFile(file?: File) {
    if (!file) return;
    if (!/\.(md|txt)$/i.test(file.name) || file.size > 100 * 1024) {
      setError('请选择 100 KB 以内的 Markdown 或 TXT 文件。'); return;
    }
    try {
      const text = await file.text();
      if (text.length > 20000) { setError('文本技能不能超过 20000 字符。'); return; }
      setTextContent(text);
      if (!textName.trim()) setTextName(file.name.replace(/\.(md|txt)$/i, '').slice(0, 200));
      setError('');
    } catch { setError('文件读取失败，请重新选择。'); }
  }

  async function saveTextSkill(event: FormEvent) {
    event.preventDefault();
    if (busy || importing) return;
    const name = textName.trim();
    const content = textContent.trim();
    if (!name) { setError('请填写技能名称。'); return; }
    if (!content) { setError('请填写技能内容，或从 Markdown / TXT 文件导入。'); return; }
    if (content.length > 20000) { setError('文本技能不能超过 20000 字符。'); return; }
    setBusy(true); setError('');
    try {
      const value = await importTextSkill({ name, description: textDescription.trim(), content });
      const labels: Record<string, string> = {
        created: '已创建并启用', version_added: '已新增版本（未启用）', unchanged: '内容未变化',
      };
      setNotice(`文本技能「${value.name}」${labels[value.status] || value.status}。${value.status === 'version_added' ? '请在详情中手动启用新版本。' : ''}`);
      setTextName(''); setTextDescription(''); setTextContent('');
      setImportOpen(false);
      await load(value.id);
    } catch (err) { setError(err instanceof Error ? err.message : '文本技能保存失败'); }
    finally { setBusy(false); }
  }

  function openImport() {
    setError(''); setNotice(''); setImportOpen(true);
  }

  function closeImport() {
    if (importing || busy) return;
    setImportOpen(false);
    setPreview(undefined); setArchive(undefined); setFolder([]); setEntryPath('');
  }

  async function inspect(event?: FormEvent) {
    event?.preventDefault();
    if (busy) return;
    if (archive && archive.size > 20 * 1024 * 1024) {
      setError('压缩包不能超过 20 MB。'); return;
    }
    if (format === 'zip' && !archive) {
      setError('请选择一个 zip 压缩包。'); return;
    }
    if (format === 'folder' && !folder.length) {
      setError('请选择一个技能文件夹。'); return;
    }
    setBusy(true); setError(''); setPreview(undefined);
    try {
      const form = new FormData();
      if (format === 'zip' && archive) form.append('archive', archive);
      else {
        form.append('paths', JSON.stringify(folder.map(item => item.webkitRelativePath || item.name)));
        folder.forEach(item => form.append('files', item, item.name));
      }
      if (entryPath.trim()) form.set('entry_path', entryPath.trim());
      const value = await uploadPackage(form);
      setPreview(value);
      setChecks(Object.fromEntries(value.skills.map(item => [item.root, !item.same_content && !item.reserved && !item.resource_only])));
      setDrafts(Object.fromEntries(value.skills.map(item => [item.root, {name: item.name, description: item.description}])));
    } catch (err) { setError(err instanceof Error ? err.message : '导入检查失败'); }
    finally { setBusy(false); }
  }

  async function confirm() {
    if (!preview) return;
    const selections = preview.skills
      .filter(item => checks[item.root] && !!drafts[item.root]?.name.trim() &&
        (!item.reserved || drafts[item.root].name.trim() !== item.name))
      .map(item => ({ name: item.name, root: item.root, import_name: drafts[item.root]?.name.trim() || item.name,
                     description: drafts[item.root]?.description || '', compile_level: 'core' as const }));
    if (!selections.length) { setError('请至少选择一个技能。'); return; }
    if (new Set(selections.map(item => item.import_name)).size !== selections.length) {
      setError('本次有重复的技能名称，请在识别结果中区分名称。'); return;
    }
    setImporting(true); setError('');
    try {
      const result = await confirmPackage(preview.upload_id, selections);
      const label: Record<string, string> = { created: '新建', version_added: '新增版本（未启用）', unchanged: '内容未变化' };
      setNotice(result.map(item => `${item.name}：${label[item.status]}`).join('；') + (result.some(item => item.status === 'version_added') ? '。新版本需在详情中手动启用。' : ''));
      setPreview(undefined); setArchive(undefined); setFolder([]);
      setImportOpen(false);
      await load(selected?.id);
    } catch (err) { setError(err instanceof Error ? err.message : '导入失败'); }
    finally { setImporting(false); }
  }

  async function resolveEntry() {
    if (!preview || !entryPath || busy) return;
    setBusy(true); setError('');
    try {
      const value = await choosePackageEntry(preview.upload_id, entryPath);
      setPreview(value);
      setChecks(Object.fromEntries(value.skills.map(item => [item.root, !item.same_content && !item.reserved && !item.resource_only])));
      setDrafts(Object.fromEntries(value.skills.map(item => [item.root, {name: item.name, description: item.description}])));
    } catch (err) { setError(err instanceof Error ? err.message : '说明文件读取失败'); }
    finally { setBusy(false); }
  }

  const filtered = items.filter(item => `${item.name} ${item.description} ${item.source}`.toLowerCase().includes(search.toLowerCase()));
  const current = selected?.current_version;

  return <section>
    <div className="section-heading"><div><p className="eyebrow">IMMUTABLE SKILL PACKAGES</p><h2>技能库</h2></div>
      <div className="skill-heading-actions">
        <span>{items.length} 个技能包</span>
        <button type="button" className="button-primary" onClick={openImport}>＋ 新增技能包</button>
      </div>
    </div>
    <p className="settings-intro">技能包是只读的制作规范。支持完整技能包（zip / 文件夹）和单文件文本技能；内置技能包对所有账号共享，你创建的个人技能包只归你使用，管理员可只读排障。</p>
    <p className="form-footnote">所有登录用户都可以新增技能包。新版本导入后需在详情中手动启用；已开始或历史任务始终使用当时的版本。</p>

    <details className="skill-rules">
      <summary>导入说明与文件限制</summary>
      <ul>
        <li>支持 zip 压缩包、文件夹，或直接粘贴一份文本技能；压缩包不超过 20 MB、1000 个文件、单文件不超过 5 MB。</li>
        <li>优先识别 <code>SKILL.md</code>；也可指定其他 Markdown 入口。名称与用途可从标准文件头读取。</li>
        <li>文本技能会生成只读的 <code>SKILL.md</code>，最多 20000 字符；修改内容会作为新版本，不覆盖旧版本。</li>
        <li>同名个人技能会作为新版本导入，不会覆盖旧版本；导入完成后需手动启用。</li>
        <li>内置技能名保留，个人技能不能覆盖；需要定制时请使用「复制为副本」。</li>
        <li>个人技能包仅创建者可见、可启用并可用于 Agent；管理员可只读查看，不能代为启用。</li>
        <li>保留完整导入包及公共资源；AI 按需读取文本，脚本只存档不执行。</li>
        <li>不支持符号链接、<code>../</code> 路径或绝对路径；拒绝不安全压缩包。</li>
      </ul>
    </details>

    {!importOpen && error && <p className="feedback feedback-error" role="alert">{error}</p>}
    {notice && <p className="feedback feedback-success" role="status">{notice}</p>}

    <div className="settings-layout skill-layout">
      <aside className="config-list">
        <div className="form-field"><label htmlFor="skill-search">搜索技能包</label><input id="skill-search" value={search} onChange={e => setSearch(e.target.value)} placeholder="名称、说明或来源" /></div>
        {loading && <p className="empty-config">正在读取…</p>}
        {filtered.map(item => <button type="button" key={item.id} className={`config-item ${selected?.id === item.id ? 'config-item-active' : ''}`} onClick={() => { setSelected(item); setNotice(''); setError(''); }}>
          <strong>{item.name}</strong>
          <small>{item.current_version ? `当前版本 ${versionLabel(item.current_version.version_label)}` : '尚未启用版本'} · {item.version_count} 个版本</small>
          <small>{sourceLabel(item.source)} · {scopeLabel(item, user.id)} · 只读</small>
        </button>)}
        {!loading && !filtered.length && <p className="empty-config">还没有可见的技能包。可在下方导入一个。</p>}
      </aside>

      <div className="config-form">
        {selected ? <>
          <div className="section-heading"><div><h3>{selected.name}</h3><p className="settings-intro">{selected.description || '未填写说明'}</p></div><span className="skill-badge">{selected.is_readonly ? '只读' : '可编辑'}</span></div>
          <dl className="skill-meta">
            <div><dt>来源</dt><dd>{sourceLabel(selected.source, true)}</dd></div>
            <div><dt>归属</dt><dd>{scopeLabel(selected, user.id)}</dd></div>
            <div><dt>当前版本</dt><dd>{current ? `${versionLabel(current.version_label)}（执行时按需读取）` : '未启用'}</dd></div>
            <div><dt>文件</dt><dd>{current ? `${current.file_count} 个 · ${bytes(current.total_bytes)}` : '—'}</dd></div>
            <div><dt>更新时间</dt><dd>{formatTaskTime(selected.updated_at)}</dd></div>
          </dl>

          {current && <>
            <div className="skill-meta-actions">
              <button type="button" className="button-secondary" disabled={busy} onClick={() => void fork()}>复制为副本</button>
              <button type="button" className="button-secondary" disabled={busy} onClick={() => void viewVersion(current)}>查看当前版本文件</button>
            </div>

            <h3 className="skill-subhead">版本</h3>
            <div className="member-table-wrap"><table className="member-table"><thead><tr><th>版本</th><th>归档快照</th><th>文件</th><th>导入时间</th><th>状态</th></tr></thead><tbody>
              {versions.map(item => <tr key={item.id}>
                <td><strong>{versionLabel(item.version_label)}</strong><small>{item.compiled_chars.toLocaleString()} 字符</small></td>
                <td>{item.compile_level === 'full' ? '完整参考' : '核心'}</td>
                <td>{item.file_count}</td>
                <td>{formatTaskTime(item.created_at)}</td>
                <td>{item.id === current.id ? <span className="member-active">已启用</span> : selected.can_activate
                  ? <button type="button" className="button-secondary" disabled={busy} onClick={() => void activate(item)}>启用此版本</button>
                  : <span className="member-inactive">未启用</span>}</td>
              </tr>)}
            </tbody></table></div>

            <h3 className="skill-subhead">{viewing && viewing.id !== current.id ? `查看版本 ${viewing.version_label} 的文件` : '当前版本文件'}</h3>
            <p className="form-footnote">文件只读。文本可预览；脚本、压缩包等只能下载核对，系统不会执行。</p>
            <ul className="skill-file-list">{files.map(item => <li key={item.path}>
              <button type="button" className={`skill-file ${file?.path === item.path ? 'skill-file-active' : ''}`} disabled={!item.is_text || busy} onClick={() => void openFile(item)}>
                <span>{item.path}</span><small>{kindLabels[item.kind] || item.kind} · {bytes(item.size)}</small>
              </button>
              <a className="skill-file-download" href={fileUrl(selected.id, viewing?.id || current.id, item.path, true)} download>下载</a>
            </li>)}</ul>
            {resources.length > 0 && <details className="skill-input-details"><summary>同一导入包的公共资料与其他资源 · {resources.length} 个文件</summary><p className="form-footnote">保留原始相对路径，AI 可按需读取文本。脚本不执行。</p><ul className="skill-file-list">{resources.map(item => <li key={item.path}><button type="button" className="skill-file" disabled={!item.is_text || busy} onClick={async () => { if (!selected || !viewing) return; setBusy(true); try { setFile(await readResource(selected.id, viewing.id, item.path)); } catch (err) { setError(err instanceof Error ? err.message : '资源读取失败'); } finally { setBusy(false); } }}><span>{item.path}</span><small>{kindLabels[item.kind] || item.kind} · {bytes(item.size)}</small></button></li>)}</ul></details>}
            {file && <div className="skill-preview"><div className="section-heading"><strong>{file.path}</strong><span>{file.total_chars.toLocaleString()} 字符{file.truncated ? '（已截断）' : ''}</span></div><pre className="skill-content">{file.content}</pre></div>}
          </>}
        </> : <div className="product-welcome"><span className="step-icon">只读技能包</span><h3>导入一个技能包开始</h3><p>技能包包含 SKILL.md 与参考规范。导入后保留不可变版本，创作时按用途读取所需规则。</p></div>}
      </div>
    </div>

    <dialog ref={importDialog} className={`product-dialog skill-import-dialog${format === 'text' ? ' skill-import-dialog-text' : ''}`} aria-labelledby="skill-import-title" onCancel={event => { event.preventDefault(); closeImport(); }}>
      <div className="product-dialog-heading">
        <div><h2 id="skill-import-title">导入技能</h2><p className="settings-intro">直接上传现有文件，系统会识别技能和相关资料，再由你确认。</p></div>
        <button type="button" className="button-secondary" disabled={busy} onClick={closeImport} aria-label="关闭导入技能">关闭</button>
      </div>
      {error && <p className="feedback feedback-error" role="alert">{error}</p>}
      <form onSubmit={format === 'text' ? (event) => void saveTextSkill(event) : inspect}>
        <fieldset className="skill-import-format">
          <legend>导入格式</legend>
          <div className="skill-import-options skill-import-options-three">
            <label className={`skill-import-option${format === 'zip' ? ' skill-import-option-active' : ''}`}>
              <input type="radio" name="skill-import-format" value="zip" checked={format === 'zip'} onChange={() => pickFormat('zip')} />
              <strong>zip 压缩包</strong>
              <small>上传单个 .zip 文件</small>
            </label>
            <label className={`skill-import-option${format === 'folder' ? ' skill-import-option-active' : ''}`}>
              <input type="radio" name="skill-import-format" value="folder" checked={format === 'folder'} onChange={() => pickFormat('folder')} />
              <strong>文件夹</strong>
              <small>保留原有文件和目录</small>
            </label>
            <label className={`skill-import-option${format === 'text' ? ' skill-import-option-active' : ''}`}>
              <input type="radio" name="skill-import-format" value="text" checked={format === 'text'} onChange={() => pickFormat('text')} />
              <strong>文本技能</strong>
              <small>填写名称与正文，或导入 .md / .txt</small>
            </label>
          </div>
        </fieldset>

        <p className="skill-import-hint">{format === 'text' ? '粘贴制作要求，或从 Markdown / TXT 导入内容即可。' : '无需按固定目录重新打包。系统优先识别技能入口；说明文件不明确时，再让你选择。'}</p>
        <details className="skill-import-help"><summary>文件限制与保存方式</summary><p>{format === 'text' ? '正文最多 20000 字符；从文件导入时限 100 KB。' : 'ZIP 或文件夹总计最多 20 MB、1000 个文件，单个文件最多 5 MB。文字资料需为 UTF-8，支持 BOM。'}原始资料和历史版本会保留，包内脚本不会自动执行。</p></details>
        {format === 'text' ? <div className="skill-text-form">
          <div className="skill-text-grid">
            <div className="form-field">
              <label htmlFor="text-skill-name">技能名称</label>
              <input id="text-skill-name" value={textName} maxLength={200} disabled={busy}
                     placeholder="例如：产品结构核对" onChange={e => setTextName(e.target.value)} />
              <small>用于在技能库中识别这份制作方法。</small>
            </div>
            <div className="form-field">
              <label htmlFor="text-skill-description">说明</label>
              <input id="text-skill-description" value={textDescription} maxLength={1000} disabled={busy}
                     placeholder="可选，一句话说明这个技能做什么" onChange={e => setTextDescription(e.target.value)} />
            </div>
          </div>
          <div className="form-field">
            <div className="skill-text-label">
              <label htmlFor="text-skill-content">正文</label>
              <span className={textContent.length > 20000 ? 'skill-text-over' : ''}>{textContent.length.toLocaleString()} / 20000 字符</span>
            </div>
            <textarea id="text-skill-content" rows={10} value={textContent} maxLength={20000} disabled={busy}
                      placeholder="用自然语言写下制作规范或核对清单…" onChange={e => setTextContent(e.target.value)} />
            <div className="skill-text-file">
              <input id="text-skill-file" className="skill-file-input" type="file" accept=".md,.txt,text/markdown,text/plain" disabled={busy}
                     onChange={e => void readTextFile(e.target.files?.[0])} />
              <label htmlFor="text-skill-file" className={`button-secondary skill-file-button${busy ? ' skill-file-button-disabled' : ''}`}>从文件导入内容</label>
              <small>支持 100 KB 以内的 Markdown 或 TXT，导入后可继续编辑。</small>
            </div>
          </div>
        </div> : <div className="skill-import-picker">
          {format === 'zip' ? <>
            <input id="skill-archive" className="skill-file-input" type="file" accept=".zip,application/zip" disabled={busy}
                   onChange={e => pickArchive(e.target.files?.[0])} />
            <label htmlFor="skill-archive" className={`button-secondary skill-file-button${busy ? ' skill-file-button-disabled' : ''}`}>选择 zip 文件</label>
            <small>{archive ? `${archive.name} · ${bytes(archive.size)}` : '未选择文件，支持包含一个或多个技能目录的压缩包。'}</small>
          </> : <>
            <input id="skill-folder" className="skill-file-input" type="file" multiple disabled={busy}
                   {...({ webkitdirectory: 'true', directory: 'true' } as Record<string, string>)}
                   onChange={e => pickFolder(e.target.files)} />
            <label htmlFor="skill-folder" className={`button-secondary skill-file-button${busy ? ' skill-file-button-disabled' : ''}`}>选择文件夹</label>
            <small>{folder.length ? `已选择 ${folder.length} 个文件，相对路径会保留。` : '未选择文件夹，限制与压缩包相同。'}</small>
          </>}
        </div>}

        {!preview && <div className="form-actions"><button className="button-primary" disabled={busy || importing}>
          {format === 'text' ? (busy ? '保存中…' : '保存文本技能') : (busy ? '检查中…' : '上传并检查')}
        </button></div>}
      </form>

      {preview && <div className="skill-import-preview">
        {preview.manifest.present && !preview.manifest.ok && <p className="feedback feedback-warning">包内文件清单校验不一致：缺失 {preview.manifest.missing.length} 项、内容不符 {preview.manifest.mismatch.length} 项，请核对来源后再导入。</p>}
        {preview.needs_entry ? <section className="skill-entry-choice"><h3>选择说明文件</h3><p>{preview.entry_candidates?.length ? '找到多份文档，请选择 AI 应先阅读的说明，其他资料也会保留。' : '没有找到 Markdown 或 TXT 说明。可以补充说明后重新上传，或切换到文本技能直接填写。'}</p>
          {!!preview.entry_candidates?.length && <><div className="form-field"><label htmlFor="skill-entry-choice">先读取的说明</label><select id="skill-entry-choice" value={entryPath} onChange={event => setEntryPath(event.target.value)}><option value="">请选择文档</option>{preview.entry_candidates.map(item => <option key={item.path} value={item.path}>{item.path}</option>)}</select></div><button type="button" className="button-primary" disabled={!entryPath || busy} onClick={() => void resolveEntry()}>使用这份说明</button></>}
        </section> : <><h3>确认识别结果</h3><p className="form-footnote">选择要加入技能库的内容，名称和用途可直接修改。无需填写版本号或整理文件结构。</p>
          <div className="skill-import-results">{preview.skills.map(item => {
            const draft = drafts[item.root] || {name: item.name, description: item.description};
            const reserved = item.reserved && draft.name.trim() === item.name;
            return <article className="skill-import-result" key={item.root}><label className="skill-import-check"><input type="checkbox" aria-label={`导入 ${item.name}（${item.root}）`} disabled={reserved || !draft.name.trim()} checked={!!checks[item.root] && !reserved} onChange={event => setChecks(previous => ({...previous, [item.root]: event.target.checked}))} /><span>{item.resource_only ? '运行工具资料' : '制作技能'} · {item.file_count} 个文件</span><small>{reserved ? '与内置技能同名，修改名称后可导入副本' : item.same_content && draft.name === item.name ? '内容未变化' : item.is_upgrade && draft.name === item.name ? '新增版本，稍后启用' : '可导入'}</small></label>
              <div className="skill-import-result-fields"><div className="form-field"><label htmlFor={`import-name-${item.root}`}>名称</label><input id={`import-name-${item.root}`} maxLength={200} value={draft.name} onChange={event => { const name = event.target.value; setDrafts(previous => ({...previous, [item.root]: {...draft, name}})); if (name.trim() && name.trim() !== item.name) setChecks(previous => ({...previous, [item.root]: true})); }} /></div><div className="form-field"><label htmlFor={`import-description-${item.root}`}>用途说明 <span>帮助 AI 自动选择</span></label><textarea id={`import-description-${item.root}`} rows={2} maxLength={1000} value={draft.description} placeholder="例如：制作 A+ 场景模块时使用，保持产品结构并统一排版。" onChange={event => setDrafts(previous => ({...previous, [item.root]: {...draft, description: event.target.value}}))} /></div></div>
              <small className="skill-import-source">原目录：{item.root === '.' ? '上传内容根目录' : item.root} · {bytes(item.total_bytes)}</small>
            </article>;
          })}</div><div className="form-actions"><button type="button" className="button-secondary" disabled={importing} onClick={() => { setPreview(undefined); setArchive(undefined); setFolder([]); setEntryPath(''); }}>重新选择</button><button type="button" className="button-primary" disabled={importing} onClick={() => void confirm()}>{importing ? '导入中…' : '确认导入'}</button></div></>}
      </div>}
    </dialog>
  </section>;
}
