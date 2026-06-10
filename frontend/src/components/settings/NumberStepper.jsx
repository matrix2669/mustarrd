import { useEffect, useState } from 'react'

import classes from './NumberStepper.module.css'

// Horizontal [−] value [+] stepper used everywhere settings need a number.
export default function NumberStepper({
  value,
  onChange,
  min = 0,
  max = 9999,
  unit,
  disabled = false,
  error = false,
  'aria-label': ariaLabel,
}) {
  const current = typeof value === 'number' ? value : min
  const clamp = (v) => Math.max(min, Math.min(max, v))
  const [text, setText] = useState(String(current))

  useEffect(() => {
    setText(String(typeof value === 'number' ? value : min))
  }, [value, min])

  const step = (delta) => {
    onChange(clamp(current + delta))
  }

  const handleInput = (raw) => {
    setText(raw)
    const n = parseInt(raw, 10)
    if (!Number.isNaN(n)) {
      onChange(clamp(n))
    }
  }

  const handleBlur = () => {
    const n = parseInt(text, 10)
    const next = Number.isNaN(n) ? current : clamp(n)
    onChange(next)
    setText(String(next))
  }

  return (
    <span className={`${classes.wrap}${disabled ? ` ${classes.wrapDisabled}` : ''}`}>
      <span className={`${classes.box}${error ? ` ${classes.boxError}` : ''}`}>
        <button
          type="button"
          className={`${classes.step} ${classes.stepDec}`}
          aria-label={ariaLabel ? `Decrease ${ariaLabel}` : 'Decrease'}
          disabled={disabled || current <= min}
          onClick={() => step(-1)}
        >
          −
        </button>
        <input
          className={classes.value}
          type="text"
          inputMode="numeric"
          aria-label={ariaLabel}
          value={text}
          disabled={disabled}
          onChange={(e) => handleInput(e.target.value)}
          onBlur={handleBlur}
        />
        <button
          type="button"
          className={`${classes.step} ${classes.stepInc}`}
          aria-label={ariaLabel ? `Increase ${ariaLabel}` : 'Increase'}
          disabled={disabled || current >= max}
          onClick={() => step(1)}
        >
          +
        </button>
      </span>
      {unit && <span className={classes.unit}>{unit}</span>}
    </span>
  )
}
