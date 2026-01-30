import { Box } from '@mantine/core'
import './ProgressBar.css'

export default function ProgressBar({ progress = 0, color = 'blue', height = 6, indeterminate = false }) {
  const clampedProgress = Math.min(100, Math.max(0, progress))

  return (
    <Box
      className="progress-bar-track"
      style={{
        width: '100%',
        height,
        backgroundColor: 'var(--mantine-color-dark-5)',
        borderRadius: height / 2,
        overflow: 'hidden',
        '--progress-color': `var(--mantine-color-${color}-6)`,
      }}
    >
      <Box
        className={indeterminate ? 'progress-bar-fill progress-bar-indeterminate' : 'progress-bar-fill'}
        style={{
          width: indeterminate ? '100%' : `${clampedProgress}%`,
          height: '100%',
          backgroundColor: `var(--mantine-color-${color}-6)`,
          borderRadius: height / 2,
          transition: indeterminate ? 'none' : 'width 0.3s ease',
        }}
      />
    </Box>
  )
}
