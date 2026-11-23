import { PRODUCT_VARIABLE_FIELDS, type Product } from './productApi';

export default function TemplateVariableField({ name, value, product, onChange, idPrefix = 'variable' }: {
  name: string; value: string; product?: Product; onChange: (value: string) => void; idPrefix?: string;
}) {
  const fromProduct = !!product && name in PRODUCT_VARIABLE_FIELDS;
  const missing = fromProduct && !value.trim();
  const locked = fromProduct && !missing;
  return <div className="form-field">
    <label htmlFor={`${idPrefix}-${name}`}>{name}{fromProduct && <span className="field-source" title="由所选产品自动填入">来自产品资料</span>}</label>
    <input id={`${idPrefix}-${name}`} required maxLength={2000} value={value} readOnly={locked}
           title={locked ? '来自产品资料，修改请前往产品资料页' : undefined}
           onChange={event => onChange(event.target.value)} />
    {missing && <small>产品资料里这一项为空，可在此临时补充，或到<a href="#/products">产品资料</a>补全。</small>}
  </div>;
}
