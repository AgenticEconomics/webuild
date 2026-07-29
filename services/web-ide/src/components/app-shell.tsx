'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { usePathname } from 'next/navigation'
import { Menu, X } from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
import { useI18n } from '@/lib/i18n'

type NavContextValue = {
  open: boolean
  openNav: () => void
  closeNav: () => void
  toggleNav: () => void
}

const NavContext = createContext<NavContextValue | null>(null)

export function useNav() {
  const ctx = useContext(NavContext)
  if (!ctx) {
    throw new Error('useNav must be used within AppShell')
  }
  return ctx
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const pathname = usePathname()

  const closeNav = useCallback(() => setOpen(false), [])
  const openNav = useCallback(() => setOpen(true), [])
  const toggleNav = useCallback(() => setOpen((v) => !v), [])

  useEffect(() => {
    setOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open])

  const value = useMemo(
    () => ({ open, openNav, closeNav, toggleNav }),
    [open, openNav, closeNav, toggleNav]
  )

  return (
    <NavContext.Provider value={value}>
      <div className="flex h-[100dvh] max-h-[100dvh] overflow-hidden">
        {/* Mobile backdrop */}
        <div
          aria-hidden={!open}
          className={`fixed inset-0 z-40 bg-black/40 transition-opacity md:hidden ${
            open ? 'opacity-100' : 'pointer-events-none opacity-0'
          }`}
          onClick={closeNav}
        />

        <Sidebar mobileOpen={open} onMobileClose={closeNav} />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
      </div>
    </NavContext.Provider>
  )
}

export function NavMenuButton({ className = '' }: { className?: string }) {
  const { open, toggleNav } = useNav()
  const { t } = useI18n()

  return (
    <button
      type="button"
      onClick={toggleNav}
      aria-label={open ? t('closeMenu') : t('openMenu')}
      aria-expanded={open}
      className={`inline-flex h-9 w-9 items-center justify-center rounded text-console-muted hover:bg-console-bg hover:text-console-ink md:hidden ${className}`}
    >
      {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
    </button>
  )
}
