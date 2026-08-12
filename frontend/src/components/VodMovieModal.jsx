import { useMemo } from 'react'
import {
  Modal,
  Stack,
  Text,
  Button,
  Group,
  Badge,
  Loader,
  Alert,
  Image,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IconPlayerPlay, IconCalendar } from '@tabler/icons-react'

import { vodApi } from '../api'

export function extractReleaseDate(info) {
  const value =
    info?.info?.releasedate ??
    info?.info?.releaseDate ??
    info?.info?.year ??
    info?.releasedate ??
    info?.releaseDate ??
    info?.year ??
    null

  if (value === null || value === undefined || value === '') return null
  return String(value)
}

export function extractTmdbId(info) {
  const value =
    info?.info?.tmdb_id ??
    info?.info?.tmdb ??
    info?.tmdb_id ??
    info?.tmdb ??
    null

  if (value === null || value === undefined || value === '') return null
  const match = String(value).trim().match(/(?:^|\/)(\d+)(?:\/?$)/)
  return match ? match[1] : null
}

export default function MovieModal({ opened, onClose, movie, accountId }) {
  const queryClient = useQueryClient()

  const { data: movieInfo, isLoading, error } = useQuery({
    queryKey: ['vod', 'movie', accountId, movie?.stream_id],
    queryFn: () => vodApi.getMovieInfo(accountId, movie.stream_id),
    enabled: !!opened && !!movie && !!accountId,
    retry: false,
  })

  const releaseDate = useMemo(() => extractReleaseDate(movieInfo), [movieInfo])
  const tmdbId = useMemo(() => extractTmdbId(movieInfo), [movieInfo])

  const downloadMutation = useMutation({
    mutationFn: (data) => vodApi.downloadMovie(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downloads'] })
      notifications.show({
        title: 'Download Queued',
        message: 'Your movie has been added to the download queue',
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
    if (!movie || !accountId) return
    downloadMutation.mutate({
      account_id: parseInt(accountId),
      vod_id: movie.stream_id?.toString(),
      name: movie.name,
      container_extension: movie.container_extension,
      direct_source: movie.direct_source || null,
      release_date: releaseDate,
      tmdb_id: tmdbId,
    })
  }

  if (!movie) return null

  return (
    <Modal opened={opened} onClose={onClose} title="On Demand Movie" size="lg">
      <Stack>
        <Group gap="md" wrap="nowrap">
          {movie.stream_icon && (
            <Image
              src={movie.stream_icon}
              alt={movie.name}
              w={96}
              h={96}
              fit="contain"
              fallbackSrc="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>"
            />
          )}
          <Stack gap={4} style={{ flex: 1 }}>
            <Text fw={600} size="lg">
              {movie.name}
            </Text>
            <Group gap="xs">
              <Badge variant="light" leftSection={<IconPlayerPlay size={12} />}>
                Movie
              </Badge>
              {releaseDate && (
                <Badge variant="light" leftSection={<IconCalendar size={12} />}>
                  {releaseDate}
                </Badge>
              )}
            </Group>
          </Stack>
        </Group>

        {isLoading ? (
          <Group>
            <Loader size="sm" />
            <Text size="sm" c="dimmed">Loading details...</Text>
          </Group>
        ) : error ? (
          <Alert color="yellow" variant="light">
            <Text size="sm">Unable to load movie details. You can still download it.</Text>
          </Alert>
        ) : (
          movieInfo?.info?.plot && (
            <Alert variant="light" color="gray">
              <Text size="sm">{movieInfo.info.plot}</Text>
            </Alert>
          )
        )}

        <Group justify="flex-end" mt="md">
          <Button variant="subtle" onClick={onClose}>
            Close
          </Button>
          <Button
            leftSection={<IconPlayerPlay size={16} />}
            onClick={handleDownload}
            loading={downloadMutation.isPending}
          >
            Download
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
