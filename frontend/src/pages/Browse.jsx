import { useState, useMemo } from 'react'
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
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { IconSearch, IconAlertCircle, IconVideo, IconClock } from '@tabler/icons-react'

import { accountsApi, channelsApi, settingsApi } from '../api'
import EPGGrid from '../components/EPGGrid'
import DownloadModal from '../components/DownloadModal'

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

export default function Browse() {
  const [selectedAccountId, setSelectedAccountId] = useState(null)
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [selectedChannel, setSelectedChannel] = useState(null)
  const [downloadProgram, setDownloadProgram] = useState(null)
  const [programSearch, setProgramSearch] = useState('')

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

  const { data: appSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: settingsApi.get,
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

  const handleProgramClick = (program) => {
    setDownloadProgram(program)
  }

  const handleSelectChannel = (channel) => {
    setSelectedChannel(channel)
    setProgramSearch('')
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
        <Title order={2}>Browse Channels</Title>
        <Group>
          <Select
            placeholder="Select account"
            data={accountOptions}
            value={selectedAccountId}
            onChange={setSelectedAccountId}
            w={200}
          />
          <Select
            placeholder="All categories"
            data={categoryOptions}
            value={selectedCategory || ''}
            onChange={(val) => setSelectedCategory(val || null)}
            w={200}
            searchable
            clearable
          />
        </Group>
      </Group>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '300px 1fr',
          gap: 16,
          alignItems: 'stretch',
          height: 'calc(100vh - 220px)',
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
          {selectedChannel ? (
            <Stack style={{ height: '100%' }}>
              <Group justify="space-between">
                <Group gap="xs">
                  {selectedChannel.stream_icon && (
                    <Image
                      src={selectedChannel.stream_icon}
                      alt={selectedChannel.name}
                      w={32}
                      h={32}
                      fit="contain"
                    />
                  )}
                  <Text fw={500}>{selectedChannel.name}</Text>
                </Group>
                <Badge variant="light" leftSection={<IconClock size={12} />}>
                  {selectedChannel.tv_archive_duration || 7} days
                </Badge>
              </Group>

              <Tabs defaultValue="timeline" style={{ flex: 1, minHeight: 0 }}>
                <Tabs.List>
                  <Tabs.Tab value="timeline">EPG Timeline</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="timeline" pt="md" style={{ height: '100%' }}>
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
                </Tabs.Panel>
              </Tabs>
            </Stack>
          ) : (
            <Stack align="center" justify="center" h={400}>
              <IconVideo size={48} opacity={0.3} />
              <Text c="dimmed">Select a channel to view its EPG</Text>
            </Stack>
          )}
        </Card>
      </div>

      <DownloadModal
        opened={!!downloadProgram}
        onClose={() => setDownloadProgram(null)}
        program={downloadProgram}
        channel={selectedChannel}
        accountId={selectedAccountId}
      />
    </Stack>
  )
}
