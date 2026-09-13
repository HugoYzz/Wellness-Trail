# 康迹前端

Vue 3 + TypeScript + Vite 前端。完整安装、运行、安全边界与项目说明见仓库根目录 [`README.md`](../README.md)。

```powershell
npm ci
npm run dev
npm run test:unit
npm run build
npm run test:e2e
```

开发服务器将 `/api` 代理到 `VITE_API_TARGET`，默认 `http://localhost:8001`。浏览器测试会自动启动隔离的 Mock 后端和临时数据库。
