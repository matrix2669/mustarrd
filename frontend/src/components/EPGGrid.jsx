import { useMemo, useRef, useEffect } from 'react'
import { Stack, Text, Group, Badge, ScrollArea, Box } from '@mantine/core'
import { IconClock, IconDownload, IconCalendar } from '@tabler/icons-react'
import dayjs from 'dayjs'

function ProgramBlock({ program, onClick, isPast, isCurrent, isDownloadable, isSchedulable, elementId }) {
  const startTime = dayjs(program.start_time)
  const endTime = dayjs(program.end_time)

  const backgroundColor = isCurrent
    ? 'var(--mantine-color-green-light)'
    : isPast && program.has_archive
    ? 'var(--mantine-color-blue-light)'
    : isPast
    ? 'var(--mantine-color-dark-5)'
    : 'var(--mantine-color-dark-6)'

  const isClickable = isDownloadable || isSchedulable
  const actionIcon = isDownloadable ? IconDownload : isSchedulable ? IconCalendar : null
  const ActionIcon = actionIcon

  return (
    <Box
      id={elementId}
      style={{
        padding: '8px 12px',
        borderRadius: 6,
        backgroundColor,
        cursor: isClickable ? 'pointer' : 'default',
        border: isDownloadable
          ? '1px solid var(--mantine-color-blue-6)'
          : isSchedulable
          ? '1px solid var(--mantine-color-teal-6)'
          : '1px solid transparent',
        opacity: isPast && !program.has_archive ? 0.5 : 1,
        transition: 'transform 0.1s, box-shadow 0.1s',
      }}
      onClick={() => isClickable && onClick(program, { action: isDownloadable ? 'download' : 'schedule' })}
      onMouseEnter={(e) => {
        if (isClickable) {
          e.currentTarget.style.transform = 'scale(1.02)'
          e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.3)'
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'scale(1)'
        e.currentTarget.style.boxShadow = 'none'
      }}
    >
      <Stack gap={4}>
        <Group justify="space-between" wrap="nowrap">
          <Text size="sm" fw={500} truncate style={{ flex: 1 }}>
            {program.title}
          </Text>
          {ActionIcon && (
            <ActionIcon size={14} style={{ flexShrink: 0 }} opacity={0.7} />
          )}
        </Group>

        <Group gap="xs">
          <Badge size="xs" variant="outline">
            {startTime.format('h:mm A')} - {endTime.format('h:mm A')}
          </Badge>
          <Badge size="xs" variant="light" color={isCurrent ? 'green' : isPast ? 'gray' : 'blue'}>
            {program.duration_minutes}m
          </Badge>
        </Group>

        {program.description && (
          <Text size="xs" c="dimmed" lineClamp={2}>
            {program.description}
          </Text>
        )}
      </Stack>
    </Box>
  )
}

function DaySection({ date, programs, onProgramClick }) {
  const now = dayjs()
  const isToday = date.isSame(now, 'day')

  // Sort programs by start time
  const sortedPrograms = useMemo(() => {
    return [...programs].sort((a, b) =>
      dayjs(b.start_time).valueOf() - dayjs(a.start_time).valueOf()
    )
  }, [programs])

  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Text fw={600} size="sm">
          {isToday ? 'Today' : date.format('ddd, MMM D')}
        </Text>
        <Badge size="xs" variant="light">
          {sortedPrograms.length} programs
        </Badge>
      </Group>

      <Stack gap={6}>
        {sortedPrograms.map((program, idx) => {
          const start = dayjs(program.start_time)
          const end = dayjs(program.end_time)
          const isPast = end.isBefore(now)
          const isCurrent = start.isBefore(now) && end.isAfter(now)
          const isDownloadable = isPast && program.has_archive
          const isSchedulable = !isPast
          const elementId = `epg-program-${program.epg_id || program.id || idx}`

          return (
            <ProgramBlock
              key={program.id || idx}
              program={program}
              onClick={onProgramClick}
              isPast={isPast}
              isCurrent={isCurrent}
              isDownloadable={isDownloadable}
              isSchedulable={isSchedulable}
              elementId={elementId}
            />
          )
        })}
      </Stack>
    </Stack>
  )
}

export default function EPGGrid({ epgData, onProgramClick, showFuture = false }) {
  const scrollAreaRef = useRef(null)
  const now = dayjs()

  const visiblePrograms = useMemo(() => {
    if (!epgData) return epgData
    if (showFuture) return epgData
    return epgData.filter((program) => dayjs(program.end_time).isBefore(now))
  }, [epgData, showFuture, now])

  // Group programs by day
  const programsByDay = useMemo(() => {
    const grouped = {}

    if (!visiblePrograms) return []

    visiblePrograms.forEach((program) => {
      if (!program.start_time) return

      const date = dayjs(program.start_time).startOf('day')
      const key = date.format('YYYY-MM-DD')

      if (!grouped[key]) {
        grouped[key] = {
          date,
          programs: [],
        }
      }
      grouped[key].programs.push(program)
    })

    // Sort days
    return Object.values(grouped).sort((a, b) => b.date.valueOf() - a.date.valueOf())
  }, [visiblePrograms])

  const scrollTargetId = useMemo(() => {
    let target = null
    for (const { programs } of programsByDay) {
      const sorted = [...programs].sort((a, b) =>
        dayjs(b.start_time).valueOf() - dayjs(a.start_time).valueOf()
      )
      for (const program of sorted) {
        const start = dayjs(program.start_time)
        const end = dayjs(program.end_time)
        const isCurrent = start.isBefore(now) && end.isAfter(now)
        if (isCurrent) {
          target = program
          break
        }
      }
      if (target) break
    }
    if (!target) {
      for (const { programs } of programsByDay) {
        const sorted = [...programs].sort((a, b) =>
          dayjs(b.start_time).valueOf() - dayjs(a.start_time).valueOf()
        )
        for (const program of sorted) {
          const end = dayjs(program.end_time)
          if (end.isBefore(now)) {
            target = program
            break
          }
        }
        if (target) break
      }
    }
    return target ? `epg-program-${target.epg_id || target.id || 'target'}` : null
  }, [programsByDay, now])

  // Scroll to today on load
  useEffect(() => {
    if (!scrollTargetId) return
    const target = document.getElementById(scrollTargetId)
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [scrollTargetId])

  if (!visiblePrograms || visiblePrograms.length === 0) {
    return (
      <Stack align="center" justify="center" h={200}>
        <IconClock size={48} opacity={0.3} />
        <Text c="dimmed">No EPG data available</Text>
      </Stack>
    )
  }

  // Count downloadable programs
  const downloadableCount = visiblePrograms.filter(
    (p) => p.has_archive && dayjs(p.end_time).isBefore(dayjs())
  ).length
  const schedulableCount = visiblePrograms.filter(
    (p) => dayjs(p.end_time).isAfter(dayjs())
  ).length

  return (
    <Stack gap="md" style={{ height: '100%' }}>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Showing {epgData.length} programs
        </Text>
        <Group gap="xs">
          <Badge variant="light" color="blue" leftSection={<IconDownload size={12} />}>
            {downloadableCount} available
          </Badge>
          <Badge variant="light" color="teal" leftSection={<IconCalendar size={12} />}>
            {schedulableCount} upcoming
          </Badge>
        </Group>
      </Group>

      <Text size="xs" c="dimmed">
        Click past programs with a blue border to download. Click upcoming programs to schedule.
      </Text>

      <ScrollArea style={{ flex: 1 }} ref={scrollAreaRef}>
        <Stack gap="lg">
          {programsByDay.map(({ date, programs }) => (
            <Box key={date.format('YYYY-MM-DD')} id={`epg-day-${date.format('YYYY-MM-DD')}`}>
              <DaySection
                date={date}
                programs={programs}
                onProgramClick={onProgramClick}
              />
            </Box>
          ))}
        </Stack>
      </ScrollArea>
    </Stack>
  )
}
