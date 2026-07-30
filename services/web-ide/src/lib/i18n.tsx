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
    heroBefore: 'Your ',
    heroHighlight: 'multi-skill agent',
    heroAfter: ' is ready',
    heroSubtitle:
      'Not just coding — WeBuild plans, builds, runs tools in a secure sandbox, and extends with skills, plugins, and MCP.',
    promptPlaceholder: 'Ask WeBuild to code, draft docs, run tools, or automate a workflow…',
    start: 'Start',
    pressEnterHint: 'Press',
    toStartSession: 'to start a session',
    capabilitiesHeading: 'Core capabilities',
    capability1Title: 'Code & engineering',
    capability1Desc: 'Write, debug, refactor, and ship software with natural language.',
    capability1Prompt: 'Review this project structure and suggest a clean refactor plan',
    capability2Title: 'Skills & documents',
    capability2Desc: 'Run packaged skills for reviews, ops, and office docs (PDF, DOCX, PPTX, XLSX).',
    capability2Prompt: 'Draft a project status deck in PPTX from a short outline I will provide',
    capability3Title: 'Secure sandbox',
    capability3Desc: 'Execute shell, files, and installs in an isolated cloud workspace.',
    capability3Prompt: 'In the sandbox, scaffold a small FastAPI service and show how to run it',
    capability4Title: 'Plugins & MCP',
    capability4Desc: 'Extend the agent with plugins, hooks, and Model Context Protocol servers.',
    capability4Prompt: 'Explain how to add an MCP server and a custom skill for my team workflow',
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
    deleteSession: 'Delete session',
    deleteSessionConfirm: 'Delete this session and its chat history?',
    inviteOnlyTitle: 'Invite only',
    inviteOnlyDesc: 'WeBuild uses an invite whitelist. Email to request access; you will receive a username and password manually.',
    inviteEmailLabel: 'Request access',
    loginTitle: 'Login',
    loginDesc: 'Sign in with your invite username and password',
    username: 'Username',
    password: 'Password',
    language: 'Language',
    langEn: 'English',
    langZh: '中文',
    openMenu: 'Open menu',
    closeMenu: 'Close menu',
    uploadFiles: 'Upload files',
    uploading: 'Uploading…',
    uploadFailed: 'Upload failed',
    uploadedToInbox: 'Uploaded to inbox',
    removeUpload: 'Remove',
    outputsPanel: 'Outputs',
    refreshOutputs: 'Refresh outputs',
    outputsEmpty: 'No files in /workspace/outputs yet. Ask the agent to write deliverables there.',
    outputsNeedSandbox: 'Outputs are available when the sandbox is running.',
    downloadFile: 'Download',
    outputsTtlHint: 'Files are deleted when the sandbox expires or is terminated.',
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
    heroBefore: '你的',
    heroHighlight: '多功能智能体',
    heroAfter: '已就绪',
    heroSubtitle:
      '不只是写代码 — WeBuild 能规划与执行任务，在安全沙箱中运行工具，并用技能、插件与 MCP 持续扩展。',
    promptPlaceholder: '让 WeBuild 写代码、做文档、跑工具，或自动化一段工作流…',
    start: '开始',
    pressEnterHint: '按',
    toStartSession: '开始会话',
    capabilitiesHeading: '核心能力',
    capability1Title: '编码与工程',
    capability1Desc: '用自然语言编写、调试、重构并交付软件。',
    capability1Prompt: '先看看这个项目结构，给出一份清晰的重构计划',
    capability2Title: '技能与文档',
    capability2Desc: '调用封装技能，覆盖评审、运维与办公文档（PDF / DOCX / PPTX / XLSX）。',
    capability2Prompt: '根据我稍后给出的提纲，生成一份项目进展 PPTX',
    capability3Title: '安全沙箱',
    capability3Desc: '在隔离的云端工作区执行终端、文件与安装操作。',
    capability3Prompt: '在沙箱里搭一个小型 FastAPI 服务，并说明如何启动',
    capability4Title: '插件与 MCP',
    capability4Desc: '通过插件、钩子与 Model Context Protocol 扩展智能体能力。',
    capability4Prompt: '说明如何为我的团队工作流添加一个 MCP 服务和自定义技能',
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
    deleteSession: '删除会话',
    deleteSessionConfirm: '确定删除该会话及其聊天记录？',
    inviteOnlyTitle: '邀请制注册',
    inviteOnlyDesc: 'WeBuild 采用白名单邀请制。请发邮件申请账号，管理员将手工回复用户名与密码。',
    inviteEmailLabel: '申请入口',
    loginTitle: '登录',
    loginDesc: '使用邀请账号的用户名和密码登录',
    username: '用户名',
    password: '密码',
    language: '语言',
    langEn: 'English',
    langZh: '中文',
    openMenu: '打开菜单',
    closeMenu: '关闭菜单',
    uploadFiles: '上传文件',
    uploading: '上传中…',
    uploadFailed: '上传失败',
    uploadedToInbox: '已上传到 inbox',
    removeUpload: '移除',
    outputsPanel: '交付物 Outputs',
    refreshOutputs: '刷新列表',
    outputsEmpty: 'outputs/ 中尚无文件。请让智能体将最终报告写入 /workspace/outputs/。',
    outputsNeedSandbox: '沙箱运行后可查看与下载交付物。',
    downloadFile: '下载',
    outputsTtlHint: '沙箱到期或终止后，文件会被删除。',
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
