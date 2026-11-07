import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './styles/animations.css'
import './styles/responsive.css'
import App from './App'
import { ThemeProvider } from './contexts/ThemeContext'
import { JobProvider } from './contexts/JobContext'
import { AnalyticsProvider } from './contexts/AnalyticsContext'
import { ToastProvider } from './components/ui/Toast'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <JobProvider>
        <AnalyticsProvider>
          <App />
          <ToastProvider />
        </AnalyticsProvider>
      </JobProvider>
    </ThemeProvider>
  </StrictMode>,
)
