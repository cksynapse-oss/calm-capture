export default function ListView({ captures, onCaptureClick }) {
  if (!captures || captures.length === 0) {
    return (
      <div className="list-container">
        <div className="page-header">
          <h1 className="brand">Captures</h1>
          <p>You haven't captured any knowledge yet.</p>
        </div>
      </div>
    );
  }

  const getNoveltyClass = (score) => {
    if (score > 0.65) return 'novelty-high';
    if (score > 0.3) return 'novelty-med';
    return 'novelty-low';
  };

  const getNoveltyLabel = (score) => {
    if (score > 0.65) return 'Novel ✦';
    if (score > 0.3) return 'Interesting';
    return 'Familiar';
  };

  return (
    <div className="list-container">
      <div className="page-header">
        <h1 className="brand">Knowledge Base</h1>
        <p>Your captured active inference knowledge.</p>
      </div>
      
      <div className="capture-grid">
        {captures.map(cap => {
          const epistemicType = cap.epistemic_type || 'pratyaksa';
          const displayTitle = cap.title || cap.auto_title || cap.source_url || 'Captured Note';
          
          return (
            <div 
              key={cap.capture_id} 
              className={`glass-panel capture-card epistemic-${epistemicType}`}
              onClick={() => onCaptureClick(cap)}
              style={{ cursor: 'pointer' }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div className="card-domain">{cap.domain || 'SYSTEM'}</div>
                <span className={`pramana-badge ${epistemicType}`}>{epistemicType}</span>
              </div>
              
              <div className="card-title">{displayTitle}</div>
              
              {cap.user_note && (
                <div className="card-note">
                  {cap.user_note}
                </div>
              )}
              
              <div className="card-meta">
                <span>{new Date(cap.timestamp * 1000).toLocaleDateString()}</span>
                <span className={`novelty-badge ${getNoveltyClass(cap.prediction_error_score)}`}>
                  {getNoveltyLabel(cap.prediction_error_score)} ({(cap.prediction_error_score * 100).toFixed(0)}%)
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

