import { formatChannelDateTime } from '../src/utils/channelTime.js'

const sampleProgram = {
  title: 'Sample Show',
  start_timestamp: 1774890000,
  stop_timestamp: 1774894500,
  start_time: '2026-03-30T17:00:00+00:00',
  end_time: '2026-03-30T18:15:00+00:00',
}

const sampleDownload = {
  program_title: 'Sample Download',
  start_timestamp: 1774890000,
  stop_timestamp: 1774894500,
  program_start: '2026-03-30T19:00:00+00:00',
  program_end: '2026-03-30T20:15:00+00:00',
}

const guideOffsetHours = 2

console.log(`TZ=${process.env.TZ || 'system-default'}`)
console.log(`start=${formatChannelDateTime(sampleProgram, 'start', guideOffsetHours, 'YYYY-MM-DD HH:mm')}`)
console.log(`end=${formatChannelDateTime(sampleProgram, 'end', guideOffsetHours, 'YYYY-MM-DD HH:mm')}`)
console.log(`download_start=${formatChannelDateTime(sampleDownload, 'start', guideOffsetHours, 'YYYY-MM-DD HH:mm')}`)
console.log(`download_end=${formatChannelDateTime(sampleDownload, 'end', guideOffsetHours, 'YYYY-MM-DD HH:mm')}`)
