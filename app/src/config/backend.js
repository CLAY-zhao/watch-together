/**
 * 统一的后端地址配置
 *
 * 判断当前运行环境：
 * - 浏览器（开发/生产）：同源，返回空字符串
 * - Capacitor App：指向 Render 后端
 */

// ★★★ 改成你的 Render 后端地址 ★★★
const BACKEND_ORIGIN = 'https://watch-together-t10x.onrender.com'

/** 是否在 Capacitor 原生 App 里运行 */
export function isNativeApp() {
    const proto = location.protocol
    const host = location.hostname

    // Capacitor 环境特征
    if (proto === 'capacitor:' || proto === 'ionic:') return true

    // Android Capacitor：https://localhost
    if (host === 'localhost' && proto === 'https:') return true

    // iOS Capacitor：capacitor://localhost
    if (host === 'localhost' && proto === 'capacitor:') return true

    return false
}

/** 获取后端 HTTP 基础地址 */
export function getBackendOrigin() {
    return isNativeApp() ? BACKEND_ORIGIN : ''
}

/** 获取 WebSocket 基础地址（不含 /ws） */
export function getWsBase() {
    if (isNativeApp()) {
        // https://xxx → wss://xxx
        return BACKEND_ORIGIN.replace(/^http/, 'ws')
    }
    // 同源
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://'
    return proto + location.host
}

/** 拼接完整 API URL：apiUrl('/api/ice') → 'https://xxx/api/ice' */
export function apiUrl(path) {
    const origin = getBackendOrigin()
    return origin + path
}