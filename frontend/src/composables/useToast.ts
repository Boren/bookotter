import { ref } from 'vue';

interface Toast {
  id: number;
  message: string;
  kind: 'success' | 'error' | 'info';
}

const toasts = ref<Toast[]>([]);
let nextId = 0;

export function useToast() {
  function add(message: string, kind: Toast['kind'], duration: number) {
    const id = nextId++;
    toasts.value.push({ id, message, kind });
    setTimeout(() => {
      toasts.value = toasts.value.filter((t) => t.id !== id);
    }, duration);
  }

  return {
    toasts,
    success: (msg: string) => add(msg, 'success', 4000),
    error: (msg: string) => add(msg, 'error', 6000),
    info: (msg: string) => add(msg, 'info', 4000),
  };
}
