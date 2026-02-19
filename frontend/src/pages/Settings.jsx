import { useState, useEffect, useCallback, useContext } from 'react'
import { UNSAFE_NavigationContext } from 'react-router-dom'
import {
  Title,
  Card,
  Group,
  Text,
  Stack,
  TextInput,
  NumberInput,
  Button,
  Accordion,
  Code,
  Loader,
  Alert,
  Switch,
  Select,
  Badge,
  useMantineColorScheme,
  useMantineTheme,
  Modal,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  IconFolder,
  IconFile,
  IconAlertCircle,
  IconInfoCircle,
  IconWand,
  IconCheck,
  IconX,
  IconMoon,
  IconCalendar,
} from '@tabler/icons-react'

import { settingsApi } from '../api'

function TemplateSection({ label, template, variables, example, onChange }) {
  return (
    <Stack gap="xs">
      <TextInput
        label={label}
        value={template}
        onChange={(e) => onChange(e.target.value)}
        placeholder={example}
      />
      <Group gap="xs" wrap="wrap">
        {variables.map((v) => (
          <Code key={v.name} style={{ cursor: 'help' }} title={v.description}>
            {`{${v.name}}`}
          </Code>
        ))}
      </Group>
      <Text size="xs" c="dimmed">
        Example: <Code>{example}</Code>
      </Text>
    </Stack>
  )
}

function useBlocker(blocker, when = true) {
  const { navigator } = useContext(UNSAFE_NavigationContext)

  useEffect(() => {
    if (!when) return
    if (!navigator?.block) return undefined

    const unblock = navigator.block((tx) => {
      const autoUnblockingTx = {
        ...tx,
        retry() {
          unblock()
          tx.retry()
        },
      }
      blocker(autoUnblockingTx)
    })

    return unblock
  }, [navigator, blocker, when])
}

export default function Settings() {
  const queryClient = useQueryClient()
  const [formData, setFormData] = useState(null)
  const [hasChanges, setHasChanges] = useState(false)
  const [leaveModalOpen, setLeaveModalOpen] = useState(false)
  const [pendingNavigation, setPendingNavigation] = useState(null)
  const [isSavingAndLeaving, setIsSavingAndLeaving] = useState(false)
  const [desktopStartupSupported, setDesktopStartupSupported] = useState(false)
  const [desktopStartupLoading, setDesktopStartupLoading] = useState(false)
  const { colorScheme, setColorScheme } = useMantineColorScheme()
  const theme = useMantineTheme()
  const blockNavigation = useCallback((tx) => {
    if (!hasChanges) {
      tx.retry()
      return
    }
    setPendingNavigation(tx)
    setLeaveModalOpen(true)
  }, [hasChanges])
  useBlocker(blockNavigation, hasChanges)

  const accordionStyles = {
    item: {
      borderRadius: theme.radius.md,
      border: `1px solid ${colorScheme === 'dark' ? theme.colors.dark[6] : theme.colors.gray[5]}`,
      backgroundColor: colorScheme === 'dark' ? theme.colors.dark[7] : theme.colors.gray[1],
    },
    control: {
      borderRadius: theme.radius.md,
    },
    panel: {
      borderTop: `1px solid ${colorScheme === 'dark' ? theme.colors.dark[6] : theme.colors.gray[3]}`,
    },
  }

  // Fetch settings
  const { data: settings, isLoading, error } = useQuery({
    queryKey: ['settings'],
    queryFn: settingsApi.get,
  })

  // Fetch template variables
  const { data: templateInfo } = useQuery({
    queryKey: ['settings', 'templates'],
    queryFn: settingsApi.getTemplates,
  })

  // Fetch tools status
  const { data: toolsStatus } = useQuery({
    queryKey: ['settings', 'tools'],
    queryFn: settingsApi.getTools,
  })

  // Initialize form when settings load
  useEffect(() => {
    if (settings && !formData) {
      setFormData({ ...settings })
    }
  }, [settings, formData])

  const applyDesktopStartupSetting = useCallback(async (enabled) => {
    const desktopApi = window.mustarrdDesktop
    if (!desktopApi?.setLaunchOnStartup) {
      return
    }

    try {
      const result = await desktopApi.setLaunchOnStartup(enabled)
      if (result?.supported) {
        setDesktopStartupSupported(true)
        if (typeof result.enabled === 'boolean') {
          setFormData((prev) => {
            if (!prev) return prev
            if (prev.launch_on_startup === result.enabled) return prev
            return { ...prev, launch_on_startup: result.enabled }
          })
        }
      }
    } catch (error) {
      notifications.show({
        title: 'Startup Setting',
        message: error.message || 'Unable to update startup behavior on this device.',
        color: 'red',
      })
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    const loadDesktopStartup = async () => {
      const desktopApi = window.mustarrdDesktop
      if (!desktopApi?.getLaunchOnStartup) {
        return
      }

      setDesktopStartupLoading(true)
      try {
        const result = await desktopApi.getLaunchOnStartup()
        if (cancelled) {
          return
        }
        setDesktopStartupSupported(Boolean(result?.supported))
        if (result?.supported && typeof result.enabled === 'boolean') {
          setFormData((prev) => {
            if (!prev) return prev
            if (prev.launch_on_startup === result.enabled) return prev
            return { ...prev, launch_on_startup: result.enabled }
          })
        }
      } finally {
        if (!cancelled) {
          setDesktopStartupLoading(false)
        }
      }
    }

    if (settings) {
      loadDesktopStartup()
    }

    return () => {
      cancelled = true
    }
  }, [settings])

  const updateMutation = useMutation({
    mutationFn: settingsApi.update,
    onSuccess: (_data, variables) => {
      if (typeof variables?.launch_on_startup === 'boolean') {
        void applyDesktopStartupSetting(variables.launch_on_startup)
      }
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      setHasChanges(false)
      notifications.show({
        title: 'Settings Saved',
        message: 'Your settings have been updated',
        color: 'green',
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

  const handleChange = (field, value) => {
    setFormData((prev) => {
      const next = { ...prev, [field]: value }
      if (field === 'comskip_enabled' && value) {
        next.transcode_enabled = true
      }
      return next
    })
    setHasChanges(true)
  }

  const handleSave = () => {
    updateMutation.mutate(formData)
  }

  const handleReset = () => {
    setFormData({ ...settings })
    setHasChanges(false)
  }

  useEffect(() => {
    if (!hasChanges) {
      setLeaveModalOpen(false)
      setPendingNavigation(null)
    }
  }, [hasChanges])

  useEffect(() => {
    const handleBeforeUnload = (event) => {
      if (!hasChanges) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [hasChanges])

  const handleStay = () => {
    setLeaveModalOpen(false)
    setPendingNavigation(null)
  }

  const handleDiscardAndContinue = () => {
    const tx = pendingNavigation
    setLeaveModalOpen(false)
    setPendingNavigation(null)
    setHasChanges(false)
    tx?.retry?.()
  }

  const handleSaveAndContinue = async () => {
    const tx = pendingNavigation
    if (!tx) {
      return
    }
    setIsSavingAndLeaving(true)
    try {
      await updateMutation.mutateAsync(formData)
      setLeaveModalOpen(false)
      setPendingNavigation(null)
      tx.retry()
    } catch (error) {
      setIsSavingAndLeaving(false)
    }
    setIsSavingAndLeaving(false)
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
      <Alert icon={<IconAlertCircle size={16} />} title="Error" color="red">
        Failed to load settings: {error.message}
      </Alert>
    )
  }

  if (!formData) {
    return null
  }

  return (
    <Stack>
      <Modal
        opened={leaveModalOpen}
        onClose={handleStay}
        title="Unsaved changes"
        centered
        size="md"
        radius="md"
        padding="lg"
        overlayProps={{ opacity: 0.55, blur: 2 }}
      >
        <Stack gap="md">
          <Alert icon={<IconAlertCircle size={16} />} color="yellow" variant="light" radius="md">
            <Text size="sm">
              You have unsaved settings changes. Save before leaving this page?
            </Text>
          </Alert>
          <Stack gap="xs">
            <Button
              onClick={handleSaveAndContinue}
              loading={isSavingAndLeaving || updateMutation.isPending}
              fullWidth
            >
              Save & Continue
            </Button>
            <Button variant="default" onClick={handleDiscardAndContinue} fullWidth>
              Discard & Continue
            </Button>
            <Button variant="subtle" color="gray" onClick={handleStay} fullWidth>
              Keep Editing
            </Button>
          </Stack>
        </Stack>
      </Modal>
      <Group justify="space-between">
        <Title order={2}>Settings</Title>
        <Group>
          {hasChanges && (
            <Button variant="subtle" onClick={handleReset}>
              Discard Changes
            </Button>
          )}
          <Button
            onClick={handleSave}
            loading={updateMutation.isPending}
            disabled={!hasChanges}
          >
            Save Settings
          </Button>
        </Group>
      </Group>

      <Card shadow="sm" padding="lg" radius="md" withBorder>
        <Stack gap="md">
          <Group gap="xs">
            <IconFolder size={20} />
            <Text fw={500}>Download Settings</Text>
          </Group>

          <TextInput
            label="Download Folder"
            description="Where downloaded files will be saved"
            value={formData.download_folder}
            onChange={(e) => handleChange('download_folder', e.target.value)}
            leftSection={<IconFolder size={16} />}
          />
          <TextInput
            label="Completed Folder"
            description="Where finished files will be moved"
            value={formData.completed_folder}
            onChange={(e) => handleChange('completed_folder', e.target.value)}
            leftSection={<IconFolder size={16} />}
          />

          <NumberInput
            label="Max Concurrent Downloads"
            description="How many downloads can run at the same time"
            min={1}
            max={5}
            value={formData.max_concurrent_downloads}
            onChange={(val) => handleChange('max_concurrent_downloads', val)}
          />

          <NumberInput
            label="Default Minutes Before Start"
            description="Start recordings early by default"
            min={0}
            max={120}
            value={formData.default_pre_padding_minutes}
            onChange={(val) => handleChange('default_pre_padding_minutes', val)}
          />

          <NumberInput
            label="Default Minutes After End"
            description="Keep recordings running after the program ends by default"
            min={0}
            max={120}
            value={formData.default_post_padding_minutes}
            onChange={(val) => handleChange('default_post_padding_minutes', val)}
          />

          <NumberInput
            label="EPG Time Offset (hours)"
            description="Adjust guide times if your provider's schedule is offset"
            min={-12}
            max={12}
            step={1}
            value={(formData.epg_offset_minutes || 0) / 60}
            onChange={(val) => {
              const hours = typeof val === 'number' ? val : 0
              handleChange('epg_offset_minutes', hours * 60)
            }}
          />

          <Switch
            label="Show future programs (schedule-only)"
            description="Show upcoming programs that cannot be downloaded yet. Clicking them schedules recordings, so leave the app running."
            checked={formData.show_future_programs || false}
            onChange={(e) => handleChange('show_future_programs', e.currentTarget.checked)}
          />

          {(desktopStartupSupported || desktopStartupLoading) && (
            <Switch
              label="Run app at system startup"
              description="Automatically launch Mustarrd when you sign in."
              checked={formData.launch_on_startup !== false}
              disabled={desktopStartupLoading}
              onChange={(e) => handleChange('launch_on_startup', e.currentTarget.checked)}
            />
          )}
        </Stack>
      </Card>

      <Card shadow="sm" padding="lg" radius="md" withBorder>
        <Stack gap="md">
          <Group gap="xs">
            <IconCalendar size={20} />
            <Text fw={500}>Scheduled Recordings</Text>
          </Group>

          <NumberInput
            label="Minimum Free Space (GB)"
            description="Pause scheduled recordings if free space drops below this amount"
            min={1}
            max={10000}
            value={formData.min_free_space_gb}
            onChange={(val) => handleChange('min_free_space_gb', val)}
          />
        </Stack>
      </Card>

      <Card shadow="sm" padding="lg" radius="md" withBorder>
        <Stack gap="md">
          <Group gap="xs">
            <IconWand size={20} />
            <Text fw={500}>Post-Processing</Text>
          </Group>

          <Alert icon={<IconInfoCircle size={16} />} variant="light">
            <Text size="sm">
              Automatically process downloads after completion. Requires working ffmpeg and/or Comskip binaries.
            </Text>
          </Alert>

          <NumberInput
            label="Max Concurrent Post-Processing"
            description="How many files can be converted at the same time (Recommended: 1). Higher values use much more CPU/GPU and disk I/O."
            min={1}
            max={10}
            value={formData.max_concurrent_post_processing ?? 1}
            onChange={(val) => handleChange('max_concurrent_post_processing', val)}
          />

          {(formData.max_concurrent_post_processing ?? 1) > 1 && (
            <Alert icon={<IconAlertCircle size={16} />} color="yellow" variant="light">
              <Text size="sm">
                Running multiple conversions at once can saturate your CPU/GPU and disk. Some GPUs also have limited
                concurrent encoding sessions.
              </Text>
            </Alert>
          )}

          {toolsStatus && (
            <Stack gap={6}>
              <Group gap="md">
                <Badge
                  color={toolsStatus.ffmpeg?.available ? 'green' : 'red'}
                  variant="light"
                  leftSection={toolsStatus.ffmpeg?.available ? <IconCheck size={12} /> : <IconX size={12} />}
                >
                  ffmpeg {toolsStatus.ffmpeg?.available ? 'ready' : 'unavailable'}
                </Badge>
                <Badge
                  color={toolsStatus.comskip?.available ? 'green' : 'red'}
                  variant="light"
                  leftSection={toolsStatus.comskip?.available ? <IconCheck size={12} /> : <IconX size={12} />}
                >
                  Comskip {toolsStatus.comskip?.available ? 'ready' : 'unavailable'}
                </Badge>
              </Group>
              {toolsStatus.ffmpeg?.path && (
                <Text size="xs" c="dimmed">ffmpeg: {toolsStatus.ffmpeg.path}</Text>
              )}
              {toolsStatus.ffmpeg?.error && (
                <Text size="xs" c="red">ffmpeg error: {toolsStatus.ffmpeg.error}</Text>
              )}
              {toolsStatus.comskip?.path && (
                <Text size="xs" c="dimmed">comskip: {toolsStatus.comskip.path}</Text>
              )}
              {toolsStatus.comskip?.error && (
                <Text size="xs" c="red">comskip error: {toolsStatus.comskip.error}</Text>
              )}
            </Stack>
          )}

          <Accordion variant="separated" styles={accordionStyles}>
            <Accordion.Item value="transcode">
              <Accordion.Control>
                <Group gap="xs">
                  <Text>Post-Processing (Advanced)</Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="md">
                  <Text size="xs" c="dimmed">
                    By default, downloads are remuxed to MKV using stream copy. Use these options if you want
                    to change the format or force a re-encode.
                  </Text>

                  <Select
                    label="Output Format"
                    data={[
                      { value: 'mp4', label: 'MP4 (H.264 + AAC)' },
                      { value: 'mkv', label: 'MKV (best compatibility)' },
                      { value: 'ts', label: 'TS (keep original)' },
                    ]}
                    value={formData.transcode_format || 'mkv'}
                    onChange={(val) => handleChange('transcode_format', val)}
                  />

                  <Switch
                    label="Remux only (no re-encode)"
                    description="Faster and lossless; may show minor glitches at cut points."
                    checked={formData.remux_only !== false}
                    onChange={(e) => handleChange('remux_only', e.currentTarget.checked)}
                  />

                  <Switch
                    label="Delete original after processing"
                    checked={formData.delete_original_after_transcode !== false}
                    onChange={(e) => handleChange('delete_original_after_transcode', e.currentTarget.checked)}
                  />

                  {!formData.remux_only && (
                    <Select
                      label="Output Hardware"
                      description="Use GPU for faster encoding"
                      data={toolsStatus?.hardware_accels?.map(hw => ({
                        value: hw.id,
                        label: hw.name,
                        disabled: !hw.available,
                      })) || [{ value: 'cpu', label: 'CPU (Software)' }]}
                      value={formData.hw_accel || 'cpu'}
                      onChange={(val) => handleChange('hw_accel', val)}
                    />
                  )}

                  {!toolsStatus?.ffmpeg?.available && (
                    <Alert color="yellow" variant="light">
                      <Text size="sm">
                        ffmpeg is unavailable. The Docker image includes ffmpeg; install or fix it manually if running locally.
                      </Text>
                    </Alert>
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>

            <Accordion.Item value="comskip">
              <Accordion.Control>
                <Group gap="xs">
                  <Text>Commercial Detection (Comskip) (Beta)</Text>
                  {formData.comskip_enabled && (
                    <Badge size="xs" color="blue">Enabled</Badge>
                  )}
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="md">
                  <Switch
                    label="Enable Comskip"
                    description="Detect and remove commercials from recordings"
                    checked={formData.comskip_enabled || false}
                    onChange={(e) => handleChange('comskip_enabled', e.currentTarget.checked)}
                    disabled={!toolsStatus?.comskip?.available}
                  />

                  {formData.comskip_enabled && (
                    <>
                      <Text size="xs" c="dimmed">
                        Commercials will be cut out and the result will be remuxed using your advanced settings.
                      </Text>

                      <TextInput
                        label="Comskip Path (optional)"
                        description="Custom path to comskip binary"
                        placeholder="/usr/local/bin/comskip"
                        value={formData.comskip_path || ''}
                        onChange={(e) => handleChange('comskip_path', e.target.value || null)}
                      />

                      <TextInput
                        label="Comskip INI Path (optional)"
                        description="Custom comskip.ini configuration file (leave blank to use the app default)"
                        placeholder="/path/to/comskip.ini"
                        value={formData.comskip_ini_path || ''}
                        onChange={(e) => handleChange('comskip_ini_path', e.target.value || null)}
                      />
                    </>
                  )}

                  {!toolsStatus?.comskip?.available && (
                    <Alert color="yellow" variant="light">
                      <Text size="sm">
                        Comskip is unavailable. See{' '}
                        <a href="https://github.com/erikkaashoek/Comskip" target="_blank" rel="noopener noreferrer">
                          github.com/erikkaashoek/Comskip
                        </a>{' '}
                        for installation instructions.
                      </Text>
                    </Alert>
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        </Stack>
      </Card>

      <Card shadow="sm" padding="lg" radius="md" withBorder>
        <Stack gap="md">
          <Group gap="xs">
            <IconFile size={20} />
            <Text fw={500}>Filename Templates</Text>
          </Group>

          <Alert icon={<IconInfoCircle size={16} />} variant="light">
            <Text size="sm">
              Customize how downloaded files are named. Use the variables shown below each field.
              Files will automatically get the .ts extension.
            </Text>
          </Alert>

          <Accordion variant="separated" styles={accordionStyles}>
            <Accordion.Item value="tv">
              <Accordion.Control>TV Shows</Accordion.Control>
              <Accordion.Panel>
                {templateInfo?.tv_show && (
                  <TemplateSection
                    label="TV Show Template"
                    template={formData.tv_template}
                    variables={templateInfo.tv_show.variables}
                    example={templateInfo.tv_show.example}
                    onChange={(val) => handleChange('tv_template', val)}
                  />
                )}
              </Accordion.Panel>
            </Accordion.Item>

            <Accordion.Item value="movie">
              <Accordion.Control>Movies</Accordion.Control>
              <Accordion.Panel>
                {templateInfo?.movie && (
                  <TemplateSection
                    label="Movie Template"
                    template={formData.movie_template}
                    variables={templateInfo.movie.variables}
                    example={templateInfo.movie.example}
                    onChange={(val) => handleChange('movie_template', val)}
                  />
                )}
              </Accordion.Panel>
            </Accordion.Item>

            <Accordion.Item value="sports">
              <Accordion.Control>Sports</Accordion.Control>
              <Accordion.Panel>
                {templateInfo?.sports && (
                  <TemplateSection
                    label="Sports Template"
                    template={formData.sports_template}
                    variables={templateInfo.sports.variables}
                    example={templateInfo.sports.example}
                    onChange={(val) => handleChange('sports_template', val)}
                  />
                )}
              </Accordion.Panel>
            </Accordion.Item>

            <Accordion.Item value="default">
              <Accordion.Control>Default (Other Content)</Accordion.Control>
              <Accordion.Panel>
                {templateInfo?.default && (
                  <TemplateSection
                    label="Default Template"
                    template={formData.default_template}
                    variables={templateInfo.default.variables}
                    example={templateInfo.default.example}
                    onChange={(val) => handleChange('default_template', val)}
                  />
                )}
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        </Stack>
      </Card>

      <Card shadow="sm" padding="lg" radius="md" withBorder>
        <Stack gap="md">
          <Group gap="xs">
            <IconMoon size={20} />
            <Text fw={500}>Appearance</Text>
          </Group>

          <Switch
            label="Enable Dark Mode"
            checked={colorScheme === 'dark'}
            onChange={(e) => setColorScheme(e.currentTarget.checked ? 'dark' : 'light')}
          />
        </Stack>
      </Card>
    </Stack>
  )
}
