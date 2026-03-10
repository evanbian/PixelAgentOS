import React, { useEffect, useRef, useState } from 'react';
import { useStore } from '../store/useStore';
import type { InteractionLog as LogEntry } from '../types';

export const InteractionLog: React.FC = () => {
  const {
    logs,
    agents,
    selectedAgentId,
    wsSend,
    addLog,
  } = useStore();

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [chatMessage, setChatMessage] = useState('');

  // Auto-scroll on new logs
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // Auto-focus input when selected agent changes
  useEffect(() => {
    if (selectedAgentId) {
      inputRef.current?.focus();
    }
  }, [selectedAgentId]);

  const selectedAgent = agents.find((a) => a.id === selectedAgentId);

  // Filter: only chat + deliverable messages
  const filteredLogs = selectedAgentId
    ? logs.filter(
        (log) =>
          (log.type === 'chat' || log.type === 'deliverable') &&
          (log.from_id === selectedAgentId || log.to_id === selectedAgentId)
      )
    : logs.filter(
        (log) => log.type === 'chat' || log.type === 'deliverable'
      );

  const handleSendChat = (e: React.FormEvent) => {
    e.preventDefault();
    const message = chatMessage.trim();
    if (!message || !selectedAgentId) return;

    // 1. Clear input immediately
    setChatMessage('');

    // 2. Optimistic insert of user message
    addLog({
      from_id: 'human',
      to_id: selectedAgentId,
      content: message,
      type: 'chat',
    });

    // 3. Non-blocking WS send
    if (wsSend) {
      wsSend('agent:chat', { agent_id: selectedAgentId, message });
    }
  };

  // Determine typing indicator
  const typingAgent =
    selectedAgent &&
    (selectedAgent.status === 'thinking' || selectedAgent.status === 'working')
      ? selectedAgent
      : null;

  const panelTitle = selectedAgent
    ? `💬 Chat with ${selectedAgent.name}`
    : '💬 Chat';

  return (
    <div className="log-panel">
      <div className="panel-header">
        <span>{panelTitle}</span>
        <div className="header-actions" />
      </div>

      <div className="log-entries">
        {filteredLogs.length === 0 && (
          <div className="chat-empty-state">
            {selectedAgent
              ? `Chat with ${selectedAgent.name} will appear here`
              : 'Chat messages and deliverables appear here'}
          </div>
        )}
        {filteredLogs.map((log) => (
          <LogEntryRow key={log.id} log={log} agents={agents} />
        ))}

        {/* Typing indicator */}
        {typingAgent && (
          <div className="typing-indicator">
            {typingAgent.status === 'thinking' ? '🤔' : '⚡'}{' '}
            {typingAgent.name} is {typingAgent.status}
            <span className="typing-dots">
              <span>.</span><span>.</span><span>.</span>
            </span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Chat with selected agent */}
      {selectedAgent && (
        <div className="chat-input-area">
          <form onSubmit={handleSendChat} className="chat-form">
            <input
              ref={inputRef}
              className="pixel-input chat-input"
              placeholder={`Message ${selectedAgent.name}...`}
              value={chatMessage}
              onChange={(e) => setChatMessage(e.target.value)}
            />
            <button
              type="submit"
              className="btn-send"
              disabled={!chatMessage.trim() || !wsSend}
            >
              →
            </button>
          </form>
        </div>
      )}
    </div>
  );
};

const LOG_COLORS: Record<string, string> = {
  system: '#7986cb',
  chat: '#4db6ac',
  agent: '#ff8a65',
  error: '#ef5350',
  deliverable: '#5c6bc0',
};

interface LogEntryRowProps {
  log: LogEntry;
  agents: Array<{ id: string; name: string }>;
}

const LogEntryRow: React.FC<LogEntryRowProps> = ({ log, agents }) => {
  // Deliverable card rendering
  if (log.type === 'deliverable') {
    const taskId = log.content.replace('__DELIVERABLE__', '');
    const task = useStore.getState().tasks.find(t => t.id === taskId);
    if (!task) return null;
    return (
      <div className="deliverable-card" onClick={() => useStore.getState().setSelectedTask(taskId)}>
        <div className="deliverable-card-header">
          <span className="deliverable-icon">📦</span>
          <span className="deliverable-title">{task.title}</span>
          <span className="status-badge status-done">done</span>
        </div>
        <div className="deliverable-preview">
          {task.output?.slice(0, 150)}{(task.output?.length ?? 0) > 150 ? '...' : ''}
        </div>
        <div className="deliverable-action">Click to view full deliverable →</div>
      </div>
    );
  }

  const getDisplayName = (id: string) => {
    if (id === 'system') return '🤖 System';
    if (id === 'human') return '👤 You';
    if (id === 'all') return '📢 All';
    return agents.find((a) => a.id === id)?.name || id.slice(0, 8);
  };

  const isUser = log.from_id === 'human';
  const isSystem = log.type === 'system' || log.type === 'error';

  const msgClass = isSystem ? 'msg-system' : isUser ? 'msg-user' : 'msg-agent';
  const color = LOG_COLORS[log.type] || '#aaaaaa';
  const time = log.timestamp.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  if (isSystem) {
    return (
      <div className={`log-entry ${msgClass}`}>
        <span className="log-time">{time}</span> {log.content}
      </div>
    );
  }

  return (
    <div className={`log-entry ${msgClass}`} style={{ borderLeftColor: isUser ? 'transparent' : color }}>
      <div className="log-meta">
        <span className="log-time">{time}</span>
        {!isUser && (
          <span className="log-from" style={{ color }}>
            {getDisplayName(log.from_id)}
          </span>
        )}
      </div>
      <div className="log-content">{log.content}</div>
    </div>
  );
};
