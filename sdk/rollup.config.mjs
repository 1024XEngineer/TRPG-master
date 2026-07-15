import resolve from '@rollup/plugin-node-resolve';
import typescript from '@rollup/plugin-typescript';
import dts from 'rollup-plugin-dts';

const input = 'src/index.ts';

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
