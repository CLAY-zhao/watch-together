/**
 * 观影历史记录
 * 数据存在 localStorage，结构：
 * [
 *   { id, time, date, duration, movieName },
 *   ...
 * ]
 */
const STORAGE_KEY = 'wt:watchHistory'
const MAX_ENTRIES = 500

function formatDate(d) {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${dd}`
}

export function getHistory() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY)
        return raw ? JSON.parse(raw) : []
    } catch (e) {
        return []
    }
}

function saveHistory(history) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(history))
    } catch (e) { }
}

/**
 * 新增一条观影记录（进入房间时调用）
 * @returns {string} sessionId
 */
export function addHistory(entry = {}) {
    const history = getHistory()
    const id = 's_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)

    history.push({
        id,
        time: Date.now(),
        date: formatDate(new Date()),
        duration: 0,
        movieName: '',
        ...entry,
    })

    while (history.length > MAX_ENTRIES) history.shift()
    saveHistory(history)
    return id
}

/**
 * 更新某条记录的时长（秒）
 */
export function updateHistoryDuration(id, duration) {
    if (!id) return
    const history = getHistory()
    const item = history.find(h => h.id === id)
    if (item) {
        item.duration = Math.max(item.duration || 0, Math.floor(duration))
        saveHistory(history)
    }
}

/**
 * 更新电影名
 */
export function updateHistoryMovieName(id, name) {
    if (!id) return
    const history = getHistory()
    const item = history.find(h => h.id === id)
    if (item) {
        item.movieName = name
        saveHistory(history)
    }
}

/**
 * 总体统计
 */
export function getStats() {
    const history = getHistory()
    const totalSessions = history.length
    const totalSeconds = history.reduce((sum, h) => sum + (h.duration || 0), 0)
    const uniqueDays = new Set(history.map(h => h.date)).size
    const firstDate = history.length > 0 ? history[0].date : null

    return {
        totalSessions,
        totalSeconds,
        totalMinutes: Math.floor(totalSeconds / 60),
        totalHours: Math.round(totalSeconds / 360) / 10,
        uniqueDays,
        firstDate,
    }
}

/**
 * 日历热力图数据
 * 返回 { '2025-10-07': 3600, ... }
 */
export function getCalendarData() {
    const history = getHistory()
    const map = {}
    for (const h of history) {
        map[h.date] = (map[h.date] || 0) + (h.duration || 0)
    }
    return map
}

/**
 * 成就列表
 */
export function getAchievements() {
    const stats = getStats()
    const history = getHistory()

    // 连续周数检查
    const dates = new Set(history.map(h => h.date))
    const now = new Date()
    let weekStreak = 0
    for (let i = 0; i < 52; i++) {
        const weekStart = new Date(now)
        weekStart.setDate(weekStart.getDate() - (now.getDay() || 7) + 1 - i * 7)
        let hasThisWeek = false
        for (let d = 0; d < 7; d++) {
            const day = new Date(weekStart)
            day.setDate(day.getDate() + d)
            if (dates.has(formatDate(day))) { hasThisWeek = true; break }
        }
        if (hasThisWeek) weekStreak++
        else if (i > 0) break
    }

    const nightOwl = history.some(h => {
        const hr = new Date(h.time).getHours()
        return hr >= 2 && hr < 5
    })
    const marathon = history.some(h => h.duration >= 10800)
    const firstDate = stats.firstDate ? new Date(stats.firstDate) : null
    const daysSinceFirst = firstDate
        ? Math.floor((Date.now() - firstDate.getTime()) / 86400000)
        : 0

    return [
        {
            id: 'first',
            emoji: '🎬',
            name: '首映礼',
            desc: '第一次一起看',
            unlocked: stats.totalSessions >= 1,
        },
        {
            id: 'five',
            emoji: '🎭',
            name: '影迷',
            desc: '累计看 5 部',
            unlocked: stats.totalSessions >= 5,
        },
        {
            id: 'ten',
            emoji: '🏆',
            name: '资深影迷',
            desc: '累计看 10 部',
            unlocked: stats.totalSessions >= 10,
            progress: `${Math.min(stats.totalSessions, 10)}/10`,
        },
        {
            id: 'hours10',
            emoji: '⏰',
            name: '十小时',
            desc: '累计看 10 小时',
            unlocked: stats.totalSeconds >= 36000,
        },
        {
            id: 'hours50',
            emoji: '💫',
            name: '五十小时',
            desc: '累计看 50 小时',
            unlocked: stats.totalSeconds >= 180000,
        },
        {
            id: 'nights',
            emoji: '🌙',
            name: '深夜党',
            desc: '凌晨 2 点后还在看',
            unlocked: nightOwl,
        },
        {
            id: 'marathon',
            emoji: '🔥',
            name: '马拉松',
            desc: '单次超过 3 小时',
            unlocked: marathon,
        },
        {
            id: 'weekstreak',
            emoji: '📅',
            name: '周更',
            desc: '连续 4 周都一起看',
            unlocked: weekStreak >= 4,
            progress: `${Math.min(weekStreak, 4)}/4`,
        },
        {
            id: 'days100',
            emoji: '💖',
            name: '百日纪念',
            desc: '一起看 100 天',
            unlocked: daysSinceFirst >= 100,
            progress: `${Math.min(daysSinceFirst, 100)}/100`,
        },
    ]
}

/**
 * 清空所有记录（调试用）
 */
export function clearHistory() {
    localStorage.removeItem(STORAGE_KEY)
}