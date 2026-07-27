import type { Metadata } from 'next'
import { Noto_Sans_SC, Roboto } from 'next/font/google'
import { I18nProvider } from '@/lib/i18n'
import './globals.css'

const roboto = Roboto({
  subsets: ['latin'],
  weight: ['400', '500', '700'],
  variable: '--font-console',
  display: 'swap',
})

const notoSansSC = Noto_Sans_SC({
  subsets: ['latin'],
  weight: ['400', '500', '700'],
  variable: '--font-console-zh',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'WeBuild Web IDE',
  description: 'Agentics Assistant',
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: 'any' },
      { url: '/icon-32.png', sizes: '32x32', type: 'image/png' },
      { url: '/icon-192.png', sizes: '192x192', type: 'image/png' },
    ],
    apple: [{ url: '/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }],
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={`${roboto.variable} ${notoSansSC.variable}`}>
      <body className="font-sans">
        <I18nProvider>
          <div className="min-h-screen bg-console-bg text-console-ink">
            {children}
          </div>
        </I18nProvider>
      </body>
    </html>
  )
}
