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

export type Locale = 'en' | 'zh'

const STORAGE_KEY = 'webuild_locale'

const messages = {
  en: {
    tagline: 'Agentics Assistant',
    newSession: 'New Session',
    recent: 'Recent',
    noSessions: 'No sessions yet',
    settings: 'Settings',
    connected: 'Connected',
    disconnected: 'Disconnected',
    home: 'Home',
    heroBefore: 'How can I help you ',
    heroHighlight: 'code today',
    heroAfter: '?',
    heroSubtitle:
      'Your Agentics assistant — write, debug, refactor, and deploy code with natural language.',
    promptPlaceholder: 'Describe what you want to build...',
    start: 'Start',
    pressEnterHint: 'Press',
    toStartSession: 'to start a session',
    suggestion1: 'Help me debug this Rust async code',
    suggestion2: 'Set up a Docker Compose for my project',
    suggestion3: 'Create a REST API with FastAPI',
    suggestion4: 'Refactor this function for readability',
    settingsDesc: 'Configure your WeBuild connection and preferences.',
    relayReachable: 'Relay server is reachable',
    checkWsToken: 'Check your WebSocket URL and token',
    relayServer: 'Relay Server',
    relayDesc: 'WebSocket endpoint for ACP messages',
    authentication: 'Authentication',
    authDesc: 'JWT access token from the Auth Service',
    pasteToken: 'Paste your JWT token...',
    saved: 'Saved!',
    saveSettings: 'Save Settings',
    session: 'Session',
    startConversation: 'Start the conversation below',
    messagePlaceholder: 'Message WeBuild...',
    connecting: 'Connecting...',
    toSend: 'to send',
    forNewline: 'for newline',
    language: 'Language',
    langEn: 'English',
    langZh: '中文',
  },
  zh: {
    tagline: 'Agentics Assistant',
    newSession: '新建会话',
    recent: '最近',
    noSessions: '暂无会话',
    settings: '设置',
    connected: '已连接',
    disconnected: '未连接',
    home: '首页',
    heroBefore: '今天想让我帮你',
    heroHighlight: '写点什么',
    heroAfter: '？',
    heroSubtitle: '你的 Agentics 助手 — 用自然语言编写、调试、重构并部署代码。',
    promptPlaceholder: '描述你想构建的内容…',
    start: '开始',
    pressEnterHint: '按',
    toStartSession: '开始会话',
    suggestion1: '帮我调试这段 Rust 异步代码',
    suggestion2: '为我的项目配置 Docker Compose',
    suggestion3: '用 FastAPI 创建一个 REST API',
    suggestion4: '重构这个函数以提高可读性',
    settingsDesc: '配置 WeBuild 连接与偏好设置。',
    relayReachable: '中继服务可达',
    checkWsToken: '请检查 WebSocket 地址与令牌',
    relayServer: '中继服务',
    relayDesc: '用于 ACP 消息的 WebSocket 端点',
    authentication: '身份认证',
    authDesc: '来自认证服务的 JWT 访问令牌',
    pasteToken: '粘贴你的 JWT 令牌…',
    saved: '已保存！',
    saveSettings: '保存设置',
    session: '会话',
    startConversation: '在下方开始对话',
    messagePlaceholder: '给 WeBuild 发送消息…',
    connecting: '连接中…',
    toSend: '发送',
    forNewline: '换行',
    language: '语言',
    langEn: 'English',
    langZh: '中文',
  },
} as const

export type MessageKey = keyof typeof messages.en

type I18nContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: MessageKey) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

function readStoredLocale(): Locale {
  if (typeof window === 'undefined') return 'en'
  const stored = localStorage.getItem(STORAGE_KEY)
  return stored === 'zh' || stored === 'en' ? stored : 'en'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>('en')

  useEffect(() => {
    setLocaleState(readStoredLocale())
  }, [])

  useEffect(() => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en'
  }, [locale])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    localStorage.setItem(STORAGE_KEY, next)
  }, [])

  const t = useCallback(
    (key: MessageKey) => messages[locale][key] ?? messages.en[key] ?? key,
    [locale]
  )

  const value = useMemo(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t]
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const ctx = useContext(I18nContext)
  if (!ctx) {
    throw new Error('useI18n must be used within I18nProvider')
  }
  return ctx
}
