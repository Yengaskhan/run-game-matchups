import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import MatchupApp from './MatchupApp';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MatchupApp />
  </StrictMode>,
);
