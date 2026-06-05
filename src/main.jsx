import React from 'react'
import { createRoot } from 'react-dom/client'
import MobileKnob from './components/MobileKnob'
import './app.css'

function App(){
  const [val, setVal] = React.useState(0.5)

  React.useEffect(()=>{
    // register AudioWorklet (skeleton) when available
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

  return (
    <div className="app-root">
      <header className="topbar">Unfazed Studio — Mobile MVP</header>
      <main className="main">
        <section className="controls">
          <MobileKnob value={val} onChange={setVal} />
          <div className="val">Value: {(val*100).toFixed(0)}%</div>
        </section>
        <section className="notes">
          <p>AudioWorklet skeleton is registered in console. Use this branch as a starting point.</p>
        </section>
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
