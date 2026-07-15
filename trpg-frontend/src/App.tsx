import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, createTrpgSdk, type Example } from 'trpg-sdk';

const sdk = createTrpgSdk({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1'
});

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export default function App() {
  const [examples, setExamples] = useState<Example[]>([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');

  const loadExamples = async () => {
    setLoading(true);
    setError(null);
    try {
      setExamples(await sdk.examples.list());
    } catch (err) {
      setError(errorMessage(err, '加载失败'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadExamples();
  }, []);

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setError(null);
    try {
      await sdk.examples.create({ name, description: description || null });
      setName('');
      setDescription('');
      await loadExamples();
    } catch (err) {
      setError(errorMessage(err, '创建失败'));
    }
  };

  const startEditing = (example: Example) => {
    setEditingId(example.id);
    setEditName(example.name);
    setEditDescription(example.description ?? '');
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditName('');
    setEditDescription('');
  };

  const handleSaveEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingId || !editName.trim()) return;
    setError(null);
    try {
      await sdk.examples.update(editingId, {
        name: editName,
        description: editDescription || null
      });
      cancelEditing();
      await loadExamples();
    } catch (err) {
      setError(errorMessage(err, '更新失败'));
    }
  };

  const handleDelete = async (example: Example) => {
    try {
      await sdk.examples.remove(example.id);
      await loadExamples();
    } catch (err) {
      setError(errorMessage(err, '删除失败'));
    }
  };

  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">TRPG-master</p>
        <h1>Examples 端到端联调</h1>
        <p className="lede">
          通过 trpg-sdk 调用后端 /api/v1/examples 接口，验证前后端全链路 CRUD 流程。
        </p>
      </header>

      <form className="panel example-form" onSubmit={handleCreate}>
        <h2>新增 Example</h2>
        <div className="example-form-row">
          <input
            placeholder="名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <input
            placeholder="描述（可选）"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
          <button type="submit">新增</button>
        </div>
        {error && <p className="example-error">{error}</p>}
      </form>

      <section className="panel">
        <h2>Example 列表{loading ? '（加载中…）' : ''}</h2>
        {examples.length === 0 && !loading && <p className="lede">暂无数据，先新增一条。</p>}
        <ul className="example-list">
          {examples.map((example) =>
            editingId === example.id ? (
              <li key={example.id} className="example-item">
                <form className="example-edit-form" onSubmit={handleSaveEdit}>
                  <input
                    value={editName}
                    onChange={(event) => setEditName(event.target.value)}
                  />
                  <input
                    placeholder="描述（可选）"
                    value={editDescription}
                    onChange={(event) => setEditDescription(event.target.value)}
                  />
                  <div className="example-actions">
                    <button type="submit">保存</button>
                    <button type="button" onClick={cancelEditing}>
                      取消
                    </button>
                  </div>
                </form>
              </li>
            ) : (
              <li key={example.id} className="example-item">
                <div>
                  <strong>{example.name}</strong>
                  {example.description && (
                    <span className="example-desc"> — {example.description}</span>
                  )}
                </div>
                <div className="example-actions">
                  <button type="button" onClick={() => startEditing(example)}>
                    编辑
                  </button>
                  <button type="button" onClick={() => handleDelete(example)}>
                    删除
                  </button>
                </div>
              </li>
            )
          )}
        </ul>
      </section>
    </main>
  );
}
