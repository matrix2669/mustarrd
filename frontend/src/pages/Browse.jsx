import { useState, useMemo, useEffect, useRef } from 'react'
import {
  Title,
  Select,
  Card,
  Group,
  Text,
  Stack,
  TextInput,
  ScrollArea,
  Badge,
  Loader,
  Alert,
  Box,
  Image,
  Tabs,
  Button,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import {
  IconSearch,
  IconAlertCircle,
  IconVideo,
  IconClock,
  IconPlayerPlay,
} from '@tabler/icons-react'
import dayjs from 'dayjs'

import { accountsApi, channelsApi, epgApi, settingsApi, vodApi } from '../api'
import EPGGrid from '../components/EPGGrid'
import DownloadModal from '../components/DownloadModal'
import ScheduleModal from '../components/ScheduleModal'
import MovieModal from '../components/VodMovieModal'
import SeriesModal from '../components/VodSeriesModal'

function ChannelList({ channels, selectedChannel, onSelectChannel, isLoading }) {
  const [search, setSearch] = useState('')

  const filteredChannels = useMemo(() => {
    if (!channels) return []
    if (!search) return channels
    const searchLower = search.toLowerCase()
    return channels.filter((ch) => ch.name?.toLowerCase().includes(searchLower))
  }, [channels, search])

  if (isLoading) {
    return (
      <Stack align="center" justify="center" h={200}>
        <Loader />
      </Stack>
    )
  }

  return (
    <Stack gap="xs" style={{ height: '100%' }}>
      <TextInput
        placeholder="Search channels..."
        leftSection={<IconSearch size={16} />}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <ScrollArea style={{ flex: 1 }}>
        <Stack gap={4}>
          {filteredChannels.map((channel) => (
            <Card
              key={channel.stream_id}
              padding="xs"
              radius="sm"
              withBorder
              style={{
                cursor: 'pointer',
                backgroundColor:
                  selectedChannel?.stream_id === channel.stream_id
                    ? 'var(--mantine-color-blue-light)'
                    : undefined,
              }}
              onClick={() => onSelectChannel(channel)}
            >
              <Group gap="xs" wrap="nowrap">
                {channel.stream_icon ? (
                  <Image
                    src={channel.stream_icon}
                    alt={channel.name}
                    w={32}
                    h={32}
                    fit="contain"
                    fallbackSrc="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>"
                  />
                ) : (
                  <Box w={32} h={32} bg="dark.5" style={{ borderRadius: 4 }} />
                )}
                <Stack gap={0} style={{ flex: 1, overflow: 'hidden' }}>
                  <Text size="sm" fw={500} truncate>
                    {channel.name}
                  </Text>
                  {channel.tv_archive_duration && (
                    <Text size="xs" c="dimmed">
                      {channel.tv_archive_duration} days catchup
                    </Text>
                  )}
                </Stack>
              </Group>
            </Card>
          ))}
          {filteredChannels.length === 0 && (
            <Text c="dimmed" ta="center" py="md">
              No channels found
            </Text>
          )}
        </Stack>
      </ScrollArea>
    </Stack>
  )
}

function CategoryList({ categories, selectedCategory, onSelectCategory, isLoading, label }) {
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!categories) return []
    if (!search) return categories
    const searchLower = search.toLowerCase()
    return categories.filter((cat) => cat.category_name?.toLowerCase().includes(searchLower))
  }, [categories, search])

  if (isLoading) {
    return (
      <Stack align="center" justify="center" h={200}>
        <Loader />
      </Stack>
    )
  }

  return (
    <Stack gap="xs" style={{ height: '100%' }}>
      <TextInput
        placeholder={`Search ${label || 'categories'}...`}
        leftSection={<IconSearch size={16} />}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <ScrollArea style={{ flex: 1 }}>
        <Stack gap={4}>
          <Card
            padding="xs"
            radius="sm"
            withBorder
            style={{
              cursor: 'pointer',
              backgroundColor: selectedCategory == null ? 'var(--mantine-color-blue-light)' : undefined,
            }}
            onClick={() => onSelectCategory(null)}
          >
            <Text size="sm" fw={500}>
              All Categories
            </Text>
          </Card>
          {filtered.map((category) => (
            <Card
              key={category.category_id}
              padding="xs"
              radius="sm"
              withBorder
              style={{
                cursor: 'pointer',
                backgroundColor:
                  selectedCategory === category.category_id
                    ? 'var(--mantine-color-blue-light)'
                    : undefined,
              }}
              onClick={() => onSelectCategory(category.category_id)}
            >
              <Text size="sm" fw={500} truncate>
                {category.category_name}
              </Text>
            </Card>
          ))}
          {filtered.length === 0 && (
            <Text c="dimmed" ta="center" py="md">
              No categories found
            </Text>
          )}
        </Stack>
      </ScrollArea>
    </Stack>
  )
}

function VodGrid({ items, onSelect, isLoading, searchPlaceholder, emptyLabel, icon: Icon }) {
  const [search, setSearch] = useState('')

  const filteredItems = useMemo(() => {
    if (!items) return []
    if (!search) return items
    const searchLower = search.toLowerCase()
    return items.filter((item) => item.name?.toLowerCase().includes(searchLower))
  }, [items, search])

  if (isLoading) {
    return (
      <Stack align="center" justify="center" h={300}>
        <Loader />
      </Stack>
    )
  }

  return (
    <Stack gap="xs" style={{ height: '100%' }}>
      <TextInput
        placeholder={searchPlaceholder}
        leftSection={<IconSearch size={16} />}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      {filteredItems.length === 0 ? (
        <Card shadow="sm" padding="xl" radius="md" withBorder>
          <Stack align="center" gap="md">
            {Icon && <Icon size={48} opacity={0.3} />}
            <Text c="dimmed" ta="center">
              {emptyLabel}
            </Text>
          </Stack>
        </Card>
      ) : (
        <ScrollArea style={{ flex: 1 }}>
          <Stack gap="sm">
            {filteredItems.map((item) => (
              <Card
                key={item.stream_id || item.series_id}
                padding="sm"
                radius="md"
                withBorder
                style={{ cursor: 'pointer' }}
                onClick={() => onSelect(item)}
              >
                <Group gap="md" wrap="nowrap">
                  {item.stream_icon || item.cover ? (
                    <Image
                      src={item.stream_icon || item.cover}
                      alt={item.name}
                      w={64}
                      h={64}
                      fit="contain"
                      fallbackSrc="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>"
                    />
                  ) : (
                    <Box w={64} h={64} bg="dark.5" style={{ borderRadius: 6 }} />
                  )}
                  <Stack gap={2} style={{ flex: 1, overflow: 'hidden' }}>
                    <Text fw={500} truncate>
                      {item.name}
                    </Text>
                    {item.year && (
                      <Text size="xs" c="dimmed">
                        {item.year}
                      </Text>
                    )}
                  </Stack>
                  <Button variant="light" size="xs">
                    View
                  </Button>
                </Group>
              </Card>
            ))}
          </Stack>
        </ScrollArea>
      )}
    </Stack>
  )
}

export default function Browse() {
  const [selectedAccountId, setSelectedAccountId] = useState(null)
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [selectedChannel, setSelectedChannel] = useState(null)
  const [downloadProgram, setDownloadProgram] = useState(null)
  const [scheduleProgram, setScheduleProgram] = useState(null)
  const [programSearch, setProgramSearch] = useState('')
  const [globalSearch, setGlobalSearch] = useState('')
  const [debouncedGlobalSearch] = useDebouncedValue(globalSearch, 400)
  const searchViewportRef = useRef(null)
  const searchLimit = 100
  const [browseTab, setBrowseTab] = useState('epg')
  const [vodTab, setVodTab] = useState('movies')
  const [selectedMovieCategory, setSelectedMovieCategory] = useState(null)
  const [selectedSeriesCategory, setSelectedSeriesCategory] = useState(null)
  const [selectedMovie, setSelectedMovie] = useState(null)
  const [selectedSeries, setSelectedSeries] = useState(null)

  // Fetch accounts
  const { data: accounts, isLoading: accountsLoading } = useQuery({
    queryKey: ['accounts'],
    queryFn: accountsApi.list,
  })

  // Set default account when loaded
  useMemo(() => {
    if (accounts?.length > 0 && !selectedAccountId) {
      setSelectedAccountId(accounts[0].id.toString())
    }
  }, [accounts, selectedAccountId])

  // Fetch categories
  const { data: categories } = useQuery({
    queryKey: ['categories', selectedAccountId],
    queryFn: () => channelsApi.getCategories(selectedAccountId),
    enabled: !!selectedAccountId,
  })

  // Fetch channels
  const { data: channels, isLoading: channelsLoading } = useQuery({
    queryKey: ['channels', selectedAccountId, selectedCategory],
    queryFn: () => channelsApi.getChannels(selectedAccountId, selectedCategory, true),
    enabled: !!selectedAccountId,
  })

  // Fetch EPG for selected channel
  const { data: epgData, isLoading: epgLoading } = useQuery({
    queryKey: ['epg', selectedAccountId, selectedChannel?.stream_id],
    queryFn: () => channelsApi.getEpg(selectedAccountId, selectedChannel.stream_id, 7),
    enabled: !!selectedAccountId && !!selectedChannel,
  })

  const {
    data: globalEpgPages,
    isLoading: globalEpgLoading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['epg-search', selectedAccountId, debouncedGlobalSearch],
    queryFn: ({ pageParam = 0 }) =>
      epgApi.search(selectedAccountId, debouncedGlobalSearch, searchLimit, pageParam),
    enabled: !!selectedAccountId && debouncedGlobalSearch.length >= 2,
    retry: false,
    getNextPageParam: (lastPage, allPages) => {
      if (!lastPage || lastPage.length < searchLimit) return undefined
      return allPages.reduce((total, page) => total + page.length, 0)
    },
  })

  const globalEpgResults = useMemo(() => {
    if (!globalEpgPages?.pages) return []
    return globalEpgPages.pages.flat()
  }, [globalEpgPages])

  const { data: appSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: settingsApi.get,
  })

  const {
    data: movieCategories = [],
    isLoading: movieCategoriesLoading,
  } = useQuery({
    queryKey: ['vod', 'movies', 'categories', selectedAccountId],
    queryFn: () => vodApi.getMovieCategories(selectedAccountId),
    enabled: !!selectedAccountId,
    retry: false,
  })

  const {
    data: seriesCategories = [],
    isLoading: seriesCategoriesLoading,
  } = useQuery({
    queryKey: ['vod', 'series', 'categories', selectedAccountId],
    queryFn: () => vodApi.getSeriesCategories(selectedAccountId),
    enabled: !!selectedAccountId,
    retry: false,
  })

  const vodAvailable = movieCategories.length > 0 || seriesCategories.length > 0

  const { data: movies = [], isLoading: moviesLoading } = useQuery({
    queryKey: ['vod', 'movies', selectedAccountId, selectedMovieCategory],
    queryFn: () => vodApi.getMovies(selectedAccountId, selectedMovieCategory),
    enabled: !!selectedAccountId && browseTab === 'vod' && vodTab === 'movies' && movieCategories.length > 0,
    retry: false,
  })

  const { data: series = [], isLoading: seriesLoading } = useQuery({
    queryKey: ['vod', 'series', selectedAccountId, selectedSeriesCategory],
    queryFn: () => vodApi.getSeries(selectedAccountId, selectedSeriesCategory),
    enabled: !!selectedAccountId && browseTab === 'vod' && vodTab === 'series' && seriesCategories.length > 0,
    retry: false,
  })

  const filteredEpgData = useMemo(() => {
    if (!epgData) return epgData
    if (!programSearch) return epgData
    const searchLower = programSearch.toLowerCase()
    return epgData.filter((program) => {
      const title = program.title?.toLowerCase() || ''
      const desc = program.description?.toLowerCase() || ''
      return title.includes(searchLower) || desc.includes(searchLower)
    })
  }, [epgData, programSearch])

  useEffect(() => {
    if (!vodAvailable && browseTab === 'vod') {
      setBrowseTab('epg')
    }
  }, [vodAvailable, browseTab])

  useEffect(() => {
    if (vodTab === 'movies' && movieCategories.length === 0 && seriesCategories.length > 0) {
      setVodTab('series')
    }
    if (vodTab === 'series' && seriesCategories.length === 0 && movieCategories.length > 0) {
      setVodTab('movies')
    }
  }, [vodTab, movieCategories.length, seriesCategories.length])

  useEffect(() => {
    setSelectedMovieCategory(null)
    setSelectedSeriesCategory(null)
    setSelectedMovie(null)
    setSelectedSeries(null)
    setGlobalSearch('')
  }, [selectedAccountId])

  useEffect(() => {
    if (searchViewportRef.current) {
      searchViewportRef.current.scrollTo({ top: 0 })
    }
  }, [debouncedGlobalSearch, browseTab])

  const handleProgramClick = (program, meta = {}) => {
    if (meta.action === 'schedule') {
      setScheduleProgram(program)
      return
    }
    setDownloadProgram(program)
  }

  const handleSelectChannel = (channel) => {
    setSelectedChannel(channel)
    setProgramSearch('')
  }

  const handleSelectMovie = (movie) => {
    setSelectedMovie(movie)
  }

  const handleSelectSeries = (seriesItem) => {
    setSelectedSeries(seriesItem)
  }

  const handleGlobalProgramClick = async (program) => {
    if (!selectedAccountId || !program?.channel_id) {
      return
    }

    const endTime = dayjs(program.end_time)
    const isPast = endTime.isBefore(dayjs())
    if (isPast && !program.has_archive) {
      return
    }

    let channel = channels?.find(
      (ch) => ch.stream_id?.toString() === program.channel_id?.toString()
    )

    if (!channel) {
      try {
        channel = await channelsApi.getChannel(selectedAccountId, program.channel_id)
      } catch (err) {
        return
      }
    }

    if (!channel) return

    setSelectedChannel(channel)

    if (isPast && program.has_archive) {
      setDownloadProgram(program)
    } else {
      setScheduleProgram(program)
    }
  }

  const accountOptions = accounts?.map((acc) => ({
    value: acc.id.toString(),
    label: acc.name,
  })) || []

  const categoryOptions = [
    { value: '', label: 'All Categories' },
    ...(categories?.map((cat) => ({
      value: cat.category_id,
      label: cat.category_name,
    })) || []),
  ]

  if (accountsLoading) {
    return (
      <Stack align="center" justify="center" h={300}>
        <Loader />
      </Stack>
    )
  }

  if (!accounts?.length) {
    return (
      <Alert icon={<IconAlertCircle size={16} />} title="No Accounts" color="blue">
        Please add an Xtream Codes account in the Accounts page first.
      </Alert>
    )
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>
          {browseTab === 'vod'
            ? 'Browse On Demand'
            : browseTab === 'search'
            ? 'Search All TV'
            : 'Browse EPG'}
        </Title>
        <Group>
          <Select
            placeholder="Select account"
            data={accountOptions}
            value={selectedAccountId}
            onChange={setSelectedAccountId}
            w={200}
          />
          {browseTab === 'epg' && (
            <Select
              placeholder="All categories"
              data={categoryOptions}
              value={selectedCategory || ''}
              onChange={(val) => setSelectedCategory(val || null)}
              w={200}
              searchable
              clearable
            />
          )}
        </Group>
      </Group>

      <Tabs value={browseTab} onChange={setBrowseTab}>
        <Tabs.List>
          <Tabs.Tab value="epg" leftSection={<IconVideo size={14} />}>
            Browse EPG
          </Tabs.Tab>
          <Tabs.Tab value="search" leftSection={<IconSearch size={14} />}>
            Search All TV
          </Tabs.Tab>
          {vodAvailable && (
            <Tabs.Tab value="vod" leftSection={<IconPlayerPlay size={14} />}>
              On Demand
            </Tabs.Tab>
          )}
        </Tabs.List>

        <Tabs.Panel value="epg" pt="md">
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '300px 1fr',
              gap: 16,
              alignItems: 'stretch',
              height: 'calc(100vh - 260px)',
            }}
          >
            <Card shadow="sm" padding="md" radius="md" withBorder style={{ height: '100%' }}>
              <Stack gap="xs" style={{ height: '100%' }}>
                <Group gap="xs">
                  <IconVideo size={18} />
                  <Text fw={500}>Channels</Text>
                  {channels && (
                    <Badge size="sm" variant="light">
                      {channels.length}
                    </Badge>
                  )}
                </Group>
                <ChannelList
                  channels={channels}
                  selectedChannel={selectedChannel}
                  onSelectChannel={handleSelectChannel}
                  isLoading={channelsLoading}
                />
              </Stack>
            </Card>

            <Card shadow="sm" padding="md" radius="md" withBorder style={{ height: '100%' }}>
              <Stack style={{ height: '100%' }}>
                <Group justify="space-between">
                  <Group gap="xs">
                    {selectedChannel?.stream_icon ? (
                      <Image
                        src={selectedChannel.stream_icon}
                        alt={selectedChannel.name}
                        w={32}
                        h={32}
                        fit="contain"
                      />
                    ) : (
                      <IconVideo size={28} opacity={0.4} />
                    )}
                    <Text fw={500}>
                      {selectedChannel ? selectedChannel.name : 'No channel selected'}
                    </Text>
                  </Group>
                  {selectedChannel && (
                    <Badge variant="light" leftSection={<IconClock size={12} />}>
                      {selectedChannel.tv_archive_duration || 7} days
                    </Badge>
                  )}
                </Group>

                {selectedChannel ? (
                  <Stack style={{ flex: 1, minHeight: 0 }}>
                    <TextInput
                      placeholder="Search shows on this channel..."
                      leftSection={<IconSearch size={16} />}
                      value={programSearch}
                      onChange={(e) => setProgramSearch(e.target.value)}
                      mb="md"
                    />
                    {epgLoading ? (
                      <Stack align="center" justify="center" h={300}>
                        <Loader />
                      </Stack>
                    ) : filteredEpgData ? (
                      <EPGGrid
                        epgData={filteredEpgData}
                        onProgramClick={handleProgramClick}
                        showFuture={appSettings?.show_future_programs}
                      />
                    ) : (
                      <Text c="dimmed" ta="center" py="xl">
                        No EPG data available
                      </Text>
                    )}
                  </Stack>
                ) : (
                  <Stack align="center" justify="center" h={300}>
                    <IconVideo size={48} opacity={0.3} />
                    <Text c="dimmed">Select a channel to view its EPG</Text>
                  </Stack>
                )}
              </Stack>
            </Card>
          </div>
        </Tabs.Panel>

        <Tabs.Panel value="search" pt="md">
          <Card shadow="sm" padding="md" radius="md" withBorder style={{ height: 'calc(100vh - 260px)' }}>
            <Stack style={{ height: '100%', minHeight: 0 }}>
              <TextInput
                placeholder="Search all channels..."
                leftSection={<IconSearch size={16} />}
                value={globalSearch}
                onChange={(e) => setGlobalSearch(e.target.value)}
              />

              {debouncedGlobalSearch.length < 2 ? (
                <Text c="dimmed" ta="center" py="md">
                  Enter at least 2 characters to search.
                </Text>
              ) : globalEpgLoading ? (
                <Stack align="center" justify="center" h={200}>
                  <Loader />
                </Stack>
              ) : globalEpgResults.length === 0 ? (
                <Text c="dimmed" ta="center" py="md">
                  No matching programs found.
                </Text>
              ) : (
                <ScrollArea
                  style={{ flex: 1, minHeight: 0 }}
                  viewportRef={searchViewportRef}
                  onScrollPositionChange={() => {
                    const viewport = searchViewportRef.current
                    if (!viewport || !hasNextPage || isFetchingNextPage) return
                    const threshold = 160
                    if (viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - threshold) {
                      fetchNextPage()
                    }
                  }}
                >
                  <Stack gap="xs">
                    {globalEpgResults.map((program) => {
                      const start = dayjs(program.start_time)
                      const end = dayjs(program.end_time)
                      const isPast = end.isBefore(dayjs())
                      const isDownloadable = isPast && program.has_archive
                      const isClickable = !isPast || isDownloadable
                      const actionLabel = isDownloadable ? 'Download' : isPast ? 'Unavailable' : 'Schedule'
                      return (
                        <Card
                          key={program.epg_id || program.id}
                          padding="sm"
                          radius="sm"
                          withBorder
                          style={{
                            cursor: isClickable ? 'pointer' : 'default',
                            opacity: isClickable ? 1 : 0.6,
                          }}
                          onClick={() => isClickable && handleGlobalProgramClick(program)}
                        >
                          <Stack gap={4}>
                            <Group justify="space-between" wrap="nowrap">
                              <Text fw={500} truncate style={{ flex: 1 }}>
                                {program.title}
                              </Text>
                              <Badge
                                size="xs"
                                variant="light"
                                color={isDownloadable ? 'blue' : isPast ? 'gray' : 'teal'}
                              >
                                {actionLabel}
                              </Badge>
                            </Group>
                            <Text size="xs" c="dimmed">
                              {program.channel_name}
                            </Text>
                            <Group gap="xs">
                              <Badge size="xs" variant="outline">
                                {start.format('MMM D, h:mm A')} - {end.format('h:mm A')}
                              </Badge>
                              <Badge size="xs" variant="light">
                                {program.duration_minutes}m
                              </Badge>
                            </Group>
                          </Stack>
                        </Card>
                      )
                    })}
                    {isFetchingNextPage && (
                      <Group justify="center" py="xs">
                        <Loader size="sm" />
                        <Text size="sm" c="dimmed">
                          Loading more results...
                        </Text>
                      </Group>
                    )}
                    {!hasNextPage && globalEpgResults.length > 0 && (
                      <Text size="sm" c="dimmed" ta="center" py="xs">
                        End of results.
                      </Text>
                    )}
                  </Stack>
                </ScrollArea>
              )}
            </Stack>
          </Card>
        </Tabs.Panel>

        {vodAvailable && (
          <Tabs.Panel value="vod" pt="md">
            <Tabs value={vodTab} onChange={setVodTab}>
              <Tabs.List>
                {movieCategories.length > 0 && (
                  <Tabs.Tab value="movies" leftSection={<IconPlayerPlay size={14} />}>
                    Movies
                  </Tabs.Tab>
                )}
                {seriesCategories.length > 0 && (
                  <Tabs.Tab value="series" leftSection={<IconVideo size={14} />}>
                    Shows
                  </Tabs.Tab>
                )}
              </Tabs.List>

              <Tabs.Panel value="movies" pt="md">
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '300px 1fr',
                    gap: 16,
                    alignItems: 'stretch',
                    height: 'calc(100vh - 300px)',
                  }}
                >
                  <Card shadow="sm" padding="md" radius="md" withBorder style={{ height: '100%' }}>
                    <Stack gap="xs" style={{ height: '100%' }}>
                      <Group gap="xs">
                        <IconPlayerPlay size={18} />
                        <Text fw={500}>Movie Categories</Text>
                        {movieCategories && (
                          <Badge size="sm" variant="light">
                            {movieCategories.length}
                          </Badge>
                        )}
                      </Group>
                      <CategoryList
                        categories={movieCategories}
                        selectedCategory={selectedMovieCategory}
                        onSelectCategory={setSelectedMovieCategory}
                        isLoading={movieCategoriesLoading}
                        label="movie categories"
                      />
                    </Stack>
                  </Card>

                  <Card shadow="sm" padding="md" radius="md" withBorder style={{ height: '100%' }}>
                    <VodGrid
                      items={movies}
                      onSelect={handleSelectMovie}
                      isLoading={moviesLoading}
                      searchPlaceholder="Search movies..."
                      emptyLabel="No movies available in this category."
                      icon={IconPlayerPlay}
                    />
                  </Card>
                </div>
              </Tabs.Panel>

              <Tabs.Panel value="series" pt="md">
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '300px 1fr',
                    gap: 16,
                    alignItems: 'stretch',
                    height: 'calc(100vh - 300px)',
                  }}
                >
                  <Card shadow="sm" padding="md" radius="md" withBorder style={{ height: '100%' }}>
                    <Stack gap="xs" style={{ height: '100%' }}>
                      <Group gap="xs">
                        <IconVideo size={18} />
                        <Text fw={500}>Show Categories</Text>
                        {seriesCategories && (
                          <Badge size="sm" variant="light">
                            {seriesCategories.length}
                          </Badge>
                        )}
                      </Group>
                      <CategoryList
                        categories={seriesCategories}
                        selectedCategory={selectedSeriesCategory}
                        onSelectCategory={setSelectedSeriesCategory}
                        isLoading={seriesCategoriesLoading}
                        label="show categories"
                      />
                    </Stack>
                  </Card>

                  <Card shadow="sm" padding="md" radius="md" withBorder style={{ height: '100%' }}>
                    <VodGrid
                      items={series}
                      onSelect={handleSelectSeries}
                      isLoading={seriesLoading}
                      searchPlaceholder="Search shows..."
                      emptyLabel="No shows available in this category."
                      icon={IconVideo}
                    />
                  </Card>
                </div>
              </Tabs.Panel>
            </Tabs>
          </Tabs.Panel>
        )}
      </Tabs>

      <DownloadModal
        opened={!!downloadProgram}
        onClose={() => setDownloadProgram(null)}
        program={downloadProgram}
        channel={selectedChannel}
        accountId={selectedAccountId}
      />
      <ScheduleModal
        opened={!!scheduleProgram}
        onClose={() => setScheduleProgram(null)}
        program={scheduleProgram}
        channel={selectedChannel}
        accountId={selectedAccountId}
      />
      <MovieModal
        opened={!!selectedMovie}
        onClose={() => setSelectedMovie(null)}
        movie={selectedMovie}
        accountId={selectedAccountId}
      />
      <SeriesModal
        opened={!!selectedSeries}
        onClose={() => setSelectedSeries(null)}
        series={selectedSeries}
        accountId={selectedAccountId}
      />
    </Stack>
  )
}
