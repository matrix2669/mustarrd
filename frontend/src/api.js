const API_BASE = '/api'

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`
  const config = {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  }

  if (config.body && typeof config.body === 'object') {
    config.body = JSON.stringify(config.body)
  }

  const response = await fetch(url, config)

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    const err = new Error(error.detail || 'Request failed')
    err.status = response.status
    throw err
  }

  return response.json()
}

// Accounts
export const accountsApi = {
  list: () => request('/accounts'),
  publicList: () => request('/accounts/public'),
  get: (id) => request(`/accounts/${id}`),
  create: (data) => request('/accounts', { method: 'POST', body: data }),
  update: (id, data) => request(`/accounts/${id}`, { method: 'PUT', body: data }),
  delete: (id) => request(`/accounts/${id}`, { method: 'DELETE' }),
  test: (id) => request(`/accounts/${id}/test`, { method: 'POST' }),
}

// Channels & EPG
export const channelsApi = {
  getCategories: (accountId) => request(`/accounts/${accountId}/categories`),
  getChannels: (accountId, categoryId = null, catchupOnly = true) => {
    const params = new URLSearchParams()
    if (categoryId) params.append('category_id', categoryId)
    params.append('catchup_only', catchupOnly)
    return request(`/accounts/${accountId}/channels?${params}`)
  },
  getChannel: (accountId, channelId) => request(`/accounts/${accountId}/channels/${channelId}`),
  getEpg: (accountId, channelId, daysBack = 7, fresh = false) =>
    request(
      `/accounts/${accountId}/channels/${channelId}/epg?days_back=${daysBack}&fresh=${fresh ? 'true' : 'false'}`
    ),
  getCatchup: (accountId, channelId, daysBack = 7) =>
    request(`/accounts/${accountId}/channels/${channelId}/catchup?days_back=${daysBack}`),
}

// EPG Search
export const epgApi = {
  search: (accountId, query, limit = 100, offset = 0) =>
    request(
      `/epg/search?account_id=${accountId}&q=${encodeURIComponent(query)}&limit=${limit}&offset=${offset}`
    ),
  status: () => request('/epg/status'),
  refresh: (force = false) => request('/epg/refresh', { method: 'POST', body: { force } }),
}

// Downloads
export const downloadsApi = {
  list: () => request('/downloads'),
  getQueue: () => request('/downloads/queue'),
  getHistory: () => request('/downloads/history'),
  get: (id) => request(`/downloads/${id}`),
  create: (data) => request('/downloads', { method: 'POST', body: data }),
  cancel: (id) => request(`/downloads/${id}`, { method: 'DELETE' }),
  retry: (id) => request(`/downloads/${id}/retry`, { method: 'POST' }),
  previewFilename: (data) => request('/downloads/preview-filename', { method: 'POST', body: data }),
}

// Schedules
export const schedulesApi = {
  list: () => request('/schedules'),
  create: (data) => request('/schedules', { method: 'POST', body: data }),
  cancel: (id) => request(`/schedules/${id}`, { method: 'DELETE' }),
}

// VOD (On Demand)
export const vodApi = {
  getMovieCategories: (accountId) => request(`/vod/movies/categories?account_id=${accountId}`),
  getMovies: (accountId, categoryId = null) => {
    const params = new URLSearchParams()
    params.append('account_id', accountId)
    if (categoryId) params.append('category_id', categoryId)
    return request(`/vod/movies?${params}`)
  },
  getMovieInfo: (accountId, vodId) =>
    request(`/vod/movies/${vodId}?account_id=${accountId}`),
  downloadMovie: (data) => request('/vod/movies/download', { method: 'POST', body: data }),
  getSeriesCategories: (accountId) => request(`/vod/series/categories?account_id=${accountId}`),
  getSeries: (accountId, categoryId = null) => {
    const params = new URLSearchParams()
    params.append('account_id', accountId)
    if (categoryId) params.append('category_id', categoryId)
    return request(`/vod/series?${params}`)
  },
  getSeriesInfo: (accountId, seriesId) =>
    request(`/vod/series/${seriesId}?account_id=${accountId}`),
  downloadSeries: (data) => request('/vod/series/download', { method: 'POST', body: data }),
}

// Settings
export const settingsApi = {
  get: () => request('/settings'),
  getPublic: () => request('/settings/public'),
  update: (data) => request('/settings', { method: 'PUT', body: data }),
  getTemplates: () => request('/settings/templates'),
  getTools: () => request('/settings/tools'),
}

// Authentication
export const authApi = {
  status: () => request('/auth/status'),
  setup: (password) => request('/auth/setup', { method: 'POST', body: { password } }),
  login: (password) => request('/auth/login', { method: 'POST', body: { password } }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  changePassword: (currentPassword, newPassword) =>
    request('/auth/change-password', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    }),
}

export const onboardingApi = {
  status: () => request('/onboarding/status'),
  applyProcessingProfile: (profile) =>
    request('/onboarding/processing-profile', {
      method: 'POST',
      body: { profile },
    }),
  setComskipPolicy: (enabled, acknowledgeUnavailable = false) =>
    request('/onboarding/comskip-policy', {
      method: 'POST',
      body: { enabled, acknowledge_unavailable: acknowledgeUnavailable },
    }),
  dismiss: () => request('/onboarding/dismiss', { method: 'POST' }),
}

// Backend Logs
export const logsApi = {
  list: (limit = 300, source = null, level = null, view = 'basic') => {
    const params = new URLSearchParams()
    params.append('limit', String(limit))
    if (source) params.append('source', source)
    if (level) params.append('level', level)
    params.append('view', view)
    return request(`/logs?${params.toString()}`)
  },
}

// WebSocket for download progress
export function createDownloadWebSocket(onMessage, onError = null) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/api/downloads/ws`

  const ws = new WebSocket(wsUrl)

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    onMessage(data)
  }

  ws.onerror = (error) => {
    if (onError) onError(error)
  }

  return ws
}

export function createLogsWebSocket(onMessage, onError = null) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/api/logs/ws`
  const ws = new WebSocket(wsUrl)

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    onMessage(data)
  }

  ws.onerror = (error) => {
    if (onError) onError(error)
  }

  return ws
}
