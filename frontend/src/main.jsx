import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from '@/App'
import ThemeProvider from '@/context/ThemeContext'
import { warmUpBackend } from '@/utils/warmup'
import '@/index.css'

// Wake the Render API the instant the page opens, so its cold start overlaps
// with the time the visitor spends reading the first screen instead of
// blocking their first click.
warmUpBackend()

// ThemeProvider sits outside the router: the theme is a property of the whole
// document, not of any route, and the sign-in screen has to be themed too.
ReactDOM.createRoot(document.getElementById('root')).render(
 <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ThemeProvider>
 </React.StrictMode>,
)
