import { useState } from 'react'
import {
  Title,
  Button,
  Card,
  Group,
  Text,
  Stack,
  Modal,
  TextInput,
  NumberInput,
  Badge,
  ActionIcon,
  Menu,
  Loader,
  Alert,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  IconPlus,
  IconDotsVertical,
  IconEdit,
  IconTrash,
  IconPlugConnected,
  IconAlertCircle,
  IconServer,
  IconRefresh,
} from '@tabler/icons-react'
import dayjs from 'dayjs'

import { accountsApi, epgApi } from '../api'

function AccountForm({ account, onSubmit, onCancel, isLoading }) {
  const [formData, setFormData] = useState({
    name: account?.name || '',
    server_url: account?.server_url || '',
    username: account?.username || '',
    password: account?.password || '',
    catchup_days: account?.catchup_days || 7,
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    onSubmit(formData)
  }

  return (
    <form onSubmit={handleSubmit}>
      <Stack>
        <TextInput
          label="Account Name"
          placeholder="My IPTV Provider"
          required
          value={formData.name}
          onChange={(e) => setFormData({ ...formData, name: e.target.value })}
        />
        <TextInput
          label="Server URL"
          placeholder="https://provider.example.com"
          required
          value={formData.server_url}
          onChange={(e) => setFormData({ ...formData, server_url: e.target.value })}
        />
        <TextInput
          label="Username"
          required
          value={formData.username}
          onChange={(e) => setFormData({ ...formData, username: e.target.value })}
        />
        <TextInput
          label="Password"
          type="password"
          required
          value={formData.password}
          onChange={(e) => setFormData({ ...formData, password: e.target.value })}
        />
        <NumberInput
          label="Catchup Days Available"
          description="How many days of past content is available"
          min={1}
          max={30}
          value={formData.catchup_days}
          onChange={(val) => setFormData({ ...formData, catchup_days: val })}
        />
        <Group justify="flex-end" mt="md">
          <Button variant="subtle" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" loading={isLoading}>
            {account ? 'Update' : 'Add Account'}
          </Button>
        </Group>
      </Stack>
    </form>
  )
}

function AccountCard({ account, onEdit, onDelete, onTest }) {
  const isExpired = account.expiration_date && dayjs(account.expiration_date).isBefore(dayjs())

  return (
    <Card shadow="sm" padding="lg" radius="md" withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={500}>{account.name}</Text>
        <Group gap="xs">
          <Badge color={account.is_active ? 'green' : 'gray'} variant="light">
            {account.is_active ? 'Active' : 'Inactive'}
          </Badge>
          <Menu shadow="md" width={150}>
            <Menu.Target>
              <ActionIcon variant="subtle">
                <IconDotsVertical size={16} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item leftSection={<IconPlugConnected size={14} />} onClick={() => onTest(account)}>
                Test Connection
              </Menu.Item>
              <Menu.Item leftSection={<IconEdit size={14} />} onClick={() => onEdit(account)}>
                Edit
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={() => onDelete(account)}>
                Delete
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </Group>

      <Text size="sm" c="dimmed" mb="xs">
        {account.server_url}
      </Text>
      <Text size="sm" c="dimmed">
        User: {account.username}
      </Text>

      <Group mt="md" gap="xs">
        {account.max_connections && (
          <Badge variant="outline" size="sm">
            {account.active_connections || 0}/{account.max_connections} connections
          </Badge>
        )}
        {account.expiration_date && (
          <Badge variant="outline" size="sm" color={isExpired ? 'red' : 'yellow'}>
            {isExpired ? 'Expired' : `Expires ${dayjs(account.expiration_date).format('MMM D, YYYY')}`}
          </Badge>
        )}
        <Badge variant="outline" size="sm">
          {account.catchup_days} days catchup
        </Badge>
      </Group>
    </Card>
  )
}

export default function Accounts() {
  const queryClient = useQueryClient()
  const [modalOpened, { open: openModal, close: closeModal }] = useDisclosure(false)
  const [editingAccount, setEditingAccount] = useState(null)

  const { data: accounts, isLoading, error } = useQuery({
    queryKey: ['accounts'],
    queryFn: accountsApi.list,
  })
  const { data: epgStatus } = useQuery({
    queryKey: ['epg', 'status'],
    queryFn: epgApi.status,
    refetchInterval: 5000,
  })

  const createMutation = useMutation({
    mutationFn: accountsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      closeModal()
      setEditingAccount(null)
      notifications.show({
        title: 'Success',
        message: 'Account added successfully',
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

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => accountsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      closeModal()
      setEditingAccount(null)
      notifications.show({
        title: 'Success',
        message: 'Account updated successfully',
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

  const deleteMutation = useMutation({
    mutationFn: accountsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      notifications.show({
        title: 'Success',
        message: 'Account deleted',
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

  const testMutation = useMutation({
    mutationFn: accountsApi.test,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      notifications.show({
        title: 'Connection Successful',
        message: 'Server connection verified',
        color: 'green',
      })
    },
    onError: (error) => {
      notifications.show({
        title: 'Connection Failed',
        message: error.message,
        color: 'red',
      })
    },
  })

  const forceRefreshMutation = useMutation({
    mutationFn: () => epgApi.refresh(true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['epg', 'status'] })
      notifications.show({
        title: 'Force EPG Refresh Started',
        message: 'Guide data is being rebuilt for all active accounts.',
        color: 'yellow',
      })
    },
    onError: (error) => {
      notifications.show({
        title: 'Refresh Failed',
        message: error.message,
        color: 'red',
      })
    },
  })

  const handleAddClick = () => {
    setEditingAccount(null)
    openModal()
  }

  const handleEdit = (account) => {
    setEditingAccount(account)
    openModal()
  }

  const handleDelete = (account) => {
    if (confirm(`Delete account "${account.name}"?`)) {
      deleteMutation.mutate(account.id)
    }
  }

  const handleTest = (account) => {
    testMutation.mutate(account.id)
  }

  const handleForceRefresh = () => {
    if (epgStatus?.running) {
      notifications.show({
        title: 'Refresh Already Running',
        message: 'Wait for the current EPG refresh to finish.',
        color: 'yellow',
      })
      return
    }

    if (!confirm('Force refresh will clear stored EPG rows and rebuild guide data. Continue?')) {
      return
    }

    forceRefreshMutation.mutate()
  }

  const handleSubmit = (data) => {
    if (editingAccount) {
      updateMutation.mutate({ id: editingAccount.id, data })
    } else {
      createMutation.mutate(data)
    }
  }

  if (isLoading) {
    return (
      <Stack align="center" justify="center" h={200}>
        <Loader />
      </Stack>
    )
  }

  if (error) {
    return (
      <Alert icon={<IconAlertCircle size={16} />} title="Error" color="red">
        Failed to load accounts: {error.message}
      </Alert>
    )
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Accounts</Title>
        <Group>
          <Button
            variant="light"
            color="orange"
            leftSection={<IconRefresh size={16} />}
            onClick={handleForceRefresh}
            loading={forceRefreshMutation.isPending}
            disabled={Boolean(epgStatus?.running)}
          >
            Force EPG Refresh
          </Button>
          <Button leftSection={<IconPlus size={16} />} onClick={handleAddClick}>
            Add Account
          </Button>
        </Group>
      </Group>

      {accounts?.length === 0 ? (
        <Card shadow="sm" padding="xl" radius="md" withBorder>
          <Stack align="center" gap="md">
            <IconServer size={48} opacity={0.5} />
            <Text c="dimmed" ta="center">
              No accounts configured. Add an Xtream Codes account to get started.
            </Text>
            <Button onClick={handleAddClick}>Add Your First Account</Button>
          </Stack>
        </Card>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))', gap: 16 }}>
          {accounts?.map((account) => (
            <AccountCard
              key={account.id}
              account={account}
              onEdit={handleEdit}
              onDelete={handleDelete}
              onTest={handleTest}
            />
          ))}
        </div>
      )}

      <Modal
        opened={modalOpened}
        onClose={closeModal}
        title={editingAccount ? 'Edit Account' : 'Add Account'}
        size="md"
      >
        <AccountForm
          account={editingAccount}
          onSubmit={handleSubmit}
          onCancel={closeModal}
          isLoading={createMutation.isPending || updateMutation.isPending}
        />
      </Modal>
    </Stack>
  )
}
