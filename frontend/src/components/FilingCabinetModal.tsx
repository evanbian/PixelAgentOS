import React, { useEffect } from 'react';
import { useStore } from '../store/useStore';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function FilingCabinetModal({ open, onClose }: Props) {
  const { tasks, agents } = useStore();

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  // Completed tasks sorted by updated_at descending
  const completedTasks = tasks
    .filter((t) => t.status === 'done')
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

  const getAgentNames = (ids: string[]) =>
    ids.map((id) => agents.find((a) => a.id === id)?.name ?? id).join(', ');

  const openDeliverable = (taskId: string) => {
    useStore.getState().setSelectedTask(taskId);
  };

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="filing-cabinet-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span>Filing Cabinet</span>
          <button className="close-btn" onClick={onClose}>x</button>
        </div>
        <div className="filing-cabinet-body">
          {completedTasks.length === 0 ? (
            <div className="filing-empty">No completed tasks yet.</div>
          ) : (
            completedTasks.map((task) => (
              <div key={task.id} className="filing-card" onClick={() => openDeliverable(task.id)}>
                <div className="filing-card-header">
                  <span className="filing-card-title">{task.title}</span>
                  <span className="filing-card-date">{formatDate(task.updated_at)}</span>
                </div>
                <div className="filing-card-meta">
                  {task.assigned_to.length > 0 && (
                    <span className="filing-card-agents">{getAgentNames(task.assigned_to)}</span>
                  )}
                  {task.subtasks.length > 0 && (
                    <span className="filing-card-subtasks">
                      {task.subtasks.length} subtask{task.subtasks.length !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                <button className="btn-small filing-view-btn">View Deliverable</button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
