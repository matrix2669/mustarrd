import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  PasswordInput,
  Radio,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IconAlertCircle, IconCheck } from '@tabler/icons-react'

import { accountsApi, onboardingApi } from '../api'
import classes from './Onboarding.module.css'

function getMaxUnlockedStep(status) {
  if (!status) return 0
  if ((status.account_count || 0) < 1) return 0
  return 1
}

export default function Onboarding() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isMobile = useMediaQuery('(max-width: 48em)')
  const [currentStep, setCurrentStep] = useState(0)
  const [selectedProfile, setSelectedProfile] = useState('')
  const [comskipChoice, setComskipChoice] = useState('enable')
  const [acknowledgeUnavailable, setAcknowledgeUnavailable] = useState(false)
  const [accountForm, setAccountForm] = useState({
    name: '',
    server_url: '',
    username: '',
    password: '',
  })

  const { data: status, isLoading, error } = useQuery({
    queryKey: ['onboarding', 'status'],
    queryFn: onboardingApi.status,
    refetchOnWindowFocus: true,
  })

  const createAccountMutation = useMutation({
    mutationFn: accountsApi.create,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] })
      await queryClient.invalidateQueries({ queryKey: ['accounts', 'public'] })
      await queryClient.invalidateQueries({ queryKey: ['onboarding', 'status'] })
      setAccountForm((prev) => ({ ...prev, password: '' }))
      setCurrentStep(1)
      notifications.show({
        title: 'Account Added',
        message: 'Xtream account connected successfully.',
        color: 'green',
      })
    },
    onError: (err) => {
      notifications.show({
        title: 'Could not add account',
        message: err.message,
        color: 'red',
      })
    },
  })

  const saveProcessingMutation = useMutation({
    mutationFn: async ({ profile, comskipEnabled, acknowledgeUnavailable }) => {
      await onboardingApi.applyProcessingProfile(profile)
      await onboardingApi.setComskipPolicy(comskipEnabled, acknowledgeUnavailable)
      return onboardingApi.status()
    },
    onSuccess: async (nextStatus) => {
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
      await queryClient.invalidateQueries({ queryKey: ['onboarding', 'status'] })
      if (nextStatus?.completed) {
        navigate('/browse', { replace: true })
        return
      }
      notifications.show({
        title: 'Setup incomplete',
        message: 'Account, processing, and Comskip must be completed to continue.',
        color: 'yellow',
      })
    },
    onError: (err) => {
      notifications.show({
        title: 'Could not save setup',
        message: err.message,
        color: 'red',
      })
    },
  })

  const availableProfiles = useMemo(() => (status?.profiles || []).filter((profile) => profile.available), [status])

  useEffect(() => {
    if (!status) return
    if (status.completed) {
      navigate('/browse', { replace: true })
      return
    }

    if (!selectedProfile) {
      setSelectedProfile(status.selected_profile || status.recommended_profile || '')
    }

    const comskipAvailable = Boolean(status?.tools?.comskip?.available)
    if (status.comskip_confirmed) {
      setComskipChoice(status.comskip_enabled ? 'enable' : 'disable_with_ack')
    } else if (comskipAvailable) {
      setComskipChoice('enable')
    } else {
      setComskipChoice('disable_with_ack')
    }

    const maxUnlocked = getMaxUnlockedStep(status)
    setCurrentStep((prev) => (prev > maxUnlocked ? maxUnlocked : prev))
  }, [navigate, selectedProfile, status])

  if (isLoading) {
    return (
      <Stack align="center" justify="center" h={320}>
        <Loader />
      </Stack>
    )
  }

  if (error) {
    return (
      <Alert color="red" icon={<IconAlertCircle size={16} />}>
        {error.message}
      </Alert>
    )
  }

  const accountComplete = (status?.account_count || 0) > 0
  const comskipAvailable = Boolean(status?.tools?.comskip?.available)
  const isBusy = createAccountMutation.isPending || saveProcessingMutation.isPending

  const canOpenStep = (step) => step <= getMaxUnlockedStep(status)

  const handleCreateAccount = (e) => {
    e.preventDefault()
    createAccountMutation.mutate(accountForm)
  }

  const handleSaveProcessingAndComskip = () => {
    if (!selectedProfile) {
      notifications.show({
        title: 'Select a profile',
        message: 'Choose a processing profile to continue.',
        color: 'yellow',
      })
      return
    }
    if (comskipAvailable) {
      saveProcessingMutation.mutate({
        profile: selectedProfile,
        comskipEnabled: comskipChoice === 'enable',
        acknowledgeUnavailable: false,
      })
      return
    }

    if (!acknowledgeUnavailable) {
      notifications.show({
        title: 'Confirm fallback',
        message: 'Acknowledge that Comskip is unavailable to continue.',
        color: 'yellow',
      })
      return
    }

    saveProcessingMutation.mutate({
      profile: selectedProfile,
      comskipEnabled: false,
      acknowledgeUnavailable: true,
    })
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center" wrap="nowrap">
        <div>
          <Title order={isMobile ? 3 : 2}>First-Time Setup</Title>
        </div>
        <Badge color="yellow" variant="light" size={isMobile ? 'md' : 'lg'}>Required</Badge>
      </Group>

      <Card withBorder p={isMobile ? 'sm' : 'md'}>
        <div className={classes.stepHeader}>
          <button
            type="button"
            className={`${classes.stepButton} ${currentStep === 0 ? classes.stepButtonActive : ''}`}
            onClick={() => {
              if (!isBusy && canOpenStep(0)) setCurrentStep(0)
            }}
          >
            <span className={classes.stepIcon}>{1}</span>
            <span className={classes.stepBody}>
              <span className={classes.stepLabel}>Account</span>
              <span className={classes.stepDescription}>Add provider</span>
            </span>
          </button>

          <div className={`${classes.stepConnector} ${currentStep > 0 ? classes.stepConnectorActive : ''}`} />

          <button
            type="button"
            className={`${classes.stepButton} ${currentStep === 1 ? classes.stepButtonActive : ''}`}
            onClick={() => {
              if (!isBusy && canOpenStep(1)) setCurrentStep(1)
            }}
            disabled={!canOpenStep(1) || isBusy}
          >
            <span className={classes.stepIcon}>{2}</span>
            <span className={classes.stepBody}>
              <span className={classes.stepLabel}>Processing + Comskip</span>
              <span className={classes.stepDescription}>Set defaults</span>
            </span>
          </button>
        </div>

        {currentStep === 0 && (
          <Stack gap="md" mt="md">
            {accountComplete && (
              <Alert color="green" icon={<IconCheck size={16} />}>
                At least one account is connected ({status.account_count}).
              </Alert>
            )}

            <form onSubmit={handleCreateAccount}>
              <Stack>
                <TextInput
                  label="Account Name"
                  placeholder="My IPTV Provider"
                  size={isMobile ? 'md' : 'sm'}
                  required
                  value={accountForm.name}
                  onChange={(e) => setAccountForm((prev) => ({ ...prev, name: e.target.value }))}
                />
                <TextInput
                  label="Server URL"
                  placeholder="https://provider.example.com"
                  size={isMobile ? 'md' : 'sm'}
                  required
                  value={accountForm.server_url}
                  onChange={(e) => setAccountForm((prev) => ({ ...prev, server_url: e.target.value }))}
                />
                <TextInput
                  label="Username"
                  size={isMobile ? 'md' : 'sm'}
                  required
                  value={accountForm.username}
                  onChange={(e) => setAccountForm((prev) => ({ ...prev, username: e.target.value }))}
                />
                <PasswordInput
                  label="Password"
                  size={isMobile ? 'md' : 'sm'}
                  required
                  value={accountForm.password}
                  onChange={(e) => setAccountForm((prev) => ({ ...prev, password: e.target.value }))}
                />
                <Box
                  mt="sm"
                  style={{
                    position: isMobile ? 'sticky' : 'static',
                    bottom: isMobile ? 0 : 'auto',
                    background: 'var(--mantine-color-body)',
                    paddingTop: isMobile ? 8 : 0,
                    zIndex: 5,
                  }}
                >
                  <Group justify="space-between" grow={isMobile}>
                    <Button type="submit" loading={createAccountMutation.isPending} fullWidth={isMobile}>
                      {accountComplete ? 'Add Another Account' : 'Save & Continue'}
                    </Button>
                    <Button
                      variant="light"
                      onClick={() => setCurrentStep(1)}
                      disabled={!accountComplete || isBusy}
                      fullWidth={isMobile}
                    >
                      Continue
                    </Button>
                  </Group>
                </Box>
              </Stack>
            </form>
          </Stack>
        )}

        {currentStep === 1 && (
          <Stack gap="md" mt="md">
            <Radio.Group value={selectedProfile} onChange={setSelectedProfile}>
              <Stack gap="xs">
                {availableProfiles.map((profile) => (
                  <Card key={profile.id} withBorder padding="sm">
                    <Radio value={profile.id} label={profile.label} description={profile.description} />
                    {profile.recommended && (
                      <Badge mt={8} size="xs" color="orange" variant="outline">
                        Recommended
                      </Badge>
                    )}
                  </Card>
                ))}
              </Stack>
            </Radio.Group>

            {comskipAvailable ? (
              <Radio.Group value={comskipChoice} onChange={setComskipChoice}>
                <Stack gap="xs">
                  <Radio value="enable" label="Enable Comskip" description="Detect and remove commercials." />
                  <Radio value="disable_with_ack" label="Disable Comskip" description="Keep commercials in recordings." />
                </Stack>
              </Radio.Group>
            ) : (
              <>
                <Alert color="yellow" icon={<IconAlertCircle size={16} />}>
                  Comskip is unavailable: {status?.tools?.comskip?.error || 'Tool not detected'}
                </Alert>
                <Checkbox
                  checked={acknowledgeUnavailable}
                  onChange={(e) => setAcknowledgeUnavailable(e.currentTarget.checked)}
                  label="I understand setup will continue with Comskip disabled."
                />
              </>
            )}

            <Group justify="space-between">
              <Box
                style={{
                  width: '100%',
                  position: isMobile ? 'sticky' : 'static',
                  bottom: isMobile ? 0 : 'auto',
                  background: 'var(--mantine-color-body)',
                  paddingTop: isMobile ? 8 : 0,
                  zIndex: 5,
                }}
              >
                <Group justify="space-between" grow={isMobile}>
                  <Button variant="subtle" onClick={() => setCurrentStep(0)} disabled={isBusy} fullWidth={isMobile}>
                    Back
                  </Button>
                  <Button onClick={handleSaveProcessingAndComskip} loading={saveProcessingMutation.isPending} fullWidth={isMobile}>
                    Save & Finish
                  </Button>
                </Group>
              </Box>
            </Group>
          </Stack>
        )}
      </Card>
    </Stack>
  )
}
