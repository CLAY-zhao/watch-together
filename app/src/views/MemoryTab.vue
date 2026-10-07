<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getHistory, getStats, getCalendarData, getAchievements } from '@/utils/watchHistory'

const stats = ref({ totalSessions: 0, totalHours: 0, uniqueDays: 0, firstDate: null })
const calendarMap = ref({})
const achievements = ref([])
const recentHistory = ref([])
const currentYear = ref(new Date().getFullYear())

/* 图表需要的数据 */
const calendarCells = ref([])

function formatDate(d) {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${dd}`
}

function formatDuration(sec) {
    if (!sec) return '0m'
    const h = Math.floor(sec / 3600)
    const m = Math.floor((sec % 3600) / 60)
    if (h > 0) return `${h}h${m}m`
    return `${m}m`
}

function formatDateCN(dateStr) {
    if (!dateStr) return ''
    const [y, m, d] = dateStr.split('-')
    return `${y}年${parseInt(m)}月${parseInt(d)}日`
}

/* 生成日历格子（最近 52 周） */
function buildCalendarCells() {
    const map = calendarMap.value
    const today = new Date()
    // 本周的周日
    const thisSunday = new Date(today)
    thisSunday.setDate(thisSunday.getDate() - today.getDay())

    // 起点：51 周前的周日（共 52 周 = 364 天）
    const startDate = new Date(thisSunday)
    startDate.setDate(startDate.getDate() - 51 * 7)

    const cells = []
    for (let w = 0; w < 52; w++) {
        for (let d = 0; d < 7; d++) {
            const date = new Date(startDate)
            date.setDate(date.getDate() + w * 7 + d)

            const dateStr = formatDate(date)
            const seconds = map[dateStr] || 0
            const isFuture = date > today

            let level = 0
            if (seconds > 0) {
                if (seconds < 1800) level = 1        // < 30min
                else if (seconds < 7200) level = 2   // < 2h
                else if (seconds < 14400) level = 3  // < 4h
                else level = 4                       // 4h+
            }

            cells.push({
                date: dateStr,
                seconds,
                level,
                isFuture,
                week: w,
                day: d,
            })
        }
    }
    calendarCells.value = cells
}

/* 分月标签 */
const monthLabels = computed(() => {
    const labels = []
    const today = new Date()
    const thisSunday = new Date(today)
    thisSunday.setDate(thisSunday.getDate() - today.getDay())
    const startDate = new Date(thisSunday)
    startDate.setDate(startDate.getDate() - 51 * 7)

    let lastMonth = -1
    for (let w = 0; w < 52; w++) {
        const d = new Date(startDate)
        d.setDate(d.getDate() + w * 7)
        const m = d.getMonth()
        if (m !== lastMonth) {
            labels.push({ week: w, month: m + 1 })
            lastMonth = m
        }
    }
    return labels
})

function reload() {
    stats.value = getStats()
    calendarMap.value = getCalendarData()
    achievements.value = getAchievements()

    const h = getHistory()
    recentHistory.value = h.slice().reverse().slice(0, 20)

    buildCalendarCells()
}

let refreshTimer = null

onMounted(() => {
    reload()
    // 每 30 秒刷新一次（正在看的时候数据会变）
    refreshTimer = setInterval(reload, 30000)
})

onUnmounted(() => {
    if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
    <div class="memory-tab">

        <!-- 头部 -->
        <header class="memory-header">
            <h1 class="memory-header__title">
                <span class="memory-header__star">⭐</span>
                观影回忆
            </h1>
            <p class="memory-header__sub" v-if="stats.firstDate">
                从 {{ formatDateCN(stats.firstDate) }} 开始
            </p>
            <p class="memory-header__sub" v-else>
                还没有记录，去看场电影吧～
            </p>
        </header>

        <!-- 统计卡 -->
        <section class="stats-card">
            <div class="stats-card__glow"></div>

            <div class="stat">
                <div class="stat__num">{{ stats.totalSessions }}</div>
                <div class="stat__label">部电影</div>
            </div>

            <div class="stat__divider"></div>

            <div class="stat">
                <div class="stat__num">{{ stats.totalHours }}</div>
                <div class="stat__label">小时</div>
            </div>

            <div class="stat__divider"></div>

            <div class="stat">
                <div class="stat__num">{{ stats.uniqueDays }}</div>
                <div class="stat__label">天</div>
            </div>
        </section>

        <!-- 日历热力图 -->
        <section class="memory-section">
            <div class="memory-section__head">
                <span class="memory-section__dot"></span>
                <span class="memory-section__title">观影日历</span>
                <span class="memory-section__hint">最近一年</span>
            </div>

            <div class="calendar-wrap">
                <!-- 月份标签 -->
                <div class="calendar-months">
                    <span v-for="m in monthLabels" :key="m.week" class="calendar-month"
                        :style="{ left: (m.week * 14) + 'px' }">{{ m.month }}月</span>
                </div>

                <!-- 格子 -->
                <div class="calendar-grid">
                    <div v-for="cell in calendarCells" :key="cell.date" class="calendar-cell" :class="[
                        'calendar-cell--level-' + cell.level,
                        { 'calendar-cell--future': cell.isFuture },
                    ]" :title="`${cell.date}: ${formatDuration(cell.seconds)}`"></div>
                </div>

                <!-- 图例 -->
                <div class="calendar-legend">
                    <span class="calendar-legend__text">少</span>
                    <div class="calendar-cell calendar-cell--level-0"></div>
                    <div class="calendar-cell calendar-cell--level-1"></div>
                    <div class="calendar-cell calendar-cell--level-2"></div>
                    <div class="calendar-cell calendar-cell--level-3"></div>
                    <div class="calendar-cell calendar-cell--level-4"></div>
                    <span class="calendar-legend__text">多</span>
                </div>
            </div>
        </section>

        <!-- 成就 -->
        <section class="memory-section">
            <div class="memory-section__head">
                <span class="memory-section__dot"></span>
                <span class="memory-section__title">成就</span>
                <span class="memory-section__hint">
                    {{achievements.filter(a => a.unlocked).length}} / {{ achievements.length }}
                </span>
            </div>

            <div class="achievements">
                <div v-for="a in achievements" :key="a.id" class="achievement"
                    :class="{ 'achievement--unlocked': a.unlocked }">
                    <div class="achievement__icon">
                        <span v-if="a.unlocked">{{ a.emoji }}</span>
                        <span v-else class="achievement__lock">🔒</span>
                    </div>
                    <div class="achievement__info">
                        <div class="achievement__name">{{ a.name }}</div>
                        <div class="achievement__desc">{{ a.desc }}</div>
                    </div>
                    <div v-if="a.progress && !a.unlocked" class="achievement__progress">
                        {{ a.progress }}
                    </div>
                </div>
            </div>
        </section>

        <!-- 观影记录 -->
        <section class="memory-section">
            <div class="memory-section__head">
                <span class="memory-section__dot"></span>
                <span class="memory-section__title">观影记录</span>
                <span class="memory-section__hint">{{ recentHistory.length }} 条</span>
            </div>

            <div v-if="recentHistory.length === 0" class="history-empty">
                还没有观影记录
            </div>

            <div v-else class="history-list">
                <div v-for="h in recentHistory" :key="h.id" class="history-item">
                    <div class="history-item__dot"></div>
                    <div class="history-item__body">
                        <div class="history-item__date">{{ formatDateCN(h.date) }}</div>
                        <div class="history-item__meta">
                            <span v-if="h.movieName" class="history-item__name">{{ h.movieName }}</span>
                            <span v-else class="history-item__name history-item__name--empty">未命名</span>
                            <span class="history-item__sep">·</span>
                            <span class="history-item__duration">{{ formatDuration(h.duration) }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 底部留白 -->
        <div style="height: 20px"></div>
    </div>
</template>

<style scoped>
.memory-tab {
    padding: calc(env(safe-area-inset-top, 0px) + 24px) 16px 24px;
    display: flex;
    flex-direction: column;
    gap: 18px;
    max-width: 480px;
    margin: 0 auto;
}

/* 头部 */
.memory-header {
    text-align: left;
    padding: 0 4px;
}

.memory-header__title {
    margin: 0;
    font-size: 26px;
    font-weight: 800;
    color: #f1f5f9;
    letter-spacing: -0.02em;
    display: flex;
    align-items: center;
    gap: 10px;
}

.memory-header__star {
    font-size: 24px;
    filter: drop-shadow(0 0 12px rgba(255, 215, 0, 0.6));
}

.memory-header__sub {
    margin: 8px 0 0;
    font-size: 12.5px;
    color: #94a3b8;
}

/* 统计卡 */
.stats-card {
    position: relative;
    padding: 22px 18px;
    border-radius: 22px;
    background: linear-gradient(135deg,
            rgba(124, 107, 255, 0.14) 0%,
            rgba(79, 140, 255, 0.08) 100%);
    border: 1px solid rgba(124, 107, 255, 0.28);
    display: flex;
    align-items: center;
    justify-content: space-around;
    overflow: hidden;
    box-shadow:
        0 20px 50px -20px rgba(124, 107, 255, 0.5),
        0 1px 0 rgba(255, 255, 255, 0.06) inset;
    animation: cardIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes cardIn {
    0% {
        opacity: 0;
        transform: translateY(12px);
    }

    100% {
        opacity: 1;
        transform: translateY(0);
    }
}

.stats-card__glow {
    position: absolute;
    top: -60%;
    left: 50%;
    width: 200px;
    height: 200px;
    transform: translateX(-50%);
    background: radial-gradient(circle, rgba(124, 107, 255, 0.4) 0%, transparent 65%);
    filter: blur(40px);
    pointer-events: none;
    animation: glowFloat 6s ease-in-out infinite alternate;
}

@keyframes glowFloat {
    0% {
        transform: translateX(-50%) scale(1);
    }

    100% {
        transform: translateX(-50%) scale(1.3);
    }
}

.stat {
    position: relative;
    flex: 1;
    text-align: center;
}

.stat__num {
    font-size: 30px;
    font-weight: 800;
    background: linear-gradient(180deg, #ffffff 0%, #b8b1ff 100%);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    line-height: 1;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
}

.stat__label {
    margin-top: 6px;
    font-size: 11.5px;
    color: #94a3b8;
    letter-spacing: 0.06em;
}

.stat__divider {
    width: 1px;
    height: 32px;
    background: linear-gradient(180deg, transparent, rgba(255, 255, 255, 0.12), transparent);
}

/* 分区 */
.memory-section {
    padding: 18px;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    display: flex;
    flex-direction: column;
    gap: 14px;
    animation: cardIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 0.05s both;
}

.memory-section__head {
    display: flex;
    align-items: center;
    gap: 8px;
}

.memory-section__dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #7c6bff;
    box-shadow: 0 0 8px #7c6bff;
    animation: dotPulse 2s ease-in-out infinite;
}

@keyframes dotPulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.4;
    }
}

.memory-section__title {
    font-size: 13px;
    font-weight: 700;
    color: #f1f5f9;
    letter-spacing: 0.02em;
}

.memory-section__hint {
    margin-left: auto;
    font-size: 11px;
    color: #64748b;
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.04);
}

/* 日历 */
.calendar-wrap {
    position: relative;
    padding: 20px 4px 4px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}

.calendar-wrap::-webkit-scrollbar {
    height: 0;
    display: none;
}

.calendar-months {
    position: relative;
    height: 14px;
    margin-bottom: 4px;
}

.calendar-month {
    position: absolute;
    top: 0;
    font-size: 10px;
    color: #64748b;
    white-space: nowrap;
}

.calendar-grid {
    display: grid;
    grid-template-rows: repeat(7, 12px);
    grid-auto-flow: column;
    grid-auto-columns: 12px;
    gap: 2px;
    width: max-content;
}

.calendar-cell {
    width: 12px;
    height: 12px;
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.05);
    transition: transform 0.15s;
}

.calendar-cell:active:not(.calendar-cell--future) {
    transform: scale(1.3);
}

.calendar-cell--future {
    opacity: 0.25;
}

.calendar-cell--level-0 {
    background: rgba(255, 255, 255, 0.05);
}

.calendar-cell--level-1 {
    background: rgba(124, 107, 255, 0.35);
}

.calendar-cell--level-2 {
    background: rgba(124, 107, 255, 0.55);
}

.calendar-cell--level-3 {
    background: rgba(124, 107, 255, 0.75);
}

.calendar-cell--level-4 {
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    box-shadow: 0 0 8px rgba(124, 107, 255, 0.7);
}

.calendar-legend {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 10px;
    justify-content: flex-end;
}

.calendar-legend__text {
    font-size: 10px;
    color: #64748b;
    padding: 0 4px;
}

/* 成就 */
.achievements {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
}

.achievement {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 12px;
    opacity: 0.45;
    transition: all 0.2s;
}

.achievement--unlocked {
    opacity: 1;
    background: linear-gradient(135deg,
            rgba(124, 107, 255, 0.12) 0%,
            rgba(79, 140, 255, 0.06) 100%);
    border-color: rgba(124, 107, 255, 0.3);
    box-shadow: 0 4px 16px -6px rgba(124, 107, 255, 0.4);
}

.achievement__icon {
    width: 32px;
    height: 32px;
    flex: none;
    border-radius: 10px;
    display: grid;
    place-items: center;
    background: rgba(255, 255, 255, 0.05);
    font-size: 18px;
    filter: grayscale(1);
}

.achievement--unlocked .achievement__icon {
    background: linear-gradient(135deg, #7c6bff, #4f8cff);
    filter: none;
    box-shadow: 0 4px 12px -4px rgba(124, 107, 255, 0.8);
}

.achievement__lock {
    font-size: 14px;
    filter: grayscale(0.5);
}

.achievement__info {
    flex: 1;
    min-width: 0;
}

.achievement__name {
    font-size: 12.5px;
    font-weight: 700;
    color: #f1f5f9;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.achievement__desc {
    font-size: 10.5px;
    color: #64748b;
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.achievement__progress {
    font-size: 10.5px;
    font-weight: 700;
    color: #7c6bff;
    font-variant-numeric: tabular-nums;
    flex: none;
}

/* 记录 */
.history-empty {
    padding: 24px 0;
    text-align: center;
    font-size: 12.5px;
    color: #475569;
}

.history-list {
    display: flex;
    flex-direction: column;
    position: relative;
    padding-left: 16px;
}

.history-list::before {
    content: '';
    position: absolute;
    left: 3px;
    top: 8px;
    bottom: 8px;
    width: 1px;
    background: linear-gradient(180deg,
            rgba(124, 107, 255, 0.4),
            rgba(124, 107, 255, 0.1),
            transparent);
}

.history-item {
    position: relative;
    padding: 8px 0 8px 12px;
    display: flex;
    gap: 10px;
    align-items: center;
}

.history-item__dot {
    position: absolute;
    left: -16px;
    top: 50%;
    transform: translateY(-50%);
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #7c6bff;
    box-shadow: 0 0 8px rgba(124, 107, 255, 0.8);
}

.history-item__body {
    flex: 1;
    min-width: 0;
}

.history-item__date {
    font-size: 12.5px;
    font-weight: 600;
    color: #f1f5f9;
}

.history-item__meta {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 3px;
    font-size: 11px;
    color: #94a3b8;
}

.history-item__name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 60%;
}

.history-item__name--empty {
    color: #475569;
    font-style: italic;
}

.history-item__sep {
    color: #334155;
}

.history-item__duration {
    font-variant-numeric: tabular-nums;
}
</style>