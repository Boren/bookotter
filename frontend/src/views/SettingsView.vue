<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { Config, Kindle, RootFolder, FolderOrganization } from '../types'

const config = ref<Config | null>(null)
const loading = ref(true)
const saving = ref(false)
const testResults = ref<Record<string, { success: boolean; message?: string; error?: string }>>({})
const testingService = ref<string | null>(null)

// Kindle form
const showKindleForm = ref(false)
const editingKindleId = ref<string | null>(null)
const kindleForm = ref({
  name: '',
  hostname: '',
  port: 22,
  username: 'root',
  password: '',
  ssh_key_path: '~/.ssh/id_rsa',
  destination_path: '/mnt/us/books/',
})

// Root folders
const rootFolders = ref<RootFolder[]>([])
const loadingFolders = ref(false)
const showRootFolderForm = ref(false)
const rootFolderForm = ref({
  name: '',
  path: '',
  folder_organization: 'flat' as FolderOrganization,
})
const rootFolderError = ref<string | null>(null)

const fetchConfig = async () => {
  try {
    const response = await fetch('/api/config')
    config.value = await response.json()
  } catch (e) {
    console.error('Failed to fetch config:', e)
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  if (!config.value) return
  saving.value = true

  try {
    const response = await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: config.value }),
    })

    if (response.ok) {
      const data = await response.json()
      config.value = data.config
    }
  } catch (e) {
    console.error('Failed to save config:', e)
  } finally {
    saving.value = false
  }
}

const testConnection = async (service: string, kindleId?: string) => {
  const key = kindleId ? `kindle_${kindleId}` : service
  testingService.value = key

  try {
    let url: string
    let body: object | undefined

    if (service === 'hardcover') {
      url = '/api/config/test/hardcover'
      body = {
        api_token: config.value?.hardcover?.api_token,
        api_url: config.value?.hardcover?.api_url
      }
    } else if (service === 'prowlarr') {
      url = '/prowlarr/test'
    } else if (service === 'qbittorrent') {
      url = '/qbittorrent/test'
    } else if (kindleId) {
      url = `/api/config/test/kindle/${kindleId}`
    } else {
      url = `/api/config/test/${service}`
    }

    const response = await fetch(url, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined
    })
    testResults.value[key] = await response.json()
  } catch (e) {
    testResults.value[key] = { success: false, error: 'Connection failed' }
  } finally {
    testingService.value = null
  }
}

// Kindle management
const openKindleForm = (kindle?: Kindle) => {
  if (kindle) {
    editingKindleId.value = kindle.id
    kindleForm.value = {
      name: kindle.name,
      hostname: kindle.hostname,
      port: kindle.port,
      username: kindle.username,
      password: '',
      ssh_key_path: kindle.ssh_key_path || '',
      destination_path: kindle.destination_path,
    }
  } else {
    editingKindleId.value = null
    kindleForm.value = {
      name: '',
      hostname: '',
      port: 22,
      username: 'root',
      password: '',
      ssh_key_path: '~/.ssh/id_rsa',
      destination_path: '/mnt/us/books/',
    }
  }
  showKindleForm.value = true
}

const closeKindleForm = () => {
  showKindleForm.value = false
  editingKindleId.value = null
}

const saveKindle = async () => {
  try {
    const url = editingKindleId.value
      ? `/api/kindles/${editingKindleId.value}`
      : '/api/kindles'
    const method = editingKindleId.value ? 'PUT' : 'POST'

    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(kindleForm.value),
    })

    if (response.ok) {
      closeKindleForm()
      fetchConfig()
    }
  } catch (e) {
    console.error('Failed to save kindle:', e)
  }
}

const deleteKindle = async (id: string) => {
  if (!confirm('Delete this Kindle?')) return

  try {
    await fetch(`/api/kindles/${id}`, { method: 'DELETE' })
    fetchConfig()
  } catch (e) {
    console.error('Failed to delete kindle:', e)
  }
}

// Root folder management
const fetchRootFolders = async () => {
  loadingFolders.value = true
  try {
    const response = await fetch('/api/root-folders')
    if (response.ok) {
      const data = await response.json()
      rootFolders.value = data.folders
    }
  } catch (e) {
    console.error('Failed to fetch root folders:', e)
  } finally {
    loadingFolders.value = false
  }
}

const openRootFolderForm = () => {
  rootFolderForm.value = { name: '', path: '', folder_organization: 'flat' }
  rootFolderError.value = null
  showRootFolderForm.value = true
}

const closeRootFolderForm = () => {
  showRootFolderForm.value = false
  rootFolderError.value = null
}

const saveRootFolder = async () => {
  rootFolderError.value = null
  try {
    const response = await fetch('/api/root-folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rootFolderForm.value),
    })

    if (response.ok) {
      closeRootFolderForm()
      fetchRootFolders()
    } else {
      const data = await response.json()
      rootFolderError.value = data.detail || 'Failed to create root folder'
    }
  } catch (e) {
    rootFolderError.value = 'Failed to create root folder'
  }
}

const deleteRootFolder = async (id: number) => {
  if (!confirm('Delete this root folder?')) return

  try {
    await fetch(`/api/root-folders/${id}`, { method: 'DELETE' })
    fetchRootFolders()
  } catch (e) {
    console.error('Failed to delete root folder:', e)
  }
}

const folderOrgLabel = (org: string) => {
  const labels: Record<string, string> = {
    flat: 'Flat',
    author: 'By Author',
    series: 'By Series',
    author_series: 'Author / Series',
  }
  return labels[org] || org
}

onMounted(() => {
  fetchConfig()
  fetchRootFolders()
})
</script>

<template>
  <div class="space-y-8">
    <!-- Page Header -->
    <div class="page-header">
      <h1 class="page-title">Settings</h1>
      <p class="page-subtitle">Configure BookOtter connections and preferences</p>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-kindle-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Loading settings...</span>
      </div>
    </div>

    <template v-else-if="config">
      <!-- Hardcover Settings -->
      <div class="card">
        <div class="flex items-center justify-between mb-6">
          <div class="flex items-center gap-3">
            <div class="icon-container-primary">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
              </svg>
            </div>
            <div>
              <h2 class="text-lg font-display font-semibold text-stone-900">Hardcover</h2>
              <p class="text-sm text-stone-500">Your reading list source</p>
            </div>
          </div>
          <button
            @click="testConnection('hardcover')"
            :disabled="testingService === 'hardcover'"
            class="btn btn-secondary"
          >
            <svg v-if="testingService === 'hardcover'" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span v-else>Test Connection</span>
          </button>
        </div>

        <div v-if="testResults.hardcover" class="mb-6 p-4 rounded-xl animate-fade-in" :class="testResults.hardcover.success ? 'bg-success-50 border border-success-100' : 'bg-error-50 border border-error-100'">
          <p class="text-sm font-medium" :class="testResults.hardcover.success ? 'text-success-700' : 'text-error-700'">
            {{ testResults.hardcover.success ? testResults.hardcover.message : testResults.hardcover.error }}
          </p>
        </div>

        <div class="space-y-4">
          <div>
            <label class="label">API Token</label>
            <input v-model="config.hardcover.api_token" type="password" class="input" />
            <p class="mt-1.5 text-xs text-stone-500">
              Get from <a href="https://hardcover.app/account/api" target="_blank" class="text-kindle-600 hover:text-kindle-700 underline underline-offset-2">hardcover.app/account/api</a>
            </p>
          </div>
          <div>
            <label class="label">API URL</label>
            <input v-model="config.hardcover.api_url" type="text" class="input" />
          </div>
        </div>
      </div>

      <!-- Prowlarr Settings -->
      <div class="card">
        <div class="flex items-center justify-between mb-6">
          <div class="flex items-center gap-3">
            <div class="icon-container">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7"/>
              </svg>
            </div>
            <div>
              <h2 class="text-lg font-display font-semibold text-stone-900">Prowlarr</h2>
              <p class="text-sm text-stone-500">Indexer manager for book searches</p>
            </div>
          </div>
          <button
            @click="testConnection('prowlarr')"
            :disabled="testingService === 'prowlarr'"
            class="btn btn-secondary"
          >
            <svg v-if="testingService === 'prowlarr'" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span v-else>Test Connection</span>
          </button>
        </div>

        <div v-if="testResults.prowlarr" class="mb-6 p-4 rounded-xl animate-fade-in" :class="testResults.prowlarr.success ? 'bg-success-50 border border-success-100' : 'bg-error-50 border border-error-100'">
          <p class="text-sm font-medium" :class="testResults.prowlarr.success ? 'text-success-700' : 'text-error-700'">
            {{ testResults.prowlarr.success ? testResults.prowlarr.message : testResults.prowlarr.error }}
          </p>
        </div>

        <div class="space-y-4">
          <div>
            <label class="label">Base URL</label>
            <input v-model="config.prowlarr.base_url" type="text" class="input" placeholder="http://localhost:9696" />
          </div>
          <div>
            <label class="label">API Key</label>
            <input v-model="config.prowlarr.api_key" type="password" class="input" />
            <p class="mt-1.5 text-xs text-stone-500">
              Found in Prowlarr under Settings &rarr; General &rarr; API Key
            </p>
          </div>
        </div>
      </div>

      <!-- qBittorrent Settings -->
      <div class="card">
        <div class="flex items-center justify-between mb-6">
          <div class="flex items-center gap-3">
            <div class="icon-container">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
              </svg>
            </div>
            <div>
              <h2 class="text-lg font-display font-semibold text-stone-900">qBittorrent</h2>
              <p class="text-sm text-stone-500">Download client for book files</p>
            </div>
          </div>
          <button
            @click="testConnection('qbittorrent')"
            :disabled="testingService === 'qbittorrent'"
            class="btn btn-secondary"
          >
            <svg v-if="testingService === 'qbittorrent'" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span v-else>Test Connection</span>
          </button>
        </div>

        <div v-if="testResults.qbittorrent" class="mb-6 p-4 rounded-xl animate-fade-in" :class="testResults.qbittorrent.success ? 'bg-success-50 border border-success-100' : 'bg-error-50 border border-error-100'">
          <p class="text-sm font-medium" :class="testResults.qbittorrent.success ? 'text-success-700' : 'text-error-700'">
            {{ testResults.qbittorrent.success ? testResults.qbittorrent.message : testResults.qbittorrent.error }}
          </p>
        </div>

        <div class="space-y-4">
          <div>
            <label class="label">Base URL</label>
            <input v-model="config.qbittorrent.base_url" type="text" class="input" placeholder="http://localhost:8080" />
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="label">Username</label>
              <input v-model="config.qbittorrent.username" type="text" class="input" placeholder="admin" />
            </div>
            <div>
              <label class="label">Password</label>
              <input v-model="config.qbittorrent.password" type="password" class="input" />
            </div>
          </div>
          <div>
            <label class="label">Category</label>
            <input v-model="config.qbittorrent.category" type="text" class="input" placeholder="books" />
            <p class="mt-1.5 text-xs text-stone-500">
              Downloads will be tagged with this category in qBittorrent
            </p>
          </div>
        </div>
      </div>

      <!-- Root Folders -->
      <div class="card">
        <div class="flex items-center justify-between mb-6">
          <div class="flex items-center gap-3">
            <div class="icon-container-primary">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
              </svg>
            </div>
            <div>
              <h2 class="text-lg font-display font-semibold text-stone-900">Root Folders</h2>
              <p class="text-sm text-stone-500">Where your book library is stored</p>
            </div>
          </div>
          <button @click="openRootFolderForm()" class="btn btn-primary">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
            </svg>
            Add Folder
          </button>
        </div>

        <div v-if="loadingFolders" class="flex justify-center py-8">
          <div class="flex items-center gap-3 text-stone-500">
            <svg class="animate-spin h-5 w-5 text-kindle-600" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span class="text-sm font-medium">Loading folders...</span>
          </div>
        </div>

        <div v-else-if="rootFolders.length === 0" class="text-center py-8 text-stone-500">
          <p class="text-sm">No root folders configured</p>
          <p class="text-xs mt-1 text-stone-400">Add a folder to organize your book library</p>
        </div>

        <div v-else class="space-y-3">
          <div
            v-for="folder in rootFolders"
            :key="folder.id"
            class="border border-stone-200 rounded-xl p-4 hover:border-stone-300 transition-colors"
          >
            <div class="flex items-center justify-between">
              <div class="min-w-0 flex-1">
                <p class="font-medium text-stone-900">{{ folder.name }}</p>
                <p class="text-sm text-stone-500 font-mono truncate">{{ folder.path }}</p>
                <span class="inline-flex items-center mt-1.5 px-2 py-0.5 rounded-md text-xs font-medium bg-stone-100 text-stone-600">
                  {{ folderOrgLabel(folder.folder_organization) }}
                </span>
              </div>
              <button
                @click="deleteRootFolder(folder.id)"
                class="shrink-0 ml-4 p-2 rounded-lg text-stone-500 hover:text-error-600 hover:bg-error-50 transition-colors"
              >
                <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Kindle Devices -->
      <div class="card">
        <div class="flex items-center justify-between mb-6">
          <div class="flex items-center gap-3">
            <div class="icon-container">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"/>
              </svg>
            </div>
            <div>
              <h2 class="text-lg font-display font-semibold text-stone-900">Kindle Devices</h2>
              <p class="text-sm text-stone-500">Target devices for book transfers</p>
            </div>
          </div>
          <button @click="openKindleForm()" class="btn btn-primary">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
            </svg>
            Add Kindle
          </button>
        </div>

        <div v-if="config.kindles.length === 0" class="text-center py-8 text-stone-500">
          <p class="text-sm">No Kindle devices configured</p>
        </div>

        <div v-else class="space-y-4">
          <div
            v-for="kindle in config.kindles"
            :key="kindle.id"
            class="border border-stone-200 rounded-xl p-4 hover:border-stone-300 transition-colors"
          >
            <div class="flex items-center justify-between">
              <div>
                <p class="font-medium text-stone-900">{{ kindle.name }}</p>
                <p class="text-sm text-stone-500 font-mono">{{ kindle.hostname }}:{{ kindle.port }}</p>
              </div>
              <div class="flex items-center gap-2">
                <button
                  @click="testConnection('kindle', kindle.id)"
                  :disabled="testingService === `kindle_${kindle.id}`"
                  class="btn btn-secondary btn-sm"
                >
                  <svg v-if="testingService === `kindle_${kindle.id}`" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                  <span v-else>Test</span>
                </button>
                <button @click="openKindleForm(kindle)" class="p-2 rounded-lg text-stone-500 hover:text-stone-700 hover:bg-stone-100 transition-colors">
                  <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </button>
                <button @click="deleteKindle(kindle.id)" class="p-2 rounded-lg text-stone-500 hover:text-error-600 hover:bg-error-50 transition-colors">
                  <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>

            <div v-if="testResults[`kindle_${kindle.id}`]" class="mt-3 p-3 rounded-lg text-sm animate-fade-in" :class="testResults[`kindle_${kindle.id}`].success ? 'bg-success-50 text-success-700' : 'bg-error-50 text-error-700'">
              {{ testResults[`kindle_${kindle.id}`].success ? 'Connected!' : testResults[`kindle_${kindle.id}`].error }}
            </div>
          </div>
        </div>
      </div>

      <!-- Sync Settings - Book Statuses -->
      <div class="card">
        <div class="flex items-center gap-3 mb-6">
          <div class="icon-container-primary">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
            </svg>
          </div>
          <div>
            <h2 class="text-lg font-display font-semibold text-stone-900">Book Statuses to Sync</h2>
            <p class="text-sm text-stone-500">Choose which Hardcover statuses to include</p>
          </div>
        </div>
        <div class="space-y-3">
          <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-3">Books are synced in priority order</p>
          <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition-all duration-200"
            :class="config.sync.include_statuses.currently_reading
              ? 'bg-kindle-50 border-kindle-300 ring-1 ring-kindle-300'
              : 'bg-white border-stone-200 hover:border-stone-300'"
          >
            <input type="checkbox" v-model="config.sync.include_statuses.currently_reading" class="sr-only" />
            <div class="shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
              :class="config.sync.include_statuses.currently_reading ? 'bg-kindle-600 text-white' : 'bg-stone-200 text-stone-500'">1</div>
            <div class="flex-1">
              <span class="text-sm font-medium text-stone-800">Currently Reading</span>
              <p class="text-xs text-stone-500">Books you're actively reading — synced first</p>
            </div>
            <div class="toggle" :class="config.sync.include_statuses.currently_reading ? 'toggle-on' : 'toggle-off'">
              <span class="toggle-knob"></span>
            </div>
          </label>
          <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition-all duration-200"
            :class="config.sync.include_statuses.want_to_read
              ? 'bg-kindle-50 border-kindle-300 ring-1 ring-kindle-300'
              : 'bg-white border-stone-200 hover:border-stone-300'"
          >
            <input type="checkbox" v-model="config.sync.include_statuses.want_to_read" class="sr-only" />
            <div class="shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
              :class="config.sync.include_statuses.want_to_read ? 'bg-kindle-600 text-white' : 'bg-stone-200 text-stone-500'">2</div>
            <div class="flex-1">
              <span class="text-sm font-medium text-stone-800">Want to Read</span>
              <p class="text-xs text-stone-500">Your reading wishlist</p>
            </div>
            <div class="toggle" :class="config.sync.include_statuses.want_to_read ? 'toggle-on' : 'toggle-off'">
              <span class="toggle-knob"></span>
            </div>
          </label>
          <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition-all duration-200"
            :class="config.sync.include_statuses.read
              ? 'bg-kindle-50 border-kindle-300 ring-1 ring-kindle-300'
              : 'bg-white border-stone-200 hover:border-stone-300'"
          >
            <input type="checkbox" v-model="config.sync.include_statuses.read" class="sr-only" />
            <div class="shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
              :class="config.sync.include_statuses.read ? 'bg-kindle-600 text-white' : 'bg-stone-200 text-stone-500'">3</div>
            <div class="flex-1">
              <span class="text-sm font-medium text-stone-800">Read</span>
              <p class="text-xs text-stone-500">Completed books</p>
            </div>
            <div class="toggle" :class="config.sync.include_statuses.read ? 'toggle-on' : 'toggle-off'">
              <span class="toggle-knob"></span>
            </div>
          </label>
        </div>
      </div>

      <!-- Matching Settings -->
      <div class="card">
        <div class="flex items-center gap-3 mb-6">
          <div class="icon-container">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
            </svg>
          </div>
          <div>
            <h2 class="text-lg font-display font-semibold text-stone-900">Matching</h2>
            <p class="text-sm text-stone-500">How books are matched</p>
          </div>
        </div>
        <div class="space-y-4">
          <label class="flex items-center gap-3 p-3 rounded-xl bg-stone-50 border border-stone-200 cursor-pointer hover:bg-stone-100 transition-colors">
            <input type="checkbox" v-model="config.matching.use_isbn" class="sr-only peer" />
            <div class="toggle" :class="config.matching.use_isbn ? 'toggle-on' : 'toggle-off'">
              <span class="toggle-knob"></span>
            </div>
            <span class="text-sm font-medium text-stone-700">Use ISBN matching</span>
          </label>
          <label class="flex items-center gap-3 p-3 rounded-xl bg-stone-50 border border-stone-200 cursor-pointer hover:bg-stone-100 transition-colors">
            <input type="checkbox" v-model="config.matching.use_fuzzy" class="sr-only peer" />
            <div class="toggle" :class="config.matching.use_fuzzy ? 'toggle-on' : 'toggle-off'">
              <span class="toggle-knob"></span>
            </div>
            <span class="text-sm font-medium text-stone-700">Use fuzzy title/author matching</span>
          </label>
          <div>
            <label class="label">Fuzzy Match Threshold (0-100)</label>
            <input v-model.number="config.matching.fuzzy_threshold" type="number" min="0" max="100" class="input w-32" />
          </div>
        </div>
      </div>

      <!-- Transfer Settings -->
      <div class="card">
        <div class="flex items-center gap-3 mb-6">
          <div class="icon-container">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
            </svg>
          </div>
          <div>
            <h2 class="text-lg font-display font-semibold text-stone-900">Transfer</h2>
            <p class="text-sm text-stone-500">Default transfer behavior</p>
          </div>
        </div>
        <div class="space-y-4">
          <label class="flex items-center gap-3 p-3 rounded-xl bg-stone-50 border border-stone-200 cursor-pointer hover:bg-stone-100 transition-colors">
            <input type="checkbox" v-model="config.transfer.skip_existing" class="sr-only peer" />
            <div class="toggle" :class="config.transfer.skip_existing ? 'toggle-on' : 'toggle-off'">
              <span class="toggle-knob"></span>
            </div>
            <div>
              <span class="text-sm font-medium text-stone-700">Skip existing files</span>
              <p class="text-xs text-stone-500">Don't transfer books already on Kindle</p>
            </div>
          </label>
          <label class="flex items-center gap-3 p-3 rounded-xl bg-stone-50 border border-stone-200 cursor-pointer hover:bg-stone-100 transition-colors">
            <input type="checkbox" v-model="config.transfer.dry_run" class="sr-only peer" />
            <div class="toggle" :class="config.transfer.dry_run ? 'toggle-on' : 'toggle-off'">
              <span class="toggle-knob"></span>
            </div>
            <div>
              <span class="text-sm font-medium text-stone-700">Default to dry run</span>
              <p class="text-xs text-stone-500">Simulate transfers by default</p>
            </div>
          </label>

          <!-- Folder Organization -->
          <div>
            <label class="label">Folder Organization</label>
            <select v-model="config.transfer.folder_organization" class="input">
              <option value="flat">Flat (all books in root)</option>
              <option value="author">By Author</option>
              <option value="series">By Series (or Author)</option>
              <option value="author_series">Author / Series</option>
            </select>
            <p class="mt-1.5 text-xs text-stone-500">
              How books are organized on the Kindle. KOReader works best with simple folder structures.
            </p>
          </div>

          <!-- Divider -->
          <div class="border-t border-stone-200 pt-4 mt-4">
            <p class="text-sm font-medium text-stone-700 mb-3">Cleanup Options</p>
          </div>

          <!-- Cleanup Enabled -->
          <label class="flex items-center gap-3 p-3 rounded-xl cursor-pointer hover:bg-stone-100 transition-colors" :class="config.transfer.cleanup_enabled ? 'bg-warning-50 border border-warning-200' : 'bg-stone-50 border border-stone-200'">
            <input type="checkbox" v-model="config.transfer.cleanup_enabled" class="sr-only peer" />
            <div class="toggle" :class="config.transfer.cleanup_enabled ? 'toggle-on' : 'toggle-off'">
              <span class="toggle-knob"></span>
            </div>
            <div>
              <span class="text-sm font-medium text-stone-700">Remove books not in sync list</span>
              <p class="text-xs text-stone-500">Delete books from Kindle that aren't in your "want to read" list</p>
            </div>
          </label>

          <!-- Cleanup SDR Folders (only shown when cleanup enabled) -->
          <Transition
            enter-active-class="transition-all duration-200"
            enter-from-class="opacity-0 -translate-y-2"
            enter-to-class="opacity-100 translate-y-0"
            leave-active-class="transition-all duration-150"
            leave-from-class="opacity-100 translate-y-0"
            leave-to-class="opacity-0 -translate-y-2"
          >
            <label v-if="config.transfer.cleanup_enabled" class="flex items-center gap-3 p-3 rounded-xl bg-stone-50 border border-stone-200 cursor-pointer hover:bg-stone-100 transition-colors ml-4">
              <input type="checkbox" v-model="config.transfer.cleanup_sdr_folders" class="sr-only peer" />
              <div class="toggle" :class="config.transfer.cleanup_sdr_folders ? 'toggle-on' : 'toggle-off'">
                <span class="toggle-knob"></span>
              </div>
              <div>
                <span class="text-sm font-medium text-stone-700">Also remove .sdr folders</span>
                <p class="text-xs text-stone-500">Delete reading progress/annotations for removed books</p>
              </div>
            </label>
          </Transition>
        </div>
      </div>

      <!-- Save Button -->
      <div class="flex justify-end">
        <button @click="saveConfig" :disabled="saving" class="btn btn-primary btn-lg">
          <svg v-if="saving" class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          <span v-else>
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
            </svg>
          </span>
          {{ saving ? 'Saving...' : 'Save Settings' }}
        </button>
      </div>
    </template>

    <!-- Kindle Form Modal -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="showKindleForm" class="modal-overlay" @click.self="closeKindleForm">
        <div class="modal-content max-w-lg">
          <div class="flex items-center justify-between mb-6">
            <h2 class="text-xl font-display font-semibold text-stone-900">
              {{ editingKindleId ? 'Edit Kindle' : 'Add Kindle' }}
            </h2>
            <button @click="closeKindleForm" class="p-2 rounded-lg text-stone-500 hover:text-stone-700 hover:bg-stone-100 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>

          <div class="space-y-4">
            <div>
              <label class="label">Name</label>
              <input v-model="kindleForm.name" type="text" class="input" placeholder="My Kindle" />
            </div>
            <div>
              <label class="label">Hostname</label>
              <input v-model="kindleForm.hostname" type="text" class="input" placeholder="kindle.tailnet" />
            </div>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="label">Port</label>
                <input v-model.number="kindleForm.port" type="number" class="input" />
              </div>
              <div>
                <label class="label">Username</label>
                <input v-model="kindleForm.username" type="text" class="input" />
              </div>
            </div>
            <div>
              <label class="label">Password (optional)</label>
              <input v-model="kindleForm.password" type="password" class="input" placeholder="Leave blank for SSH key auth" />
            </div>
            <div>
              <label class="label">SSH Key Path</label>
              <input v-model="kindleForm.ssh_key_path" type="text" class="input font-mono text-sm" />
            </div>
            <div>
              <label class="label">Destination Path</label>
              <input v-model="kindleForm.destination_path" type="text" class="input font-mono text-sm" />
            </div>
          </div>

          <div class="mt-6 flex justify-end gap-3">
            <button @click="closeKindleForm" class="btn btn-secondary">Cancel</button>
            <button @click="saveKindle" class="btn btn-primary">
              {{ editingKindleId ? 'Save Changes' : 'Add Kindle' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Root Folder Form Modal -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="showRootFolderForm" class="modal-overlay" @click.self="closeRootFolderForm">
        <div class="modal-content max-w-lg">
          <div class="flex items-center justify-between mb-6">
            <h2 class="text-xl font-display font-semibold text-stone-900">Add Root Folder</h2>
            <button @click="closeRootFolderForm" class="p-2 rounded-lg text-stone-500 hover:text-stone-700 hover:bg-stone-100 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>

          <div v-if="rootFolderError" class="mb-4 p-4 rounded-xl bg-error-50 border border-error-100 animate-fade-in">
            <p class="text-sm font-medium text-error-700">{{ rootFolderError }}</p>
          </div>

          <div class="space-y-4">
            <div>
              <label class="label">Name</label>
              <input v-model="rootFolderForm.name" type="text" class="input" placeholder="My Books" />
            </div>
            <div>
              <label class="label">Path</label>
              <input v-model="rootFolderForm.path" type="text" class="input font-mono text-sm" placeholder="/books" />
              <p class="mt-1.5 text-xs text-stone-500">
                Absolute path where book files will be stored
              </p>
            </div>
            <div>
              <label class="label">Folder Organization</label>
              <select v-model="rootFolderForm.folder_organization" class="input">
                <option value="flat">Flat (all books in root)</option>
                <option value="author">By Author</option>
                <option value="series">By Series (or Author)</option>
                <option value="author_series">Author / Series</option>
              </select>
            </div>
          </div>

          <div class="mt-6 flex justify-end gap-3">
            <button @click="closeRootFolderForm" class="btn btn-secondary">Cancel</button>
            <button @click="saveRootFolder" class="btn btn-primary">Add Folder</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
