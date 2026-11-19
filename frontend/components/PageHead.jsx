export default function PageHead({ title, sub, children }) {
  return (<div className="top"><div><h1>{title}</h1><p>{sub}</p></div><div className="sp" />{children}</div>);
}
