import { useState, useEffect } from 'react'
import { LayoutGrid, Network, X, ExternalLink, Calendar, Compass, FileText } from 'lucide-react'
import GraphView from './components/GraphView'
import ListView from './components/ListView'

function App() {
  const [view, setView] = useState('list');
  const [captures, setCaptures] = useState([]);
  const [graphData, setGraphData] = useState(null);
  const [threshold, setThreshold] = useState(0.82);
  const [loading, setLoading] = useState(true);
  
  // Detail Modal State
  const [selectedCapture, setSelectedCapture] = useState(null);
  const [noteText, setNoteText] = useState('');
  const [savingNote, setSavingNote] = useState(false);

  // Fetch captures once at mount
  const fetchCaptures = async () => {
    try {
      const capRes = await fetch('http://localhost:8000/api/captures');
      const capData = await capRes.json();
      setCaptures(capData);
    } catch (err) {
      console.error("Failed to fetch captures", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCaptures();
  }, []);

  // Fetch graph data whenever threshold changes
  useEffect(() => {
    const fetchGraph = async () => {
      try {
        const graphRes = await fetch(`http://localhost:8000/api/graph?threshold=${threshold}`);
        const gData = await graphRes.json();
        setGraphData(gData);
      } catch (err) {
        console.error("Failed to fetch graph data", err);
      }
    };
    fetchGraph();
  }, [threshold]);

  // Sync textarea text when selected capture changes
  useEffect(() => {
    if (selectedCapture) {
      setNoteText(selectedCapture.user_note || '');
    }
  }, [selectedCapture]);

  const handleNodeSelect = (nodeId) => {
    const cap = captures.find(c => c.capture_id === nodeId);
    if (cap) {
      setSelectedCapture(cap);
    }
  };

  const handleSaveNote = async () => {
    if (!selectedCapture) return;
    setSavingNote(true);
    try {
      const res = await fetch(`http://localhost:8000/api/captures/${selectedCapture.capture_id}/note`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ user_note: noteText }),
      });
      const data = await res.json();
      if (data.success) {
        // Update local state list
        setCaptures(prev => prev.map(c => 
          c.capture_id === selectedCapture.capture_id 
            ? { ...c, user_note: noteText } 
            : c
        ));
        
        // Update modal instance
        setSelectedCapture(prev => ({ ...prev, user_note: noteText }));
        
        // Refresh graph so the metadata stays in sync
        const graphRes = await fetch(`http://localhost:8000/api/graph?threshold=${threshold}`);
        const gData = await graphRes.json();
        setGraphData(gData);
      }
    } catch (err) {
      console.error("Failed to save note", err);
    } finally {
      setSavingNote(false);
    }
  };

  return (
    <div className="app-container">
      <aside className="sidebar">
        <div className="brand">
          <div style={{width: '24px', height: '24px', borderRadius: '6px', background: 'var(--accent-color)'}}></div>
          Calm Capture
        </div>
        
        <div style={{marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '8px'}}>
          <div 
            className={`nav-item ${view === 'list' ? 'active' : ''}`}
            onClick={() => setView('list')}
          >
            <LayoutGrid size={20} />
            Library
          </div>
          <div 
            className={`nav-item ${view === 'graph' ? 'active' : ''}`}
            onClick={() => setView('graph')}
          >
            <Network size={20} />
            Knowledge Graph
          </div>
        </div>
      </aside>

      <main className="main-content">
        {loading ? (
          <div className="loading-screen">
            <div className="spinner"></div>
            <p style={{color: 'var(--text-secondary)'}}>Loading Knowledge Base...</p>
          </div>
        ) : (
          view === 'list' ? (
            <ListView captures={captures} onCaptureClick={setSelectedCapture} />
          ) : (
            <GraphView 
              graphData={graphData} 
              threshold={threshold}
              onThresholdChange={setThreshold}
              onNodeSelect={handleNodeSelect}
            />
          )
        )}
      </main>

      {/* Glassmorphic Detail Modal */}
      {selectedCapture && (
        <div className="modal-backdrop" onClick={() => setSelectedCapture(null)}>
          <div className="modal-container glass-panel" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <span className="card-domain">{selectedCapture.domain || 'OCR SYSTEM'}</span>
                <span className={`pramana-badge ${selectedCapture.epistemic_type || 'pratyaksa'}`}>
                  {selectedCapture.epistemic_type || 'pratyaksa'}
                </span>
              </div>
              <button className="close-btn" onClick={() => setSelectedCapture(null)}>
                <X size={18} />
              </button>
            </div>

            <div className="modal-body">
              <h2 className="modal-title">
                {selectedCapture.title || selectedCapture.auto_title || 'Captured Note'}
              </h2>

              <div className="modal-meta">
                <span className="meta-item">
                  <Calendar size={14} />
                  {new Date(selectedCapture.timestamp * 1000).toLocaleString()}
                </span>
                <span className="meta-item">
                  <Compass size={14} />
                  Novelty: {((selectedCapture.prediction_error_score || 0) * 100).toFixed(0)}%
                </span>
                {selectedCapture.word_count > 0 && (
                  <span className="meta-item">
                    <FileText size={14} />
                    {selectedCapture.word_count} words
                  </span>
                )}
              </div>

              {selectedCapture.source_url && selectedCapture.source_url.startsWith('http') && (
                <a 
                  href={selectedCapture.source_url} 
                  target="_blank" 
                  rel="noopener noreferrer" 
                  className="source-link"
                >
                  Open Original Page <ExternalLink size={12} style={{ marginLeft: '4px' }} />
                </a>
              )}

              <div className="modal-section">
                <h3>Auto Summary</h3>
                <p className="summary-text">
                  {selectedCapture.one_sentence_summary || selectedCapture.excerpt || 'No summary available.'}
                </p>
              </div>

              <div className="modal-section">
                <h3>Full Capture Content</h3>
                <div className="content-markdown-body">
                  {selectedCapture.content_markdown ? (
                    selectedCapture.content_markdown.split('\n').map((para, i) => (
                      para.trim() && <p key={i}>{para}</p>
                    ))
                  ) : (
                    <p style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                      No detailed text was captured for this entry.
                    </p>
                  )}
                </div>
              </div>

              <div className="modal-section note-section">
                <h3>Reflection Note</h3>
                <textarea
                  value={noteText}
                  onChange={e => setNoteText(e.target.value)}
                  placeholder="Reflect on this concept. How does this connect to your existing knowledge?"
                  className="note-textarea"
                />
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '10px' }}>
                  <button 
                    className="save-note-btn" 
                    onClick={handleSaveNote}
                    disabled={savingNote}
                  >
                    {savingNote ? 'Saving...' : 'Save Reflection'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
