<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import type { BrowseEntry, BrowseResponse, PathBrowserMode } from '@/types'

interface Props {
  modelValue: boolean
  mode: PathBrowserMode
  ereaderId?: string
  initialPath: string
  title?: string
  selectMode?: 'directory' | 'file'
}

const props = withDefaults(defineProps<Props>(), {
  title: 'Browse',
  selectMode: 'directory',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  select: [path: string]
}>()

const currentPath = ref<string>(props.initialPath)
const pathInput = ref(props.initialPath)
const entries = ref<BrowseEntry[]>([])
const parentPath = ref<string | null>(null)
const truncated = ref(false)
const isLoading = ref(false)
const error = ref<string | null>(null)
const showHidden = ref(false)
const inFlightController = ref<AbortController | null>(null)
const selectedFile = ref<string | null>(null)
const debounceTimer = ref<ReturnType<typeof setTimeout> | null>(null)

const selectedPath = computed(() => {
  return props.selectMode === 'file' ? selectedFile.value ?? '(no file selected)' : currentPath.value
})

const breadcrumbs = computed(() => {
  if (currentPath.value === '/') {
    return [{ label: '/', path: '/' }]
  }

  const segments = currentPath.value.split('/').filter(Boolean)
  return [
    { label: '/', path: '/' },
    ...segments.map((segment, index) => ({
      label: segment,
      path: `/${segments.slice(0, index + 1).join('/')}`,
    })),
  ]
})

function joinPath(base: string, name: string) {
  return base === '/' ? `/${name}` : `${base}/${name}`
}

function close() {
  inFlightController.value?.abort()
  emit('update:modelValue', false)
}

function clearDebounce() {
  if (debounceTimer.value) {
    clearTimeout(debounceTimer.value)
    debounceTimer.value = null
  }
}

async function fetchPath(target: string) {
  inFlightController.value?.abort()
  const ctrl = new AbortController()
  inFlightController.value = ctrl
  isLoading.value = true
  error.value = null

  try {
    const url =
      props.mode === 'local'
        ? `/api/browse/local?path=${encodeURIComponent(target)}&show_hidden=${showHidden.value}`
        : `/api/ereaders/${props.ereaderId}/browse?path=${encodeURIComponent(target)}&show_hidden=${showHidden.value}`
    const response = await fetch(url, { signal: ctrl.signal })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      error.value = data.detail || `Failed (${response.status})`
      return
    }

    const data: BrowseResponse = await response.json()
    currentPath.value = data.current_path
    pathInput.value = data.current_path
    parentPath.value = data.parent_path
    entries.value = data.entries
    truncated.value = data.truncated
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') {
      return
    }

    error.value = e instanceof Error ? e.message : 'Network error'
  } finally {
    if (inFlightController.value === ctrl) {
      isLoading.value = false
      inFlightController.value = null
    }
  }
}

function navigateTo(target: string) {
  pathInput.value = target
  void fetchPath(target)
}

function handlePathInput() {
  clearDebounce()
  debounceTimer.value = setTimeout(() => {
    if (!props.modelValue) {
      return
    }

    void fetchPath(pathInput.value)
  }, 500)
}

function handlePathSubmit() {
  clearDebounce()
  void fetchPath(pathInput.value)
}

function handleEntryClick(entry: BrowseEntry) {
  if (entry.type === 'dir') {
    navigateTo(joinPath(currentPath.value, entry.name))
    return
  }

  if (props.selectMode === 'file' && entry.type === 'file') {
    selectedFile.value = joinPath(currentPath.value, entry.name)
  }
}

function selectPath() {
  if (props.selectMode === 'file') {
    if (!selectedFile.value) {
      return
    }

    emit('select', selectedFile.value)
  } else {
    emit('select', currentPath.value)
  }

  emit('update:modelValue', false)
}

watch(currentPath, () => {
  selectedFile.value = null
})

watch(
  () => [props.modelValue, props.initialPath, showHidden.value] as const,
  ([isOpen, initialPath, hidden], [wasOpen, previousInitialPath, previousHidden]) => {
    if (!isOpen) {
      clearDebounce()
      inFlightController.value?.abort()
      return
    }

    if (!wasOpen || initialPath !== previousInitialPath) {
      currentPath.value = initialPath
      pathInput.value = initialPath
      void fetchPath(initialPath)
      return
    }

    if (hidden !== previousHidden) {
      void fetchPath(currentPath.value)
    }
  },
)

onUnmounted(() => {
  clearDebounce()
  inFlightController.value?.abort()
})
</script>

<template>
  <Transition
    enter-active-class="transition-opacity duration-200"
    enter-from-class="opacity-0"
    enter-to-class="opacity-100"
    leave-active-class="transition-opacity duration-200"
    leave-from-class="opacity-100"
    leave-to-class="opacity-0"
  >
    <div v-if="modelValue" class="modal-overlay" @click.self="close">
      <div class="modal-content max-w-2xl">
        <div class="flex items-center justify-between mb-6">
          <h2 class="text-xl font-display font-semibold text-stone-900">{{ title }}</h2>
          <button
            type="button"
            class="p-2 rounded-lg text-stone-500 hover:text-stone-700 hover:bg-stone-100 transition-colors"
            @click="close"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div v-if="error" class="mb-4 p-4 rounded-xl bg-error-50 border border-error-100 animate-fade-in">
          <p class="text-sm font-medium text-error-700">{{ error }}</p>
        </div>

        <div class="space-y-4">
          <div>
            <label class="label">Path</label>
            <input
              v-model="pathInput"
              type="text"
              class="input font-mono text-sm"
              @input="handlePathInput"
              @keyup.enter="handlePathSubmit"
            />
          </div>

          <div class="flex flex-wrap items-center gap-1 text-sm">
            <button
              v-for="crumb in breadcrumbs"
              :key="crumb.path"
              type="button"
              :class="[
                'rounded-lg px-2 py-1 transition-colors',
                crumb.path === currentPath ? 'font-semibold text-stone-900' : 'text-stone-500 hover:text-stone-700',
              ]"
              @click="navigateTo(crumb.path)"
            >
              {{ crumb.label }}
            </button>
          </div>

          <p v-if="truncated" class="text-xs text-amber-600">
            Showing first 1000 entries — type a more specific path to narrow.
          </p>

          <div class="max-h-96 overflow-y-auto border border-stone-200 rounded-xl">
            <div v-if="isLoading" class="px-3 py-6 text-center text-sm text-stone-500">Loading...</div>
            <div v-else-if="entries.length === 0 && parentPath === null" class="px-3 py-6 text-center text-sm text-stone-500">
              This folder is empty.
            </div>
            <template v-else>
              <button
                v-if="parentPath !== null"
                type="button"
                class="w-full text-left px-3 py-2 hover:bg-stone-100 flex items-center gap-3 border-b border-stone-100"
                @click="navigateTo(parentPath)"
              >
                <svg class="w-4 h-4 text-stone-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
                </svg>
                <span class="font-mono text-sm text-stone-700">..</span>
              </button>

              <button
                v-for="entry in entries"
                :key="`${entry.type}:${entry.name}`"
                type="button"
                :disabled="props.selectMode === 'directory' && entry.type !== 'dir'"
                :class="[
                  'w-full text-left px-3 py-2 flex items-center gap-3 transition-colors',
                  props.selectMode === 'file' && selectedFile === joinPath(currentPath, entry.name) ? 'bg-ereader-100' : 'hover:bg-stone-100',
                  props.selectMode === 'directory' && entry.type !== 'dir' ? 'text-stone-400 cursor-not-allowed' : 'text-stone-700',
                ]"
                @click="handleEntryClick(entry)"
              >
                <svg
                  v-if="entry.type === 'dir'"
                  class="w-4 h-4 text-ereader-700 shrink-0"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
                  />
                </svg>
                <svg
                  v-else
                  class="w-4 h-4 text-stone-500 shrink-0"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 3h7l5 5v13a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1z" />
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 3v5h5" />
                </svg>
                <div class="min-w-0 flex-1">
                  <div class="font-mono text-sm truncate">
                    {{ entry.name }}
                    <span v-if="entry.is_symlink" class="text-xs text-stone-500">@</span>
                  </div>
                  <div v-if="entry.type === 'broken_symlink'" class="text-xs text-error-700">
                    Broken symlink
                  </div>
                </div>
              </button>
            </template>
          </div>

          <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div class="space-y-2">
              <label class="inline-flex items-center gap-2 text-sm text-stone-600">
                <input v-model="showHidden" type="checkbox" />
                <span>Show hidden</span>
              </label>
              <code class="text-xs">{{ selectedPath }}</code>
            </div>

            <div class="flex justify-end gap-3">
              <button type="button" class="btn btn-secondary" @click="close">Cancel</button>
              <button
                type="button"
                class="btn btn-primary"
                :disabled="props.selectMode === 'file' ? !selectedFile : false"
                @click="selectPath"
              >
                {{ props.selectMode === 'file' ? 'Select this file' : 'Select this folder' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>
