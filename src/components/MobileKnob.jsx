import React, { useRef } from 'react'
import './knob.css'

export default function MobileKnob({ value = 0.5, onChange = ()=>{}, fineStep = 0.001 }){
  const startRef = useRef(null)

  function clamp(v, a=0, b=1){ return Math.max(a, Math.min(b, v)) }

  function onTouchStart(e){
    const t = e.touches[0]
    startRef.current = { y: t.clientY, v0: value }
    navigator.vibrate?.(5)
  }
  function onTouchMove(e){
    if (!startRef.current) return
    const t = e.touches[0]
    const dy = startRef.current.y - t.clientY
    const delta = dy / 150
    const newVal = clamp(startRef.current.v0 + delta, 0, 1)
    onChange(newVal)
  }
  function onTouchEnd(){ startRef.current = null }

  const rotation = 270 * (value - 0.5)

  return (
    <div
      className="mobile-knob"
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      role="slider"
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={value}
      tabIndex={0}
    >
      <svg width="64" height="64" viewBox="0 0 64 64">
        <g transform={`rotate(${rotation} 32 32)`}>
          <circle cx="32" cy="32" r="28" stroke="#333" strokeWidth="3" fill="#111" />
          <rect x="31" y="8" width="2" height="12" fill="#fff" rx="1" />
        </g>
      </svg>
    </div>
  )
}
