import { useEffect, useRef, useState } from 'react';

const presets = [
  ['default', '自动（不指定尺寸）'],
  ['1024x1024', '方形 · 1024 × 1024'],
  ['1536x1024', '横向 · 1536 × 1024'],
  ['1024x1536', '纵向 · 1024 × 1536'],
];
const isPreset = (value: string) => presets.some(([size]) => size === value);
const maxPixels = 20_000_000;

export function formatImageSize(value: string) {
  return value === 'default' ? '自动（不指定尺寸）' : `${value.replace('x', ' × ')} 像素`;
}

export default function ImageSizePicker({ id, value, onChange, label = '输出尺寸' }: {
  id: string; value: string; onChange: (value: string) => void; label?: string;
}) {
  const [custom, setCustom] = useState(() => !isPreset(value));
  const emitted = useRef(value);
  const widthInput = useRef<HTMLInputElement>(null);
  const [width = '', height = ''] = value === 'default' ? ['', ''] : value.split('x');
  const tooLarge = Number(width) * Number(height) > maxPixels;
  const showCustom = custom || !isPreset(value);

  useEffect(() => {
    if (value !== emitted.current) setCustom(!isPreset(value));
    emitted.current = value;
  }, [value]);
  useEffect(() => {
    widthInput.current?.setCustomValidity(tooLarge ? '总像素不能超过 2000 万，请减小宽度或高度。' : '');
  }, [value, showCustom, tooLarge]);

  function update(next: string) { emitted.current = next; onChange(next); }

  return <div className="form-field image-size-picker">
    <label htmlFor={id}>{label}</label>
    <select id={id} value={showCustom ? 'custom' : value} aria-describedby={`${id}-help`} onChange={event => {
      const next = event.target.value;
      setCustom(next === 'custom');
      update(next === 'custom' ? '2000x2000' : next);
    }}>
      {presets.map(([size, title]) => <option key={size} value={size}>{title}</option>)}
      <option value="custom">自定义尺寸</option>
    </select>
    {showCustom && <div className="custom-image-size">
      <div><label htmlFor={`${id}-width`}>宽度（像素）</label><input ref={widthInput} id={`${id}-width`} type="number" min={1} max={maxPixels} step={1} required value={width} onChange={event => update(`${event.target.value}x${height}`)} /></div>
      <span aria-hidden="true">×</span>
      <div><label htmlFor={`${id}-height`}>高度（像素）</label><input id={`${id}-height`} type="number" min={1} max={maxPixels} step={1} required value={height} onChange={event => update(`${width}x${event.target.value}`)} /></div>
    </div>}
    <small id={`${id}-help`}>{value === 'default' ? '不向接口指定尺寸，由服务商按默认规则处理；实际大小以返回图片为准。' : '请求的尺寸需要所选服务商和模型支持，不会自动缩放返回的图片。'}{showCustom && ' 宽高须为正整数，总像素不超过 2000 万。'}</small>
    {tooLarge && <small className="size-error" role="alert">总像素超过 2000 万，请减小宽度或高度。</small>}
  </div>;
}
