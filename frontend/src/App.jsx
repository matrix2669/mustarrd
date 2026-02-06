import { useState, useEffect } from 'react'
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
import { downloadsApi, createDownloadWebSocket } from './api'
import mustarrdLogo from './assets/mustarrdlogo.png'

function App() {
  const [opened, { toggle }] = useDisclosure()
  const [activeDownloads, setActiveDownloads] = useState(0)

  // Fetch download queue for badge
  const { data: queue } = useQuery({
    queryKey: ['downloads', 'queue'],
    queryFn: downloadsApi.getQueue,
    refetchInterval: 5000,
  })

  useEffect(() => {
    if (queue) {
      setActiveDownloads(queue.length)
    }
  }, [queue])

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
      navbar={{ width: 250, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Navbar p="md">
        <Stack gap="md">
          <Group justify="flex-start">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
          </Group>
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
