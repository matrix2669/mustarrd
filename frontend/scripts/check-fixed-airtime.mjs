import { formatChannelDateTime } from '../src/utils/channelTime.js'

const sampleProgram = {
  title: 'Sample Show',
  start_timestamp: 1774890000,
  stop_timestamp: 1774894500,
  start_time: '2026-03-30T17:00:00+00:00',
  end_time: '2026-03-30T18:15:00+00:00',
}

const guideOffsetHours = 2

console.log(`TZ=${process.env.TZ || 'system-default'}`)
console.log(`start=${formatChannelDateTime(sampleProgram, 'start', guideOffsetHours, 'YYYY-MM-DD HH:mm')}`)
console.log(`end=${formatChannelDateTime(sampleProgram, 'end', guideOffsetHours, 'YYYY-MM-DD HH:mm')}`)
