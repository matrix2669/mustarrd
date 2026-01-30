import { useState, useEffect } from 'react'
import {
  Title,
  Card,
  Group,
  Text,
  Stack,
  Badge,
  ActionIcon,
  Menu,
  Tabs,
  Loader,
  Alert,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  IconDotsVertical,
  IconPlayerStop,
  IconRefresh,
  IconTrash,
  IconAlertCircle,
  IconCheck,
  IconX,
  IconClock,
  IconDownload,
  IconSettings,
} from '@tabler/icons-react'
import dayjs from 'dayjs'
import duration from 'dayjs/plugin/duration'

import { downloadsApi, createDownloadWebSocket } from '../api'
import ProgressBar from '../components/ProgressBar'

dayjs.extend(duration)

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

function formatDuration(minutes) {
  const d = dayjs.duration(minutes, 'minutes')
  const hours = d.hours()
  const mins = d.minutes()
  if (hours > 0) {
    return `${hours}h ${mins}m`
  }
  return `${mins}m`
}

function getStatusBadge(status) {
  const statusConfig = {
    pending: { color: 'gray', icon: IconClock, label: 'Pending' },
    downloading: { color: 'blue', icon: IconDownload, label: 'Downloading' },
    processing: { color: 'teal', icon: IconSettings, label: 'Processing' },
    completed: { color: 'green', icon: IconCheck, label: 'Completed' },
    failed: { color: 'red', icon: IconX, label: 'Failed' },
    cancelled: { color: 'orange', icon: IconX, label: 'Cancelled' },
  }

  const config = statusConfig[status] || statusConfig.pending
  const Icon = config.icon

  return (
    <Badge color={config.color} variant="light" leftSection={<Icon size={12} />}>
      {config.label}
    </Badge>
  )
}

function DownloadCard({ download, onCancel, onRetry, onDelete }) {
  const isActive = ['pending', 'downloading', 'processing'].includes(download.status)
  const canRetry = ['failed', 'cancelled'].includes(download.status)

  return (
    <Card shadow="sm" padding="md" radius="md" withBorder>
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <Stack gap={2} style={{ flex: 1, overflow: 'hidden' }}>
            <Text fw={500} truncate>
              {download.program_title}
            </Text>
            <Text size="sm" c="dimmed" truncate>
              {download.channel_name}
            </Text>
          </Stack>
          <Group gap="xs">
            {getStatusBadge(download.status)}
            <Menu shadow="md" width={150}>
              <Menu.Target>
                <ActionIcon variant="subtle">
                  <IconDotsVertical size={16} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                {isActive && (
                  <Menu.Item
                    leftSection={<IconPlayerStop size={14} />}
                    onClick={() => onCancel(download)}
                  >
                    Cancel
                  </Menu.Item>
                )}
                {canRetry && (
                  <Menu.Item
                    leftSection={<IconRefresh size={14} />}
                    onClick={() => onRetry(download)}
                  >
                    Retry
                  </Menu.Item>
                )}
                {!isActive && (
                  <Menu.Item
                    color="red"
                    leftSection={<IconTrash size={14} />}
                    onClick={() => onDelete(download)}
                  >
                    Delete
                  </Menu.Item>
                )}
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>

        <Group gap="xs" wrap="nowrap">
          <Text size="xs" c="dimmed">
            {dayjs(download.program_start).format('MMM D, YYYY h:mm A')}
          </Text>
          <Text size="xs" c="dimmed">
            ({formatDuration(download.duration_minutes)})
          </Text>
        </Group>

        {['downloading', 'processing'].includes(download.status) && (
          <Stack gap={4}>
            <ProgressBar
              progress={download.progress}
              color={download.status === 'processing' ? 'teal' : 'blue'}
              indeterminate={download.indeterminate}
            />
            <Group justify="space-between">
              {download.status === 'downloading' && (
                <Text size="xs" c="dimmed">
                  {formatBytes(download.downloaded_bytes)} / {formatBytes(download.file_size)}
                </Text>
              )}
              {!download.indeterminate && (
                <Text size="xs" c="dimmed">
                  {download.progress?.toFixed(1)}%
                </Text>
              )}
            </Group>
            {download.status === 'processing' && (
              <Text size="xs" c="dimmed">
                {download.message || 'Processing...'}
              </Text>
            )}
          </Stack>
        )}

        {download.logs?.length > 0 && (
          <Card withBorder radius="sm" p="xs" bg="dark.8">
            <Stack gap={2}>
              {download.logs.slice(-6).map((line, index) => (
                <Text key={`${download.id}-log-${index}`} size="xs" c="dimmed" ff="monospace">
                  {line}
                </Text>
              ))}
            </Stack>
          </Card>
        )}

        {download.status === 'completed' && (
          <Tooltip label={download.output_path}>
            <Text size="xs" c="dimmed" truncate>
              Saved to: {download.output_path.split('/').pop()}
            </Text>
          </Tooltip>
        )}

        {download.status === 'failed' && download.error_message && (
          <Alert color="red" variant="light" p="xs">
            <Text size="xs">{download.error_message}</Text>
          </Alert>
        )}
      </Stack>
    </Card>
  )
}

export default function Downloads() {
  const queryClient = useQueryClient()
  const [localProgress, setLocalProgress] = useState({})
  const [localLogs, setLocalLogs] = useState({})

  // Fetch downloads
  const { data: downloads, isLoading, error } = useQuery({
    queryKey: ['downloads'],
    queryFn: downloadsApi.list,
    refetchInterval: 5000,
  })

  // WebSocket for real-time updates
  useEffect(() => {
    const ws = createDownloadWebSocket((data) => {
      if (data.type === 'progress') {
        setLocalProgress((prev) => ({
          ...prev,
          [data.download_id]: {
            progress: data.progress,
            status: data.status,
            downloaded_bytes: data.downloaded_bytes,
            file_size: data.file_size,
            message: data.message,
            indeterminate: data.indeterminate,
          },
        }))

        // Refresh on status change
        if (['completed', 'failed', 'cancelled'].includes(data.status)) {
          queryClient.invalidateQueries({ queryKey: ['downloads'] })
        }
      } else if (data.type === 'log') {
        setLocalLogs((prev) => {
          const existing = prev[data.download_id] || []
          const timestamp = dayjs().format('HH:mm:ss')
          const next = [...existing, `[${timestamp}] ${data.message}`].slice(-200)
          return { ...prev, [data.download_id]: next }
        })
      }
    })

    return () => ws.close()
  }, [queryClient])

  const cancelMutation = useMutation({
    mutationFn: (download) => downloadsApi.cancel(download.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downloads'] })
      notifications.show({
        title: 'Download Cancelled',
        message: 'The download has been cancelled',
        color: 'orange',
      })
    },
    onError: (error) => {
      notifications.show({
        title: 'Error',
        message: error.message,
        color: 'red',
      })
    },
  })

  const retryMutation = useMutation({
    mutationFn: (download) => downloadsApi.retry(download.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downloads'] })
      notifications.show({
        title: 'Download Restarted',
        message: 'The download has been queued',
        color: 'blue',
      })
    },
    onError: (error) => {
      notifications.show({
        title: 'Error',
        message: error.message,
        color: 'red',
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (download) => downloadsApi.cancel(download.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downloads'] })
      notifications.show({
        title: 'Download Removed',
        message: 'The download has been removed from history',
        color: 'green',
      })
    },
  })

  // Merge WebSocket updates with fetched data
  const enhancedDownloads = downloads?.map((d) => ({
    ...d,
    ...localProgress[d.id],
    logs: localLogs[d.id],
  }))

  const activeDownloads = enhancedDownloads?.filter((d) =>
    ['pending', 'downloading', 'processing'].includes(d.status)
  ) || []

  const historyDownloads = enhancedDownloads?.filter((d) =>
    ['completed', 'failed', 'cancelled'].includes(d.status)
  ) || []

  if (isLoading) {
    return (
      <Stack align="center" justify="center" h={300}>
        <Loader />
      </Stack>
    )
  }

  if (error) {
    return (
      <Alert icon={<IconAlertCircle size={16} />} title="Error" color="red">
        Failed to load downloads: {error.message}
      </Alert>
    )
  }

  return (
    <Stack>
      <Title order={2}>Downloads</Title>

      <Tabs defaultValue="active">
        <Tabs.List>
          <Tabs.Tab value="active" leftSection={<IconDownload size={16} />}>
            Active {activeDownloads.length > 0 && `(${activeDownloads.length})`}
          </Tabs.Tab>
          <Tabs.Tab value="history" leftSection={<IconClock size={16} />}>
            History {historyDownloads.length > 0 && `(${historyDownloads.length})`}
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="active" pt="md">
          {activeDownloads.length === 0 ? (
            <Card shadow="sm" padding="xl" radius="md" withBorder>
              <Stack align="center" gap="md">
                <IconDownload size={48} opacity={0.3} />
                <Text c="dimmed" ta="center">
                  No active downloads. Browse channels to start downloading.
                </Text>
              </Stack>
            </Card>
          ) : (
            <Stack gap="md">
              {activeDownloads.map((download) => (
                <DownloadCard
                  key={download.id}
                  download={download}
                  onCancel={(d) => cancelMutation.mutate(d)}
                  onRetry={(d) => retryMutation.mutate(d)}
                  onDelete={(d) => deleteMutation.mutate(d)}
                />
              ))}
            </Stack>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="history" pt="md">
          {historyDownloads.length === 0 ? (
            <Card shadow="sm" padding="xl" radius="md" withBorder>
              <Stack align="center" gap="md">
                <IconClock size={48} opacity={0.3} />
                <Text c="dimmed" ta="center">
                  No download history yet.
                </Text>
              </Stack>
            </Card>
          ) : (
            <Stack gap="md">
              {historyDownloads.map((download) => (
                <DownloadCard
                  key={download.id}
                  download={download}
                  onCancel={(d) => cancelMutation.mutate(d)}
                  onRetry={(d) => retryMutation.mutate(d)}
                  onDelete={(d) => deleteMutation.mutate(d)}
                />
              ))}
            </Stack>
          )}
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
