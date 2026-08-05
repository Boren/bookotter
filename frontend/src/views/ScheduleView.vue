<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useKindlesStore } from '../stores/kindles'
import type { Schedule } from '../types'

const schedules = ref<Schedule[]>([])
const kindlesStore = useKindlesStore()
const kindles = computed(() => kindlesStore.kindles)
const loading = ref(true)
const showForm = ref(false)
const editingId = ref<string | null>(null)

// Form state
const form = ref({
  name: '',
  cron_expression: '0 2 * * *',
  kindle_device: '',
  dry_run: false,
})

const cronPresets = [
  { label: 'Daily at 2am', value: '0 2 * * *' },
  { label: 'Midnight', value: '0 0 * * *' },
  { label: 'Every 6 hours', value: '0 */6 * * *' },
  { label: 'Sundays 3am', value: '0 3 * * 0' },
  { label: 'Weekdays 7am', value: '0 7 * * 1-5' },
]

const fetchSchedules = async () => {
  try {
    const response = await fetch('/api/schedules')
    schedules.value = await response.json()
  } catch (e) {
    console.error('Failed to fetch schedules:', e)
  }
}

const openForm = (schedule?: Schedule) => {
  if (schedule) {
    editingId.value = schedule.id
    form.value = {
      name: schedule.name,
      cron_expression: schedule.cron_expression,
      kindle_device: schedule.kindle_device || '',
      dry_run: schedule.dry_run,
    }
  } else {
    editingId.value = null
    form.value = {
      name: '',
      cron_expression: '0 2 * * *',
      kindle_device: kindles.value[0]?.id || '',
      dry_run: false,
    }
  }
  showForm.value = true
}

const closeForm = () => {
  showForm.value = false
  editingId.value = null
}

const saveSchedule = async () => {
  try {
    const url = editingId.value
      ? `/api/schedules/${editingId.value}`
      : '/api/schedules'
    const method = editingId.value ? 'PUT' : 'POST'

    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })

    if (!response.ok) {
      const error = await response.json()
      alert(error.detail || 'Failed to save schedule')
      return
    }

    closeForm()
    fetchSchedules()
  } catch (e) {
    console.error('Failed to save schedule:', e)
  }
}

const toggleSchedule = async (id: string) => {
  try {
    await fetch(`/api/schedules/${id}/toggle`, { method: 'POST' })
    fetchSchedules()
  } catch (e) {
    console.error('Failed to toggle schedule:', e)
  }
}

const deleteSchedule = async (id: string) => {
  if (!confirm('Delete this schedule?')) return

  try {
    await fetch(`/api/schedules/${id}`, { method: 'DELETE' })
    fetchSchedules()
  } catch (e) {
    console.error('Failed to delete schedule:', e)
  }
}

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return 'Never'
  return new Date(dateStr).toLocaleString()
}

onMounted(async () => {
  await Promise.all([fetchSchedules(), kindlesStore.fetchKindles()])
  loading.value = false
})
</script>

<template>
  <div class="space-y-8">
    <!-- Page Header -->
    <div class="flex items-start justify-between">
      <div class="page-header mb-0">
        <h1 class="page-title">Schedules</h1>
        <p class="page-subtitle">Configure automatic sync schedules</p>
      </div>
      <button @click="openForm()" class="btn btn-primary">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
        </svg>
        Add Schedule
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-kindle-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Loading schedules...</span>
      </div>
    </div>

    <!-- Schedules List -->
    <div v-else-if="schedules.length > 0" class="space-y-4">
      <div
        v-for="(schedule, index) in schedules"
        :key="schedule.id"
        class="card animate-fade-in-up"
        :style="{ animationDelay: `${index * 50}ms` }"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-4">
            <!-- Toggle Switch -->
            <button
              @click="toggleSchedule(schedule.id)"
              class="toggle focus-ring"
              :class="schedule.enabled ? 'toggle-on' : 'toggle-off'"
            >
              <span class="toggle-knob"></span>
            </button>
            <div>
              <p class="font-semibold text-stone-900">{{ schedule.name }}</p>
              <p class="text-sm text-stone-500 font-mono">{{ schedule.cron_expression }}</p>
            </div>
          </div>

          <div class="flex items-center gap-4">
            <div class="text-right hidden sm:block">
              <p class="text-xs font-medium uppercase tracking-wider text-stone-600">Next run</p>
              <p class="text-sm font-medium text-stone-800">{{ formatDate(schedule.next_run_at) }}</p>
            </div>
            <button
              @click="openForm(schedule)"
              class="p-2 rounded-lg text-stone-500 hover:text-stone-700 hover:bg-stone-100 transition-colors"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
            </button>
            <button
              @click="deleteSchedule(schedule.id)"
              class="p-2 rounded-lg text-stone-500 hover:text-error-600 hover:bg-error-50 transition-colors"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap gap-2">
          <span v-if="schedule.dry_run" class="badge badge-warning">
            Dry run
          </span>
          <span v-if="schedule.kindle_device" class="badge badge-neutral">
            {{ kindles.find(k => k.id === schedule.kindle_device)?.name || schedule.kindle_device }}
          </span>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else class="card">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
          </svg>
        </div>
        <p class="empty-state-title">No schedules configured</p>
        <p class="empty-state-description">
          Create a schedule to automatically sync your books
        </p>
        <button @click="openForm()" class="btn btn-primary">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
          </svg>
          Create Schedule
        </button>
      </div>
    </div>

    <!-- Form Modal -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="showForm" class="modal-overlay" @click.self="closeForm">
        <div class="modal-content">
          <div class="flex items-center justify-between mb-6">
            <h2 class="text-xl font-display font-semibold text-stone-900">
              {{ editingId ? 'Edit Schedule' : 'New Schedule' }}
            </h2>
            <button @click="closeForm" class="p-2 rounded-lg text-stone-500 hover:text-stone-700 hover:bg-stone-100 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>

          <div class="space-y-5">
            <div>
              <label class="label">Name</label>
              <input v-model="form.name" type="text" class="input" placeholder="Daily sync" />
            </div>

            <div>
              <label class="label">Cron Expression</label>
              <input v-model="form.cron_expression" type="text" class="input font-mono" />
              <div class="mt-2 flex flex-wrap gap-2">
                <button
                  v-for="preset in cronPresets"
                  :key="preset.value"
                  @click="form.cron_expression = preset.value"
                  class="text-xs px-2.5 py-1.5 bg-stone-100 hover:bg-stone-200 text-stone-600 rounded-lg transition-colors"
                >
                  {{ preset.label }}
                </button>
              </div>
            </div>

            <div>
              <label class="label">Target Kindle</label>
              <select v-model="form.kindle_device" class="input">
                <option value="">Default (first configured)</option>
                <option v-for="kindle in kindles" :key="kindle.id" :value="kindle.id">
                  {{ kindle.name }}
                </option>
              </select>
            </div>

            <div>
              <label class="flex items-center gap-3 p-3 rounded-xl bg-stone-50 border border-stone-200 cursor-pointer hover:bg-stone-100 transition-colors">
                <input type="checkbox" v-model="form.dry_run" class="sr-only peer" />
                <div class="toggle" :class="form.dry_run ? 'toggle-on' : 'toggle-off'">
                  <span class="toggle-knob"></span>
                </div>
                <div>
                  <span class="text-sm font-medium text-stone-700">Dry Run Mode</span>
                  <p class="text-xs text-stone-500">Simulate without transferring files</p>
                </div>
              </label>
            </div>
          </div>

          <div class="mt-6 flex justify-end gap-3">
            <button @click="closeForm" class="btn btn-secondary">Cancel</button>
            <button @click="saveSchedule" class="btn btn-primary">
              {{ editingId ? 'Save Changes' : 'Create Schedule' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
