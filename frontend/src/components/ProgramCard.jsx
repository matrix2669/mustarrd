import { Card, Stack, Text, Group, Badge, ActionIcon } from '@mantine/core'
import { IconDownload, IconClock } from '@tabler/icons-react'
import { getChannelDisplayTime, getNowUtc, getProgramInstant } from '../utils/channelTime'

export default function ProgramCard({ program, channel, onClick, showDownload = true, guideOffsetHours = 0 }) {
  const startTime = getChannelDisplayTime(program, 'start', guideOffsetHours)
  const endTime = getChannelDisplayTime(program, 'end', guideOffsetHours)
  const now = getNowUtc()
  const startInstant = getProgramInstant(program, 'start')
  const endInstant = getProgramInstant(program, 'end')
  const isPast = Boolean(endInstant?.isBefore(now))
  const isCurrent = Boolean(startInstant?.isBefore(now) && endInstant?.isAfter(now))
  const isDownloadable = isPast && program.has_archive

  return (
    <Card
      shadow="sm"
      padding="sm"
      radius="md"
      withBorder
      style={{
        cursor: isDownloadable ? 'pointer' : 'default',
        borderColor: isDownloadable
          ? 'var(--mantine-color-blue-6)'
          : isCurrent
          ? 'var(--mantine-color-green-6)'
          : undefined,
        opacity: isPast && !program.has_archive ? 0.6 : 1,
      }}
      onClick={() => isDownloadable && onClick?.(program)}
    >
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <Stack gap={2} style={{ flex: 1, overflow: 'hidden' }}>
            <Text fw={500} truncate>
              {program.title}
            </Text>
            {channel && (
              <Text size="sm" c="dimmed" truncate>
                {channel.name}
              </Text>
            )}
          </Stack>
          {showDownload && isDownloadable && (
            <ActionIcon variant="light" color="blue" size="lg">
              <IconDownload size={18} />
            </ActionIcon>
          )}
        </Group>

        <Group gap="xs">
          <Badge
            size="sm"
            variant="light"
            color={isCurrent ? 'green' : isPast ? 'gray' : 'blue'}
            leftSection={<IconClock size={10} />}
          >
            {startTime?.format('h:mm A') || 'Unknown'} - {endTime?.format('h:mm A') || 'Unknown'}
          </Badge>
          <Badge size="sm" variant="outline">
            {program.duration_minutes}m
          </Badge>
          {isCurrent && (
            <Badge size="sm" color="green">
              Now Playing
            </Badge>
          )}
          {isDownloadable && (
            <Badge size="sm" color="blue">
              Available
            </Badge>
          )}
        </Group>

        {program.description && (
          <Text size="xs" c="dimmed" lineClamp={2}>
            {program.description}
          </Text>
        )}
      </Stack>
    </Card>
  )
}
