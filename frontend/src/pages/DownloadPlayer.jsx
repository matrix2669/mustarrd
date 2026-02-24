import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Alert, Button, Group, Stack, Text, Title } from '@mantine/core'
import { IconAlertCircle, IconDownload } from '@tabler/icons-react'

export default function DownloadPlayer() {
  const { downloadId } = useParams()
  const parsedId = Number(downloadId)
  const isValidId = Number.isInteger(parsedId) && parsedId > 0

  const playUrl = useMemo(() => {
    if (!isValidId) return null
    return `/api/downloads/${parsedId}/file?action=play`
  }, [isValidId, parsedId])

  const downloadUrl = useMemo(() => {
    if (!isValidId) return null
    return `/api/downloads/${parsedId}/file?action=download`
  }, [isValidId, parsedId])

  if (!isValidId) {
    return (
      <Stack gap="md">
        <Title order={3}>Playback</Title>
        <Alert color="red" icon={<IconAlertCircle size={16} />}>
          Invalid download id.
        </Alert>
        <Group>
          <Button component={Link} to="/downloads" variant="default">Back to Downloads</Button>
        </Group>
      </Stack>
    )
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={3}>Playback</Title>
        <Group>
          <Button component={Link} to="/downloads" variant="default">Back to Downloads</Button>
          <Button
            component="a"
            href={downloadUrl}
            leftSection={<IconDownload size={14} />}
            variant="light"
          >
            Download File
          </Button>
        </Group>
      </Group>

      <Text size="sm" c="dimmed">
        Browser playback depends on codec support. If playback fails, use Download.
      </Text>

      <video
        controls
        preload="metadata"
        style={{ width: '100%', maxHeight: '70vh', background: '#000', borderRadius: 8 }}
        src={playUrl}
      />
    </Stack>
  )
}
