import React from 'react'
import { createRoot } from 'react-dom/client'
import MobileKnob from './components/MobileKnob'
import FileImport from './components/FileImport'
import './app.css'
import EnginePage from './pages/EnginePage'

function isTouchDevice(){
  return (('ontouchstart' in window) || (navigator.maxTouchPoints && navigator.maxTouchPoints > 0))
}

function HomeContent({ files }){
  return (
    <main className="main">
      <section className="controls">
        <MobileKnob value={0.5} onChange={()=>{}} />
        <div className="val">Studio controls</div>
      </section>

      <section className="import-section">
        <p className="small">Import audio or project files to test the sampler and engine integration.</p>
      </section>

      <section className="notes">
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
  )
}

function App(){
  const [page, setPage] = React.useState('home')
  const [files, setFiles] = React.useState([])
  const touch = isTouchDevice()

  async function handleFiles(selectedFiles){
    setFiles(selectedFiles)
    console.log('Imported files:', selectedFiles.map(f => ({name: f.name, size: f.size, type: f.type})))
  }

  return (
    <div className="app-root mobile-first">
      <header className="topbar">
        <div style={{display:'flex',gap:8,alignItems:'center'}}>
          <button className="nav-btn" onClick={()=>setPage('home')}>Home</button>
          <button className="nav-btn" onClick={()=>setPage('engine')}>Engine</button>
        </div>
      </header>

      {page === 'home' && (
        <div>
          <section style={{padding:16}}>
            <FileImport onFiles={handleFiles} />
            {!touch && <div className="desktop-note">Desktop detected — you can drag & drop files or click to open.</div>}
          </section>
          <HomeContent files={files} />
        </div>
      )}

      {page === 'engine' && <EnginePage />}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
