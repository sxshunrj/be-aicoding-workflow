import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog, Modal, Skeleton } from '../ui'

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

describe('Modal 焦点', () => {
  it('初始焦点落在 autoFocus 输入框而非关闭按钮', () => {
    render(
      <Modal title="t" onClose={() => {}}>
        <input data-testid="q" autoFocus placeholder="需求" />
      </Modal>,
    )
    expect(document.activeElement).toBe(screen.getByTestId('q'))
  })

  it('无 autoFocus 时焦点落在第一个输入框', () => {
    render(
      <Modal title="t" onClose={() => {}}>
        <p>说明</p>
        <input data-testid="path" placeholder="路径" />
      </Modal>,
    )
    expect(document.activeElement).toBe(screen.getByTestId('path'))
  })
})
