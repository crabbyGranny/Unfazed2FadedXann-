import React from 'react'
import { createRoot } from 'react-dom/client'
import MobileKnob from './components/MobileKnob'
import FileImport from './components/FileImport'
import './app.css'

function isTouchDevice(){
  return (('ontouchstart' in window) || (navigator.maxTouchPoints && navigator.maxTouchPoints > 0))
}

function App(){
  const [val, setVal] = React.useState(0.5)
  const [files, setFiles] = React.useState([])
  const touch = isTouchDevice()

  React.useEffect(()=>{
    async function setupAudioWorklet(){
      if (!window.AudioContext) return
      const ac = new AudioContext()
      try{
        await ac.audioWorklet.addModule('/src/audio/processor.js')
        console.log('AudioWorklet processor registered')
      }catch(e){
        console.warn('AudioWorklet registration failed', e)
      }
    }
    setupAudioWorklet()
  },[])

  async function handleFiles(selectedFiles){
    setFiles(selectedFiles)
    // placeholder: in next iterations we will run BPM detection, stem separation, and import mapping
    console.log('Imported files:', selectedFiles.map(f => ({name: f.name, size: f.size, type: f.type})))
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

createRoot(document.getElementById('root')).render(<App />)
