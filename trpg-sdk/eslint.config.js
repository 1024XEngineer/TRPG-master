// ESLint 9 flat config。
//
// SDK 是纯 TypeScript 库，只接入 typescript-eslint 的 recommended 规则集。
// 不用 strictTypeChecked / stylisticTypeChecked ——见 issue #73 决策 3：
// 实测这两套会带来大量存量违规，先用最基础的一档把 lint 立起来。
import tseslint from 'typescript-eslint'

export default tseslint.config(
  {
    // dist 是 rollup 构建产物；src/generated 是 `npm run codegen` 从后端
    // pydantic 模型生成出来的 TS 类型（issue #75）。两者都不是需要人工按
    // 风格规则审查的源码——dist 的正确性由构建流程保证，src/generated 的
    // 正确性由"重新生成后 git diff"这个漂移检查（CI）保证，不是靠 lint。
    // 而且生成器产出的写法本来就会踩一些手写代码不该踩的规则，比如空
    // payload（GameStartPayload）生成出的 `export interface Foo {}` 会被
    // no-empty-object-type 判定成"错误"，但这是 JSON Schema 到 TS 的正常
    // 映射结果，不是真的代码问题。
    ignores: ['dist/**', 'src/generated/**'],
  },
  ...tseslint.configs.recommended,
)
