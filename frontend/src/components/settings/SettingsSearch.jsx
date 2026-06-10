import { useMemo, useState } from 'react'
import { TextInput } from '@mantine/core'
import { useClickOutside } from '@mantine/hooks'
import { IconSearch } from '@tabler/icons-react'

import { SEARCH_INDEX, SECTION_LABELS } from './sections'
import classes from './SettingsSearch.module.css'

export default function SettingsSearch({ onNavigate, isMobile = false }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const wrapRef = useClickOutside(() => setOpen(false))

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return []
    return SEARCH_INDEX.filter((entry) =>
      `${entry.label} ${entry.kw} ${SECTION_LABELS[entry.section]?.label || ''}`
        .toLowerCase()
        .includes(needle)
    ).slice(0, 8)
  }, [query])

  return (
    <div className={classes.wrap} ref={wrapRef}>
      <TextInput
        placeholder="Search settings…"
        aria-label="Search settings"
        leftSection={<IconSearch size={14} />}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onFocus={() => query && setOpen(true)}
        styles={{
          input: isMobile
            ? { height: 42, fontSize: 16 }
            : { height: 34, minHeight: 34, fontSize: 13 },
        }}
      />
      {open && query.trim() && (
        <div className={classes.results}>
          {results.length === 0 && (
            <div className={classes.empty}>No settings match &quot;{query}&quot;</div>
          )}
          {results.map((entry) => {
            const section = SECTION_LABELS[entry.section]
            return (
              <button
                key={`${entry.section}-${entry.label}`}
                type="button"
                className={classes.result}
                onClick={() => {
                  onNavigate(entry.section)
                  setOpen(false)
                  setQuery('')
                }}
              >
                <span className={classes.resultLabel}>{entry.label}</span>
                <span className={classes.resultPath}>
                  {section?.group} › <b>{section?.label}</b>
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
