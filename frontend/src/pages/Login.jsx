import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import {
  Card,
  Stack,
  PasswordInput,
  Button,
  Text,
  Alert,
  Loader,
  Box,
  Group,
  useMantineColorScheme,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IconAlertCircle } from '@tabler/icons-react'

import { authApi } from '../api'

export default function Login() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const fromPath = location.state?.from || '/settings'
  const { colorScheme } = useMantineColorScheme()
  const isDark = colorScheme === 'dark'

  const { data: status, isLoading } = useQuery({
    queryKey: ['auth', 'status'],
    queryFn: authApi.status,
    refetchOnWindowFocus: true,
  })

  const setupMutation = useMutation({
    mutationFn: (value) => authApi.setup(value),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['auth', 'status'] })
      navigate(fromPath, { replace: true })
    },
    onError: (err) => {
      setError(err.message)
    },
  })

  const loginMutation = useMutation({
    mutationFn: (value) => authApi.login(value),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['auth', 'status'] })
      navigate(fromPath, { replace: true })
    },
    onError: (err) => {
      setError(err.message)
    },
  })

  if (isLoading) {
    return (
      <Stack align="center" justify="center" h={320}>
        <Loader />
      </Stack>
    )
  }

  if (status?.authenticated) {
    return <Navigate to={fromPath} replace />
  }

  const isSetupMode = !status?.password_set
  const isSubmitting = setupMutation.isPending || loginMutation.isPending

  const handleSubmit = (e) => {
    e.preventDefault()
    setError('')

    if (!password || password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }

    if (isSetupMode) {
      setupMutation.mutate(password)
      return
    }

    loginMutation.mutate(password)
  }

  return (
    <Box
      style={{
        minHeight: 'calc(100vh - 4rem)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '2rem',
      }}
    >
      <style>{`
        @keyframes mustarrd-rec-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.15; }
        }
      `}</style>

      <Card
        withBorder
        shadow="md"
        w="100%"
        maw={400}
        radius="lg"
        p={0}
        style={{
          borderTop: '3px solid #f59f00',
          overflow: 'hidden',
        }}
      >
        {/* Branded header */}
        <Box px="lg" pt="lg" pb="md">
          <Group justify="space-between" align="center">
            <Text
              style={{
                fontFamily: "'Bebas Neue', cursive",
                fontSize: 24,
                letterSpacing: '0.12em',
                color: '#f59f00',
                lineHeight: 1,
              }}
            >
              MUSTARRD
            </Text>
            <Group gap={6} align="center">
              <Box
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: '#fa5252',
                  animation: 'mustarrd-rec-pulse 1.5s ease-in-out infinite',
                }}
              />
              <Text
                size="xs"
                fw={700}
                c="red"
                style={{ letterSpacing: '0.12em' }}
              >
                REC
              </Text>
            </Group>
          </Group>
        </Box>

        <Box
          style={{
            height: 1,
            background: isDark ? '#2C2E33' : '#e9ecef',
          }}
        />

        {/* Form */}
        <Stack px="lg" pt="lg" pb="xl" gap="md">
          <Stack gap={4}>
            <Text fw={600} size="xl">
              {isSetupMode ? 'Set Admin Password' : 'Admin Login'}
            </Text>
            <Text size="sm" c="dimmed">
              {isSetupMode
                ? 'Create a password to protect Settings and Accounts.'
                : 'Enter your password to manage Settings and Accounts.'}
            </Text>
          </Stack>

          {error && (
            <Alert color="red" icon={<IconAlertCircle size={16} />} radius="md">
              {error}
            </Alert>
          )}

          <form onSubmit={handleSubmit}>
            <Stack gap="sm">
              <PasswordInput
                label="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                required
                size="md"
              />
              <Button
                type="submit"
                loading={isSubmitting}
                size="md"
                color="yellow"
                fullWidth
                mt={4}
              >
                {isSetupMode ? 'Save Password' : 'Sign In'}
              </Button>
            </Stack>
          </form>
        </Stack>
      </Card>
    </Box>
  )
}
