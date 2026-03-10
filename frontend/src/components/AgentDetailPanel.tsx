import React, { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';
import type { Agent } from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const STATUS_LABELS: Record<string, string> = {
  idle: '💤 Idle',
  working: '⚙️ Working',
  thinking: '💭 Thinking',
  communicating: '💬 Communicating',
};

const STATUS_COLORS: Record<string, string> = {
  idle: '#888',
  working: '#4caf50',
  thinking: '#ffc107',
  communicating: '#2196f3',
};

export const AgentDetailPanel: React.FC = () => {
  const { agents, selectedAgentId, setSelectedAgent, tasks } = useStore();
  const [showPromptModal, setShowPromptModal] = useState(false);
  const agent = agents.find((a) => a.id === selectedAgentId);

  if (!agent) return null;

  const agentTasks = tasks.filter((t) => t.assigned_to.includes(agent.id) && (t.status === 'todo' || t.status === 'in_progress'));

  const handleDismiss = async () => {
    if (!confirm(`Dismiss agent ${agent.name}?`)) return;
    await fetch(`${API_URL}/api/agents/${agent.id}`, { method: 'DELETE' });
    setSelectedAgent(null);
  };

  return (
    <>
    <div className="agent-detail-panel">
      <div className="panel-header">
        <span>🧑‍💼 Agent Details</span>
        <button className="close-btn" onClick={() => setSelectedAgent(null)}>✕</button>
      </div>

      <div className="agent-profile">
        <div
          className="avatar-circle"
          style={{ background: `hsl(${agent.avatar_index * 45}, 70%, 60%)` }}
        >
          {getRoleEmoji(agent.role)}
        </div>
        <div className="agent-info">
          <div className="agent-name">{agent.name}</div>
          <div className="agent-role">{agent.role}</div>
          <div
            className="agent-status"
            style={{ color: STATUS_COLORS[agent.status] }}
          >
            {STATUS_LABELS[agent.status] || agent.status}
          </div>
        </div>
      </div>

      <div className="detail-section">
        <div className="section-label">Model</div>
        <div className="section-value">{agent.model}</div>
      </div>

      <div className="detail-section">
        <div className="section-label">Workstation</div>
        <div className="section-value">{agent.workstation_id}</div>
      </div>

      {agent.skills.length > 0 && (
        <div className="detail-section">
          <div className="section-label">Skills</div>
          <div className="skill-tags">
            {agent.skills.map((s) => (
              <span key={s} className="skill-tag">{s}</span>
            ))}
          </div>
        </div>
      )}

      {agentTasks.length > 0 && (
        <div className="detail-section">
          <div className="section-label">Tasks ({agentTasks.length})</div>
          <div className="task-list">
            {agentTasks.map((t) => (
              <div key={t.id} className="task-item">
                <span className={`task-dot ${t.status}`} />
                <span>{t.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="agent-actions">
        <button className="btn-chat" onClick={() => {}}>
          💬 Chat
        </button>
        <button className="btn-prompt" onClick={() => setShowPromptModal(true)}>
          📝 Prompt
        </button>
        <button className="btn-dismiss" onClick={handleDismiss}>
          👋 Dismiss
        </button>
      </div>
    </div>
    {showPromptModal && (
      <SystemPromptModal agent={agent} onClose={() => setShowPromptModal(false)} />
    )}
    </>
  );
};

const SystemPromptModal: React.FC<{
  agent: Agent;
  onClose: () => void;
}> = ({ agent, onClose }) => {
  const { updateAgent } = useStore();
  const [prompt, setPrompt] = useState(agent.system_prompt);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(!agent.system_prompt);

  useEffect(() => {
    if (agent.system_prompt) return;
    // Fetch role default for old agents with empty system_prompt
    fetch(`${API_URL}/api/agents/role-prompts`)
      .then((r) => r.json())
      .then((defaults: Record<string, string>) => {
        setPrompt(defaults[agent.role] || '');
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [agent.system_prompt, agent.role]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch(`${API_URL}/api/agents/${agent.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ system_prompt: prompt }),
      });
      updateAgent(agent.id, { system_prompt: prompt });
    } finally {
      setSaving(false);
    }
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ width: 560 }}>
        <div className="modal-header">
          <span>📝 System Prompt — {agent.name}</span>
          <button className="close-btn" onClick={onClose}>✕</button>
        </div>
        <div style={{ padding: '12px 16px' }}>
          <textarea
            className="prompt-textarea"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Enter system prompt to customize this agent's behavior..."
          />
        </div>
        <div className="prompt-modal-actions">
          <button className="btn-chat" onClick={onClose}>Cancel</button>
          <button className="btn-prompt" onClick={handleSave} disabled={saving || loading}>
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};

function getRoleEmoji(role: string): string {
  const map: Record<string, string> = {
    Developer: '💻',
    Researcher: '🔍',
    Analyst: '📊',
    Writer: '✍️',
    Designer: '🎨',
    PM: '📋',
    DevOps: '🔧',
    QA: '🧪',
  };
  return map[role] || '🤖';
}
