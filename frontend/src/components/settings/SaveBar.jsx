import { Button } from '@mantine/core'

import classes from './SaveBar.module.css'

// Sticky save bar that floats over the content while there are unsaved changes.
export default function SaveBar({ count, saving = false, disabled = false, onSave, onDiscard }) {
  if (count === 0 && !saving) return null
  return (
    <div className={classes.bar} role="status">
      <div className={classes.inner}>
        <span className={classes.msg}>
          <span className={classes.count}>{count}</span> unsaved change{count === 1 ? '' : 's'}
        </span>
        <Button variant="subtle" color="gray" size="xs" onClick={onDiscard} disabled={saving}>
          Discard
        </Button>
        <Button size="xs" onClick={onSave} loading={saving} disabled={disabled}>
          Save Changes
        </Button>
      </div>
    </div>
  )
}
