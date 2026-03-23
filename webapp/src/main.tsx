import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import Home from './Home.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <HashRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/course/:courseName" element={<App />} />
        <Route
          path="*"
          element={(
            <main className="min-h-screen bg-slate-50 px-4 py-20 text-slate-900">
              <section className="mx-auto max-w-2xl rounded-2xl border border-rose-200 bg-white p-6 shadow-sm">
                <h1 className="text-xl font-semibold text-rose-700">路由不存在</h1>
                <p className="mt-2 text-sm text-slate-600">当前只支持 /course/:courseName 路由格式，请通过课程分享链接访问。</p>
              </section>
            </main>
          )}
        />
      </Routes>
    </HashRouter>
  </StrictMode>,
)
