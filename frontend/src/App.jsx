import { useState, useEffect, useRef } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import {
  AppShell,
  Burger,
  Group,
  NavLink as MantineNavLink,
  Badge,
  Stack,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import {
  IconServer,
  IconSearch,
  IconDownload,
  IconCalendar,
  IconSettings,
} from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'

import Accounts from './pages/Accounts'
import Browse from './pages/Browse'
import Downloads from './pages/Downloads'
import Scheduled from './pages/Scheduled'
import Settings from './pages/Settings'
import { downloadsApi, epgApi, createDownloadWebSocket } from './api'
import mustarrdLogo from './assets/mustarrdlogo.png'

function App() {
  const [opened, { toggle }] = useDisclosure()
  const [activeDownloads, setActiveDownloads] = useState(0)
  const epgToastVisibleRef = useRef(false)
  const epgToastCloseTimerRef = useRef(null)
  const epgToastPendingCloseRef = useRef(false)

  // Fetch download queue for badge
  const { data: queue } = useQuery({
    queryKey: ['downloads', 'queue'],
    queryFn: downloadsApi.getQueue,
    refetchInterval: 5000,
  })

  const { data: epgStatus } = useQuery({
    queryKey: ['epg', 'status'],
    queryFn: epgApi.status,
    refetchInterval: 5000,
  })

  useEffect(() => {
    if (queue) {
      setActiveDownloads(queue.length)
    }
  }, [queue])

  const clearEpgToastTimer = () => {
    if (epgToastCloseTimerRef.current) {
      clearTimeout(epgToastCloseTimerRef.current)
      epgToastCloseTimerRef.current = null
    }
  }

  const scheduleEpgToastClose = () => {
    clearEpgToastTimer()
    if (document.visibilityState === 'hidden') {
      epgToastPendingCloseRef.current = true
      return
    }
    epgToastPendingCloseRef.current = false
    epgToastCloseTimerRef.current = setTimeout(() => {
      notifications.hide('epg-download-progress')
      epgToastVisibleRef.current = false
    }, 10000)
  }

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && epgToastPendingCloseRef.current) {
        scheduleEpgToastClose()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [])

  useEffect(() => {
    if (!epgStatus) return

    const {
      running,
      account_name: accountName,
      processed_programs: processedPrograms,
      total_programs: totalPrograms,
      last_error: lastError,
    } = epgStatus

    const processed = typeof processedPrograms === 'number' ? processedPrograms : 0
    const total = typeof totalPrograms === 'number' ? totalPrograms : null
    const hasTotal = total && total > 0
    const percent = hasTotal ? Math.min(100, Math.round((processed / total) * 100)) : null
    const percentLabel = percent != null ? ` • ${percent}%` : ''
    const title = accountName
      ? `Downloading full EPG (${accountName}${percentLabel})`
      : 'Downloading full EPG'
    const message = hasTotal
      ? `${processed.toLocaleString()} of ${total.toLocaleString()} programs (${percent}%).`
      : `${processed.toLocaleString()} programs indexed so far.`

    if (running) {
      clearEpgToastTimer()
      epgToastPendingCloseRef.current = false
      if (epgToastVisibleRef.current) {
        notifications.update({
          id: 'epg-download-progress',
          title,
          message,
          loading: true,
          autoClose: false,
          withCloseButton: false,
        })
      } else {
        notifications.show({
          id: 'epg-download-progress',
          title,
          message,
          loading: true,
          autoClose: false,
          withCloseButton: false,
        })
        epgToastVisibleRef.current = true
      }
      return
    }

    if (epgToastVisibleRef.current) {
      clearEpgToastTimer()
      if (lastError) {
        notifications.update({
          id: 'epg-download-progress',
          title: 'EPG download failed',
          message: lastError,
          color: 'red',
          loading: false,
          autoClose: false,
          withCloseButton: true,
        })
      } else {
        notifications.update({
          id: 'epg-download-progress',
          title: 'EPG download complete',
          message: 'Full EPG index updated.',
          color: 'green',
          loading: false,
          autoClose: false,
          withCloseButton: true,
        })
      }
      scheduleEpgToastClose()
    }
  }, [epgStatus])

  // WebSocket for real-time updates
  useEffect(() => {
    const ws = createDownloadWebSocket((data) => {
      if (data.type === 'progress') {
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
          setActiveDownloads((prev) => Math.max(0, prev - 1))
        }
      }
    })

    return () => ws.close()
  }, [])

  const navItems = [
    { icon: IconServer, label: 'Accounts', to: '/accounts' },
    { icon: IconSearch, label: 'Browse', to: '/browse' },
    {
      icon: IconDownload,
      label: 'Downloads',
      to: '/downloads',
      badge: activeDownloads > 0 ? activeDownloads : null,
    },
    { icon: IconCalendar, label: 'Scheduled', to: '/scheduled' },
    { icon: IconSettings, label: 'Settings', to: '/settings' },
  ]

  return (
    <AppShell
      header={{ height: { base: 56, sm: 0 } }}
      navbar={{ width: 250, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header hiddenFrom="sm">
        <Group h="100%" px="md">
          <Burger opened={opened} onClick={toggle} size="sm" />
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <Stack gap="md">
          <Group mb="md" justify="center">
            <img
              src={mustarrdLogo}
              alt="Mustarrd"
              style={{ width: '100%', height: 'auto', maxWidth: 220 }}
            />
          </Group>
          {navItems.map((item) => (
            <MantineNavLink
              key={item.to}
              component={NavLink}
              to={item.to}
              label={item.label}
              leftSection={<item.icon size={20} />}
              rightSection={
                item.badge ? (
                  <Badge size="sm" variant="filled" color="blue">
                    {item.badge}
                  </Badge>
                ) : null
              }
              style={{ borderRadius: 8, marginBottom: 4 }}
            />
          ))}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>
        <Routes>
          <Route path="/" element={<Navigate to="/browse" replace />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="/browse" element={<Browse />} />
          <Route path="/downloads" element={<Downloads />} />
          <Route path="/scheduled" element={<Scheduled />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  )
}

export default App
