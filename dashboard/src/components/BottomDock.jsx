import React from 'react';
import { NavLink } from 'react-router-dom';

const BottomDock = () => {
  return (
    <nav className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 flex items-center p-2 bg-surface/10 backdrop-blur-[40px] border border-on-surface/15 shadow-xl rounded-full">
      <div className="flex items-center">
        <NavLink 
          to="/" 
          className={({ isActive }) => `flex flex-col items-center justify-center px-6 py-2 transition-colors active:scale-90 duration-300 cursor-pointer ${isActive ? 'text-primary bg-surface-container-highest/50 rounded-full transition-transform' : 'text-on-surface-variant/70 hover:text-on-surface'}`}
        >
          <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>radio_button_checked</span>
          <span className="font-label-md text-[14px] mt-1">The Void</span>
        </NavLink>

        <NavLink 
          to="/lattice" 
          className={({ isActive }) => `flex flex-col items-center justify-center px-6 py-2 transition-colors active:scale-90 duration-300 cursor-pointer ${isActive ? 'text-primary bg-surface-container-highest/50 rounded-full transition-transform' : 'text-on-surface-variant/70 hover:text-on-surface'}`}
        >
          <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>hub</span>
          <span className="font-label-md text-[14px] mt-1">Lattice</span>
        </NavLink>

        <NavLink 
          to="/workbench" 
          className={({ isActive }) => `flex flex-col items-center justify-center px-6 py-2 transition-colors active:scale-90 duration-300 cursor-pointer ${isActive ? 'text-primary bg-surface-container-highest/50 rounded-full transition-transform' : 'text-on-surface-variant/70 hover:text-on-surface'}`}
        >
          <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>edit_square</span>
          <span className="font-label-md text-[14px] mt-1">Workbench</span>
        </NavLink>
      </div>
    </nav>
  );
};

export default BottomDock;
