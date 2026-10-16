import { nextTick, onBeforeUnmount, onDeactivated, watch, type Ref } from 'vue'

const focusable = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])'

/** Shared keyboard and scroll lifecycle for mounted modal panels. */
export function useDialog(open: Ref<boolean>, panel: Ref<HTMLElement | null>, close: () => void): void {
  let previous: HTMLElement | null = null
  let overflow = ''
  let active = false
  function keydown(event: KeyboardEvent): void {
    if (!active || !panel.value) return
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
    } else if (event.key === 'Tab') {
      const elements = Array.from(panel.value.querySelectorAll<HTMLElement>(focusable))
        .filter(element => element.getClientRects().length > 0)
      const first = elements[0]
      const last = elements.at(-1)
      if (!first || !last) {
        event.preventDefault()
        panel.value.focus()
      } else if (!panel.value.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
  }
  function release(): void {
    if (!active) return
    active = false
    document.removeEventListener('keydown', keydown)
    document.body.style.overflow = overflow
    if (previous?.isConnected) previous.focus()
  }
  watch(open, async value => {
    if (!value) { release(); return }
    if (active) return
    previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    overflow = document.body.style.overflow
    active = true
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', keydown)
    await nextTick()
    if (!active || !open.value) return
    const target = panel.value?.querySelector<HTMLElement>('[data-dialog-close]') ?? panel.value
    target?.focus()
  }, { immediate: true })
  onBeforeUnmount(release)
  onDeactivated(() => { close(); release() })
}
