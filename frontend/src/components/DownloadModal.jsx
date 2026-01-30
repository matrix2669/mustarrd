import { useState, useEffect } from 'react'
import {
  Modal,
  Stack,
  Text,
  TextInput,
  Button,
  Group,
  Badge,
  Loader,
  Alert,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  IconDownload,
  IconClock,
  IconVideo,
  IconPlayerPlay,
  IconTrophy,
  IconFile,
} from '@tabler/icons-react'
import dayjs from 'dayjs'

import { downloadsApi } from '../api'

const typeIcons = {
  tv_show: IconVideo,
  movie: IconPlayerPlay,
  sports: IconTrophy,
  other: IconFile,
  news: IconFile,
}

const typeLabels = {
  tv_show: 'TV Show',
  movie: 'Movie',
  sports: 'Sports',
  news: 'News',
  other: 'Other',
}

export default function DownloadModal({ opened, onClose, program, channel, accountId }) {
  const queryClient = useQueryClient()
  const [filename, setFilename] = useState('')
  const [detectedType, setDetectedType] = useState('other')
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)

  // Get filename preview when modal opens
  useEffect(() => {
    if (opened && program && channel && accountId) {
      setIsLoadingPreview(true)
      downloadsApi
        .previewFilename({
          account_id: parseInt(accountId),
          channel_id: channel.stream_id.toString(),
          channel_name: channel.name,
          program: program,
        })
        .then((data) => {
          setFilename(data.filename.replace('.ts', ''))
          setDetectedType(data.detected_type)
        })
        .catch((err) => {
          console.error('Failed to get filename preview:', err)
          // Fall back to basic filename
          const date = dayjs(program.start_time).format('YYYY-MM-DD')
          setFilename(`${channel.name} - ${program.title} - ${date}`)
        })
        .finally(() => {
          setIsLoadingPreview(false)
        })
    }
  }, [opened, program, channel, accountId])

  const downloadMutation = useMutation({
    mutationFn: (data) => downloadsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downloads'] })
      notifications.show({
        title: 'Download Queued',
        message: 'Your download has been added to the queue',
        color: 'green',
      })
      onClose()
    },
    onError: (error) => {
      notifications.show({
        title: 'Error',
        message: error.message,
        color: 'red',
      })
    },
  })

  const handleDownload = () => {
    downloadMutation.mutate({
      account_id: parseInt(accountId),
      channel_id: channel.stream_id.toString(),
      channel_name: channel.name,
      program: program,
      custom_filename: filename ? `${filename}.ts` : null,
    })
  }

  if (!program || !channel) {
    return null
  }

  const startTime = dayjs(program.start_time)
  const endTime = dayjs(program.end_time)
  const TypeIcon = typeIcons[detectedType] || IconFile

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Download Program"
      size="lg"
    >
      <Stack>
        <Stack gap="xs">
          <Text fw={600} size="lg">
            {program.title}
          </Text>
          <Text size="sm" c="dimmed">
            {channel.name}
          </Text>
        </Stack>

        <Group gap="xs">
          <Badge variant="light" leftSection={<IconClock size={12} />}>
            {startTime.format('MMM D, YYYY h:mm A')}
          </Badge>
          <Badge variant="light">
            {program.duration_minutes} minutes
          </Badge>
          <Badge variant="light" color="blue" leftSection={<TypeIcon size={12} />}>
            {typeLabels[detectedType]}
          </Badge>
        </Group>

        {program.description && (
          <Alert variant="light" color="gray">
            <Text size="sm">{program.description}</Text>
          </Alert>
        )}

        <Stack gap="xs">
          <Text fw={500}>Filename</Text>
          {isLoadingPreview ? (
            <Group>
              <Loader size="sm" />
              <Text size="sm" c="dimmed">Generating filename...</Text>
            </Group>
          ) : (
            <TextInput
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              rightSection={<Text size="xs" c="dimmed">.ts</Text>}
              description="Auto-generated based on program type. Edit if needed."
            />
          )}
        </Stack>

        <Group justify="flex-end" mt="md">
          <Button variant="subtle" onClick={onClose}>
            Cancel
          </Button>
          <Button
            leftSection={<IconDownload size={16} />}
            onClick={handleDownload}
            loading={downloadMutation.isPending}
            disabled={isLoadingPreview || !filename}
          >
            Download
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
