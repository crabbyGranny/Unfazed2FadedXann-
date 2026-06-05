import React from 'react'

export default function FileImport({onFiles}){
  const fileRef = React.useRef(null)
  const [dragActive, setDragActive] = React.useState(false)

  function handleFiles(files){
    if (!files || files.length === 0) return
    onFiles(Array.from(files))
  }

  function onInputChange(e){
    handleFiles(e.target.files)
  }

  function onDragOver(e){ e.preventDefault(); e.stopPropagation(); setDragActive(true) }
  function onDragLeave(e){ e.preventDefault(); e.stopPropagation(); setDragActive(false) }
  function onDrop(e){ e.preventDefault(); e.stopPropagation(); setDragActive(false); handleFiles(e.dataTransfer.files) }

  function onButtonClick(){ fileRef.current?.click() }

  return (
    <div className={`file-import ${dragActive ? 'drag-active' : ''}`}
      onDragOver={onDragOver} onDragEnter={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
    >
      <input ref={fileRef} className="visually-hidden" type="file" accept="audio/*,.zip,.wav,.mp3,.ogg" onChange={onInputChange} multiple />
      <div className="file-import-inner">
        <button className="import-btn" onClick={onButtonClick} aria-label="Import audio or project">
          Import audio or project
        </button>
        <div className="import-hint">Tap to open files on mobile. Drag & drop files here on desktop.</div>
      </div>
    </div>
  )
}
