import React from 'react'
import { createRoot } from 'react-dom/client'
import MobileKnob from './components/MobileKnob'
import FileImport from './components/FileImport'
import './app.css'

function isTouchDevice(){
  // safe guard: only access window/navigator when available
  if (typeof window === 'undefined') return false
  return ('ontouchstart' in window) || (navigator?.maxTouchPoints > 0)
}

function App(){
  const [val, setVal] = React.useState(0.5)
  const [files, setFiles] = React.useState([])
  const [touch, setTouch] = React.useState(false)

  React.useEffect(()=>{
    async function setupAudioWorklet(){
      if (typeof window === 'undefined' || !window.AudioContext) return
      try {
        const ac = new AudioContext()
        if (ac.audioWorklet) {
          // AudioWorklet registration skeleton (placeholder)
          console.log('AudioWorklet available', ac)
        } else {
          console.log('AudioWorklet not available in this browser')
        }
      } catch (err) {
        console.error('Failed to setup AudioContext/Worklet:', err)
      }
    }

    setupAudioWorklet()
    // determine touch support after mount (safe)
    setTouch(isTouchDevice())
  },[])

  async function handleFiles(selectedFiles){
    // selectedFiles may be a FileList or Array — normalize to Array
    const arr = Array.isArray(selectedFiles) ? selectedFiles : Array.from(selectedFiles || [])
    setFiles(arr)
    // placeholder: in next iterations we will run BPM detection, stem separation, and import mapping
    console.log('Imported files:', arr.map(f => ({name: f.name, size: f.size, type: f.type})))
  }

  return (
    <div className="app-root mobile-first">
      <header className="topbar">Unfazed Studio — Mobile MVP</header>
      <main className="main">
        <section className="controls">
          <MobileKnob value={val} onChange={setVal} />
          <div className="val">Value: {(val*100).toFixed(0)}%</div>
        </section>

        <section className="import-section">
          <FileImport onFiles={handleFiles} />
          {!touch && <div className="desktop-note">Desktop detected — you can drag & drop files or click to open.</div>}
        </section>

        <section className="notes">
          <p>AudioWorklet skeleton is registered in console. Use this branch as a starting point. The UI is mobile-first but accepts drag & drop / open file actions on desktop.</p>
          <div className="file-list">
            {files.length === 0 ? <em>No files imported yet.</em> : (
              <ul>
                {files.map((f, i) => (
                  <li key={i}>{f.name} — {(f.size/1024).toFixed(1)} KB</li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}

const root = createRoot(document.getElementById('root'))
root.render(<App />)
