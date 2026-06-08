import React from 'react';

const Workbench = () => {
  return (
    <main className="relative w-full h-screen pt-[120px] px-8 md:px-16 flex overflow-hidden">
      
      {/* Sidebar: Context Nodes */}
      <aside className="w-1/3 max-w-[350px] border-r border-outline/10 pr-8 overflow-y-auto hidden md:flex flex-col gap-6 h-full pb-32 custom-scrollbar">
        <div className="flex items-center justify-between mb-4 sticky top-0 bg-background/80 backdrop-blur-md py-2 z-10">
          <span className="font-label-sm text-tertiary uppercase tracking-widest">Active Context</span>
          <button className="text-on-surface-variant hover:text-on-surface transition-colors">
            <span className="material-symbols-outlined text-[18px]">add</span>
          </button>
        </div>

        {/* Node: Insight */}
        <div className="glass-panel p-5 rounded-lg border-l-2 border-l-tertiary cursor-pointer hover:bg-surface-container-low transition-colors group">
          <div className="flex justify-between items-start mb-2">
            <span className="font-label-sm text-[10px] text-tertiary-fixed-dim uppercase tracking-wider">Insight Node</span>
            <span className="material-symbols-outlined text-[14px] text-on-surface-variant/50 group-hover:text-on-surface transition-colors">drag_indicator</span>
          </div>
          <h3 className="font-display-md text-[20px] leading-tight mb-2">The Architecture of Silence</h3>
          <p className="font-body-md text-[14px] text-on-surface-variant/70 line-clamp-2">
            In digital environments, white space isn't empty; it's the structural tension that gives weight to the focal elements.
          </p>
        </div>

        {/* Node: Reference */}
        <div className="glass-panel p-5 rounded-lg border-l-2 border-l-secondary cursor-pointer hover:bg-surface-container-low transition-colors group">
          <div className="flex justify-between items-start mb-2">
            <span className="font-label-sm text-[10px] text-secondary-fixed-dim uppercase tracking-wider">Reference</span>
            <span className="material-symbols-outlined text-[14px] text-on-surface-variant/50 group-hover:text-on-surface transition-colors">drag_indicator</span>
          </div>
          <h3 className="font-display-md text-[20px] leading-tight mb-2">Cybernetic Zen Principles</h3>
          <p className="font-body-md text-[14px] text-on-surface-variant/70 line-clamp-2">
            Balancing high-throughput data streams with physiological pacing. The UI must breathe with the user.
          </p>
        </div>
      </aside>

      {/* Main Editor: The Workbench */}
      <section className="flex-1 md:pl-16 flex flex-col h-full relative">
        
        {/* Editor Toolbar */}
        <header className="flex justify-between items-center mb-12">
          <div className="flex gap-4">
            <button className="px-4 py-2 rounded-full border border-outline/20 font-label-sm uppercase tracking-widest text-on-surface hover:bg-surface-bright transition-colors">
              Save Draft
            </button>
            <button className="px-4 py-2 rounded-full font-label-sm uppercase tracking-widest text-on-surface-variant hover:text-on-surface transition-colors">
              Share
            </button>
          </div>
          <div className="flex items-center gap-4 text-on-surface-variant">
            <button className="hover:text-tertiary transition-colors" title="Deep Focus Mode">
              <span className="material-symbols-outlined">center_focus_strong</span>
            </button>
            <button className="hover:text-secondary transition-colors" title="Insert Component">
              <span className="material-symbols-outlined">library_add</span>
            </button>
          </div>
        </header>

        {/* Writing Canvas */}
        <div className="flex-grow flex flex-col max-w-3xl pb-32">
          <input 
            className="w-full bg-transparent border-none p-0 font-display-lg text-[48px] text-on-surface focus:ring-0 placeholder:text-on-surface-variant/30 mb-8" 
            placeholder="Document Title" 
            type="text" 
            defaultValue="Synthesis: Phase II Architecture" 
          />
          
          <textarea 
            className="w-full flex-grow bg-transparent border-none p-0 font-body-lg text-[18px] text-on-surface-variant focus:ring-0 resize-none placeholder:text-on-surface-variant/30 leading-relaxed" 
            placeholder="Begin drafting..."
            defaultValue="By integrating the Insight Node on 'The Architecture of Silence' with the 'Cybernetic Zen Principles', we establish a framework where the user's cognitive load is dynamically measured and mitigated. 

The inference engine does not just predict what information is needed; it predicts the optimal density of that information. When biological metrics (like the 68 BPM baseline) suggest strain, the UI artificially dilates time—increasing padding, slowing animations, and dimming peripheral nodes."
          />
        </div>
      </section>

    </main>
  );
};

export default Workbench;
