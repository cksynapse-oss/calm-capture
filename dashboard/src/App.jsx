import { useState, useEffect } from 'react'
import { LayoutGrid, Network } from 'lucide-react'
import GraphView from './components/GraphView'
import ListView from './components/ListView'

function App() {
  const [view, setView] = useState('list');
  const [captures, setCaptures] = useState([]);
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const capRes = await fetch('http://localhost:8000/api/captures');
        const capData = await capRes.json();
        setCaptures(capData);

        const graphRes = await fetch('http://localhost:8000/api/graph');
        const gData = await graphRes.json();
        setGraphData(gData);
      } catch (err) {
        console.error("Failed to fetch data", err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

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
            <ListView captures={captures} />
          ) : (
            <GraphView graphData={graphData} />
          )
        )}
      </main>
    </div>
  )
}

export default App
