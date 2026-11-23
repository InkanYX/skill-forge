import { useEffect, useState } from 'react';
import { fetchHealth, fetchStorage, type HealthResponse, type StorageStatus } from './api';

export default function SystemStatus() {
  const [health, setHealth] = useState<HealthResponse>(); const [storage, setStorage] = useState<StorageStatus>();
  const [error, setError] = useState(''); const [busy, setBusy] = useState(true); const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true; const controller = new AbortController(); const timeout = window.setTimeout(() => controller.abort(), 8000);
    setBusy(true); setError(''); setHealth(undefined); setStorage(undefined);
    Promise.allSettled([fetchHealth(controller.signal), fetchStorage(controller.signal)]).then(([h, s]) => {
      if (!active) return;
      if (h.status === 'fulfilled') setHealth(h.value);
      if (s.status === 'fulfilled') setStorage(s.value);
      if (h.status === 'rejected' || s.status === 'rejected') setError('部分状态无法读取，请检查本机服务是否启动。');
    }).finally(() => { window.clearTimeout(timeout); if (active) setBusy(false); });
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [attempt]);
  return <section className="connection-card"><div className="service-grid"><div><span>后端服务</span><strong>{busy ? '检查中…' : health ? '连接正常' : '未连接'}</strong><small>{health ? `${health.service} · ${health.version}` : '本机端口 8000'}</small></div><div><span>数据存储</span><strong>{busy ? '检查中…' : storage?.status === 'ready' ? '已就绪' : '未就绪'}</strong><small>{storage?.message || '无法读取数据库状态'}</small></div><div><span>前端页面</span><strong>已加载</strong><small>本机开发模式 · 端口 5173</small></div></div>{error && <p className="feedback feedback-warning">{error}</p>}<div className="form-actions"><button className="button-secondary" type="button" disabled={busy} onClick={() => setAttempt(value => value + 1)}>{busy ? '检查中…' : '重新检查'}</button></div></section>;
}
