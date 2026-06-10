import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderWithMantine } from '../../test/renderWithProviders'
import NumberStepper from './NumberStepper'

function renderStepper(props = {}) {
  const onChange = vi.fn()
  renderWithMantine(
    <NumberStepper value={5} min={1} max={10} aria-label="Count" onChange={onChange} {...props} />
  )
  return { onChange }
}

describe('NumberStepper', () => {
  it('renders the value and unit', () => {
    renderStepper({ unit: 'GB' })
    expect(screen.getByRole('textbox', { name: 'Count' })).toHaveValue('5')
    expect(screen.getByText('GB')).toBeInTheDocument()
  })

  it('increments and decrements within bounds', () => {
    const { onChange } = renderStepper()
    fireEvent.click(screen.getByRole('button', { name: 'Increase Count' }))
    expect(onChange).toHaveBeenCalledWith(6)
    fireEvent.click(screen.getByRole('button', { name: 'Decrease Count' }))
    expect(onChange).toHaveBeenCalledWith(4)
  })

  it('disables the decrement button at min and increment at max', () => {
    renderStepper({ value: 1 })
    expect(screen.getByRole('button', { name: 'Decrease Count' })).toBeDisabled()
    renderStepper({ value: 10 })
    expect(screen.getAllByRole('button', { name: 'Increase Count' })[1]).toBeDisabled()
  })

  it('clamps typed values to the range', () => {
    const { onChange } = renderStepper()
    const input = screen.getByRole('textbox', { name: 'Count' })
    fireEvent.change(input, { target: { value: '99' } })
    expect(onChange).toHaveBeenCalledWith(10)
  })

  it('restores the last value when input is left empty', () => {
    const { onChange } = renderStepper()
    const input = screen.getByRole('textbox', { name: 'Count' })
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)
    expect(onChange).toHaveBeenLastCalledWith(5)
    expect(input).toHaveValue('5')
  })
})
