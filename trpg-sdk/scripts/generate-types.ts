/**
 * 从后端导出的 JSON Schema 生成 `src/generated/dto.ts`（issue #75）。
 *
 * 完整流程分两步，跨语言边界，所以是两个独立脚本：
 *   1. `cd trpg-backend && uv run python scripts/export_schema.py`
 *      —— 把 REST DTO + WS 事件 payload 的 pydantic 模型导出成一份 JSON Schema。
 *   2. `cd trpg-sdk && npm run codegen`（这个文件）
 *      —— 读第 1 步产出的 JSON Schema，为里面每一个具名模型（`$defs` 的每个
 *         key）生成一个同名 TS interface/type，写进 src/generated/dto.ts。
 *
 * 只生成类型，不生成 resource 方法（issue #75 决策 2）——resources/*.ts 里的
 * 类仍然手写，这个脚本的产出只被 src/types.ts 当"类型来源"引用。
 *
 * 逐个 $defs 条目单独 compile()（而不是把整份 schema 丢给 compile 一次）：
 * 后端脚本给的是一份 `{ $defs: {...} }` 的合并 schema，本身没有一个可以当
 * 根类型的顶层 schema，直接 compile 整份文档只会得到一个没用的
 * `{ [k: string]: unknown }`。改成对每个 $defs 条目单独构造一个"以它为根、
 * 但仍带着完整 $defs 用于 $ref 解析"的 schema 分别 compile，且
 * `declareExternallyReferenced: false`——这样每个模型只生成一次，互相引用
 * （比如 RoomPreview 引用 RoomPlayerRead）靠生成的 TS 类型名直接对上，
 * 不会有重复定义。
 */
import { compile } from 'json-schema-to-typescript';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCHEMA_PATH = resolve(__dirname, '../../trpg-backend/.schema-export/models.schema.json');
const OUT_PATH = resolve(__dirname, '../src/generated/dto.ts');

const BANNER = `/**
 * 本文件由 \`npm run codegen\` 从后端 pydantic 模型自动生成，请勿手改。
 *
 * 源头：trpg-backend/app/dto/{auth,room,character,common,ws}.py
 * 重新生成：
 *   1. cd trpg-backend && uv run python scripts/export_schema.py
 *   2. cd trpg-sdk && npm run codegen
 * 生成后把这个文件的改动一并提交——CI 会重新跑一遍上面两步，用 git diff
 * 校验有没有人改了后端 DTO 却忘记重新生成（issue #75 决策 3）。
 */

`;

interface JsonSchemaDocument {
  $defs?: Record<string, object>;
}

async function main(): Promise<void> {
  const raw = readFileSync(SCHEMA_PATH, 'utf-8');
  const document = JSON.parse(raw) as JsonSchemaDocument;
  const defs = document.$defs ?? {};
  // 固定按名称排序：pydantic 那边的 $defs 顺序取决于模型互相引用时的发现顺序，
  // 换一种引用路径就可能变化；排序后只有真正新增/改名的模型才会让 diff
  // 出现变化，其它模型的生成结果不会因为顺序抖动而跟着变。
  const names = Object.keys(defs).sort();

  if (names.length === 0) {
    throw new Error(`未在 ${SCHEMA_PATH} 里找到任何 $defs——是不是忘了先跑后端的导出脚本？`);
  }

  const sections: string[] = [];
  for (const name of names) {
    const rootSchema = { ...defs[name], $defs: defs, title: name };
    const ts = await compile(rootSchema, name, {
      bannerComment: '',
      additionalProperties: false,
      declareExternallyReferenced: false,
    });
    sections.push(ts.trim());
  }

  mkdirSync(dirname(OUT_PATH), { recursive: true });
  writeFileSync(OUT_PATH, BANNER + sections.join('\n\n') + '\n', 'utf-8');
  console.log(`Generated ${names.length} types -> ${OUT_PATH}`);
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
