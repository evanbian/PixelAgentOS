import React, { useCallback, useEffect, useRef, useState } from 'react';
import Phaser from 'phaser';
import { gameConfig } from './game/config';
import { useStore } from './store/useStore';
import { useWebSocket } from './hooks/useWebSocket';
import { useGameBridge } from './hooks/useGameBridge';
import { AgentCreateModal } from './components/AgentCreateModal';
import { TaskDashboard } from './components/TaskDashboard';
import { InteractionLog } from './components/InteractionLog';
import { AgentDetailPanel } from './components/AgentDetailPanel';
import { DeliverableViewer } from './components/DeliverableViewer';
import { PMSettings } from './components/PMSettings';
import { WhiteboardModal } from './components/WhiteboardModal';
import { FilingCabinetModal } from './components/FilingCabinetModal';
import './App.css';

export default function App() {
  const gameRef = useRef<Phaser.Game | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { wsConnected, agents, showTaskDashboard, toggleTaskDashboard, tasks } = useStore();

  const [showWhiteboard, setShowWhiteboard] = useState(false);
  const [showFilingCabinet, setShowFilingCabinet] = useState(false);

  useWebSocket();
  // Whiteboard click → WhiteboardModal (kanban), FilingCabinet → modal
  useGameBridge({
    onWhiteboardClick: useCallback(() => setShowWhiteboard((v) => !v), []),
    onFilingCabinetClick: useCallback(() => setShowFilingCabinet((v) => !v), []),
  });

  // Initialize Phaser once — OfficeScene subscribes to Zustand store directly
  useEffect(() => {
    if (containerRef.current && !gameRef.current) {
      gameRef.current = new Phaser.Game({
        ...gameConfig,
        parent: containerRef.current,
      });
    }
    return () => {
      gameRef.current?.destroy(true);
      gameRef.current = null;
    };
  }, []);

  return (
    <div className="app-layout">
      {/* Status Bar */}
      <div className="status-bar">
        <div className="status-left">
          <span className="app-title">PixelAgentOS</span>
          <span className={`ws-badge ${wsConnected ? 'connected' : 'disconnected'}`}>
            {wsConnected ? 'Connected' : 'Reconnecting...'}
          </span>
        </div>
        <div className="status-right">
          <PMSettings />
          <button
            className={`status-toggle ${showTaskDashboard ? 'active' : ''}`}
            onClick={toggleTaskDashboard}
          >
            Tasks {tasks.length > 0 ? `(${tasks.length})` : ''}
          </button>
          <span className="stat">{agents.length} Agents</span>
          <span className="stat">
            {agents.filter((a) => a.status !== 'idle').length} Active
          </span>
        </div>
      </div>

      {/* Main Layout */}
      <div className="main-layout">
        <div className="left-column">
          <div className="game-container">
            <div ref={containerRef} className="phaser-container" />
            <div className="game-hint">
              Click an empty workstation to hire an agent · Click an agent to interact
            </div>
          </div>
          {showTaskDashboard && <TaskDashboard />}
        </div>

        <div className="sidebar">
          <InteractionLog />
        </div>
      </div>

      {/* Overlays */}
      <AgentCreateModal onAgentCreated={() => {}} />
      <AgentDetailPanel />
      <DeliverableViewer />
      <WhiteboardModal open={showWhiteboard} onClose={() => setShowWhiteboard(false)} />
      <FilingCabinetModal open={showFilingCabinet} onClose={() => setShowFilingCabinet(false)} />
    </div>
  );
}
