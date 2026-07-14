const sections = [
  {
    title: '前端',
    items: ['React 19', 'TypeScript', 'Vite']
  },
  {
    title: '后端',
    items: ['FastAPI', 'Python 3', 'uv']
  }
];

export default function App() {
  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">TRPG-master</p>
        <h1>项目骨架</h1>
        <p className="lede">
          前端与后端的最小可运行目录已经拆开，后续可以直接在各自目录里继续扩展。
        </p>
      </header>

      <section className="grid">
        {sections.map((section) => (
          <article className="panel" key={section.title}>
            <h2>{section.title}</h2>
            <ul>
              {section.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        ))}
      </section>
    </main>
  );
}
