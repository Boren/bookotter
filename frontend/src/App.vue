<script setup lang="ts">
import { RouterView, RouterLink, useRoute } from 'vue-router'
import { ref, onMounted, onUnmounted } from 'vue'
import { useSyncStore } from './stores/sync'

const route = useRoute()
const syncStore = useSyncStore()
const mobileMenuOpen = ref(false)

// Otter-themed taglines - randomly selected on each page load
const taglines = [
  "Your Reading Companion",
  "Otterly Organized Reading",
  "Swimming Through Your Library",
  "Delivering Books Like a Pro",
  "Making Waves in Your Library",
  "One Paw on Your Books",
  "Fetching Your Next Read",
  "Dam Good Book Syncing",
  "Floating Your Books Home",
  "Otter-matic Book Delivery",
]
const tagline = taglines[Math.floor(Math.random() * taglines.length)]

const navLinks = [
  {
    name: 'Dashboard',
    path: '/',
    icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 5a1 1 0 011-1h4a1 1 0 011 1v5a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v5a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zM14 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"/>
    </svg>`
  },
  {
    name: 'Library',
    path: '/library',
    icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
    </svg>`
  },
  {
    name: 'Schedule',
    path: '/schedule',
    icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
    </svg>`
  },
  {
    name: 'Downloads',
    path: '/downloads',
    icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10"/>
    </svg>`
  },
  {
    name: 'Settings',
    path: '/settings',
    icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
    </svg>`
  },
  {
    name: 'Logs',
    path: '/logs',
    icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
    </svg>`
  },
]

const isActive = (path: string) => {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

const closeMobileMenu = () => {
  mobileMenuOpen.value = false
}

onMounted(() => {
  syncStore.connectWebSocket()
})

onUnmounted(() => {
  syncStore.disconnectWebSocket()
})
</script>

<template>
  <div class="min-h-screen bg-stone-50 flex">
    <!-- Sidebar - Desktop -->
    <aside class="hidden lg:flex lg:flex-col lg:w-64 lg:fixed lg:inset-y-0 bg-stone-900 shadow-warm-xl">
      <!-- Logo -->
      <div class="flex items-center gap-3 px-6 h-20 border-b border-stone-800">
        <img src="/logo.png" alt="BookOtter" class="w-10 h-auto" />
        <div>
          <h1 class="text-lg font-display font-bold text-white">BookOtter</h1>
          <p class="text-xs text-stone-400">{{ tagline }}</p>
        </div>
      </div>

      <!-- Navigation -->
      <nav class="flex-1 px-4 py-6 space-y-1 overflow-y-auto scrollbar-hide">
        <RouterLink
          v-for="link in navLinks"
          :key="link.path"
          :to="link.path"
          :class="[
            'nav-item',
            isActive(link.path) ? 'nav-item-active' : ''
          ]"
        >
          <span v-html="link.icon"></span>
          <span>{{ link.name }}</span>
        </RouterLink>
      </nav>

      <!-- Sync Status -->
      <div class="px-4 py-4 border-t border-stone-800">
        <div
          class="flex items-center gap-3 px-4 py-3 rounded-xl"
          :class="syncStore.isRunning ? 'bg-kindle-900/30' : 'bg-stone-800/50'"
        >
          <div class="relative">
            <span
              class="status-dot"
              :class="syncStore.isRunning ? 'bg-kindle-400 animate-pulse' : 'status-dot-success'"
            ></span>
          </div>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-white truncate">
              {{ syncStore.isRunning ? 'Syncing...' : 'Ready' }}
            </p>
            <p class="text-xs text-stone-400">
              {{ syncStore.wsConnected ? 'Connected' : 'Disconnected' }}
            </p>
          </div>
          <div v-if="syncStore.isRunning" class="text-kindle-400">
            <svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          </div>
        </div>
      </div>
    </aside>

    <!-- Mobile Header -->
    <header class="lg:hidden fixed top-0 left-0 right-0 z-40 bg-white/95 backdrop-blur-md border-b border-stone-200 shadow-warm-sm">
      <div class="flex items-center justify-between h-16 px-4">
        <!-- Logo -->
        <div class="flex items-center gap-3">
          <img src="/logo.png" alt="BookOtter" class="w-9 h-auto" />
          <span class="text-lg font-display font-bold text-stone-900">BookOtter</span>
        </div>

        <!-- Status + Menu Button -->
        <div class="flex items-center gap-3">
          <div class="flex items-center gap-2 text-sm">
            <span
              class="status-dot"
              :class="syncStore.isRunning ? 'bg-kindle-500 animate-pulse' : 'status-dot-success'"
            ></span>
            <span class="text-stone-600">{{ syncStore.isRunning ? 'Syncing' : 'Ready' }}</span>
          </div>
          <button
            @click="mobileMenuOpen = !mobileMenuOpen"
            class="p-2 rounded-lg text-stone-600 hover:bg-stone-100 transition-colors"
          >
            <svg v-if="!mobileMenuOpen" class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/>
            </svg>
            <svg v-else class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>
    </header>

    <!-- Mobile Menu Overlay -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="mobileMenuOpen"
        class="lg:hidden fixed inset-0 z-30 bg-stone-900/50 backdrop-blur-xs"
        @click="closeMobileMenu"
      ></div>
    </Transition>

    <!-- Mobile Menu Panel -->
    <Transition
      enter-active-class="transition-transform duration-300 ease-out"
      enter-from-class="translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition-transform duration-300 ease-in"
      leave-from-class="translate-x-0"
      leave-to-class="translate-x-full"
    >
      <div
        v-if="mobileMenuOpen"
        class="lg:hidden fixed right-0 top-16 bottom-0 z-40 w-64 bg-stone-900 shadow-warm-xl"
      >
        <nav class="px-4 py-6 space-y-1">
          <RouterLink
            v-for="link in navLinks"
            :key="link.path"
            :to="link.path"
            :class="[
              'nav-item',
              isActive(link.path) ? 'nav-item-active' : ''
            ]"
            @click="closeMobileMenu"
          >
            <span v-html="link.icon"></span>
            <span>{{ link.name }}</span>
          </RouterLink>
        </nav>
      </div>
    </Transition>

    <!-- Main Content -->
    <main class="flex-1 lg:pl-64">
      <!-- Paper texture background -->
      <div class="min-h-screen paper-texture">
        <div class="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 pt-24 lg:pt-8">
          <RouterView v-slot="{ Component }">
            <Transition
              enter-active-class="animate-fade-in-up"
              leave-active-class="animate-fade-out"
              mode="out-in"
            >
              <component :is="Component" />
            </Transition>
          </RouterView>
        </div>
      </div>
    </main>
  </div>
</template>
