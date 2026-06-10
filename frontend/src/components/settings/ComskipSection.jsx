import {
  Alert,
  Anchor,
  Button,
  Checkbox,
  Group,
  Stack,
  Text,
  TextInput,
} from '@mantine/core'
import { IconInfoCircle } from '@tabler/icons-react'

import NumberStepper from './NumberStepper'
import { LabelWithTooltip, SectionHeader, SettingRow, StepperField, SubGroup } from './SettingsPrimitives'
import classes from './ComskipSection.module.css'

export const COMSKIP_DEFAULTS = {
  comskip_detect_method: 107,
  comskip_max_commercialbreak: 600,
  comskip_min_commercialbreak: 25,
  comskip_max_commercial_size: 125,
  comskip_min_commercial_size: 4,
  comskip_always_keep_first_seconds: 0,
  comskip_always_keep_last_seconds: 60,
  comskip_remove_before: 0,
  comskip_remove_after: 0,
  comskip_thread_count: 1,
}

const DETECT_METHOD_OPTIONS = [
  { bit: 1, label: 'Black frames' },
  { bit: 2, label: 'Logo detection' },
  { bit: 4, label: 'Scene change' },
  { bit: 8, label: 'Resolution change' },
  { bit: 32, label: 'Aspect ratio change' },
  { bit: 64, label: 'Silence detection' },
]
const KNOWN_DETECT_BITS = DETECT_METHOD_OPTIONS.reduce((sum, option) => sum + option.bit, 0)

export function getComskipErrors(formData) {
  if (!formData) return {}
  const errors = {}
  const value = (field) => formData[field] ?? COMSKIP_DEFAULTS[field]
  if (value('comskip_min_commercialbreak') > value('comskip_max_commercialbreak')) {
    errors.commercialbreak = 'Min commercial break must be less than or equal to max commercial break.'
  }
  if (value('comskip_min_commercial_size') > value('comskip_max_commercial_size')) {
    errors.commercial_size = 'Min single commercial must be less than or equal to max single commercial.'
  }
  return errors
}

function RecordingTimeline() {
  return (
    <div>
      <div className={classes.timeline} aria-hidden="true">
        <div className={classes.segKeep} style={{ width: '4%' }} />
        <div className={classes.segShow} />
        <div className={classes.segAd} style={{ width: '12%' }} />
        <div className={classes.segShow} />
        <div className={classes.segAd} style={{ width: '9%' }} />
        <div className={classes.segShow} />
        <div className={classes.segKeep} style={{ width: '7%' }} />
      </div>
      <div className={classes.legend}>
        <span className={classes.legendKey}>
          <span className={classes.swatch} style={{ background: 'rgba(64,192,87,0.45)' }} />
          Kept show content
        </span>
        <span className={classes.legendKey}>
          <span className={classes.swatch} style={{ background: 'rgba(250,82,82,0.5)' }} />
          Detected commercials (cut)
        </span>
        <span className={classes.legendKey}>
          <span className={classes.swatch} style={{ background: 'rgba(245,159,0,0.55)' }} />
          Protected (never cut)
        </span>
      </div>
    </div>
  )
}

export default function ComskipSection({ formData, onChange, onResetDefaults, onNavigateToProcessing }) {
  const enabled = Boolean(formData?.comskip_enabled)
  const errors = getComskipErrors(formData)

  const detectMethod = formData?.comskip_detect_method ?? COMSKIP_DEFAULTS.comskip_detect_method
  const checkedBits = DETECT_METHOD_OPTIONS
    .filter((option) => (detectMethod & option.bit) === option.bit)
    .map((option) => String(option.bit))

  const handleDetectChange = (values) => {
    const known = values.reduce((sum, v) => sum + Number(v), 0)
    // Preserve bits without a checkbox (e.g. closed captions = 16) so an
    // externally-set bitmask is not silently truncated by a save.
    const unknown = detectMethod & ~KNOWN_DETECT_BITS
    onChange('comskip_detect_method', known + unknown)
  }

  const stepperField = (field, label, tooltip, props = {}) => (
    <StepperField
      label={label}
      tooltip={tooltip}
      disabled={!enabled}
      value={formData?.[field] ?? COMSKIP_DEFAULTS[field]}
      onChange={(val) => onChange(field, typeof val === 'number' ? val : COMSKIP_DEFAULTS[field])}
      {...props}
    />
  )

  const dimClass = enabled ? undefined : classes.dimmed

  return (
    <Stack gap="xl">
      <SectionHeader title="Commercial Skip" description="Tune how Comskip detects and removes ad breaks" />

      {!enabled && (
        <Alert color="blue" variant="light" icon={<IconInfoCircle size={16} />}>
          <Text size="sm">
            Comskip is not enabled. Turn it on in{' '}
            <Anchor onClick={onNavigateToProcessing}>Post-Processing</Anchor>{' '}
            to configure these settings.
          </Text>
        </Alert>
      )}

      <Stack gap="xl" className={dimClass}>
        <SubGroup label="What a recording looks like">
          <RecordingTimeline />
        </SubGroup>

        <SubGroup label="Detection signals">
          <Text size="xs" c="dimmed" maw="60ch">
            Which signals Comskip looks for when finding commercial boundaries. The defaults work for most
            providers — adding more signals rarely helps and slows processing.
          </Text>
          <Checkbox.Group value={checkedBits} onChange={handleDetectChange}>
            <div className={classes.checkGrid}>
              {DETECT_METHOD_OPTIONS.map((option) => (
                <Checkbox
                  key={option.bit}
                  value={String(option.bit)}
                  label={option.label}
                  disabled={!enabled}
                />
              ))}
            </div>
          </Checkbox.Group>
        </SubGroup>

        <SubGroup label="Break timing">
          <div className={classes.grid2}>
            {stepperField(
              'comskip_min_commercialbreak',
              'Min commercial break',
              'Shortest stretch Comskip will call a commercial break. Lower values may cause false positives on short scene transitions. Recommended: 25.',
              { unit: 'sec', max: 3600, error: errors.commercialbreak },
            )}
            {stepperField(
              'comskip_max_commercialbreak',
              'Max commercial break',
              'Longest stretch of continuous commercials Comskip will mark as a single break. Increase if your provider runs long ad blocks. Recommended: 600.',
              { unit: 'sec', max: 3600 },
            )}
            {stepperField(
              'comskip_min_commercial_size',
              'Min single commercial',
              'Shortest a single commercial can be. Raise this to avoid false cuts on brief logo bumpers. Recommended: 4.',
              { unit: 'sec', max: 600, error: errors.commercial_size },
            )}
            {stepperField(
              'comskip_max_commercial_size',
              'Max single commercial',
              'Longest a single commercial can be. Spots longer than this are treated as show content. Recommended: 125.',
              { unit: 'sec', max: 600 },
            )}
          </div>
        </SubGroup>

        <SubGroup label="Show protection">
          <div className={classes.grid2}>
            {stepperField(
              'comskip_always_keep_first_seconds',
              'Always keep first',
              'Never mark this many seconds at the start of the recording as commercial, regardless of what Comskip detects. Useful for providers that play a logo intro before the show.',
              { unit: 'sec', max: 3600 },
            )}
            {stepperField(
              'comskip_always_keep_last_seconds',
              'Always keep last',
              'Never mark this many seconds at the end of the recording as commercial. Prevents accidental cutting of end credits or a post-credits scene.',
              { unit: 'sec', max: 3600 },
            )}
            {stepperField(
              'comskip_remove_before',
              'Trim before each break',
              'Extra seconds of show content to cut immediately before each detected commercial block. Use with caution: removes show content.',
              { unit: 'sec', max: 120 },
            )}
            {stepperField(
              'comskip_remove_after',
              'Trim after each break',
              'Extra seconds of show content to cut immediately after each detected commercial block.',
              { unit: 'sec', max: 120 },
            )}
          </div>
        </SubGroup>

        <SubGroup label="Advanced">
          <Stack gap={0}>
            <SettingRow
              label="Processing threads"
              description="More threads finish faster but load the CPU during recording"
              tooltip="Number of CPU threads Comskip uses. More threads = faster processing but more CPU load during recording. Maximum: 16."
            >
              <NumberStepper
                aria-label="Processing threads"
                min={1}
                max={16}
                disabled={!enabled}
                value={formData?.comskip_thread_count ?? COMSKIP_DEFAULTS.comskip_thread_count}
                onChange={(val) => onChange('comskip_thread_count', typeof val === 'number' ? val : COMSKIP_DEFAULTS.comskip_thread_count)}
              />
            </SettingRow>
          </Stack>
          <TextInput
            label={
              <LabelWithTooltip
                label="Custom Comskip INI path"
                tooltip="If set, this file overrides the generated settings above. Leave blank to use the settings on this page."
              />
            }
            description="Optional — overrides all settings above"
            placeholder="/path/to/comskip.ini"
            disabled={!enabled}
            value={formData?.comskip_custom_ini_path || ''}
            onChange={(e) => onChange('comskip_custom_ini_path', e.target.value || null)}
            styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)', fontSize: 12.5 } }}
          />
          <Group>
            <Button variant="default" size="xs" disabled={!enabled} onClick={onResetDefaults}>
              Reset to Defaults
            </Button>
          </Group>
        </SubGroup>
      </Stack>
    </Stack>
  )
}
