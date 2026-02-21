import React from 'react'
import ReactDOM from 'react-dom/client'
import { MantineProvider, Title, Notification, createTheme } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { unstable_HistoryRouter as HistoryRouter } from 'react-router-dom'
import { createBrowserHistory } from 'history'
import App from './App'

import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'
import './styles.css'

const theme = createTheme({
  primaryColor: 'yellow',
  fontFamily: "'DM Sans', system-ui, -apple-system, sans-serif",
  components: {
    Title: Title.extend({
      styles: (_theme, props) => ({
        root: props.order === 2 ? {
          paddingBottom: 6,
          borderBottom: '2px solid #f59f00',
          display: 'inline-block',
        } : {},
      }),
    }),
    Notification: Notification.extend({
      styles: {
        root: {
          borderTop: '2px solid #f59f00',
        },
      },
    }),
  },
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute
      retry: 1,
    },
  },
})

const history = createBrowserHistory()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme} defaultColorScheme="dark">
        <Notifications position="top-right" />
        <HistoryRouter history={history}>
          <App />
        </HistoryRouter>
      </MantineProvider>
    </QueryClientProvider>
  </React.StrictMode>
)
