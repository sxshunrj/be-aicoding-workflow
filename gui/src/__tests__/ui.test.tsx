import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog, Skeleton } from '../ui'

describe('ConfirmDialog', () => {
  it('确认与取消回调都触发', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ConfirmDialog
        title="中止 Run"
        message="确认中止？"
        confirmText="中止"
        danger
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    expect(screen.getByRole('dialog')).toBeTruthy()
    fireEvent.click(screen.getByText('中止'))
    expect(onConfirm).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByText('取消'))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('ESC 触发取消', () => {
    const onCancel = vi.fn()
    render(
      <ConfirmDialog title="t" message="m" onConfirm={() => {}} onCancel={onCancel} />,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onCancel).toHaveBeenCalledOnce()
  })
})

describe('Skeleton', () => {
  it('按行数渲染占位', () => {
    const { container } = render(<Skeleton lines={3} />)
    expect(container.querySelectorAll('.skeleton').length).toBe(3)
  })
})
