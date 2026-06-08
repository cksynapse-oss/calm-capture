import React from 'react';

const TopAppBar = () => {
  return (
    <header className="fixed top-0 w-full z-40 bg-transparent flex justify-between items-center px-8 pt-8 pb-4 md:px-16 md:pt-6">
      <div className="font-display-md text-[24px] md:text-[28px] text-on-surface tracking-widest uppercase font-bold">
        Corteon
      </div>
      <div className="flex items-center gap-6">
        {/* Incognito Widget */}
        <div className="glass-panel px-4 py-2 rounded-full flex items-center gap-3">
          <span className="material-symbols-outlined text-secondary text-[18px]">vital_signs</span>
          <span className="font-label-sm text-[12px] text-on-surface-variant">BPM 68</span>
          <div className="w-2 h-2 rounded-full bg-secondary animate-pulse"></div>
        </div>
        <div className="flex items-center gap-4 text-primary">
          <button aria-label="Account" className="hover:opacity-100 transition-opacity opacity-60 text-on-surface-variant">
            <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>account_circle</span>
          </button>
          <button aria-label="Settings" className="hover:opacity-100 transition-opacity opacity-60 text-on-surface-variant">
            <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>settings</span>
          </button>
        </div>
      </div>
    </header>
  );
};

export default TopAppBar;
