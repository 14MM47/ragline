// main.tsx — React entry point: mount <App /> into #root with StrictMode.
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

// StrictMode double-invokes effects in dev to surface unsafe patterns early.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
