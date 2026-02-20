import { useState, useEffect, useRef } from 'react'
import { Routes, Route, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import {
  AppShell,
  Burger,
  Group,
  NavLink as MantineNavLink,
  Badge,
  Stack,
  Button,
  Text,
  Box,
  Divider,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import {
  IconServer,
  IconSearch,
  IconDownload,
  IconCalendar,
  IconSettings,
  IconListDetails,
} from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import Accounts from './pages/Accounts'
import Browse from './pages/Browse'
import Downloads from './pages/Downloads'
import Scheduled from './pages/Scheduled'
import Settings from './pages/Settings'
import Logs from './pages/Logs'
import Login from './pages/Login'
import { authApi, downloadsApi, epgApi, createDownloadWebSocket } from './api'

function ProtectedRoute({ authStatus, authLoading }) {
  const location = useLocation()

  if (authLoading) {
    return null
  }

  if (authStatus?.authenticated) {
    return <Outlet />
  }

  return <Navigate to="/login" replace state={{ from: location.pathname }} />
}

function App() {
  const [opened, { toggle, close }] = useDisclosure()
  const [activeDownloads, setActiveDownloads] = useState(0)
  const epgToastVisibleRef = useRef(false)
  const epgToastCloseTimerRef = useRef(null)
  const epgToastPendingCloseRef = useRef(false)
  const queryClient = useQueryClient()

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
  const { data: authStatus, isLoading: authLoading } = useQuery({
    queryKey: ['auth', 'status'],
    queryFn: authApi.status,
  })

  const logoutMutation = useMutation({
    mutationFn: authApi.logout,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['auth', 'status'] })
      notifications.show({
        title: 'Logged out',
        message: 'Admin access is now locked.',
        color: 'yellow',
      })
    },
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
      inserted_programs: insertedPrograms,
      total_programs: totalPrograms,
      last_error: lastError,
    } = epgStatus

    const processed = typeof processedPrograms === 'number' ? processedPrograms : 0
    const inserted = typeof insertedPrograms === 'number' ? insertedPrograms : 0
    const total = typeof totalPrograms === 'number' ? totalPrograms : null
    const hasTotal = total && total > 0
    const percent = hasTotal ? Math.min(100, Math.round((processed / total) * 100)) : null
    const percentLabel = percent != null ? ` • ${percent}%` : ''
    const title = accountName
      ? `Syncing EPG (${accountName}${percentLabel})`
      : 'Syncing EPG'
    const message = hasTotal
      ? `${inserted.toLocaleString()} new, ${processed.toLocaleString()} scanned of ${total.toLocaleString()} (${percent}%).`
      : `${inserted.toLocaleString()} new, ${processed.toLocaleString()} scanned so far.`

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
          message: `${inserted.toLocaleString()} new programs added.`,
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
    { icon: IconServer, label: 'Accounts', to: '/accounts', adminOnly: true },
    { icon: IconSearch, label: 'Browse', to: '/browse' },
    {
      icon: IconDownload,
      label: 'Downloads',
      to: '/downloads',
      badge: activeDownloads > 0 ? activeDownloads : null,
    },
    { icon: IconCalendar, label: 'Scheduled', to: '/scheduled' },
    { icon: IconListDetails, label: 'Logs', to: '/logs' },
    { icon: IconSettings, label: 'Settings', to: '/settings', adminOnly: true },
  ].filter((item) => !item.adminOnly || authStatus?.authenticated)

  return (
    <AppShell
      header={{ height: { base: 56, sm: 0 } }}
      navbar={{ width: 250, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header hiddenFrom="sm" style={{ borderBottom: '2px solid #f59f00' }}>
        <Group h="100%" px="md" justify="space-between">
          <Burger opened={opened} onClick={toggle} size="sm" />
          <Text
            style={{
              fontFamily: "'Bebas Neue', cursive",
              fontSize: 22,
              letterSpacing: '0.12em',
              color: '#f59f00',
              lineHeight: 1,
            }}
          >
            MUSTARRD
          </Text>
          <Group gap={5} align="center">
            <Box
              style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                background: '#fa5252',
                animation: 'mustarrd-rec-pulse 1.5s ease-in-out infinite',
              }}
            />
            <Text size="xs" fw={700} c="red" style={{ letterSpacing: '0.12em' }}>
              REC
            </Text>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md" style={{ borderTop: '3px solid #f59f00' }}>
        <Stack gap="md">
          <Group mb={4} justify="space-between" align="center" wrap="nowrap">
            <Text
              style={{
                fontFamily: "'Bebas Neue', cursive",
                fontSize: 28,
                letterSpacing: '0.12em',
                color: '#f59f00',
                lineHeight: 1,
              }}
            >
              MUSTARRD
            </Text>
            <Group gap={5} align="center">
              <Box
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: '#fa5252',
                  animation: 'mustarrd-rec-pulse 1.5s ease-in-out infinite',
                }}
              />
              <Text size="xs" fw={700} c="red" style={{ letterSpacing: '0.12em' }}>
                REC
              </Text>
            </Group>
          </Group>
          <Divider mb={4} />
          {navItems.map((item) => (
            <MantineNavLink
              key={item.to}
              component={NavLink}
              to={item.to}
              onClick={close}
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
          {authStatus?.authenticated ? (
            <Button
              variant="light"
              color="gray"
              onClick={() => logoutMutation.mutate()}
              loading={logoutMutation.isPending}
            >
              Log Out Admin
            </Button>
          ) : (
            <Button component={NavLink} to="/login" variant="light">
              Admin Login
            </Button>
          )}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>
        <Routes>
          <Route path="/" element={<Navigate to="/browse" replace />} />
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute authStatus={authStatus} authLoading={authLoading} />}>
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
          <Route path="/browse" element={<Browse />} />
          <Route path="/downloads" element={<Downloads />} />
          <Route path="/scheduled" element={<Scheduled />} />
          <Route path="/logs" element={<Logs />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  )
}

export default App
