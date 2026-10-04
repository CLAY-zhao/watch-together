import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: { '@': path.resolve(__dirname, 'src') },
    },
    server: {
        host: '0.0.0.0',
        port: 5173,
        strictPort: true,

        // ★ 关键：允许局域网 IP 访问（Vite 7 默认只允许 localhost）
        allowedHosts: [
            'localhost',
            '127.0.0.1',
            '192.168.1.21',     // ← 你的电脑局域网 IP
            '.local',
        ],
        // 或者直接允许所有（开发时简单粗暴，但不太安全）
        // allowedHosts: true,

        proxy: {
            '/ws': {
                target: 'ws://127.0.0.1:8765',    // ★ 用 127.0.0.1 别用 localhost
                ws: true,
                changeOrigin: true,
            },
            '/api': {
                target: 'http://127.0.0.1:8765',
                changeOrigin: true,
            },
        },
    },
    build: {
        outDir: 'dist',
        emptyOutDir: true,
    },
})