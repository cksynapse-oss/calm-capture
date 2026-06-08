import React from 'react';

const TheVoid = () => {
  return (
    <main className="relative w-full h-screen flex flex-col items-center justify-center">
      {/* Absolute Ambient Center Glow */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="w-[600px] h-[600px] rounded-full bg-[radial-gradient(circle,rgba(255,183,134,0.05)_0%,transparent_70%)] blur-3xl"></div>
      </div>

      {/* Main Interactive Core */}
      <div className="relative z-10 w-full max-w-2xl px-8 flex flex-col items-center gap-12">
        <div className="w-16 h-16 rounded-full glass-panel flex items-center justify-center node-pulse shadow-[0_0_30px_rgba(255,183,134,0.1)]">
          <span className="material-symbols-outlined text-tertiary scale-110" style={{ fontVariationSettings: "'FILL' 1" }}>
            all_inclusive
          </span>
        </div>

        <div className="w-full relative group">
          <input
            className="w-full bg-transparent border-none p-0 font-display-lg text-[48px] text-on-surface text-center focus:ring-0 focus:outline-none placeholder:text-on-surface-variant/30 tracking-tight transition-all"
            placeholder="Initialize thought sequence..."
            type="text"
            autoFocus
          />
          <div className="absolute -bottom-4 left-1/2 -translate-x-1/2 w-0 h-[1px] bg-gradient-to-r from-transparent via-tertiary to-transparent group-focus-within:w-2/3 transition-all duration-700 opacity-50"></div>
        </div>

        {/* Peripheral Action Nodes */}
        <div className="flex items-center gap-12 mt-8">
          <button className="flex flex-col items-center gap-3 text-on-surface-variant/40 hover:text-secondary-fixed transition-all duration-500 group">
            <div className="w-2 h-2 rounded-full bg-secondary/30 group-hover:bg-secondary group-hover:shadow-[0_0_15px_rgba(192,193,255,0.4)] transition-all"></div>
            <span className="font-label-sm text-[10px] uppercase tracking-wider opacity-0 group-hover:opacity-100 transition-opacity">
              Connect Hardware
            </span>
          </button>

          <button className="flex flex-col items-center gap-3 text-on-surface-variant/40 hover:text-tertiary-fixed transition-all duration-500 group">
            <div className="w-2 h-2 rounded-full bg-tertiary/30 group-hover:bg-tertiary group-hover:shadow-[0_0_15px_rgba(255,183,134,0.4)] transition-all"></div>
            <span className="font-label-sm text-[10px] uppercase tracking-wider opacity-0 group-hover:opacity-100 transition-opacity">
              Sync Memory
            </span>
          </button>

          <button className="flex flex-col items-center gap-3 text-on-surface-variant/40 hover:text-on-surface transition-all duration-500 group">
            <div className="w-2 h-2 rounded-full bg-on-surface-variant/30 group-hover:bg-on-surface-variant group-hover:shadow-[0_0_15px_rgba(226,226,226,0.3)] transition-all"></div>
            <span className="font-label-sm text-[10px] uppercase tracking-wider opacity-0 group-hover:opacity-100 transition-opacity">
              Inference Settings
            </span>
          </button>
        </div>
      </div>
    </main>
  );
};

export default TheVoid;
