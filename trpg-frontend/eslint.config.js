// ESLint 9 flat config。
//
// 接入 typescript-eslint 的 recommended 规则集 + eslint-plugin-react-hooks
// 的 recommended 规则集。不用 strictTypeChecked / stylisticTypeChecked ——
// 见 issue #73 决策 3：实测会带来 196~245 处存量违规，而前端目前零测试、
// 没有回归防线，这种规模的机械改动风险不成比例，等有测试再上。
// ⚠️ eslint-plugin-react-hooks 有意锁在 5.x（npm 上最新已是 7.x）：从 v7 起
// recommended 里塞进了一整批 React Compiler 规则（purity / immutability /
// static-components / set-state-in-render 等），升上去会立刻涌出大量存量违规，
// 与决策 3「本期只收敛到 7 处、保持 PR 干净」的前提冲突。要升版本请连带重新
// 评估违规规模，不要顺手 bump。v5 的 recommended 只含经典的 rules-of-hooks
// 与 exhaustive-deps 两条。
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'

export default tseslint.config(
  {
    // dist 是构建产物，node_modules 不属于本包源码，都不需要 lint。
    ignores: ['dist/**'],
  },
  ...tseslint.configs.recommended,
  reactHooks.configs['recommended-latest'],
)
