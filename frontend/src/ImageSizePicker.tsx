import { useEffect, useRef, useState } from 'react';

const presets = [
  ['default', '不指定画幅'],
  ['1024x1024', '方形 · 1:1'],
  ['1536x1024', '横向 · 3:2'],
  ['1024x1536', '纵向 · 2:3'],
];
const isPreset = (value: string) => presets.some(([size]) => size === value);
const maxPixels = 20_000_000;

export function formatImageSize(value: string) {
  return value === 'default' ? '不指定画幅' : `目标画幅 ${value.replace('x', ':')}`;
}

export default function ImageSizePicker({ id, value, onChange, label = '画幅要求' }: {
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
      update(next === 'custom' ? '1x1' : next);
    }}>
      {presets.map(([size, title]) => <option key={size} value={size}>{title}</option>)}
      <option value="custom">自定义比例</option>
    </select>
    {showCustom && <div className="custom-image-size">
      <div><label htmlFor={`${id}-width`}>宽度比例</label><input ref={widthInput} id={`${id}-width`} type="number" min={1} max={maxPixels} step={1} required value={width} onChange={event => update(`${event.target.value}x${height}`)} /></div>
      <span aria-hidden="true">×</span>
      <div><label htmlFor={`${id}-height`}>高度比例</label><input id={`${id}-height`} type="number" min={1} max={maxPixels} step={1} required value={height} onChange={event => update(`${width}x${event.target.value}`)} /></div>
    </div>}
    <small id={`${id}-help`}>{value === 'default' ? '原生尺寸由模型配置或服务商默认值决定。' : '比例用于构图要求；原生请求尺寸可在模型参数中配置，实际像素以返回为准。'}{showCustom && ' 宽高比例须为正整数。'}</small>
    {tooLarge && <small className="size-error" role="alert">总像素超过 2000 万，请减小宽度或高度。</small>}
  </div>;
}
