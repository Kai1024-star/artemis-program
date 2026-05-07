# ARTEMIS React

React 重写版术语抽取前端控制台（带高级动效）。

## 功能

- 导入/粘贴句对 JSON
- `recall` / `balanced` / `strict` 三档模式
- 前端术语抽取 MVP（规则 + 分数 + 去重）
- 结果表展示与 CSV 导出
- Framer Motion + GSAP 动画界面

## 启动

1. 安装 Node.js（建议 18+）
2. 在项目目录执行：

```bash
cd artemis-react
npm install
npm run dev
```

## 说明

当前是前端 MVP 版，适合先把交互和视觉做起来。  
如果你要 1:1 对齐 Python V3.1（含 LLM expand/judge + Excel 输出），建议再补一个 Node/Python API 后端，把这套前端接上即可。
