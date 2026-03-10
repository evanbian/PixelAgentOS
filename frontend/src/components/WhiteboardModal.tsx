import React, { useCallback, useEffect, useState } from 'react';
import { useStore } from '../store/useStore';
import type { Task, TaskStatus } from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface Props {
  open: boolean;
  onClose: () => void;
}

const COLUMNS: { key: TaskStatus; label: string; color: string }[] = [
  { key: 'todo',        label: 'To Do',        color: '#ff8a65' },
  { key: 'in_progress', label: 'In Progress',   color: '#4caf50' },
  { key: 'done',        label: 'Done',          color: '#7986cb' },
];

export function WhiteboardModal({ open, onClose }: Props) {
  const { tasks, agents } = useStore();
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [desc, setDesc] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showCreate) setShowCreate(false);
        else onClose();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose, showCreate]);

  const handleCreate = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setLoading(true);
    try {
      await fetch(`${API_URL}/api/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, description: desc, assigned_to: [], schedule: null }),
      });
      setTitle('');
      setDesc('');
      setShowCreate(false);
    } finally {
      setLoading(false);
    }
  }, [title, desc]);

  if (!open) return null;

  const grouped: Record<TaskStatus, Task[]> = {
    todo: [],
    in_progress: [],
    done: [],
    cancelled: [],
  };
  for (const t of tasks) {
    if (grouped[t.status]) grouped[t.status].push(t);
  }

  const getAgentNames = (ids: string[]) =>
    ids.map((id) => agents.find((a) => a.id === id)?.name ?? id).join(', ');

  const openDeliverable = (taskId: string) => {
    useStore.getState().setSelectedTask(taskId);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="whiteboard-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span>Whiteboard</span>
          <div className="modal-header-actions">
            <button
              className="kanban-add-btn"
              onClick={() => setShowCreate((v) => !v)}
            >
              {showCreate ? '- Cancel' : '+ New Task'}
            </button>
            <button className="close-btn" onClick={onClose}>x</button>
          </div>
        </div>

        {showCreate && (
          <form className="kanban-create-form" onSubmit={handleCreate}>
            <input
              className="kanban-create-input"
              placeholder="Task title..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
              required
            />
            <textarea
              className="kanban-create-input kanban-create-desc"
              placeholder="Description (optional)..."
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              rows={2}
            />
            <div className="kanban-create-actions">
              <span className="kanban-create-hint">
                PM will auto-assign to agents
              </span>
              <button type="submit" className="kanban-create-submit" disabled={loading}>
                {loading ? '...' : 'Create'}
              </button>
            </div>
          </form>
        )}

        <div className="kanban-board">
          {COLUMNS.map((col) => (
            <div key={col.key} className="kanban-column">
              <div className="kanban-column-header" style={{ borderBottomColor: col.color }}>
                <span className="kanban-column-title">{col.label}</span>
                <span className="kanban-column-count">{grouped[col.key].length}</span>
              </div>
              <div className="kanban-column-body">
                {grouped[col.key].length === 0 ? (
                  <div className="kanban-empty">No tasks</div>
                ) : (
                  grouped[col.key].map((task) => (
                    <div
                      key={task.id}
                      className="kanban-card"
                      style={{ borderLeftColor: col.color }}
                      onClick={() => openDeliverable(task.id)}
                    >
                      <div className="kanban-card-title">{task.title}</div>
                      {task.assigned_to.length > 0 && (
                        <div className="kanban-card-agents">
                          {getAgentNames(task.assigned_to)}
                        </div>
                      )}
                      {task.subtasks.length > 0 && (
                        <div className="kanban-card-meta">
                          <span className="kanban-subtask-count">
                            {task.subtasks.filter((s) => s.status === 'done').length}/{task.subtasks.length} subtasks
                          </span>
                          {typeof task.progress === 'number' && task.progress > 0 && (
                            <div className="kanban-progress">
                              <div
                                className="kanban-progress-fill"
                                style={{ width: `${task.progress}%` }}
                              />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
