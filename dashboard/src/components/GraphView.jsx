import { useEffect, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

// Pramāṇa color map — matches CSS variables
const PRAMANA_COLORS = {
  pratyaksa: '#3b82f6',   // Blue — raw perception
  anumana:   '#f59e0b',   // Amber — inference
  sabda:     '#10b981',   // Emerald — testimony
  upamana:   '#a855f7',   // Purple — analogy
};

const PRAMANA_LABELS = {
  pratyaksa: 'Pratyakṣa (Perception)',
  anumana:   'Anumāna (Inference)',
  sabda:     'Śabda (Testimony)',
  upamana:   'Upamāna (Analogy)',
};

const PRAMANA_GLOW = {
  pratyaksa: 'rgba(59, 130, 246, 0.35)',
  anumana:   'rgba(245, 158, 11, 0.35)',
  sabda:     'rgba(16, 185, 129, 0.35)',
  upamana:   'rgba(168, 85, 247, 0.35)',
};

export default function GraphView({ graphData, threshold, onThresholdChange, onNodeSelect }) {
  const fgRef = useRef();
  const [dimensions, setDimensions] = useState({ width: window.innerWidth - 280, height: window.innerHeight });

  useEffect(() => {
    const handleResize = () => {
      setDimensions({ width: window.innerWidth - 280, height: window.innerHeight });
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  if (!graphData || !graphData.nodes.length) {
    return (
      <div className="loading-screen">
        <p>No graph data available. Capture some knowledge first!</p>
      </div>
    );
  }

  const getNodeColor = (node) => {
    return PRAMANA_COLORS[node.epistemic_type] || PRAMANA_COLORS.pratyaksa;
  };

  // Draw node with Pramāṇa color-coding and glow
  const paintNode = (node, ctx, globalScale) => {
    const label = node.title;
    const fontSize = 12 / globalScale;
    const nodeColor = getNodeColor(node);
    const glowColor = PRAMANA_GLOW[node.epistemic_type] || PRAMANA_GLOW.pratyaksa;

    ctx.font = `${fontSize}px Inter, sans-serif`;
    const textWidth = ctx.measureText(label).width;
    const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 0.8);

    // Glassmorphic card background
    ctx.fillStyle = 'rgba(11, 12, 16, 0.85)';
    ctx.strokeStyle = `${nodeColor}33`;
    ctx.lineWidth = 1 / globalScale;
    ctx.beginPath();
    ctx.roundRect(
      node.x - bckgDimensions[0] / 2,
      node.y - bckgDimensions[1] / 2,
      bckgDimensions[0],
      bckgDimensions[1],
      4
    );
    ctx.fill();
    ctx.stroke();

    // Colored dot with glow
    const dotRadius = 4 / globalScale;
    ctx.save();
    ctx.shadowColor = glowColor;
    ctx.shadowBlur = 8 / globalScale;
    ctx.beginPath();
    ctx.arc(node.x - bckgDimensions[0] / 2 + dotRadius + 4 / globalScale, node.y, dotRadius, 0, 2 * Math.PI);
    ctx.fillStyle = nodeColor;
    ctx.fill();
    ctx.restore();

    // Label text
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#e2e8f0';
    ctx.fillText(label, node.x + dotRadius, node.y);
  };

  // Draw edge labels for connections
  const paintLink = (link, ctx, globalScale) => {
    if (!link.label) return;
    const fontSize = 9 / globalScale;
    const midX = (link.source.x + link.target.x) / 2;
    const midY = (link.source.y + link.target.y) / 2;

    ctx.font = `${fontSize}px Inter, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.35)';
    ctx.fillText(link.label, midX, midY - fontSize);
  };

  return (
    <div className="graph-container">
      <ForceGraph2D
        ref={fgRef}
        width={dimensions.width}
        height={dimensions.height}
        graphData={graphData}
        nodeLabel="title"
        nodeColor={getNodeColor}
        linkColor={() => 'rgba(255, 255, 255, 0.12)'}
        linkWidth={link => Math.max(0.5, (link.value - 0.7) * 6)}
        nodeCanvasObject={paintNode}
        linkCanvasObjectMode={() => 'after'}
        linkCanvasObject={paintLink}
        backgroundColor="#0b0c10"
        cooldownTicks={100}
        onNodeClick={node => {
          fgRef.current.centerAt(node.x, node.y, 1000);
          fgRef.current.zoom(2.5, 2000);
          if (onNodeSelect) {
            onNodeSelect(node.id);
          }
        }}
      />

      {/* Pramāṇa Legend */}
      <div className="glass-panel graph-legend">
        <h4>Pramāṇa</h4>
        {Object.entries(PRAMANA_LABELS).map(([key, label]) => (
          <div className="legend-item" key={key}>
            <span className={`legend-dot ${key}`}></span>
            <span>{label}</span>
          </div>
        ))}
      </div>

      {/* Meta info with slider */}
      <div className="glass-panel graph-meta" style={{ display: 'flex', flexDirection: 'column', gap: '8px', minWidth: '220px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: '600', fontSize: '12px', color: 'var(--text-primary)' }}>Precision Weighting</span>
          <span style={{ fontSize: '11px', fontFamily: 'monospace', background: 'rgba(255,255,255,0.08)', padding: '1px 5px', borderRadius: '3px', color: 'var(--accent-color)' }}>
            {threshold.toFixed(2)}
          </span>
        </div>
        <input 
          type="range" 
          min="0.75" 
          max="0.95" 
          step="0.01" 
          value={threshold} 
          onChange={(e) => onThresholdChange(parseFloat(e.target.value))}
          style={{ width: '100%', accentColor: 'var(--accent-color)', cursor: 'pointer', margin: '4px 0' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-secondary)' }}>
          <span>{graphData.nodes.length} nodes</span>
          <span>{graphData.links.length} edges</span>
        </div>
      </div>
    </div>
  );
}
