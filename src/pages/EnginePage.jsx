import React, { useEffect, useState } from 'react'
import '../app.css'
import './engine.css'

export default function EnginePage(){
  const [readme, setReadme] = useState('')
  useEffect(() => {
    // Try to fetch the README from the public engine path
    fetch('/engine/README.md').then(async res => {
      if (res.ok) {
        setReadme(await res.text())
      } else {
        setReadme('# StudioFlow Engine\n\nREADME not found on server.')
      }
    }).catch(()=> setReadme('# StudioFlow Engine\n\nREADME not available.'))
  }, [])

  return (
    <div className="engine-page">
      <header className="topbar">StudioFlow Engine — Download & Quickstart</header>
      <main className="main">
        <section className="engine-hero">
          <h2>StudioFlow Core (studioflow_core.py)</h2>
          <p className="small">A Python prototype audio engine (DSP, project model, export, example usage).</p>
          <div className="engine-actions">
            <a className="import-btn" href="/engine/studioflow_core.py" download>Download engine (studioflow_core.py)</a>
            <a className="import-btn" href="/engine/README.md" download>Download README</a>
          </div>
        </section>

        <section className="engine-docs">
          <h3>Quickstart (run locally)</h3>
          <p className="small">The engine is a backend module. To run locally:</p>
          <ol>
            <li>Save <code>studioflow_core.py</code> to a folder.</li>
            <li>Install dependencies: <code>pip install numpy</code> (optionals: soundfile scipy sounddevice requests).</li>
            <li>Run the example: <code>python studioflow_core.py</code>.</li>
          </ol>

          <h3>README</h3>
          <pre className="readme">{readme}</pre>

          <h3>Next steps</h3>
          <ul>
            <li>If you want a server demo, I can add a small Flask wrapper to show example logs and let users trigger the example from the site.</li>
            <li>I can also add a downloadable ZIP (engine + README + small server example).</li>
          </ul>
        </section>
      </main>
    </div>
  )
}
