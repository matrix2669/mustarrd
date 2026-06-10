import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Title,
  Stack,
  Group,
  Text,
  Button,
  SegmentedControl,
  Alert,
  Loader,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { IconAlertCircle, IconDownload } from '@tabler/icons-react'
import dayjs from 'dayjs'

import { logsApi, createLogsWebSocket } from '../../api'
import classes from './LogsSection.module.css'

const LEVEL_LABELS = {
  info: 'INFO',
  warning: 'WARN',
  error: 'ERROR',
  debug: 'DEBUG',
}

const LEVEL_CLASSES = {
  info: classes.levelInfo,
  warning: classes.levelWarn,
  error: classes.levelError,
  debug: classes.levelDebug,
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

function entryMatchesFilter(entry, filter) {
  const source = String(entry?.source || '').toLowerCase()
  const level = String(entry?.level || 'info').toLowerCase()
  if (filter === 'warnings') return level === 'warning'
  if (filter === 'errors') return level === 'error'
  // "All" keeps the existing basic view: app activity without raw server logs.
  return source !== 'server' && ['info', 'warning', 'error'].includes(level)
}

export default function LogsSection({ showTitle = true }) {
  const [entries, setEntries] = useState([])
  const [filter, setFilter] = useState('all')
  const viewportRef = useRef(null)

  // Warnings/Errors map onto the backend's "minimal" view (warning+error);
  // All keeps "basic". Exact level filtering happens client-side below.
  const viewPreset = filter === 'all' ? 'basic' : 'minimal'

  const {
    data: recentLogs,
    isLoading,
    error,
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
      if (data.type === 'backend_log' && data.entry) {
        setEntries((prev) => mergeLogs(prev, [data.entry]))
      }
    })
    return () => ws.close()
  }, [])

  const filteredEntries = useMemo(
    () => entries.filter((entry) => entryMatchesFilter(entry, filter)),
    [entries, filter]
  )

  useEffect(() => {
    if (!viewportRef.current) return
    viewportRef.current.scrollTop = viewportRef.current.scrollHeight
  }, [filteredEntries])

  const handleDownload = () => {
    const lines = filteredEntries.map((entry) => {
      const ts = entry.timestamp ? dayjs(entry.timestamp).format('YYYY-MM-DD HH:mm:ss') : ''
      const level = LEVEL_LABELS[String(entry.level || 'info').toLowerCase()] || 'INFO'
      const source = entry.source ? `[${entry.source}]` : ''
      return [ts, level, source, entry.message || ''].filter(Boolean).join(' ')
    })
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `mustarrd-logs-${dayjs().format('YYYYMMDD-HHmmss')}.txt`
    link.click()
    URL.revokeObjectURL(url)
  }

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
    <Stack gap="lg">
      <div className={classes.header}>
        <Stack gap={2}>
          {showTitle ? (
            <Title order={2}>Logs</Title>
          ) : (
            <Text fw={700} size="lg">Logs</Text>
          )}
          <Text size="sm" c="dimmed">Recent application activity</Text>
        </Stack>
        <Group gap="xs" ml="auto" wrap="nowrap">
          <SegmentedControl
            value={filter}
            onChange={setFilter}
            data={[
              { label: 'All', value: 'all' },
              { label: 'Warnings', value: 'warnings' },
              { label: 'Errors', value: 'errors' },
            ]}
          />
          <Button
            size="xs"
            variant="default"
            leftSection={<IconDownload size={14} />}
            onClick={handleDownload}
            disabled={filteredEntries.length === 0}
          >
            Download
          </Button>
        </Group>
      </div>

      <div className={classes.viewer} ref={viewportRef}>
        {filteredEntries.length === 0 ? (
          <Text c="dimmed" ta="center" py="xl" size="sm">
            No log entries match the current filter.
          </Text>
        ) : (
          filteredEntries.map((entry) => {
            const level = String(entry.level || 'info').toLowerCase()
            return (
              <div key={entry.id ?? `${entry.timestamp}-${entry.source}-${entry.message}`} className={classes.line}>
                <span className={classes.ts}>{dayjs(entry.timestamp).format('HH:mm:ss')}</span>
                <span className={`${classes.level} ${LEVEL_CLASSES[level] || classes.levelInfo}`}>
                  {LEVEL_LABELS[level] || 'INFO'}
                </span>
                <span className={classes.message}>
                  {entry.account_name ? `${entry.account_name}: ` : ''}
                  {entry.download_id ? `[DL #${entry.download_id}] ` : ''}
                  {entry.message}
                </span>
              </div>
            )
          })
        )}
      </div>
    </Stack>
  )
}
