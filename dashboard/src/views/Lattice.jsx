import React, { useState } from 'react';

const Lattice = () => {
  const [panePos, setPanePos] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [offset, setOffset] = useState({ x: 0, y: 0 });

  const handleMouseDown = (e) => {
    setIsDragging(true);
    const rect = e.currentTarget.getBoundingClientRect();
    setOffset({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    });
  };

  const handleMouseMove = (e) => {
    if (!isDragging) return;
    setPanePos({
      x: e.clientX - offset.x,
      y: e.clientY - offset.y
    });
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  return (
    <main 
      className="relative w-full h-screen overflow-hidden perspective-container"
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {/* SideNavBar (Desktop) */}
      <nav className="hidden md:flex flex-col items-center py-12 gap-12 fixed left-0 top-0 h-full w-[120px] bg-gradient-to-r from-secondary/10 to-transparent backdrop-blur-3xl z-30">
        <div className="flex flex-col items-center gap-2 mb-8 mt-16">
          <div className="w-12 h-12 rounded-full glass-panel flex items-center justify-center overflow-hidden">
            <span className="material-symbols-outlined text-on-surface">all_inclusive</span>
          </div>
        </div>
        <div className="flex flex-col gap-8 w-full items-center">
          <button className="flex flex-col items-center gap-2 text-on-surface-variant/40 hover:text-on-surface transition-all duration-500 group">
            <span className="material-symbols-outlined group-hover:scale-110 transition-transform">search</span>
            <span className="font-label-sm text-[10px] uppercase tracking-wider opacity-0 group-hover:opacity-100 transition-opacity">Index</span>
          </button>
          <button className="flex flex-col items-center gap-2 text-tertiary-fixed-dim drop-shadow-[0_0_15px_rgba(255,183,134,0.5)] group">
            <span className="material-symbols-outlined scale-110" style={{ fontVariationSettings: "'FILL' 1" }}>psychology</span>
            <span className="font-label-sm text-[10px] uppercase tracking-wider">Inference</span>
          </button>
          <button className="flex flex-col items-center gap-2 text-on-surface-variant/40 hover:text-on-surface transition-all duration-500 group">
            <span className="material-symbols-outlined group-hover:scale-110 transition-transform">database</span>
            <span className="font-label-sm text-[10px] uppercase tracking-wider opacity-0 group-hover:opacity-100 transition-opacity">Memory</span>
          </button>
          <button className="flex flex-col items-center gap-2 text-on-surface-variant/40 hover:text-on-surface transition-all duration-500 group">
            <span className="material-symbols-outlined group-hover:scale-110 transition-transform">shortcut</span>
            <span className="font-label-sm text-[10px] uppercase tracking-wider opacity-0 group-hover:opacity-100 transition-opacity">Action</span>
          </button>
        </div>
      </nav>

      {/* Constellation Graph */}
      <svg className="absolute inset-0 w-full h-full z-20 pointer-events-none" xmlns="http://www.w3.org/2000/svg">
        <path className="constellation-line" d="M 20%,20% L 40%,35% L 30%,60% Z" fill="none" opacity="0.3" stroke="#ffb786" strokeWidth="0.5"></path>
        <path className="constellation-line" d="M 80%,15% L 95%,40% L 70%,55% Z" fill="none" opacity="0.3" stroke="#ffb786" strokeWidth="0.5"></path>
        <path className="constellation-line" d="M 12%,20% L 14%,60% L 10%,70% Z" fill="none" opacity="0.4" stroke="#c0c1ff" strokeWidth="0.5"></path>
        
        <circle className="node-pulse" cx="20%" cy="20%" fill="#ffb786" r="4"></circle>
        <circle className="node-pulse" cx="40%" cy="35%" fill="#ffb786" r="3"></circle>
        <circle className="node-pulse" cx="30%" cy="60%" fill="#ffb786" r="5"></circle>
        <circle className="node-pulse" cx="95%" cy="40%" fill="#c0c1ff" r="4"></circle>
      </svg>

      {/* Floating Glassmorphic Reading Pane */}
      <article 
        className="absolute glass-pane w-[600px] p-12 rounded-xl z-30 shadow-2xl flex flex-col gap-8"
        style={{
          left: panePos.x === 0 ? '50%' : panePos.x,
          top: panePos.y === 0 ? '50%' : panePos.y,
          transform: panePos.x === 0 ? 'translate(-50%, -50%)' : 'none',
          cursor: isDragging ? 'grabbing' : 'grab'
        }}
        onMouseDown={handleMouseDown}
      >
        <div className="flex justify-between items-start mb-2 pointer-events-none">
          <div className="flex flex-col">
            <span className="font-label-sm text-tertiary uppercase tracking-widest">Synthesis Node 0xAF3</span>
            <h2 className="font-display-md text-[36px] text-on-surface mt-2 tracking-tight">On the Entropy of Meaning</h2>
          </div>
          <div className="p-2 rounded-full border border-on-surface/10 hover:bg-on-surface/5 transition-colors cursor-pointer pointer-events-auto">
            <span className="material-symbols-outlined text-on-surface-variant text-[20px]">drag_indicator</span>
          </div>
        </div>

        <div className="font-headline-lg text-[28px] italic text-on-surface/90 leading-snug pointer-events-none">
          "The structural integrity of semantic networks relies heavily on the tension between cognitive dissonance and the rhythmic 'Ma' of silence."
        </div>

        <p className="font-body-md text-on-surface-variant/80 pointer-events-none">
          This abstract explores the intersection of Cybernetic Zen and the architectural void. By applying frosted layers to active cognition, we reduce peripheral load, allowing the primary data constellation to emerge with crystalline clarity.
        </p>

        {/* Bottom Actions */}
        <div className="flex items-center gap-6 pt-6 border-t border-on-surface/10 pointer-events-auto">
          <button className="flex items-center gap-2 font-label-md text-tertiary hover:text-on-surface transition-colors">
            <span className="material-symbols-outlined">add_circle</span>
            Insert Snippet
          </button>
          <button className="flex items-center gap-2 font-label-md text-secondary hover:text-on-surface transition-colors">
            <span className="material-symbols-outlined">hub</span>
            Trace Origin
          </button>
          <div className="ml-auto">
            <button className="flex items-center gap-2 font-label-md text-on-surface-variant/50 hover:text-error transition-colors">
              <span className="material-symbols-outlined">close</span>
              Close
            </button>
          </div>
        </div>
      </article>
    </main>
  );
};

export default Lattice;
