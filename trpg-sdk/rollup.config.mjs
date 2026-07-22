import resolve from '@rollup/plugin-node-resolve';
import typescript from '@rollup/plugin-typescript';
import dts from 'rollup-plugin-dts';

const input = 'src/index.ts';

// 导出两份配置，rollup 会依次跑完：
// 1. 把 src/index.ts 编译打包成 ESM + CJS 两份产物（消费方不管用 import
//    还是 require 都能引到），declaration:false 是因为类型声明交给第二份
//    配置统一生成，避免这里再散落一堆逐文件的 .d.ts。
// 2. 用 rollup-plugin-dts 把所有类型声明合并打包成单独一个 dist/index.d.ts，
//    package.json 的 "types" 字段指向它。
export default [
  {
    input,
    output: [
      { file: 'dist/index.esm.js', format: 'esm', sourcemap: true },
      { file: 'dist/index.cjs.js', format: 'cjs', sourcemap: true, exports: 'named' }
    ],
    plugins: [resolve(), typescript({ tsconfig: './tsconfig.json', declaration: false })]
  },
  {
    input,
    output: [{ file: 'dist/index.d.ts', format: 'esm' }],
    plugins: [dts()]
  }
];
