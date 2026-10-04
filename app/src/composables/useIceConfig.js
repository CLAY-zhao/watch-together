import { ref } from 'vue'

/* ============================================================
 *  你从 metered.ca 拿到的 ICE 配置
 * ============================================================ */
const ICE_SERVERS = [
    {
        urls: 'stun:stun.relay.metered.ca:80',
    },
    {
        urls: 'turn:asia.relay.metered.ca:80',
        username: '9dd6ce6953377deb966f471f',
        credential: 'QnV7fYMKMKFJd+tx',
    },
    {
        urls: 'turn:asia.relay.metered.ca:80?transport=tcp',
        username: '9dd6ce6953377deb966f471f',
        credential: 'QnV7fYMKMKFJd+tx',
    },
    {
        urls: 'turn:asia.relay.metered.ca:443',
        username: '9dd6ce6953377deb966f471f',
        credential: 'QnV7fYMKMKFJd+tx',
    },
    {
        urls: 'turns:asia.relay.metered.ca:443?transport=tcp',
        username: '9dd6ce6953377deb966f471f',
        credential: 'QnV7fYMKMKFJd+tx',
    },
]

const _servers = ref(ICE_SERVERS)

/**
 * 返回配置好的 ICE 服务器列表
 * 现在不做任何网络请求，直接用写死的配置
 */
async function ensureIceReady() {
    return _servers.value
}

export function useIceConfig() {
    return {
        iceServers: _servers,
        ensureIceReady,
    }
}