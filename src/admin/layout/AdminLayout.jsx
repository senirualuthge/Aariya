import React from 'react';
import Sidebar from './Sidebar';
import TopBar from './TopBar';

export default function AdminLayout({ children }) {
  return (
    <div style={{
      display: 'flex',
      width: '100vw',
      height: '100vh',
      background: '#050508',
      color: '#fff',
      fontFamily: 'system-ui, -apple-system, sans-serif'
    }}>
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
        <TopBar />
        <main style={{
          flex: 1,
          overflowY: 'auto',
          padding: '32px',
          background: 'radial-gradient(ellipse at top right, rgba(255,143,163,0.03), transparent 50%)'
        }}>
          {children}
        </main>
      </div>
    </div>
  );
}
