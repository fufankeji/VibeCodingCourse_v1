# Data Analysis Assistant - Frontend

基于 React + TypeScript + Tailwind CSS 的智能数据分析助理前端应用。

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

### 3. 访问应用

打开浏览器访问 http://localhost:5173

## 项目结构

```
frontend/
├── src/
│   ├── App.tsx           # 主应用组件
│   ├── main.tsx          # 入口文件
│   ├── index.css         # 全局样式
│   ├── components/       # 组件 (Phase 2)
│   │   ├── ChatSidebar/  # 左侧聊天管理
│   │   ├── ChatArea/     # 中间问答区域
│   │   └── ChartPanel/   # 右侧图表面板
│   ├── hooks/            # 自定义 Hooks (Phase 2)
│   ├── services/         # API 服务 (Phase 4)
│   ├── store/            # 状态管理 (Phase 2)
│   └── types/            # 类型定义 (Phase 2)
├── public/
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── tsconfig.json
```

## 技术栈

- **框架**: React 18
- **语言**: TypeScript
- **构建工具**: Vite
- **样式**: Tailwind CSS
- **状态管理**: Zustand
- **图表**: ECharts
- **图标**: Lucide React

## 可用脚本

- `npm run dev` - 启动开发服务器
- `npm run build` - 构建生产版本
- `npm run preview` - 预览生产版本
- `npm run lint` - 代码检查
