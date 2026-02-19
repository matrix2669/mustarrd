import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Card, Stack, PasswordInput, Button, Text, Title, Alert, Loader } from '@mantine/core'
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
    <Stack align="center" justify="center" h="calc(100vh - 4rem)">
      <Card withBorder shadow="sm" w="100%" maw={420} p="lg" radius="md">
        <Stack>
          <Title order={3}>{isSetupMode ? 'Set Admin Password' : 'Admin Login'}</Title>
          <Text size="sm" c="dimmed">
            {isSetupMode
              ? 'Create an admin password to lock Settings and Accounts.'
              : 'Enter the admin password to manage Settings and Accounts.'}
          </Text>

          {error ? (
            <Alert color="red" icon={<IconAlertCircle size={16} />}>
              {error}
            </Alert>
          ) : null}

          <form onSubmit={handleSubmit}>
            <Stack>
              <PasswordInput
                label="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                required
              />
              <Button type="submit" loading={isSubmitting}>
                {isSetupMode ? 'Save Password' : 'Sign In'}
              </Button>
            </Stack>
          </form>
        </Stack>
      </Card>
    </Stack>
  )
}
