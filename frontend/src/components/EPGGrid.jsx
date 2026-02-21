import { useMemo, useRef, useEffect } from 'react'
import { Stack, Text, Group, Badge, ScrollArea, Box, Divider } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { IconClock, IconDownload, IconCalendar } from '@tabler/icons-react'
import dayjs from 'dayjs'

const previousDownloadStatusMeta = {
  pending: { label: 'Queued', color: 'yellow' },
  downloading: { label: 'Downloading', color: 'yellow' },
  processing: { label: 'Processing', color: 'violet' },
  completed: { label: 'Downloaded', color: 'green' },
  failed: { label: 'Failed', color: 'red' },
  cancelled: { label: 'Cancelled', color: 'gray' },
}

function ProgramBlock({
  program,
  onClick,
  isPast,
  isCurrent,
  isDownloadable,
  isSchedulable,
  elementId,
  previousDownload,
}) {
  const startTime = dayjs(program.start_time)
  const endTime = dayjs(program.end_time)
  const isMobile = useMediaQuery('(max-width: 48em)')
  const previousStatus = previousDownload?.status
  const previousMeta = (previousStatus && previousDownloadStatusMeta[previousStatus]) || null

  const backgroundColor = isCurrent
    ? 'var(--mantine-color-green-light)'
    : isPast && program.has_archive
    ? 'rgba(245, 159, 0, 0.1)'
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
        borderTop: '1px solid transparent',
        borderRight: '1px solid transparent',
        borderBottom: '1px solid transparent',
        borderLeft: isDownloadable
          ? '3px solid #f59f00'
          : isSchedulable
          ? '3px solid var(--mantine-color-teal-6)'
          : '3px solid transparent',
        opacity: isPast && !program.has_archive ? 0.5 : 1,
        transition: 'box-shadow 0.15s, background-color 0.15s',
      }}
      onClick={() => isClickable && onClick(program, { action: isDownloadable ? 'download' : 'schedule' })}
      onMouseEnter={(e) => {
        if (isClickable) {
          e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.35)'
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = 'none'
      }}
    >
      <Stack gap={4}>
        <Group justify="space-between" wrap="nowrap">
          <Group gap={6} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
            {isCurrent && (
              <Box
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: '#fa5252',
                  flexShrink: 0,
                  animation: 'mustarrd-rec-pulse 1.5s ease-in-out infinite',
                }}
              />
            )}
            <Text
              size={isMobile ? 'xs' : 'sm'}
              fw={500}
              lineClamp={isMobile ? 2 : 1}
              style={{ minWidth: 0, lineHeight: isMobile ? 1.25 : undefined }}
            >
              {program.title}
            </Text>
          </Group>
          {ActionIcon && (
            <ActionIcon size={14} style={{ flexShrink: 0 }} opacity={0.7} />
          )}
        </Group>

        <Group gap="xs">
          <Text size="xs" c="dimmed">
            {startTime.format('h:mm A')} – {endTime.format('h:mm A')}
          </Text>
          <Badge size="xs" variant="light" color={isCurrent ? 'green' : isPast ? 'gray' : 'yellow'}>
            {program.duration_minutes}m
          </Badge>
          {previousMeta && (
            <Badge size="xs" variant="light" color={previousMeta.color}>
              {previousMeta.label}
            </Badge>
          )}
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

function DaySection({ date, programs, onProgramClick, getProgramPreviousDownload }) {
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
      <Group gap="xs" align="center">
        <Text
          fw={700}
          size="sm"
          style={isToday ? {
            color: '#f59f00',
            fontFamily: "'Bebas Neue', cursive",
            fontSize: 16,
            letterSpacing: '0.08em',
          } : {
            color: 'var(--mantine-color-dimmed)',
            textTransform: 'uppercase',
            fontSize: 11,
            letterSpacing: '0.08em',
          }}
        >
          {isToday ? 'Today' : date.format('ddd, MMM D')}
        </Text>
        <Divider style={{ flex: 1 }} />
        <Text size="xs" c="dimmed">{sortedPrograms.length}</Text>
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
          const previousDownload = getProgramPreviousDownload
            ? getProgramPreviousDownload(program)
            : null

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
              previousDownload={previousDownload}
            />
          )
        })}
      </Stack>
    </Stack>
  )
}

export default function EPGGrid({
  epgData,
  onProgramClick,
  showFuture = false,
  getProgramPreviousDownload = null,
}) {
  const scrollAreaRef = useRef(null)
  const didAutoScrollRef = useRef(false)
  const now = useMemo(() => dayjs(), [epgData, showFuture])

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
    didAutoScrollRef.current = false
  }, [epgData, showFuture])

  useEffect(() => {
    if (!scrollTargetId || didAutoScrollRef.current) return
    const target = document.getElementById(scrollTargetId)
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' })
      didAutoScrollRef.current = true
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
    <Stack gap="md" style={{ height: '100%', minHeight: 0 }}>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Showing {visiblePrograms.length} programs
        </Text>
        <Group gap="xs">
          <Badge variant="light" color="yellow" leftSection={<IconDownload size={12} />}>
            {downloadableCount} available
          </Badge>
          <Badge variant="light" color="teal" leftSection={<IconCalendar size={12} />}>
            {schedulableCount} upcoming
          </Badge>
        </Group>
      </Group>

      <ScrollArea style={{ flex: 1, minHeight: 0 }} ref={scrollAreaRef}>
        <Stack gap="lg">
          {programsByDay.map(({ date, programs }) => (
            <Box key={date.format('YYYY-MM-DD')} id={`epg-day-${date.format('YYYY-MM-DD')}`}>
              <DaySection
                date={date}
                programs={programs}
                onProgramClick={onProgramClick}
                getProgramPreviousDownload={getProgramPreviousDownload}
              />
            </Box>
          ))}
        </Stack>
      </ScrollArea>
    </Stack>
  )
}
