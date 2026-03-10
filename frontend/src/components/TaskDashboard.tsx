import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useStore } from '../store/useStore';
import type { Task, SubTask, ActivityEvent, TaskMetrics } from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const TaskDashboard: React.FC = () => {
  const {
    tasks,
    agents,
    activityFeed,
    expandedTaskId,
    setExpandedTask,
    selectedSubtaskId,
    setSelectedSubtask,
    streamingSubtaskId,
    streamingContent,
    taskMetrics,
  } = useStore();

  const [showCreateTask, setShowCreateTask] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [executing, setExecuting] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Schedule state
  const [schedulePreset, setSchedulePreset] = useState('none');
  const [customCron, setCustomCron] = useState('');

  // PM config check
  const [pmConfigured, setPmConfigured] = useState(true);

  useEffect(() => {
    fetch(`${API_URL}/api/config/pm/status`)
      .then((r) => r.json())
      .then((d) => setPmConfigured(d.configured))
      .catch(() => {});
  }, []);

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;

    setLoading(true);
    try {
      // Resolve schedule
      const SCHEDULE_PRESETS: Record<string, string> = {
        none: '',
        hourly: '0 * * * *',
        'daily-9': '0 9 * * *',
        'weekly-mon': '0 9 * * 1',
      };
      const cronValue = schedulePreset === 'custom'
        ? customCron.trim()
        : (SCHEDULE_PRESETS[schedulePreset] || '');

      await fetch(`${API_URL}/api/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: newTitle,
          description: newDesc,
          assigned_to: [],
          schedule: cronValue || null,
        }),
      });
      setNewTitle('');
      setNewDesc('');
      setSchedulePreset('none');
      setCustomCron('');
      setShowCreateTask(false);
    } finally {
      setLoading(false);
    }
  };

  const handleExecuteTask = async (taskId: string) => {
    setExecuting(taskId);
    try {
      await fetch(`${API_URL}/api/tasks/${taskId}/execute`, { method: 'POST' });
    } finally {
      setTimeout(() => setExecuting(null), 2000);
    }
  };

  const handleDeleteTask = async (taskId: string) => {
    await fetch(`${API_URL}/api/tasks/${taskId}`, { method: 'DELETE' });
  };

  const handleCancelTask = async (taskId: string) => {
    try {
      await fetch(`${API_URL}/api/tasks/${taskId}/cancel`, { method: 'POST' });
    } catch {
      // fallback: send via WS
      const { wsSend } = useStore.getState();
      if (wsSend) wsSend('task:cancel', { task_id: taskId });
    }
  };

  const getAgentName = (id: string) =>
    agents.find((a) => a.id === id)?.name || id.slice(0, 8);

  // Find selected subtask data
  const selectedSubtask = useMemo(() => {
    if (!selectedSubtaskId) return null;
    for (const t of tasks) {
      const st = t.subtasks.find((s) => s.id === selectedSubtaskId);
      if (st) return st;
    }
    return null;
  }, [selectedSubtaskId, tasks]);

  return (
    <div className="task-dashboard">
      <div className="panel-header">
        <span>📋 Tasks</span>
        <div className="header-actions">
          <button className="btn-small" onClick={() => setShowCreateTask(!showCreateTask)}>
            + New Task
          </button>
        </div>
      </div>

      {/* Create Task Form */}
      {showCreateTask && (
        <div className="create-task-form">
          <form onSubmit={handleCreateTask}>
            <input
              className="pixel-input"
              placeholder="Task title..."
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              required
            />
            <textarea
              className="pixel-input"
              placeholder="Description..."
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              rows={2}
            />
            <div className="auto-assign-hint">
              PM will auto-assign {agents.length} available agent{agents.length !== 1 ? 's' : ''}
            </div>

            {/* Schedule Picker */}
            <div className="schedule-picker">
              <label className="schedule-label">⏰ Schedule</label>
              <select
                className="pixel-input schedule-select"
                value={schedulePreset}
                onChange={(e) => setSchedulePreset(e.target.value)}
              >
                <option value="none">One-time (no repeat)</option>
                <option value="hourly">Every hour</option>
                <option value="daily-9">Every day at 9:00</option>
                <option value="weekly-mon">Every Monday at 9:00</option>
                <option value="custom">Custom cron...</option>
              </select>
              {schedulePreset === 'custom' && (
                <input
                  className="pixel-input cron-input"
                  placeholder="e.g. 0 9 * * *"
                  value={customCron}
                  onChange={(e) => setCustomCron(e.target.value)}
                />
              )}
            </div>

            {/* PM config warning */}
            {!pmConfigured && (
              <div className="pm-warning">
                ⚠️ PM not configured. Click the PM button in the status bar to set up.
              </div>
            )}

            <div className="form-row">
              <button type="button" className="btn-secondary" onClick={() => setShowCreateTask(false)}>
                Cancel
              </button>
              <button type="submit" className="btn-primary" disabled={loading}>
                {loading ? '...' : '+ Create'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Task List + Subtask Detail split */}
      <div className="dashboard-body">
        <div className="task-list-v2">
          {tasks.length === 0 && (
            <div className="dashboard-empty">No tasks yet. Create one to get started.</div>
          )}
          {tasks.map((task) => (
            <TaskCardV2
              key={task.id}
              task={task}
              expanded={expandedTaskId === task.id}
              executing={executing === task.id}
              onExpand={() => setExpandedTask(expandedTaskId === task.id ? null : task.id)}
              onExecute={() => handleExecuteTask(task.id)}
              onDelete={() => handleDeleteTask(task.id)}
              onCancel={() => handleCancelTask(task.id)}
              getAgentName={getAgentName}
              streamingSubtaskId={streamingSubtaskId}
              streamingContent={streamingContent}
              onSelectSubtask={setSelectedSubtask}
              selectedSubtaskId={selectedSubtaskId}
              metrics={taskMetrics[task.id]}
            />
          ))}
        </div>

        {/* Subtask Detail Panel */}
        {selectedSubtask && (
          <SubtaskDetail
            subtask={selectedSubtask}
            getAgentName={getAgentName}
            onClose={() => setSelectedSubtask(null)}
          />
        )}
      </div>

      {/* Activity Feed */}
      <div className="activity-feed">
        <div className="activity-feed-header">⚡ Activity</div>
        <ActivityFeedList
          activityFeed={activityFeed}
          streamingSubtaskId={streamingSubtaskId}
          streamingContent={streamingContent}
        />
      </div>
    </div>
  );
};

/* ── Task Card V2 ───────────────────────────── */

interface TaskCardV2Props {
  task: Task;
  expanded: boolean;
  executing: boolean;
  onExpand: () => void;
  onExecute: () => void;
  onDelete: () => void;
  onCancel: () => void;
  getAgentName: (id: string) => string;
  streamingSubtaskId: string | null;
  streamingContent: string;
  onSelectSubtask: (id: string | null) => void;
  selectedSubtaskId: string | null;
  metrics?: TaskMetrics;
}

const TaskCardV2: React.FC<TaskCardV2Props> = ({
  task, expanded, executing, onExpand, onExecute, onDelete, onCancel, getAgentName,
  streamingSubtaskId, streamingContent, onSelectSubtask, selectedSubtaskId, metrics,
}) => {
  const statusClass =
    task.status === 'done' ? 'card-done'
    : task.status === 'in_progress' ? 'card-active'
    : task.status === 'cancelled' ? 'card-cancelled'
    : 'card-todo';

  return (
    <div className={`task-card-v2 ${statusClass}`}>
      <div className="card-header-v2" onClick={onExpand}>
        <span className="card-expand-icon">{expanded ? '▾' : '▸'}</span>
        {task.schedule && <span className="cron-indicator" title={`Cron: ${task.schedule}`}>🔄</span>}
        <span className="card-title-v2">{task.title}</span>
        <span className={`status-badge status-${task.status}`}>{task.status.replace('_', ' ')}</span>
      </div>

      {task.status === 'in_progress' && (
        <div className="progress-bar-v2">
          <div className="progress-fill-v2" style={{ width: `${task.progress ?? 0}%` }} />
        </div>
      )}

      {expanded && (
        <div className="card-body-v2">
          {task.description && (
            <div className="card-desc">{task.description}</div>
          )}

          {task.assigned_to.length > 0 && (
            <div className="card-agents">
              {task.assigned_to.map((id) => (
                <span key={id} className="agent-tag">{getAgentName(id)}</span>
              ))}
            </div>
          )}

          {task.schedule && (
            <div className="schedule-badge">
              <span className="schedule-icon">🔄</span>
              <span className="schedule-cron">{task.schedule}</span>
              {task.next_run_at && (
                <span className="schedule-next">
                  Next: {new Date(task.next_run_at).toLocaleString()}
                </span>
              )}
              {task.last_run_at && (
                <span className="schedule-last">
                  Last: {new Date(task.last_run_at).toLocaleString()}
                </span>
              )}
            </div>
          )}

          {/* Subtask list */}
          {task.subtasks.length > 0 && (
            <div className="subtask-list-v2">
              {task.subtasks.map((st) => (
                <SubtaskRow
                  key={st.id}
                  subtask={st}
                  isStreaming={streamingSubtaskId === st.id}
                  streamPreview={streamingSubtaskId === st.id ? streamingContent.slice(-80) : ''}
                  isSelected={selectedSubtaskId === st.id}
                  onClick={() => onSelectSubtask(selectedSubtaskId === st.id ? null : st.id)}
                  getAgentName={getAgentName}
                />
              ))}
            </div>
          )}

          {task.output && (
            <div className="task-output">
              <div className="output-label">Output:</div>
              <div className="output-text">
                {task.output.slice(0, 200)}{task.output.length > 200 ? '...' : ''}
              </div>
              <button
                className="btn-view-output"
                onClick={(e) => {
                  e.stopPropagation();
                  useStore.getState().setSelectedTask(task.id);
                }}
              >
                View Full Output
              </button>
            </div>
          )}

          {/* Execution Metrics Summary */}
          {metrics && task.status === 'done' && (
            <MetricsSummary metrics={metrics} getAgentName={getAgentName} subtasks={task.subtasks} />
          )}

          <div className="card-actions">
            {(task.status === 'todo' || task.status === 'cancelled') && (
              <button
                className="btn-run"
                disabled={executing}
                onClick={onExecute}
              >
                {executing ? '... Running' : '▶ Run'}
              </button>
            )}
            {task.status === 'in_progress' && (
              <button className="btn-cancel" onClick={onCancel}>
                ■ Cancel
              </button>
            )}
            <button className="btn-danger-sm" onClick={onDelete}>DEL</button>
          </div>
        </div>
      )}
    </div>
  );
};

/* ── Subtask Row ────────────────────────────── */

interface SubtaskRowProps {
  subtask: SubTask;
  isStreaming: boolean;
  streamPreview: string;
  isSelected: boolean;
  onClick: () => void;
  getAgentName: (id: string) => string;
}

const SubtaskRow: React.FC<SubtaskRowProps> = ({
  subtask, isStreaming, streamPreview, isSelected, onClick, getAgentName,
}) => {
  const statusIcon = subtask.status === 'done' ? '✅' : subtask.status === 'in_progress' ? '🔄' : '⬜';
  const isParallel = !subtask.depends_on || subtask.depends_on.length === 0;

  return (
    <div
      className={`subtask-row-v2 ${isSelected ? 'selected' : ''} ${isStreaming ? 'streaming' : ''}`}
      onClick={onClick}
    >
      <span className="subtask-status-icon">{statusIcon}</span>
      {isParallel && <span className="parallel-badge" title="Can run in parallel">⚡</span>}
      <span className="subtask-title-v2">{subtask.title}</span>
      {subtask.assigned_to && (
        <span className="agent-tag sm">{getAgentName(subtask.assigned_to)}</span>
      )}
      {isStreaming && (
        <span className="streaming-preview">
          {streamPreview}
          <span className="streaming-cursor" />
        </span>
      )}
    </div>
  );
};

/* ── Subtask Detail Panel ───────────────────── */

interface SubtaskDetailProps {
  subtask: SubTask;
  getAgentName: (id: string) => string;
  onClose: () => void;
}

const SubtaskDetail: React.FC<SubtaskDetailProps> = ({ subtask, getAgentName, onClose }) => {
  const { streamingSubtaskId, streamingContent } = useStore();
  const isStreaming = streamingSubtaskId === subtask.id;
  const outputRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    if (isStreaming && outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [streamingContent, isStreaming]);

  const displayContent = isStreaming ? streamingContent : (subtask.output || '');

  return (
    <div className="subtask-detail">
      <div className="subtask-detail-header">
        <span className={`status-badge status-${subtask.status}`}>{subtask.status.replace('_', ' ')}</span>
        <span className="subtask-detail-title">{subtask.title}</span>
        {subtask.assigned_to && (
          <span className="agent-tag sm">{getAgentName(subtask.assigned_to)}</span>
        )}
        <button className="close-btn" onClick={onClose}>✕</button>
      </div>
      <div className="streaming-output" ref={outputRef}>
        {displayContent || 'Waiting for output...'}
        {isStreaming && <span className="streaming-cursor" />}
      </div>
    </div>
  );
};

/* ── Metrics Summary ───────────────────────── */

const MetricsSummary: React.FC<{
  metrics: TaskMetrics;
  getAgentName: (id: string) => string;
  subtasks: SubTask[];
}> = ({ metrics }) => {
  const [expanded, setExpanded] = useState(false);

  const formatDuration = (s: number) => {
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    const rem = (s % 60).toFixed(0);
    return `${m}m ${rem}s`;
  };

  // Top tools by usage
  const topTools = Object.entries(metrics.tool_call_distribution)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);

  return (
    <div className="metrics-summary">
      <div className="metrics-header" onClick={() => setExpanded(!expanded)}>
        <span className="metrics-toggle">{expanded ? '▾' : '▸'}</span>
        <span className="metrics-label">Execution Report</span>
        <span className="metrics-quick">
          {formatDuration(metrics.total_duration_s)} · {metrics.tool_call_count} tools · {metrics.subtask_count} subtasks
        </span>
      </div>
      {expanded && (
        <div className="metrics-body">
          <div className="metrics-grid">
            <div className="metric-item">
              <span className="metric-value">{formatDuration(metrics.total_duration_s)}</span>
              <span className="metric-label">Duration</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">{metrics.subtask_count}</span>
              <span className="metric-label">Subtasks</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">{metrics.tool_call_count}</span>
              <span className="metric-label">Tool Calls</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">{metrics.reflection_count}</span>
              <span className="metric-label">Reflections</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">{metrics.self_critique_count}</span>
              <span className="metric-label">Self-Reviews</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">{metrics.rework_count}</span>
              <span className="metric-label">Reworks</span>
            </div>
            {metrics.replan_count > 0 && (
              <div className="metric-item">
                <span className="metric-value">{metrics.replan_count}</span>
                <span className="metric-label">Replans</span>
              </div>
            )}
            {metrics.llm_errors > 0 && (
              <div className="metric-item metric-warn">
                <span className="metric-value">{metrics.llm_errors}</span>
                <span className="metric-label">LLM Errors</span>
              </div>
            )}
          </div>
          {topTools.length > 0 && (
            <div className="metrics-tools">
              <div className="metrics-tools-label">Top Tools</div>
              <div className="metrics-tools-list">
                {topTools.map(([name, count]) => (
                  <span key={name} className="tool-usage-tag">
                    {name} <em>{count}</em>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

/* ── Activity Feed List (with live streaming) ── */

interface ActivityFeedListProps {
  activityFeed: ActivityEvent[];
  streamingSubtaskId: string | null;
  streamingContent: string;
}

const ActivityFeedList: React.FC<ActivityFeedListProps> = ({
  activityFeed, streamingSubtaskId, streamingContent,
}) => {
  const listRef = useRef<HTMLDivElement>(null);
  const [expandedLive, setExpandedLive] = useState(false);

  // Auto-scroll when streaming or new events
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [activityFeed.length, streamingContent]);

  return (
    <div className="activity-feed-list" ref={listRef}>
      {activityFeed.length === 0 && !streamingSubtaskId && (
        <div className="activity-empty">Waiting for activity...</div>
      )}
      {activityFeed.slice(-30).map((evt) => (
        <ActivityRow key={evt.id} event={evt} />
      ))}
      {streamingSubtaskId && (
        <div
          className={`activity-row activity-streaming-live ${expandedLive ? 'expanded' : ''}`}
          onClick={() => setExpandedLive(!expandedLive)}
        >
          <span className="activity-icon">🔴</span>
          <span className="activity-content">
            <span className="live-badge">LIVE</span>
            {expandedLive ? (
              <div className="live-full-content">
                {streamingContent}
                <span className="streaming-cursor" />
              </div>
            ) : (
              <>
                {streamingContent.slice(-120)}
                <span className="streaming-cursor" />
                {streamingContent.length > 120 && (
                  <span className="expand-hint"> click to expand</span>
                )}
              </>
            )}
          </span>
        </div>
      )}
    </div>
  );
};

/* ── Activity Row ───────────────────────────── */

const ACTIVITY_ICONS: Record<string, string> = {
  pm: '📋',
  agent: '🤖',
  system: '⚙️',
  status: '💡',
  subtask: '📌',
};

const ActivityRow: React.FC<{ event: ActivityEvent }> = ({ event }) => {
  const time = event.timestamp.toLocaleTimeString('en-US', {
    hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  return (
    <div className={`activity-row activity-${event.type}`}>
      <span className="activity-icon">{ACTIVITY_ICONS[event.type] || '•'}</span>
      <span className="activity-content">
        {event.agent_name && <strong>{event.agent_name}: </strong>}
        {event.content}
      </span>
      <span className="activity-time">{time}</span>
    </div>
  );
};
