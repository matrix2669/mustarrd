import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Title,
  Card,
  Stack,
  Group,
  Text,
  Badge,
  Button,
  ScrollArea,
  SegmentedControl,
  TextInput,
  Switch,
  Alert,
  Loader,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { IconAlertCircle, IconSearch, IconRefresh, IconTrash } from '@tabler/icons-react'
import dayjs from 'dayjs'

import { logsApi, createLogsWebSocket } from '../../api'


function sourceColor(source) {
  if (source === 'epg') return 'blue'
  if (source === 'download') return 'teal'
  if (source === 'server') return 'grape'
  return 'gray'
}

function levelColor(level) {
  if (level === 'error') return 'red'
  if (level === 'warning') return 'yellow'
  if (level === 'debug') return 'grape'
  return 'gray'
}

function mergeLogs(existing, incoming) {
  const byId = new Map()
  for (const entry of existing) {
    byId.set(entry.id ?? `${entry.timestamp}-${entry.source}-${entry.message}`, entry)
  }
  for (const entry of incoming) {
    byId.set(entry.id ?? `${entry.timestamp}-${entry.source}-${entry.message}`, entry)
  }
  return Array.from(byId.values())
    .sort((a, b) => String(a.timestamp || '').localeCompare(String(b.timestamp || '')))
    .slice(-3000)
}

function entryMatchesView(entry, view) {
  const source = String(entry?.source || '').toLowerCase()
  const level = String(entry?.level || 'info').toLowerCase()

  if (view === 'detailed') {
    return ['debug', 'info', 'warning', 'error'].includes(level)
  }
  if (view === 'minimal') {
    return ['warning', 'error'].includes(level)
  }
  return source !== 'server' && ['info', 'warning', 'error'].includes(level)
}

export default function LogsSection({ showTitle = true }) {
  const [entries, setEntries] = useState([])
  const [viewPreset, setViewPreset] = useState('basic')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const viewportRef = useRef(null)

  const {
    data: recentLogs,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['logs', 'recent', viewPreset],
    queryFn: () => logsApi.list(600, null, null, viewPreset),
    refetchInterval: 30000,
  })

  useEffect(() => {
    if (!recentLogs) return
    setEntries((prev) => mergeLogs(prev, recentLogs))
  }, [recentLogs])

  useEffect(() => {
    const ws = createLogsWebSocket((data) => {
      if (data.type === 'backend_log' && data.entry && entryMatchesView(data.entry, viewPreset)) {
        setEntries((prev) => mergeLogs(prev, [data.entry]))
      }
    })
    return () => ws.close()
  }, [viewPreset])

  useEffect(() => {
    if (!autoScroll || !viewportRef.current) return
    viewportRef.current.scrollTop = viewportRef.current.scrollHeight
  }, [entries, autoScroll])

  const filteredEntries = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return entries.filter((entry) => {
      if (!entryMatchesView(entry, viewPreset)) {
        return false
      }
      if (sourceFilter !== 'all' && entry.source !== sourceFilter) {
        return false
      }
      if (!needle) return true
      const message = `${entry.message || ''} ${entry.account_name || ''}`.toLowerCase()
      return message.includes(needle)
    })
  }, [entries, sourceFilter, search, viewPreset])

  if (isLoading) {
    return (
      <Stack align="center" justify="center" h={300}>
        <Loader />
      </Stack>
    )
  }

  if (error) {
    return (
      <Alert icon={<IconAlertCircle size={16} />} title="Failed to load logs" color="red">
        {error.message}
      </Alert>
    )
  }

  return (
    <Stack>
      <Group justify="space-between">
        {showTitle ? <Title order={2}>Backend Logs</Title> : <Title order={4}>Logs</Title>}
        <Group gap="xs">
          <Switch
            label="Auto-scroll"
            checked={autoScroll}
            onChange={(event) => setAutoScroll(event.currentTarget.checked)}
          />
          <Button variant="light" leftSection={<IconRefresh size={14} />} onClick={() => refetch()}>
            Refresh
          </Button>
          <Button
            variant="subtle"
            color="red"
            leftSection={<IconTrash size={14} />}
            onClick={() => setEntries([])}
          >
            Clear View
          </Button>
        </Group>
      </Group>

      <Group gap="sm">
        <SegmentedControl
          value={viewPreset}
          onChange={setViewPreset}
          data={[
            { label: 'Detailed', value: 'detailed' },
            { label: 'Basic', value: 'basic' },
            { label: 'Minimal', value: 'minimal' },
          ]}
        />
        <SegmentedControl
          value={sourceFilter}
          onChange={setSourceFilter}
          data={[
            { label: 'All', value: 'all' },
            { label: 'EPG', value: 'epg' },
            { label: 'Downloads', value: 'download' },
            { label: 'Server', value: 'server' },
          ]}
        />
        <TextInput
          placeholder="Search logs..."
          leftSection={<IconSearch size={14} />}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          style={{ flex: 1, minWidth: 220 }}
        />
      </Group>

      <Card shadow="sm" padding="md" radius="md" withBorder style={{ height: 'calc(100vh - 280px)' }}>
        <ScrollArea style={{ height: '100%' }} viewportRef={viewportRef}>
          <Stack gap={6}>
            {filteredEntries.length === 0 ? (
              <Text c="dimmed" ta="center" py="xl">
                No log entries match the current filters.
              </Text>
            ) : (
              filteredEntries.map((entry) => (
                <Group key={entry.id ?? `${entry.timestamp}-${entry.source}-${entry.message}`} gap="xs" align="flex-start" wrap="nowrap">
                  <Text size="xs" c="dimmed" ff="monospace" style={{ width: 88, flexShrink: 0 }}>
                    {dayjs(entry.timestamp).format('HH:mm:ss')}
                  </Text>
                  <Badge size="xs" variant="light" color={sourceColor(entry.source)} style={{ flexShrink: 0 }}>
                    {(entry.source || 'system').toUpperCase()}
                  </Badge>
                  <Badge size="xs" variant="outline" color={levelColor(entry.level)} style={{ flexShrink: 0 }}>
                    {(entry.level || 'info').toUpperCase()}
                  </Badge>
                  {entry.download_id && (
                    <Badge size="xs" variant="outline" color="gray" style={{ flexShrink: 0 }}>
                      DL #{entry.download_id}
                    </Badge>
                  )}
                  {entry.account_name && viewPreset === 'detailed' && (
                    <Badge size="xs" variant="outline" color="gray" style={{ flexShrink: 0 }}>
                      {entry.account_name}
                    </Badge>
                  )}
                  <Text size="xs" ff="monospace" style={{ wordBreak: 'break-word' }}>
                    {entry.message}
                  </Text>
                </Group>
              ))
            )}
          </Stack>
        </ScrollArea>
      </Card>
    </Stack>
  )
}
