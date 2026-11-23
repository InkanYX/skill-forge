import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useAuth } from './AuthGate';
import { formatTaskTime } from './imageTaskApi';
import {
  activateVersion, confirmPackage, fileUrl, forkPackage, importTextSkill, listFiles, listPackages, listVersions,
  readFile, uploadPackage,
  type ImportPreview, type SkillFile, type SkillPackage, type SkillText, type SkillVersion,
} from './skillPackageApi';

const kindLabels: Record<string, string> = {
  entry: '入口', reference: '规范', template: '模板', asset: '素材', license: '许可',
  script: '脚本（只存档）', execution: '执行说明', other: '其他',
};

function bytes(value: number) {
  return value > 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`;
}

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
  const [levels, setLevels] = useState<Record<string, 'core' | 'full'>>({});
  const [importing, setImporting] = useState(false);
  const [format, setFormat] = useState<'zip' | 'folder' | 'text'>('zip');
  const [textName, setTextName] = useState('');
  const [textDescription, setTextDescription] = useState('');
  const [textContent, setTextContent] = useState('');

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
    if (!selected) { setVersions([]); setFiles([]); setViewing(undefined); setFile(undefined); return; }
    let active = true;
    setFile(undefined);
    setViewing(selected.current_version || undefined);
    Promise.all([listVersions(selected.id), selected.current_version ? listFiles(selected.id, selected.current_version.id) : Promise.resolve(undefined)])
      .then(([value, detail]) => {
        if (!active) return;
        setVersions(value);
        setFiles(detail?.files || []);
      })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : '技能详情读取失败'); });
    return () => { active = false; };
  }, [selected]);

  async function viewVersion(item: SkillVersion) {
    if (!selected) return;
    setBusy(true); setFile(undefined); setViewing(item);
    try { setFiles((await listFiles(selected.id, item.id)).files); setNotice(`正在查看版本 ${item.version_label} 的文件。`); }
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

  function pickArchive(value?: File) { setArchive(value); setFolder([]); setPreview(undefined); setError(''); }
  function pickFolder(list: FileList | null) {
    setFolder(list ? Array.from(list) : []);
    setArchive(undefined); setPreview(undefined); setError('');
  }

  function pickFormat(value: 'zip' | 'folder' | 'text') {
    if (value === format) return;
    setFormat(value);
    setArchive(undefined); setFolder([]); setPreview(undefined); setError('');
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
    setPreview(undefined); setArchive(undefined); setFolder([]);
  }

  async function inspect(event: FormEvent) {
    event.preventDefault();
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
      const value = await uploadPackage(form);
      setPreview(value);
      setChecks(Object.fromEntries(value.skills.map(item => [item.name, !item.same_content && !item.reserved])));
      setLevels(Object.fromEntries(value.skills.map(item => [item.name, 'core' as const])));
    } catch (err) { setError(err instanceof Error ? err.message : '导入检查失败'); }
    finally { setBusy(false); }
  }

  async function confirm() {
    if (!preview) return;
    const selections = preview.skills
      .filter(item => checks[item.name])
      .map(item => ({ name: item.name, compile_level: levels[item.name] || 'core' as const }));
    if (!selections.length) { setError('请至少选择一个技能。'); return; }
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

    <div className="skill-rules">
      <strong>导入规则</strong>
      <ul>
        <li>支持 zip 压缩包、文件夹，或直接粘贴一份文本技能；压缩包不超过 20 MB、1000 个文件、单文件不超过 5 MB。</li>
        <li>完整技能目录必须有 <code>SKILL.md</code>，并在 frontmatter 中提供 <code>name</code> 与 <code>description</code>。</li>
        <li>文本技能会生成只读的 <code>SKILL.md</code>，最多 20000 字符；修改内容会作为新版本，不覆盖旧版本。</li>
        <li>同名个人技能会作为新版本导入，不会覆盖旧版本；导入完成后需手动启用。</li>
        <li>内置技能名保留，个人技能不能覆盖；需要定制时请使用「复制为副本」。</li>
        <li>个人技能包仅创建者可见、可启用并可用于 Agent；管理员可只读查看，不能代为启用。</li>
        <li>脚本、图片只存档不执行；Agent 只读取文本规范并调用系统工具。</li>
        <li>不支持符号链接、<code>../</code> 路径或绝对路径；拒绝不安全压缩包。</li>
      </ul>
    </div>

    {!importOpen && error && <p className="feedback feedback-error" role="alert">{error}</p>}
    {notice && <p className="feedback feedback-success" role="status">{notice}</p>}

    <div className="settings-layout skill-layout">
      <aside className="config-list">
        <div className="form-field"><label htmlFor="skill-search">搜索技能包</label><input id="skill-search" value={search} onChange={e => setSearch(e.target.value)} placeholder="名称、说明或来源" /></div>
        {loading && <p className="empty-config">正在读取…</p>}
        {filtered.map(item => <button type="button" key={item.id} className={`config-item ${selected?.id === item.id ? 'config-item-active' : ''}`} onClick={() => { setSelected(item); setNotice(''); setError(''); }}>
          <strong>{item.name}</strong>
          <small>{item.current_version ? `当前版本 ${item.current_version.version_label}` : '尚未启用版本'} · {item.version_count} 个版本</small>
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
            <div><dt>当前版本</dt><dd>{current ? `${current.version_label}（${current.compile_level === 'full' ? '完整参考' : '核心'}）` : '未启用'}</dd></div>
            <div><dt>文件</dt><dd>{current ? `${current.file_count} 个 · ${bytes(current.total_bytes)}` : '—'}</dd></div>
            <div><dt>更新时间</dt><dd>{formatTaskTime(selected.updated_at)}</dd></div>
          </dl>

          {current && <>
            <div className="skill-meta-actions">
              <button type="button" className="button-secondary" disabled={busy} onClick={() => void fork()}>复制为副本</button>
              <button type="button" className="button-secondary" disabled={busy} onClick={() => void viewVersion(current)}>查看当前版本文件</button>
            </div>

            <h3 className="skill-subhead">版本</h3>
            <div className="member-table-wrap"><table className="member-table"><thead><tr><th>版本</th><th>编译</th><th>文件</th><th>导入时间</th><th>状态</th></tr></thead><tbody>
              {versions.map(item => <tr key={item.id}>
                <td><strong>{item.version_label}</strong><small>{item.compiled_chars.toLocaleString()} 字符</small></td>
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
            {file && <div className="skill-preview"><div className="section-heading"><strong>{file.path}</strong><span>{file.total_chars.toLocaleString()} 字符{file.truncated ? '（已截断）' : ''}</span></div><pre className="skill-content">{file.content}</pre></div>}
          </>}
        </> : <div className="product-welcome"><span className="step-icon">只读技能包</span><h3>导入一个技能包开始</h3><p>技能包包含 SKILL.md 与参考规范。导入后系统会生成不可变的预编译快照，Agent 任务直接装入使用。</p></div>}
      </div>
    </div>

    <dialog ref={importDialog} className={`product-dialog skill-import-dialog${format === 'text' ? ' skill-import-dialog-text' : ''}`} aria-labelledby="skill-import-title" onCancel={event => { event.preventDefault(); closeImport(); }}>
      <div className="product-dialog-heading">
        <div><h2 id="skill-import-title">导入技能</h2><p className="settings-intro">上传后先检查识别结果，确认后才写入技能库。导入的技能归当前账号私有。</p></div>
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
              <small>直接选择整个技能目录</small>
            </label>
            <label className={`skill-import-option${format === 'text' ? ' skill-import-option-active' : ''}`}>
              <input type="radio" name="skill-import-format" value="text" checked={format === 'text'} onChange={() => pickFormat('text')} />
              <strong>文本技能</strong>
              <small>填写名称与正文，或导入 .md / .txt</small>
            </label>
          </div>
        </fieldset>

        <div className={`skill-import-requirements${format === 'text' ? ' skill-import-requirements-text' : ''}`}>
          <strong>{format === 'text' ? '文本技能说明' : '打包要求'}</strong>
          {format === 'text' ? <ul>
            <li>不需要 zip、文件夹或 <code>SKILL.md</code>，直接填写名称和正文即可。</li>
            <li>名称必填，说明可选，正文最多 20000 字符。</li>
            <li>可从 <code>.md</code> / <code>.txt</code> 文件导入内容，文件不超过 100 KB，导入后仍可编辑。</li>
            <li>保存后会生成只读 <code>SKILL.md</code>；首次导入自动启用，内容变化会新增版本，需要手动启用。</li>
          </ul> : <ul>
            <li>至少包含一个 <code>SKILL.md</code>；每个含 <code>SKILL.md</code> 的目录算一个技能，可一次导入多个。</li>
            <li><code>SKILL.md</code> 使用 UTF-8，开头是 <code>---</code> 包住的 frontmatter，并提供 <code>name</code> 与 <code>description</code>；建议写上 <code>metadata.version</code>。</li>
            <li>{format === 'zip' ? '单个 zip 文件' : '所选文件夹'}总计不超过 20 MB、1000 个文件，单个文件不超过 5 MB。</li>
            {format === 'folder' && <li>请选择技能目录本身（其中直接包含 <code>SKILL.md</code>）；相对路径会保留，外层文件夹可以保留。</li>}
            <li>不能包含绝对路径、<code>../</code> 或符号链接；脚本和图片只存档，不会执行。</li>
          </ul>}
          {format !== 'text' && <details className="skill-import-example">
            <summary>查看目录结构与 SKILL.md 示例</summary>
            <pre>{`my-skill/
├─ SKILL.md
├─ references/
│  ├─ prompt-writing-standard.md
│  └─ quality-gate.md
└─ templates/
   └─ product.md

SKILL.md 开头：
---
name: my-skill
description: 一句话说明这个技能
metadata:
  version: 1.0.0
---

技能正文…`}</pre>
          </details>}
        </div>

        {format === 'text' ? <div className="skill-text-form">
          <div className="skill-text-grid">
            <div className="form-field">
              <label htmlFor="text-skill-name">技能名称</label>
              <input id="text-skill-name" value={textName} maxLength={200} disabled={busy}
                     placeholder="例如：产品结构核对" onChange={e => setTextName(e.target.value)} />
              <small>必填。内置技能名保留，不能覆盖。</small>
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

        <div className="form-actions"><button className="button-primary" disabled={busy || importing}>
          {format === 'text' ? (busy ? '保存中…' : '保存文本技能') : (busy ? '检查中…' : '上传并检查')}
        </button></div>
      </form>

      {preview && <div className="skill-import-preview">
        <p className={preview.manifest.present && !preview.manifest.ok ? 'feedback feedback-warning' : 'form-footnote'}>
          {preview.manifest.present ? (preview.manifest.ok ? `manifest.json 校验通过（${preview.manifest.checked} 项）。` : `manifest.json 校验不一致：缺失 ${preview.manifest.missing.length} 项、哈希不符 ${preview.manifest.mismatch.length} 项。仍可人工确认后导入。`) : '未提供 manifest.json；将按实际文件导入。'}
        </p>
        <div className="member-table-wrap"><table className="member-table"><thead><tr><th>选择</th><th>技能</th><th>内容</th><th>编译</th><th>状态</th><th>编译档位</th></tr></thead><tbody>
          {preview.skills.map(item => <tr key={item.name}>
            <td><input type="checkbox" aria-label={`导入 ${item.name}`} disabled={item.reserved} checked={!!checks[item.name]} onChange={e => setChecks(previous => ({ ...previous, [item.name]: e.target.checked }))} /></td>
            <td><strong>{item.name}</strong><small>{item.description || '未填写说明'} · {item.version_label}</small></td>
            <td>{item.file_count} 个文件 · {bytes(item.total_bytes)}</td>
            <td>核心 {item.compiled.core_chars.toLocaleString()} / 完整 {item.compiled.full_chars.toLocaleString()}</td>
            <td>{item.reserved ? <span className="member-inactive">内置名称保留</span> : item.same_content ? <span className="member-inactive">内容未变化</span> : item.is_upgrade ? <span className="member-active">将新增版本</span> : <span className="member-active">新技能</span>}</td>
            <td><select value={levels[item.name] || 'core'} onChange={e => setLevels(previous => ({ ...previous, [item.name]: e.target.value as 'core' | 'full' }))}>
              <option value="core">核心（推荐）</option><option value="full">完整参考</option>
            </select></td>
          </tr>)}
        </tbody></table></div>
        <div className="form-actions"><button type="button" className="button-secondary" disabled={importing} onClick={() => { setPreview(undefined); setArchive(undefined); setFolder([]); }}>重新选择</button><button type="button" className="button-primary" disabled={importing} onClick={() => void confirm()}>{importing ? '导入中…' : '确认导入'}</button></div>
      </div>}
    </dialog>
  </section>;
}
