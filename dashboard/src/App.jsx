import React from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import TopAppBar from './components/TopAppBar'
import BottomDock from './components/BottomDock'
import TheVoid from './views/TheVoid'
import Lattice from './views/Lattice'
import Workbench from './views/Workbench'

function App() {
  return (
    <Router>
      <div className="bg-background text-on-surface min-h-screen overflow-hidden antialiased selection:bg-tertiary/30 selection:text-tertiary-fixed relative">
        {/* Ambient Biosphere */}
        <div className="biosphere-glow-left"></div>
        <div className="biosphere-glow-right"></div>
        
        <TopAppBar />
        
        <Routes>
          <Route path="/" element={<TheVoid />} />
          <Route path="/lattice" element={<Lattice />} />
          <Route path="/workbench" element={<Workbench />} />
        </Routes>

        <BottomDock />
      </div>
    </Router>
  )
}

export default App

