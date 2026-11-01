import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Citation } from './types'

function Reference({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState({ left: 0, top: 0 })
  const anchor = useRef<HTMLButtonElement>(null)
  const card = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const id = useId()
  function show() {
    clearTimeout(timer.current)
    const rect = anchor.current?.getBoundingClientRect()
    if (!rect) return
    setPosition({
      left: Math.max(12, Math.min(rect.left, window.innerWidth - 372)),
      top: rect.bottom + 8,
    })
    setOpen(true)
  }
  function hide() {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setOpen(false), 180)
  }
  useEffect(() => {
    if (!open) return
    function close(event: Event) {
      if (
        event.type === 'pointerdown' &&
        (anchor.current?.contains(event.target as Node) ||
          card.current?.contains(event.target as Node))
      )
        return
      if (event.type === 'keydown' && (event as KeyboardEvent).key !== 'Escape') return
      setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    window.addEventListener('resize', close)
    const height = card.current?.getBoundingClientRect().height || 0
    const rect = anchor.current?.getBoundingClientRect()
    if (rect && rect.bottom + 8 + height > window.innerHeight - 12) {
      setPosition((p) => ({ ...p, top: Math.max(12, rect.top - height - 8) }))
    }
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', close)
      window.removeEventListener('resize', close)
    }
  }, [open])
  useEffect(() => () => clearTimeout(timer.current), [])
  return (
    <>
      <button
        ref={anchor}
        className="citation-reference"
        aria-label={`查看引用 ${citation.n}：${citation.question}`}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={show}
      >
        [{citation.n}]
      </button>
      {open &&
        createPortal(
          <div
            ref={card}
            id={id}
            role="tooltip"
            className="citation-preview"
            style={position}
            onMouseEnter={() => clearTimeout(timer.current)}
            onMouseLeave={hide}
          >
            <span className="quiet-label">回答依据 [{citation.n}]</span>
            <h3>{citation.question || citation.section_path}</h3>
            {citation.section_path && <small>{citation.section_path}</small>}
            <p>{citation.answer}</p>
          </div>,
          document.body,
        )}
    </>
  )
}

export default function CitedText({
  text,
  citations = [],
}: {
  text: string
  citations?: Citation[]
}) {
  return (
    <>
      {text.split(/(\[\d+\])/g).map((part, index) => {
        const match = /^\[(\d+)\]$/.exec(part)
        const citation = match ? citations.find((item) => item.n === Number(match[1])) : undefined
        return citation ? <Reference key={index} citation={citation} /> : part
      })}
    </>
  )
}
