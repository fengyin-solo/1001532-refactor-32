<template>
  <section class="page" data-module="contract">
    <header class="page-head">
      <div>
        <h2>运维合同管理</h2>
        <p class="page-desc">维护运维合同，围绕合同编号、服务单位、合同金额、服务期限做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记运维合同</button>
        <button class="btn" type="button" @click="exportRows">导出运维合同清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '合同状态'">
              <span :title="row.expiry_note ? String(row.expiry_note) : ''" :class="['status-tag', statusClass(row)]">
                {{ row[column] ?? '—' }}
                <em v-if="row.expiring" class="status-warn">即将到期</em>
              </span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无运维合同数据，可先登记运维合同</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条运维合同记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/contract'
const columns = ["合同编号", "服务单位", "合同金额", "服务期限", "考核方式", "签订人员", "到期日期", "合同状态"]
const actions = ["确认签订", "标记到期", "终止合同"]
const stats = ref([
  { label: '履行中合同', value: 0 },
  { label: '即将到期合同', value: 0 },
  { label: '超期合同', value: 0 },
  { label: '合同总金额', value: '—' },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function statusClass(row: Row) {
  if (row.overdue) return 'status-expired'
  if (row.status === '已终止') return 'status-terminated'
  if (row.expiring) return 'status-expiring'
  if (row.expiry_note) return 'status-issue'
  return ''
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '运维合同登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '运维合同动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '运维合同操作失败'
  }
}

// 列表与统计卡同一份接口口径，一起刷新，避免返回后两边对不上
async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResponse.ok) {
      throw new Error('运维合同列表读取失败')
    }
    if (!statsResponse.ok) {
      throw new Error('运维合同统计读取失败')
    }
    const payload = await listResponse.json()
    const summary = await statsResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = [
      { label: '履行中合同', value: summary.active_count ?? 0 },
      { label: '即将到期合同', value: summary.expiring_count ?? 0 },
      { label: '超期合同', value: summary.overdue_count ?? 0 },
      { label: '合同总金额', value: summary.total_amount ?? '—' },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '运维合同列表读取失败'
  }
}

onMounted(reload)
</script>
